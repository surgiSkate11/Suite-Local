import re
import sqlite3
from datetime import datetime

import pytest

from suitelocal.application.auth import AuthService
from suitelocal.application.tables import TablesService
from suitelocal.domain.auth import Session
from suitelocal.domain.models import Payment, Sale, SaleItem
from suitelocal.domain.tables import (
    ComandaLine,
    OpenOrder,
    OrderLine,
    Table,
    TableError,
    TableStatus,
)
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import ProductRepository, SaleRepository
from suitelocal.infrastructure.tables_repository import (
    TABLES_SCHEMA,
    TablesRepository,
    ensure_tables_schema,
)


@pytest.fixture
def env(tmp_path):
    database = Database(tmp_path / "tables.db")
    database.initialize()
    with database.connect() as connection:
        ensure_tables_schema(connection)
    auth = AuthService(database)
    owner = Session(auth.setup_owner("Café", "dueno", "Clave-segura-1", "Clave-segura-1"))
    cashier = Session(auth.create_cashier(owner, "cajero", "Clave-segura-2", "Clave-segura-2"))
    products = ProductRepository(database)
    coffee = products.add("C-1", "Café", 150, 10)
    cake = products.add("T-1", "Torta", 300, 4)
    service = TablesService(database)
    return database, service, owner, cashier, products, coffee, cake


def _stock(products, product):
    return next(p.stock for p in products.find_active("") if p.id == product.id)


def _count(database, table):
    with database.connect() as connection:
        return connection.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]


def _order_status(database, order_id):
    with database.connect() as connection:
        row = connection.execute(
            "SELECT status, sale_id FROM table_orders WHERE id = ?", (order_id,)
        ).fetchone()
    return row["status"], row["sale_id"]


def test_ensure_tables_schema_is_idempotent(env):
    database, service, owner, *_ = env
    service.create_table(owner, "Mesa 1")
    with database.connect() as connection:
        ensure_tables_schema(connection)
        ensure_tables_schema(connection)
    assert [s.table.name for s in service.list_tables(owner)] == ["Mesa 1"]


def test_create_and_list_tables_with_zone(env):
    _, service, owner, cashier, *_ = env
    first = service.create_table(owner, "  Mesa 1  ", "Terraza")
    second = service.create_table(owner, "Mesa 2")
    blank_zone = service.create_table(owner, "Mesa 3", "   ")

    assert first == Table(first.id, owner.user.business_id, "Mesa 1", "Terraza", True)
    assert second.zone is None
    assert blank_zone.zone is None
    statuses = service.list_tables(cashier)
    assert [s.table.name for s in statuses] == ["Mesa 1", "Mesa 2", "Mesa 3"]
    assert all(isinstance(s, TableStatus) and s.order is None for s in statuses)
    assert all(not s.occupied for s in statuses)


def test_create_table_validates_name_and_uniqueness(env):
    database, service, owner, *_ = env
    service.create_table(owner, "Mesa 1")
    with pytest.raises(ValueError, match="El nombre de la mesa es obligatorio."):
        service.create_table(owner, "   ")
    with pytest.raises(ValueError, match="Ya existe una mesa con ese nombre."):
        service.create_table(owner, "Mesa 1")
    assert _count(database, "tables") == 1


def test_only_owner_creates_tables_but_cashier_operates_orders(env):
    database, service, owner, cashier, _, coffee, _ = env
    with pytest.raises(PermissionError):
        service.create_table(cashier, "Mesa 1")
    assert _count(database, "tables") == 0

    table = service.create_table(owner, "Mesa 1")
    order = service.open_order(cashier, table.id)
    order = service.add_product(cashier, order.id, coffee.id, 1)
    assert order.lines[0].quantity == 1


def test_one_open_order_per_table(env):
    database, service, owner, cashier, _, coffee, _ = env
    table = service.create_table(owner, "Mesa 1")
    order = service.open_order(cashier, table.id)
    service.add_product(cashier, order.id, coffee.id, 2)

    with pytest.raises(ValueError, match="La mesa ya tiene una cuenta abierta."):
        service.open_order(cashier, table.id)

    assert _count(database, "table_orders") == 1
    current = service.get_order(cashier, table.id)
    assert current is not None
    assert current.id == order.id
    assert current.lines[0].quantity == 2


