import sqlite3

from suitelocal.domain.tables import (
    ComandaLine,
    OpenOrder,
    OrderLine,
    Table,
    TableError,
    normalize_table_name,
    normalize_zone,
    require_positive_quantity,
)
from suitelocal.infrastructure.database import Database, add_missing_columns

TABLES_SCHEMA = """
CREATE TABLE IF NOT EXISTS tables (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    name TEXT NOT NULL,
    zone TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    UNIQUE (business_id, name)
);

CREATE TABLE IF NOT EXISTS table_orders (
    id INTEGER PRIMARY KEY,
    table_id INTEGER NOT NULL REFERENCES tables(id),
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed', 'cancelled')),
    opened_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    closed_at TEXT,
    sale_id INTEGER REFERENCES sales(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_table_orders_one_open
    ON table_orders(table_id) WHERE status = 'open';

CREATE TABLE IF NOT EXISTS order_lines (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES table_orders(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    product_name TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price_cents INTEGER NOT NULL CHECK (unit_price_cents >= 0),
    sent_quantity INTEGER NOT NULL DEFAULT 0
        CHECK (sent_quantity >= 0 AND sent_quantity <= quantity),
    tax_rate_basis_points INTEGER NOT NULL DEFAULT 0
        CHECK (tax_rate_basis_points IN (1500, 500, 0)),
    UNIQUE (order_id, product_id)
);
"""

_ORDER_NOT_OPEN = "La cuenta ya no está abierta."
_ORDER_ALREADY_FINISHED = "La cuenta de esta mesa ya fue cobrada o anulada."
_TABLE_MISSING = "La mesa no existe."


def ensure_tables_schema(connection: sqlite3.Connection) -> None:
    """Create the tables, orders and order lines when missing; safe to call repeatedly.

    Old ``order_lines`` lacked the per-line IVA rate: it is added and backfilled here. The script
    commits what the connection had pending, so call it outside any transaction.
    """
    connection.executescript(TABLES_SCHEMA)
    # One transaction for the ALTER and its backfill, so a crash never leaves the column with
    # every old line stuck at the 0 % default.
    connection.execute("BEGIN IMMEDIATE")
    added = add_missing_columns(
        connection,
        "order_lines",
        (
            "tax_rate_basis_points INTEGER NOT NULL DEFAULT 0 "
            "CHECK (tax_rate_basis_points IN (1500, 500, 0))",
        ),
    )
    if added:
        # Each existing line takes its product's current rate; a line whose product is gone
        # falls back to the general 15 %. Runs only when the column is created.
        connection.execute(
            """
            UPDATE order_lines SET tax_rate_basis_points = COALESCE(
                (SELECT p.tax_rate_basis_points FROM products p
                 WHERE p.id = order_lines.product_id),
                1500
            )
            """
        )
    connection.commit()


def _to_table(row: sqlite3.Row) -> Table:
    return Table(row["id"], row["business_id"], row["name"], row["zone"], bool(row["active"]))


class TablesRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def add_table(self, business_id: int, name: str, zone: str | None) -> Table:
        name = normalize_table_name(name)
        zone = normalize_zone(zone)
        try:
            with self.database.connect() as connection:
                cursor = connection.execute(
                    "INSERT INTO tables (business_id, name, zone) VALUES (?, ?, ?)",
                    (business_id, name, zone),
                )
                table_id = cursor.lastrowid
                if table_id is None:
                    raise RuntimeError("No se pudo obtener el identificador de la mesa.")
        except sqlite3.IntegrityError as error:
            if "UNIQUE constraint failed: tables.business_id, tables.name" in str(error):
                raise TableError("Ya existe una mesa con ese nombre.") from error
            raise
        return Table(table_id, business_id, name, zone, True)

    def list_tables(self, business_id: int) -> list[Table]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM tables WHERE business_id = ? AND active = 1 ORDER BY id",
                (business_id,),
            ).fetchall()
        return [_to_table(row) for row in rows]

    def open_orders(self, business_id: int) -> dict[int, OpenOrder]:
        """Open orders of the business keyed by table id."""
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT o.id FROM table_orders o JOIN tables t ON t.id = o.table_id
                WHERE t.business_id = ? AND o.status = 'open'
                """,
                (business_id,),
            ).fetchall()
            orders = [self._read_order(connection, row["id"]) for row in rows]
        return {order.table_id: order for order in orders}

    def order_for_table(self, business_id: int, table_id: int) -> OpenOrder | None:
        with self.database.connect() as connection:
            self._require_table(connection, business_id, table_id)
            row = connection.execute(
                "SELECT id FROM table_orders WHERE table_id = ? AND status = 'open'",
                (table_id,),
            ).fetchone()
            return None if row is None else self._read_order(connection, row["id"])

    def open_order(self, business_id: int, table_id: int) -> OpenOrder:
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_table(connection, business_id, table_id)
            if self._open_order_id(connection, table_id) is not None:
                raise TableError("La mesa ya tiene una cuenta abierta.")
            cursor = connection.execute(
                "INSERT INTO table_orders (table_id) VALUES (?)", (table_id,)
            )
            return self._read_order(connection, self._require_id(cursor.lastrowid))

    def add_product(
        self, business_id: int, order_id: int, product_id: int, quantity: int
    ) -> OpenOrder:
        require_positive_quantity(quantity)
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_open_order(connection, business_id, order_id)
            product = connection.execute(
                "SELECT name, price_cents, tax_rate_basis_points FROM products "
                "WHERE id = ? AND active = 1",
                (product_id,),
            ).fetchone()
            if product is None:
                raise TableError("El producto ya no está disponible.")
            # A repeated product keeps the price and IVA rate it was ordered at and only grows
            # its quantity.
            connection.execute(
                """
                INSERT INTO order_lines
                    (order_id, product_id, product_name, quantity, unit_price_cents,
                     tax_rate_basis_points)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (order_id, product_id) DO UPDATE SET quantity = quantity + ?
                """,
                (
                    order_id,
                    product_id,
                    product["name"],
                    quantity,
                    product["price_cents"],
                    product["tax_rate_basis_points"],
                    quantity,
                ),
            )
            return self._read_order(connection, order_id)

    def set_quantity(
        self, business_id: int, order_id: int, product_id: int, quantity: int
    ) -> OpenOrder:
        """Set a line's quantity; zero removes it. Sent units never exceed the new quantity."""
        if quantity < 0:
            raise TableError("La cantidad no puede ser negativa.")
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_open_order(connection, business_id, order_id)
            if quantity == 0:
                cursor = connection.execute(
                    "DELETE FROM order_lines WHERE order_id = ? AND product_id = ?",
                    (order_id, product_id),
                )
            else:
                cursor = connection.execute(
                    """
                    UPDATE order_lines
                    SET quantity = ?, sent_quantity = MIN(sent_quantity, ?)
                    WHERE order_id = ? AND product_id = ?
                    """,
                    (quantity, quantity, order_id, product_id),
                )
            if cursor.rowcount != 1:
                raise TableError("El producto no está en la cuenta.")
            return self._read_order(connection, order_id)

    def remove_line(self, business_id: int, order_id: int, product_id: int) -> OpenOrder:
        return self.set_quantity(business_id, order_id, product_id, 0)

    def mark_sent(self, business_id: int, order_id: int) -> list[ComandaLine]:
        """Mark every unsent unit as sent and return what was newly sent."""
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_open_order(connection, business_id, order_id)
            order = self._read_order(connection, order_id)
            comanda = [
                ComandaLine(line.product_id, line.product_name, line.pending_quantity)
                for line in order.lines
                if line.pending_quantity > 0
            ]
            connection.execute(
                "UPDATE order_lines SET sent_quantity = quantity WHERE order_id = ?", (order_id,)
            )
        return comanda

    def transfer(self, business_id: int, order_id: int, target_table_id: int) -> OpenOrder:
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = self._require_open_order(connection, business_id, order_id)
            self._require_table(connection, business_id, target_table_id)
            if current["table_id"] == target_table_id:
                raise TableError("La cuenta ya está en esa mesa.")
            if self._open_order_id(connection, target_table_id) is not None:
                raise TableError("La mesa de destino ya tiene una cuenta abierta.")
            connection.execute(
                "UPDATE table_orders SET table_id = ? WHERE id = ?", (target_table_id, order_id)
            )
            return self._read_order(connection, order_id)

    def cancel(self, business_id: int, order_id: int) -> None:
        self._finish(business_id, order_id, "cancelled", None)

    def close(self, business_id: int, order_id: int, sale_id: int) -> None:
        self._finish(business_id, order_id, "closed", sale_id)

    @staticmethod
    def close_in(
        connection: sqlite3.Connection, business_id: int, order_id: int, sale_id: int
    ) -> None:
        """Close an order inside the caller's transaction; it must still be open.

        Meant for ``SaleRepository.register(on_registered=...)``: it opens no connection and no
        transaction, so a failure here rolls back the sale that is being registered.
        """
        cursor = connection.execute(
            """
            UPDATE table_orders
            SET status = 'closed', sale_id = ?, closed_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'open'
              AND table_id IN (SELECT id FROM tables WHERE business_id = ?)
            """,
            (sale_id, order_id, business_id),
        )
        if cursor.rowcount != 1:
            raise TableError(_ORDER_ALREADY_FINISHED)

    @staticmethod
    def read_order_in(connection: sqlite3.Connection, order_id: int) -> OpenOrder:
        """Read an order through the caller's connection, so it sees the caller's transaction."""
        return TablesRepository._read_order(connection, order_id)

    def get_order(self, business_id: int, order_id: int) -> OpenOrder:
        with self.database.connect() as connection:
            self._require_open_order(connection, business_id, order_id)
            return self._read_order(connection, order_id)

    def _finish(self, business_id: int, order_id: int, status: str, sale_id: int | None) -> None:
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_open_order(connection, business_id, order_id)
            connection.execute(
                """
                UPDATE table_orders
                SET status = ?, sale_id = ?, closed_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, sale_id, order_id),
            )

    @staticmethod
    def _require_id(row_id: int | None) -> int:
        if row_id is None:
            raise RuntimeError("No se pudo obtener el identificador de la cuenta.")
        return row_id

    @staticmethod
    def _require_table(connection: sqlite3.Connection, business_id: int, table_id: int) -> None:
        row = connection.execute(
            "SELECT 1 FROM tables WHERE id = ? AND business_id = ? AND active = 1",
            (table_id, business_id),
        ).fetchone()
        if row is None:
            raise TableError(_TABLE_MISSING)

    @staticmethod
    def _open_order_id(connection: sqlite3.Connection, table_id: int) -> int | None:
        row = connection.execute(
            "SELECT id FROM table_orders WHERE table_id = ? AND status = 'open'", (table_id,)
        ).fetchone()
        return None if row is None else int(row["id"])

    @staticmethod
    def _require_open_order(
        connection: sqlite3.Connection, business_id: int, order_id: int
    ) -> sqlite3.Row:
        row: sqlite3.Row | None = connection.execute(
            """
            SELECT o.id, o.table_id FROM table_orders o JOIN tables t ON t.id = o.table_id
            WHERE o.id = ? AND t.business_id = ? AND o.status = 'open'
            """,
            (order_id, business_id),
        ).fetchone()
        if row is None:
            raise TableError(_ORDER_NOT_OPEN)
        return row

    @staticmethod
    def _read_order(connection: sqlite3.Connection, order_id: int) -> OpenOrder:
        order = connection.execute(
            "SELECT id, table_id, opened_at FROM table_orders WHERE id = ?", (order_id,)
        ).fetchone()
        rows = connection.execute(
            """
            SELECT product_id, product_name, quantity, unit_price_cents, sent_quantity,
                   tax_rate_basis_points
            FROM order_lines WHERE order_id = ? ORDER BY id
            """,
            (order_id,),
        ).fetchall()
        lines = tuple(
            OrderLine(
                row["product_id"],
                row["product_name"],
                row["quantity"],
                row["unit_price_cents"],
                row["sent_quantity"],
                row["tax_rate_basis_points"],
            )
            for row in rows
        )
        return OpenOrder(order["id"], order["table_id"], order["opened_at"], lines)
