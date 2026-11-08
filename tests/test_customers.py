import sqlite3
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from suitelocal.application.auth import AuthService
from suitelocal.application.customers import CustomerService
from suitelocal.domain.auth import Session, User
from suitelocal.domain.customers import CustomerData
from suitelocal.domain.models import Sale, SaleItem
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import ProductRepository, SaleRepository

ANA = CustomerData("cedula", "1712345678", "Ana Pérez")


@pytest.fixture
def env(tmp_path):
    database = Database(tmp_path / "customers.db")
    database.initialize()
    auth = AuthService(database)
    owner = Session(auth.setup_owner("Tienda Sol", "owner", "clave-segura", "clave-segura"))
    cashier = Session(auth.create_cashier(owner, "cajero", "clave-cajero", "clave-cajero"))
    return database, owner, cashier, CustomerService(database)


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


def sell(database: Database, session: Session, price_cents: int, customer_id: int | None) -> int:
    code = f"P{price_cents}-{customer_id}"
    product = ProductRepository(database).add(code, "Corte", price_cents, 100)
    sale = Sale((SaleItem(product.id, product.name, 1, price_cents),), price_cents)
    return SaleRepository(database).register(
        sale,
        business_id=session.user.business_id,
        user_id=session.user.id,
        customer_id=customer_id,
    )


# -- validation ---------------------------------------------------------------------------


def test_create_stores_the_customer_with_trimmed_fields(env):
    _, owner, _, service = env

    customer = service.create(
        owner,
        CustomerData(
            "cedula",
            " 1712345678 ",
            "  Ana Pérez ",
            phone=" 0991234567 ",
            address=" Av. Sol 1 ",
            email=" ANA@Correo.com ",
            accepts_offers=True,
        ),
    )

    assert (
        customer.business_id,
        customer.id_type,
        customer.id_number,
        customer.full_name,
        customer.phone,
        customer.address,
        customer.email,
        customer.accepts_offers,
        customer.active,
    ) == (
        owner.user.business_id,
        "cedula",
        "1712345678",
        "Ana Pérez",
        "0991234567",
        "Av. Sol 1",
        "ana@correo.com",
        True,
        True,
    )
    assert customer.created_at
    assert service.find_by_id_number(owner, "1712345678") == customer


@pytest.mark.parametrize(
    ("id_type", "id_number", "message"),
    [
        ("cedula", "17123", "La cédula debe tener exactamente 10 dígitos."),
        ("cedula", "17123456AB", "La cédula debe tener exactamente 10 dígitos."),
        ("ruc", "1712345678", "El RUC del comprador debe tener 13 dígitos."),
        ("ruc", "1712345678000", "El RUC del comprador no puede terminar en 000."),
        ("pasaporte", "AB", "El pasaporte debe tener entre 3 y 20 letras o dígitos."),
        ("pasaporte", "AB-123", "El pasaporte debe tener entre 3 y 20 letras o dígitos."),
        ("pasaporte", "A" * 21, "El pasaporte debe tener entre 3 y 20 letras o dígitos."),
        ("otro", "1712345678", "El tipo de identificación no es válido."),
        ("ruc", "9999999999999", "El número 9999999999999 es solo para consumidor final."),
    ],
)
def test_invalid_identification_is_rejected_in_spanish(env, id_type, id_number, message):
    _, owner, _, service = env

    with pytest.raises(ValueError) as error:
        service.create(owner, CustomerData(id_type, id_number, "Ana"))

    assert str(error.value) == message
    assert service.search(owner, "") == []


def test_valid_ruc_and_passport_are_accepted(env):
    _, owner, _, service = env

    ruc = service.create(owner, CustomerData("ruc", "1790012345001", "Café Sol S.A."))
    passport = service.create(owner, CustomerData("pasaporte", "ab12345", "John Smith"))

    assert (ruc.id_type, ruc.id_number) == ("ruc", "1790012345001")
    assert (passport.id_type, passport.id_number) == ("pasaporte", "ab12345")


