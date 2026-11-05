import sqlite3

import pytest

from suitelocal.application.auth import AuthService
from suitelocal.application.cart import Cart
from suitelocal.application.inventory import InventoryService
from suitelocal.domain.auth import Session
from suitelocal.domain.models import Payment, Product, Sale, SaleError, SaleItem
from suitelocal.domain.tax import split_tax_included, tax_breakdown, validate_tax_rate
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import ProductRepository, SaleRepository
from suitelocal.infrastructure.settings import BusinessSettingsRepository


@pytest.fixture
def database(tmp_path):
    database = Database(tmp_path / "tax.db")
    database.initialize()
    return database


def product_row_count(database: Database) -> int:
    with database.connect() as connection:
        return connection.execute("SELECT COUNT(*) AS total FROM products").fetchone()["total"]


# -- pure rule ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("total", "rate", "base", "iva"),
    [
        (115, 1500, 100, 15),
        (99, 1500, 86, 13),
        (200, 0, 200, 0),
        (105, 500, 100, 5),
        (0, 1500, 0, 0),
        (1, 1500, 1, 0),
        (10, 1500, 9, 1),
    ],
)
def test_tax_is_extracted_from_the_final_price(total, rate, base, iva):
    assert split_tax_included(total, rate) == (base, iva)


@pytest.mark.parametrize("rate", [1500, 500, 0])
def test_base_plus_tax_always_equals_total(rate):
    for total in range(0, 3000):
        base, iva = split_tax_included(total, rate)
        assert base + iva == total
        assert 0 <= iva <= total


@pytest.mark.parametrize("rate", [1200, 1900, 1, 10000, -500])
def test_only_ecuadorian_rates_are_valid(rate):
    with pytest.raises(ValueError, match="IVA"):
        validate_tax_rate(rate)
    with pytest.raises(ValueError, match="IVA"):
        split_tax_included(100, rate)


@pytest.mark.parametrize("rate", [1500, 500, 0])
def test_valid_rates_are_returned_unchanged(rate):
    assert validate_tax_rate(rate) == rate


def test_breakdown_groups_by_rate_ordered_descending():
    lines = [(200, 0), (115, 1500), (105, 500), (115, 1500)]

    assert tax_breakdown(lines) == ((1500, 200, 30), (500, 100, 5), (0, 200, 0))


def test_breakdown_is_empty_without_lines():
    assert tax_breakdown([]) == ()


# -- cart ---------------------------------------------------------------------------------


def test_cart_does_not_add_tax_on_top_of_the_price():
    cart = Cart()
    cart.add(Product(1, "A-1", "Café", 115, 5, tax_rate_basis_points=1500))

    assert cart.total_cents == 115
    assert cart.grand_total_cents == 115
    assert cart.subtotal_cents == 100
    assert cart.tax_cents == 15
    assert cart.tax_breakdown == ((1500, 100, 15),)


def test_cart_rounds_the_base_half_up_per_line():
    cart = Cart()
    product = Product(1, "A-1", "Caramelo", 33, 10, tax_rate_basis_points=1500)
    for _ in range(3):
        cart.add(product)

    assert cart.lines[0].total_cents == 99
    assert cart.grand_total_cents == 99
    assert cart.subtotal_cents == 86
    assert cart.tax_cents == 13
    assert cart.tax_breakdown == ((1500, 86, 13),)


def test_mixed_cart_groups_bases_by_rate():
    cart = Cart()
    cart.add(Product(1, "A-1", "Café", 115, 5, tax_rate_basis_points=1500))
    cart.add(Product(2, "B-1", "Arroz", 200, 5, tax_rate_basis_points=0))

    assert cart.grand_total_cents == 315
    assert cart.subtotal_cents == 300
    assert cart.tax_cents == 15
    assert cart.tax_breakdown == ((1500, 100, 15), (0, 200, 0))


def test_cart_breakdown_omits_rates_without_lines_and_empty_cart_has_none():
    cart = Cart()
    assert cart.tax_breakdown == ()
    assert cart.tax_cents == 0
    assert cart.grand_total_cents == 0

    cart.add(Product(1, "A-1", "Cemento", 105, 5, tax_rate_basis_points=500))
    assert cart.tax_breakdown == ((500, 100, 5),)


