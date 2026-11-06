import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from suitelocal.domain.models import KEEP, Keep, Product, Sale, validate_sale
from suitelocal.domain.tax import DEFAULT_TAX_RATE_BASIS_POINTS, validate_tax_rate
from suitelocal.infrastructure.database import Database

CATEGORY_NAME_MAX_LENGTH = 40

_PRODUCT_COLUMNS = (
    "id, code, name, price_cents, stock, category_id, cost_cents, tax_rate_basis_points"
)


def _product_from_row(row: sqlite3.Row) -> Product:
    return Product(
        row["id"],
        row["code"],
        row["name"],
        row["price_cents"],
        row["stock"],
        row["category_id"],
        row["cost_cents"],
        row["tax_rate_basis_points"],
    )


def _validate_product_values(
    code: str, name: str, price_cents: int, stock: int, cost_cents: int | None
) -> None:
    if not code.strip() or not name.strip():
        raise ValueError("El código y el nombre son obligatorios.")
    if price_cents < 0 or stock < 0:
        raise ValueError("El precio y el stock no pueden ser negativos.")
    if cost_cents is not None and cost_cents < 0:
        raise ValueError("El costo no puede ser negativo.")


def _translate_integrity_error(error: sqlite3.IntegrityError) -> ValueError | None:
    message = str(error)
    if "UNIQUE constraint failed: products.code" in message:
        return ValueError("Ya existe un producto con ese código.")
    if "FOREIGN KEY constraint failed" in message:
        return ValueError("La categoría seleccionada no existe.")
    return None


def _require_category_of_business(
    connection: sqlite3.Connection, category_id: int | None, business_id: int | None
) -> None:
    """Reject a category the business does not own; callers without a business skip the check."""
    if category_id is None or business_id is None:
        return
    owned = connection.execute(
        "SELECT 1 FROM categories WHERE id = ? AND business_id = ?", (category_id, business_id)
    ).fetchone()
    if owned is None:
        raise ValueError("La categoría seleccionada no existe.")


def _default_tax_rate(connection: sqlite3.Connection) -> int:
    """Business default for new products; 15 % when unset or not a legal rate."""
    row = connection.execute(
        "SELECT tax_rate_basis_points FROM business_settings ORDER BY business_id LIMIT 1"
    ).fetchone()
    if row is None or row["tax_rate_basis_points"] not in (1500, 500, 0):
        return DEFAULT_TAX_RATE_BASIS_POINTS
    return row["tax_rate_basis_points"]


class ProductRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def add(
        self,
        code: str,
        name: str,
        price_cents: int,
        stock: int,
        category_id: int | None = None,
        cost_cents: int | None = None,
        tax_rate_basis_points: int | None = None,
        business_id: int | None = None,
    ) -> Product:
        """Create a product; without a rate it gets the business default for new products.

        With ``business_id`` the category must belong to that business.
        """
        _validate_product_values(code, name, price_cents, stock, cost_cents)
        if tax_rate_basis_points is not None:
            validate_tax_rate(tax_rate_basis_points)
        try:
            with self.database.connect() as connection:
                _require_category_of_business(connection, category_id, business_id)
                if tax_rate_basis_points is None:
                    tax_rate_basis_points = _default_tax_rate(connection)
                cursor = connection.execute(
                    """
                    INSERT INTO products
                        (code, name, price_cents, stock, category_id, cost_cents,
                         tax_rate_basis_points)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        code.strip(),
                        name.strip(),
                        price_cents,
                        stock,
                        category_id,
                        cost_cents,
                        tax_rate_basis_points,
                    ),
                )
                product_id = cursor.lastrowid
                if product_id is None:
                    raise RuntimeError("No se pudo obtener el identificador del producto.")
        except sqlite3.IntegrityError as error:
            translated = _translate_integrity_error(error)
            if translated is not None:
                raise translated from error
            raise
        return Product(
            product_id,
            code.strip(),
            name.strip(),
            price_cents,
            stock,
            category_id,
            cost_cents,
            tax_rate_basis_points,
        )

    def find_active(self, search: str = "") -> list[Product]:
        pattern = f"%{search.strip()}%"
        with self.database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT {_PRODUCT_COLUMNS}
                FROM products
                WHERE active = 1 AND (code LIKE ? OR name LIKE ?)
                ORDER BY name
                """,
                (pattern, pattern),
            ).fetchall()
        return [_product_from_row(row) for row in rows]

    def update(
        self,
        product_id: int,
        code: str,
        name: str,
        price_cents: int,
        stock: int,
        category_id: int | None | Keep = KEEP,
        cost_cents: int | None | Keep = KEEP,
        tax_rate_basis_points: int | Keep = KEEP,
        business_id: int | None = None,
    ) -> Product:
        """Update a product; category, cost and rate are left alone unless given.

        With ``business_id`` a given category must belong to that business.
        """
        _validate_product_values(
            code, name, price_cents, stock, None if isinstance(cost_cents, Keep) else cost_cents
        )
        if not isinstance(tax_rate_basis_points, Keep):
            validate_tax_rate(tax_rate_basis_points)
        try:
            with self.database.connect() as connection:
                if not isinstance(category_id, Keep):
                    _require_category_of_business(connection, category_id, business_id)
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
                if not isinstance(category_id, Keep):
                    connection.execute(
                        "UPDATE products SET category_id = ? WHERE id = ?",
                        (category_id, product_id),
                    )
                if not isinstance(cost_cents, Keep):
                    connection.execute(
                        "UPDATE products SET cost_cents = ? WHERE id = ?", (cost_cents, product_id)
                    )
                if not isinstance(tax_rate_basis_points, Keep):
                    connection.execute(
                        "UPDATE products SET tax_rate_basis_points = ? WHERE id = ?",
                        (tax_rate_basis_points, product_id),
                    )
                row = connection.execute(
                    f"SELECT {_PRODUCT_COLUMNS} FROM products WHERE id = ?", (product_id,)
                ).fetchone()
        except sqlite3.IntegrityError as error:
            translated = _translate_integrity_error(error)
            if translated is not None:
                raise translated from error
            raise
        return _product_from_row(row)

    def deactivate(self, product_id: int) -> None:
        with self.database.connect() as connection:
            connection.execute("UPDATE products SET active = 0 WHERE id = ?", (product_id,))


