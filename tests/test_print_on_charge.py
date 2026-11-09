"""The "Imprimir comprobante al cobrar" business setting (storage and permissions)."""

import pytest

from suitelocal.application.auth import AuthService
from suitelocal.application.business_profile import BusinessProfileService
from suitelocal.domain.auth import Session
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import CategoryRepository
from suitelocal.infrastructure.settings import BusinessSettingsRepository


@pytest.fixture
def env(tmp_path):
    database = Database(tmp_path / "print.db")
    database.initialize()
    auth = AuthService(database)
    owner = Session(auth.setup_owner("Barbería", "dueno", "Clave-segura-1", "Clave-segura-1"))
    cashier = Session(auth.create_cashier(owner, "cajero", "Clave-segura-2", "Clave-segura-2"))
    settings = BusinessSettingsRepository(database)
    service = BusinessProfileService(settings, CategoryRepository(database))
    return database, owner, cashier, settings, service


def test_printing_on_charge_is_on_by_default(env):
    _, owner, _, settings, _ = env

    assert settings.get(owner.user.business_id).print_on_charge is True


def test_the_owner_turns_it_off_and_on_and_it_persists(env):
    _, owner, _, settings, service = env

    assert service.update_profile(owner, print_on_charge=False).print_on_charge is False
    assert settings.get(owner.user.business_id).print_on_charge is False
    assert service.update_profile(owner, print_on_charge=True).print_on_charge is True


def test_other_profile_changes_leave_it_alone(env):
    _, owner, _, _, service = env
    service.update_profile(owner, print_on_charge=False)

    assert service.update_profile(owner, phone="0999999999").print_on_charge is False


def test_a_cashier_cannot_change_it(env):
    _, owner, cashier, settings, service = env

    with pytest.raises(PermissionError):
        service.update_profile(cashier, print_on_charge=False)

    assert settings.get(owner.user.business_id).print_on_charge is True


def test_an_old_database_gets_the_column_with_printing_on(env, tmp_path):
    database, owner, _, settings, _ = env
    with database.connect() as connection:
        connection.execute("ALTER TABLE business_settings DROP COLUMN print_on_charge")

    database.initialize()

    assert settings.get(owner.user.business_id).print_on_charge is True
