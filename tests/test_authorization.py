import pytest

from suitelocal.application.inventory import InventoryService
from suitelocal.domain.auth import Session, User
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import ProductRepository


def test_cashier_cannot_create_product(tmp_path):
    database = Database(tmp_path / "authorization.db")
    database.initialize()
    inventory = InventoryService(ProductRepository(database))
    cashier = Session(User(2, 1, "cashier", "cashier", True))

    with pytest.raises(PermissionError, match="Solo el dueño"):
        inventory.create_product(cashier, "A-1", "Arroz", 250, 5)
