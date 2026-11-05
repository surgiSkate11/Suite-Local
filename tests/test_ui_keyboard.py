import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QPushButton

from suitelocal.application.auth import AuthService
from suitelocal.domain.auth import Session
from suitelocal.domain.models import Payment
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import ProductRepository, SaleRepository
from suitelocal.infrastructure.settings import BusinessSettingsRepository
from suitelocal.ui.components import Drawer
from suitelocal.ui.inventory import InventoryWidget
from suitelocal.ui.pos import PosWidget
from suitelocal.ui.shell import AppShell


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def database(tmp_path):
    database = Database(tmp_path / "keyboard.db")
    database.initialize()
    return database


@pytest.fixture
def owner(database):
    auth = AuthService(database)
    user = auth.setup_owner("Tienda Sol", "owner", "clave-segura", "clave-segura")
    return auth, Session(user)


def show_active(widget):
    widget.resize(1300, 800)
    widget.show()
    widget.activateWindow()
    QTest.qWaitForWindowActive(widget)


def test_drawer_title_close_button_and_escape(qapp):
    drawer = Drawer("Nuevo producto")
    close = next(b for b in drawer.findChildren(QPushButton) if b.objectName() == "drawerClose")

    drawer.set_title("Editar producto")

    assert drawer.heading.text() == "Editar producto"
    assert close.accessibleName() == "Cerrar panel"
    assert close.text() == ""
    show_active(drawer)
    QTest.keyClick(drawer, Qt.Key.Key_Escape)
    assert drawer.isHidden()


def test_inventory_drawer_opens_with_focus_and_saves_with_enter(qapp, database, owner):
    _, session = owner
    inventory = InventoryWidget(ProductRepository(database), session)
    notifications: list[tuple[str, str]] = []
    inventory.notification.connect(lambda text, state: notifications.append((text, state)))
    show_active(inventory)

    inventory.open_new_product()
    assert inventory.drawer.heading.text() == "Nuevo producto"
    assert QApplication.focusWidget() is inventory.code

    QTest.keyClicks(inventory.code, "A-1")
    QTest.keyClicks(inventory.name, "Arroz")
    QTest.keyClicks(inventory.price, "2.50")
    QTest.keyClicks(inventory.stock, "10")
    QTest.keyClick(inventory.stock, Qt.Key.Key_Return)

    assert notifications == [("Arroz está disponible en el inventario.", "success")]
    assert inventory.drawer.isHidden()
    assert inventory.code.text() == ""


def test_inventory_selection_opens_edit_drawer(qapp, database, owner):
    _, session = owner
    products = ProductRepository(database)
    products.add("A-1", "Arroz", 250, 10)
    inventory = InventoryWidget(products, session)
    show_active(inventory)

    inventory.table.selectRow(0)

    assert inventory.drawer.heading.text() == "Editar producto"
    assert not inventory.drawer.isHidden()
    assert QApplication.focusWidget() is inventory.name


def test_inventory_enter_with_invalid_price_keeps_drawer_open(qapp, database, owner):
    _, session = owner
    products = ProductRepository(database)
    inventory = InventoryWidget(products, session)
    show_active(inventory)
    inventory.open_new_product()

    QTest.keyClicks(inventory.code, "A-1")
    QTest.keyClicks(inventory.name, "Arroz")
    QTest.keyClicks(inventory.price, "abc")
    QTest.keyClick(inventory.price, Qt.Key.Key_Return)

    assert not inventory.drawer.isHidden()
    assert inventory.message.property("state") == "error"
    assert products.find_active("") == []


def test_pos_search_arrows_move_the_product_selection(qapp, database):
    products = ProductRepository(database)
    products.add("A-1", "Arroz", 250, 10)
    products.add("B-2", "Frijol", 300, 5)
    pos = PosWidget(products, SaleRepository(database))
    show_active(pos)
    pos.search_input.setFocus()

    QTest.keyClick(pos.search_input, Qt.Key.Key_Down)
    assert pos.product_list.currentRow() == 1
    QTest.keyClick(pos.search_input, Qt.Key.Key_Down)
    assert pos.product_list.currentRow() == 1
    QTest.keyClick(pos.search_input, Qt.Key.Key_Up)
    assert pos.product_list.currentRow() == 0
    assert pos.search_input.accessibleName() == "Buscar producto"


class FakeDialog:
    """Stands in for PaymentDialog so no test blocks on a real modal ``exec``."""

    def __init__(self, payments: tuple[Payment, ...]) -> None:
        self.payments = payments
        self.print_ticket = False

    def exec(self) -> QDialog.DialogCode:
        return QDialog.DialogCode.Accepted

    def deleteLater(self) -> None:
        pass


@pytest.fixture
def pos_with_stock(qapp, database):
    products = ProductRepository(database)
    products.add("A-1", "Arroz", 250, 10)
    products.add("B-2", "Frijol", 300, 5)
    pos = PosWidget(products, SaleRepository(database), ("cash", "transfer"))
    show_active(pos)
    yield pos
    pos.deleteLater()


