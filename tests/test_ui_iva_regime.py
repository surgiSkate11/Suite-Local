"""Screens and ticket when the business does not charge IVA, and when it does."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from PySide6.QtWidgets import QApplication, QDialog
from sale_owner import owner_session

from suitelocal.application.business_profile import BusinessProfileService
from suitelocal.application.catalog import CatalogService
from suitelocal.application.receipts import (
    Receipt,
    ReceiptBusiness,
    ReceiptLine,
    ReceiptPayment,
    ReceiptTax,
)
from suitelocal.application.tables import TablesService
from suitelocal.domain.models import Payment
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import (
    CategoryRepository,
    ProductRepository,
    SaleRepository,
)
from suitelocal.infrastructure.settings import BusinessSettingsRepository
from suitelocal.infrastructure.tables_repository import ensure_tables_schema
from suitelocal.ui.inventory import InventoryWidget
from suitelocal.ui.pos import PosWidget
from suitelocal.ui.receipt import render_receipt_html
from suitelocal.ui.tables import TablesWidget


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class Env:
    def __init__(self, tmp_path) -> None:
        self.database = Database(tmp_path / "iva-ui.db")
        self.database.initialize()
        with self.database.connect() as connection:
            ensure_tables_schema(connection)
        self.owner = owner_session(self.database)
        self.products = ProductRepository(self.database)
        self.juice = self.products.add("J-1", "Jugo", 115, 20, tax_rate_basis_points=1500)
        self.profile = BusinessProfileService(
            BusinessSettingsRepository(self.database), CategoryRepository(self.database)
        )

    def use_regime(self, regime: str) -> None:
        ruc = "1790012345001" if regime in ("general", "rimpe_emprendedor") else ""
        self.profile.update_profile(self.owner, tax_regime=regime, ruc=ruc)

    def pos(self, regime: str) -> PosWidget:
        widget = PosWidget(
            self.products,
            SaleRepository(self.database),
            ("cash",),
            tax_regime=regime,
            session=self.owner,
        )
        widget.search_input.setText("2*J-1")
        widget.add_selected_product()
        return widget


@pytest.fixture
def env(qapp, tmp_path):
    return Env(tmp_path)


# -- counter ----------------------------------------------------------------------------


def test_pos_without_iva_shows_the_total_and_no_iva_note(env):
    widget = env.pos("sin_registro")
    widget.show()

    assert widget.total_label.text() == "$ 2,30"
    assert not widget.tax_label.isVisible()
    assert not widget.subtotal_label.isVisible()
    assert widget.cart.tax_cents == 0
    widget.deleteLater()


def test_pos_with_iva_shows_the_split_and_the_note(env):
    widget = env.pos("general")
    widget.show()

    assert widget.subtotal_label.text() == "Subtotal $ 2,00"
    assert widget.tax_label.text() == "IVA incluido $ 0,30"
    assert widget.tax_label.isVisible()
    widget.deleteLater()


def test_pos_adopts_a_regime_change_without_rebuilding(env):
    widget = env.pos("sin_registro")
    widget.show()
    env.use_regime("general")

    widget.apply_business(env.profile.get(env.owner), [])

    assert widget.tax_label.text() == "IVA incluido $ 0,30"
    assert widget.tax_label.isVisible()
    assert widget.total_label.text() == "$ 2,30"
    widget.deleteLater()


def test_pos_sale_without_iva_is_stored_at_rate_zero(env):
    widget = env.pos("sin_registro")
    widget.received_edit.setText("5.00")

    widget.confirm_sale()

    with env.database.connect() as connection:
        sale = connection.execute("SELECT subtotal_cents, tax_cents FROM sales").fetchone()
        item = connection.execute("SELECT tax_rate_basis_points FROM sale_items").fetchone()
        product = connection.execute(
            "SELECT tax_rate_basis_points FROM products WHERE id = ?", (env.juice.id,)
        ).fetchone()
    assert tuple(sale) == (230, 0)
    assert item[0] == 0
    assert product[0] == 1500
    widget.deleteLater()


def test_the_split_dialog_gets_no_iva_note_without_iva(env):
    widget = env.pos("sin_registro")
    calls: list[dict] = []

    class Dialog:
        payments = ()
        print_ticket = False
        buyer = None
        customer = None

        def __init__(self, **kwargs) -> None:
            calls.append(kwargs)

        def exec(self) -> QDialog.DialogCode:
            return QDialog.DialogCode.Rejected

        def deleteLater(self) -> None:
            pass

    widget.payment_dialog_factory = Dialog
    widget.open_split_payment()

    assert calls[0]["total_note"] == ""
    widget.deleteLater()


# -- tables -----------------------------------------------------------------------------


def tables_widget(env, calls: list[dict]) -> tuple[TablesWidget, int]:
    service = TablesService(env.database)
    table = service.create_table(env.owner, "Mesa 1")
    order = service.open_order(env.owner, table.id)
    service.add_product(env.owner, order.id, env.juice.id, 2)

    class Dialog:
        payments = (Payment("cash", 230),)
        print_ticket = False
        buyer = None
        customer = None

        def __init__(self, **kwargs) -> None:
            calls.append(kwargs)

        def exec(self) -> QDialog.DialogCode:
            return QDialog.DialogCode.Accepted

        def deleteLater(self) -> None:
            pass

    widget = TablesWidget(
        service,
        CatalogService(env.products),
        env.owner,
        payment_dialog_factory=Dialog,
    )
    widget.select_table(table.id)
    return widget, order.id


def test_tables_show_no_iva_note_without_iva(env):
    widget, _ = tables_widget(env, [])
    widget.show()

    assert widget.total_note.text() == ""


def test_tables_show_the_iva_note_under_the_general_regime(env):
    env.use_regime("general")
    widget, _ = tables_widget(env, [])

    assert widget.total_note.text() == "IVA incluido $ 0,30"


def test_a_table_charge_without_iva_stores_rate_zero_through_the_widget(env):
    calls: list[dict] = []
    widget, _ = tables_widget(env, calls)

    widget.charge_order()

    assert calls[0]["total_note"] == ""
    with env.database.connect() as connection:
        item = connection.execute("SELECT tax_rate_basis_points, tax_cents FROM sale_items")
        assert tuple(item.fetchone()) == (0, 0)


# -- inventory --------------------------------------------------------------------------


def test_inventory_hides_the_iva_rate_field_and_column_without_iva(env):
    widget = InventoryWidget(env.products, env.owner)
    widget.show()
    widget.open_new_product()

    assert not widget.tax_rate.isVisible()
    assert widget.table.isColumnHidden(4)
    assert widget.table.horizontalHeaderItem(4).text() == "IVA"
    widget.deleteLater()


def test_inventory_shows_them_again_when_the_regime_charges_iva(env):
    widget = InventoryWidget(env.products, env.owner)
    widget.show()
    env.use_regime("general")

    widget.refresh_profile()
    widget.open_new_product()

    assert widget.tax_rate.isVisible()
    assert not widget.table.isColumnHidden(4)
    widget.deleteLater()


def test_the_margin_without_iva_is_the_price_minus_the_cost(env):
    env.products.add("K-1", "Chuzo", 200, 5, cost_cents=120, tax_rate_basis_points=1500)
    widget = InventoryWidget(env.products, env.owner)

    row = next(
        row for row in range(widget.table.rowCount()) if widget.table.item(row, 0).text() == "K-1"
    )
    assert widget.table.item(row, 5).text() == "$ 0,80"
    env.use_regime("general")
    widget.refresh_profile()
    assert widget.table.item(row, 5).text() == "$ 0,54"
    widget.deleteLater()


def test_the_product_keeps_its_rate_when_saved_while_hidden(env):
    widget = InventoryWidget(env.products, env.owner)
    widget.open_new_product()
    widget.code.setText("N-1")
    widget.name.setText("Nuevo")
    widget.price.setText("1.00")
    widget.stock.setText("3")

    widget.save_product()

    stored = next(p for p in env.products.find_active("N-1"))
    assert stored.tax_rate_basis_points == 1500
    widget.deleteLater()


# -- ticket -----------------------------------------------------------------------------


def make_receipt(**changes) -> Receipt:
    receipt = Receipt(
        business=ReceiptBusiness("Chuzos", "", "", "", "Sin registro en el SRI", ""),
        number="000042",
        issued_at=datetime(2026, 3, 5, 15, 30, tzinfo=timezone(timedelta(hours=-5))),
        cashier="cajero",
        lines=(ReceiptLine("Jugo", 2, 115, 230, 0),),
        subtotal_cents=230,
        taxes=(ReceiptTax(0, 230, 0),),
        total_cents=230,
        payments=(ReceiptPayment("cash", 230, ""),),
        cash_received_cents=230,
        change_cents=0,
        charges_iva=False,
    )
    return replace(receipt, **changes)


def test_the_ticket_without_iva_shows_no_iva_or_base_or_subtotal(qapp):
    text = render_receipt_html(make_receipt(), ",", 80)

    assert "IVA" not in text
    assert "Base" not in text
    assert "Subtotal" not in text
    assert "2 × $ 1,15" in text
    assert "TOTAL" in text and "$ 2,30" in text


def test_the_ticket_with_iva_keeps_its_breakdown(qapp):
    receipt = make_receipt(
        charges_iva=True,
        lines=(ReceiptLine("Jugo", 2, 115, 230, 1500),),
        subtotal_cents=200,
        taxes=(ReceiptTax(1500, 200, 30),),
    )

    text = render_receipt_html(receipt, ",", 80)

    for expected in ("(IVA 15 %)", "Subtotal", "Base 15 %", "IVA 15 %", "$ 0,30"):
        assert expected in text, expected