def test_database_enforces_one_open_order_per_table(env):
    database, service, owner, *_ = env
    table = service.create_table(owner, "Mesa 1")
    service.open_order(owner, table.id)
    with pytest.raises(sqlite3.IntegrityError), database.connect() as connection:
        connection.execute(
            "INSERT INTO table_orders (table_id, status) VALUES (?, 'open')", (table.id,)
        )


def test_open_order_for_unknown_table_or_other_business_fails(env):
    database, service, owner, *_ = env
    with pytest.raises(ValueError, match="La mesa no existe."):
        service.open_order(owner, 999)
    with database.connect() as connection:
        connection.execute("INSERT INTO businesses (id, name) VALUES (2, 'Otro')")
        connection.execute("INSERT INTO tables (id, business_id, name) VALUES (50, 2, 'Ajena')")
    with pytest.raises(ValueError, match="La mesa no existe."):
        service.open_order(owner, 50)
    assert _count(database, "table_orders") == 0


def test_add_product_twice_merges_quantity(env):
    database, service, owner, _, _, coffee, cake = env
    table = service.create_table(owner, "Mesa 1")
    order = service.open_order(owner, table.id)
    service.add_product(owner, order.id, coffee.id, 1)
    service.add_product(owner, order.id, cake.id, 1)
    order = service.add_product(owner, order.id, coffee.id, 2)

    assert isinstance(order, OpenOrder)
    assert order.lines == (
        OrderLine(coffee.id, "Café", 3, 150, 0, 1500),
        OrderLine(cake.id, "Torta", 1, 300, 0, 1500),
    )
    assert order.subtotal_cents == 3 * 150 + 300
    assert _count(database, "order_lines") == 2


def test_add_product_rejects_bad_quantity_and_unknown_product(env):
    database, service, owner, _, _, coffee, _ = env
    table = service.create_table(owner, "Mesa 1")
    order = service.open_order(owner, table.id)
    with pytest.raises(ValueError, match="La cantidad debe ser mayor que cero."):
        service.add_product(owner, order.id, coffee.id, 0)
    with pytest.raises(ValueError, match="El producto ya no está disponible."):
        service.add_product(owner, order.id, 999, 1)
    assert _count(database, "order_lines") == 0


def test_change_quantity_and_remove(env):
    _, service, owner, _, _, coffee, cake = env
    table = service.create_table(owner, "Mesa 1")
    order = service.open_order(owner, table.id)
    service.add_product(owner, order.id, coffee.id, 2)
    service.add_product(owner, order.id, cake.id, 1)

    order = service.set_quantity(owner, order.id, coffee.id, 5)
    assert [(line.product_id, line.quantity) for line in order.lines] == [
        (coffee.id, 5),
        (cake.id, 1),
    ]

    order = service.set_quantity(owner, order.id, coffee.id, 0)
    assert [line.product_id for line in order.lines] == [cake.id]

    order = service.remove_line(owner, order.id, cake.id)
    assert order.lines == ()

    with pytest.raises(ValueError, match="El producto no está en la cuenta."):
        service.remove_line(owner, order.id, cake.id)
    with pytest.raises(ValueError, match="El producto no está en la cuenta."):
        service.set_quantity(owner, order.id, cake.id, 2)
    with pytest.raises(ValueError, match="La cantidad no puede ser negativa."):
        service.set_quantity(owner, order.id, cake.id, -1)


def test_adding_items_does_not_touch_stock(env):
    _, service, owner, _, products, coffee, cake = env
    table = service.create_table(owner, "Mesa 1")
    order = service.open_order(owner, table.id)
    service.add_product(owner, order.id, coffee.id, 4)
    service.add_product(owner, order.id, cake.id, 3)
    service.set_quantity(owner, order.id, coffee.id, 6)
    service.send_to_kitchen(owner, order.id)

    assert _stock(products, coffee) == 10
    assert _stock(products, cake) == 4