def test_name_is_required(env):
    _, owner, _, service = env

    with pytest.raises(ValueError, match="^El nombre del cliente es obligatorio.$"):
        service.create(owner, replace(ANA, full_name="   "))


@pytest.mark.parametrize("email", ["ana", "ana@", "@correo.com", "ana@correo", "a na@correo.com"])
def test_invalid_email_is_rejected(env, email):
    _, owner, _, service = env

    with pytest.raises(ValueError, match="^El correo no es válido.$"):
        service.create(owner, replace(ANA, email=email))


def test_offers_require_an_email(env):
    _, owner, _, service = env

    with pytest.raises(ValueError, match="^Para recibir ofertas necesitás registrar un correo.$"):
        service.create(owner, replace(ANA, accepts_offers=True))
    assert service.search(owner, "") == []


# -- uniqueness ---------------------------------------------------------------------------


def test_duplicate_identification_points_to_the_existing_customer(env):
    _, owner, cashier, service = env
    service.create(owner, ANA)

    with pytest.raises(ValueError) as error:
        service.create(cashier, replace(ANA, full_name="Otra Ana"))

    assert str(error.value) == "Ya existe un cliente con esa identificación: Ana Pérez."
    assert len(service.search(owner, "")) == 1


def test_update_cannot_take_the_identification_of_another_customer(env):
    _, owner, _, service = env
    service.create(owner, ANA)
    luis = service.create(owner, CustomerData("cedula", "1798765432", "Luis"))

    with pytest.raises(ValueError, match="^Ya existe un cliente con esa identificación: Ana"):
        service.update(owner, luis.id, replace(ANA, full_name="Luis"))

    assert service.find_by_id_number(owner, "1798765432") == luis


def test_a_deactivated_customer_still_holds_its_identification(env):
    _, owner, _, service = env
    ana = service.create(owner, ANA)
    service.deactivate(owner, ana.id)

    with pytest.raises(ValueError) as error:
        service.create(owner, ANA)

    assert str(error.value) == (
        "Ya existe un cliente con esa identificación: Ana Pérez (está desactivado)."
    )


def test_two_businesses_can_register_the_same_identification(env):
    database, owner, _, service = env
    outsider = other_business_session(database)

    mine = service.create(owner, ANA)
    theirs = service.create(outsider, ANA)

    assert mine.id != theirs.id
    assert service.find_by_id_number(owner, ANA.id_number) == mine
    assert service.find_by_id_number(outsider, ANA.id_number) == theirs


def test_the_database_enforces_uniqueness_per_business(env):
    database, owner, _, service = env
    service.create(owner, ANA)

    with pytest.raises(sqlite3.IntegrityError), database.connect() as connection:
        connection.execute(
            "INSERT INTO customers (business_id, id_type, id_number, full_name) "
            "VALUES (?, 'cedula', '1712345678', 'Copia')",
            (owner.user.business_id,),
        )


# -- find, search, update, deactivate ----------------------------------------------------


def test_find_by_id_number_returns_none_when_unknown_or_deactivated(env):
    _, owner, _, service = env
    ana = service.create(owner, ANA)

    assert service.find_by_id_number(owner, "1700000000") is None
    assert service.find_by_id_number(owner, " 1712345678 ") == ana
    service.deactivate(owner, ana.id)
    assert service.find_by_id_number(owner, "1712345678") is None


def test_search_by_identification_prefix_and_accent_insensitive_name(env):
    _, owner, _, service = env
    ana = service.create(owner, ANA)
    jose = service.create(owner, CustomerData("cedula", "1798765432", "José Núñez"))
    service.create(owner, CustomerData("pasaporte", "XK12345", "Mary Jones"))

    assert service.search(owner, "17123") == [ana]
    assert service.search(owner, "1798") == [jose]
    assert service.search(owner, "5678") == []  # a prefix, not any part of the number
    assert service.search(owner, "jose nunez") == [jose]
    assert service.search(owner, "NÚÑEZ") == [jose]
    assert service.search(owner, "perez") == [ana]
    assert [c.full_name for c in service.search(owner, "xk1")] == ["Mary Jones"]
    assert service.search(owner, "zzz") == []


