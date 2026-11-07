import hashlib
import sys
from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from test_xades import make_p12

from suitelocal.infrastructure.sri.certificate_store import (
    CertificateInfo,
    CertificateStore,
    CertificateStoreError,
    DpapiProtector,
)
from suitelocal.infrastructure.sri.xades import SigningError

PASSWORD = "contraseña-secreta-123"
NO_CERTIFICATE = "No hay un certificado de firma guardado."
EXPIRED = "El certificado de firma está vencido."
CANNOT_OPEN = (
    "No se pudo abrir el certificado: la contraseña es incorrecta "
    "o el archivo no es un .p12 válido."
)
UNREADABLE = (
    "El certificado guardado no se puede abrir con este usuario de Windows. "
    "Vuelve a cargar el archivo .p12."
)


class FakeProtector:
    """A reversible stand-in for DPAPI that, like it, refuses data protected with other entropy."""

    def protect(self, data: bytes, entropy: bytes) -> bytes:
        tag = hashlib.sha256(entropy).digest()[:8]
        return b"FAKE" + tag + bytes(byte ^ 0x5A for byte in data)

    def unprotect(self, data: bytes, entropy: bytes) -> bytes:
        tag = hashlib.sha256(entropy).digest()[:8]
        if data[:4] != b"FAKE" or data[4:12] != tag:
            raise ValueError("no se puede desproteger")
        return bytes(byte ^ 0x5A for byte in data[12:])


@pytest.fixture(scope="module")
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def store(tmp_path) -> CertificateStore:
    return CertificateStore(tmp_path / "certificates" / "business-1.bin", FakeProtector())


def make_p12_with_ruc(key: rsa.RSAPrivateKey, ruc: str | None, password: bytes) -> bytes:
    attributes = [
        x509.NameAttribute(NameOID.COUNTRY_NAME, "EC"),
        x509.NameAttribute(NameOID.COMMON_NAME, "MARIA PEREZ"),
    ]
    if ruc is not None:
        attributes.append(x509.NameAttribute(NameOID.SERIAL_NUMBER, ruc))
    name = x509.Name(attributes)
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=100))
        .sign(key, hashes.SHA256())
    )
    return pkcs12.serialize_key_and_certificates(
        b"firma", key, certificate, None, serialization.BestAvailableEncryption(password)
    )


def stored_bytes(store: CertificateStore) -> bytes:
    return store.path.read_bytes()


# -- save and load -----------------------------------------------------------------------


def test_nothing_is_stored_until_a_certificate_is_saved(store):
    assert store.exists() is False
    with pytest.raises(CertificateStoreError) as error:
        store.load()
    assert str(error.value) == NO_CERTIFICATE


def test_a_saved_certificate_loads_back_with_its_password(store, rsa_key):
    p12 = make_p12(rsa_key, PASSWORD.encode())

    store.save(p12, PASSWORD)

    assert store.exists() is True
    assert store.load() == (p12, PASSWORD)


def test_the_file_never_holds_the_p12_or_the_password_in_plain(store, rsa_key):
    p12 = make_p12(rsa_key, PASSWORD.encode())

    store.save(p12, PASSWORD)

    content = stored_bytes(store)
    assert PASSWORD.encode() not in content
    assert p12 not in content
    assert p12[:64] not in content
    assert b"Firma de prueba" not in content
    assert store.path.parent.name == "certificates"


def test_the_stored_file_is_protected_with_an_entropy_salt(store, rsa_key):
    store.save(make_p12(rsa_key, b"clave"), "clave")

    other = CertificateStore(store.path, FakeProtector(), entropy=b"otra-sal")
    with pytest.raises(CertificateStoreError) as error:
        other.load()

    assert str(error.value) == UNREADABLE


def test_a_second_save_replaces_the_first(store, rsa_key):
    store.save(make_p12(rsa_key, b"uno"), "uno")
    second = make_p12(rsa_key, b"dos")

    store.save(second, "dos")

    assert store.load() == (second, "dos")


def test_a_wrong_password_is_rejected_and_nothing_is_stored(store, rsa_key):
    with pytest.raises(SigningError) as error:
        store.save(make_p12(rsa_key, b"correcta"), "incorrecta")

    assert str(error.value) == CANNOT_OPEN
    assert store.exists() is False
    assert not store.path.parent.exists() or list(store.path.parent.iterdir()) == []


def test_a_wrong_password_keeps_the_previous_certificate(store, rsa_key):
    previous = make_p12(rsa_key, b"clave")
    store.save(previous, "clave")

    with pytest.raises(SigningError):
        store.save(make_p12(rsa_key, b"correcta"), "incorrecta")

    assert store.load() == (previous, "clave")


def test_a_file_that_is_not_a_p12_is_rejected(store):
    with pytest.raises(SigningError) as error:
        store.save(b"basura", "clave")

    assert str(error.value) == CANNOT_OPEN
    assert store.exists() is False


def test_an_expired_certificate_is_rejected_and_nothing_is_stored(store, rsa_key):
    now = datetime.now(UTC)
    p12 = make_p12(
        rsa_key, b"clave", not_before=now - timedelta(days=400), not_after=now - timedelta(days=1)
    )

    with pytest.raises(SigningError) as error:
        store.save(p12, "clave")

    assert str(error.value) == EXPIRED
    assert store.exists() is False