def test_send_to_kitchen_returns_only_newly_sent_lines(env):
    _, service, owner, _, _, coffee, cake = env
    table = service.create_table(owner, "Mesa 1")
    order = service.open_order(owner, table.id)
    service.add_product(owner, order.id, coffee.id, 2)
    service.add_product(owner, order.id, cake.id, 1)

    first = service.send_to_kitchen(owner, order.id)
    assert first == [ComandaLine(coffee.id, "Café", 2), ComandaLine(cake.id, "Torta", 1)]
    assert service.send_to_kitchen(owner, order.id) == []

    service.add_product(owner, order.id, coffee.id, 3)
    second = service.send_to_kitchen(owner, order.id)
    assert second == [ComandaLine(coffee.id, "Café", 3)]

    current = service.get_order(owner, table.id)
    assert current is not None
    assert all(line.pending_quantity == 0 for line in current.lines)
    assert [line.quantity for line in current.lines] == [5, 1]


def test_lowering_quantity_below_sent_keeps_sent_consistent(env):
    _, service, owner, _, _, coffee, _ = env
    table = service.create_table(owner, "Mesa 1")
    order = service.open_order(owner, table.id)
    service.add_product(owner, order.id, coffee.id, 3)
    service.send_to_kitchen(owner, order.id)

    order = service.set_quantity(owner, order.id, coffee.id, 1)
    assert order.lines[0].quantity == 1
    assert order.lines[0].sent_quantity == 1
    assert service.send_to_kitchen(owner, order.id) == []


def test_transfer_to_free_table_moves_the_order(env):
    _, service, owner, _, _, coffee, _ = env
    source = service.create_table(owner, "Mesa 1")
    target = service.create_table(owner, "Mesa 2")
    order = service.open_order(owner, source.id)
    service.add_product(owner, order.id, coffee.id, 2)

    moved = service.transfer(owner, order.id, target.id)

    assert moved.id == order.id
    assert moved.table_id == target.id
    assert [line.quantity for line in moved.lines] == [2]
    assert service.get_order(owner, source.id) is None
    on_target = service.get_order(owner, target.id)
    assert on_target is not None
    assert on_target.id == order.id


def test_transfer_to_occupied_table_fails_and_changes_nothing(env):
    _, service, owner, _, _, coffee, cake = env
    source = service.create_table(owner, "Mesa 1")
    target = service.create_table(owner, "Mesa 2")
    first = service.open_order(owner, source.id)
    second = service.open_order(owner, target.id)
    service.add_product(owner, first.id, coffee.id, 2)
    service.add_product(owner, second.id, cake.id, 1)

    with pytest.raises(ValueError, match="La mesa de destino ya tiene una cuenta abierta."):
        service.transfer(owner, first.id, target.id)
    with pytest.raises(ValueError, match="La cuenta ya está en esa mesa."):
        service.transfer(owner, first.id, source.id)
    with pytest.raises(ValueError, match="La mesa no existe."):
        service.transfer(owner, first.id, 999)

    on_source = service.get_order(owner, source.id)
    on_target = service.get_order(owner, target.id)
    assert on_source is not None
    assert on_target is not None
    assert (on_source.id, [line.quantity for line in on_source.lines]) == (first.id, [2])
    assert (on_target.id, [line.quantity for line in on_target.lines]) == (second.id, [1])


def test_cancel_removes_the_open_order_and_leaves_stock(env):
    database, service, owner, _, products, coffee, _ = env
    table = service.create_table(owner, "Mesa 1")
    order = service.open_order(owner, table.id)
    service.add_product(owner, order.id, coffee.id, 3)

    service.cancel(owner, order.id)

    assert service.get_order(owner, table.id) is None
    assert _stock(products, coffee) == 10
    assert _count(database, "sales") == 0
    assert _order_status(database, order.id) == ("cancelled", None)
    with pytest.raises(ValueError, match="La cuenta ya no está abierta."):
        service.add_product(owner, order.id, coffee.id, 1)
    # The table is free again.
    assert service.open_order(owner, table.id).id != order.id


