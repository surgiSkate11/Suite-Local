import pytest

from suitelocal.application.auth import AuthService
from suitelocal.application.categories import CategoryService
from suitelocal.application.inventory import InventoryService
from suitelocal.domain.auth import Session, User
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import CategoryRepository, ProductRepository


@pytest.fixture
def env(tmp_path):
    database = Database(tmp_path / "categories.db")
    database.initialize()
    auth = AuthService(database)
    owner = Session(auth.setup_owner("Tienda Sol", "owner", "clave-segura", "clave-segura"))
    cashier = Session(auth.create_cashier(owner, "cajero", "clave-cajero", "clave-cajero"))
    repository = CategoryRepository(database)
    return database, owner, cashier, CategoryService(repository), ProductRepository(database)


def names(service: CategoryService, session: Session, include_inactive: bool = False) -> list[str]:
    return [c.name for c in service.list(session, include_inactive=include_inactive)]


def other_business_session(database: Database) -> Session:
    with database.connect() as connection:
        business_id = connection.execute("INSERT INTO businesses (name) VALUES ('Otro')").lastrowid
        user_id = connection.execute(
            "INSERT INTO users (business_id, username, password_hash, role) "
            "VALUES (?, 'otro', 'x', 'owner')",
            (business_id,),
        ).lastrowid
    assert business_id is not None and user_id is not None
    return Session(User(user_id, business_id, "otro", "owner", True))


# -- CRUD ---------------------------------------------------------------------------------


def test_owner_creates_lists_renames_and_deactivates(env):
    _, owner, _, service, _ = env

    bebidas = service.create(owner, "  Bebidas ")
    service.create(owner, "Abarrotes")

    assert (bebidas.name, bebidas.active, bebidas.business_id) == (
        "Bebidas",
        True,
        owner.user.business_id,
    )
    assert names(service, owner) == ["Abarrotes", "Bebidas"]

    renamed = service.rename(owner, bebidas.id, "Bebidas frías")
    assert renamed.name == "Bebidas frías"

    service.set_active(owner, bebidas.id, False)
    assert names(service, owner) == ["Abarrotes"]
    assert names(service, owner, include_inactive=True) == ["Abarrotes", "Bebidas frías"]

    service.set_active(owner, bebidas.id, True)
    assert names(service, owner) == ["Abarrotes", "Bebidas frías"]


def test_names_are_unique_per_business_ignoring_case(env):
    database, owner, _, service, _ = env
    service.create(owner, "Bebidas")
    abarrotes = service.create(owner, "Abarrotes")

    with pytest.raises(ValueError, match="Ya existe"):
        service.create(owner, "bebidas")
    with pytest.raises(ValueError, match="Ya existe"):
        service.rename(owner, abarrotes.id, "BEBIDAS")

    assert names(service, owner) == ["Abarrotes", "Bebidas"]
    other = other_business_session(database)
    assert CategoryService(CategoryRepository(database)).create(other, "Bebidas").name == "Bebidas"


def test_rename_to_the_same_name_with_other_case_is_allowed(env):
    _, owner, _, service, _ = env
    category = service.create(owner, "bebidas")

    assert service.rename(owner, category.id, "Bebidas").name == "Bebidas"


@pytest.mark.parametrize("name", ["", "   ", "x" * 41])
def test_invalid_names_are_rejected_without_changes(env, name):
    _, owner, _, service, _ = env
    category = service.create(owner, "Bebidas")

    with pytest.raises(ValueError, match="nombre"):
        service.create(owner, name)
    with pytest.raises(ValueError, match="nombre"):
        service.rename(owner, category.id, name)

    assert names(service, owner, include_inactive=True) == ["Bebidas"]


def test_unknown_or_foreign_category_cannot_be_changed(env):
    database, owner, _, service, _ = env
    other = other_business_session(database)
    foreign = CategoryService(CategoryRepository(database)).create(other, "Ajena")

    for action in (
        lambda: service.rename(owner, foreign.id, "Mía"),
        lambda: service.set_active(owner, foreign.id, False),
        lambda: service.delete(owner, foreign.id),
        lambda: service.rename(owner, 999, "Nada"),
    ):
        with pytest.raises(ValueError, match="categoría"):
            action()

    assert [c.name for c in CategoryRepository(database).list(other.user.business_id)] == ["Ajena"]


def test_delete_removes_unused_categories_only(env):
    _, owner, _, service, products = env
    unused = service.create(owner, "Sin uso")
    used = service.create(owner, "Con productos")
    products.add("A-1", "Arroz", 250, 5, category_id=used.id)

    service.delete(owner, unused.id)
    with pytest.raises(ValueError, match="desactívala"):
        service.delete(owner, used.id)

    assert names(service, owner, include_inactive=True) == ["Con productos"]


def test_cashier_can_list_but_not_change_categories(env):
    _, owner, cashier, service, _ = env
    category = service.create(owner, "Bebidas")

    assert [c.name for c in service.list(cashier)] == ["Bebidas"]
    for action in (
        lambda: service.create(cashier, "Snacks"),
        lambda: service.rename(cashier, category.id, "Otra"),
        lambda: service.set_active(cashier, category.id, False),
        lambda: service.delete(cashier, category.id),
    ):
        with pytest.raises(PermissionError, match="Solo el dueño"):
            action()

    assert names(service, owner, include_inactive=True) == ["Bebidas"]


