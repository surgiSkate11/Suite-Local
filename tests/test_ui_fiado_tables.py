import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QDialog
from sale_owner import owner_session

from suitelocal.application.catalog import CatalogService
from suitelocal.application.credit import CreditService
from suitelocal.application.customers import CustomerService
from suitelocal.application.tables import TablesService
from suitelocal.domain.customers import CustomerData
from suitelocal.domain.models import Payment
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import ProductRepository
from suitelocal.infrastructure.settings import BusinessSettingsRepository
from suitelocal.infrastructure.tables_repository import ensure_tables_schema
from suitelocal.ui.tables import TablesWidget


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class CreditDialog:
    """Stands in for the charge dialog: the cashier picked a customer and put it all on credit."""

    def __init__(self, chosen, **kwargs) -> None:
        self.kwargs = kwargs
        self.payments = (Payment("credit", kwargs["total_cents"]),)
        self.print_ticket = False
        self.buyer = None
        self.customer = chosen

    def exec(self) -> QDialog.DialogCode:
        return QDialog.DialogCode.Accepted

    def deleteLater(self) -> None:
        pass


def test_a_table_charged_on_credit_leaves_the_debt_on_the_customer(qapp, tmp_path):
    database = Database(tmp_path / "fiado_tables.db")
    database.initialize()
    with database.connect() as connection:
        ensure_tables_schema(connection)
    owner = owner_session(database)
    BusinessSettingsRepository(database).update_profile(
        owner.user.business_id, enabled_modules={"fiado"}
    )
    coffee = ProductRepository(database).add("C-1", "Café", 150, 10, tax_rate_basis_points=0)
    customers = CustomerService(database)
    credit = CreditService(database)
    ana = customers.create(owner, CustomerData("cedula", "1712345678", "Ana Pérez"))
    service = TablesService(database)
    table = service.create_table(owner, "Mesa 1", "Salón")
    order = service.open_order(owner, table.id)
    service.add_product(owner, order.id, coffee.id, 2)
    dialogs: list[CreditDialog] = []

    def factory(**kwargs):
        dialogs.append(CreditDialog(ana, **kwargs))
        return dialogs[-1]

    widget = TablesWidget(
        service,
        CatalogService(ProductRepository(database)),
        owner,
        enabled_payment_methods=("cash", "credit"),
        payment_dialog_factory=factory,
        customers=customers,
        credit=credit,
    )
    widget.refresh()
    widget.select_table(table.id)

    widget.charge_order()

    assert dialogs[0].kwargs["credit"] is credit
    assert credit.balance_cents(owner, ana.id) == 300
    assert service.get_order(owner, table.id) is None
