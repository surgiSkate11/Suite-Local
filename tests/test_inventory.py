import pytest

from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import ProductRepository


@pytest.fixture
def products(tmp_path):
    database = Database(tmp_path / "inventory.db")
    database.initialize()
    return ProductRepository(database)


def test_product_code_must_be_unique(products):
    products.add("A-1", "Arroz", 250, 10)

    with pytest.raises(ValueError, match="Ya existe"):
        products.add("A-1", "Otro", 300, 2)


def test_product_can_be_updated_and_deactivated(products):
    product = products.add("A-1", "Arroz", 250, 10)

    updated = products.update(product.id, "A-2", "Arroz integral", 325, 8)
    products.deactivate(updated.id)

    assert products.find_active() == []


def test_product_code_preserves_custom_scanner_identifier(products):
    product = products.add("QR-TIENDA-001", "Arroz", 250, 10)

    assert products.find_active("QR-TIENDA-001")[0].id == product.id
