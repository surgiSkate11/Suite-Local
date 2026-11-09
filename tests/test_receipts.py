import sqlite3
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sale_owner import owner_of

from suitelocal.application.auth import AuthService
from suitelocal.application.business_profile import BusinessProfileService
from suitelocal.application.receipts import (
    RECEIPT_LEGEND,
    Receipt,
    ReceiptLine,
    ReceiptService,
    ReceiptTax,
)
from suitelocal.domain.auth import Session, User
from suitelocal.domain.models import Payment, Sale, SaleItem
from suitelocal.infrastructure.database import SCHEMA, Database
from suitelocal.infrastructure.repositories import (
    CategoryRepository,
    ProductRepository,
    SaleRepository,
)
from suitelocal.infrastructure.settings import BusinessSettingsRepository

LEGEND = "Comprobante interno, no válido como documento tributario."
ECUADOR = timezone(timedelta(hours=-5))
NOT_FOUND = "La venta no existe en este negocio."


@pytest.fixture
def env(tmp_path):
    database = Database(tmp_path / "receipts.db")
    database.initialize()
    auth = AuthService(database)
    owner = Session(auth.setup_owner("Tienda Sol", "owner", "clave-segura", "clave-segura"))
    cashier = Session(auth.create_cashier(owner, "cajero", "clave-cajero", "clave-cajero"))
    products = ProductRepository(database)
    profile = BusinessProfileService(
        BusinessSettingsRepository(database), CategoryRepository(database)
    )
    return database, owner, cashier, products, profile


def sell_mixed(env, session=None, payments=None, note=None) -> int:
    """2 x 1,15 at 15 % (base 2,00 / IVA 0,30) and 3 x 0,50 at 0 %: total 3,80, base 3,50."""
    database, owner, _, products, _ = env
    session = session or owner
    taxed = products.add("A-1", "Arroz", 115, 50, tax_rate_basis_points=1500)
    exempt = products.add("B-2", "Leche", 50, 50, tax_rate_basis_points=0)
    sale = Sale(
        (
            SaleItem(taxed.id, taxed.name, 2, 115, 1500),
            SaleItem(exempt.id, exempt.name, 3, 50, 0),
        ),
        400,
        payments or (Payment("cash", 400),),
    )
    return SaleRepository(database).register(
        sale,
        business_id=session.user.business_id,
        user_id=session.user.id,
        sales_note_number=note,
    )


def second_business(database) -> Session:
    """The installation wizard allows one business, so the second one is inserted directly."""
    with database.connect() as connection:
        business_id = connection.execute("INSERT INTO businesses (name) VALUES ('Otra')").lastrowid
        user_id = connection.execute(
            "INSERT INTO users (business_id, username, password_hash, role) "
            "VALUES (?, 'otro', 'x', 'owner')",
            (business_id,),
        ).lastrowid
    assert business_id is not None and user_id is not None
    return Session(User(user_id, business_id, "otro", "owner", True))


def set_created_at(database, sale_id: int, utc_text: str) -> None:
    with database.connect() as connection:
        connection.execute("UPDATE sales SET created_at = ? WHERE id = ?", (utc_text, sale_id))


# -- the receipt of a stored sale ----------------------------------------------------------


def test_mixed_iva_sale_produces_the_exact_receipt(env):
    database, owner, cashier, _, profile = env
    profile.update_profile(
        owner,
        ruc="1790012345001",
        tax_regime="general",
        address="Av. Amazonas 123",
        phone="022345678",
        receipt_footer="Gracias por su compra",
    )
    sale_id = sell_mixed(env, session=cashier)
    set_created_at(database, sale_id, "2026-03-05 20:30:00")

    receipt = ReceiptService(database, ECUADOR).build(owner, sale_id)

    assert isinstance(receipt, Receipt)
    assert receipt.business.name == "Tienda Sol"
    assert receipt.business.ruc == "1790012345001"
    assert receipt.business.address == "Av. Amazonas 123"
    assert receipt.business.phone == "022345678"
    assert receipt.business.regime_label == "Régimen general"
    assert receipt.business.footer == "Gracias por su compra"
    assert receipt.number == "000001"
    assert receipt.issued_at == datetime(2026, 3, 5, 15, 30, tzinfo=ECUADOR)
    assert receipt.issued_at.utcoffset() == timedelta(hours=-5)
    assert receipt.cashier == "cajero"
    assert receipt.lines == (
        ReceiptLine("Arroz", 2, 115, 230, 1500),
        ReceiptLine("Leche", 3, 50, 150, 0),
    )
    assert receipt.subtotal_cents == 350
    assert receipt.taxes == (ReceiptTax(1500, 200, 30), ReceiptTax(0, 150, 0))
    assert receipt.total_cents == 380
    assert [(p.method, p.amount_cents, p.reference) for p in receipt.payments] == [
        ("cash", 400, "")
    ]
    assert receipt.cash_received_cents == 400
    assert receipt.change_cents == 20


