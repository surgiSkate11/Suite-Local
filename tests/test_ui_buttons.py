import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

from suitelocal.application.auth import AuthService
from suitelocal.domain.auth import Session
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import ProductRepository
from suitelocal.infrastructure.settings import BusinessSettingsRepository
from suitelocal.ui.components import (
    DangerButton,
    ElidedLabel,
    KeyHint,
    SegmentedControl,
)
from suitelocal.ui.inventory import InventoryWidget
from suitelocal.ui.login import LoginDialog
from suitelocal.ui.settings import SettingsWidget
from suitelocal.ui.theme.qss import build_stylesheet
from suitelocal.ui.theme.tokens import DARK_TOKENS, LIGHT_TOKENS
from suitelocal.ui.users import UsersWidget


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def database(tmp_path):
    database = Database(tmp_path / "buttons.db")
    database.initialize()
    return database


@pytest.fixture
def owner(database):
    auth = AuthService(database)
    user = auth.setup_owner("Tienda Sol", "owner", "clave-segura", "clave-segura")
    return auth, Session(user)


def variants(widget: QWidget) -> dict[str, str]:
    return {
        button.text(): str(button.property("variant") or "primary")
        for button in widget.findChildren(QPushButton)
        if button.text()
    }


def test_stylesheet_defines_button_variants():
    stylesheet = build_stylesheet()

    for variant in ("secondary", "danger", "ghost"):
        assert f'QPushButton[variant="{variant}"]' in stylesheet


def test_danger_button_sets_variant(qapp):
    assert DangerButton("Eliminar").property("variant") == "danger"


def test_inventory_drawer_has_one_primary_action(qapp, database, owner):
    _, session = owner
    inventory = InventoryWidget(ProductRepository(database), session)

    drawer = variants(inventory.drawer)

    assert drawer == {
        "Guardar producto": "primary",
        "Nuevo": "secondary",
        "Desactivar seleccionado": "danger",
    }


def test_page_level_new_buttons_are_primary_but_not_oversized(qapp, database, owner):
    auth, session = owner
    inventory = InventoryWidget(ProductRepository(database), session)
    users = UsersWidget(auth, session)

    for page, text in ((inventory, "Nuevo producto"), (users, "Nuevo cajero")):
        button = next(b for b in page.findChildren(QPushButton) if b.text() == text)
        assert button.property("variant") == "primary"
        assert button.objectName() != "primaryAction"


def test_users_drawer_has_one_primary_action(qapp, owner):
    auth, session = owner
    users = UsersWidget(auth, session)

    assert variants(users.drawer) == {"Crear cajero": "primary"}
    assert variants(users)["Desactivar seleccionado"] == "danger"


def test_settings_has_one_primary_and_restore_is_danger(qapp, database, owner):
    _, session = owner
    settings = SettingsWidget(
        BusinessSettingsRepository(database), session.user.business_id, database
    )

    found = variants(settings)

    assert found["Guardar configuración"] == "primary"
    assert found["Crear respaldo"] == "secondary"
    assert found["Restaurar respaldo"] == "danger"
    assert list(found.values()).count("primary") == 1


def test_login_uses_svg_icons_instead_of_text_glyphs(qapp, owner):
    auth, _ = owner
    dialog = LoginDialog(auth)

    texts = [label.text() for label in dialog.findChildren(QLabel)]

    assert not any("✓" in text for text in texts)
    assert "Funciona sin internet" in texts


@pytest.mark.parametrize(("cents", "expected"), [(250, "2.50"), (1999, "19.99"), (5, "0.05")])
def test_edit_drawer_shows_exact_price(qapp, database, owner, cents, expected):
    _, session = owner
    products = ProductRepository(database)
    products.add("A-1", "Arroz", cents, 10)
    inventory = InventoryWidget(products, session)

    inventory.table.selectRow(0)

    assert inventory.price.text() == expected


def test_icon_only_close_buttons_are_transparent():
    stylesheet = build_stylesheet()

    for name in ("drawerClose", "toastClose"):
        assert f"#{name} {{{{ background: transparent;".replace("{{", "{") in stylesheet


@pytest.mark.parametrize("tokens", [LIGHT_TOKENS, DARK_TOKENS], ids=["light", "dark"])
def test_champagne_button_and_segmented_track_follow_the_palette(tokens):
    stylesheet = build_stylesheet(tokens)

    champagne = stylesheet.split('QPushButton[variant="champagne"] {', 1)[1].split("}", 1)[0]
    assert tokens.champagne_100 in champagne
    assert tokens.on_champagne in champagne
    segmented = stylesheet.split("#segmented {", 1)[1].split("}", 1)[0]
    assert tokens.sunken in segmented


def test_segmented_control_selects_one_option_and_emits_the_choice(qapp):
    control = SegmentedControl(["Favoritos", "Bebidas", "Aseo"])
    chosen: list[str] = []
    control.selected.connect(chosen.append)
    buttons = {b.text(): b for b in control.findChildren(QPushButton)}
    assert control.current == "Favoritos"

    buttons["Bebidas"].click()

    assert chosen == ["Bebidas"]
    assert control.current == "Bebidas"
    assert [name for name, b in buttons.items() if b.isChecked()] == ["Bebidas"]
    control.select("Aseo")
    assert control.current == "Aseo"
    assert not buttons["Bebidas"].isChecked()


def test_segmented_control_honors_the_initial_option(qapp):
    assert SegmentedControl(["A", "B"], current="B").current == "B"
    assert SegmentedControl([]).current is None


def test_key_hint_is_a_key_cap_label(qapp):
    hint = KeyHint("F4")

    assert hint.text() == "F4"
    assert hint.property("role") == "kbd"


def test_elided_label_keeps_full_text_until_shown_then_elides_to_its_width(qapp):
    long_name = "Supermercado y distribuidora La Esperanza del Valle"
    label = ElidedLabel(long_name)
    assert label.text() == long_name

    label.resize(90, 20)
    label.show()
    qapp.processEvents()

    assert label.text().endswith("…")
    assert label.fontMetrics().horizontalAdvance(label.text()) <= 90
    assert label.toolTip() == long_name
    assert label.full_text() == long_name

    label.resize(900, 20)
    qapp.processEvents()

    assert label.text() == long_name
    assert label.toolTip() == ""
    label.close()
