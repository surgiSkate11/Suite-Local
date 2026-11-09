import csv
import os
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, fields, is_dataclass
from datetime import date
from pathlib import Path

from suitelocal.domain.auth import Session
from suitelocal.domain.policies import require_owner
from suitelocal.infrastructure.database import Database

CSV_DELIMITER = ";"

# Spanish column labels used in exported files, keyed by row field name.
CSV_LABELS = {
    "day": "Fecha",
    "sale_count": "Ventas",
    "total_cents": "Total",
    "tax_cents": "IVA",
    "product_name": "Producto",
    "quantity": "Cantidad",
    "revenue_cents": "Ingresos",
    "method": "Forma de pago",
    "payment_count": "Pagos",
    "amount_cents": "Monto",
}


@dataclass(frozen=True, slots=True)
class DaySales:
    day: date
    sale_count: int
    total_cents: int
    tax_cents: int


@dataclass(frozen=True, slots=True)
class ProductSales:
    product_name: str
    quantity: int
    revenue_cents: int


@dataclass(frozen=True, slots=True)
class MethodPayments:
    method: str
    payment_count: int
    amount_cents: int


class ReportService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def sales_by_day(self, session: Session, start: date, end: date) -> list[DaySales]:
        _validate_range(session, start, end)
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT date(created_at, 'localtime') AS day,
                       COUNT(*) AS sale_count,
                       COALESCE(SUM(total_cents), 0) AS total_cents,
                       COALESCE(SUM(tax_cents), 0) AS tax_cents
                FROM sales
                WHERE date(created_at, 'localtime') BETWEEN ? AND ?
                GROUP BY day
                ORDER BY day
                """,
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        return [
            DaySales(
                date.fromisoformat(row["day"]),
                row["sale_count"],
                row["total_cents"],
                row["tax_cents"],
            )
            for row in rows
        ]

    def top_products(
        self, session: Session, start: date, end: date, limit: int = 10
    ) -> list[ProductSales]:
        _validate_range(session, start, end)
        if limit < 1:
            raise ValueError("El límite debe ser al menos 1.")
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT si.product_name AS product_name,
                       SUM(si.quantity) AS quantity,
                       SUM(si.quantity * si.unit_price_cents) AS revenue_cents
                FROM sale_items si
                JOIN sales s ON s.id = si.sale_id
                WHERE date(s.created_at, 'localtime') BETWEEN ? AND ?
                GROUP BY si.product_name
                ORDER BY quantity DESC, revenue_cents DESC, si.product_name
                LIMIT ?
                """,
                (start.isoformat(), end.isoformat(), limit),
            ).fetchall()
        return [
            ProductSales(row["product_name"], row["quantity"], row["revenue_cents"]) for row in rows
        ]

    def payments_by_method(self, session: Session, start: date, end: date) -> list[MethodPayments]:
        _validate_range(session, start, end)
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT sp.method AS method,
                       COUNT(*) AS payment_count,
                       SUM(sp.amount_cents) AS amount_cents
                FROM sale_payments sp
                JOIN sales s ON s.id = sp.sale_id
                WHERE date(s.created_at, 'localtime') BETWEEN ? AND ?
                GROUP BY sp.method
                ORDER BY amount_cents DESC, sp.method
                """,
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        return [
            MethodPayments(row["method"], row["payment_count"], row["amount_cents"]) for row in rows
        ]


def export_csv(rows: Sequence[object], path: Path | str, row_type: type | None = None) -> Path:
    """Write report rows as a CSV that opens correctly in Spanish-locale Excel.

    ``row_type`` is only needed for an empty ``rows`` so the header can still be written.
    """
    target = Path(path)
    kind = type(rows[0]) if rows else row_type
    if kind is None:
        raise ValueError("Indique el tipo de fila para exportar un reporte vacío.")
    if not is_dataclass(kind):
        raise ValueError("Las filas a exportar no son válidas.")
    names = [field.name for field in fields(kind)]

    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter=CSV_DELIMITER)
            writer.writerow([CSV_LABELS.get(name, name) for name in names])
            for row in rows:
                writer.writerow([_format_cell(name, getattr(row, name)) for name in names])
        os.replace(temp_name, target)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
    return target


def _validate_range(session: Session, start: date, end: date) -> None:
    require_owner(session)
    if start > end:
        raise ValueError("La fecha inicial no puede ser posterior a la fecha final.")


PAYMENT_METHOD_LABELS = {
    "cash": "Efectivo",
    "transfer": "Transferencia",
    "card": "Tarjeta",
    "credit": "Fiado",
}


def _format_cell(name: str, value: object) -> str:
    if name == "method" and isinstance(value, str):
        return PAYMENT_METHOD_LABELS.get(value, value)
    if name.endswith("_cents") and isinstance(value, int):
        sign = "-" if value < 0 else ""
        pesos, cents = divmod(abs(value), 100)
        return f"{sign}{pesos},{cents:02d}"
    if isinstance(value, date):
        return value.isoformat()
    return str(value)