def test_receipt_reads_stored_values_not_the_current_catalog(env):
    database, owner, _, products, _ = env
    sale_id = sell_mixed(env)
    for product in products.find_active(""):
        products.update(product.id, product.code, "Renombrado", 999, 5, tax_rate_basis_points=0)

    receipt = ReceiptService(database).build(owner, sale_id)

    assert [(line.name, line.unit_price_cents) for line in receipt.lines] == [
        ("Arroz", 115),
        ("Leche", 50),
    ]
    assert receipt.total_cents == 380


def test_split_payments_keep_method_reference_cash_and_change(env):
    database, owner, _, _, _ = env
    sale_id = sell_mixed(
        env,
        payments=(Payment("transfer", 200, " TR-889 "), Payment("cash", 500)),
    )

    receipt = ReceiptService(database).build(owner, sale_id)

    assert [(p.method, p.amount_cents, p.reference) for p in receipt.payments] == [
        ("transfer", 200, "TR-889"),
        ("cash", 500, ""),
    ]
    assert receipt.cash_received_cents == 500
    # 3,80 total - 2,00 transferred = 1,80 in cash; 5,00 handed over.
    assert receipt.change_cents == 320


@pytest.mark.parametrize(
    "regime", ["sin_registro", "rimpe_popular", "rimpe_emprendedor", "general"]
)
def test_every_regime_carries_the_internal_legend(env, regime):
    database, owner, _, _, profile = env
    profile.update_profile(owner, tax_regime=regime, ruc="1790012345001")
    sale_id = sell_mixed(env)

    receipt = ReceiptService(database).build(owner, sale_id)

    assert receipt.legend == LEGEND
    assert RECEIPT_LEGEND == LEGEND


def test_any_session_of_the_same_business_can_build_it(env):
    database, owner, cashier, _, _ = env
    sale_id = sell_mixed(env)

    by_cashier = ReceiptService(database).build(cashier, sale_id)

    assert by_cashier == ReceiptService(database).build(owner, sale_id)


def test_a_sale_of_another_business_is_rejected_in_spanish(env):
    database, owner, _, _, _ = env
    sale_id = sell_mixed(env)
    stranger = second_business(database)

    with pytest.raises(ValueError, match=NOT_FOUND):
        ReceiptService(database).build(stranger, sale_id)
    assert ReceiptService(database).build(owner, sale_id).number == "000001"


def test_an_unknown_sale_is_rejected_with_the_same_error(env):
    database, owner, _, _, _ = env

    with pytest.raises(ValueError, match=NOT_FOUND):
        ReceiptService(database).build(owner, 999)


def test_a_sale_without_a_business_is_never_readable(env):
    database, owner, _, products, _ = env
    product = products.add("A-1", "Arroz", 250, 10)
    sale_id = SaleRepository(database).register(
        Sale((SaleItem(product.id, product.name, 1, 250),), 250), **owner_of(database)
    )
    # register() no longer accepts it; a row from an older database can still have no business.
    with database.connect() as connection:
        connection.execute("UPDATE sales SET business_id = NULL WHERE id = ?", (sale_id,))

    with pytest.raises(ValueError, match=NOT_FOUND):
        ReceiptService(database).build(owner, sale_id)
    with pytest.raises(ValueError, match=NOT_FOUND):
        ReceiptService(database).build(second_business(database), sale_id)


def test_a_sale_before_the_iva_breakdown_has_no_receipt(env):
    database, owner, _, _, _ = env
    sale_id = sell_mixed(env)
    with database.connect() as connection:
        connection.execute("UPDATE sale_items SET tax_rate_basis_points = NULL, tax_cents = NULL")

    with pytest.raises(ValueError, match="anterior al desglose de IVA"):
        ReceiptService(database).build(owner, sale_id)


def test_the_cashier_is_empty_when_the_seller_was_not_recorded(env):
    database, owner, _, products, _ = env
    product = products.add("A-1", "Arroz", 250, 10)
    sale_id = SaleRepository(database).register(
        Sale((SaleItem(product.id, product.name, 1, 250),), 250),
        business_id=owner.user.business_id,
        user_id=owner.user.id,
    )
    # register() no longer accepts it; a row from an older database can still have no cashier.
    with database.connect() as connection:
        connection.execute("UPDATE sales SET user_id = NULL WHERE id = ?", (sale_id,))

    assert ReceiptService(database).build(owner, sale_id).cashier == ""


def test_stored_utc_time_is_converted_to_an_aware_local_time(env):
    database, owner, _, _, _ = env
    sale_id = sell_mixed(env)
    set_created_at(database, sale_id, "2026-03-05 20:30:00")

    receipt = ReceiptService(database).build(owner, sale_id)

    assert receipt.issued_at == datetime(2026, 3, 5, 20, 30, tzinfo=UTC)
    assert receipt.issued_at.utcoffset() is not None


