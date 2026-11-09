import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QDialog
from sale_owner import owner_session

from suitelocal.application.credit import CreditService
from suitelocal.application.customers import CustomerService
from suitelocal.domain.customers import CustomerData
from suitelocal.domain.models import Payment, Sale, SaleItem
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import ProductRepository, SaleRepository
from suitelocal.infrastructure.settings import BusinessSettingsRepository
from suitelocal.ui.payment_dialog import PaymentDialog
from suitelocal.ui.pos import PosWidget

ANA = CustomerData("cedula", "1712345678", "Ana Pérez")


class FakeCustomerDialog:
    def __init__(self, customers, session, customer=None, id_number="", parent=None) -> None:
        self.customer = None

    def exec(self) -> QDialog.DialogCode:
        return QDialog.DialogCode.Rejected

    def deleteLater(self) -> None:
        pass


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class Wired:
    def __init__(self, tmp_path, *, module_on=True) -> None:
        self.database = Database(tmp_path / "fiado_ui.db")
        self.database.initialize()
        self.owner = owner_session(self.database)
        self.settings = BusinessSettingsRepository(self.database)
        business_id = self.owner.user.business_id
        if module_on:
            self.settings.update_profile(business_id, enabled_modules={"fiado"})
        self.business = self.settings.get(business_id)
        self.products = ProductRepository(self.database)
        self.products.add("A-1", "Arroz", 250, 50, tax_rate_basis_points=0)
        self.customers = CustomerService(self.database)
        self.credit = CreditService(self.database)
        self.sales = SaleRepository(self.database)
        self.notifications: list[tuple[str, str]] = []
        self.pos = PosWidget(
            self.products,
            self.sales,
            self.business.enabled_payment_methods,
            enabled_modules=self.business.enabled_modules,
            session=self.owner,
            customers=self.customers,
            credit=self.credit,
            customer_dialog_factory=FakeCustomerDialog,
        )
        self.pos.notification.connect(lambda text, kind: self.notifications.append((text, kind)))
        self.pos.show()

    def add(self, code="A-1", quantity=1) -> None:
        self.pos.search_input.setText(f"{quantity}*{code}")
        self.pos.add_selected_product()

    def select(self, customer) -> None:
        self.pos.customer_picker.id_edit.setText(customer.id_number)
        self.pos.customer_picker.search_button.click()

    def sale_count(self) -> int:
        with self.database.connect() as connection:
            return connection.execute("SELECT COUNT(*) AS n FROM sales").fetchone()["n"]


@pytest.fixture
def wired(qapp, tmp_path):
    value = Wired(tmp_path)
    yield value
    value.pos.deleteLater()


# -- the method control ---------------------------------------------------------------------


def test_fiado_is_in_the_method_control_only_with_the_module_on(qapp, tmp_path):
    on = Wired(tmp_path / "on")
    off = Wired(tmp_path / "off", module_on=False)

    assert list(on.pos.method_control._buttons) == ["Efectivo", "Transferencia", "Fiado"]
    assert list(off.pos.method_control._buttons) == ["Efectivo", "Transferencia"]


def test_turning_the_module_on_adds_fiado_to_an_open_pos(qapp, tmp_path):
    off = Wired(tmp_path, module_on=False)
    off.settings.update_profile(off.owner.user.business_id, enabled_modules={"fiado"})

    off.pos.apply_business(off.settings.get(off.owner.user.business_id), [])

    assert "Fiado" in off.pos.method_control._buttons


def test_fiado_is_not_offered_when_the_pos_cannot_pick_a_customer(qapp, tmp_path):
    database = Database(tmp_path / "x.db")
    database.initialize()
    pos = PosWidget(ProductRepository(database), SaleRepository(database), ("cash", "credit"))
    assert list(pos.method_control._buttons) == ["Efectivo"]


# -- charging on credit ---------------------------------------------------------------------


def test_fiado_without_a_customer_shows_an_error_and_registers_nothing(wired):
    wired.add()
    wired.pos.method_control.select("Fiado")
    wired.pos.method_control.selected.emit("Fiado")

    wired.pos.confirm_sale()

    assert wired.sale_count() == 0
    assert wired.pos.checkout_message.text() == "El fiado necesita un cliente seleccionado."
    assert len(wired.pos.cart.lines) == 1


