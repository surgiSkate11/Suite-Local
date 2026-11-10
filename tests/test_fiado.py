import pytest

from suitelocal.application.auth import AuthService
from suitelocal.application.cash_register import CashRegisterService
from suitelocal.application.credit import CreditService
from suitelocal.application.customers import CustomerService
from suitelocal.domain.auth import Session
from suitelocal.domain.business import parse_modules, profile_template
from suitelocal.domain.customers import CustomerData
from suitelocal.domain.models import Payment, Sale, SaleItem
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import ProductRepository, SaleRepository
from suitelocal.infrastructure.settings import BusinessSettingsRepository

ANA = CustomerData("cedula", "1712345678", "Ana Pérez")


@pytest.fixture
def env(tmp_path):
    database = Database(tmp_path / "fiado.db")
    database.initialize()
    auth = AuthService(database)
    owner = Session(auth.setup_owner("Tienda Sol", "owner", "clave-segura", "clave-segura"))
    cashier = Session(auth.create_cashier(owner, "cajero", "clave-cajero", "clave-cajero"))
    BusinessSettingsRepository(database).update_profile(
        owner.user.business_id, enabled_modules={"fiado"}
    )
    product = ProductRepository(database).add("A-1", "Arroz", 250, 100, tax_rate_basis_points=0)
    customer = CustomerService(database).create(owner, ANA)
    return {
        "database": database,
        "owner": owner,
        "cashier": cashier,
        "product": product,
        "customer": customer,
        "sales": SaleRepository(database),
        "credit": CreditService(database),
        "cash": CashRegisterService(database),
    }


def sell(env, quantity, payments, *, customer=True, session=None):
    session = session or env["cashier"]
    product = env["product"]
    sale = Sale(
        (SaleItem(product.id, product.name, quantity, product.price_cents),),
        sum(payment.amount_cents for payment in payments),
        tuple(payments),
    )
    return env["sales"].register(
        sale,
        business_id=session.user.business_id,
        user_id=session.user.id,
        customer_id=env["customer"].id if customer else None,
    )


def count(database, table):
    with database.connect() as connection:
        return connection.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]


def stock(env):
    with env["database"].connect() as connection:
        return connection.execute(
            "SELECT stock FROM products WHERE id = ?", (env["product"].id,)
        ).fetchone()["stock"]


def test_module_is_valid_and_on_for_tienda_and_minimarket_only():
    assert parse_modules("fiado") == frozenset({"fiado"})
    assert "fiado" in profile_template("tienda").modules
    assert "fiado" in profile_template("minimarket").modules
    assert "fiado" not in profile_template("cafeteria").modules
    assert "fiado" not in profile_template("otro").modules


def test_credit_method_is_offered_only_with_the_module(env):
    settings = BusinessSettingsRepository(env["database"])
    business_id = env["owner"].user.business_id
    assert "credit" in settings.get(business_id).enabled_payment_methods
    settings.update_profile(business_id, enabled_modules=set())
    assert "credit" not in settings.get(business_id).enabled_payment_methods


def test_fiado_sale_creates_a_cargo_and_decrements_stock_once(env):
    sale_id = sell(env, 2, [Payment("credit", 500)])

    customer_id = env["customer"].id
    assert env["credit"].balance_cents(env["cashier"], customer_id) == 500
    (entry,) = env["credit"].statement(env["cashier"], customer_id)
    assert (entry.kind, entry.amount_cents, entry.sale_id) == ("cargo", 500, sale_id)
    assert entry.user_id == env["cashier"].user.id
    assert stock(env) == 98
    with env["database"].connect() as connection:
        sale = connection.execute("SELECT change_cents FROM sales").fetchone()
        payment = connection.execute("SELECT method, amount_cents FROM sale_payments").fetchone()
    assert sale["change_cents"] == 0
    assert (payment["method"], payment["amount_cents"]) == ("credit", 500)


def test_fiado_without_customer_is_rejected_and_nothing_is_registered(env):
    with pytest.raises(ValueError, match="El fiado necesita un cliente"):
        sell(env, 2, [Payment("credit", 500)], customer=False)

    assert count(env["database"], "sales") == 0
    assert count(env["database"], "customer_ledger") == 0
    assert stock(env) == 100


def test_fiado_is_rejected_when_the_module_is_off(env):
    BusinessSettingsRepository(env["database"]).update_profile(
        env["owner"].user.business_id, enabled_modules=set()
    )
    with pytest.raises(ValueError, match="fiado no está activado"):
        sell(env, 2, [Payment("credit", 500)])

    assert count(env["database"], "sales") == 0
    assert stock(env) == 100