def test_list_tables_shows_open_order_summary(env):
    database, service, owner, _, _, coffee, cake = env
    busy = service.create_table(owner, "Mesa 1", "Salón")
    service.create_table(owner, "Mesa 2", "Salón")
    order = service.open_order(owner, busy.id)
    service.add_product(owner, order.id, coffee.id, 2)
    service.add_product(owner, order.id, cake.id, 1)
    with database.connect() as connection:
        connection.execute(
            "UPDATE table_orders SET opened_at = '2026-01-01 10:00:00' WHERE id = ?",
            (order.id,),
        )

    statuses = service.list_tables(owner)
    occupied, free = statuses

    assert occupied.occupied
    assert occupied.order is not None
    assert occupied.order.subtotal_cents == 2 * 150 + 300
    assert occupied.order.item_count == 3
    assert occupied.order.minutes_open(datetime(2026, 1, 1, 10, 42, 30)) == 42
    assert occupied.order.minutes_open(datetime(2026, 1, 1, 9, 0)) == 0
    assert not free.occupied
    assert free.order is None


def test_charge_registers_one_sale_decrements_stock_and_frees_table(env):
    database, service, owner, cashier, products, coffee, cake = env
    table = service.create_table(owner, "Mesa 1")
    order = service.open_order(cashier, table.id)
    service.add_product(cashier, order.id, coffee.id, 2)
    service.add_product(cashier, order.id, cake.id, 1)

    sale_id = service.charge(cashier, order.id, [Payment("cash", 1000)])

    assert _count(database, "sales") == 1
    assert _count(database, "sale_items") == 2
    with database.connect() as connection:
        sale = connection.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
        items = connection.execute(
            "SELECT product_id, quantity, unit_price_cents FROM sale_items WHERE sale_id = ?",
            (sale_id,),
        ).fetchall()
    assert sale["total_cents"] == 600
    assert sale["payment_cents"] == 1000
    assert sale["change_cents"] == 400
    # Prices include IVA (15 % by default): 2 x 150 and 1 x 300 each hold 39 of IVA.
    assert sale["subtotal_cents"] == 522
    assert sale["tax_cents"] == 78
    assert [tuple(row) for row in items] == [(coffee.id, 2, 150), (cake.id, 1, 300)]
    assert _stock(products, coffee) == 8
    assert _stock(products, cake) == 3
    assert _order_status(database, order.id) == ("closed", sale_id)
    assert service.get_order(cashier, table.id) is None
    assert not service.list_tables(cashier)[0].occupied
    with pytest.raises(ValueError, match="La cuenta ya no está abierta."):
        service.charge(cashier, order.id, [Payment("cash", 1000)])
    assert _count(database, "sales") == 1


def test_charge_at_mixed_rates_splits_base_iva_and_total_exactly(env):
    database, service, owner, _, products, _, _ = env
    sandwich = products.add("S-1", "Sándwich", 115, 10, tax_rate_basis_points=1500)
    bread = products.add("P-1", "Pan", 200, 10, tax_rate_basis_points=0)
    table = service.create_table(owner, "Mesa 1")
    order = service.open_order(owner, table.id)
    service.add_product(owner, order.id, sandwich.id, 3)
    order = service.add_product(owner, order.id, bread.id, 1)

    assert [line.tax_rate_basis_points for line in order.lines] == [1500, 0]
    sale_id = service.charge(owner, order.id, [Payment("cash", 600)])

    # 3 x 115 = 345 at 15 % -> base 345 * 100 / 115 = 300, IVA 45; 1 x 200 at 0 % -> 200, IVA 0.
    with database.connect() as connection:
        sale = connection.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
        items = connection.execute(
            "SELECT product_id, tax_rate_basis_points, tax_cents FROM sale_items "
            "WHERE sale_id = ? ORDER BY id",
            (sale_id,),
        ).fetchall()
    assert sale["subtotal_cents"] == 500
    assert sale["tax_cents"] == 45
    assert sale["total_cents"] == 545
    assert sale["change_cents"] == 55
    assert [tuple(row) for row in items] == [(sandwich.id, 1500, 45), (bread.id, 0, 0)]


