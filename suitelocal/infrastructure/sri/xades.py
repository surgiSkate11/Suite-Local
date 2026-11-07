"""XAdES-BES signature of SRI invoices (enveloped, RSA-SHA1, inclusive C14N 1.0).

Ported from the MIT-licensed ec-sri-invoice-signer, which is proven against the SRI test
environment. SHA-1 and RSA-SHA1 are mandated by the SRI, not a choice made here.
"""

import base64
import hashlib
import hmac
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from xml.sax.saxutils import escape

from cryptography import x509
from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import Encoding, pkcs12

from suitelocal.infrastructure.sri._xml import XmlElement, canonicalize, local_name, parse_document

DS = "http://www.w3.org/2000/09/xmldsig#"
XADES = "http://uri.etsi.org/01903/v1.3.2#"
_NS = {"ds": DS, "xades": XADES}
_C14N = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"
_SHA1 = "http://www.w3.org/2000/09/xmldsig#sha1"
_RSA_SHA1 = "http://www.w3.org/2000/09/xmldsig#rsa-sha1"
_ENVELOPED = "http://www.w3.org/2000/09/xmldsig#enveloped-signature"
_SIGNED_PROPERTIES_TYPE = "http://uri.etsi.org/01903#SignedProperties"
_ROOT_TAG = "factura"
_ROOT_ID = "comprobante"

_CANNOT_OPEN = (
    "No se pudo abrir el certificado: la contraseña es incorrecta "
    "o el archivo no es un .p12 válido."
)
_LEGACY_CIPHER = "El certificado usa un cifrado antiguo que este equipo no puede abrir."
_UNSUPPORTED_KEY = "El certificado usa una clave no soportada: se necesita una clave RSA."
_NO_CREDENTIALS = "El archivo .p12 no contiene un certificado con su clave privada."
_KEY_MISMATCH = "El certificado del archivo .p12 no corresponde a su clave privada."
_EXPIRED = "El certificado de firma está vencido."
_NOT_YET_VALID = "El certificado de firma todavía no es válido."
_NOT_AN_INVOICE = "El documento no es una factura válida para firmar."
_ALREADY_SIGNED = "La factura ya está firmada."

# RFC 4514 keywords the SRI validator (Java X500Principal) understands; others stay dotted OIDs.
_ISSUER_KEYWORDS = {
    "2.5.4.3": "CN",
    "2.5.4.6": "C",
    "2.5.4.7": "L",
    "2.5.4.8": "ST",
    "2.5.4.9": "STREET",
    "2.5.4.10": "O",
    "2.5.4.11": "OU",
    "0.9.2342.19200300.100.1.25": "DC",
    "0.9.2342.19200300.100.1.1": "UID",
    # The validator needs EMAILADDRESS where some issuers use the short name "E".
    "1.2.840.113549.1.9.1": "EMAILADDRESS",
}
_ISSUER_SPECIAL_CHARS = ',+"\\<>;'


class SigningError(ValueError):
    """The invoice cannot be signed; the message is meant for the user."""


def _sha1_b64(data: bytes) -> str:
    return base64.b64encode(hashlib.sha1(data, usedforsecurity=False).digest()).decode("ascii")


def _issuer_name(certificate: x509.Certificate) -> str:
    """Issuer attributes, most specific first (CN ... C), as in the SRI sample."""
    parts: list[str] = []
    for attribute in reversed(list(certificate.issuer)):
        dotted = attribute.oid.dotted_string
        value = attribute.value if isinstance(attribute.value, str) else attribute.value.hex()
        value = "".join(f"\\{c}" if c in _ISSUER_SPECIAL_CHARS else c for c in value)
        parts.append(f"{_ISSUER_KEYWORDS.get(dotted, dotted)}={value}")
    return ",".join(parts)


def _can_sign(certificate: x509.Certificate) -> bool:
    try:
        usage = certificate.extensions.get_extension_for_class(x509.KeyUsage).value
    except x509.ExtensionNotFound:
        return True
    return usage.digital_signature


