import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QDialog

from suitelocal.application.auth import AuthService
from suitelocal.application.customers import CustomerService
from suitelocal.domain.auth import Session
from suitelocal.domain.customers import CustomerData
from suitelocal.domain.models import Sale, SaleItem
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import ProductRepository, SaleRepository
from suitelocal.ui.customers import HEADERS, CustomersWidget

ANA = CustomerData(
    "cedula",
    "1712345678",
    "Ana Pérez",
    phone="0991112222",
    email="ana@correo.com",
    accepts_offers=True,
)
LUIS = CustomerData("cedula", "0912345678", "Luis Mora")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class FakeDialog:
    """Stands in for CustomerDialog: "saves" the configured data without showing anything."""

    calls: list[dict] = []
    data: CustomerData | None = None

    def __init__(self, customers, session, customer=None, id_number="", parent=None) -> None:
        self.customers = customers
        self.session = session
        self.editing = customer
        self.customer = None
        FakeDialog.calls.append({"customer": customer, "id_number": id_number})

    def exec(self) -> QDialog.DialogCode:
        data = FakeDialog.data
        if data is None:
            return QDialog.DialogCode.Rejected
        if self.editing is None:
            self.customer = self.customers.create(self.session, data)
        else:
            self.customer = self.customers.update(self.session, self.editing.id, data)
        return QDialog.DialogCode.Accepted

    def deleteLater(self) -> None:
        pass


class Env:
    def __init__(self, tmp_path) -> None:
        self.database = Database(tmp_path / "customers_page.db")
        self.database.initialize()
        auth = AuthService(self.database)
        self.owner = Session(
            auth.setup_owner("Barbería", "dueno", "Clave-segura-1", "Clave-segura-1")
        )
        self.cashier = Session(
            auth.create_cashier(self.owner, "cajero", "Clave-segura-2", "Clave-segura-2")
        )
        self.service = CustomerService(self.database)
        self.confirm_answer = True
        self.confirm_calls: list[str] = []
        self.save_path: str | None = None
        self.notices: list[tuple[str, str]] = []

    def build(self, session: Session | None = None) -> CustomersWidget:
        FakeDialog.calls = []
        FakeDialog.data = None
        widget = CustomersWidget(
            self.service,
            session or self.owner,
            dialog_factory=FakeDialog,
            confirmer=self.confirm,
            save_path_picker=lambda _parent, _name: self.save_path,
        )
        widget.notification.connect(lambda text, state: self.notices.append((text, state)))
        return widget

    def confirm(self, _parent, _title, text) -> bool:
        self.confirm_calls.append(text)
        return self.confirm_answer

    def sell(self, customer_id: int, price_cents: int) -> None:
        product = ProductRepository(self.database).add(f"P{price_cents}", "Corte", price_cents, 50)
        SaleRepository(self.database).register(
            Sale((SaleItem(product.id, product.name, 1, price_cents),), price_cents),
            business_id=self.owner.user.business_id,
            user_id=self.owner.user.id,
            customer_id=customer_id,
        )


@pytest.fixture
def env(qapp, tmp_path):
    return Env(tmp_path)


def rows(widget: CustomersWidget) -> list[tuple[str, ...]]:
    table = widget.table
    return [
        tuple(table.item(row, column).text() for column in range(table.columnCount()))
        for row in range(table.rowCount())
    ]


def test_the_table_lists_the_customers_with_their_offers_answer(env):
    env.service.create(env.owner, ANA)
    env.service.create(env.owner, LUIS)

    widget = env.build()

    assert HEADERS == ["Nombres", "Identificación", "Teléfono", "Correo", "Ofertas"]
    assert rows(widget) == [
        ("Ana Pérez", "1712345678", "0991112222", "ana@correo.com", "Sí"),
        ("Luis Mora", "0912345678", "", "", "No"),
    ]


def test_an_empty_business_shows_an_empty_state_hint(env):
    widget = env.build()

    assert widget.table.rowCount() == 0
    assert not widget.empty_state.isHidden()


