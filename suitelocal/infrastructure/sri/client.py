"""SOAP 1.1 client of the SRI offline web services (reception and authorization).

Endpoints and envelopes follow the reference implementation proven against the SRI test service.
The transport is injectable, so everything above it can be tested without a network.
"""

import base64
import http.client
import re
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from suitelocal.domain.einvoice import SriMessage
from suitelocal.infrastructure.sri._xml import XmlElement, parse_document

CONNECT_READ_TIMEOUT_SECONDS = 20
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
RECEIVED_STATE = "RECIBIDA"
RETURNED_STATE = "DEVUELTA"
AUTHORIZED_STATE = "AUTORIZADO"
NOT_AUTHORIZED_STATE = "NO AUTORIZADO"
IN_PROCESS_STATE = "EN PROCESO"

_SOAP_ENVELOPE_NS = "http://schemas.xmlsoap.org/soap/envelope/"
_RECEPTION_NS = "http://ec.gob.sri.ws.recepcion"
_AUTHORIZATION_NS = "http://ec.gob.sri.ws.autorizacion"
_ACCESS_KEY = re.compile(r"[0-9]{49}")
_UNRECOGNISED = "El SRI envió una respuesta que no se reconoce."


@dataclass(frozen=True, slots=True)
class SriEndpoints:
    reception: str
    authorization: str


ENDPOINTS = {
    "pruebas": SriEndpoints(
        "https://celcer.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline",
        "https://celcer.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantesOffline",
    ),
    "produccion": SriEndpoints(
        "https://cel.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline",
        "https://cel.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantesOffline",
    ),
}


class SriUnavailable(Exception):
    """The SRI could not be reached or did not answer usably; worth retrying later.

    Deliberately not a ValueError: it is never the user's input that is wrong.
    """


@dataclass(frozen=True, slots=True)
class ReceptionResult:
    """Answer of validarComprobante: "RECIBIDA" or "DEVUELTA", with the SRI messages."""

    state: str
    messages: tuple[SriMessage, ...]

    @property
    def received(self) -> bool:
        return self.state == RECEIVED_STATE

    @property
    def identifiers(self) -> tuple[str, ...]:
        return tuple(message.identifier for message in self.messages)


@dataclass(frozen=True, slots=True)
class AuthorizationResult:
    """Answer of autorizacionComprobante: "AUTORIZADO", "NO AUTORIZADO" or "EN PROCESO"."""

    state: str
    authorization_number: str | None
    authorized_at: datetime | None
    messages: tuple[SriMessage, ...]


class Transport(Protocol):
    def post(self, url: str, body: bytes) -> bytes:
        """POST a SOAP envelope and return the response body; raises SriUnavailable."""
        ...


class UrllibTransport:
    """Plain urllib: SOAP 1.1 over HTTPS with a connect/read timeout."""

    def __init__(self, timeout: float = CONNECT_READ_TIMEOUT_SECONDS) -> None:
        self.timeout = timeout

    def post(self, url: str, body: bytes) -> bytes:
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": '""'},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data: bytes = response.read(MAX_RESPONSE_BYTES + 1)
        # URLError, HTTPError, timeouts and resets are OSErrors; the rest are protocol errors.
        except (OSError, http.client.HTTPException) as error:
            raise SriUnavailable(f"No se pudo comunicar con el SRI ({error}).") from error
        if len(data) > MAX_RESPONSE_BYTES:
            raise SriUnavailable("La respuesta del SRI es demasiado grande.")
        return data


def _envelope(namespace: str, operation: str, content: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<soapenv:Envelope xmlns:soapenv="{_SOAP_ENVELOPE_NS}" xmlns:ec="{namespace}">'
        "<soapenv:Header></soapenv:Header>"
        f"<soapenv:Body><ec:{operation}>{content}</ec:{operation}></soapenv:Body>"
        "</soapenv:Envelope>"
    ).encode()


def _text(parent: XmlElement, tag: str) -> str:
    node = parent.find(f".//{{*}}{tag}")
    return "" if node is None or node.text is None else node.text.strip()


def _messages(parent: XmlElement) -> tuple[SriMessage, ...]:
    # <mensaje> is both the wrapper entry and a field inside it: only the direct children of
    # <mensajes> are entries.
    return tuple(
        SriMessage(
            _text(entry, "identificador"),
            _text(entry, "mensaje"),
            _text(entry, "informacionAdicional"),
            _text(entry, "tipo"),
        )
        for entry in parent.findall(".//{*}mensajes/{*}mensaje")
    )


def _parse_response(body: bytes) -> XmlElement:
    try:
        root = parse_document(body)
    except ValueError as error:
        raise SriUnavailable(_UNRECOGNISED) from error
    fault = root.find(".//{*}Fault")
    if fault is not None:
        detail = _text(fault, "faultstring")
        raise SriUnavailable(f"El SRI respondió con un error: {detail or 'sin detalle'}.")
    return root


def _parse_date(text: str) -> datetime | None:
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.astimezone()


class SriClient:
    """Sends signed invoices to the SRI and asks for their authorization."""

    def __init__(self, environment: str, transport: Transport | None = None) -> None:
        if environment not in ENDPOINTS:
            raise ValueError("El ambiente del SRI debe ser pruebas o producción.")
        self._endpoints = ENDPOINTS[environment]
        self._transport: Transport = transport or UrllibTransport()

    def send(self, signed_xml: bytes) -> ReceptionResult:
        """validarComprobante: hand the signed invoice to the SRI."""
        encoded = base64.b64encode(signed_xml).decode("ascii")
        envelope = _envelope(_RECEPTION_NS, "validarComprobante", f"<xml>{encoded}</xml>")
        root = _parse_response(self._transport.post(self._endpoints.reception, envelope))
        reply = root.find(".//{*}RespuestaRecepcionComprobante")
        state = "" if reply is None else _text(reply, "estado").upper()
        if reply is None or state not in (RECEIVED_STATE, RETURNED_STATE):
            raise SriUnavailable(_UNRECOGNISED)
        return ReceptionResult(state, _messages(reply))

    def authorize(self, access_key: str) -> AuthorizationResult:
        """autorizacionComprobante: ask for the verdict on an invoice that was received."""
        if not _ACCESS_KEY.fullmatch(access_key):
            raise ValueError("La clave de acceso debe tener exactamente 49 dígitos.")
        envelope = _envelope(
            _AUTHORIZATION_NS,
            "autorizacionComprobante",
            f"<claveAccesoComprobante>{access_key}</claveAccesoComprobante>",
        )
        root = _parse_response(self._transport.post(self._endpoints.authorization, envelope))
        reply = root.find(".//{*}RespuestaAutorizacionComprobante")
        if reply is None:
            raise SriUnavailable(_UNRECOGNISED)
        authorization = reply.find(".//{*}autorizaciones/{*}autorizacion")
        if authorization is None:
            # The SRI has not decided yet (or does not know the key yet).
            return AuthorizationResult(IN_PROCESS_STATE, None, None, ())
        state = _text(authorization, "estado").upper()
        if state not in (AUTHORIZED_STATE, NOT_AUTHORIZED_STATE):
            return AuthorizationResult(IN_PROCESS_STATE, None, None, _messages(authorization))
        return AuthorizationResult(
            state,
            _text(authorization, "numeroAutorizacion") or None,
            _parse_date(_text(authorization, "fechaAutorizacion")),
            _messages(authorization),
        )