def test_fiado_over_the_limit_is_rejected_with_the_available_amount(env):
    customers = CustomerService(env["database"])
    customers.update(
        env["owner"],
        env["customer"].id,
        CustomerData("cedula", "1712345678", "Ana Pérez", credit_limit_cents=1000),
    )
    sell(env, 3, [Payment("credit", 750)])  # 250 left

    with pytest.raises(ValueError, match=r"Disponible: \$ 2,50"):
        sell(env, 2, [Payment("credit", 500)])

    assert env["credit"].balance_cents(env["cashier"], env["customer"].id) == 750
    assert count(env["database"], "sales") == 1
    assert stock(env) == 97


def test_fiado_up_to_exactly_the_limit_is_allowed(env):
    CustomerService(env["database"]).update(
        env["owner"],
        env["customer"].id,
        CustomerData("cedula", "1712345678", "Ana Pérez", credit_limit_cents=500),
    )
    sell(env, 2, [Payment("credit", 500)])

    assert env["credit"].balance_cents(env["cashier"], env["customer"].id) == 500
    assert env["credit"].available_cents(env["cashier"], env["customer"].id) == 0


def test_no_limit_means_unlimited(env):
    assert env["credit"].available_cents(env["cashier"], env["customer"].id) is None
    sell(env, 50, [Payment("credit", 12_500)])
    assert env["credit"].balance_cents(env["cashier"], env["customer"].id) == 12_500


def test_partial_abono_lowers_the_balance(env):
    sell(env, 4, [Payment("credit", 1000)])

    entry = env["credit"].register_payment(env["cashier"], env["customer"].id, 300, "cash")

    assert (entry.kind, entry.amount_cents, entry.method) == ("abono", 300, "cash")
    assert env["credit"].balance_cents(env["cashier"], env["customer"].id) == 700
    kinds = [item.kind for item in env["credit"].statement(env["cashier"], env["customer"].id)]
    assert kinds == ["abono", "cargo"]


def test_abono_over_the_balance_is_rejected(env):
    sell(env, 4, [Payment("credit", 1000)])

    with pytest.raises(ValueError, match=r"supera el saldo.*\$ 10,00"):
        env["credit"].register_payment(env["cashier"], env["customer"].id, 1001, "cash")

    assert env["credit"].balance_cents(env["cashier"], env["customer"].id) == 1000
    assert count(env["database"], "customer_ledger") == 1


def test_full_abono_clears_the_balance(env):
    sell(env, 4, [Payment("credit", 1000)])
    env["credit"].register_payment(env["owner"], env["customer"].id, 1000, "cash")
    assert env["credit"].balance_cents(env["owner"], env["customer"].id) == 0


@pytest.mark.parametrize(
    ("amount", "method", "reference", "message"),
    [
        (0, "cash", "", "mayor que cero"),
        (-5, "cash", "", "mayor que cero"),
        (100, "card", "", "forma de pago"),
        (100, "credit", "", "forma de pago"),
        (100, "transfer", "  ", "referencia"),
    ],
)
def test_invalid_abonos_are_rejected(env, amount, method, reference, message):
    sell(env, 4, [Payment("credit", 1000)])
    with pytest.raises(ValueError, match=message):
        env["credit"].register_payment(
            env["cashier"], env["customer"].id, amount, method, reference
        )
    assert count(env["database"], "customer_ledger") == 1


def test_transfer_abono_keeps_its_reference(env):
    sell(env, 4, [Payment("credit", 1000)])
    entry = env["credit"].register_payment(
        env["cashier"], env["customer"].id, 400, "transfer", " TR-77 "
    )
    assert entry.note == "TR-77"


def test_a_customer_of_another_business_is_not_reachable(env):
    with env["database"].connect() as connection:
        connection.execute("INSERT INTO businesses (name) VALUES ('Otro')")
        other = connection.execute("SELECT MAX(id) AS id FROM businesses").fetchone()["id"]
        connection.execute(
            "INSERT INTO customers (business_id, id_type, id_number, full_name) "
            "VALUES (?, 'cedula', '1798765432', 'Luis')",
            (other,),
        )
        foreign = connection.execute("SELECT MAX(id) AS id FROM customers").fetchone()["id"]
    with pytest.raises(ValueError, match="El cliente no existe"):
        env["credit"].register_payment(env["owner"], foreign, 100, "cash")
    with pytest.raises(ValueError, match="El cliente no existe"):
        env["credit"].balance_cents(env["owner"], foreign)


def test_split_cash_and_fiado_sale(env):
    # 4 x 250 = 1000: 600 in cash given as 1000 (change 400), 400 on credit.
    sell(env, 4, [Payment("cash", 1000), Payment("credit", 400)])

    assert env["credit"].balance_cents(env["cashier"], env["customer"].id) == 400
    with env["database"].connect() as connection:
        sale = connection.execute("SELECT total_cents, change_cents FROM sales").fetchone()
    assert (sale["total_cents"], sale["change_cents"]) == (1000, 400)