def _open_credentials(
    p12_bytes: bytes, password: str
) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    loaded = None
    # An empty password may be stored as "no password" or as an empty one.
    for candidate in [password.encode("utf-8")] if password else [b"", None]:
        try:
            loaded = pkcs12.load_pkcs12(p12_bytes, candidate)
            break
        except UnsupportedAlgorithm as error:
            raise SigningError(_LEGACY_CIPHER) from error
        except ValueError:
            continue
    if loaded is None:
        raise SigningError(_CANNOT_OPEN)
    key = loaded.key
    if key is None or loaded.cert is None:
        raise SigningError(_NO_CREDENTIALS)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise SigningError(_UNSUPPORTED_KEY)
    numbers = key.public_key().public_numbers()
    # Some issuers ship a signing and an encryption pair in one file: use the one that signs.
    matching: list[x509.Certificate] = []
    for item in [loaded.cert, *loaded.additional_certs]:
        public_key = item.certificate.public_key()
        if isinstance(public_key, rsa.RSAPublicKey) and public_key.public_numbers() == numbers:
            matching.append(item.certificate)
    if not matching:
        raise SigningError(_KEY_MISMATCH)
    certificate = next((item for item in matching if _can_sign(item)), matching[0])
    return key, certificate


def _aware(moment: datetime | None) -> datetime:
    """`moment` as an aware datetime; None means the computer's current time."""
    if moment is None:
        return datetime.now().astimezone()
    return moment.astimezone() if moment.tzinfo is None else moment


def _load_credentials(
    p12_bytes: bytes, password: str, moment: datetime
) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    key, certificate = _open_credentials(p12_bytes, password)
    utc_moment = moment.astimezone(UTC)
    if certificate.not_valid_after_utc < utc_moment:
        raise SigningError(_EXPIRED)
    if certificate.not_valid_before_utc > utc_moment:
        raise SigningError(_NOT_YET_VALID)
    return key, certificate


def load_certificate(
    p12_bytes: bytes,
    password: str,
    *,
    now: datetime | None = None,
    require_valid: bool = True,
) -> x509.Certificate:
    """The signing certificate of a PKCS#12 file; raises SigningError if it cannot be used.

    With `require_valid` the certificate must be valid at `now` (default: the current time);
    without it only the file, the password and the key are checked, so an expired certificate can
    still be described.
    """
    if require_valid:
        return _load_credentials(p12_bytes, password, _aware(now))[1]
    return _open_credentials(p12_bytes, password)[1]