def test_pos_f4_charges_with_the_inline_payment(qapp, pos_with_stock):
    pos = pos_with_stock
    pos.add_quick_product(0)
    pos.received_edit.setText("5.00")
    pos.search_input.setFocus()

    QTest.keyClick(pos.search_input, Qt.Key.Key_F4)

    assert pos.sales.today_summary() == (1, 250)
    assert pos.cart.lines == ()


def test_pos_ctrl_return_charges_like_the_button(qapp, pos_with_stock):
    pos = pos_with_stock
    pos.add_quick_product(0)
    pos.received_edit.setText("5.00")

    QTest.keySequence(pos, "Ctrl+Return")

    assert pos.sales.today_summary() == (1, 250)


def test_pos_f4_with_insufficient_cash_only_shows_the_inline_error(qapp, pos_with_stock):
    pos = pos_with_stock
    pos.add_quick_product(0)
    pos.received_edit.setText("1.00")

    QTest.keyClick(pos.search_input, Qt.Key.Key_F4)

    assert pos.sales.today_summary() == (0, 0)
    assert pos.checkout_message.text() == "El efectivo recibido no cubre el total."


def test_pos_f9_opens_the_split_dialog_through_the_factory(qapp, pos_with_stock):
    pos = pos_with_stock
    opened: list[int] = []

    def factory(**kwargs):
        opened.append(kwargs["total_cents"])
        return FakeDialog((Payment("cash", 150), Payment("transfer", 100, "TR-7")))

    pos.payment_dialog_factory = factory
    pos.add_quick_product(0)

    QTest.keyClick(pos.search_input, Qt.Key.Key_F9)

    assert opened == [250]
    assert pos.sales.today_summary() == (1, 250)


def test_pos_delete_removes_the_highlighted_line(qapp, pos_with_stock):
    pos = pos_with_stock
    pos.add_quick_product(0)
    pos.add_quick_product(1)

    QTest.keyClick(pos.search_input, Qt.Key.Key_Delete)

    assert [line.product.code for line in pos.cart.lines] == ["A-1"]


def test_pos_f2_returns_the_focus_to_the_scanner(qapp, pos_with_stock):
    pos = pos_with_stock
    pos.received_edit.setFocus()
    assert QApplication.focusWidget() is pos.received_edit

    QTest.keyClick(pos.received_edit, Qt.Key.Key_F2)

    assert QApplication.focusWidget() is pos.search_input


def test_pos_typed_quantity_prefix_multiplies_with_enter(qapp, pos_with_stock):
    pos = pos_with_stock
    pos.search_input.setFocus()

    QTest.keyClicks(pos.search_input, "3*B-2")
    assert pos.quantity_hint.text() == "Cantidad ×3 · 3* multiplica"
    QTest.keyClick(pos.search_input, Qt.Key.Key_Return)

    assert [(line.product.code, line.quantity) for line in pos.cart.lines] == [("B-2", 3)]
    assert pos.quantity_hint.text() == "Cantidad ×1 · 3* multiplica"


def test_pos_number_keys_add_quick_products_when_focus_is_outside_text_fields(qapp, pos_with_stock):
    pos = pos_with_stock
    pos.quick_buttons[0].setFocus()

    QTest.keyClick(pos.quick_buttons[0], Qt.Key.Key_2)

    assert [line.product.code for line in pos.cart.lines] == ["B-2"]


@pytest.fixture
def shell(database, owner):
    auth, session = owner
    window = AppShell(
        ProductRepository(database),
        SaleRepository(database),
        session,
        BusinessSettingsRepository(database),
        auth,
        database,
    )
    yield window
    window.deleteLater()


def test_ctrl_k_focuses_caja_search_on_caja_and_global_search_elsewhere(qapp, shell):
    show_active(shell)

    shell.show_page(1)
    shell.global_search.setFocus()
    QTest.keySequence(shell, "Ctrl+K")
    assert QApplication.focusWidget() is shell.pos_widget.search_input

    shell.show_page(0)
    QTest.keySequence(shell, "Ctrl+K")
    assert QApplication.focusWidget() is shell.global_search
    assert shell.global_search.accessibleName() == "Búsqueda global"


def test_ctrl_number_switches_pages(qapp, shell):
    show_active(shell)

    QTest.keySequence(shell, "Ctrl+3")
    assert shell.pages.currentIndex() == 2
    QTest.keySequence(shell, "Ctrl+1")
    assert shell.pages.currentIndex() == 0


def test_escape_in_global_search_clears_it(qapp, shell):
    show_active(shell)
    shell.global_search.setFocus()
    QTest.keyClicks(shell.global_search, "arroz")

    QTest.keyClick(shell.global_search, Qt.Key.Key_Escape)

    assert shell.global_search.text() == ""