def test_search_lists_by_name_without_text_skips_deactivated_and_limits_to_50(env):
    _, owner, _, service = env
    for number in range(55):
        service.create(
            owner, CustomerData("cedula", f"17000000{number:02d}", f"Cliente {number:02d}")
        )
    service.deactivate(owner, service.find_by_id_number(owner, "1700000000").id)

    found = service.search(owner, "")

    assert len(found) == 50
    assert found[0].full_name == "Cliente 01"
    assert all(customer.active for customer in found)


def test_search_only_sees_the_own_business(env):
    database, owner, _, service = env
    outsider = other_business_session(database)
    service.create(outsider, ANA)

    assert service.search(owner, "Ana") == []
    assert service.find_by_id_number(owner, ANA.id_number) is None


def test_update_changes_the_data_and_validates_it(env):
    _, owner, cashier, service = env
    ana = service.create(owner, ANA)

    updated = service.update(
        cashier,
        ana.id,
        replace(ANA, full_name="Ana P.", phone="0990000000", email="ana@correo.com"),
    )

    assert (updated.id, updated.full_name, updated.phone, updated.email) == (
        ana.id,
        "Ana P.",
        "0990000000",
        "ana@correo.com",
    )
    assert updated.created_at == ana.created_at
    with pytest.raises(ValueError, match="^El correo no es válido.$"):
        service.update(cashier, ana.id, replace(ANA, email="mal"))
    assert service.find_by_id_number(owner, ANA.id_number) == updated


def test_update_of_an_unknown_or_foreign_customer_is_rejected(env):
    database, owner, _, service = env
    outsider = other_business_session(database)
    theirs = service.create(outsider, ANA)

    with pytest.raises(ValueError, match="^El cliente no existe.$"):
        service.update(owner, theirs.id, replace(ANA, full_name="Robo"))
    with pytest.raises(ValueError, match="^El cliente no existe.$"):
        service.update(owner, 9999, ANA)
    assert service.find_by_id_number(outsider, ANA.id_number) == theirs


def test_deactivate_hides_the_customer_but_keeps_the_record(env):
    database, owner, _, service = env
    ana = service.create(owner, ANA)

    service.deactivate(owner, ana.id)

    assert service.search(owner, "Ana") == []
    with database.connect() as connection:
        row = connection.execute("SELECT active FROM customers WHERE id = ?", (ana.id,)).fetchone()
    assert row["active"] == 0


# -- history ------------------------------------------------------------------------------


def test_history_lists_the_last_20_sales_and_the_lifetime_total(env):
    database, owner, _, service = env
    ana = service.create(owner, ANA)
    other = service.create(owner, CustomerData("cedula", "1798765432", "Luis"))
    for index in range(22):
        sell(database, owner, 100 + index, ana.id)
    sell(database, owner, 5000, other.id)
    sell(database, owner, 7000, None)

    history = service.history(owner, ana.id)

    assert len(history.purchases) == 20
    assert history.purchase_count == 22
    assert history.total_cents == sum(100 + index for index in range(22))
    assert [p.total_cents for p in history.purchases][:2] == [121, 120]  # newest first
    assert isinstance(history.purchases[0].created_at, datetime)
    assert history.purchases[0].created_at.tzinfo == UTC


def test_history_of_a_customer_without_purchases_is_empty(env):
    _, owner, _, service = env
    ana = service.create(owner, ANA)

    history = service.history(owner, ana.id)

    assert (history.purchases, history.purchase_count, history.total_cents) == ((), 0, 0)


def test_history_of_a_foreign_customer_is_rejected(env):
    database, owner, _, service = env
    theirs = service.create(other_business_session(database), ANA)

    with pytest.raises(ValueError, match="^El cliente no existe.$"):
        service.history(owner, theirs.id)


# -- sale link ----------------------------------------------------------------------------