def test_expected_cash_excludes_fiado_and_includes_cash_abonos(env):
    env["cash"].open(env["owner"], 1000)
    sell(env, 2, [Payment("cash", 300), Payment("credit", 200)])
    # Total 500: credit 200 and cash 300, so the drawer only gets the 300.
    sell(env, 4, [Payment("credit", 1000)])
    assert env["cash"].expected_cents(env["owner"]) == 1300

    env["credit"].register_payment(env["cashier"], env["customer"].id, 500, "cash")
    assert env["cash"].expected_cents(env["owner"]) == 1800

    env["credit"].register_payment(env["cashier"], env["customer"].id, 200, "transfer", "TR-1")
    assert env["cash"].expected_cents(env["owner"]) == 1800

    closed = env["cash"].close(env["owner"], 1800)
    assert closed.expected_cents == 1800
    assert closed.difference_cents == 0


def test_a_cash_abono_without_an_open_session_does_not_touch_a_later_one(env):
    sell(env, 4, [Payment("credit", 1000)])
    env["credit"].register_payment(env["cashier"], env["customer"].id, 300, "cash")
    env["cash"].open(env["owner"], 500)
    assert env["cash"].expected_cents(env["owner"]) == 500


def test_an_abono_of_a_closed_session_stays_there(env):
    sell(env, 4, [Payment("credit", 1000)])
    env["cash"].open(env["owner"], 0)
    env["credit"].register_payment(env["cashier"], env["customer"].id, 300, "cash")
    assert env["cash"].close(env["owner"], 300).expected_cents == 300
    env["cash"].open(env["owner"], 0)
    assert env["cash"].expected_cents(env["owner"]) == 0


def test_a_failed_fiado_sale_rolls_back_the_sale_and_the_cargo(env):
    with pytest.raises(ValueError, match="Stock insuficiente"):
        sell(env, 101, [Payment("credit", 25_250)])
    assert count(env["database"], "sales") == 0
    assert count(env["database"], "customer_ledger") == 0


def test_debtors_list_and_total_owed(env):
    other = CustomerService(env["database"]).create(
        env["owner"], CustomerData("cedula", "1798765432", "Luis Mora")
    )
    sell(env, 4, [Payment("credit", 1000)])
    env["credit"].register_payment(env["cashier"], env["customer"].id, 1000, "cash")
    sell(env, 2, [Payment("credit", 500)])
    env["sales"].register(
        Sale(
            (SaleItem(env["product"].id, "Arroz", 6, 250),),
            1500,
            (Payment("credit", 1500),),
        ),
        business_id=env["owner"].user.business_id,
        user_id=env["owner"].user.id,
        customer_id=other.id,
    )

    debtors = env["credit"].debtors(env["cashier"])

    assert [(d.customer.full_name, d.balance_cents) for d in debtors] == [
        ("Luis Mora", 1500),
        ("Ana Pérez", 500),
    ]
    assert env["credit"].total_owed_cents(env["cashier"]) == 2000


def test_export_debtors_csv_is_owner_only_and_exact(env, tmp_path):
    sell(env, 4, [Payment("credit", 1000)])
    with pytest.raises(PermissionError):
        env["credit"].export_debtors_csv(env["cashier"], tmp_path / "deudores.csv")

    path = env["credit"].export_debtors_csv(env["owner"], tmp_path / "deudores.csv")

    lines = path.read_text(encoding="utf-8-sig").splitlines()
    assert lines[0] == "Nombres;Cédula/RUC/Pasaporte;Teléfono;Saldo;Activo"
    assert lines[1] == "Ana Pérez;1712345678;;10,00;Sí"
    assert len(lines) == 2


def owe_as_deactivated_customer(env):
    """Luis owes 15,00 and is deactivated afterwards; Ana owes 10,00."""
    luis = CustomerService(env["database"]).create(
        env["owner"], CustomerData("cedula", "1798765432", "Luis Mora")
    )
    sell(env, 4, [Payment("credit", 1000)])
    env["sales"].register(
        Sale((SaleItem(env["product"].id, "Arroz", 6, 250),), 1500, (Payment("credit", 1500),)),
        business_id=env["owner"].user.business_id,
        user_id=env["owner"].user.id,
        customer_id=luis.id,
    )
    CustomerService(env["database"]).deactivate(env["owner"], luis.id)


