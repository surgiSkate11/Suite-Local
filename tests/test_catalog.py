import pytest

from suitelocal.application.auth import AuthService
from suitelocal.application.catalog import CatalogService
from suitelocal.domain.auth import Session
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import ProductRepository


@pytest.fixture
def env(tmp_path):
    database = Database(tmp_path / "catalog.db")
    database.initialize()
    auth = AuthService(database)
    owner = Session(auth.setup_owner("Café", "dueno", "Clave-segura-1", "Clave-segura-1"))
    cashier = Session(auth.create_cashier(owner, "cajero", "Clave-segura-2", "Clave-segura-2"))
    products = ProductRepository(database)
    products.add("C-1", "Café", 150, 10)
    products.add("T-1", "Torta", 300, 4)
    hidden = products.add("X-1", "Café viejo", 100, 0)
    products.deactivate(hidden.id)
    return CatalogService(products), owner, cashier


@pytest.mark.parametrize("role", ["owner", "cashier"])
def test_any_signed_in_user_can_search_active_products_by_name_or_code(env, role):
    catalog, owner, cashier = env
    session = owner if role == "owner" else cashier

    assert [p.name for p in catalog.search(session, "caf")] == ["Café"]
    assert [p.name for p in catalog.search(session, "T-1")] == ["Torta"]
    assert catalog.search(session, "inexistente") == []


def test_blank_search_lists_every_active_product(env):
    catalog, _, cashier = env

    assert [p.name for p in catalog.search(cashier, "  ")] == ["Café", "Torta"]
