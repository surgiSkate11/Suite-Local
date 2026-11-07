"""The business's SRI signing certificate (.p12) and its password, protected with Windows DPAPI.

Both are stored in one file under the application data directory, never in the SQLite database
and never as plain text. DPAPI ties the file to the Windows user that saved it.
"""

import ctypes
import os
import re
import struct
import sys
from ctypes import wintypes
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from cryptography import x509
from cryptography.x509.oid import NameOID

from suitelocal.infrastructure.sri.xades import load_certificate

DEFAULT_ENTROPY = b"SuiteLocal/sri-signing-certificate/v1"
CERTIFICATES_DIRECTORY = "certificates"

_NO_CERTIFICATE = "No hay un certificado de firma guardado."
_UNREADABLE = (
    "El certificado guardado no se puede abrir con este usuario de Windows. "
    "Vuelve a cargar el archivo .p12."
)
_NOT_WINDOWS = "La protección del certificado con DPAPI solo está disponible en Windows."
_DPAPI_FAILED = "Windows no pudo proteger o abrir el certificado."
# Ecuadorian RUCs have 13 digits and the main establishment ends in 001.
_RUC = re.compile(rb"(?<![0-9])[0-9]{10}001(?![0-9])")
_LENGTH = struct.Struct(">I")
_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class CertificateStoreError(ValueError):
    """The stored certificate is missing or cannot be read; the message is meant for the user."""


class Protector(Protocol):
    """Reversible protection of a secret, salted with `entropy`; DPAPI in production."""

    def protect(self, data: bytes, entropy: bytes) -> bytes: ...

    def unprotect(self, data: bytes, entropy: bytes) -> bytes: ...


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob_of(data: bytes) -> tuple[_DataBlob, "ctypes.Array[ctypes.c_char]"]:
    """A DATA_BLOB over a copy of `data`; the buffer must stay alive while the blob is used."""
    buffer = ctypes.create_string_buffer(data, len(data))
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer


class DpapiProtector:
    """Windows Data Protection API in the current user's scope, with an entropy salt."""

    def protect(self, data: bytes, entropy: bytes) -> bytes:
        return self._transform(data, entropy, protect=True)

    def unprotect(self, data: bytes, entropy: bytes) -> bytes:
        return self._transform(data, entropy, protect=False)

    @staticmethod
    def _transform(data: bytes, entropy: bytes, *, protect: bool) -> bytes:
        if sys.platform != "win32":
            raise CertificateStoreError(_NOT_WINDOWS)
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        function = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
        function.argtypes = [
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        ]
        function.restype = wintypes.BOOL
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        source, source_buffer = _blob_of(data)
        salt, salt_buffer = _blob_of(entropy)
        result = _DataBlob()
        done = function(
            ctypes.byref(source),
            None,
            ctypes.byref(salt),
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(result),
        )
        # Keep the input buffers referenced until the call has returned.
        del source_buffer, salt_buffer
        if not done:
            raise ValueError(_DPAPI_FAILED)
        try:
            return ctypes.string_at(result.pbData, result.cbData)
        finally:
            ctypes.memset(result.pbData, 0, result.cbData)
            kernel32.LocalFree(ctypes.cast(result.pbData, ctypes.c_void_p))


@dataclass(frozen=True, slots=True)
class CertificateInfo:
    """What the owner may see about the stored certificate: no key and no password."""

    subject: str
    # Empty when the certificate does not carry one.
    ruc: str
    valid_until: datetime


def _subject_name(certificate: x509.Certificate) -> str:
    common_names = certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    if common_names and isinstance(common_names[0].value, str):
        return common_names[0].value
    return certificate.subject.rfc4514_string()


def _find_ruc(certificate: x509.Certificate) -> str:
    # Issuers put the RUC in the subject's serial number or in a private extension.
    candidates: list[bytes] = []
    for attribute in certificate.subject.get_attributes_for_oid(NameOID.SERIAL_NUMBER):
        if isinstance(attribute.value, str):
            candidates.append(attribute.value.encode("utf-8"))
    for attribute in certificate.subject:
        if isinstance(attribute.value, str):
            candidates.append(attribute.value.encode("utf-8"))
    for extension in certificate.extensions:
        if isinstance(extension.value, x509.UnrecognizedExtension):
            candidates.append(extension.value.value)
    for candidate in candidates:
        found = _RUC.search(candidate)
        if found is not None:
            return found.group().decode("ascii")
    return ""


class CertificateStore:
    """One business's protected certificate file."""

    def __init__(
        self,
        path: Path,
        protector: Protector | None = None,
        *,
        entropy: bytes = DEFAULT_ENTROPY,
    ) -> None:
        self.path = path
        self.entropy = entropy
        self._protector: Protector = protector or DpapiProtector()

    @classmethod
    def for_business(
        cls, data_directory: Path, business_id: int, protector: Protector | None = None
    ) -> "CertificateStore":
        """The store of a business, under `<data_directory>/certificates/`."""
        return cls(
            data_directory / CERTIFICATES_DIRECTORY / f"business-{business_id}.bin", protector
        )

    def __repr__(self) -> str:
        return f"CertificateStore(path={str(self.path)!r})"

    def exists(self) -> bool:
        return self.path.is_file()

    def save(self, p12_bytes: bytes, password: str, *, now: datetime | None = None) -> None:
        """Check the .p12 with its password and store both; raises and stores nothing otherwise.

        Raises SigningError for a wrong password, a bad file or an expired certificate.
        """
        load_certificate(p12_bytes, password, now=now)
        secret = password.encode("utf-8")
        payload = _LENGTH.pack(len(p12_bytes)) + p12_bytes + secret
        protected = self._protector.protect(payload, self.entropy)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        try:
            temporary.write_bytes(protected)
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def load(self) -> tuple[bytes, str]:
        """The stored .p12 bytes and its password."""
        try:
            protected = self.path.read_bytes()
        except FileNotFoundError as error:
            raise CertificateStoreError(_NO_CERTIFICATE) from error
        try:
            payload = self._protector.unprotect(protected, self.entropy)
            (length,) = _LENGTH.unpack_from(payload)
            body = payload[_LENGTH.size :]
            if length > len(body):
                raise ValueError("payload truncado")
            return body[:length], body[length:].decode("utf-8")
        except (ValueError, struct.error) as error:
            raise CertificateStoreError(_UNREADABLE) from error

    def info(self) -> CertificateInfo:
        """Subject, RUC and expiry of the stored certificate, even if it has already expired."""
        p12_bytes, password = self.load()
        certificate = load_certificate(p12_bytes, password, require_valid=False)
        return CertificateInfo(
            _subject_name(certificate),
            _find_ruc(certificate),
            certificate.not_valid_after_utc.astimezone(UTC),
        )

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
