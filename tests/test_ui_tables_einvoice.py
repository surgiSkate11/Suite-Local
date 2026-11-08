import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from einvoice_env import build_env
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from suitelocal.application.catalog import CatalogService
from suitelocal.application.receipts import Receipt
from suitelocal.application.tables import TablesService
from suitelocal.domain.einvoice import Buyer
from suitelocal.domain.models import Payment
from suitelocal.infrastructure.tables_repository import ensure_tables_schema
from suitelocal.ui.ride import Ride
from suitelocal.ui.tables import TablesWidget

NOT_ENABLED = "La factura electrónica no está activada para este negocio."
BUYER = Buyer("05", "0912345678", "Ana Pérez")


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
    def __init__(self, payments, buyer, print_ticket) -> None:
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
        with self.env.database.connect() as connection:
            ensure_tables_schema(connection)
        self.env.products.add("C-1", "Café", 150, 10, tax_rate_basis_points=1500)
        self.tables = TablesService(self.env.database)
        self.table = self.tables.create_table(self.env.owner, "Mesa 1", "Salón")
        self.outputs = Outputs()
        self.notices: list[tuple[str, str]] = []
        self.dialog_calls: list[dict] = []
        self.buyer: Buyer | None = BUYER
        self.print_ticket = True
        self.issued_signals = 0
        self.widget = TablesWidget(
            self.tables,
            CatalogService(self.env.products),
            self.env.owner,
            enabled_payment_methods=("cash", "transfer"),
            payment_dialog_factory=self.dialog_factory,
            now=datetime.now,
            receipts=self.env.receipts,
            receipt_output=self.outputs,
            einvoices=self.env.service,
            ride_output=self.outputs,
            einvoicing_enabled=active,
        )
        self.widget.notification.connect(lambda text, state: self.notices.append((text, state)))
        self.widget.invoice_issued.connect(self._count_signal)

    def _count_signal(self) -> None:
        self.issued_signals += 1

    def dialog_factory(self, **kwargs) -> FakeDialog:
        self.dialog_calls.append(kwargs)
        return FakeDialog((Payment("cash", 300),), self.buyer, self.print_ticket)

    def charge(self) -> None:
        self.widget.select_table(self.table.id)
        self.widget.open_account()
        for _ in range(2):
            self.widget.search.setText("caf")
            QTest.keyClick(self.widget.search, Qt.Key.Key_Return)
        self.widget.charge_order()

    def invoice(self):
        return self.env.service.get_for_sale(self.env.owner, 1)


@pytest.fixture
def wired(qapp, tmp_path, rsa_key):
    value = Wired(tmp_path, rsa_key)
    yield value
    value.widget.deleteLater()


def test_the_dialog_gets_the_comprobante_section_while_invoicing_is_active(wired):
    wired.charge()

    assert wired.dialog_calls[0]["invoicing"] is True
    assert wired.dialog_calls[0]["buyer_draft"].with_data is False


def test_a_charge_issues_the_invoice_with_the_dialog_buyer_and_prints_the_ride(wired):
    wired.charge()

    invoice = wired.invoice()
    assert invoice is not None and invoice.buyer == BUYER
    assert len(wired.outputs.rides) == 1 and wired.outputs.tickets == []
    assert wired.issued_signals == 1


def test_without_print_the_invoice_is_issued_and_nothing_prints(wired):
    wired.print_ticket = False

    wired.charge()

    assert wired.invoice() is not None
    assert wired.outputs.rides == [] and wired.outputs.tickets == []


def test_a_failed_issue_keeps_the_charge_warns_and_prints_the_ticket(qapp, tmp_path, rsa_key):
    wired = Wired(tmp_path, rsa_key, service_enabled=False)

    wired.charge()

    assert wired.env.sales.today_summary()[0] == 1
    assert wired.invoice() is None
    warnings = [text for text, state in wired.notices if state == "warning"]
    assert len(warnings) == 1 and NOT_ENABLED in warnings[0]
    assert len(wired.outputs.tickets) == 1 and wired.outputs.rides == []
    wired.widget.deleteLater()


def test_with_invoicing_off_the_charge_works_as_before(qapp, tmp_path, rsa_key):
    wired = Wired(tmp_path, rsa_key, active=False)
    wired.buyer = None

    wired.charge()

    assert "invoicing" not in wired.dialog_calls[0] and "buyer_draft" not in wired.dialog_calls[0]
    assert wired.env.sales.today_summary()[0] == 1
    assert wired.invoice() is None
    assert len(wired.outputs.tickets) == 1 and wired.outputs.rides == []
    assert wired.issued_signals == 0
    wired.widget.deleteLater()