def _b64_int(number: int) -> str:
    return base64.b64encode(number.to_bytes((number.bit_length() + 7) // 8, "big")).decode("ascii")


def _key_info_xml(key_id: str, certificate_der: bytes, public: rsa.RSAPublicNumbers) -> str:
    return (
        f'<ds:KeyInfo Id="{key_id}">'
        "<ds:X509Data>"
        f"<ds:X509Certificate>{base64.b64encode(certificate_der).decode('ascii')}</ds:X509Certificate>"
        "</ds:X509Data>"
        "<ds:KeyValue><ds:RSAKeyValue>"
        f"<ds:Modulus>{_b64_int(public.n)}</ds:Modulus>"
        f"<ds:Exponent>{_b64_int(public.e)}</ds:Exponent>"
        "</ds:RSAKeyValue></ds:KeyValue>"
        "</ds:KeyInfo>"
    )


def _signed_properties_xml(
    properties_id: str,
    document_ref_id: str,
    signing_time: str,
    certificate_digest: str,
    issuer_name: str,
    serial_number: int,
) -> str:
    return (
        f'<xades:SignedProperties Id="{properties_id}">'
        "<xades:SignedSignatureProperties>"
        f"<xades:SigningTime>{signing_time}</xades:SigningTime>"
        "<xades:SigningCertificate><xades:Cert>"
        f'<xades:CertDigest><ds:DigestMethod Algorithm="{_SHA1}"/>'
        f"<ds:DigestValue>{certificate_digest}</ds:DigestValue></xades:CertDigest>"
        "<xades:IssuerSerial>"
        f"<ds:X509IssuerName>{escape(issuer_name)}</ds:X509IssuerName>"
        f"<ds:X509SerialNumber>{serial_number}</ds:X509SerialNumber>"
        "</xades:IssuerSerial>"
        "</xades:Cert></xades:SigningCertificate>"
        "</xades:SignedSignatureProperties>"
        "<xades:SignedDataObjectProperties>"
        f'<xades:DataObjectFormat ObjectReference="#{document_ref_id}">'
        "<xades:Description>Firma digital</xades:Description>"
        "<xades:MimeType>text/xml</xades:MimeType>"
        "<xades:Encoding>UTF-8</xades:Encoding>"
        "</xades:DataObjectFormat>"
        "</xades:SignedDataObjectProperties>"
        "</xades:SignedProperties>"
    )


class _Ids:
    """The nine random Ids of a signature, drawn in the same order as the reference signer."""

    def __init__(self, new_id: Callable[[], str]) -> None:
        self.document_ref = f"DocumentRef-{new_id()}"
        self.key_info = f"Certificate-{new_id()}"
        self.key_info_ref = f"CertificateRef-{new_id()}"
        self.signed_info = f"SignedInfo-{new_id()}"
        self.properties_ref = f"SignedPropertiesRef-{new_id()}"
        self.properties = f"SignedProperties-{new_id()}"
        self.signature = f"Signature-{new_id()}"
        self.object = f"SignatureObject-{new_id()}"
        self.signature_value = f"SignatureValue-{new_id()}"


def _signed_info_xml(
    ids: _Ids, document_digest: str, properties_digest: str, key_info_digest: str
) -> str:
    return (
        f'<ds:SignedInfo Id="{ids.signed_info}">'
        f'<ds:CanonicalizationMethod Algorithm="{_C14N}"/>'
        f'<ds:SignatureMethod Algorithm="{_RSA_SHA1}"/>'
        f'<ds:Reference Id="{ids.document_ref}" URI="#{_ROOT_ID}">'
        f'<ds:Transforms><ds:Transform Algorithm="{_ENVELOPED}"/></ds:Transforms>'
        f'<ds:DigestMethod Algorithm="{_SHA1}"/>'
        f"<ds:DigestValue>{document_digest}</ds:DigestValue>"
        "</ds:Reference>"
        f'<ds:Reference Id="{ids.properties_ref}" Type="{_SIGNED_PROPERTIES_TYPE}" '
        f'URI="#{ids.properties}">'
        f'<ds:DigestMethod Algorithm="{_SHA1}"/>'
        f"<ds:DigestValue>{properties_digest}</ds:DigestValue>"
        "</ds:Reference>"
        f'<ds:Reference Id="{ids.key_info_ref}" URI="#{ids.key_info}">'
        f'<ds:DigestMethod Algorithm="{_SHA1}"/>'
        f"<ds:DigestValue>{key_info_digest}</ds:DigestValue>"
        "</ds:Reference>"
        "</ds:SignedInfo>"
    )


def _signature_xml(
    ids: _Ids, signed_info: str, signature_value: str, key_info: str, signed_properties: str
) -> str:
    return (
        f'<ds:Signature xmlns:ds="{DS}" Id="{ids.signature}">'
        f"{signed_info}"
        f'<ds:SignatureValue Id="{ids.signature_value}">{signature_value}</ds:SignatureValue>'
        f"{key_info}"
        f'<ds:Object Id="{ids.object}">'
        f'<xades:QualifyingProperties xmlns:xades="{XADES}" Target="#{ids.signature}">'
        f"{signed_properties}"
        "</xades:QualifyingProperties>"
        "</ds:Object>"
        "</ds:Signature>"
    )


def _parsed_signature(text: str, cut: int, signature_xml: str) -> XmlElement:
    """The `ds:Signature` element once inserted into the document, to canonicalize in context."""
    root = parse_document((text[:cut] + signature_xml + text[cut:]).encode("utf-8"))
    signature = root.find("ds:Signature", _NS)
    if signature is None:
        raise SigningError(_NOT_AN_INVOICE)
    return signature


def _child(parent: XmlElement, path: str) -> XmlElement:
    found = parent.find(path, _NS)
    if found is None:
        raise SigningError(_NOT_AN_INVOICE)
    return found


def sign_invoice(
    xml_bytes: bytes,
    p12_bytes: bytes,
    password: str,
    *,
    now: datetime | None = None,
    uuid_factory: Callable[[], str] | None = None,
) -> bytes:
    """Sign an unsigned factura with the key in a PKCS#12 file; raises SigningError if it cannot.

    `now` and `uuid_factory` exist so tests can reproduce a signature exactly; the validity of
    the certificate is checked at `now`.
    """
    moment = _aware(now)
    new_id = uuid_factory or (lambda: str(uuid.uuid4()))
    key, certificate = _load_credentials(p12_bytes, password, moment)

    try:
        text = xml_bytes.decode("utf-8")
        root = parse_document(xml_bytes)
    except ValueError as error:  # UnicodeDecodeError is a ValueError too
        raise SigningError(_NOT_AN_INVOICE) from error
    cut = text.rfind(f"</{_ROOT_TAG}>")
    if root.tag != _ROOT_TAG or root.get("id") != _ROOT_ID or cut < 0:
        raise SigningError(_NOT_AN_INVOICE)
    if any(True for _ in root.iter(f"{{{DS}}}Signature")):
        raise SigningError(_ALREADY_SIGNED)

    ids = _Ids(new_id)
    certificate_der = certificate.public_bytes(Encoding.DER)
    key_info = _key_info_xml(ids.key_info, certificate_der, key.public_key().public_numbers())
    signed_properties = _signed_properties_xml(
        ids.properties,
        ids.document_ref,
        moment.isoformat(timespec="milliseconds"),
        _sha1_b64(certificate_der),
        _issuer_name(certificate),
        certificate.serial_number,
    )
    document_digest = _sha1_b64(canonicalize(root))

    # The digests of SignedProperties and KeyInfo do not depend on SignedInfo, so measure them
    # on a draft signature, canonicalized in the context of the document like a verifier does.
    draft = _parsed_signature(text, cut, _signature_xml(ids, "", "", key_info, signed_properties))
    properties_digest = _sha1_b64(canonicalize(_child(draft, ".//xades:SignedProperties")))
    key_info_digest = _sha1_b64(canonicalize(_child(draft, "ds:KeyInfo")))

    signed_info = _signed_info_xml(ids, document_digest, properties_digest, key_info_digest)
    unsigned_signature = _parsed_signature(
        text, cut, _signature_xml(ids, signed_info, "", key_info, signed_properties)
    )
    canonical_signed_info = canonicalize(_child(unsigned_signature, "ds:SignedInfo"))
    signature_value = base64.b64encode(
        key.sign(canonical_signed_info, padding.PKCS1v15(), hashes.SHA1())
    ).decode("ascii")

    final = _signature_xml(ids, signed_info, signature_value, key_info, signed_properties)
    return (text[:cut] + final + text[cut:]).encode("utf-8")


# -- verification --------------------------------------------------------------------------


def _strip_signature(root: XmlElement, signature: XmlElement) -> None:
    """The enveloped-signature transform: drop the signature but keep the text around it."""
    tail = signature.tail
    previous = signature.getprevious()
    root.remove(signature)
    if tail:
        if previous is not None:
            previous.tail = (previous.tail or "") + tail
        else:
            root.text = (root.text or "") + tail


def _find_by_id(root: XmlElement, wanted: str) -> XmlElement | None:
    matches = [item for item in root.iter("*") if wanted in (item.get("Id"), item.get("id"))]
    return matches[0] if len(matches) == 1 else None


def _algorithm(parent: XmlElement, path: str) -> str | None:
    node = parent.find(path, _NS)
    return None if node is None else node.get("Algorithm")


def _transforms_ok(reference: XmlElement, *, enveloped: bool) -> bool:
    transforms = reference.find("ds:Transforms", _NS)
    if not enveloped:
        return transforms is None
    if transforms is None:
        return False
    algorithms = [item.get("Algorithm") for item in transforms.findall("ds:Transform", _NS)]
    return algorithms == [_ENVELOPED]


def _references_hold(signed_xml: bytes, root: XmlElement, signature: XmlElement) -> bool:
    signed_info = signature.find("ds:SignedInfo", _NS)
    key_info = signature.find("ds:KeyInfo", _NS)
    if signed_info is None or key_info is None:
        return False
    if _algorithm(signed_info, "ds:CanonicalizationMethod") != _C14N:
        return False
    if _algorithm(signed_info, "ds:SignatureMethod") != _RSA_SHA1:
        return False
    references = signed_info.findall("ds:Reference", _NS)
    if len(references) != 3:
        return False
    inside = list(signature.iter("*"))
    roles: set[str] = set()
    for reference in references:
        uri = reference.get("URI") or ""
        digest_node = reference.find("ds:DigestValue", _NS)
        if not uri.startswith("#") or digest_node is None or digest_node.text is None:
            return False
        if _algorithm(reference, "ds:DigestMethod") != _SHA1:
            return False
        target = _find_by_id(root, uri[1:])
        if target is None:
            return False
        if target is root:
            role = "document"
            unsigned = parse_document(signed_xml)
            unsigned_signature = unsigned.find("ds:Signature", _NS)
            if unsigned_signature is None:
                return False
            _strip_signature(unsigned, unsigned_signature)
            measured = canonicalize(unsigned)
        else:
            if not any(target is item for item in inside):
                return False
            if local_name(target) == "SignedProperties" and target.tag.startswith(f"{{{XADES}}}"):
                role = "properties"
            elif target.tag == f"{{{DS}}}KeyInfo" and target is key_info:
                role = "key_info"
            else:
                return False
            measured = canonicalize(target)
        if not _transforms_ok(reference, enveloped=role == "document"):
            return False
        expected = digest_node.text.strip().encode("ascii")
        if not hmac.compare_digest(_sha1_b64(measured).encode("ascii"), expected):
            return False
        roles.add(role)
    return roles == {"document", "properties", "key_info"}


def _signature_holds(signature: XmlElement) -> bool:
    signed_info = signature.find("ds:SignedInfo", _NS)
    value_node = signature.find("ds:SignatureValue", _NS)
    cert_node = signature.find("ds:KeyInfo/ds:X509Data/ds:X509Certificate", _NS)
    digest_node = signature.find(
        ".//xades:SigningCertificate/xades:Cert/xades:CertDigest/ds:DigestValue", _NS
    )
    if signed_info is None or value_node is None or cert_node is None or digest_node is None:
        return False
    if value_node.text is None or cert_node.text is None or digest_node.text is None:
        return False
    certificate_der = base64.b64decode("".join(cert_node.text.split()), validate=True)
    expected_digest = digest_node.text.strip().encode("ascii")
    if not hmac.compare_digest(_sha1_b64(certificate_der).encode("ascii"), expected_digest):
        return False
    public_key = x509.load_der_x509_certificate(certificate_der).public_key()
    if not isinstance(public_key, rsa.RSAPublicKey):
        return False
    value = base64.b64decode("".join(value_node.text.split()), validate=True)
    public_key.verify(value, canonicalize(signed_info), padding.PKCS1v15(), hashes.SHA1())
    return True


def verify_invoice_signature(signed_bytes: bytes) -> bool:
    """Recompute the three digests and check the RSA signature; False for anything unsound."""
    try:
        root = parse_document(signed_bytes)
        signatures = root.findall("ds:Signature", _NS)
        if root.tag != _ROOT_TAG or len(signatures) != 1:
            return False
        signature = signatures[0]
        return _references_hold(signed_bytes, root, signature) and _signature_holds(signature)
    except (ValueError, InvalidSignature, UnsupportedAlgorithm):
        return False
