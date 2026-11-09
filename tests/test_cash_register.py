import pytest
from sale_owner import owner_of

from suitelocal.application.auth import AuthService
from suitelocal.application.cash_register import CashRegisterService
from suitelocal.domain.auth import Session
from suitelocal.domain.models import Payment, Sale, SaleItem
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import ProductRepository, SaleRepository


@pytest.fixture
def env(tmp_path):
    database = Database(tmp_path / "cash.db")
    database.initialize()
    auth = AuthService(database)
    owner = Session(auth.setup_owner("Tienda", "dueno", "Clave-segura-1", "Clave-segura-1"))
    cashier = Session(auth.create_cashier(owner, "cajero", "Clave-segura-2", "Clave-segura-2"))
    product = ProductRepository(database).add("A-1", "Arroz", 250, 100)
    return (
        database,
        CashRegisterService(database),
        SaleRepository(database),
        owner,
        cashier,
        product,
    )


def _session_count(database):
    with database.connect() as connection:
        return connection.execute("SELECT COUNT(*) AS n FROM cash_sessions").fetchone()["n"]


def test_open_and_close_with_exact_expected_and_difference(env):
    _, cash, sales, owner, cashier, product = env
    opened = cash.open(cashier, 10_000)
    assert opened.closed_at is None
    assert opened.opening_cents == 10_000
    assert opened.user_id == cashier.user.id
    assert cash.current(owner) == opened

    # 2 x 250 = 500, paid with 1000 cash -> 500 change -> net cash 500.
    sales.register(
        Sale((SaleItem(product.id, product.name, 2, 250),), 1000), **owner_of(sales.database)
    )
    closed = cash.close(cashier, 10_400, notes="faltan 100")

    assert closed.id == opened.id
    assert closed.expected_cents == 10_500
    assert closed.counted_cents == 10_400
    assert closed.difference_cents == -100
    assert closed.notes == "faltan 100"
    assert closed.closed_at is not None
    assert cash.current(owner) is None


def test_overage_is_positive_difference(env):
    _, cash, _, owner, _, _ = env
    cash.open(owner, 5_000)
    closed = cash.close(owner, 5_300)
    assert closed.expected_cents == 5_000
    assert closed.difference_cents == 300


def test_only_cash_payments_count_and_change_is_subtracted(env):
    _, cash, sales, owner, _, product = env
    cash.open(owner, 1_000)

    # total 750: transfer 500 + cash 300 -> change 50 -> net cash 250.
    sales.register(
        Sale(
            (SaleItem(product.id, product.name, 3, 250),),
            0,
            payments=(Payment("transfer", 500, "REF-1"), Payment("cash", 300)),
        ),
        **owner_of(sales.database),
    )
    # total 250, paid entirely by card: no cash.
    sales.register(
        Sale(
            (SaleItem(product.id, product.name, 1, 250),),
            0,
            payments=(Payment("card", 250),),
        ),
        **owner_of(sales.database),
    )
    closed = cash.close(owner, 1_250)

    assert closed.expected_cents == 1_250
    assert closed.difference_cents == 0


def test_sales_from_a_previous_session_are_not_counted(env):
    _, cash, sales, owner, _, product = env
    cash.open(owner, 0)
    sales.register(
        Sale((SaleItem(product.id, product.name, 2, 250),), 500), **owner_of(sales.database)
    )
    cash.close(owner, 500)

    cash.open(owner, 100)
    closed = cash.close(owner, 100)

    assert closed.expected_cents == 100


def test_second_open_is_rejected_and_leaves_one_session(env):
    database, cash, _, owner, cashier, _ = env
    cash.open(owner, 1_000)

    with pytest.raises(ValueError, match="Ya hay una caja abierta"):
        cash.open(cashier, 2_000)

    assert _session_count(database) == 1
    current = cash.current(owner)
    assert current is not None
    assert current.opening_cents == 1_000


def test_close_without_open_session_is_rejected(env):
    database, cash, _, owner, _, _ = env

    with pytest.raises(ValueError, match="No hay una caja abierta"):
        cash.close(owner, 100)

    assert _session_count(database) == 0


