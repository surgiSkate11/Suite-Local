import sqlite3

from suitelocal.domain.models import Product, Sale, validate_sale
from suitelocal.infrastructure.database import Database


class ProductRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def add(self, code: str, name: str, price_cents: int, stock: int) -> Product:
        if not code.strip() or not name.strip():
            raise ValueError("El código y el nombre son obligatorios.")
        if price_cents < 0 or stock < 0:
            raise ValueError("El precio y el stock no pueden ser negativos.")
        try:
            with self.database.connect() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO products (code, name, price_cents, stock)
                    VALUES (?, ?, ?, ?)
                    """,
                    (code.strip(), name.strip(), price_cents, stock),
                )
                product_id = cursor.lastrowid
                if product_id is None:
                    raise RuntimeError("No se pudo obtener el identificador del producto.")
        except sqlite3.IntegrityError as error:
            if "UNIQUE constraint failed: products.code" in str(error):
                raise ValueError("Ya existe un producto con ese código.") from error
            raise
        return Product(product_id, code.strip(), name.strip(), price_cents, stock)

    def find_active(self, search: str = "") -> list[Product]:
        pattern = f"%{search.strip()}%"
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, code, name, price_cents, stock
                FROM products
                WHERE active = 1 AND (code LIKE ? OR name LIKE ?)
                ORDER BY name
                """,
                (pattern, pattern),
            ).fetchall()
        return [
            Product(row["id"], row["code"], row["name"], row["price_cents"], row["stock"])
            for row in rows
        ]

    def update(
        self, product_id: int, code: str, name: str, price_cents: int, stock: int
    ) -> Product:
        if not code.strip() or not name.strip():
            raise ValueError("El código y el nombre son obligatorios.")
        if price_cents < 0 or stock < 0:
            raise ValueError("El precio y el stock no pueden ser negativos.")
        try:
            with self.database.connect() as connection:
                cursor = connection.execute(
                    """
                    UPDATE products
                    SET code = ?, name = ?, price_cents = ?, stock = ?
                    WHERE id = ? AND active = 1
                    """,
                    (code.strip(), name.strip(), price_cents, stock, product_id),
                )
                if cursor.rowcount != 1:
                    raise ValueError("El producto ya no está disponible.")
        except sqlite3.IntegrityError as error:
            if "UNIQUE constraint failed: products.code" in str(error):
                raise ValueError("Ya existe un producto con ese código.") from error
            raise
        return Product(product_id, code.strip(), name.strip(), price_cents, stock)

    def deactivate(self, product_id: int) -> None:
        with self.database.connect() as connection:
            connection.execute("UPDATE products SET active = 0 WHERE id = ?", (product_id,))


class SaleRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def register(self, sale: Sale) -> int:
        validate_sale(sale)
        with self.database.connect() as connection:
            # Take the write lock up front so concurrent sales cannot oversell.
            connection.execute("BEGIN IMMEDIATE")
            for item in sale.items:
                row = connection.execute(
                    "SELECT stock FROM products WHERE id = ? AND active = 1",
                    (item.product_id,),
                ).fetchone()
                if row is None:
                    raise ValueError(f"El producto {item.product_name} ya no está disponible.")
                if row["stock"] < item.quantity:
                    raise ValueError(f"Stock insuficiente para {item.product_name}.")

            # The installation has a single business, so the open session is unambiguous.
            open_session = connection.execute(
                "SELECT id FROM cash_sessions WHERE closed_at IS NULL ORDER BY id DESC LIMIT 1"
            ).fetchone()
            cursor = connection.execute(
                """
                INSERT INTO sales (
                    total_cents, payment_cents, change_cents,
                    subtotal_cents, tax_cents, tax_rate_basis_points, cash_session_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sale.total_cents,
                    sale.payment_cents,
                    sale.change_cents,
                    sale.subtotal_cents,
                    sale.tax_cents,
                    sale.tax_rate_basis_points,
                    None if open_session is None else open_session["id"],
                ),
            )
            sale_id = cursor.lastrowid
            if sale_id is None:
                raise RuntimeError("No se pudo obtener el identificador de la venta.")
            for item in sale.items:
                connection.execute(
                    """
                    INSERT INTO sale_items
                        (sale_id, product_id, product_name, quantity, unit_price_cents)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        sale_id,
                        item.product_id,
                        item.product_name,
                        item.quantity,
                        item.unit_price_cents,
                    ),
                )
                updated = connection.execute(
                    """
                    UPDATE products SET stock = stock - ?
                    WHERE id = ? AND active = 1 AND stock >= ?
                    """,
                    (item.quantity, item.product_id, item.quantity),
                )
                if updated.rowcount != 1:
                    raise ValueError(f"Stock insuficiente para {item.product_name}.")
            for payment in sale.payments:
                connection.execute(
                    """
                    INSERT INTO sale_payments (sale_id, method, amount_cents, reference)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        sale_id,
                        payment.method,
                        payment.amount_cents,
                        payment.reference.strip(),
                    ),
                )
        return sale_id

    def today_summary(self) -> tuple[int, int]:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS sale_count, COALESCE(SUM(total_cents), 0) AS revenue
                FROM sales
                WHERE date(created_at, 'localtime') = date('now', 'localtime')
                """
            ).fetchone()
        return row["sale_count"], row["revenue"]