def test_sale_stores_the_customer_id(env):
    database, owner, _, service = env
    ana = service.create(owner, ANA)

    sale_id = sell(database, owner, 250, ana.id)
    anonymous_id = sell(database, owner, 300, None)

    with database.connect() as connection:
        stored = {
            row["id"]: row["customer_id"]
            for row in connection.execute("SELECT id, customer_id FROM sales")
        }
    assert stored == {sale_id: ana.id, anonymous_id: None}


def test_sale_rejects_a_customer_of_another_business_and_stores_nothing(env):
    database, owner, _, service = env
    theirs = service.create(other_business_session(database), ANA)
    product = ProductRepository(database).add("X1", "Corte", 250, 5)
    sale = Sale((SaleItem(product.id, product.name, 1, 250),), 250)

    with pytest.raises(ValueError, match="^El cliente no existe.$"):
        SaleRepository(database).register(
            sale,
            business_id=owner.user.business_id,
            user_id=owner.user.id,
            customer_id=theirs.id,
        )

    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM sales").fetchone()[0] == 0
        assert connection.execute("SELECT stock FROM products").fetchone()["stock"] == 5


def test_sale_without_customer_keeps_working_as_before(env):
    database, owner, _, _ = env

    sale_id = sell(database, owner, 250, None)

    assert sale_id > 0


def test_initialize_is_idempotent_and_adds_customer_id_to_an_old_sales_table(tmp_path):
    database = Database(tmp_path / "old.db")
    database.initialize()
    with database.connect() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(sales)")}
    assert "customer_id" in columns

    database.initialize()

    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0


# -- CSV ----------------------------------------------------------------------------------


def test_offers_export_has_the_exact_content_and_only_who_accepted(env, tmp_path):
    _, owner, _, service = env
    service.create(
        owner,
        CustomerData("cedula", "1712345678", "Ana Pérez", "0991", "", "ana@correo.com", True),
    )
    service.create(
        owner, CustomerData("ruc", "1790012345001", "Café Sol", "", "", "hola@cafe.com", True)
    )
    service.create(owner, CustomerData("cedula", "1700000001", "Sin ofertas", "", "", "s@c.com"))
    service.create(owner, CustomerData("cedula", "1700000002", "Sin correo"))
    gone = service.create(
        owner, CustomerData("cedula", "1700000003", "Dado de baja", "", "", "x@c.com", True)
    )
    service.deactivate(owner, gone.id)
    path = tmp_path / "salida" / "ofertas.csv"

    result = service.export_offers_csv(owner, path)

    assert result == path
    assert (
        path.read_bytes()
        == (
            "\ufeffNombres;Cédula/RUC/Pasaporte;Teléfono;Correo\r\n"
            "Ana Pérez;1712345678;0991;ana@correo.com\r\n"
            "Café Sol;1790012345001;;hola@cafe.com\r\n"
        ).encode()
    )


def test_offers_export_of_nobody_writes_only_the_header(env, tmp_path):
    _, owner, _, service = env
    path = tmp_path / "vacio.csv"

    service.export_offers_csv(owner, path)

    assert path.read_bytes() == "\ufeffNombres;Cédula/RUC/Pasaporte;Teléfono;Correo\r\n".encode()


# -- roles --------------------------------------------------------------------------------


def test_a_cashier_registers_updates_and_searches_customers(env):
    _, _, cashier, service = env

    ana = service.create(cashier, ANA)
    service.update(cashier, ana.id, replace(ANA, phone="0990000000"))

    assert [c.phone for c in service.search(cashier, "1712")] == ["0990000000"]
    assert service.find_by_id_number(cashier, ANA.id_number) is not None
    assert service.history(cashier, ana.id).purchases == ()


def test_a_cashier_cannot_deactivate_or_export(env, tmp_path):
    _, owner, cashier, service = env
    ana = service.create(owner, ANA)
    path = tmp_path / "ofertas.csv"

    with pytest.raises(PermissionError, match="^Solo el dueño puede realizar esta acción.$"):
        service.deactivate(cashier, ana.id)
    with pytest.raises(PermissionError, match="^Solo el dueño puede realizar esta acción.$"):
        service.export_offers_csv(cashier, path)

    assert service.find_by_id_number(owner, ANA.id_number) == ana
    assert not path.exists()
