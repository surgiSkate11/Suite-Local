import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from einvoice_env import build_env
from lxml import etree
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from suitelocal.application.catalog import CatalogService
from suitelocal.application.customers import CustomerService
from suitelocal.application.tables import TablesService
from suitelocal.domain.customers import CustomerData
from suitelocal.domain.models import Payment
from suitelocal.infrastructure.tables_repository import ensure_tables_schema
from suitelocal.ui.components.buyer_section import CONSUMER, WITH_DATA
from suitelocal.ui.payment_dialog import PaymentDialog
from suitelocal.ui.pos import PosWidget
from suitelocal.ui.tables import TablesWidget

ANA = CustomerData("cedula", "1712345678", "Ana Pérez", address="Calle 1", email="ana@correo.com")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


class Outputs:
    def print_receipt(self, receipt) -> None:
        pass

    def print_ride(self, ride) -> None:
        pass


class FakeCustomerDialog:
    def __init__(self, customers, session, customer=None, id_number="", parent=None) -> None:
        self.customers = customers
        self.session = session
        self.id_number = id_number
        self.customer = None

    def exec(self) -> QDialog.DialogCode:
        self.customer = self.customers.create(
            self.session, CustomerData("cedula", self.id_number, "Cliente Nuevo")
        )
        return QDialog.DialogCode.Accepted

    def deleteLater(self) -> None:
        pass


class Wired:
    def __init__(self, tmp_path, rsa_key, *, customers=True, invoicing=False) -> None:
        self.env = build_env(tmp_path, rsa_key)
        self.env.products.add("A-1", "Arroz", 250, 50, tax_rate_basis_points=1500)
        self.env.products.add("T-1", "Televisor", 6000, 50, tax_rate_basis_points=1500)
        self.customers = CustomerService(self.env.database)
        self.outputs = Outputs()
        self.pos = PosWidget(
            self.env.products,
            self.env.sales,
            ("cash", "transfer", "card"),
            session=self.env.owner,
            receipts=self.env.receipts,
            receipt_output=self.outputs,
            einvoices=self.env.service,
            ride_output=self.outputs,
            einvoicing_enabled=invoicing,
            customers=self.customers if customers else None,
            customer_dialog_factory=FakeCustomerDialog,
        )
        self.pos.show()

    def add(self, code: str, quantity: int = 1) -> None:
        self.pos.search_input.setText(f"{quantity}*{code}")
        self.pos.add_selected_product()

    def select(self, customer) -> None:
        self.pos.customer_picker.id_edit.setText(customer.id_number)
        self.pos.customer_picker.search_button.click()

    def sale_customer(self, sale_id: int = 1):
        with self.env.database.connect() as connection:
            row = connection.execute(
                "SELECT customer_id FROM sales WHERE id = ?", (sale_id,)
            ).fetchone()
        return row["customer_id"]


@pytest.fixture
def wired(qapp, tmp_path, rsa_key):
    value = Wired(tmp_path, rsa_key)
    yield value
    value.pos.deleteLater()


@pytest.fixture
def invoiced(qapp, tmp_path, rsa_key):
    value = Wired(tmp_path, rsa_key, invoicing=True)
    yield value
    value.pos.deleteLater()


# -- POS inline checkout -------------------------------------------------------------------


def test_without_a_customer_service_there_is_no_cliente_field(qapp, tmp_path, rsa_key):
    unwired = Wired(tmp_path, rsa_key, customers=False)

    assert unwired.pos.customer_picker is None


def test_the_default_sale_has_no_customer(wired):
    wired.add("A-1")
    wired.pos.received_edit.setText("5.00")

    wired.pos.confirm_sale()

    assert wired.pos.customer_picker is not None
    assert wired.sale_customer() is None


def test_a_selected_customer_is_stored_on_the_sale_and_cleared_afterwards(wired):
    saved = wired.customers.create(wired.env.owner, ANA)
    wired.add("A-1")
    wired.select(saved)
    wired.pos.received_edit.setText("5.00")

    wired.pos.confirm_sale()

    assert wired.sale_customer() == saved.id
    assert wired.pos.customer_picker.customer is None
    assert wired.pos.customer_picker.id_edit.text() == ""


def test_quitar_before_charging_leaves_the_sale_without_customer(wired):
    saved = wired.customers.create(wired.env.owner, ANA)
    wired.add("A-1")
    wired.select(saved)
    wired.pos.customer_picker.clear_button.click()
    wired.pos.received_edit.setText("5.00")

    wired.pos.confirm_sale()

    assert wired.sale_customer() is None


def test_registering_from_the_checkout_selects_the_new_customer(wired):
    wired.add("A-1")
    picker = wired.pos.customer_picker
    picker.id_edit.setText("1790012345")
    picker.search_button.click()
    picker.register_button.click()
    wired.pos.received_edit.setText("5.00")

    wired.pos.confirm_sale()

    stored = wired.customers.find_by_id_number(wired.env.owner, "1790012345")
    assert stored is not None
    assert wired.sale_customer() == stored.id


