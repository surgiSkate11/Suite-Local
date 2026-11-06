import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QDialog

from suitelocal.application.auth import AuthService
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import CategoryRepository
from suitelocal.infrastructure.settings import BusinessSettingsRepository
from suitelocal.ui.login import SetupDialog

VALID_RUC = "1790012345001"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def env(qapp, tmp_path):
    database = Database(tmp_path / "login.db")
    database.initialize()
    auth = AuthService(database)
    return database, auth, SetupDialog(auth)


def combo_texts(combo) -> list[str]:
    return [combo.itemText(index) for index in range(combo.count())]


def fill(dialog: SetupDialog) -> None:
    dialog.business.setText("Café Luna")
    dialog.username.setText("dueno")
    dialog.password.setText("clave-segura")
    dialog.password_confirmation.setText("clave-segura")


def stored(database):
    return BusinessSettingsRepository(database).get(1)


def test_setup_asks_for_the_business_type_and_the_regime(env):
    _, _, dialog = env

    assert combo_texts(dialog.business_type) == [
        "Tienda",
        "Minimarket",
        "Cafetería",
        "Restaurante",
        "Ferretería",
        "Otro",
    ]
    assert combo_texts(dialog.regime) == [
        "Sin registro en el SRI",
        "RIMPE - Negocio popular",
        "RIMPE - Emprendedor",
        "Régimen general",
    ]
    assert dialog.regime.currentText() == "Sin registro en el SRI"


@pytest.mark.parametrize(
    ("regime", "asks_for_ruc"),
    [
        ("Sin registro en el SRI", False),
        ("RIMPE - Negocio popular", False),
        ("RIMPE - Emprendedor", True),
        ("Régimen general", True),
    ],
)
def test_the_ruc_is_asked_only_for_the_regimes_that_require_it(env, regime, asks_for_ruc):
    _, _, dialog = env

    dialog.regime.setCurrentText(regime)

    assert dialog.ruc.isHidden() is not asks_for_ruc
    assert dialog.ruc_label.isHidden() is not asks_for_ruc


def test_the_default_setup_stores_the_unregistered_regime_without_a_ruc(env):
    database, auth, dialog = env
    fill(dialog)

    dialog.create_owner()

    assert dialog.result() == QDialog.DialogCode.Accepted
    saved = stored(database)
    assert (saved.name, saved.tax_regime, saved.ruc, saved.business_type) == (
        "Café Luna",
        "sin_registro",
        "",
        "otro",
    )
    assert auth.has_users()


def test_the_chosen_type_is_stored_and_its_template_applied(env):
    database, _, dialog = env
    fill(dialog)
    dialog.business_type.setCurrentText("Cafetería")

    dialog.create_owner()

    saved = stored(database)
    assert saved.business_type == "cafeteria"
    assert saved.enabled_modules == {"mesas", "categorias"}
    names = [category.name for category in CategoryRepository(database).list(1)]
    assert names == ["Bebidas", "Café", "Desayunos", "Postres"]


def test_a_registered_regime_stores_the_ruc(env):
    database, _, dialog = env
    fill(dialog)
    dialog.regime.setCurrentText("RIMPE - Emprendedor")
    dialog.ruc.setText(VALID_RUC)

    dialog.create_owner()

    saved = stored(database)
    assert (saved.tax_regime, saved.ruc) == ("rimpe_emprendedor", VALID_RUC)


@pytest.mark.parametrize(
    ("ruc", "message"),
    [
        ("", "El RUC es obligatorio para este régimen tributario."),
        ("123", "El RUC debe tener exactamente 13 dígitos."),
    ],
)
def test_a_missing_or_invalid_ruc_shows_the_message_and_creates_nothing(env, ruc, message):
    database, auth, dialog = env
    fill(dialog)
    dialog.regime.setCurrentText("Régimen general")
    dialog.ruc.setText(ruc)

    dialog.create_owner()

    assert dialog.message.text() == message
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert not auth.has_users()


def test_a_ruc_typed_before_switching_to_an_unregistered_regime_is_ignored(env):
    database, _, dialog = env
    fill(dialog)
    dialog.regime.setCurrentText("Régimen general")
    dialog.ruc.setText(VALID_RUC)
    dialog.regime.setCurrentText("RIMPE - Negocio popular")

    dialog.create_owner()

    saved = stored(database)
    assert (saved.tax_regime, saved.ruc) == ("rimpe_popular", "")
