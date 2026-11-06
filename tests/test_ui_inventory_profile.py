import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from suitelocal.application.auth import AuthService
from suitelocal.application.business_profile import BusinessProfileService
from suitelocal.application.categories import CategoryService
from suitelocal.domain.auth import Session
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import CategoryRepository, ProductRepository
from suitelocal.infrastructure.settings import BusinessSettingsRepository
from suitelocal.ui.inventory import InventoryWidget

HEADERS = ["Código", "Nombre", "Categoría", "Precio", "IVA", "Margen", "Stock", "Estado"]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def env(qapp, tmp_path):
    database = Database(tmp_path / "inventory-profile.db")
    database.initialize()
    auth = AuthService(database)
    owner = Session(auth.setup_owner("Tienda Sol", "owner", "clave-segura", "clave-segura"))
    cashier = Session(auth.create_cashier(owner, "cajero", "clave-cajero", "clave-cajero"))
    categories = CategoryService(CategoryRepository(database))
    profile = BusinessProfileService(
        BusinessSettingsRepository(database), CategoryRepository(database)
    )
    return database, owner, cashier, categories, profile


def build(env, session=None) -> InventoryWidget:
    database, owner, *_ = env
    return InventoryWidget(ProductRepository(database), session or owner)


def combo_texts(combo) -> list[str]:
    return [combo.itemText(index) for index in range(combo.count())]


def cells(widget: InventoryWidget, row: int) -> list[str]:
    return [widget.table.item(row, column).text() for column in range(7)]


def fill(widget: InventoryWidget, code="A-1", name="Arroz", price="2.50", stock="10") -> None:
    widget.open_new_product()
    widget.code.setText(code)
    widget.name.setText(name)
    widget.price.setText(price)
    widget.stock.setText(stock)


def test_form_offers_optional_category_cost_and_the_three_iva_rates(env):
    _, owner, _, categories, _ = env
    categories.create(owner, "Snacks")
    categories.create(owner, "Bebidas")
    inventory = build(env)

    assert combo_texts(inventory.category) == ["Sin categoría", "Bebidas", "Snacks"]
    assert inventory.category.currentText() == "Sin categoría"
    assert combo_texts(inventory.tax_rate) == ["15 %", "5 %", "0 %"]
    assert inventory.tax_rate.currentText() == "15 %"
    assert inventory.cost.text() == ""


def test_new_products_default_to_the_business_iva_rate(env):
    _, owner, _, _, profile = env
    profile.update_settings(owner, "Tienda Sol", "$", 3, ("cash",), "5")
    inventory = build(env)

    assert inventory.tax_rate.currentText() == "5 %"
    inventory.open_new_product()
    assert inventory.tax_rate.currentText() == "5 %"


def test_saving_stores_category_cost_and_rate(env):
    database, owner, _, categories, _ = env
    bebidas = categories.create(owner, "Bebidas")
    inventory = build(env)
    fill(inventory, price="1,15")
    inventory.category.setCurrentText("Bebidas")
    inventory.cost.setText("0.60")
    inventory.tax_rate.setCurrentText("5 %")

    inventory.save_product()

    stored = ProductRepository(database).find_active()[0]
    assert (stored.price_cents, stored.category_id, stored.cost_cents) == (115, bebidas.id, 60)
    assert stored.tax_rate_basis_points == 500


def test_cost_is_optional_and_category_defaults_to_none(env):
    database, *_ = env
    inventory = build(env)
    fill(inventory)

    inventory.save_product()

    stored = ProductRepository(database).find_active()[0]
    assert (stored.category_id, stored.cost_cents, stored.tax_rate_basis_points) == (
        None,
        None,
        1500,
    )


def test_editing_loads_and_updates_category_cost_and_rate(env):
    database, owner, _, categories, _ = env
    bebidas = categories.create(owner, "Bebidas")
    snacks = categories.create(owner, "Snacks")
    ProductRepository(database).add(
        "A-1", "Cola", 150, 4, category_id=bebidas.id, cost_cents=90, tax_rate_basis_points=0
    )
    inventory = build(env)

    inventory.table.selectRow(0)

    assert inventory.category.currentText() == "Bebidas"
    assert inventory.cost.text() == "0,90"
    assert inventory.price.text() == "1,50"
    assert inventory.tax_rate.currentText() == "0 %"
    inventory.category.setCurrentText("Snacks")
    inventory.cost.setText("")
    inventory.tax_rate.setCurrentText("15 %")
    inventory.save_product()
    stored = ProductRepository(database).find_active()[0]
    assert (stored.category_id, stored.cost_cents, stored.tax_rate_basis_points) == (
        snacks.id,
        None,
        1500,
    )