class SplitDialog:
    """The split PaymentDialog, answering with a customer picked inside it."""

    def __init__(self, chosen, **kwargs) -> None:
        self.kwargs = kwargs
        self.payments = (Payment("cash", kwargs["total_cents"]),)
        self.print_ticket = False
        self.buyer = None
        self.customer = chosen

    def exec(self) -> QDialog.DialogCode:
        return QDialog.DialogCode.Accepted

    def deleteLater(self) -> None:
        pass


def test_the_split_dialog_receives_the_customer_wiring_and_hands_back_its_choice(wired):
    saved = wired.customers.create(wired.env.owner, ANA)
    calls: list[SplitDialog] = []

    def factory(**kwargs):
        dialog = SplitDialog(saved, **kwargs)
        calls.append(dialog)
        return dialog

    wired.pos.payment_dialog_factory = factory
    wired.add("A-1")

    wired.pos.open_split_payment()

    kwargs = calls[0].kwargs
    assert kwargs["customers"] is wired.customers
    assert kwargs["session"] is wired.env.owner
    assert kwargs["customer"] is None
    assert wired.sale_customer() == saved.id


def test_the_split_dialog_starts_with_the_customer_already_chosen(wired):
    saved = wired.customers.create(wired.env.owner, ANA)
    calls: list[SplitDialog] = []

    def factory(**kwargs):
        dialog = SplitDialog(saved, **kwargs)
        calls.append(dialog)
        return dialog

    wired.pos.payment_dialog_factory = factory
    wired.add("A-1")
    wired.select(saved)

    wired.pos.open_split_payment()

    assert calls[0].kwargs["customer"] == saved


# -- buyer prefill (electronic invoicing) --------------------------------------------------


def test_choosing_a_customer_prefills_the_buyer_section_and_keeps_it_editable(invoiced):
    saved = invoiced.customers.create(invoiced.env.owner, ANA)
    invoiced.add("A-1")

    invoiced.select(saved)

    section = invoiced.pos.buyer_section
    assert section.mode_control.current == WITH_DATA
    assert section.type_combo.currentText() == "Cédula"
    assert section.identification_edit.text() == "1712345678"
    assert section.name_edit.text() == "Ana Pérez"
    assert section.address_edit.text() == "Calle 1"
    section.name_edit.setText("Ana P. de Mora")
    assert invoiced.pos.buyer_section.buyer(250) is not None
    assert invoiced.pos.buyer_section.buyer(250).name == "Ana P. de Mora"


def test_quitar_resets_an_untouched_prefill_but_keeps_an_edited_one(invoiced):
    saved = invoiced.customers.create(invoiced.env.owner, ANA)
    invoiced.select(saved)
    invoiced.pos.customer_picker.clear_button.click()
    assert invoiced.pos.buyer_section.mode_control.current == CONSUMER
    assert invoiced.pos.buyer_section.name_edit.text() == ""

    invoiced.select(saved)
    invoiced.pos.buyer_section.name_edit.setText("Otra persona")
    invoiced.pos.customer_picker.clear_button.click()
    assert invoiced.pos.buyer_section.name_edit.text() == "Otra persona"


def test_a_customer_does_not_lift_the_fifty_dollar_rule(invoiced):
    saved = invoiced.customers.create(invoiced.env.owner, ANA)
    invoiced.add("T-1")

    invoiced.select(saved)

    section = invoiced.pos.buyer_section
    assert section.mode_control.current == WITH_DATA
    assert not section.mode_control.is_option_enabled(CONSUMER)


def test_the_invoice_of_a_sale_to_a_customer_carries_the_email(invoiced):
    saved = invoiced.customers.create(invoiced.env.owner, ANA)
    invoiced.add("A-1")
    invoiced.select(saved)
    invoiced.pos.received_edit.setText("5.00")

    invoiced.pos.confirm_sale()

    einvoice = invoiced.env.service.get_for_sale(invoiced.env.owner, 1)
    assert einvoice is not None
    fields = etree.fromstring(einvoice.signed_xml).findall("infoAdicional/campoAdicional")
    assert [(field.get("nombre"), field.text) for field in fields] == [("Email", "ana@correo.com")]
    assert einvoice.buyer.name == "Ana Pérez"


# -- the real PaymentDialog ----------------------------------------------------------------


@pytest.fixture
def make_dialog(wired):
    created: list[PaymentDialog] = []

    def build(total_cents: int = 1000, **kwargs) -> PaymentDialog:
        dialog = PaymentDialog(
            total_cents, enabled_methods=("cash", "transfer", "card"), sale_label="Venta", **kwargs
        )
        dialog.show()
        created.append(dialog)
        return dialog

    yield build
    for dialog in created:
        dialog.close()
        dialog.deleteLater()


def customer_kwargs(wired, **extra):
    return {
        "customers": wired.customers,
        "session": wired.env.owner,
        "customer_dialog_factory": FakeCustomerDialog,
        **extra,
    }


