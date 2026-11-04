import pytest

from suitelocal.domain.models import Sale, SaleError, SaleItem
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import ProductRepository, SaleRepository


@pytest.fixture
def repositories(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    return ProductRepository(database), SaleRepository(database)


def test_register_sale_decreases_stock_and_stores_change(repositories):
    products, sales = repositories
    product = products.add("A-1", "Arroz", 250, 10)

    sale_id = sales.register(
        Sale((SaleItem(product.id, product.name, 2, product.price_cents),), 600)
    )

    assert sale_id == 1
    assert products.find_active("A-1")[0].stock == 8


def test_register_sale_is_rejected_when_stock_is_insufficient(repositories):
    products, sales = repositories
    product = products.add("A-1", "Arroz", 250, 1)

    with pytest.raises(ValueError, match="Stock insuficiente"):
        sales.register(Sale((SaleItem(product.id, product.name, 2, 250),), 500))

    assert products.find_active("A-1")[0].stock == 1


def test_sale_requires_enough_payment():
    with pytest.raises(SaleError, match="menor"):
        Sale((SaleItem(1, "Arroz", 1, 250),), 200)
