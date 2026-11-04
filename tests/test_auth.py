from suitelocal.application.auth import AuthService
from suitelocal.infrastructure.database import Database


def test_owner_setup_and_authentication(tmp_path):
    database = Database(tmp_path / "auth.db")
    database.initialize()
    auth = AuthService(database)

    owner = auth.setup_owner("Tienda Sol", "daniel", "clave-segura", "clave-segura")
    session = auth.authenticate("daniel", "clave-segura")

    assert owner.role == "owner"
    assert session.is_owner
    assert session.user.business_id == owner.business_id


def test_authentication_rejects_wrong_password(tmp_path):
    database = Database(tmp_path / "auth.db")
    database.initialize()
    auth = AuthService(database)
    auth.setup_owner("Tienda Sol", "daniel", "clave-segura", "clave-segura")

    try:
        auth.authenticate("daniel", "incorrecta")
    except ValueError as error:
        assert str(error) == "Usuario o contraseña incorrectos."
    else:
        raise AssertionError("La autenticación debía rechazar la contraseña.")