def test_the_dialog_has_no_cliente_field_without_a_customer_service(make_dialog):
    dialog = make_dialog()

    assert dialog.customer_picker is None
    assert dialog.customer is None


def test_the_dialog_picks_a_customer_and_exposes_it(wired, make_dialog):
    saved = wired.customers.create(wired.env.owner, ANA)
    dialog = make_dialog(**customer_kwargs(wired))
    assert dialog.customer is None

    dialog.customer_picker.id_edit.setText("1712345678")
    dialog.customer_picker.search_button.click()

    assert dialog.customer == saved


def test_the_dialog_can_start_with_a_customer(wired, make_dialog):
    saved = wired.customers.create(wired.env.owner, ANA)

    dialog = make_dialog(**customer_kwargs(wired, customer=saved))

    assert dialog.customer == saved
    assert dialog.customer_picker.id_edit.text() == "1712345678"


def test_enter_in_the_cliente_field_searches_and_does_not_confirm_the_dialog(wired, make_dialog):
    saved = wired.customers.create(wired.env.owner, ANA)
    dialog = make_dialog(1000, **customer_kwargs(wired))
    dialog.pad_buttons["1"].click()
    dialog.pad_buttons["00"].click()
    dialog.pad_buttons["00"].click()
    assert dialog.covered

    dialog.customer_picker.id_edit.setText("1712345678")
    QTest.keyClick(dialog.customer_picker.id_edit, Qt.Key.Key_Return)

    assert dialog.customer == saved
    assert dialog.result() != QDialog.DialogCode.Accepted


def test_a_customer_picked_in_the_dialog_prefills_its_buyer_section(wired, make_dialog):
    saved = wired.customers.create(wired.env.owner, ANA)
    dialog = make_dialog(1000, **customer_kwargs(wired, invoicing=True))

    dialog.customer_picker.set_customer(saved)

    assert dialog.buyer_section.mode_control.current == WITH_DATA
    assert dialog.buyer_section.name_edit.text() == "Ana Pérez"


# -- Tables --------------------------------------------------------------------------------


class TablesDialog:
    def __init__(self, chosen, **kwargs) -> None:
        self.kwargs = kwargs
        self.payments = (Payment("cash", kwargs["total_cents"]),)
        self.print_ticket = False
        self.buyer = None
        self.customer = chosen

    def exec(self) -> QDialog.DialogCode:
        return QDialog.DialogCode.Accepted

    def deleteLater(self) -> None:
        pass


def test_charging_a_table_stores_the_customer_chosen_in_the_dialog(qapp, tmp_path, rsa_key):
    env = build_env(tmp_path, rsa_key)
    with env.database.connect() as connection:
        ensure_tables_schema(connection)
    coffee = env.products.add("C-1", "Café", 150, 10)
    customers = CustomerService(env.database)
    saved = customers.create(env.owner, ANA)
    service = TablesService(env.database)
    table = service.create_table(env.owner, "Mesa 1", "Salón")
    order = service.open_order(env.owner, table.id)
    service.add_product(env.owner, order.id, coffee.id, 2)
    calls: list[TablesDialog] = []

    def factory(**kwargs):
        dialog = TablesDialog(saved, **kwargs)
        calls.append(dialog)
        return dialog

    widget = TablesWidget(
        service,
        CatalogService(env.products),
        env.owner,
        payment_dialog_factory=factory,
        customers=customers,
        customer_dialog_factory=FakeCustomerDialog,
    )
    widget.refresh()
    widget.select_table(table.id)

    widget.charge_order()

    assert calls[0].kwargs["customers"] is customers
    assert calls[0].kwargs["session"] is env.owner
    with env.database.connect() as connection:
        row = connection.execute("SELECT customer_id FROM sales").fetchone()
    assert row["customer_id"] == saved.id


def test_charging_a_table_without_customer_service_works_as_before(qapp, tmp_path, rsa_key):
    env = build_env(tmp_path, rsa_key)
    with env.database.connect() as connection:
        ensure_tables_schema(connection)
    coffee = env.products.add("C-1", "Café", 150, 10)
    service = TablesService(env.database)
    table = service.create_table(env.owner, "Mesa 1", "Salón")
    order = service.open_order(env.owner, table.id)
    service.add_product(env.owner, order.id, coffee.id, 1)
    calls: list[TablesDialog] = []

    def factory(**kwargs):
        dialog = TablesDialog(None, **kwargs)
        calls.append(dialog)
        return dialog

    widget = TablesWidget(
        service, CatalogService(env.products), env.owner, payment_dialog_factory=factory
    )
    widget.refresh()
    widget.select_table(table.id)

    widget.charge_order()

    assert "customers" not in calls[0].kwargs
    with env.database.connect() as connection:
        row = connection.execute("SELECT customer_id FROM sales").fetchone()
    assert row["customer_id"] is None