def test_the_expiry_check_uses_the_given_moment(store, rsa_key):
    now = datetime.now(UTC)
    p12 = make_p12(rsa_key, b"clave", not_after=now + timedelta(days=10))

    with pytest.raises(SigningError) as error:
        store.save(p12, "clave", now=now + timedelta(days=11))
    assert str(error.value) == EXPIRED
    assert store.exists() is False

    store.save(p12, "clave", now=now)
    assert store.exists() is True


def test_a_certificate_with_an_empty_password_can_be_stored(store, rsa_key):
    p12 = make_p12(rsa_key, b"")

    store.save(p12, "")

    assert store.load() == (p12, "")


def test_a_corrupted_file_raises_a_spanish_error(store, rsa_key):
    store.save(make_p12(rsa_key, b"clave"), "clave")
    store.path.write_bytes(b"cualquier cosa")

    with pytest.raises(CertificateStoreError) as error:
        store.load()

    assert str(error.value) == UNREADABLE


def test_a_truncated_payload_raises_a_spanish_error(store, rsa_key):
    store.save(make_p12(rsa_key, b"clave"), "clave")
    protector = FakeProtector()
    store.path.write_bytes(protector.protect(b"\x00\x00\x00\xff abc", store.entropy))

    with pytest.raises(CertificateStoreError) as error:
        store.load()

    assert str(error.value) == UNREADABLE


# -- info ---------------------------------------------------------------------------------


def test_info_reports_subject_ruc_and_expiry_without_secrets(store, rsa_key):
    p12 = make_p12_with_ruc(rsa_key, "1790012345001", PASSWORD.encode())
    store.save(p12, PASSWORD)

    info = store.info()

    certificate = pkcs12.load_pkcs12(p12, PASSWORD.encode()).cert
    assert certificate is not None
    assert info == CertificateInfo(
        "MARIA PEREZ", "1790012345001", certificate.certificate.not_valid_after_utc
    )
    assert info.valid_until.tzinfo is UTC
    assert PASSWORD not in repr(info)
    assert set(CertificateInfo.__dataclass_fields__) == {"subject", "ruc", "valid_until"}


def test_info_without_a_ruc_in_the_certificate_has_an_empty_ruc(store, rsa_key):
    store.save(make_p12_with_ruc(rsa_key, None, b"clave"), "clave")

    assert store.info().ruc == ""


def test_info_takes_the_ruc_from_the_serial_number_even_with_other_text(store, rsa_key):
    store.save(make_p12_with_ruc(rsa_key, "RUC 0991234567001", b"clave"), "clave")

    assert store.info().ruc == "0991234567001"


def test_info_without_a_certificate_raises(store):
    with pytest.raises(CertificateStoreError) as error:
        store.info()

    assert str(error.value) == NO_CERTIFICATE


# -- clear and isolation ------------------------------------------------------------------


def test_clear_removes_the_certificate(store, rsa_key):
    store.save(make_p12(rsa_key, b"clave"), "clave")

    store.clear()

    assert store.exists() is False
    assert not store.path.exists()
    with pytest.raises(CertificateStoreError):
        store.load()


def test_clear_without_a_certificate_is_harmless(store):
    store.clear()

    assert store.exists() is False


def test_each_business_has_its_own_certificate(tmp_path, rsa_key):
    first = CertificateStore.for_business(tmp_path, 1, FakeProtector())
    second = CertificateStore.for_business(tmp_path, 2, FakeProtector())
    p12 = make_p12(rsa_key, b"clave")

    first.save(p12, "clave")

    assert first.exists() is True
    assert second.exists() is False
    assert first.path != second.path
    assert first.path.parent == tmp_path / "certificates"


def test_the_password_and_key_never_appear_in_repr_or_str(store, rsa_key):
    store.save(make_p12(rsa_key, PASSWORD.encode()), PASSWORD)

    for text in (repr(store), str(store), repr(store.info())):
        assert PASSWORD not in text
        assert "PRIVATE" not in text


# -- the real Windows DPAPI ---------------------------------------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI exists only on Windows")
def test_dpapi_round_trips_and_does_not_leave_plain_text():
    protector = DpapiProtector()
    secret = b"p12 y contrasena " + PASSWORD.encode()

    blob = protector.protect(secret, b"sal")

    assert blob != secret
    assert PASSWORD.encode() not in blob
    assert protector.unprotect(blob, b"sal") == secret


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI exists only on Windows")
def test_dpapi_refuses_a_different_entropy_and_a_corrupted_blob():
    protector = DpapiProtector()
    blob = protector.protect(b"secreto", b"sal")

    with pytest.raises(ValueError):
        protector.unprotect(blob, b"otra-sal")
    with pytest.raises(ValueError):
        protector.unprotect(b"no es un blob", b"sal")


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI exists only on Windows")
def test_the_default_store_uses_dpapi_and_round_trips(tmp_path, rsa_key):
    store = CertificateStore.for_business(tmp_path, 7)
    p12 = make_p12(rsa_key, PASSWORD.encode())

    store.save(p12, PASSWORD)

    assert PASSWORD.encode() not in stored_bytes(store)
    assert p12 not in stored_bytes(store)
    assert store.load() == (p12, PASSWORD)
    store.clear()