def test_cart_sale_keeps_total_and_per_line_rates():
    cart = Cart()
    cart.add(Product(1, "A-1", "Café", 115, 5, tax_rate_basis_points=1500))
    cart.add(Product(2, "B-1", "Arroz", 200, 5, tax_rate_basis_points=0))

    sale = cart.to_sale(400)

    assert sale.total_cents == 315
    assert sale.subtotal_cents == 300
    assert sale.tax_cents == 15
    assert sale.change_cents == 85
    assert sale.tax_breakdown == ((1500, 100, 15), (0, 200, 0))
    assert [item.tax_rate_basis_points for item in sale.items] == [1500, 0]
    assert [item.tax_cents for item in sale.items] == [15, 0]


def test_payment_must_cover_the_price_not_price_plus_tax():
    cart = Cart()
    cart.add(Product(1, "A-1", "Café", 115, 5, tax_rate_basis_points=1500))

    assert cart.to_sale(115).change_cents == 0
    with pytest.raises(SaleError, match="menor"):
        cart.to_sale(114)


def test_sale_rejects_an_invalid_item_rate():
    with pytest.raises(SaleError, match="IVA"):
        Sale((SaleItem(1, "Café", 1, 115, tax_rate_basis_points=1200),), 115)


# -- persistence --------------------------------------------------------------------------


def test_sale_persists_totals_and_per_line_tax(database):
    products = ProductRepository(database)
    coffee = products.add("A-1", "Café", 115, 10, tax_rate_basis_points=1500)
    rice = products.add("B-1", "Arroz", 200, 10, tax_rate_basis_points=0)
    cart = Cart()
    cart.add(coffee)
    cart.add(rice)
    cart.add(rice)

    sale_id = SaleRepository(database).register(cart.to_sale((Payment("cash", 600),)))

    with database.connect() as connection:
        sale = connection.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
        items = connection.execute(
            "SELECT product_name, quantity, tax_rate_basis_points, tax_cents "
            "FROM sale_items WHERE sale_id = ? ORDER BY id",
            (sale_id,),
        ).fetchall()
    assert (sale["total_cents"], sale["subtotal_cents"], sale["tax_cents"]) == (515, 500, 15)
    assert (sale["payment_cents"], sale["change_cents"]) == (600, 85)
    assert [tuple(row) for row in items] == [("Café", 1, 1500, 15), ("Arroz", 2, 0, 0)]
    stocks = {product.code: product.stock for product in products.find_active()}
    assert stocks == {"A-1": 9, "B-1": 8}


def test_failed_sale_with_tax_leaves_stock_and_tables_untouched(database):
    products = ProductRepository(database)
    coffee = products.add("A-1", "Café", 115, 1)
    sale = Sale((SaleItem(coffee.id, coffee.name, 2, 115, 1500),), 230)

    with pytest.raises(ValueError, match="Stock insuficiente"):
        SaleRepository(database).register(sale)

    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM sales").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM sale_items").fetchone()[0] == 0
    assert products.find_active()[0].stock == 1


# -- product rate -------------------------------------------------------------------------


def test_product_rate_defaults_to_the_business_default_for_new_products(database):
    with database.connect() as connection:
        connection.execute("INSERT INTO businesses (name) VALUES ('Tienda Sol')")
        connection.execute(
            "INSERT INTO business_settings (business_id, tax_rate_basis_points) VALUES (1, 500)"
        )
    products = ProductRepository(database)

    default = products.add("A-1", "Cemento", 105, 3)
    explicit = products.add("B-1", "Arroz", 200, 3, tax_rate_basis_points=0)

    assert default.tax_rate_basis_points == 500
    assert explicit.tax_rate_basis_points == 0
    assert {p.code: p.tax_rate_basis_points for p in products.find_active()} == {
        "A-1": 500,
        "B-1": 0,
    }


def test_product_rate_defaults_to_15_percent_without_settings(database):
    product = ProductRepository(database).add("A-1", "Café", 115, 3)

    assert product.tax_rate_basis_points == 1500