def test_closing_twice_is_rejected(env):
    _, cash, _, owner, _, _ = env
    cash.open(owner, 100)
    cash.close(owner, 100)

    with pytest.raises(ValueError, match="No hay una caja abierta"):
        cash.close(owner, 100)


def test_negative_amounts_are_rejected_without_changing_data(env):
    database, cash, _, owner, _, _ = env

    with pytest.raises(ValueError, match="no puede ser negativo"):
        cash.open(owner, -1)
    assert _session_count(database) == 0

    cash.open(owner, 100)
    with pytest.raises(ValueError, match="no puede ser negativo"):
        cash.close(owner, -1)

    current = cash.current(owner)
    assert current is not None
    assert current.closed_at is None
    assert current.counted_cents is None
    assert current.expected_cents is None


def test_cashier_cannot_read_history(env):
    _, cash, _, owner, cashier, _ = env
    cash.open(cashier, 100)
    cash.close(cashier, 100)

    with pytest.raises(PermissionError, match="Solo el dueño puede realizar esta acción."):
        cash.history(cashier)

    history = cash.history(owner)
    assert len(history) == 1
    assert history[0].user_id == cashier.user.id


def test_history_is_newest_first_and_respects_limit(env):
    _, cash, _, owner, _, _ = env
    for amount in (100, 200, 300):
        cash.open(owner, amount)
        cash.close(owner, amount)

    history = cash.history(owner, limit=2)

    assert [item.opening_cents for item in history] == [300, 200]


def test_sale_without_open_session_still_works_with_null_cash_session(env):
    database, _, sales, _, _, product = env

    sale_id = sales.register(
        Sale((SaleItem(product.id, product.name, 1, 250),), 250), **owner_of(sales.database)
    )

    with database.connect() as connection:
        row = connection.execute(
            "SELECT cash_session_id FROM sales WHERE id = ?", (sale_id,)
        ).fetchone()
    assert row["cash_session_id"] is None


def test_sale_with_open_session_is_linked_to_it(env):
    database, cash, sales, owner, _, product = env
    opened = cash.open(owner, 0)

    sale_id = sales.register(
        Sale((SaleItem(product.id, product.name, 1, 250),), 250), **owner_of(sales.database)
    )

    with database.connect() as connection:
        row = connection.execute(
            "SELECT cash_session_id FROM sales WHERE id = ?", (sale_id,)
        ).fetchone()
    assert row["cash_session_id"] == opened.id


def test_initialize_is_idempotent_and_adds_column_to_legacy_sales(tmp_path):
    database = Database(tmp_path / "legacy.db")
    database.initialize()
    database.initialize()
    with database.connect() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(sales)")}
    assert "cash_session_id" in columns


def _cash_session_rows(database):
    with database.connect() as connection:
        return [tuple(row) for row in connection.execute("SELECT * FROM cash_sessions")]


def test_expected_cents_is_none_without_an_open_session(env):
    _, cash, _, owner, _, _ = env

    assert cash.expected_cents(owner) is None

    cash.open(owner, 100)
    cash.close(owner, 100)
    assert cash.expected_cents(owner) is None


def test_expected_cents_matches_close_and_changes_no_data(env):
    database, cash, sales, owner, cashier, product = env
    cash.open(cashier, 1_000)
    assert cash.expected_cents(owner) == 1_000

    # Same mix as the close test: transfer is ignored, cash minus change counts.
    sales.register(
        Sale(
            (SaleItem(product.id, product.name, 3, 250),),
            0,
            payments=(Payment("transfer", 500, "REF-1"), Payment("cash", 300)),
        ),
        **owner_of(sales.database),
    )
    sales.register(
        Sale((SaleItem(product.id, product.name, 2, 250),), 1_000), **owner_of(sales.database)
    )
    before = _cash_session_rows(database)

    expected = cash.expected_cents(owner)

    assert expected == 1_750
    assert _cash_session_rows(database) == before
    assert cash.current(owner) is not None
    closed = cash.close(owner, expected)
    assert closed.expected_cents == expected
    assert closed.difference_cents == 0