@dataclass(frozen=True, slots=True)
class Category:
    id: int
    business_id: int
    name: str
    active: bool = True


def _category_from_row(row: sqlite3.Row) -> Category:
    return Category(row["id"], row["business_id"], row["name"], bool(row["active"]))


def _validate_category_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise ValueError("El nombre de la categoría es obligatorio.")
    if len(name) > CATEGORY_NAME_MAX_LENGTH:
        raise ValueError(
            f"El nombre de la categoría no puede superar {CATEGORY_NAME_MAX_LENGTH} caracteres."
        )
    return name


class CategoryRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list(self, business_id: int, include_inactive: bool = False) -> list[Category]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, business_id, name, active FROM categories
                WHERE business_id = ? AND (active = 1 OR ?)
                ORDER BY name COLLATE NOCASE
                """,
                (business_id, include_inactive),
            ).fetchall()
        return [_category_from_row(row) for row in rows]

    def add(self, business_id: int, name: str) -> Category:
        name = _validate_category_name(name)
        with self.database.connect() as connection:
            return self._insert(connection, business_id, name)

    def add_missing(
        self,
        business_id: int,
        names: tuple[str, ...],
        connection: sqlite3.Connection | None = None,
    ) -> None:
        """Create the categories the business lacks; existing ones (even inactive) stay as is.

        With ``connection`` the inserts join the caller's transaction instead of their own.
        """
        valid_names = [_validate_category_name(name) for name in names]
        if connection is not None:
            self._insert_missing(connection, business_id, valid_names)
            return
        with self.database.connect() as own_connection:
            self._insert_missing(own_connection, business_id, valid_names)

    def _insert_missing(
        self, connection: sqlite3.Connection, business_id: int, names: Sequence[str]
    ) -> None:
        for name in names:
            exists = connection.execute(
                "SELECT 1 FROM categories WHERE business_id = ? AND name = ? COLLATE NOCASE",
                (business_id, name),
            ).fetchone()
            if exists is None:
                self._insert(connection, business_id, name)

    def rename(self, business_id: int, category_id: int, name: str) -> Category:
        name = _validate_category_name(name)
        try:
            with self.database.connect() as connection:
                cursor = connection.execute(
                    "UPDATE categories SET name = ? WHERE id = ? AND business_id = ?",
                    (name, category_id, business_id),
                )
                if cursor.rowcount != 1:
                    raise ValueError("La categoría no existe.")
                row = connection.execute(
                    "SELECT id, business_id, name, active FROM categories WHERE id = ?",
                    (category_id,),
                ).fetchone()
        except sqlite3.IntegrityError as error:
            raise ValueError("Ya existe una categoría con ese nombre.") from error
        return _category_from_row(row)

    def set_active(self, business_id: int, category_id: int, active: bool) -> None:
        with self.database.connect() as connection:
            cursor = connection.execute(
                "UPDATE categories SET active = ? WHERE id = ? AND business_id = ?",
                (1 if active else 0, category_id, business_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("La categoría no existe.")

    def delete(self, business_id: int, category_id: int) -> None:
        with self.database.connect() as connection:
            owned = connection.execute(
                "SELECT 1 FROM categories WHERE id = ? AND business_id = ?",
                (category_id, business_id),
            ).fetchone()
            if owned is None:
                raise ValueError("La categoría no existe.")
            used = connection.execute(
                "SELECT 1 FROM products WHERE category_id = ? LIMIT 1", (category_id,)
            ).fetchone()
            if used is not None:
                raise ValueError(
                    "La categoría tiene productos; desactivala en lugar de eliminarla."
                )
            connection.execute("DELETE FROM categories WHERE id = ?", (category_id,))

    @staticmethod
    def _insert(connection: sqlite3.Connection, business_id: int, name: str) -> Category:
        try:
            cursor = connection.execute(
                "INSERT INTO categories (business_id, name) VALUES (?, ?)", (business_id, name)
            )
        except sqlite3.IntegrityError as error:
            if "UNIQUE constraint failed" in str(error):
                raise ValueError("Ya existe una categoría con ese nombre.") from error
            raise ValueError("El negocio de la categoría no existe.") from error
        if cursor.lastrowid is None:
            raise RuntimeError("No se pudo obtener el identificador de la categoría.")
        return Category(cursor.lastrowid, business_id, name)


class SaleRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def register(
        self,
        sale: Sale,
        on_registered: Callable[[sqlite3.Connection, int], None] | None = None,
    ) -> int:
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
                    # A sale can mix rates, so this legacy single-rate column stays 0; the
                    # per-line rate and IVA in sale_items are the source of truth.
                    0,
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
                        (sale_id, product_id, product_name, quantity, unit_price_cents,
                         tax_rate_basis_points, tax_cents)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sale_id,
                        item.product_id,
                        item.product_name,
                        item.quantity,
                        item.unit_price_cents,
                        item.tax_rate_basis_points,
                        item.tax_cents,
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
            # Runs in the same transaction: if it raises, the whole sale rolls back.
            if on_registered is not None:
                on_registered(connection, sale_id)
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
