import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from einvoice_env import build_env
from PySide6.QtWidgets import QApplication, QDialog

from suitelocal.application.receipts import Receipt
from suitelocal.domain.einvoice import Buyer
from suitelocal.domain.models import Payment
from suitelocal.ui.components.buyer_section import CONSUMER, WITH_DATA
from suitelocal.ui.pos import PosWidget
from suitelocal.ui.ride import Ride

NOT_ENABLED = "La factura electrónica no está activada para este negocio."


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


class Outputs:
    def __init__(self) -> None:
        self.tickets: list[Receipt] = []
        self.rides: list[Ride] = []

    def print_receipt(self, receipt: Receipt) -> None:
        self.tickets.append(receipt)

    def print_ride(self, ride: Ride) -> None:
        self.rides.append(ride)


class FakeDialog:
    def __init__(self, payments, buyer, print_ticket=True) -> None:
        self.payments = payments
        self.buyer = buyer
        self.print_ticket = print_ticket

    def exec(self) -> QDialog.DialogCode:
        return QDialog.DialogCode.Accepted

    def deleteLater(self) -> None:
        pass


class Wired:
    def __init__(self, tmp_path, rsa_key, *, service_enabled=True, active=True) -> None:
        self.env = build_env(tmp_path, rsa_key, enabled=service_enabled)
        self.env.products.add("A-1", "Arroz", 250, 50, tax_rate_basis_points=1500)
        self.env.products.add("T-1", "Televisor", 6000, 50, tax_rate_basis_points=1500)
        self.outputs = Outputs()
        self.notices: list[tuple[str, str]] = []
        self.pos = PosWidget(
            self.env.products,
            self.env.sales,
            ("cash", "transfer", "card"),
            session=self.env.owner,
            receipts=self.env.receipts,
            receipt_output=self.outputs,
            einvoices=self.env.service,
            ride_output=self.outputs,
            einvoicing_enabled=active,
        )
        self.pos.notification.connect(lambda text, state: self.notices.append((text, state)))

    def add(self, code: str, quantity: int = 1) -> None:
        self.pos.search_input.setText(f"{quantity}*{code}")
        self.pos.add_selected_product()

    def sales(self) -> int:
        return self.env.sales.today_summary()[0]

    def invoice(self, sale_id: int = 1):
        return self.env.service.get_for_sale(self.env.owner, sale_id)

    def give_buyer(self, number="0912345678", name="Ana Pérez") -> None:
        section = self.pos.buyer_section
        section.mode_control.select(WITH_DATA)
        section.mode_control.selected.emit(WITH_DATA)
        section.identification_edit.setText(number)
        section.name_edit.setText(name)


@pytest.fixture
def wired(qapp, tmp_path, rsa_key):
    value = Wired(tmp_path, rsa_key)
    yield value
    value.pos.deleteLater()


def test_the_comprobante_section_shows_only_while_invoicing_is_active(qapp, tmp_path, rsa_key):
    active = Wired(tmp_path / "a", rsa_key)
    inactive = Wired(tmp_path / "b", rsa_key, active=False)

    assert not active.pos.buyer_section.isHidden()
    assert inactive.pos.buyer_section.isHidden()


def test_a_final_consumer_sale_issues_the_invoice_and_prints_the_ride(wired):
    wired.add("A-1")
    wired.pos.received_edit.setText("5.00")

    wired.pos.confirm_sale()

    assert wired.sales() == 1
    invoice = wired.invoice()
    assert invoice is not None and invoice.buyer == Buyer.final_consumer()
    assert len(wired.outputs.rides) == 1
    assert wired.outputs.tickets == []
    assert wired.notices[-1][1] == "success"


def test_a_sale_with_buyer_data_stores_them_in_the_invoice(wired):
    wired.add("A-1")
    wired.give_buyer()
    wired.pos.received_edit.setText("5.00")

    wired.pos.confirm_sale()

    invoice = wired.invoice()
    assert invoice is not None
    assert invoice.buyer == Buyer("05", "0912345678", "Ana Pérez")
    assert wired.outputs.rides[0].invoice.buyer.name == "Ana Pérez"


def test_invalid_buyer_data_block_the_sale_with_an_inline_error(wired):
    wired.add("A-1")
    wired.give_buyer(number="123")
    wired.pos.received_edit.setText("5.00")

    wired.pos.confirm_sale()

    assert wired.sales() == 0
    assert wired.invoice() is None
    assert wired.pos.buyer_section.message.text() == "La cédula debe tener exactamente 10 dígitos."
    assert wired.outputs.rides == [] and wired.outputs.tickets == []