@pytest.mark.parametrize(
    ("cost", "message"),
    [
        ("abc", "El costo debe ser un número válido."),
        ("NaN", "El costo debe ser un número válido."),
        ("-1", "El costo no puede ser negativo."),
    ],
)
def test_invalid_cost_shows_the_message_and_saves_nothing(env, cost, message):
    database, *_ = env
    inventory = build(env)
    fill(inventory)
    inventory.cost.setText(cost)

    inventory.save_product()

    assert inventory.message.text() == message
    assert ProductRepository(database).find_active() == []


def test_table_has_category_iva_and_margin_columns(env):
    _, _, _, _, _ = env
    inventory = build(env)

    headers = [inventory.table.horizontalHeaderItem(i).text() for i in range(8)]

    assert headers == HEADERS


def test_margin_is_the_price_base_without_iva_minus_the_cost(env):
    database, owner, _, categories, _ = env
    bebidas = categories.create(owner, "Bebidas")
    products = ProductRepository(database)
    # 1.15 at 15 %: base 1.00, so margin 1.00 - 0.60 = 0.40.
    products.add(
        "A-1", "Agua", 115, 9, category_id=bebidas.id, cost_cents=60, tax_rate_basis_points=1500
    )
    # 0 % rate: the base is the whole price, margin 10.00 - 4.00 = 6.00.
    products.add("B-1", "Arroz", 1000, 9, cost_cents=400, tax_rate_basis_points=0)
    # No cost: no margin.
    products.add("C-1", "Café", 300, 9)
    # Price below cost: negative margin, base 0.87 - 1.00 = -0.13.
    products.add("D-1", "Dulce", 100, 9, cost_cents=100, tax_rate_basis_points=1500)
    inventory = build(env)

    rows = {cells(inventory, row)[0]: cells(inventory, row) for row in range(4)}

    assert rows["A-1"] == ["A-1", "Agua", "Bebidas", "$ 1,15", "15 %", "$ 0,40", "9"]
    assert rows["B-1"] == ["B-1", "Arroz", "—", "$ 10,00", "0 %", "$ 6,00", "9"]
    assert rows["C-1"] == ["C-1", "Café", "—", "$ 3,00", "15 %", "—", "9"]
    assert rows["D-1"] == ["D-1", "Dulce", "—", "$ 1,00", "15 %", "-$ 0,13", "9"]


def test_money_follows_the_business_decimal_separator_and_symbol(env):
    database, owner, _, _, profile = env
    profile.update_profile(owner, decimal_separator=".")
    ProductRepository(database).add(
        "A-1", "Cemento", 123_450, 2, cost_cents=100_000, tax_rate_basis_points=500
    )
    inventory = build(env)

    # Base of 1,234.50 at 5 % is 1,175.71 (rounded half up); margin 175.71.
    assert cells(inventory, 0)[3:6] == ["$ 1,234.50", "5 %", "$ 175.71"]
    inventory.table.selectRow(0)
    assert inventory.price.text() == "1234.50"
    assert inventory.cost.text() == "1000.00"


def test_status_badge_uses_the_business_low_stock_threshold(env):
    database, owner, _, _, profile = env
    profile.update_settings(owner, "Tienda Sol", "$", 8, ("cash",))
    products = ProductRepository(database)
    products.add("A-1", "Arroz", 100, 8)
    products.add("B-1", "Frijol", 100, 9)
    products.add("C-1", "Sal", 100, 0)
    inventory = build(env)

    states = {
        # StatusBadge draws a leading bullet before the state name.
        cells(inventory, row)[0]: inventory.table.cellWidget(row, 7).text().removeprefix("•  ")
        for row in range(3)
    }

    assert states == {"A-1": "Stock bajo", "B-1": "Activo", "C-1": "Agotado"}


def test_refresh_profile_picks_up_categories_created_later(env):
    _, owner, _, categories, profile = env
    inventory = build(env)
    assert combo_texts(inventory.category) == ["Sin categoría"]

    categories.create(owner, "Lácteos")
    profile.update_settings(owner, "Tienda Sol", "$", 3, ("cash",), "0")
    inventory.refresh_profile()

    assert combo_texts(inventory.category) == ["Sin categoría", "Lácteos"]
    assert inventory.tax_rate.currentText() == "0 %"


def test_editing_keeps_a_deactivated_category_selectable(env):
    database, owner, _, categories, _ = env
    old = categories.create(owner, "Temporada")
    ProductRepository(database).add("A-1", "Turrón", 500, 2, category_id=old.id)
    categories.set_active(owner, old.id, False)
    inventory = build(env)
    assert cells(inventory, 0)[2] == "Temporada"

    inventory.table.selectRow(0)

    assert inventory.category.currentText() == "Temporada (inactiva)"
    inventory.save_product()
    assert ProductRepository(database).find_active()[0].category_id == old.id


def test_a_cashier_cannot_save_products(env):
    database, _, cashier, *_ = env
    inventory = build(env, cashier)
    fill(inventory)

    inventory.save_product()

    assert inventory.message.text() == "Solo el dueño puede realizar esta acción."
    assert ProductRepository(database).find_active() == []
