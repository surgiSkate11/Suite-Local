from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from suitelocal.application.reports import (
    DaySales,
    MethodPayments,
    ProductSales,
    ReportService,
    export_csv,
)
from suitelocal.domain.auth import Session, User
from suitelocal.domain.models import Payment, Sale, SaleItem
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import ProductRepository, SaleRepository

OWNER = Session(User(1, 1, "owner", "owner", True))
CASHIER = Session(User(2, 1, "cashier", "cashier", True))

DAY_1 = date(2026, 3, 10)
DAY_2 = date(2026, 3, 11)
DAY_3 = date(2026, 3, 12)


class Seed:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.products = ProductRepository(database)
        self.sales = SaleRepository(database)

    def sell(self, day: date, lines: list[tuple[str, int]], *payments: Payment, tax: int = 0):
        """Register a sale and move it to local noon of the given day."""
        items = tuple(
            SaleItem(product.id, product.name, quantity, product.price_cents)
            for code, quantity in lines
            for product in self.products.find_active(code)
            if product.code == code
        )
        subtotal = sum(item.total_cents for item in items)
        total = subtotal + round(subtotal * tax / 10000)
        sale_payments = payments or (Payment("cash", total),)
        sale_id = self.sales.register(
            Sale(items, total, payments=sale_payments, tax_rate_basis_points=tax)
        )
        local_noon = datetime(day.year, day.month, day.day, 12).astimezone(UTC)
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE sales SET created_at = ? WHERE id = ?",
                (local_noon.strftime("%Y-%m-%d %H:%M:%S"), sale_id),
            )
        return sale_id


