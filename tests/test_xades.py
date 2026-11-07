import base64
import re
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from lxml import etree

from suitelocal.domain.einvoice import (
    Buyer,
    InvoiceData,
    InvoiceEmission,
    InvoiceIssuer,
    InvoiceLine,
    InvoicePayment,
)
from suitelocal.infrastructure.sri.invoice_xml import build_invoice_xml, validate_against_xsd
from suitelocal.infrastructure.sri.xades import SigningError, sign_invoice, verify_invoice_signature

FIXTURES = Path(__file__).parent / "fixtures" / "sri"
DS = "http://www.w3.org/2000/09/xmldsig#"
XADES = "http://uri.etsi.org/01903/v1.3.2#"
NS = {"ds": DS, "xades": XADES}
# The values the reference signature.test.ts mocks, so its signed.xml can be reproduced exactly.
REFERENCE_TIME = datetime(2024, 4, 18, 14, 34, 32, 878000, tzinfo=timezone(timedelta(hours=-5)))
REFERENCE_UUID = "5bdfc32d-a37f-47c3-90fe-49f5a093b7bf"
EXPIRED = "El certificado de firma está vencido."


def read_text(name: str) -> str:
    # Git may convert line endings; the digests in the reference are over the LF form.
    return (FIXTURES / name).read_text(encoding="utf-8").replace("\r\n", "\n")


def read_bytes(name: str) -> bytes:
    return read_text(name).encode("utf-8")


@pytest.fixture(scope="module")
def reference_p12() -> bytes:
    return (FIXTURES / "signature.p12").read_bytes()


@pytest.fixture(scope="module")
def reference_signed() -> bytes:
    return read_bytes("signed.xml")


@pytest.fixture(scope="module")
def reference_original() -> bytes:
    return read_bytes("original.xml")


