"""Bulk product import: reads what the preview needs and writes the whole plan at once."""

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass

from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import CategoryRepository


@dataclass(frozen=True, slots=True)
class ProductImportRow:
    """One valid CSV row. ``None`` means the file gave no value for that optional column."""

    line: int
    code: str
    name: str
    price_cents: int
    stock: int
    category: str | None = None
    cost_cents: int | None = None
    tax_rate_basis_points: int | None = None


def nocase_key(name: str) -> str:
    """Category identity as the database sees it: SQLite NOCASE folds ASCII letters only."""
    return "".join(char.lower() if char.isascii() else char for char in name.strip())


class ProductImportRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def product_states(self) -> dict[str, bool]:
        """Every stored product code with whether the product is active."""
        with self.database.connect() as connection:
            rows = connection.execute("SELECT code, active FROM products").fetchall()
        return {row["code"]: bool(row["active"]) for row in rows}

    def category_keys(self, business_id: int) -> set[str]:
        """The categories of the business, inactive ones included, as ``nocase_key`` values."""
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT name FROM categories WHERE business_id = ?", (business_id,)
            ).fetchall()
        return {nocase_key(row["name"]) for row in rows}

    def apply(
        self,
        business_id: int,
        categories: Sequence[str],
        to_create: Sequence[ProductImportRow],
        to_update: Sequence[ProductImportRow],
        default_tax_rate: int,
    ) -> None:
        """Create the categories, insert the new products and update the existing ones.

        One transaction: any failure rolls everything back. The plan is checked again here,
        since the data may have changed since the preview.
        """
        with self.database.connect() as connection:
            # Take the write lock up front so nobody changes the data under the checks.
            connection.execute("BEGIN IMMEDIATE")
            CategoryRepository(self.database).add_missing(
                business_id, tuple(categories), connection
            )
            for row in to_create:
                self._insert(connection, business_id, row, default_tax_rate)
            for row in to_update:
                self._update(connection, business_id, row)

    @classmethod
    def _insert(
        cls,
        connection: sqlite3.Connection,
        business_id: int,
        row: ProductImportRow,
        default_tax_rate: int,
    ) -> None:
        exists = connection.execute("SELECT 1 FROM products WHERE code = ?", (row.code,)).fetchone()
        if exists is not None:
            raise ValueError(f"Línea {row.line}: ya existe un producto con el código {row.code}.")
        rate = default_tax_rate if row.tax_rate_basis_points is None else row.tax_rate_basis_points
        connection.execute(
            """
            INSERT INTO products
                (code, name, price_cents, stock, category_id, cost_cents, tax_rate_basis_points)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row.code,
                row.name,
                row.price_cents,
                row.stock,
                cls._category_id(connection, business_id, row.category),
                row.cost_cents,
                rate,
            ),
        )

    @classmethod
    def _update(
        cls, connection: sqlite3.Connection, business_id: int, row: ProductImportRow
    ) -> None:
        assignments = ["name = ?", "price_cents = ?", "stock = ?"]
        values: list[str | int | None] = [row.name, row.price_cents, row.stock]
        # A column the file left blank keeps its stored value.
        if row.category is not None:
            assignments.append("category_id = ?")
            values.append(cls._category_id(connection, business_id, row.category))
        if row.cost_cents is not None:
            assignments.append("cost_cents = ?")
            values.append(row.cost_cents)
        if row.tax_rate_basis_points is not None:
            assignments.append("tax_rate_basis_points = ?")
            values.append(row.tax_rate_basis_points)
        cursor = connection.execute(
            f"UPDATE products SET {', '.join(assignments)} WHERE code = ? AND active = 1",
            (*values, row.code),
        )
        if cursor.rowcount != 1:
            raise ValueError(f"Línea {row.line}: el producto {row.code} ya no está disponible.")

    @staticmethod
    def _category_id(
        connection: sqlite3.Connection, business_id: int, name: str | None
    ) -> int | None:
        if name is None:
            return None
        found = connection.execute(
            "SELECT id FROM categories WHERE business_id = ? AND name = ? COLLATE NOCASE",
            (business_id, name.strip()),
        ).fetchone()
        if found is None:
            raise ValueError(f"La categoría {name} no existe.")
        return found["id"]
