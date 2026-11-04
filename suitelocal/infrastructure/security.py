import base64
import binascii
import hashlib
import hmac
import secrets

_ALGORITHM = "scrypt"
_SALT_BYTES = 16
_DIGEST_BYTES = 64
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise ValueError("La contraseña debe tener al menos 8 caracteres.")
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_DIGEST_BYTES,
    )
    return f"{_ALGORITHM}$" + base64.urlsafe_b64encode(salt + digest).decode("ascii")


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, encoded = stored_hash.split("$", 1)
        if algorithm != _ALGORITHM:
            return False
        decoded = base64.b64decode(encoded.encode("ascii"), altchars=b"-_", validate=True)
        if len(decoded) != _SALT_BYTES + _DIGEST_BYTES:
            return False
        salt, expected = decoded[:_SALT_BYTES], decoded[_SALT_BYTES:]
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=_SCRYPT_N,
            r=_SCRYPT_R,
            p=_SCRYPT_P,
            dklen=_DIGEST_BYTES,
        )
    except (
        AttributeError,
        binascii.Error,
        UnicodeError,
        ValueError,
        TypeError,
        OverflowError,
    ):
        return False
    return hmac.compare_digest(actual, expected)