@pytest.mark.parametrize("rate", [1200, 1900, -1, 10000])
def test_invalid_product_rate_is_rejected_and_leaves_products_unchanged(database, rate):
    products = ProductRepository(database)
    existing = products.add("A-1", "Café", 115, 3, tax_rate_basis_points=500)

    with pytest.raises(ValueError, match="IVA"):
        products.add("B-1", "Arroz", 200, 3, tax_rate_basis_points=rate)
    with pytest.raises(ValueError, match="IVA"):
        products.update(existing.id, "A-1", "Café", 115, 3, tax_rate_basis_points=rate)

    assert product_row_count(database) == 1
    assert products.find_active() == [existing]


def test_update_without_rate_keeps_the_current_one(database):
    products = ProductRepository(database)
    product = products.add("A-1", "Cemento", 105, 3, tax_rate_basis_points=500)

    updated = products.update(product.id, "A-1", "Cemento gris", 110, 4)

    assert updated.tax_rate_basis_points == 500
    assert products.find_active()[0].tax_rate_basis_points == 500


def test_owner_changes_the_rate_through_the_service_and_cashier_cannot(database):
    auth = AuthService(database)
    owner = Session(auth.setup_owner("Tienda Sol", "owner", "clave-segura", "clave-segura"))
    cashier = Session(auth.create_cashier(owner, "cajero", "clave-cajero", "clave-cajero"))
    inventory = InventoryService(ProductRepository(database))
    product = inventory.create_product(owner, "A-1", "Arroz", 200, 5, tax_rate_basis_points=0)

    updated = inventory.update_product(owner, product.id, "A-1", "Arroz", 200, 5, 1500)
    assert updated.tax_rate_basis_points == 1500
    with pytest.raises(PermissionError, match="Solo el dueño"):
        inventory.update_product(cashier, product.id, "A-1", "Arroz", 200, 5, 0)
    assert ProductRepository(database).find_active()[0].tax_rate_basis_points == 1500


# -- business default ---------------------------------------------------------------------


def test_new_installs_default_to_15_percent(database):
    owner = AuthService(database).setup_owner("Tienda Sol", "owner", "clave-segura", "clave-segura")

    settings = BusinessSettingsRepository(database).get(owner.business_id)

    assert settings.tax_rate_basis_points == 1500


@pytest.mark.parametrize(
    ("text", "basis_points"), [("15", 1500), ("5", 500), ("0", 0), ("15,00", 1500)]
)
def test_business_default_rate_accepts_only_ecuadorian_rates(database, text, basis_points):
    owner = AuthService(database).setup_owner("Tienda Sol", "owner", "clave-segura", "clave-segura")
    repository = BusinessSettingsRepository(database)

    repository.update(owner.business_id, "Tienda Sol", "$", 3, ("cash",), text)

    assert repository.get(owner.business_id).tax_rate_basis_points == basis_points


@pytest.mark.parametrize("text", ["12", "19,5", "14,99", "100"])
def test_business_default_rate_rejects_other_rates_and_keeps_the_old_one(database, text):
    owner = AuthService(database).setup_owner("Tienda Sol", "owner", "clave-segura", "clave-segura")
    repository = BusinessSettingsRepository(database)

    with pytest.raises(ValueError, match="IVA"):
        repository.update(owner.business_id, "Otro nombre", "$", 3, ("cash",), text)

    settings = repository.get(owner.business_id)
    assert settings.tax_rate_basis_points == 1500
    assert settings.name == "Tienda Sol"


# -- migration ----------------------------------------------------------------------------

OLD_SCHEMA = """
CREATE TABLE products (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    price_cents INTEGER NOT NULL CHECK (price_cents >= 0),
    stock INTEGER NOT NULL CHECK (stock >= 0),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);
CREATE TABLE businesses (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE business_settings (
    business_id INTEGER PRIMARY KEY REFERENCES businesses(id),
    currency_symbol TEXT NOT NULL DEFAULT '$',
    low_stock_threshold INTEGER NOT NULL DEFAULT 3,
    enabled_payment_methods TEXT NOT NULL DEFAULT 'cash,transfer',
    tax_rate_basis_points INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE sales (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    total_cents INTEGER NOT NULL,
    payment_cents INTEGER NOT NULL,
    change_cents INTEGER NOT NULL,
    subtotal_cents INTEGER NOT NULL DEFAULT 0,
    tax_cents INTEGER NOT NULL DEFAULT 0,
    tax_rate_basis_points INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE sale_items (
    id INTEGER PRIMARY KEY,
    sale_id INTEGER NOT NULL REFERENCES sales(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    product_name TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price_cents INTEGER NOT NULL
);
"""