@pytest.fixture(scope="module")
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def make_p12(
    key: rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey,
    password: bytes = b"clave",
    not_before: datetime | None = None,
    not_after: datetime | None = None,
) -> bytes:
    """A self-signed test certificate and key, protected with the given password."""
    now = datetime.now(UTC)
    name = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "EC"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Prueba SA"),
            x509.NameAttribute(NameOID.COMMON_NAME, "Firma de prueba"),
        ]
    )
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before or now - timedelta(days=1))
        .not_valid_after(not_after or now + timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    encryption = (
        serialization.BestAvailableEncryption(password)
        if password
        else serialization.NoEncryption()
    )
    return pkcs12.serialize_key_and_certificates(b"firma", key, certificate, None, encryption)


def sample_invoice() -> InvoiceData:
    return InvoiceData(
        InvoiceIssuer("1790012345001", "Tienda Sol S.A.", "Av. Amazonas 123"),
        InvoiceEmission("1", "001", "001", "000000007", "12345678"),
        date(2026, 3, 5),
        Buyer("05", "1712345678", "Ana Pérez"),
        (InvoiceLine("A-1", "Arroz", 2, 230, 1500), InvoiceLine("B-2", "Leche", 3, 150, 0)),
        (InvoicePayment("cash", 380),),
    )


def outline(xml: bytes) -> list[tuple[str, tuple[tuple[str, str], ...], str | None]]:
    """Every element below ds:Signature as (path, attributes, text), minus volatile values.

    Ids hold a random UUID and the SigningTime, the signature value and the digests of the two
    signed property blocks depend on them, so those are normalised or dropped.
    """
    root = etree.fromstring(xml)
    signature = root.find("ds:Signature", NS)
    assert signature is not None
    rows = []
    for element in signature.iter():
        names = []
        node = element
        while True:
            names.append(etree.QName(node).localname)
            if node is signature:
                break
            node = node.getparent()
        path = "/".join(reversed(names))
        local = names[0]
        attributes = tuple(
            sorted(
                (name, re.sub(r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}", "<uuid>", value))
                for name, value in element.attrib.items()
            )
        )
        text: str | None = (element.text or "").strip() or None
        parent = element.getparent()
        # Only the digest of the comprobante (the first Reference) is stable across signings.
        volatile = local in {"SigningTime", "SignatureValue"} or (
            local == "DigestValue"
            and parent is not None
            and etree.QName(parent).localname == "Reference"
            and parent.getparent().findall("ds:Reference", NS).index(parent) != 0
        )
        rows.append((path, attributes, None if volatile else text))
    return rows


def comprobante_digest(xml: bytes) -> str:
    root = etree.fromstring(xml)
    digest = root.find("ds:Signature/ds:SignedInfo/ds:Reference/ds:DigestValue", NS)
    assert digest is not None and digest.text is not None
    return digest.text


def replace_once(data: bytes, old: bytes, new: bytes) -> bytes:
    assert data.count(old) == 1
    return data.replace(old, new)


# -- the verifier against the reference ----------------------------------------------------


def test_verifier_accepts_the_reference_signed_invoice(reference_signed):
    assert verify_invoice_signature(reference_signed) is True


def test_verifier_accepts_the_reference_invoice_with_crlf_line_endings():
    # Parsing normalises CRLF to LF, so a file git converted on checkout still verifies.
    raw = (FIXTURES / "signed.xml").read_bytes()
    assert verify_invoice_signature(raw.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")) is True


def test_verifier_rejects_a_changed_total_in_the_reference_invoice(reference_signed):
    tampered = replace_once(reference_signed, b"<importeTotal>44.56<", b"<importeTotal>44.57<")

    assert verify_invoice_signature(tampered) is False


def test_verifier_rejects_a_changed_signing_time(reference_signed):
    tampered = replace_once(reference_signed, b"14:34:32.878", b"14:34:32.879")

    assert verify_invoice_signature(tampered) is False


def test_verifier_rejects_a_replaced_certificate_in_key_info(reference_signed, rsa_key):
    other = make_p12(rsa_key, b"")
    other_cert = pkcs12.load_pkcs12(other, b"").cert
    assert other_cert is not None
    other_der = base64.b64encode(other_cert.certificate.public_bytes(serialization.Encoding.DER))
    root = etree.fromstring(reference_signed)
    node = root.find(".//ds:X509Certificate", NS)
    assert node is not None
    node.text = other_der.decode()

    assert verify_invoice_signature(etree.tostring(root)) is False


def test_verifier_rejects_a_corrupted_signature_value(reference_signed):
    root = etree.fromstring(reference_signed)
    node = root.find(".//ds:SignatureValue", NS)
    assert node is not None and node.text is not None
    node.text = ("A" if node.text[0] != "A" else "B") + node.text[1:]

    assert verify_invoice_signature(etree.tostring(root)) is False


@pytest.mark.parametrize("payload", [b"", b"no es xml", b"<factura/>", b"<a><b></a>"])
def test_verifier_rejects_unsigned_or_malformed_documents(payload):
    assert verify_invoice_signature(payload) is False


def test_verifier_rejects_a_document_whose_signature_was_removed(reference_signed):
    root = etree.fromstring(reference_signed)
    signature = root.find("ds:Signature", NS)
    assert signature is not None
    root.remove(signature)

    assert verify_invoice_signature(etree.tostring(root)) is False


def test_verifier_rejects_a_signature_that_references_something_other_than_the_root(
    reference_signed,
):
    tampered = replace_once(reference_signed, b'URI="#comprobante"', b'URI="#Certificate-5bdf"')

    assert verify_invoice_signature(tampered) is False


# -- signing -------------------------------------------------------------------------------


def test_signing_the_reference_invoice_produces_a_document_our_verifier_accepts(
    reference_original, reference_p12
):
    signed = sign_invoice(reference_original, reference_p12, "")

    assert verify_invoice_signature(signed) is True


def test_signing_with_the_reference_inputs_reproduces_the_reference_signed_invoice_exactly(
    reference_original, reference_p12, reference_signed
):
    ids = iter([REFERENCE_UUID] * 40)

    signed = sign_invoice(
        reference_original,
        reference_p12,
        "",
        now=REFERENCE_TIME,
        uuid_factory=lambda: next(ids),
    )

    assert signed == reference_signed


def test_signed_document_has_the_same_structure_as_the_reference(
    reference_original, reference_p12, reference_signed
):
    signed = sign_invoice(reference_original, reference_p12, "")

    assert outline(signed) == outline(reference_signed)


def test_comprobante_digest_equals_the_reference_for_the_same_input(
    reference_original, reference_p12, reference_signed
):
    signed = sign_invoice(reference_original, reference_p12, "")

    assert comprobante_digest(signed) == comprobante_digest(reference_signed)
    assert comprobante_digest(signed) == "atMB7w7TZedotqKWGtb/0eoC/1k="


def test_reference_uris_and_id_patterns_match_the_reference(reference_original, reference_p12):
    signed = sign_invoice(reference_original, reference_p12, "")

    root = etree.fromstring(signed)
    uuid_pattern = r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}"
    references = root.findall("ds:Signature/ds:SignedInfo/ds:Reference", NS)
    assert [reference.get("URI") for reference in references][0] == "#comprobante"
    assert re.fullmatch(f"#SignedProperties-{uuid_pattern}", references[1].get("URI") or "")
    assert re.fullmatch(f"#Certificate-{uuid_pattern}", references[2].get("URI") or "")
    assert re.fullmatch(f"DocumentRef-{uuid_pattern}", references[0].get("Id") or "")
    assert re.fullmatch(f"SignedPropertiesRef-{uuid_pattern}", references[1].get("Id") or "")
    assert re.fullmatch(f"CertificateRef-{uuid_pattern}", references[2].get("Id") or "")
    assert references[1].get("Type") == "http://uri.etsi.org/01903#SignedProperties"
    signature = root.find("ds:Signature", NS)
    assert signature is not None
    assert re.fullmatch(f"Signature-{uuid_pattern}", signature.get("Id") or "")
    for tag, prefix in {
        "ds:SignedInfo": "SignedInfo",
        "ds:SignatureValue": "SignatureValue",
        "ds:KeyInfo": "Certificate",
        "ds:Object": "SignatureObject",
        ".//xades:SignedProperties": "SignedProperties",
    }.items():
        node = signature.find(tag, NS)
        assert node is not None
        assert re.fullmatch(f"{prefix}-{uuid_pattern}", node.get("Id") or "")


def test_each_signing_uses_fresh_random_ids_and_a_current_signing_time(
    reference_original, reference_p12
):
    first = sign_invoice(reference_original, reference_p12, "")
    second = sign_invoice(reference_original, reference_p12, "")

    first_ids = re.findall(rb'Id="([^"]+)"', first)
    second_ids = re.findall(rb'Id="([^"]+)"', second)
    assert len(first_ids) == len(set(first_ids)) == 9
    assert not set(first_ids) & set(second_ids)
    time_text = re.search(rb"<xades:SigningTime>([^<]+)</xades:SigningTime>", first)
    assert time_text is not None
    assert re.fullmatch(
        rb"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}[+-]\d{2}:\d{2}", time_text.group(1)
    )
    signed_at = datetime.fromisoformat(time_text.group(1).decode())
    assert abs(datetime.now(UTC) - signed_at) < timedelta(minutes=1)


def test_signature_is_inserted_right_before_the_closing_root_tag(reference_original, reference_p12):
    signed = sign_invoice(reference_original, reference_p12, "")

    cut = reference_original.rfind(b"</factura>")
    assert signed.startswith(reference_original[:cut] + b"<ds:Signature ")
    assert signed.endswith(b"</ds:Signature></factura>")


def test_tampering_one_byte_of_the_signed_comprobante_fails_verification(
    reference_original, reference_p12
):
    signed = sign_invoice(reference_original, reference_p12, "")
    position = signed.index(b"<totalDescuento>3.00") + len(b"<totalDescuento>3.0")
    tampered = signed[:position] + b"1" + signed[position + 1 :]

    assert verify_invoice_signature(signed) is True
    assert len(tampered) == len(signed)
    assert verify_invoice_signature(tampered) is False


def test_a_built_invoice_signs_verifies_and_still_validates_against_the_xsd(rsa_key):
    unsigned = build_invoice_xml(sample_invoice())
    p12 = make_p12(rsa_key, b"clave")

    signed = sign_invoice(unsigned, p12, "clave")

    assert verify_invoice_signature(signed) is True
    validate_against_xsd(signed)


def test_signing_works_with_a_certificate_without_password(rsa_key):
    unsigned = build_invoice_xml(sample_invoice())

    signed = sign_invoice(unsigned, make_p12(rsa_key, b""), "")

    assert verify_invoice_signature(signed) is True


def test_signature_carries_the_certificate_digest_issuer_and_serial(rsa_key):
    unsigned = build_invoice_xml(sample_invoice())
    p12 = make_p12(rsa_key, b"clave")
    loaded = pkcs12.load_pkcs12(p12, b"clave")
    assert loaded.cert is not None
    certificate = loaded.cert.certificate

    root = etree.fromstring(sign_invoice(unsigned, p12, "clave"))

    digest = hashes.Hash(hashes.SHA1())
    digest.update(certificate.public_bytes(serialization.Encoding.DER))
    assert (
        root.findtext(".//xades:CertDigest/ds:DigestValue", namespaces=NS)
        == base64.b64encode(digest.finalize()).decode()
    )
    # Most specific attribute first, like the SRI sample: CN, O, C.
    assert (
        root.findtext(".//xades:IssuerSerial/ds:X509IssuerName", namespaces=NS)
        == "CN=Firma de prueba,O=Prueba SA,C=EC"
    )
    assert root.findtext(".//xades:IssuerSerial/ds:X509SerialNumber", namespaces=NS) == str(
        certificate.serial_number
    )
    assert (
        root.findtext(".//ds:X509Certificate", namespaces=NS)
        == base64.b64encode(certificate.public_bytes(serialization.Encoding.DER)).decode()
    )
    numbers = rsa_key.public_key().public_numbers()
    modulus = root.findtext(".//ds:RSAKeyValue/ds:Modulus", namespaces=NS)
    exponent = root.findtext(".//ds:RSAKeyValue/ds:Exponent", namespaces=NS)
    assert modulus is not None and exponent is not None
    assert int.from_bytes(base64.b64decode(modulus), "big") == numbers.n
    assert int.from_bytes(base64.b64decode(exponent), "big") == numbers.e


def test_signing_rejects_a_document_that_is_already_signed(reference_p12, reference_signed):
    with pytest.raises(SigningError) as error:
        sign_invoice(reference_signed, reference_p12, "")

    assert str(error.value) == "La factura ya está firmada."


@pytest.mark.parametrize(
    "xml",
    [
        b"no es xml",
        b"<notaCredito id='comprobante'></notaCredito>",
        b'<factura version="1.1.0"></factura>',
    ],
)
def test_signing_rejects_documents_that_are_not_an_invoice(reference_p12, xml):
    with pytest.raises(SigningError) as error:
        sign_invoice(xml, reference_p12, "")

    assert str(error.value) == "El documento no es una factura válida para firmar."


def test_signing_rejects_documents_with_a_doctype(reference_p12):
    xml = b'<!DOCTYPE factura [<!ENTITY x "y">]><factura id="comprobante">&x;</factura>'

    with pytest.raises(SigningError) as error:
        sign_invoice(xml, reference_p12, "")

    assert str(error.value) == "El documento no es una factura válida para firmar."


# -- certificates --------------------------------------------------------------------------


def test_a_wrong_password_raises_a_spanish_error(rsa_key):
    p12 = make_p12(rsa_key, b"correcta")

    with pytest.raises(SigningError) as error:
        sign_invoice(build_invoice_xml(sample_invoice()), p12, "incorrecta")

    assert str(error.value) == (
        "No se pudo abrir el certificado: la contraseña es incorrecta "
        "o el archivo no es un .p12 válido."
    )


def test_a_file_that_is_not_a_p12_raises_the_same_spanish_error():
    with pytest.raises(SigningError) as error:
        sign_invoice(build_invoice_xml(sample_invoice()), b"basura", "")

    assert "No se pudo abrir el certificado" in str(error.value)


def test_an_elliptic_curve_key_is_rejected_as_unsupported():
    p12 = make_p12(ec.generate_private_key(ec.SECP256R1()), b"clave")

    with pytest.raises(SigningError) as error:
        sign_invoice(build_invoice_xml(sample_invoice()), p12, "clave")

    assert (
        str(error.value) == "El certificado usa una clave no soportada: se necesita una clave RSA."
    )


def test_a_p12_without_certificate_or_key_is_rejected(rsa_key):
    only_key = pkcs12.serialize_key_and_certificates(
        b"firma", rsa_key, None, None, serialization.NoEncryption()
    )

    with pytest.raises(SigningError) as error:
        sign_invoice(build_invoice_xml(sample_invoice()), only_key, "")

    assert str(error.value) == "El archivo .p12 no contiene un certificado con su clave privada."


def test_an_expired_certificate_is_rejected(rsa_key):
    now = datetime.now(UTC)
    p12 = make_p12(
        rsa_key,
        b"clave",
        not_before=now - timedelta(days=400),
        not_after=now - timedelta(days=1),
    )

    with pytest.raises(SigningError) as error:
        sign_invoice(build_invoice_xml(sample_invoice()), p12, "clave")

    assert str(error.value) == EXPIRED


def test_the_validity_check_uses_the_given_signing_moment(rsa_key):
    now = datetime.now(UTC)
    p12 = make_p12(rsa_key, b"clave", not_after=now + timedelta(days=10))
    unsigned = build_invoice_xml(sample_invoice())

    with pytest.raises(SigningError) as error:
        sign_invoice(unsigned, p12, "clave", now=now + timedelta(days=11))

    assert str(error.value) == EXPIRED
    assert verify_invoice_signature(sign_invoice(unsigned, p12, "clave", now=now)) is True


def test_a_certificate_that_is_not_valid_yet_is_rejected(rsa_key):
    now = datetime.now(UTC)
    p12 = make_p12(
        rsa_key, b"clave", not_before=now + timedelta(days=2), not_after=now + timedelta(days=30)
    )

    with pytest.raises(SigningError) as error:
        sign_invoice(build_invoice_xml(sample_invoice()), p12, "clave")

    assert str(error.value) == "El certificado de firma todavía no es válido."


def test_signing_error_is_a_value_error():
    assert issubclass(SigningError, ValueError)