def test_a_deactivated_customer_who_still_owes_stays_in_the_debtors_and_the_total(env):
    owe_as_deactivated_customer(env)

    debtors = env["credit"].debtors(env["cashier"])

    assert [(d.customer.full_name, d.customer.active, d.balance_cents) for d in debtors] == [
        ("Luis Mora", False, 1500),
        ("Ana Pérez", True, 1000),
    ]
    assert env["credit"].total_owed_cents(env["cashier"]) == 2500


def test_the_debtors_csv_marks_the_deactivated_customers(env, tmp_path):
    owe_as_deactivated_customer(env)

    path = env["credit"].export_debtors_csv(env["owner"], tmp_path / "deudores.csv")

    assert path.read_text(encoding="utf-8-sig").splitlines() == [
        "Nombres;Cédula/RUC/Pasaporte;Teléfono;Saldo;Activo",
        "Luis Mora;1798765432;;15,00;No",
        "Ana Pérez;1712345678;;10,00;Sí",
    ]


def test_credit_limit_is_validated(env):
    with pytest.raises(ValueError, match="límite de crédito"):
        CustomerService(env["database"]).update(
            env["owner"],
            env["customer"].id,
            CustomerData("cedula", "1712345678", "Ana Pérez", credit_limit_cents=-1),
        )


def test_old_database_gets_credit_payments_allowed_in_sale_payments(tmp_path):
    """A database made before the module keeps its payments and accepts 'credit' after upgrade."""
    import sqlite3

    path = tmp_path / "old.db"
    database = Database(path)
    database.initialize()
    with database.connect() as connection:
        connection.executescript(
            """
            DROP TABLE sale_payments;
            CREATE TABLE sale_payments (
                id INTEGER PRIMARY KEY,
                sale_id INTEGER NOT NULL REFERENCES sales(id),
                method TEXT NOT NULL CHECK (method IN ('cash', 'transfer', 'card')),
                amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
                reference TEXT NOT NULL DEFAULT ''
            );
            INSERT INTO sales (total_cents, payment_cents, change_cents) VALUES (100, 100, 0);
            INSERT INTO sale_payments (sale_id, method, amount_cents) VALUES (1, 'cash', 100);
            """
        )
    database.initialize()
    with database.connect() as connection:
        rows = connection.execute("SELECT method, amount_cents FROM sale_payments").fetchall()
        assert [tuple(row) for row in rows] == [("cash", 100)]
        connection.execute(
            "INSERT INTO sale_payments (sale_id, method, amount_cents) VALUES (1, 'credit', 5)"
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO sale_payments (sale_id, method, amount_cents) VALUES (1, 'xx', 5)"
            )


LIMITED_ANA = CustomerData("cedula", "1712345678", "Ana Pérez", credit_limit_cents=2000)
OWNER_ONLY = "Solo el dueño puede realizar esta acción."


def test_a_cashier_cannot_create_a_customer_with_a_credit_limit(env):
    service = CustomerService(env["database"])

    with pytest.raises(PermissionError, match=OWNER_ONLY):
        service.create(
            env["cashier"], CustomerData("cedula", "1798765432", "Luis Mora", credit_limit_cents=1)
        )

    assert service.find_by_id_number(env["owner"], "1798765432") is None


def test_a_cashier_creates_a_customer_without_a_limit(env):
    service = CustomerService(env["database"])

    created = service.create(env["cashier"], CustomerData("cedula", "1798765432", "Luis Mora"))

    assert created.credit_limit_cents is None


def test_a_cashier_cannot_change_or_clear_a_credit_limit(env):
    service = CustomerService(env["database"])
    service.update(env["owner"], env["customer"].id, LIMITED_ANA)

    for limit in (5000, None):
        with pytest.raises(PermissionError, match=OWNER_ONLY):
            service.update(
                env["cashier"],
                env["customer"].id,
                CustomerData("cedula", "1712345678", "Ana Pérez", credit_limit_cents=limit),
            )

    assert service.find_by_id_number(env["owner"], "1712345678").credit_limit_cents == 2000


def test_a_cashier_edits_other_fields_keeping_the_limit_and_the_owner_changes_it(env):
    service = CustomerService(env["database"])
    service.update(env["owner"], env["customer"].id, LIMITED_ANA)

    edited = service.update(
        env["cashier"],
        env["customer"].id,
        CustomerData("cedula", "1712345678", "Ana P. Pérez", credit_limit_cents=2000),
    )
    raised = service.update(
        env["owner"],
        env["customer"].id,
        CustomerData("cedula", "1712345678", "Ana P. Pérez", credit_limit_cents=5000),
    )

    assert (edited.full_name, edited.credit_limit_cents) == ("Ana P. Pérez", 2000)
    assert raised.credit_limit_cents == 5000