def test_searching_filters_by_name_or_identification(env):
    env.service.create(env.owner, ANA)
    env.service.create(env.owner, LUIS)
    widget = env.build()

    widget.search_edit.setText("jose")
    assert rows(widget) == []
    widget.search_edit.setText("pere")
    assert [row[0] for row in rows(widget)] == ["Ana Pérez"]
    widget.search_edit.setText("0912")
    assert [row[0] for row in rows(widget)] == ["Luis Mora"]


def test_nuevo_cliente_opens_the_dialog_and_lists_the_saved_customer(env):
    widget = env.build()
    FakeDialog.data = ANA

    widget.new_button.click()

    assert FakeDialog.calls == [{"customer": None, "id_number": ""}]
    assert [row[0] for row in rows(widget)] == ["Ana Pérez"]
    assert widget.selected_customer() is not None


def test_cancelling_the_dialog_changes_nothing(env):
    widget = env.build()

    widget.new_button.click()

    assert rows(widget) == []


def test_editar_opens_the_dialog_with_the_selected_customer(env):
    saved = env.service.create(env.owner, ANA)
    widget = env.build()
    widget.table.selectRow(0)
    FakeDialog.data = CustomerData("cedula", "1712345678", "Ana Pérez Mora")

    widget.edit_button.click()

    assert FakeDialog.calls[0]["customer"] == saved
    assert rows(widget)[0][0] == "Ana Pérez Mora"


def test_editar_without_a_selection_does_nothing(env):
    env.service.create(env.owner, ANA)
    widget = env.build()

    widget.edit_button.click()

    assert FakeDialog.calls == []


def test_selecting_a_customer_shows_the_last_purchases_and_the_total(env):
    saved = env.service.create(env.owner, ANA)
    env.sell(saved.id, 1000)
    env.sell(saved.id, 250)
    widget = env.build()

    widget.table.selectRow(0)

    assert "Ana Pérez" in widget.detail_title.text()
    assert widget.total_label.text() == "Total comprado: $ 12,50"
    assert widget.purchases_table.rowCount() == 2
    assert {widget.purchases_table.item(row, 2).text() for row in range(2)} == {"$ 10,00", "$ 2,50"}


def test_a_customer_without_purchases_says_so(env):
    env.service.create(env.owner, LUIS)
    widget = env.build()

    widget.table.selectRow(0)

    assert widget.total_label.text() == "Total comprado: $ 0,00"
    assert widget.purchases_table.rowCount() == 0


def test_without_a_selection_the_detail_asks_to_pick_one(env):
    env.service.create(env.owner, LUIS)

    widget = env.build()

    assert "Elegí un cliente" in widget.detail_title.text()


# -- roles ---------------------------------------------------------------------------------


def test_the_cashier_has_no_deactivate_or_export_buttons(env):
    widget = env.build(env.cashier)

    assert widget.deactivate_button is None
    assert widget.export_button is None
    assert widget.new_button is not None and widget.edit_button is not None


def test_the_owner_deactivates_after_confirming(env):
    env.service.create(env.owner, ANA)
    widget = env.build()
    widget.table.selectRow(0)

    widget.deactivate_button.click()

    assert "Ana Pérez" in env.confirm_calls[0]
    assert rows(widget) == []
    assert env.service.find_by_id_number(env.owner, "1712345678") is None


def test_declining_the_confirmation_keeps_the_customer(env):
    env.service.create(env.owner, ANA)
    env.confirm_answer = False
    widget = env.build()
    widget.table.selectRow(0)

    widget.deactivate_button.click()

    assert len(rows(widget)) == 1


def test_the_owner_exports_the_customers_who_accept_offers(env, tmp_path):
    env.service.create(env.owner, ANA)
    env.service.create(env.owner, LUIS)
    widget = env.build()
    env.save_path = str(tmp_path / "ofertas.csv")

    widget.export_button.click()

    text = (tmp_path / "ofertas.csv").read_text(encoding="utf-8-sig")
    assert "Ana Pérez" in text and "Luis Mora" not in text
    assert env.notices[-1][1] == "success"


def test_cancelling_the_save_picker_writes_nothing(env, tmp_path):
    env.service.create(env.owner, ANA)
    widget = env.build()
    env.save_path = None

    widget.export_button.click()

    assert list(tmp_path.glob("*.csv")) == []
    assert env.notices == []
