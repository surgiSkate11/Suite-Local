import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QDialog
from sale_owner import owner_session

from suitelocal.application.auth import AuthService
from suitelocal.application.credit import CreditService
from suitelocal.application.customers import CustomerService
from suitelocal.domain.auth import Session
from suitelocal.domain.customers import CustomerData
from suitelocal.domain.models import Payment, Sale, SaleItem
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import ProductRepository, SaleRepository
from suitelocal.infrastructure.settings import BusinessSettingsRepository
from suitelocal.ui.abono_dialog import AbonoDialog
from suitelocal.ui.customer_dialog import CustomerDialog
from suitelocal.ui.customers import CustomersWidget

ANA = CustomerData("cedula", "1712345678", "Ana Pérez")
LUIS = CustomerData("cedula", "1798765432", "Luis Mora")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class Env:
    def __init__(self, tmp_path, *, module_on=True) -> None:
        self.database = Database(tmp_path / "fiado_customers.db")
        self.database.initialize()
        self.owner = owner_session(self.database)
        self.cashier = Session(
            AuthService(self.database).create_cashier(
                self.owner, "cajero", "clave-cajero", "clave-cajero"
            )
        )
        if module_on:
            BusinessSettingsRepository(self.database).update_profile(
                self.owner.user.business_id, enabled_modules={"fiado"}
            )
        self.customers = CustomerService(self.database)
        self.credit = CreditService(self.database)
        self.sales = SaleRepository(self.database)
        self.product = ProductRepository(self.database).add(
            "A-1", "Arroz", 250, 500, tax_rate_basis_points=0
        )
        self.ana = self.customers.create(self.owner, ANA)
        self.luis = self.customers.create(self.owner, LUIS)

    def owe(self, customer, cents: int) -> None:
        self.sales.register(
            Sale(
                (SaleItem(self.product.id, "Arroz", cents // 250, 250),),
                cents,
                (Payment("credit", cents),),
            ),
            business_id=self.owner.user.business_id,
            user_id=self.owner.user.id,
            customer_id=customer.id,
        )


@pytest.fixture
def env(qapp, tmp_path):
    return Env(tmp_path)


class FakeAbonoDialog:
    """Stands in for the modal dialog: takes a fixed abono when it is "executed"."""

    amount = 300
    method = "cash"
    reference = ""
    opened_with: list[int] = []

    def __init__(self, credit, session, customer, balance_cents, **kwargs) -> None:
        self.credit = credit
        self.session = session
        self.customer = customer
        self.entry = None
        FakeAbonoDialog.opened_with.append(balance_cents)

    def exec(self) -> QDialog.DialogCode:
        self.entry = self.credit.register_payment(
            self.session, self.customer.id, self.amount, self.method, self.reference
        )
        return QDialog.DialogCode.Accepted

    def deleteLater(self) -> None:
        pass


def make_page(env, session=None, **kwargs) -> CustomersWidget:
    page = CustomersWidget(
        env.customers,
        session or env.owner,
        credit=env.credit,
        abono_dialog_factory=FakeAbonoDialog,
        **kwargs,
    )
    page.show()
    return page


def select(page: CustomersWidget, customer) -> None:
    for row, candidate in enumerate(page._customers):
        if candidate.id == customer.id:
            page.table.selectRow(row)
            return
    raise AssertionError("customer not in the list")


def cells(table, row: int) -> list[str]:
    return [table.item(row, column).text() for column in range(table.columnCount())]


# -- the credit limit in the customer dialog ------------------------------------------------


def test_the_customer_dialog_has_a_credit_limit_only_with_the_module_on(qapp, tmp_path):
    on = Env(tmp_path / "on")
    off = Env(tmp_path / "off", module_on=False)

    assert CustomerDialog(on.customers, on.owner).credit_enabled is True
    assert CustomerDialog(off.customers, off.owner).credit_enabled is False


def test_saving_a_customer_stores_the_typed_limit_in_cents(env):
    dialog = CustomerDialog(env.customers, env.owner)
    dialog.id_edit.setText("1700000001")
    dialog.name_edit.setText("Rosa")
    dialog.limit_edit.setText("50,5")

    dialog.save()

    assert dialog.customer.credit_limit_cents == 5050


def test_an_empty_limit_means_no_limit(env):
    dialog = CustomerDialog(env.customers, env.owner)
    dialog.id_edit.setText("1700000001")
    dialog.name_edit.setText("Rosa")

    dialog.save()

    assert dialog.customer.credit_limit_cents is None


@pytest.mark.parametrize("text", ["abc", "-5", "nan", "inf", "100001"])
def test_an_invalid_limit_shows_a_spanish_error_and_saves_nothing(env, text):
    dialog = CustomerDialog(env.customers, env.owner)
    dialog.id_edit.setText("1700000001")
    dialog.name_edit.setText("Rosa")
    dialog.limit_edit.setText(text)

    dialog.save()

    assert dialog.customer is None
    assert "límite de crédito" in dialog.message.text()
    assert env.customers.find_by_id_number(env.owner, "1700000001") is None


def test_editing_shows_the_saved_limit_and_changing_it_updates_it(env):
    saved = env.customers.update(
        env.owner,
        env.ana.id,
        CustomerData("cedula", "1712345678", "Ana Pérez", credit_limit_cents=2000),
    )
    dialog = CustomerDialog(env.customers, env.owner, customer=saved)
    assert dialog.limit_edit.text() == "20,00"

    dialog.limit_edit.setText("35")
    dialog.save()

    assert dialog.customer.credit_limit_cents == 3500


def test_editing_with_the_module_off_keeps_the_saved_limit(qapp, tmp_path):
    env = Env(tmp_path, module_on=False)
    saved = env.customers.update(
        env.owner,
        env.ana.id,
        CustomerData("cedula", "1712345678", "Ana Pérez", credit_limit_cents=2000),
    )
    dialog = CustomerDialog(env.customers, env.owner, customer=saved)
    dialog.name_edit.setText("Ana P. Pérez")

    dialog.save()

    assert dialog.customer.credit_limit_cents == 2000


def set_separator(env, separator: str) -> None:
    BusinessSettingsRepository(env.database).update_profile(
        env.owner.user.business_id, decimal_separator=separator
    )


def limited_ana(env, cents: int):
    return env.customers.update(
        env.owner,
        env.ana.id,
        CustomerData("cedula", "1712345678", "Ana Pérez", credit_limit_cents=cents),
    )


def test_the_limit_field_is_only_for_the_owner(env):
    owner_dialog = CustomerDialog(env.customers, env.owner)
    assert owner_dialog.limit_edit.isVisibleTo(owner_dialog) is True
    cashier_dialog = CustomerDialog(env.customers, env.cashier)

    assert cashier_dialog.limit_edit.isVisibleTo(cashier_dialog) is False


def test_a_cashier_creates_a_customer_without_a_limit_from_the_dialog(env):
    dialog = CustomerDialog(env.customers, env.cashier)
    dialog.id_edit.setText("1700000001")
    dialog.name_edit.setText("Rosa")
    dialog.limit_edit.setText("99")

    dialog.save()

    assert dialog.customer is not None
    assert dialog.customer.credit_limit_cents is None


def test_a_cashier_editing_a_customer_keeps_the_saved_limit(env):
    dialog = CustomerDialog(env.customers, env.cashier, customer=limited_ana(env, 2000))
    dialog.name_edit.setText("Ana P. Pérez")
    dialog.limit_edit.setText("99")

    dialog.save()

    assert dialog.customer is not None
    assert (dialog.customer.full_name, dialog.customer.credit_limit_cents) == ("Ana P. Pérez", 2000)


@pytest.mark.parametrize(
    ("separator", "shown", "typed", "cents"),
    [
        (",", "1234,56", "1.234,5", 123450),
        (",", "1234,56", "50,5", 5050),
        (".", "1234.56", "1,234.5", 123450),
        (".", "1234.56", "50.5", 5050),
    ],
)
def test_the_limit_is_shown_and_parsed_with_the_business_separator(
    env, separator, shown, typed, cents
):
    set_separator(env, separator)
    dialog = CustomerDialog(env.customers, env.owner, customer=limited_ana(env, 123456))
    assert dialog.limit_edit.text() == shown

    dialog.limit_edit.setText(typed)
    dialog.save()

    assert dialog.customer is not None
    assert dialog.customer.credit_limit_cents == cents


@pytest.mark.parametrize(("separator", "text"), [(",", "50.5"), (".", "50,5"), (",", "1.23")])
def test_a_limit_typed_with_the_other_separator_is_rejected(env, separator, text):
    set_separator(env, separator)
    dialog = CustomerDialog(env.customers, env.owner, customer=limited_ana(env, 2000))
    dialog.limit_edit.setText(text)

    dialog.save()

    assert dialog.customer is None
    assert "límite de crédito" in dialog.message.text()


# -- the abono dialog -----------------------------------------------------------------------


def make_abono(env, customer, balance_cents) -> AbonoDialog:
    return AbonoDialog(env.credit, env.cashier, customer, balance_cents)


def test_the_abono_dialog_starts_with_the_whole_balance(env):
    env.owe(env.ana, 1000)
    dialog = make_abono(env, env.ana, 1000)

    assert dialog.amount_edit.text() == "10,00"
    assert "Ana Pérez debe $ 10,00" in dialog.summary_label.text()


def test_the_abono_dialog_registers_a_partial_cash_abono(env):
    env.owe(env.ana, 1000)
    dialog = make_abono(env, env.ana, 1000)
    dialog.amount_edit.setText("3,50")

    dialog.save()

    assert dialog.entry.amount_cents == 350
    assert dialog.entry.method == "cash"
    assert env.credit.balance_cents(env.owner, env.ana.id) == 650


def test_the_abono_dialog_rejects_more_than_the_balance(env):
    env.owe(env.ana, 1000)
    dialog = make_abono(env, env.ana, 1000)
    dialog.amount_edit.setText("10,01")

    dialog.save()

    assert dialog.entry is None
    assert "supera el saldo" in dialog.message.text()
    assert env.credit.balance_cents(env.owner, env.ana.id) == 1000


def test_the_abono_dialog_asks_for_a_reference_on_transfers(env):
    env.owe(env.ana, 1000)
    dialog = make_abono(env, env.ana, 1000)
    dialog.show()
    assert dialog.reference_edit.isVisible() is False
    dialog.method_combo.setCurrentIndex(dialog.method_combo.findData("transfer"))
    assert dialog.reference_edit.isVisible() is True

    dialog.save()
    assert dialog.entry is None
    assert "referencia" in dialog.message.text()

    dialog.reference_edit.setText("TR-9")
    dialog.save()
    assert dialog.entry.note == "TR-9"


def test_the_abono_dialog_rejects_text_that_is_not_an_amount(env):
    env.owe(env.ana, 1000)
    dialog = make_abono(env, env.ana, 1000)
    dialog.amount_edit.setText("diez")

    dialog.save()

    assert dialog.entry is None
    assert dialog.message.text() != ""


# -- the Clientes page ----------------------------------------------------------------------


def test_without_the_module_the_page_has_no_credit_controls(qapp, tmp_path):
    env = Env(tmp_path, module_on=False)
    page = make_page(env)

    assert page.credit_active is False
    assert page.balance_label.isVisible() is False
    assert page.abono_button.isVisible() is False
    assert page.debt_filter.isVisible() is False
    assert page.debtors_export_button is None or page.debtors_export_button.isVisible() is False
    assert page.table.columnCount() == 5


def test_the_detail_shows_the_balance_and_the_statement(env):
    env.owe(env.ana, 1000)
    env.credit.register_payment(env.owner, env.ana.id, 400, "cash")
    page = make_page(env)

    select(page, env.ana)

    assert page.balance_label.text() == "Saldo pendiente: $ 6,00"
    assert page.statement_table.rowCount() == 2
    abono, cargo = cells(page.statement_table, 0), cells(page.statement_table, 1)
    assert abono[1:] == ["Abono (Efectivo)", "", "$ 4,00", "$ 6,00"]
    assert cargo[1:] == ["Fiado", "Venta N.º 1", "$ 10,00", "$ 10,00"]


def test_a_customer_without_debt_shows_zero_and_disables_the_abono_button(env):
    page = make_page(env)

    select(page, env.ana)

    assert page.balance_label.text() == "Saldo pendiente: $ 0,00"
    assert page.abono_button.isEnabled() is False
    assert page.statement_table.rowCount() == 0


def test_registering_an_abono_updates_the_balance_and_tells_the_shell(env):
    env.owe(env.ana, 1000)
    FakeAbonoDialog.opened_with = []
    FakeAbonoDialog.amount = 300
    page = make_page(env)
    paid: list[bool] = []
    page.payment_registered.connect(lambda: paid.append(True))
    notes: list[tuple[str, str]] = []
    page.notification.connect(lambda text, kind: notes.append((text, kind)))
    select(page, env.ana)
    assert page.abono_button.isEnabled() is True

    page.abono_button.click()

    assert FakeAbonoDialog.opened_with == [1000]
    assert page.balance_label.text() == "Saldo pendiente: $ 7,00"
    assert page.statement_table.rowCount() == 2
    assert paid == [True]
    assert notes[-1] == ("Abono de $ 3,00 registrado a Ana Pérez.", "success")


def test_the_list_has_a_balance_column_and_the_con_saldo_chip_filters_debtors(env):
    env.owe(env.ana, 1000)
    page = make_page(env)

    assert page.table.columnCount() == 6
    rows = {cells(page.table, row)[0]: cells(page.table, row)[5] for row in range(2)}
    assert rows == {"Ana Pérez": "$ 10,00", "Luis Mora": "$ 0,00"}

    page.debt_filter.click()

    assert [customer.full_name for customer in page._customers] == ["Ana Pérez"]
    page.debt_filter.click()
    assert len(page._customers) == 2


def test_the_chip_combines_with_the_search(env):
    env.owe(env.ana, 1000)
    env.owe(env.luis, 500)
    page = make_page(env)
    page.debt_filter.click()

    page.search_edit.setText("luis")

    assert [customer.full_name for customer in page._customers] == ["Luis Mora"]


def test_the_page_shows_the_total_owed(env):
    env.owe(env.ana, 1000)
    env.owe(env.luis, 500)
    page = make_page(env)

    assert page.owed_label.text() == "Total adeudado: $ 15,00 (2 clientes)"


def test_only_the_owner_gets_the_debtors_export(env, tmp_path):
    env.owe(env.ana, 1000)
    cashier_page = make_page(env, session=env.cashier)
    assert cashier_page.debtors_export_button is None

    target = tmp_path / "deudores.csv"
    owner_page = make_page(env, save_path_picker=lambda _parent, _name: str(target))
    notes: list[tuple[str, str]] = []
    owner_page.notification.connect(lambda text, kind: notes.append((text, kind)))
    assert owner_page.debtors_export_button.text() == "Exportar deudores (CSV)"

    owner_page.debtors_export_button.click()

    assert (
        target.read_text(encoding="utf-8-sig").splitlines()[1] == "Ana Pérez;1712345678;;10,00;Sí"
    )
    assert notes[-1][1] == "success"


def test_the_cashier_can_take_an_abono_from_the_page(env):
    env.owe(env.ana, 1000)
    page = make_page(env, session=env.cashier)
    select(page, env.ana)

    page.abono_button.click()

    assert env.credit.balance_cents(env.owner, env.ana.id) == 700