def test_order_line_keeps_the_rate_it_was_added_with(env):
    database, service, owner, _, products, _, _ = env
    bread = products.add("P-1", "Pan", 200, 10, tax_rate_basis_points=0)
    table = service.create_table(owner, "Mesa 1")
    order = service.open_order(owner, table.id)
    service.add_product(owner, order.id, bread.id, 1)
    order = service.add_product(owner, order.id, bread.id, 2)

    assert order.lines[0].tax_rate_basis_points == 0
    assert order.sale_items() == (SaleItem(bread.id, "Pan", 3, 200, 0),)
    with database.connect() as connection:
        ensure_tables_schema(connection)
        ensure_tables_schema(connection)
    assert service.get_order(owner, table.id) == order


def _sale_of(product, quantity=1):
    return Sale(
        (SaleItem(product.id, product.name, quantity, product.price_cents, 1500),),
        product.price_cents * quantity,
    )


def test_register_calls_the_hook_with_the_same_connection_before_commit(env):
    database, _, _, _, products, coffee, _ = env
    seen = {}

    def hook(connection, sale_id):
        seen["sale_id"] = sale_id
        seen["sale_rows"] = connection.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
        seen["stock"] = connection.execute(
            "SELECT stock FROM products WHERE id = ?", (coffee.id,)
        ).fetchone()[0]
        seen["payments"] = connection.execute("SELECT COUNT(*) FROM sale_payments").fetchone()[0]
        seen["in_transaction"] = connection.in_transaction

    sale_id = SaleRepository(database).register(_sale_of(coffee, 2), on_registered=hook)

    assert seen == {
        "sale_id": sale_id,
        "sale_rows": 1,
        "stock": 8,
        "payments": 1,
        "in_transaction": True,
    }
    assert _count(database, "sales") == 1


def test_register_rolls_everything_back_when_the_hook_raises(env):
    database, _, _, _, products, coffee, _ = env

    def hook(connection, sale_id):
        raise RuntimeError("falló el gancho")

    with pytest.raises(RuntimeError, match="falló el gancho"):
        SaleRepository(database).register(_sale_of(coffee, 2), on_registered=hook)

    assert _count(database, "sales") == 0
    assert _count(database, "sale_items") == 0
    assert _count(database, "sale_payments") == 0
    assert _stock(products, coffee) == 10


def test_register_without_hook_behaves_as_before(env):
    database, _, _, _, products, coffee, _ = env

    sale_id = SaleRepository(database).register(_sale_of(coffee, 2))

    assert _count(database, "sales") == 1
    assert _count(database, "sale_items") == 1
    assert _count(database, "sale_payments") == 1
    assert _stock(products, coffee) == 8
    assert sale_id > 0


def test_charge_rolls_back_the_sale_when_closing_the_order_fails(env):
    database, service, owner, _, products, coffee, cake = env
    table = service.create_table(owner, "Mesa 1")
    order = service.open_order(owner, table.id)
    service.add_product(owner, order.id, coffee.id, 2)
    before = service.add_product(owner, order.id, cake.id, 1)

    def failing_close(connection, business_id, order_id, sale_id):
        raise TableError("No se pudo cerrar la cuenta.")

    service.tables.close_in = failing_close
    with pytest.raises(TableError, match="No se pudo cerrar la cuenta."):
        service.charge(owner, order.id, [Payment("cash", 1000)])

    assert _count(database, "sales") == 0
    assert _count(database, "sale_items") == 0
    assert _count(database, "sale_payments") == 0
    assert _stock(products, coffee) == 10
    assert _stock(products, cake) == 4
    assert _order_status(database, order.id) == ("open", None)
    assert service.get_order(owner, table.id) == before