@pytest.fixture
def database(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    return database


@pytest.fixture
def seed(database):
    seed = Seed(database)
    seed.products.add("A-1", "Arroz", 250, 100)
    seed.products.add("B-1", "Bebida", 1000, 100)
    seed.products.add("C-1", "Café", 400, 100)
    return seed


@pytest.fixture
def reports(database):
    return ReportService(database)


def test_sales_by_day_totals_and_skips_empty_days(seed, reports):
    seed.sell(DAY_1, [("A-1", 2)])  # 500
    seed.sell(DAY_1, [("B-1", 1)], tax=1000)  # 1000 + 100 tax
    seed.sell(DAY_3, [("C-1", 1)])  # 400

    rows = reports.sales_by_day(OWNER, DAY_1, DAY_3)

    assert rows == [
        DaySales(DAY_1, 2, 1600, 100),
        DaySales(DAY_3, 1, 400, 0),
    ]


def test_sales_by_day_range_is_inclusive_and_excludes_outside(seed, reports):
    seed.sell(DAY_1, [("A-1", 1)])
    seed.sell(DAY_2, [("A-1", 2)])
    seed.sell(DAY_3, [("A-1", 3)])

    assert reports.sales_by_day(OWNER, DAY_1, DAY_1) == [DaySales(DAY_1, 1, 250, 0)]
    assert reports.sales_by_day(OWNER, DAY_2, DAY_3) == [
        DaySales(DAY_2, 1, 500, 0),
        DaySales(DAY_3, 1, 750, 0),
    ]
    assert reports.sales_by_day(OWNER, date(2026, 4, 1), date(2026, 4, 2)) == []


def test_top_products_orders_by_quantity_then_revenue(seed, reports):
    seed.sell(DAY_1, [("A-1", 4), ("B-1", 1)])  # Arroz 4 / 1000, Bebida 1 / 1000
    seed.sell(DAY_2, [("C-1", 2), ("B-1", 1)])  # Café 2 / 800, Bebida +1 / +1000
    seed.sell(DAY_3, [("A-1", 9)])  # outside the range below

    rows = reports.top_products(OWNER, DAY_1, DAY_2)

    assert rows == [
        ProductSales("Arroz", 4, 1000),
        ProductSales("Bebida", 2, 2000),
        ProductSales("Café", 2, 800),
    ]


def test_top_products_respects_limit(seed, reports):
    seed.sell(DAY_1, [("A-1", 3), ("B-1", 2), ("C-1", 1)])

    rows = reports.top_products(OWNER, DAY_1, DAY_1, limit=2)

    assert [row.product_name for row in rows] == ["Arroz", "Bebida"]


def test_payments_by_method_splits_amounts(seed, reports):
    seed.sell(DAY_1, [("B-1", 1)], Payment("cash", 600), Payment("card", 400))
    seed.sell(DAY_2, [("B-1", 1)], Payment("card", 1000))
    seed.sell(DAY_3, [("B-1", 1)], Payment("transfer", 1000, "REF-1"))

    rows = reports.payments_by_method(OWNER, DAY_1, DAY_2)

    assert rows == [
        MethodPayments("card", 2, 1400),
        MethodPayments("cash", 1, 600),
    ]


def test_start_after_end_is_rejected(reports):
    with pytest.raises(ValueError, match="fecha inicial"):
        reports.sales_by_day(OWNER, DAY_2, DAY_1)
    with pytest.raises(ValueError, match="fecha inicial"):
        reports.top_products(OWNER, DAY_2, DAY_1)
    with pytest.raises(ValueError, match="fecha inicial"):
        reports.payments_by_method(OWNER, DAY_2, DAY_1)


@pytest.mark.parametrize("limit", [0, -1])
def test_limit_below_one_is_rejected(reports, limit):
    with pytest.raises(ValueError, match="límite"):
        reports.top_products(OWNER, DAY_1, DAY_2, limit=limit)


def test_cashier_cannot_read_reports(seed, reports):
    seed.sell(DAY_1, [("A-1", 1)])

    with pytest.raises(PermissionError, match="Solo el dueño puede realizar esta acción."):
        reports.sales_by_day(CASHIER, DAY_1, DAY_2)
    with pytest.raises(PermissionError, match="Solo el dueño puede realizar esta acción."):
        reports.top_products(CASHIER, DAY_1, DAY_2)
    with pytest.raises(PermissionError, match="Solo el dueño puede realizar esta acción."):
        reports.payments_by_method(CASHIER, DAY_1, DAY_2)


def test_export_csv_content_is_excel_friendly(tmp_path):
    path = tmp_path / "ventas.csv"
    rows = [DaySales(DAY_1, 2, 123456, 1234), DaySales(DAY_2, 1, 5, 0)]

    result = export_csv(rows, path)

    assert result == path
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert raw.decode("utf-8-sig") == (
        "Fecha;Ventas;Total;IVA\r\n2026-03-10;2;1234,56;12,34\r\n2026-03-11;1;0,05;0,00\r\n"
    )


def test_export_csv_translates_product_and_payment_headers(tmp_path):
    products = export_csv([ProductSales("Café; con leche", 3, 1050)], tmp_path / "p.csv")
    payments = export_csv([MethodPayments("cash", 2, 700)], tmp_path / "m.csv")

    assert products.read_bytes().decode("utf-8-sig") == (
        'Producto;Cantidad;Ingresos\r\n"Café; con leche";3;10,50\r\n'
    )
    assert payments.read_bytes().decode("utf-8-sig") == (
        "Forma de pago;Pagos;Monto\r\nEfectivo;2;7,00\r\n"
    )


def test_export_empty_rows_writes_only_header(tmp_path):
    path = export_csv([], tmp_path / "vacio.csv", row_type=DaySales)

    assert path.read_bytes() == "\ufeffFecha;Ventas;Total;IVA\r\n".encode()


def test_export_empty_rows_without_row_type_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="tipo de fila"):
        export_csv([], tmp_path / "vacio.csv")

    assert not (tmp_path / "vacio.csv").exists()


def test_export_csv_replaces_existing_file_and_leaves_no_temp_files(tmp_path):
    path = tmp_path / "ventas.csv"
    path.write_text("viejo", encoding="utf-8")

    export_csv([DaySales(DAY_1, 1, 100, 0)], path)

    assert "viejo" not in path.read_text(encoding="utf-8-sig")
    assert sorted(item.name for item in Path(tmp_path).iterdir()) == ["ventas.csv"]
