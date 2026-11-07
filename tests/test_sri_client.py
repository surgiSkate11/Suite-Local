import base64
import http.client
import io
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from suitelocal.domain.einvoice import SriMessage
from suitelocal.infrastructure.sri.client import (
    ENDPOINTS,
    AuthorizationResult,
    ReceptionResult,
    SriClient,
    SriUnavailable,
    UrllibTransport,
)

SOAP = Path(__file__).parent / "fixtures" / "sri" / "soap"
ACCESS_KEY = "0503202601179001234500110010010000000011234567819"
ECUADOR = timezone(timedelta(hours=-5))
SIGNED_XML = '<factura id="comprobante"><nota>áéí</nota></factura>'.encode()
RECEPTION_URL = (
    "https://celcer.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline"
)
AUTHORIZATION_URL = (
    "https://celcer.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantesOffline"
)


def fixture(name: str) -> bytes:
    return (SOAP / name).read_bytes()


class FakeTransport:
    """Records every request and answers with scripted bodies, or raises scripted errors."""

    def __init__(self, *responses: bytes | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[tuple[str, bytes]] = []

    def post(self, url: str, body: bytes) -> bytes:
        self.requests.append((url, body))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def client_with(*responses: bytes | Exception, environment: str = "pruebas"):
    transport = FakeTransport(*responses)
    return SriClient(environment, transport), transport


# -- endpoints and envelopes ----------------------------------------------------------------


def test_the_endpoints_of_each_environment_are_the_official_ones():
    assert ENDPOINTS["pruebas"].reception == RECEPTION_URL
    assert ENDPOINTS["pruebas"].authorization == AUTHORIZATION_URL
    assert (
        ENDPOINTS["produccion"].reception
        == "https://cel.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline"
    )
    assert (
        ENDPOINTS["produccion"].authorization
        == "https://cel.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantesOffline"
    )
    assert set(ENDPOINTS) == {"pruebas", "produccion"}


def test_an_unknown_environment_is_rejected():
    with pytest.raises(ValueError, match="ambiente"):
        SriClient("otro", FakeTransport())


def test_send_posts_the_base64_invoice_in_a_validarcomprobante_envelope():
    client, transport = client_with(fixture("reception_recibida.xml"))

    client.send(SIGNED_XML)

    encoded = base64.b64encode(SIGNED_XML).decode("ascii")
    assert transport.requests == [
        (
            RECEPTION_URL,
            (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
                'xmlns:ec="http://ec.gob.sri.ws.recepcion"><soapenv:Header></soapenv:Header>'
                f"<soapenv:Body><ec:validarComprobante><xml>{encoded}</xml>"
                "</ec:validarComprobante></soapenv:Body></soapenv:Envelope>"
            ).encode(),
        )
    ]


def test_authorize_posts_the_access_key_in_an_autorizacioncomprobante_envelope():
    client, transport = client_with(fixture("authorization_en_proceso.xml"))

    client.authorize(ACCESS_KEY)

    assert transport.requests == [
        (
            AUTHORIZATION_URL,
            (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
                'xmlns:ec="http://ec.gob.sri.ws.autorizacion"><soapenv:Header></soapenv:Header>'
                "<soapenv:Body><ec:autorizacionComprobante>"
                f"<claveAccesoComprobante>{ACCESS_KEY}</claveAccesoComprobante>"
                "</ec:autorizacionComprobante></soapenv:Body></soapenv:Envelope>"
            ).encode(),
        )
    ]


def test_production_uses_the_production_endpoints():
    client, transport = client_with(
        fixture("reception_recibida.xml"),
        fixture("authorization_en_proceso.xml"),
        environment="produccion",
    )

    client.send(SIGNED_XML)
    client.authorize(ACCESS_KEY)

    assert [url for url, _ in transport.requests] == [
        "https://cel.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline",
        "https://cel.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantesOffline",
    ]


@pytest.mark.parametrize("key", ["", "123", ACCESS_KEY + "0", "a" * 49])
def test_authorize_rejects_an_access_key_that_is_not_49_digits_without_calling_the_sri(key):
    client, transport = client_with()

    with pytest.raises(ValueError, match="49 dígitos"):
        client.authorize(key)

    assert transport.requests == []


# -- reception responses ----------------------------------------------------------------------


def test_a_recibida_response_is_parsed():
    client, _ = client_with(fixture("reception_recibida.xml"))

    result = client.send(SIGNED_XML)

    assert result == ReceptionResult("RECIBIDA", ())
    assert result.received is True


def test_a_devuelta_response_keeps_every_message_with_its_identifier():
    client, _ = client_with(fixture("reception_devuelta.xml"))

    result = client.send(SIGNED_XML)

    assert result.state == "DEVUELTA"
    assert result.received is False
    assert result.messages == (
        SriMessage(
            "35",
            "ARCHIVO NO CUMPLE ESTRUCTURA XML",
            "Error en la estructura del comprobante: cvc-minLength-valid",
            "ERROR",
        ),
        SriMessage("65", "FECHA EMISION EXTEMPORANEA", "", "ERROR"),
    )


def test_a_devuelta_response_exposes_the_already_registered_error():
    client, _ = client_with(fixture("reception_devuelta_43.xml"))

    result = client.send(SIGNED_XML)

    assert result.state == "DEVUELTA"
    assert result.messages == (SriMessage("43", "CLAVE ACCESO REGISTRADA", "", "ERROR"),)
    assert result.identifiers == ("43",)


# -- authorization responses ------------------------------------------------------------------


def test_an_autorizado_response_carries_number_date_and_no_messages():
    client, _ = client_with(fixture("authorization_autorizado.xml"))

    result = client.authorize(ACCESS_KEY)

    assert result == AuthorizationResult(
        "AUTORIZADO", ACCESS_KEY, datetime(2026, 3, 5, 14, 35, 10, 123000, tzinfo=ECUADOR), ()
    )
    assert result.authorized_at is not None
    assert result.authorized_at.utcoffset() == timedelta(hours=-5)


def test_a_no_autorizado_response_has_no_number_and_keeps_the_sri_messages():
    client, _ = client_with(fixture("authorization_no_autorizado.xml"))

    result = client.authorize(ACCESS_KEY)

    assert result.state == "NO AUTORIZADO"
    assert result.authorization_number is None
    assert result.authorized_at == datetime(2026, 3, 5, 14, 36, tzinfo=ECUADOR)
    assert result.messages == (
        SriMessage("39", "FIRMA INVALIDA", "La firma es inválida [Firma inválida]", "ERROR"),
    )


def test_a_response_without_authorizations_means_still_in_process():
    client, _ = client_with(fixture("authorization_en_proceso.xml"))

    result = client.authorize(ACCESS_KEY)

    assert result == AuthorizationResult("EN PROCESO", None, None, ())


# -- unusable responses ----------------------------------------------------------------------


def test_a_soap_fault_is_reported_as_unavailable_with_its_text():
    client, _ = client_with(fixture("soap_fault.xml"))

    with pytest.raises(SriUnavailable, match="Error interno del servidor"):
        client.send(SIGNED_XML)


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"<html><body>502 Bad Gateway</body></html>",
        b"no es xml",
        b'<!DOCTYPE x [<!ENTITY y "z">]><Envelope><Body/></Envelope>',
        fixture("authorization_en_proceso.xml"),
    ],
)
def test_an_unrecognised_reception_response_is_reported_as_unavailable(body):
    client, _ = client_with(body)

    with pytest.raises(SriUnavailable, match="respuesta"):
        client.send(SIGNED_XML)