def test_charging_the_same_order_twice_creates_one_sale_and_decrements_stock_once(env):
    database, service, owner, _, products, coffee, _ = env
    table = service.create_table(owner, "Mesa 1")
    order = service.open_order(owner, table.id)
    stale = service.add_product(owner, order.id, coffee.id, 2)
    sale_id = service.charge(owner, order.id, [Payment("cash", 1000)])

    # A second cashier still holding the order read before the first charge finished.
    service.tables.get_order = lambda business_id, order_id: stale
    with pytest.raises(TableError, match="La cuenta de esta mesa ya fue cobrada o anulada."):
        service.charge(owner, order.id, [Payment("cash", 1000)])

    assert _count(database, "sales") == 1
    assert _count(database, "sale_items") == 1
    assert _count(database, "sale_payments") == 1
    assert _stock(products, coffee) == 8
    assert _order_status(database, order.id) == ("closed", sale_id)


def test_close_in_requires_an_open_order_of_the_business(env):
    database, service, owner, _, _, coffee, _ = env
    table = service.create_table(owner, "Mesa 1")
    order = service.open_order(owner, table.id)
    service.add_product(owner, order.id, coffee.id, 1)
    service.cancel(owner, order.id)

    with database.connect() as connection:
        with pytest.raises(TableError, match="La cuenta de esta mesa ya fue cobrada o anulada."):
            service.tables.close_in(connection, owner.user.business_id, order.id, 1)
    assert _order_status(database, order.id) == ("cancelled", None)


def test_charge_with_insufficient_payment_keeps_order_open(env):
    database, service, owner, _, products, coffee, _ = env
    table = service.create_table(owner, "Mesa 1")
    order = service.open_order(owner, table.id)
    before = service.add_product(owner, order.id, coffee.id, 2)

    with pytest.raises(ValueError, match="El pago recibido es menor que el total de la venta."):
        service.charge(owner, order.id, [Payment("cash", 100)])

    assert _count(database, "sales") == 0
    assert _stock(products, coffee) == 10
    assert _order_status(database, order.id) == ("open", None)
    assert service.get_order(owner, table.id) == before


def test_charge_with_insufficient_stock_keeps_order_open(env):
    database, service, owner, _, products, coffee, cake = env
    table = service.create_table(owner, "Mesa 1")
    order = service.open_order(owner, table.id)
    service.add_product(owner, order.id, coffee.id, 2)
    before = service.add_product(owner, order.id, cake.id, 5)  # only 4 in stock

    with pytest.raises(ValueError, match="Stock insuficiente para Torta."):
        service.charge(owner, order.id, [Payment("cash", 5000)])

    assert _count(database, "sales") == 0
    assert _count(database, "sale_items") == 0
    assert _stock(products, coffee) == 10
    assert _stock(products, cake) == 4
    assert _order_status(database, order.id) == ("open", None)
    assert service.get_order(owner, table.id) == before


def test_charge_empty_order_fails_and_stays_open(env):
    database, service, owner, *_ = env
    table = service.create_table(owner, "Mesa 1")
    order = service.open_order(owner, table.id)

    with pytest.raises(ValueError, match="La venta debe tener al menos un producto."):
        service.charge(owner, order.id, [Payment("cash", 100)])

    assert _order_status(database, order.id) == ("open", None)


def test_repository_is_usable_without_the_service(env):
    database, _, owner, *_ = env
    repository = TablesRepository(database)
    table = repository.add_table(owner.user.business_id, "Barra", None)
    assert repository.list_tables(owner.user.business_id) == [table]


def test_there_is_no_tip_concept(env):
    database, service, *_ = env
    assert "propina" not in TABLES_SCHEMA.lower()
    assert not re.search(r"\btip", TABLES_SCHEMA.lower())
    with database.connect() as connection:
        columns = {
            row["name"].lower()
            for name in ("tables", "table_orders", "order_lines")
            for row in connection.execute(f"PRAGMA table_info({name})")
        }
    assert not [c for c in columns if "tip" in c.split("_") or "propina" in c]
    assert not [n for n in dir(service) if "tip" in n.split("_") or "propina" in n]
