import sqlite3

import pytest

from suitelocal.application.auth import AuthService
from suitelocal.domain.auth import Session, User
from suitelocal.domain.models import Sale, SaleItem
from suitelocal.infrastructure.backups import BackupError, restore_backup
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import ProductRepository, SaleRepository


@pytest.fixture
def database(tmp_path):
    database = Database(tmp_path / "hardening.db")
    database.initialize()
    return database


def test_connection_is_closed_after_context(database):
    with database.connect() as connection:
        connection.execute("SELECT 1")

    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")


def test_connection_rolls_back_on_error(database):
    with pytest.raises(RuntimeError), database.connect() as connection:
        connection.execute("INSERT INTO businesses (name) VALUES ('Parcial')")
        raise RuntimeError("boom")

    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM businesses").fetchone()[0] == 0


def test_restore_rejects_foreign_sqlite_file_and_keeps_data(tmp_path, database):
    AuthService(database).setup_owner("Tienda Sol", "owner", "clave-segura", "clave-segura")
    foreign = tmp_path / "foreign.sqlite"
    with sqlite3.connect(foreign) as connection:
        connection.execute("CREATE TABLE notes (text TEXT)")
    connection.close()

    with pytest.raises(BackupError, match="no pertenece a SuiteLocal"):
        restore_backup(database, foreign)

    with database.connect() as connection:
        assert connection.execute("SELECT name FROM businesses").fetchone()[0] == "Tienda Sol"


def test_sale_failure_leaves_stock_and_sales_unchanged(database):
    products, sales = ProductRepository(database), SaleRepository(database)
    rice = products.add("A-1", "Arroz", 250, 10)
    oil = products.add("A-2", "Aceite", 900, 1)
    sale = Sale(
        (
            SaleItem(rice.id, rice.name, 2, rice.price_cents),
            SaleItem(oil.id, oil.name, 3, oil.price_cents),
        ),
        10_000,
    )

    with pytest.raises(ValueError, match="Stock insuficiente para Aceite"):
        sales.register(sale)

    assert products.find_active("A-1")[0].stock == 10
    assert products.find_active("A-2")[0].stock == 1
    assert sales.today_summary() == (0, 0)


def test_update_returns_product_by_id_when_code_overlaps_another(database):
    products = ProductRepository(database)
    products.add("AB-9X", "Aceite", 900, 3)
    product = products.add("A-1", "Arroz", 250, 10)

    updated = products.update(product.id, "B-9", "Arroz integral", 300, 7)

    assert (updated.id, updated.code, updated.stock) == (product.id, "B-9", 7)


def test_cashier_cannot_manage_users_with_generic_message(database):
    auth = AuthService(database)
    auth.setup_owner("Tienda Sol", "owner", "clave-segura", "clave-segura")
    cashier = Session(User(2, 1, "cajero", "cashier", True))

    with pytest.raises(PermissionError, match="^Solo el dueño puede realizar esta acción.$"):
        auth.list_users(cashier)
    with pytest.raises(PermissionError, match="^Solo el dueño puede realizar esta acción.$"):
        auth.create_cashier(cashier, "otro", "clave-cajero", "clave-cajero")


def test_setup_owner_runs_only_once(database):
    auth = AuthService(database)
    auth.setup_owner("Tienda Sol", "owner", "clave-segura", "clave-segura")

    with pytest.raises(ValueError, match="ya tiene un usuario"):
        auth.setup_owner("Otra", "owner2", "clave-segura", "clave-segura")

    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM businesses").fetchone()[0] == 1


def test_login_rejects_unknown_wrong_and_inactive_users_with_same_message(database):
    auth = AuthService(database)
    owner = Session(auth.setup_owner("Tienda Sol", "owner", "clave-segura", "clave-segura"))
    auth.create_cashier(owner, "cajero", "clave-cajero", "clave-cajero")
    with database.connect() as connection:
        connection.execute("UPDATE users SET active = 0 WHERE username = 'cajero'")

    for username, password in (
        ("nadie", "clave-segura"),
        ("owner", "incorrecta"),
        ("cajero", "clave-cajero"),
    ):
        with pytest.raises(ValueError, match="^Usuario o contraseña incorrectos.$"):
            auth.authenticate(username, password)


def test_duplicate_cashier_username_is_rejected(database):
    auth = AuthService(database)
    owner = Session(auth.setup_owner("Tienda Sol", "owner", "clave-segura", "clave-segura"))
    auth.create_cashier(owner, "cajero", "clave-cajero", "clave-cajero")

    with pytest.raises(ValueError, match="Ya existe un usuario con ese nombre"):
        auth.create_cashier(owner, "cajero", "clave-cajero", "clave-cajero")
    assert len(auth.list_users(owner)) == 2