def test_an_unrecognised_authorization_response_is_reported_as_unavailable():
    client, _ = client_with(fixture("reception_recibida.xml"))

    with pytest.raises(SriUnavailable, match="respuesta"):
        client.authorize(ACCESS_KEY)


def test_an_unknown_reception_state_is_reported_as_unavailable():
    body = fixture("reception_recibida.xml").replace(b"RECIBIDA", b"QUIEN SABE")
    client, _ = client_with(body)

    with pytest.raises(SriUnavailable, match="respuesta"):
        client.send(SIGNED_XML)


def test_transport_failures_propagate_as_unavailable():
    client, _ = client_with(SriUnavailable("sin red"))

    with pytest.raises(SriUnavailable, match="sin red"):
        client.send(SIGNED_XML)


def test_sri_unavailable_is_not_a_value_error_so_it_is_never_taken_for_bad_input():
    assert issubclass(SriUnavailable, Exception)
    assert not issubclass(SriUnavailable, ValueError)


# -- the urllib transport (urlopen is faked: tests never touch the network) ----------------


class FakeResponse(io.BytesIO):
    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def patch_urlopen(monkeypatch, outcome: bytes | BaseException):
    calls: list[tuple[urllib.request.Request, float]] = []

    def fake_urlopen(request: urllib.request.Request, timeout: float):
        calls.append((request, timeout))
        if isinstance(outcome, BaseException):
            raise outcome
        return FakeResponse(outcome)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return calls


def test_the_transport_posts_soap_1_1_with_a_20_second_timeout(monkeypatch):
    calls = patch_urlopen(monkeypatch, b"<respuesta/>")

    body = UrllibTransport().post(RECEPTION_URL, b"<envelope/>")

    assert body == b"<respuesta/>"
    (request, timeout), *rest = calls
    assert rest == []
    assert timeout == 20
    assert request.full_url == RECEPTION_URL
    assert request.get_method() == "POST"
    assert request.data == b"<envelope/>"
    assert request.get_header("Content-type") == "text/xml; charset=utf-8"
    assert request.get_header("Soapaction") == '""'


@pytest.mark.parametrize(
    "failure",
    [
        urllib.error.URLError("sin conexión"),
        TimeoutError("timed out"),
        ConnectionResetError("reset"),
        http.client.RemoteDisconnected("cerró"),
        urllib.error.HTTPError(RECEPTION_URL, 503, "Service Unavailable", {}, None),  # type: ignore[arg-type]
    ],
)
def test_network_failures_become_sri_unavailable(monkeypatch, failure):
    patch_urlopen(monkeypatch, failure)

    with pytest.raises(SriUnavailable, match="No se pudo comunicar con el SRI"):
        UrllibTransport().post(RECEPTION_URL, b"<envelope/>")


def test_an_oversized_response_is_refused(monkeypatch):
    patch_urlopen(monkeypatch, b"x" * (5 * 1024 * 1024 + 1))

    with pytest.raises(SriUnavailable, match="demasiado grande"):
        UrllibTransport().post(RECEPTION_URL, b"<envelope/>")
