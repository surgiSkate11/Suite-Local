import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from suitelocal.application.auth import AuthService
from suitelocal.domain.auth import Session
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import ProductRepository, SaleRepository
from suitelocal.infrastructure.settings import BusinessSettingsRepository
from suitelocal.ui.components import InlineMessage, Toast, ToastHost, build_confirmation
from suitelocal.ui.pos import PosWidget
from suitelocal.ui.shell import AppShell


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def no_message_boxes(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("routine feedback must not open a QMessageBox")

    for name in ("warning", "information", "critical"):
        monkeypatch.setattr(QMessageBox, name, fail)


@pytest.fixture
def database(tmp_path):
    database = Database(tmp_path / "feedback.db")
    database.initialize()
    return database


def test_inline_message_shows_error_and_success_states(qapp):
    message = InlineMessage()

    message.show_error("El código ya existe.")
    assert (message.text(), message.property("state")) == ("El código ya existe.", "error")
    assert not message.isHidden()

    message.show_success("Producto guardado.")
    assert (message.text(), message.property("state")) == ("Producto guardado.", "success")

    message.clear_message()
    assert message.isHidden()


def test_toast_host_stacks_at_most_three_toasts(qapp):
    parent = QWidget()
    host = ToastHost(parent)

    for index in range(5):
        host.show_toast(f"Aviso {index}")

    texts = [toast.message for toast in host.findChildren(Toast) if not toast.isHidden()]
    assert texts == ["Aviso 2", "Aviso 3", "Aviso 4"]


def test_toasts_close_themselves_unless_persistent(qapp):
    parent = QWidget()
    host = ToastHost(parent, duration_ms=20)

    host.show_toast("Guardado", "success")
    host.show_toast("Stock insuficiente", "danger")
    danger = host.show_toast("No se pudo guardar", "danger", persistent=True)
    assert danger.property("state") == "danger"
    QTest.qWait(400)

    remaining = [toast.message for toast in host.findChildren(Toast) if not toast.isHidden()]
    assert remaining == ["No se pudo guardar"]


def test_confirmation_uses_spanish_labels_and_defaults_to_no(qapp):
    box = build_confirmation(None, "Desactivar producto", "¿Desactivar Arroz?")

    labels = [button.text() for button in box.buttons()]
    assert sorted(labels) == ["No", "Sí"]
    assert box.defaultButton().text() == "No"
    assert box.escapeButton().text() == "No"
    assert box.windowTitle() == "Desactivar producto"
    assert box.text() == "¿Desactivar Arroz?"


def test_pos_reports_add_errors_as_danger_notification(qapp, database, no_message_boxes):
    products = ProductRepository(database)
    products.add("A-1", "Arroz", 250, 0)
    pos = PosWidget(products, SaleRepository(database))
    notifications: list[tuple[str, str]] = []
    pos.notification.connect(lambda text, state: notifications.append((text, state)))

    pos.add_selected_product()

    assert len(notifications) == 1
    assert notifications[0][1] == "danger"
    assert pos.cart.lines == ()


def test_pos_confirms_sale_with_success_notification(qapp, database, no_message_boxes):
    products = ProductRepository(database)
    products.add("A-1", "Arroz", 250, 10)
    pos = PosWidget(products, SaleRepository(database))
    notifications: list[tuple[str, str]] = []
    pos.notification.connect(lambda text, state: notifications.append((text, state)))
    pos.add_selected_product()
    pos.received_edit.setText("5.00")

    pos.confirm_sale()

    assert len(notifications) == 1
    text, state = notifications[0]
    assert state == "success"
    assert text.startswith("Venta N.º 1 registrada")
    assert "Vuelto: $ 2,50" in text
    assert pos.cart.lines == ()
    assert pos.sales.today_summary() == (1, 250)
    assert products.find_active("A-1")[0].stock == 9


def test_shell_shows_page_notifications_as_toasts(qapp, database):
    auth = AuthService(database)
    owner = auth.setup_owner("Tienda Sol", "owner", "clave-segura", "clave-segura")
    shell = AppShell(
        ProductRepository(database),
        SaleRepository(database),
        Session(owner),
        BusinessSettingsRepository(database),
        auth,
        database,
    )

    shell.pos_widget.notification.emit("Venta N.º 9 registrada", "success")

    toasts = [toast.message for toast in shell.findChildren(Toast)]
    assert toasts == ["Venta N.º 9 registrada"]


def test_success_toast_does_not_cover_the_charge_buttons(qapp, database):
    auth = AuthService(database)
    owner = auth.setup_owner("Tienda Sol", "owner", "clave-segura", "clave-segura")
    ProductRepository(database).add("A-1", "Arroz", 250, 10)
    shell = AppShell(
        ProductRepository(database),
        SaleRepository(database),
        Session(owner),
        BusinessSettingsRepository(database),
        auth,
        database,
    )
    shell.resize(1440, 900)
    shell.show()
    shell.show_page(1)
    QTest.qWait(50)
    pos = shell.pos_widget
    pos.add_quick_product(0)
    pos.received_edit.setText("5.00")
    pos.confirm_sale()
    assert [toast.message for toast in shell.findChildren(Toast)]
    toast_area = shell.toasts.geometry()
    container = shell.centralWidget()

    for button in (pos.charge_button, pos.split_button):
        origin = button.mapTo(container, button.rect().topLeft())
        rect = button.rect().translated(origin)
        assert not toast_area.intersects(rect), button.text()
    shell.close()
