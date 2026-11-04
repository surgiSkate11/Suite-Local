import pytest

from suitelocal.application.auth import AuthService
from suitelocal.domain.auth import Session
from suitelocal.infrastructure.database import Database


def setup_auth(tmp_path):
    database = Database(tmp_path / "users.db")
    database.initialize()
    auth = AuthService(database)
    owner = auth.setup_owner("Tienda Sol", "owner", "clave-segura", "clave-segura")
    return auth, Session(owner)


def test_owner_can_create_cashier_and_cashier_can_login(tmp_path):
    auth, owner = setup_auth(tmp_path)

    cashier = auth.create_cashier(owner, "cajero", "clave-cajero", "clave-cajero")
    session = auth.authenticate("cajero", "clave-cajero")

    assert cashier.role == "cashier"
    assert session.user.business_id == owner.user.business_id


def test_user_limit_is_five_active_users(tmp_path):
    auth, owner = setup_auth(tmp_path)
    for index in range(4):
        auth.create_cashier(owner, f"cajero{index}", "clave-cajero", "clave-cajero")

    with pytest.raises(ValueError, match="5 usuarios"):
        auth.create_cashier(owner, "extra", "clave-cajero", "clave-cajero")


def test_usernames_cannot_contain_spaces_or_mismatched_passwords(tmp_path):
    auth, owner = setup_auth(tmp_path)

    with pytest.raises(ValueError, match="no puede contener espacios"):
        auth.create_cashier(owner, "cajero 1", "clave-cajero", "clave-cajero")

    with pytest.raises(ValueError, match="no coinciden"):
        auth.create_cashier(owner, "cajero1", "clave-cajero", "otra-clave")