# -- sales note number ---------------------------------------------------------------------


def test_sales_note_number_is_stored_and_shown_for_rimpe_popular(env):
    database, owner, _, _, profile = env
    profile.update_profile(owner, tax_regime="rimpe_popular")
    sale_id = sell_mixed(env, note=" 001-001-000123 ")

    assert ReceiptService(database).build(owner, sale_id).sales_note_number == "001-001-000123"
    with database.connect() as connection:
        stored = connection.execute("SELECT sales_note_number FROM sales").fetchone()
    assert stored["sales_note_number"] == "001-001-000123"


@pytest.mark.parametrize("regime", ["sin_registro", "rimpe_emprendedor", "general"])
def test_sales_note_number_is_hidden_for_the_other_regimes(env, regime):
    database, owner, _, _, profile = env
    profile.update_profile(owner, tax_regime=regime, ruc="1790012345001")
    sale_id = sell_mixed(env, note="001-001-000123")

    assert ReceiptService(database).build(owner, sale_id).sales_note_number is None


def test_a_blank_sales_note_number_is_stored_as_none(env):
    database, owner, _, _, profile = env
    profile.update_profile(owner, tax_regime="rimpe_popular")
    sale_id = sell_mixed(env, note="   ")

    assert ReceiptService(database).build(owner, sale_id).sales_note_number is None
    with database.connect() as connection:
        stored = connection.execute("SELECT sales_note_number FROM sales").fetchone()
    assert stored["sales_note_number"] is None


def test_an_overlong_sales_note_number_is_rejected_and_nothing_is_sold(env):
    database, _, _, products, _ = env
    product = products.add("A-1", "Arroz", 250, 10)

    with pytest.raises(ValueError, match="no puede superar 30 caracteres"):
        SaleRepository(database).register(
            Sale((SaleItem(product.id, product.name, 1, 250),), 250),
            sales_note_number="9" * 31,
            **owner_of(database),
        )

    assert SaleRepository(database).today_summary()[0] == 0


# -- the sales schema migration ------------------------------------------------------------


def old_sales_database(path, *, extra_business: bool = False, cash_session: bool = False):
    """The schema before this change: sales that never recorded their business or seller."""
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA)
    connection.execute("INSERT INTO businesses (id, name) VALUES (1, 'Tienda Sol')")
    if extra_business:
        connection.execute("INSERT INTO businesses (id, name) VALUES (2, 'Otra')")
    connection.execute(
        "INSERT INTO users (id, business_id, username, password_hash, role) "
        "VALUES (1, 1, 'owner', 'x', 'owner')"
    )
    if cash_session:
        connection.execute("ALTER TABLE sales ADD COLUMN cash_session_id INTEGER")
        connection.execute(
            "INSERT INTO cash_sessions (id, business_id, user_id, opening_cents) "
            "VALUES (1, 2, 1, 0)"
        )
    for sale_id in (1, 2):
        connection.execute(
            "INSERT INTO sales (id, total_cents, payment_cents, change_cents) "
            "VALUES (?, 100, 100, 0)",
            (sale_id,),
        )
    if cash_session:
        connection.execute("UPDATE sales SET cash_session_id = 1 WHERE id = 1")
    connection.commit()
    connection.close()
    return Database(path)


def sale_owners(database) -> list[tuple[int | None, int | None]]:
    with database.connect() as connection:
        rows = connection.execute("SELECT business_id, user_id FROM sales ORDER BY id").fetchall()
    return [(row["business_id"], row["user_id"]) for row in rows]


def test_old_sales_of_a_single_business_are_backfilled_and_a_second_run_is_a_no_op(tmp_path):
    database = old_sales_database(tmp_path / "old.db")

    database.initialize()
    first = sale_owners(database)
    database.initialize()

    # The seller of an old sale was never recorded, so it stays unknown.
    assert first == [(1, None), (1, None)]
    assert sale_owners(database) == first


def test_a_sale_stored_without_a_business_after_the_migration_stays_unclaimed(tmp_path):
    database = old_sales_database(tmp_path / "old.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO sales (total_cents, payment_cents, change_cents) VALUES (100, 100, 0)"
        )

    database.initialize()

    assert sale_owners(database)[-1] == (None, None)


def test_the_cash_session_decides_the_business_before_the_single_business_rule(tmp_path):
    database = old_sales_database(tmp_path / "old.db", extra_business=True, cash_session=True)

    database.initialize()
    database.initialize()

    # Sale 1 belongs to business 2 through its cash session; sale 2 is ambiguous with two
    # businesses, so it belongs to nobody.
    assert sale_owners(database) == [(2, None), (None, None)]


def test_old_sales_without_a_cash_session_and_two_businesses_stay_unclaimed(tmp_path):
    database = old_sales_database(tmp_path / "old.db", extra_business=True)

    database.initialize()

    assert sale_owners(database) == [(None, None), (None, None)]
