"""Checkout polish: print-on-charge default, scrollable checkout, 4 quick keys, Clientes buttons."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog
from sale_owner import owner_session

from suitelocal.application.auth import AuthService
from suitelocal.application.catalog import CatalogService
from suitelocal.application.customers import CustomerService
from suitelocal.application.receipts import ReceiptService
from suitelocal.application.tables import TablesService
from suitelocal.domain.customers import CustomerData
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import ProductRepository, SaleRepository
from suitelocal.infrastructure.settings import BusinessSettingsRepository
from suitelocal.infrastructure.tables_repository import ensure_tables_schema
from suitelocal.ui.customers import CustomersWidget
from suitelocal.ui.payment_dialog import PaymentDialog
from suitelocal.ui.pos import QUICK_KEY_COUNT, PosWidget
from suitelocal.ui.settings import SettingsWidget
from suitelocal.ui.shell import AppShell
from suitelocal.ui.tables import TablesWidget
from suitelocal.ui.theme.qss import build_stylesheet
from suitelocal.ui.theme.tokens import LIGHT_TOKENS


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class FakeOutput:
    def __init__(self) -> None:
        self.printed: list = []

    def print_receipt(self, receipt) -> None:
        self.printed.append(receipt)


class Env:
    def __init__(self, tmp_path, products: int = 8) -> None:
        self.database = Database(tmp_path / "checkout.db")
        self.database.initialize()
        with self.database.connect() as connection:
            ensure_tables_schema(connection)
        self.owner = owner_session(self.database)
        self.products = ProductRepository(self.database)
        for index in range(products):
            self.products.add(f"P-{index}", f"Producto {index}", 250 + index, 50)
        self.output = FakeOutput()

    def pos(self, print_on_charge: bool = True) -> PosWidget:
        return PosWidget(
            self.products,
            SaleRepository(self.database),
            ("cash", "transfer"),
            session=self.owner,
            receipts=ReceiptService(self.database),
            receipt_output=self.output,
            print_on_charge=print_on_charge,
        )

    def add_lines(self, widget: PosWidget, count: int) -> None:
        for product in self.products.find_active("")[:count]:
            widget._add_product(product)


@pytest.fixture
def env(qapp, tmp_path):
    return Env(tmp_path)


# -- print on charge --------------------------------------------------------------------


def test_the_print_switch_starts_on_by_default(env):
    widget = env.pos()

    assert widget.print_switch.isChecked() is True
    assert widget.charge_button.text() == "Cobrar e imprimir"


def test_with_the_setting_off_the_switch_starts_off(env):
    widget = env.pos(print_on_charge=False)

    assert widget.print_switch.isChecked() is False
    assert widget.charge_button.text() == "Cobrar"


def test_with_the_setting_off_a_sale_prints_nothing_but_reprint_still_works(env):
    widget = env.pos(print_on_charge=False)
    env.add_lines(widget, 1)
    widget.received_edit.setText("5.00")

    widget.confirm_sale()

    assert widget.last_sale_id is not None
    assert env.output.printed == []
    assert widget.reprint_last_ticket() is True
    assert len(env.output.printed) == 1


def test_a_new_sale_starts_from_the_default_again(env):
    widget = env.pos(print_on_charge=False)
    widget.print_switch.setChecked(True)
    env.add_lines(widget, 1)
    widget.received_edit.setText("5.00")

    widget.confirm_sale()

    assert len(env.output.printed) == 1
    assert widget.print_switch.isChecked() is False


def test_the_split_dialog_and_tables_receive_the_default(env):
    widget = env.pos(print_on_charge=False)
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
    env.add_lines(widget, 1)
    widget.open_split_payment()
    assert calls[0]["print_by_default"] is False

    service = TablesService(env.database)
    table = service.create_table(env.owner, "Mesa 1")
    order = service.open_order(env.owner, table.id)
    service.add_product(env.owner, order.id, env.products.find_active("")[0].id)
    tables = TablesWidget(
        service,
        CatalogService(env.products),
        env.owner,
        payment_dialog_factory=Dialog,
        print_on_charge=False,
    )
    tables.select_table(table.id)
    tables._collect_payments("Mesa 1", tables.order)
    assert calls[1]["print_by_default"] is False


def test_the_payment_dialog_print_switch_follows_the_default(qapp):
    assert PaymentDialog(total_cents=100).print_ticket is True
    assert PaymentDialog(total_cents=100, print_by_default=False).print_ticket is False


def test_the_pos_adopts_a_saved_change_of_the_setting(env):
    widget = env.pos()
    repository = BusinessSettingsRepository(env.database)
    repository.update_profile(env.owner.user.business_id, print_on_charge=False)

    widget.apply_business(repository.get(env.owner.user.business_id), [])

    assert widget.print_switch.isChecked() is False


def test_the_cobro_card_saves_the_setting(qapp, env):
    settings = BusinessSettingsRepository(env.database)
    page = SettingsWidget(settings, env.owner, env.database, printer_names=lambda: ())
    assert page.print_on_charge.isChecked() is True

    page.print_on_charge.setChecked(False)
    page.save()

    assert settings.get(env.owner.user.business_id).print_on_charge is False
    page.deleteLater()


# -- scrollable checkout ----------------------------------------------------------------


def settle() -> None:
    """Let the posted layout requests and the deferred reveal run."""
    QTest.qWait(150)


def visible_lines(widget: PosWidget) -> int:
    viewport = widget.lines_scroll.viewport()
    count = 0
    for line in widget.ticket_lines:
        top = line.mapTo(viewport, QPoint(0, 0)).y()
        whole = line.height() >= line.sizeHint().height()
        if whole and top >= 0 and top + line.height() <= viewport.height():
            count += 1
    return count


def test_five_cart_lines_are_visible_at_1440_by_900(env):
    widget = env.pos()
    widget.resize(1440, 800)
    widget.show()
    env.add_lines(widget, 6)
    settle()

    assert len(widget.ticket_lines) == 6
    assert visible_lines(widget) >= 5


def test_the_charge_button_stays_pinned_outside_the_scroll(env):
    widget = env.pos()
    widget.resize(1440, 800)
    widget.show()
    env.add_lines(widget, 6)
    settle()

    assert not widget.lines_scroll.isAncestorOf(widget.charge_button)
    bottom = widget.charge_button.mapTo(widget, QPoint(0, widget.charge_button.height())).y()
    assert bottom <= widget.height()
    assert widget.charge_button.isVisible()


def test_every_checkout_control_is_reachable_by_scrolling(env):
    widget = env.pos()
    widget.resize(1440, 800)
    widget.show()
    env.add_lines(widget, 6)
    settle()
    scroll = widget.lines_scroll
    controls = (
        widget.method_control,
        widget.received_edit,
        widget.print_switch,
        widget.split_button,
        widget.reprint_button,
    )

    for control in controls:
        scroll.ensureWidgetVisible(control)
        settle()
        top = control.mapTo(scroll.viewport(), QPoint(0, 0)).y()
        bottom = top + control.height()
        assert 0 <= top and bottom <= scroll.viewport().height(), control
    assert scroll.verticalScrollBarPolicy() != Qt.ScrollBarPolicy.ScrollBarAlwaysOff


def test_inside_the_shell_the_charge_button_stays_on_screen_at_1440_by_900(env):
    auth = AuthService(env.database)
    shell = AppShell(
        env.products,
        SaleRepository(env.database),
        env.owner,
        BusinessSettingsRepository(env.database),
        auth,
        env.database,
    )
    shell.resize(1440, 900)
    shell.show()
    shell.show_page(1)
    env.add_lines(shell.pos_widget, 8)
    settle()
    pos = shell.pos_widget

    assert pos.height() <= shell.pages.height()
    bottom = pos.charge_button.mapTo(shell, QPoint(0, pos.charge_button.height())).y()
    assert bottom <= shell.height()
    assert visible_lines(pos) >= 5
    shell.close()
    shell.deleteLater()


def test_a_new_line_is_scrolled_into_view(env):
    widget = env.pos()
    widget.resize(1440, 760)
    widget.show()
    env.add_lines(widget, 12)
    settle()
    viewport = widget.lines_scroll.viewport()

    last = widget.ticket_lines[-1]
    top = last.mapTo(viewport, QPoint(0, 0)).y()
    assert 0 <= top and top + last.height() <= viewport.height()


# -- quick keys -------------------------------------------------------------------------


def test_there_are_four_quick_keys(env):
    widget = env.pos()

    assert QUICK_KEY_COUNT == 4
    assert len(widget.quick_buttons) == 4


def test_empty_quick_key_slots_are_hidden_not_dashed(qapp, tmp_path):
    env = Env(tmp_path, products=2)
    widget = env.pos()
    widget.show()

    visible = [button.isVisible() for button in widget.quick_buttons]
    assert visible == [True, True, False, False]
    assert all("—" not in button.property("productName") for button in widget.quick_buttons)
    assert not widget.quick_buttons[2].isEnabled()


def test_key_five_is_not_a_quick_key(env):
    widget = env.pos()

    assert 5 not in [
        index + 1 for index, button in enumerate(widget.quick_buttons) if button.isVisibleTo(widget)
    ]


# -- Clientes ---------------------------------------------------------------------------


def test_edit_and_deactivate_follow_the_selection(env):
    service = CustomerService(env.database)
    service.create(env.owner, CustomerData("cedula", "1712345678", "Ana Pérez"))
    page = CustomersWidget(service, env.owner)
    page.show()

    assert not page.edit_button.isEnabled()
    assert page.deactivate_button is not None and not page.deactivate_button.isEnabled()

    page.table.selectRow(0)
    assert page.edit_button.isEnabled()
    assert page.deactivate_button.isEnabled()

    page.table.clearSelection()
    assert not page.edit_button.isEnabled()
    assert not page.deactivate_button.isEnabled()

    page.table.selectRow(0)
    page.search_edit.setText("zzz")
    assert page.table.rowCount() == 0
    assert not page.edit_button.isEnabled()
    assert not page.deactivate_button.isEnabled()
    page.deleteLater()


def test_the_disabled_buttons_look_disabled(qapp):
    sheet = build_stylesheet(LIGHT_TOKENS)
    for variant in ("secondary", "danger"):
        assert f'QPushButton[variant="{variant}"]:disabled' in sheet
