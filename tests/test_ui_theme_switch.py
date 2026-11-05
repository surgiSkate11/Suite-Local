import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from suitelocal.application.auth import AuthService
from suitelocal.domain.auth import Session
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import ProductRepository, SaleRepository
from suitelocal.infrastructure.settings import BusinessSettingsRepository
from suitelocal.ui.shell import AppShell
from suitelocal.ui.theme.effects import apply_elevation
from suitelocal.ui.theme.manager import (
    apply_saved_theme,
    current_theme,
    current_tokens,
    saved_theme,
    set_theme,
    theme_manager,
    toggle_theme,
)
from suitelocal.ui.theme.qss import build_stylesheet
from suitelocal.ui.theme.tokens import DARK_TOKENS, LIGHT_TOKENS


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_settings(qapp, tmp_path):
    """Keep the persisted theme out of the user's real settings and start every test light."""
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings")
    )
    set_theme(qapp, "light", persist=False)
    yield
    set_theme(qapp, "light", persist=False)
    QSettings.setDefaultFormat(QSettings.Format.NativeFormat)


@pytest.fixture
def shell(qapp, tmp_path):
    database = Database(tmp_path / "theme.db")
    database.initialize()
    auth = AuthService(database)
    owner = auth.setup_owner("Tienda Sol", "owner", "clave-segura", "clave-segura")
    window = AppShell(
        ProductRepository(database),
        SaleRepository(database),
        Session(owner),
        BusinessSettingsRepository(database),
        auth,
        database,
    )
    yield window
    destroy(window)


def destroy(widget: QWidget) -> None:
    """Delete now: live widgets are re-polished on every theme change, which slows the suite."""
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


def show_active(widget: QWidget) -> None:
    widget.resize(1300, 800)
    widget.show()
    widget.activateWindow()
    QTest.qWaitForWindowActive(widget)


def test_default_theme_is_light(qapp):
    assert current_theme() == "light"
    assert current_tokens() is LIGHT_TOKENS


def test_switching_to_dark_replaces_the_stylesheet_and_back_restores_it(qapp):
    set_theme(qapp, "light", persist=False)
    light_sheet = qapp.styleSheet()
    seen: list[str] = []
    theme_manager().theme_changed.connect(seen.append)

    set_theme(qapp, "dark", persist=False)

    assert current_theme() == "dark"
    assert current_tokens() is DARK_TOKENS
    assert qapp.styleSheet() == build_stylesheet(DARK_TOKENS)
    assert qapp.styleSheet() != light_sheet
    assert DARK_TOKENS.background in qapp.styleSheet()

    set_theme(qapp, "light", persist=False)

    assert qapp.styleSheet() == light_sheet
    assert seen == ["dark", "light"]
    theme_manager().theme_changed.disconnect(seen.append)


def test_unknown_theme_is_rejected_without_changing_anything(qapp):
    before = qapp.styleSheet()

    with pytest.raises(ValueError, match="Tema no registrado"):
        set_theme(qapp, "sepia", persist=False)

    assert current_theme() == "light"
    assert qapp.styleSheet() == before


def test_toggle_theme_flips_and_returns_the_new_theme(qapp):
    assert toggle_theme(qapp) == "dark"
    assert toggle_theme(qapp) == "light"


def test_choice_is_persisted_and_restored_at_startup(qapp, tmp_path):
    assert saved_theme() == "light"

    set_theme(qapp, "dark")

    assert saved_theme() == "dark"
    assert list((tmp_path / "settings").rglob("*.ini"))
    set_theme(qapp, "light", persist=False)
    assert apply_saved_theme(qapp) == "dark"
    assert current_theme() == "dark"
    assert qapp.styleSheet() == build_stylesheet(DARK_TOKENS)


def test_applying_the_saved_theme_does_not_write_it_back(qapp):
    set_theme(qapp, "dark", persist=False)

    assert saved_theme() == "light"


def test_unknown_saved_value_falls_back_to_light(qapp):
    settings = QSettings(
        QSettings.defaultFormat(), QSettings.Scope.UserScope, "SuiteLocal", "SuiteLocal"
    )
    settings.setValue("ui/theme", "neon")
    settings.sync()

    assert saved_theme() == "light"


def test_elevation_shadows_are_recolored_in_place(qapp):
    widget = QWidget()
    effect = apply_elevation(widget, "e2")
    light_color = effect.color()

    set_theme(qapp, "dark", persist=False)

    assert effect.color() != light_color
    assert effect.color().red() == effect.color().green() == effect.color().blue() == 0
    assert effect.color().alpha() > light_color.alpha()
    set_theme(qapp, "light", persist=False)
    assert effect.color() == light_color


def test_shell_toggle_button_switches_label_checked_state_and_stylesheet(qapp, shell):
    toggle = shell.theme_toggle
    assert toggle.isCheckable()
    assert (toggle.text(), toggle.isChecked()) == ("Modo oscuro", False)
    light_sheet = qapp.styleSheet()

    toggle.click()

    assert (toggle.text(), toggle.isChecked()) == ("Modo claro", True)
    assert toggle.accessibleName() == "Modo claro"
    assert current_theme() == "dark"
    assert qapp.styleSheet() == build_stylesheet(DARK_TOKENS)
    assert qapp.styleSheet() != light_sheet

    toggle.click()

    assert (toggle.text(), toggle.isChecked()) == ("Modo oscuro", False)
    assert toggle.accessibleName() == "Modo oscuro"
    assert qapp.styleSheet() == light_sheet


def test_ctrl_shift_l_toggles_the_theme(qapp, shell):
    show_active(shell)

    QTest.keySequence(shell, "Ctrl+Shift+L")
    assert current_theme() == "dark"
    assert shell.theme_toggle.isChecked()

    QTest.keySequence(shell, "Ctrl+Shift+L")
    assert current_theme() == "light"
    assert not shell.theme_toggle.isChecked()


def test_toggle_follows_theme_changes_made_elsewhere(qapp, shell):
    set_theme(qapp, "dark", persist=False)

    assert (shell.theme_toggle.text(), shell.theme_toggle.isChecked()) == ("Modo claro", True)


def test_new_shell_starts_in_the_persisted_theme(qapp, shell, tmp_path):
    shell.theme_toggle.click()
    set_theme(qapp, "light", persist=False)
    apply_saved_theme(qapp)
    database = Database(tmp_path / "second.db")
    database.initialize()
    auth = AuthService(database)
    owner = auth.setup_owner("Otra", "owner", "clave-segura", "clave-segura")

    second = AppShell(
        ProductRepository(database),
        SaleRepository(database),
        Session(owner),
        BusinessSettingsRepository(database),
        auth,
        database,
    )

    assert (second.theme_toggle.text(), second.theme_toggle.isChecked()) == ("Modo claro", True)
    destroy(second)


def test_rail_icons_are_redrawn_for_the_new_theme(qapp, shell):
    item = shell.navigation.item(1)
    assert item is not None
    light_image = item.icon().pixmap(18, 18).toImage()

    shell.theme_toggle.click()

    assert item.icon().pixmap(18, 18).toImage() != light_image
