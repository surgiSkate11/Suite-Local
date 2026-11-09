"""IVA by tax regime: businesses outside the SRI (or in RIMPE popular) do not charge IVA."""

import pytest
from sale_owner import owner_of

from suitelocal.application.auth import AuthService
from suitelocal.application.business_profile import BusinessProfileService
from suitelocal.application.cart import Cart
from suitelocal.application.receipts import ReceiptService
from suitelocal.application.tables import TablesService
from suitelocal.domain.auth import Session
from suitelocal.domain.business import TAX_REGIMES, charges_iva
from suitelocal.domain.models import Payment
from suitelocal.domain.tax import effective_tax_rate
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import (
    CategoryRepository,
    ProductRepository,
    SaleRepository,
)
from suitelocal.infrastructure.settings import BusinessSettingsRepository
from suitelocal.infrastructure.tables_repository import ensure_tables_schema


@pytest.fixture
def env(tmp_path):
    database = Database(tmp_path / "iva.db")
    database.initialize()
    with database.connect() as connection:
        ensure_tables_schema(connection)
    auth = AuthService(database)
    owner = Session(auth.setup_owner("Chuzos", "dueno", "Clave-segura-1", "Clave-segura-1"))
    products = ProductRepository(database)
    juice = products.add("J-1", "Jugo", 115, 20, tax_rate_basis_points=1500)
    profile = BusinessProfileService(
        BusinessSettingsRepository(database), CategoryRepository(database)
    )
    return database, owner, products, juice, profile


def stored_rate(database, product_id: int) -> int:
    with database.connect() as connection:
        return connection.execute(
            "SELECT tax_rate_basis_points FROM products WHERE id = ?", (product_id,)
        ).fetchone()[0]


def sale_rows(database, sale_id: int):
    with database.connect() as connection:
        sale = connection.execute(
            "SELECT total_cents, subtotal_cents, tax_cents FROM sales WHERE id = ?", (sale_id,)
        ).fetchone()
        items = connection.execute(
            "SELECT tax_rate_basis_points, tax_cents FROM sale_items WHERE sale_id = ?",
            (sale_id,),
        ).fetchall()
    return tuple(sale), [tuple(item) for item in items]


# -- the rule ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("regime", "expected"),
    [
        ("sin_registro", False),
        ("rimpe_popular", False),
        ("rimpe_emprendedor", True),
        ("general", True),
    ],
)
def test_only_the_regimes_outside_vat_skip_the_iva(regime, expected):
    assert charges_iva(regime) is expected


def test_every_known_regime_has_a_rule():
    assert {code for code in TAX_REGIMES if not charges_iva(code)} == {
        "sin_registro",
        "rimpe_popular",
    }


def test_the_effective_rate_is_zero_without_iva_and_the_stored_one_otherwise():
    assert effective_tax_rate(1500, charges_iva=False) == 0
    assert effective_tax_rate(500, charges_iva=False) == 0
    assert effective_tax_rate(1500, charges_iva=True) == 1500
    assert effective_tax_rate(0, charges_iva=True) == 0


# -- the cart ---------------------------------------------------------------------------


def test_cart_without_iva_keeps_the_final_price_and_has_no_iva(env):
    _, _, _, juice, _ = env
    cart = Cart(charges_iva=False)
    cart.add(juice)
    cart.add(juice)

    assert cart.total_cents == 230
    assert cart.subtotal_cents == 230
    assert cart.tax_cents == 0
    assert cart.tax_breakdown == ((0, 230, 0),)
    assert [
        (item.unit_price_cents, item.tax_rate_basis_points) for item in cart.to_sale(230).items
    ] == [(115, 0)]


def test_cart_with_iva_splits_base_and_iva_at_the_product_rate(env):
    _, _, _, juice, _ = env
    cart = Cart(charges_iva=True)
    cart.add(juice)
    cart.add(juice)

    assert (cart.total_cents, cart.subtotal_cents, cart.tax_cents) == (230, 200, 30)
    assert cart.to_sale(230).items[0].tax_rate_basis_points == 1500


def test_cart_charges_iva_by_default(env):
    _, _, _, juice, _ = env
    cart = Cart()
    cart.add(juice)

    assert cart.tax_cents == 15


def test_a_sale_without_iva_stores_rate_zero_and_leaves_the_product_rate_alone(env):
    database, owner, _, juice, _ = env
    cart = Cart(charges_iva=False)
    cart.add(juice)
    cart.add(juice)

    sale_id = SaleRepository(database).register(cart.to_sale(230), **owner_of(database))

    assert sale_rows(database, sale_id) == ((230, 230, 0), [(0, 0)])
    assert stored_rate(database, juice.id) == 1500


def test_the_same_sale_under_a_regime_that_charges_iva_is_split(env):
    database, _, _, juice, _ = env
    cart = Cart(charges_iva=True)
    cart.add(juice)
    cart.add(juice)

    sale_id = SaleRepository(database).register(cart.to_sale(230), **owner_of(database))

    assert sale_rows(database, sale_id) == ((230, 200, 30), [(1500, 30)])


def test_switching_the_regime_back_brings_the_iva_back(env):
    database, owner, _, juice, profile = env
    profile.update_profile(owner, tax_regime="general", ruc="1790012345001")
    products = ProductRepository(database)
    current = next(p for p in products.find_active("J-1"))

    cart = Cart(charges_iva=False)
    cart.add(current)
    assert cart.tax_cents == 0
    cart.charges_iva = True
    assert cart.tax_cents == 15


# -- tables -----------------------------------------------------------------------------


def charge_one_table(database, owner, juice) -> int:
    service = TablesService(database)
    table = service.create_table(owner, "Mesa 1")
    order = service.open_order(owner, table.id)
    service.add_product(owner, order.id, juice.id, 2)
    return service.charge(owner, order.id, (Payment("cash", 230),))


def test_a_table_charge_without_iva_stores_rate_zero(env):
    database, owner, _, juice, _ = env

    sale_id = charge_one_table(database, owner, juice)

    assert sale_rows(database, sale_id) == ((230, 230, 0), [(0, 0)])
    assert stored_rate(database, juice.id) == 1500


def test_a_table_charge_under_general_regime_splits_the_iva(env):
    database, owner, _, juice, profile = env
    profile.update_profile(owner, tax_regime="general", ruc="1790012345001")

    sale_id = charge_one_table(database, owner, juice)

    assert sale_rows(database, sale_id) == ((230, 200, 30), [(1500, 30)])


def test_the_table_sale_preview_follows_the_regime(env):
    database, owner, _, juice, profile = env
    service = TablesService(database)
    table = service.create_table(owner, "Mesa 1")
    order = service.add_product(owner, service.open_order(owner, table.id).id, juice.id, 2)
    payments = (Payment("cash", 230),)

    assert service.sale_for(owner, order, payments).tax_cents == 0
    profile.update_profile(owner, tax_regime="general", ruc="1790012345001")
    assert service.sale_for(owner, order, payments).tax_cents == 30


# -- the ticket -------------------------------------------------------------------------


def test_the_stored_ticket_says_whether_the_iva_applies(env):
    database, owner, _, juice, profile = env
    receipts = ReceiptService(database)
    sale_id = charge_one_table(database, owner, juice)

    assert receipts.build(owner, sale_id).charges_iva is False
    profile.update_profile(owner, tax_regime="general", ruc="1790012345001")
    assert receipts.build(owner, sale_id).charges_iva is True
