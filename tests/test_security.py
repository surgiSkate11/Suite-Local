import base64

from suitelocal.infrastructure.security import hash_password, verify_password


def test_password_hash_round_trip():
    stored_hash = hash_password("clave-segura")

    assert stored_hash.startswith("scrypt$")
    assert verify_password("clave-segura", stored_hash)
    assert not verify_password("clave-incorrecta", stored_hash)


def test_hash_password_requires_minimum_length():
    try:
        hash_password("corta")
    except ValueError as error:
        assert str(error) == "La contraseña debe tener al menos 8 caracteres."
    else:
        raise AssertionError("La contraseña corta debía ser rechazada.")


def test_verify_password_rejects_malformed_hashes_without_raising():
    malformed_hashes = (
        "",
        "bcrypt$not-a-scrypt-hash",
        "scrypt$not-base64",
        "scrypt$",
        "scrypt$" + base64.urlsafe_b64encode(b"too-short").decode(),
        "scrypt$" + base64.urlsafe_b64encode(b"\x00" * 81).decode(),
    )

    for stored_hash in malformed_hashes:
        assert not verify_password("clave-segura", stored_hash)


def test_verify_password_rejects_non_string_values():
    assert not verify_password(None, "scrypt$invalid")  # type: ignore[arg-type]
    assert not verify_password("clave-segura", None)  # type: ignore[arg-type]