def test_above_fifty_dollars_final_consumer_is_blocked_and_data_are_required(wired):
    wired.add("T-1")
    section = wired.pos.buyer_section

    assert not section.mode_control.is_option_enabled(CONSUMER)
    assert not section.hint_label.isHidden()
    wired.pos.received_edit.setText("100.00")
    wired.pos.confirm_sale()
    assert wired.sales() == 0
    assert section.message.text() == "El nombre del comprador es obligatorio."

    wired.give_buyer()
    wired.pos.confirm_sale()

    assert wired.sales() == 1
    invoice = wired.invoice()
    assert invoice is not None and invoice.buyer.identification == "0912345678"


def test_removing_the_expensive_product_lets_the_final_consumer_back(wired):
    wired.add("T-1")
    wired.pos.cart.clear()
    wired.pos.refresh_cart()

    assert wired.pos.buyer_section.mode_control.is_option_enabled(CONSUMER)


def test_a_failed_issue_keeps_the_sale_warns_and_prints_the_ticket(qapp, tmp_path, rsa_key):
    wired = Wired(tmp_path, rsa_key, service_enabled=False)
    wired.add("A-1")
    wired.pos.received_edit.setText("5.00")

    wired.pos.confirm_sale()

    assert wired.sales() == 1
    assert wired.invoice() is None
    warnings = [text for text, state in wired.notices if state == "warning"]
    assert len(warnings) == 1 and NOT_ENABLED in warnings[0]
    assert len(wired.outputs.tickets) == 1 and wired.outputs.rides == []
    wired.pos.deleteLater()


def test_with_the_print_switch_off_the_invoice_is_issued_and_nothing_prints(wired):
    wired.add("A-1")
    wired.pos.received_edit.setText("5.00")
    wired.pos.print_switch.setChecked(False)

    wired.pos.confirm_sale()

    assert wired.invoice() is not None
    assert wired.outputs.rides == [] and wired.outputs.tickets == []


def test_the_buyer_section_resets_after_the_sale(wired):
    wired.add("A-1")
    wired.give_buyer()
    wired.pos.received_edit.setText("5.00")

    wired.pos.confirm_sale()

    assert wired.pos.buyer_section.mode_control.current == CONSUMER
    assert wired.pos.buyer_section.name_edit.text() == ""


def test_a_split_sale_uses_the_buyer_of_the_dialog_and_hands_it_the_draft(wired):
    calls: list[dict] = []
    buyer = Buyer("04", "0912345678001", "Casa S.A.", "Av. 1")

    def factory(**kwargs):
        calls.append(kwargs)
        return FakeDialog((Payment("cash", 250),), buyer)

    wired.pos.payment_dialog_factory = factory
    wired.add("A-1")
    wired.give_buyer(name="Borrador")

    wired.pos.open_split_payment()

    assert calls[0]["invoicing"] is True
    assert calls[0]["buyer_draft"].name == "Borrador"
    assert wired.invoice().buyer == buyer
    assert len(wired.outputs.rides) == 1 and wired.outputs.tickets == []


def test_a_split_sale_follows_the_dialog_print_switch(wired):
    wired.pos.payment_dialog_factory = lambda **_: FakeDialog(
        (Payment("cash", 250),), Buyer.final_consumer(), print_ticket=False
    )
    wired.add("A-1")

    wired.pos.open_split_payment()

    assert wired.invoice() is not None
    assert wired.outputs.rides == [] and wired.outputs.tickets == []


def test_reprinting_the_last_ticket_prints_the_ride_of_an_invoiced_sale(wired):
    wired.add("A-1")
    wired.pos.received_edit.setText("5.00")
    wired.pos.confirm_sale()

    assert wired.pos.reprint_last_ticket() is True

    assert len(wired.outputs.rides) == 2 and wired.outputs.tickets == []


def test_with_invoicing_off_nothing_changes(qapp, tmp_path, rsa_key):
    wired = Wired(tmp_path, rsa_key, active=False)
    wired.add("A-1")
    wired.pos.received_edit.setText("5.00")

    wired.pos.confirm_sale()

    assert wired.sales() == 1
    assert wired.invoice() is None
    assert len(wired.outputs.tickets) == 1 and wired.outputs.rides == []
    wired.pos.deleteLater()


def test_split_dialog_gets_no_invoicing_arguments_while_invoicing_is_off(qapp, tmp_path, rsa_key):
    wired = Wired(tmp_path, rsa_key, active=False)
    calls: list[dict] = []

    def factory(**kwargs):
        calls.append(kwargs)
        return FakeDialog((Payment("cash", 250),), None)

    wired.pos.payment_dialog_factory = factory
    wired.add("A-1")
    wired.pos.open_split_payment()

    assert "invoicing" not in calls[0] and "buyer_draft" not in calls[0]
    assert wired.invoice() is None
    wired.pos.deleteLater()


def test_apply_business_switches_the_section_with_the_saved_settings(wired):
    settings = wired.env.settings.get(wired.env.owner.user.business_id)

    wired.pos.apply_business(replace(settings, einvoice_enabled=False), ())
    assert wired.pos.buyer_section.isHidden()

    wired.pos.apply_business(settings, ())
    assert not wired.pos.buyer_section.isHidden()