def test_fiado_with_a_customer_charges_the_account_and_clears_the_sale(wired):
    ana = wired.customers.create(wired.owner, ANA)
    wired.add(quantity=2)
    wired.select(ana)
    wired.pos.method_control.select("Fiado")
    wired.pos.method_control.selected.emit("Fiado")

    wired.pos.confirm_sale()

    assert wired.sale_count() == 1
    assert wired.credit.balance_cents(wired.owner, ana.id) == 500
    assert wired.pos.cart.lines == ()
    assert wired.notifications[-1][1] == "success"


def test_fiado_over_the_limit_is_rejected_and_shows_the_available_amount(wired):
    ana = wired.customers.create(
        wired.owner,
        CustomerData("cedula", "1712345678", "Ana Pérez", credit_limit_cents=400),
    )
    wired.add(quantity=2)
    wired.select(wired.customers.find_by_id_number(wired.owner, ana.id_number))
    wired.pos.method_control.select("Fiado")
    wired.pos.method_control.selected.emit("Fiado")

    wired.pos.confirm_sale()

    assert wired.sale_count() == 0
    text, kind = wired.notifications[-1]
    assert kind == "danger"
    assert "Disponible: $ 4,00" in text


# -- the balance next to the customer -------------------------------------------------------


def test_the_selected_customer_shows_the_balance_when_the_module_is_on(wired):
    ana = wired.customers.create(wired.owner, ANA)
    wired.sales.register(
        Sale((SaleItem(1, "Arroz", 4, 250),), 1000, (Payment("credit", 1000),)),
        business_id=wired.owner.user.business_id,
        user_id=wired.owner.user.id,
        customer_id=ana.id,
    )

    wired.select(ana)

    assert "Saldo pendiente: $ 10,00" in wired.pos.customer_picker.status_label.text()


def test_without_the_module_the_customer_shows_no_balance(qapp, tmp_path):
    off = Wired(tmp_path, module_on=False)
    ana = off.customers.create(off.owner, ANA)

    off.select(ana)

    assert "Saldo" not in off.pos.customer_picker.status_label.text()


# -- the split payment dialog ---------------------------------------------------------------


@pytest.fixture
def make_dialog(wired):
    created = []

    def build(**kwargs) -> PaymentDialog:
        dialog = PaymentDialog(
            1000,
            enabled_methods=("cash", "transfer", "credit"),
            customers=wired.customers,
            session=wired.owner,
            customer_dialog_factory=FakeCustomerDialog,
            credit=wired.credit,
            **kwargs,
        )
        dialog.show()
        created.append(dialog)
        return dialog

    yield build
    for dialog in created:
        dialog.close()
        dialog.deleteLater()


def test_the_dialog_offers_fiado_as_a_method_to_add(make_dialog):
    dialog = make_dialog()

    assert "credit" in dialog.payment_methods


def test_the_dialog_without_a_customer_service_does_not_offer_fiado(qapp):
    dialog = PaymentDialog(1000, enabled_methods=("cash", "credit"))

    assert "credit" not in dialog.payment_methods


def test_the_dialog_rejects_fiado_without_a_customer(make_dialog):
    dialog = make_dialog()

    assert dialog.add_payment("credit", 400) is False

    assert dialog.message.text() == "El fiado necesita un cliente seleccionado."
    assert dialog.payments == ()


def test_the_dialog_combines_cash_and_fiado_with_a_customer(wired, make_dialog):
    ana = wired.customers.create(wired.owner, ANA)
    dialog = make_dialog(customer=ana)

    assert dialog.add_payment("credit", 400) is True
    dialog._pick_bill(0)  # Exacto: the remaining 600 in cash
    dialog.confirm()

    assert dialog.payments == (Payment("credit", 400), Payment("cash", 600))
    assert dialog.change_cents == 0


def test_removing_the_customer_after_adding_fiado_blocks_the_confirmation(wired, make_dialog):
    ana = wired.customers.create(wired.owner, ANA)
    dialog = make_dialog(customer=ana)
    dialog.add_payment("credit", 1000)

    dialog.customer_picker.clear()
    dialog.confirm()

    assert dialog.payments == ()
    assert dialog.message.text() == "El fiado necesita un cliente seleccionado."
