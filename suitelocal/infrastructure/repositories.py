import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from suitelocal.domain.business import normalize_sales_note_number
from suitelocal.domain.credit import (
    CARGO,
    CREDIT_METHOD,
    FIADO_MODULE,
    check_credit_available,
)
from suitelocal.domain.customers import Customer, CustomerData, CustomerHistory, Purchase
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
        *,
        business_id: int,
        user_id: int,
        sales_note_number: str | None = None,
        customer_id: int | None = None,
    ) -> int:
        """Register the sale and return its id.

        ``business_id`` and ``user_id`` are required: they decide which business may read the
        receipt and who the cashier on it is, so a sale never belongs to nobody.
        ``sales_note_number`` is the number of the handwritten sales note of a RIMPE popular
        business. ``customer_id`` links the sale to a customer of the same business.
        """
        validate_sale(sale)
        sales_note_number = normalize_sales_note_number(sales_note_number)
        with self.database.connect() as connection:
            # Take the write lock up front so concurrent sales cannot oversell.
            connection.execute("BEGIN IMMEDIATE")
            if customer_id is not None:
                _require_customer_of_business(connection, customer_id, business_id)
            credit_cents = sum(
                payment.amount_cents for payment in sale.payments if payment.method == CREDIT_METHOD
            )
            if credit_cents:
                _check_credit_sale(connection, business_id, customer_id, credit_cents)
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
                    subtotal_cents, tax_cents, tax_rate_basis_points, cash_session_id,
                    business_id, user_id, sales_note_number, customer_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    business_id,
                    user_id,
                    sales_note_number,
                    customer_id,
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
            if credit_cents and customer_id is not None:
                # Same transaction as the sale: the debt never exists without its sale.
                connection.execute(
                    """
                    INSERT INTO customer_ledger
                        (business_id, customer_id, kind, amount_cents, sale_id, user_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (business_id, customer_id, CARGO, credit_cents, sale_id, user_id),
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


_CUSTOMER_NOT_FOUND = "El cliente no existe."
_CUSTOMER_COLUMNS = (
    "id, business_id, id_type, id_number, full_name, phone, address, email, accepts_offers, "
    "active, created_at, credit_limit_cents"
)


def _customer_from_row(row: sqlite3.Row) -> Customer:
    return Customer(
        row["id"],
        row["business_id"],
        row["id_type"],
        row["id_number"],
        row["full_name"],
        row["phone"],
        row["address"],
        row["email"],
        bool(row["accepts_offers"]),
        bool(row["active"]),
        row["created_at"],
        row["credit_limit_cents"],
    )


def _check_credit_sale(
    connection: sqlite3.Connection,
    business_id: int,
    customer_id: int | None,
    credit_cents: int,
) -> None:
    """A credit sale needs the module on, a customer, and room under the customer's limit."""
    row = connection.execute(
        "SELECT enabled_modules, decimal_separator FROM business_settings WHERE business_id = ?",
        (business_id,),
    ).fetchone()
    modules = (row["enabled_modules"] if row is not None else "") or ""
    if FIADO_MODULE not in modules.split(","):
        raise ValueError("El fiado no está activado para este negocio.")
    if customer_id is None:
        raise ValueError("El fiado necesita un cliente seleccionado.")
    balance = connection.execute(
        """
        SELECT COALESCE(SUM(CASE kind WHEN 'cargo' THEN amount_cents ELSE -amount_cents END), 0)
               AS balance
        FROM customer_ledger WHERE business_id = ? AND customer_id = ?
        """,
        (business_id, customer_id),
    ).fetchone()["balance"]
    limit = connection.execute(
        "SELECT credit_limit_cents FROM customers WHERE id = ?", (customer_id,)
    ).fetchone()["credit_limit_cents"]
    separator = (row["decimal_separator"] if row is not None else None) or ","
    check_credit_available(balance, credit_cents, limit, separator)


def _require_customer_of_business(
    connection: sqlite3.Connection, customer_id: int, business_id: int
) -> None:
    owned = connection.execute(
        "SELECT 1 FROM customers WHERE id = ? AND business_id = ?", (customer_id, business_id)
    ).fetchone()
    if owned is None:
        raise ValueError(_CUSTOMER_NOT_FOUND)


class CustomerRepository:
    """Customers of one business; every method is scoped by ``business_id``."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def get(self, business_id: int, customer_id: int) -> Customer | None:
        with self.database.connect() as connection:
            row = connection.execute(
                f"SELECT {_CUSTOMER_COLUMNS} FROM customers WHERE id = ? AND business_id = ?",
                (customer_id, business_id),
            ).fetchone()
        return None if row is None else _customer_from_row(row)

    def find_active_by_id_number(self, business_id: int, id_number: str) -> Customer | None:
        with self.database.connect() as connection:
            row = connection.execute(
                f"SELECT {_CUSTOMER_COLUMNS} FROM customers "
                "WHERE business_id = ? AND id_number = ? AND active = 1",
                (business_id, id_number),
            ).fetchone()
        return None if row is None else _customer_from_row(row)

    def list_active(self, business_id: int) -> list[Customer]:
        with self.database.connect() as connection:
            rows = connection.execute(
                f"SELECT {_CUSTOMER_COLUMNS} FROM customers "
                "WHERE business_id = ? AND active = 1 ORDER BY id",
                (business_id,),
            ).fetchall()
        return [_customer_from_row(row) for row in rows]

    def add(self, business_id: int, data: CustomerData) -> Customer:
        try:
            with self.database.connect() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO customers
                        (business_id, id_type, id_number, full_name, phone, address, email,
                         accepts_offers, credit_limit_cents)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (business_id, *_customer_values(data)),
                )
                row = connection.execute(
                    f"SELECT {_CUSTOMER_COLUMNS} FROM customers WHERE id = ?", (cursor.lastrowid,)
                ).fetchone()
        except sqlite3.IntegrityError as error:
            raise self._translate(business_id, data.id_number, error) from error
        return _customer_from_row(row)

    def update(self, business_id: int, customer_id: int, data: CustomerData) -> Customer:
        try:
            with self.database.connect() as connection:
                updated = connection.execute(
                    """
                    UPDATE customers
                    SET id_type = ?, id_number = ?, full_name = ?, phone = ?, address = ?,
                        email = ?, accepts_offers = ?, credit_limit_cents = ?
                    WHERE id = ? AND business_id = ?
                    """,
                    (*_customer_values(data), customer_id, business_id),
                )
                if updated.rowcount != 1:
                    raise ValueError(_CUSTOMER_NOT_FOUND)
                row = connection.execute(
                    f"SELECT {_CUSTOMER_COLUMNS} FROM customers WHERE id = ?", (customer_id,)
                ).fetchone()
        except sqlite3.IntegrityError as error:
            raise self._translate(business_id, data.id_number, error) from error
        return _customer_from_row(row)

    def deactivate(self, business_id: int, customer_id: int) -> None:
        with self.database.connect() as connection:
            updated = connection.execute(
                "UPDATE customers SET active = 0 WHERE id = ? AND business_id = ?",
                (customer_id, business_id),
            )
            if updated.rowcount != 1:
                raise ValueError(_CUSTOMER_NOT_FOUND)

    def history(self, business_id: int, customer_id: int, limit: int) -> CustomerHistory:
        with self.database.connect() as connection:
            _require_customer_of_business(connection, customer_id, business_id)
            totals = connection.execute(
                """
                SELECT COUNT(*) AS purchase_count, COALESCE(SUM(total_cents), 0) AS total_cents
                FROM sales WHERE customer_id = ? AND business_id = ?
                """,
                (customer_id, business_id),
            ).fetchone()
            rows = connection.execute(
                """
                SELECT id, created_at, total_cents FROM sales
                WHERE customer_id = ? AND business_id = ?
                ORDER BY created_at DESC, id DESC LIMIT ?
                """,
                (customer_id, business_id, limit),
            ).fetchall()
        purchases = tuple(
            Purchase(
                row["id"],
                datetime.fromisoformat(row["created_at"]).replace(tzinfo=UTC),
                row["total_cents"],
            )
            for row in rows
        )
        return CustomerHistory(purchases, totals["purchase_count"], totals["total_cents"])

    def offer_recipients(self, business_id: int) -> list[Customer]:
        with self.database.connect() as connection:
            rows = connection.execute(
                f"SELECT {_CUSTOMER_COLUMNS} FROM customers "
                "WHERE business_id = ? AND active = 1 AND accepts_offers = 1 AND email <> '' "
                "ORDER BY id",
                (business_id,),
            ).fetchall()
        return [_customer_from_row(row) for row in rows]

    def _translate(
        self, business_id: int, id_number: str, error: sqlite3.IntegrityError
    ) -> ValueError | sqlite3.IntegrityError:
        """A taken identification becomes a message that names the customer who holds it."""
        if "customers.id_number" not in str(error):
            return error
        with self.database.connect() as connection:
            existing = connection.execute(
                "SELECT full_name, active FROM customers WHERE business_id = ? AND id_number = ?",
                (business_id, id_number),
            ).fetchone()
        name = "" if existing is None else existing["full_name"]
        note = " (está desactivado)" if existing is not None and not existing["active"] else ""
        return ValueError(f"Ya existe un cliente con esa identificación: {name}{note}.")


def _customer_values(data: CustomerData) -> tuple[str | int | None, ...]:
    return (
        data.id_type,
        data.id_number,
        data.full_name,
        data.phone,
        data.address,
        data.email,
        int(data.accepts_offers),
        data.credit_limit_cents,
    )
