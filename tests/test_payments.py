import pytest

from suitelocal.domain.models import Payment, Sale, SaleError, SaleItem
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import ProductRepository, SaleRepository


def test_split_cash_and_transfer_payments_are_stored(tmp_path):
    database = Database(tmp_path / "payments.db")
    database.initialize()
    products = ProductRepository(database)
    sales = SaleRepository(database)
    product = products.add("A-1", "Arroz", 1000, 5)

    sale = Sale(
        (SaleItem(product.id, product.name, 1, 1000),),
        1000,
        (Payment("cash", 400), Payment("transfer", 600, "TRX-123")),
    )
    sale_id = sales.register(sale)

    with database.connect() as connection:
        rows = connection.execute(
            "SELECT method, amount_cents, reference FROM sale_payments WHERE sale_id = ?",
            (sale_id,),
        ).fetchall()
    assert [(row["method"], row["amount_cents"], row["reference"]) for row in rows] == [
        ("cash", 400, ""),
        ("transfer", 600, "TRX-123"),
    ]


def test_transfer_requires_reference():
    with pytest.raises(SaleError, match="referencia"):
        Sale(
            (SaleItem(1, "Arroz", 1, 1000),),
            1000,
            (Payment("transfer", 1000),),
        )


def test_non_cash_payment_cannot_exceed_sale_total():
    with pytest.raises(SaleError, match="superar"):
        Sale(
            (SaleItem(1, "Arroz", 1, 1000),),
            1200,
            (Payment("transfer", 1200, "TRX-123"),),
        )