def build_old_database(path, settings_rate: int | None) -> Database:
    connection = sqlite3.connect(path)
    connection.executescript(OLD_SCHEMA)
    connection.execute("INSERT INTO businesses (id, name) VALUES (1, 'Tienda Sol')")
    if settings_rate is not None:
        connection.execute(
            "INSERT INTO business_settings (business_id, tax_rate_basis_points) VALUES (1, ?)",
            (settings_rate,),
        )
    connection.execute(
        "INSERT INTO products (code, name, price_cents, stock) VALUES ('A-1', 'Arroz', 250, 9)"
    )
    connection.execute(
        "INSERT INTO products (code, name, price_cents, stock) VALUES ('B-1', 'Aceite', 900, 4)"
    )
    connection.execute(
        "INSERT INTO sales (id, total_cents, payment_cents, change_cents, subtotal_cents, "
        "tax_cents, tax_rate_basis_points) VALUES (1, 560, 600, 40, 500, 60, 1200)"
    )
    connection.execute(
        "INSERT INTO sale_items (sale_id, product_id, product_name, quantity, unit_price_cents) "
        "VALUES (1, 1, 'Arroz', 2, 250)"
    )
    connection.commit()
    connection.close()
    return Database(path)


def dump(database: Database) -> list[str]:
    with database.connect() as connection:
        return list(connection.iterdump())


def old_sale_rows(database: Database) -> tuple[list[tuple[object, ...]], list[tuple[object, ...]]]:
    with database.connect() as connection:
        sales = connection.execute(
            "SELECT id, total_cents, payment_cents, change_cents, subtotal_cents, tax_cents, "
            "tax_rate_basis_points FROM sales"
        ).fetchall()
        items = connection.execute(
            "SELECT sale_id, product_id, product_name, quantity, unit_price_cents FROM sale_items"
        ).fetchall()
    return [tuple(row) for row in sales], [tuple(row) for row in items]


def test_migration_gives_products_a_valid_business_rate_of_1500_when_it_was_1200(tmp_path):
    database = build_old_database(tmp_path / "old.db", settings_rate=1200)
    before = old_sale_rows(database)

    database.initialize()

    products = ProductRepository(database).find_active()
    assert {p.code: p.tax_rate_basis_points for p in products} == {"A-1": 1500, "B-1": 1500}
    assert {p.code: p.stock for p in products} == {"A-1": 9, "B-1": 4}
    assert old_sale_rows(database) == before
    with database.connect() as connection:
        item = connection.execute(
            "SELECT tax_rate_basis_points, tax_cents FROM sale_items"
        ).fetchone()
    assert tuple(item) == (None, None)
    # The old default can no longer seed new products, so it falls back to 15 %.
    assert BusinessSettingsRepository(database).get(1).tax_rate_basis_points == 1500


@pytest.mark.parametrize("rate", [500, 0])
def test_migration_keeps_a_valid_business_rate_on_existing_products(tmp_path, rate):
    database = build_old_database(tmp_path / "old.db", settings_rate=rate)

    database.initialize()

    products = ProductRepository(database).find_active()
    assert {p.tax_rate_basis_points for p in products} == {rate}
    assert BusinessSettingsRepository(database).get(1).tax_rate_basis_points == rate


def test_migration_without_settings_row_uses_15_percent(tmp_path):
    database = build_old_database(tmp_path / "old.db", settings_rate=None)

    database.initialize()

    assert {p.tax_rate_basis_points for p in ProductRepository(database).find_active()} == {1500}


def test_initialize_twice_is_a_no_op_and_never_resets_product_rates(tmp_path):
    database = build_old_database(tmp_path / "old.db", settings_rate=1200)
    database.initialize()
    products = ProductRepository(database)
    arroz = products.find_active("A-1")[0]
    products.update(arroz.id, "A-1", "Arroz", 250, 9, tax_rate_basis_points=0)
    first = dump(database)

    database.initialize()

    assert dump(database) == first
    assert products.find_active("A-1")[0].tax_rate_basis_points == 0