# -- products -----------------------------------------------------------------------------


def test_product_stores_category_and_cost(env):
    _, owner, _, service, products = env
    bebidas = service.create(owner, "Bebidas")

    product = products.add("A-1", "Cola", 150, 10, category_id=bebidas.id, cost_cents=90)

    stored = products.find_active("A-1")[0]
    assert stored == product
    assert (stored.category_id, stored.cost_cents) == (bebidas.id, 90)


def test_legacy_product_calls_keep_working_without_category_or_cost(env):
    _, _, _, _, products = env

    product = products.add("A-1", "Arroz", 250, 10)
    updated = products.update(product.id, "A-1", "Arroz", 260, 10)

    assert (product.category_id, product.cost_cents) == (None, None)
    assert (updated.category_id, updated.cost_cents) == (None, None)
    assert updated.price_cents == 260


def test_update_keeps_category_and_cost_unless_they_are_given(env):
    _, owner, _, service, products = env
    bebidas = service.create(owner, "Bebidas")
    snacks = service.create(owner, "Snacks")
    product = products.add("A-1", "Cola", 150, 10, category_id=bebidas.id, cost_cents=90)

    same = products.update(product.id, "A-1", "Cola", 160, 10)
    assert (same.category_id, same.cost_cents) == (bebidas.id, 90)
    assert products.find_active()[0].category_id == bebidas.id

    moved = products.update(product.id, "A-1", "Cola", 160, 10, category_id=snacks.id)
    assert (moved.category_id, moved.cost_cents) == (snacks.id, 90)

    cleared = products.update(product.id, "A-1", "Cola", 160, 10, category_id=None, cost_cents=None)
    assert (cleared.category_id, cleared.cost_cents) == (None, None)
    stored = products.find_active()[0]
    assert (stored.category_id, stored.cost_cents) == (None, None)


def test_unknown_category_and_negative_cost_are_rejected_and_leave_products_unchanged(env):
    database, _, _, _, products = env
    product = products.add("A-1", "Arroz", 250, 10)

    with pytest.raises(ValueError, match="categoría"):
        products.add("B-1", "Aceite", 900, 3, category_id=999)
    with pytest.raises(ValueError, match="costo"):
        products.add("B-1", "Aceite", 900, 3, cost_cents=-1)
    with pytest.raises(ValueError, match="categoría"):
        products.update(product.id, "A-1", "Arroz", 250, 10, category_id=999)
    with pytest.raises(ValueError, match="costo"):
        products.update(product.id, "A-1", "Arroz", 250, 10, cost_cents=-5)

    assert products.find_active() == [product]
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 1


def test_cost_of_zero_is_valid(env):
    _, _, _, _, products = env

    assert products.add("A-1", "Regalo", 100, 1, cost_cents=0).cost_cents == 0


def test_inventory_service_passes_category_cost_and_rate_and_stays_owner_only(env):
    _, owner, cashier, service, products = env
    bebidas = service.create(owner, "Bebidas")
    inventory = InventoryService(products)

    created = inventory.create_product(
        owner, "A-1", "Cola", 150, 10, category_id=bebidas.id, cost_cents=90
    )
    updated = inventory.update_product(
        owner, created.id, "A-1", "Cola", 150, 10, category_id=None, cost_cents=95
    )

    assert (created.category_id, created.cost_cents) == (bebidas.id, 90)
    assert (updated.category_id, updated.cost_cents) == (None, 95)
    with pytest.raises(PermissionError, match="Solo el dueño"):
        inventory.create_product(cashier, "B-1", "Otro", 100, 1, category_id=bebidas.id)
    assert [p.code for p in products.find_active()] == ["A-1"]


def test_inventory_rejects_a_category_of_another_business_or_a_missing_one(env):
    database, owner, _, service, products = env
    foreign = service.create(other_business_session(database), "Ajena")
    own = service.create(owner, "Bebidas")
    inventory = InventoryService(products)
    product = inventory.create_product(owner, "A-1", "Arroz", 250, 10, category_id=own.id)

    for category_id in (foreign.id, 9999):
        with pytest.raises(ValueError, match="La categoría seleccionada no existe."):
            inventory.update_product(
                owner, product.id, "A-1", "Arroz caro", 999, 1, category_id=category_id
            )
        with pytest.raises(ValueError, match="La categoría seleccionada no existe."):
            inventory.create_product(owner, "B-1", "Aceite", 900, 3, category_id=category_id)

    assert products.find_active() == [product]


def test_inventory_accepts_own_and_empty_categories(env):
    _, owner, _, service, products = env
    own = service.create(owner, "Bebidas")
    inventory = InventoryService(products)
    product = inventory.create_product(owner, "A-1", "Arroz", 250, 10)

    assigned = inventory.update_product(
        owner, product.id, "A-1", "Arroz", 250, 10, category_id=own.id
    )
    cleared = inventory.update_product(owner, product.id, "A-1", "Arroz", 250, 10, category_id=None)

    assert (assigned.category_id, cleared.category_id) == (own.id, None)
