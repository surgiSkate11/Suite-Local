import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import re

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton

from suitelocal.application.auth import AuthService
from suitelocal.application.cash_register import CashRegisterService
from suitelocal.application.tables import TablesService
from suitelocal.domain.auth import Session
from suitelocal.domain.models import Payment, Sale, SaleItem
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import ProductRepository, SaleRepository
from suitelocal.infrastructure.settings import BusinessSettingsRepository
from suitelocal.main import run_session_loop
from suitelocal.ui.shell import AppShell


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def env(tmp_path):
    database = Database(tmp_path / "shell.db")
    database.initialize()
    auth = AuthService(database)
    owner = auth.setup_owner("Tienda Sol", "owner", "clave-segura", "clave-segura")
    return database, auth, owner


def build_shell(database, auth, user):
    return AppShell(
        ProductRepository(database),
        SaleRepository(database),
        Session(user),
        BusinessSettingsRepository(database),
        auth,
        database,
    )


@pytest.fixture
def shell(qapp, env):
    database, auth, owner = env
    window = build_shell(database, auth, owner)
    yield window
    destroy(window)


def destroy(window: AppShell) -> None:
    """Delete now so finished windows are not re-polished by later theme changes."""
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


def nav_texts(shell) -> list[str]:
    return [shell.navigation.item(row).text() for row in range(shell.navigation.count())]


def enable_tables(env) -> None:
    database, _, owner = env
    BusinessSettingsRepository(database).update_profile(
        owner.business_id, enabled_modules=["mesas"]
    )


def cashier_of(env):
    database, auth, owner = env
    return auth.create_cashier(Session(owner), "cajero", "clave-segura-2", "clave-segura-2")


def open_register(env, opening_cents=15_000):
    database, _, owner = env
    return CashRegisterService(database).open(Session(owner), opening_cents)


def register_cash_sale(env):
    """2 x 250 paid with 1000 cash: 500 of change, so the drawer gains 500."""
    database = env[0]
    product = ProductRepository(database).add("A-1", "Arroz", 250, 100)
    SaleRepository(database).register(Sale((SaleItem(product.id, product.name, 2, 250),), 1000))


def status_cash_text(shell) -> str:
    return " ".join(label.text() for label in shell.status_cash.findChildren(QLabel))


def sidebar_texts(shell) -> list[str]:
    widgets = [*shell.sidebar.findChildren(QLabel), *shell.sidebar.findChildren(QPushButton)]
    return [w.text() for w in widgets if w.isVisibleTo(shell.sidebar) and w.text()]


def test_logout_button_requests_logout_and_closes_window(shell):
    requested: list[bool] = []
    shell.logout_requested.connect(lambda: requested.append(True))
    shell.show()

    logout = next(
        button for button in shell.findChildren(QPushButton) if button.text() == "Cerrar sesión"
    )
    logout.click()

    assert requested == [True]
    assert not shell.isVisible()


class FakeShell(QObject):
    logout_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.released = False

    def show(self) -> None:
        pass

    def deleteLater(self) -> None:
        self.released = True


def test_session_loop_returns_to_login_after_logout():
    logins: list[str] = []
    shells: list[FakeShell] = []
    sessions = iter(["first", "second"])

    def login():
        logins.append("login")
        return next(sessions, None)

    def open_shell(session, on_logout):
        shell = FakeShell()
        shell.logout_requested.connect(on_logout)
        shells.append(shell)
        return shell

    def run_event_loop():
        if len(shells) == 1:
            shells[0].logout_requested.emit()
        return 7

    exit_code = run_session_loop(login, open_shell, run_event_loop)

    assert logins == ["login", "login"]
    assert len(shells) == 2
    assert exit_code == 7


def test_session_loop_releases_the_window_of_a_logged_out_session():
    # Button lambdas capture the shell, so a dropped window is never garbage collected:
    # without deleteLater() every logout would keep a whole shell alive and repainting.
    shells: list[FakeShell] = []
    sessions = iter(["first", "second"])

    def open_shell(session, on_logout):
        shell = FakeShell()
        shell.logout_requested.connect(on_logout)
        shells.append(shell)
        return shell

    def run_event_loop():
        if len(shells) == 1:
            shells[0].logout_requested.emit()
        return 0

    run_session_loop(lambda: next(sessions, None), open_shell, run_event_loop)

    assert [shell.released for shell in shells] == [True, True]


def test_session_loop_stops_when_login_is_cancelled():
    opened: list[object] = []

    exit_code = run_session_loop(lambda: None, lambda *args: opened.append(args), lambda: 3)

    assert exit_code == 0
    assert opened == []


def test_rail_groups_and_entries_for_the_owner(shell):
    assert nav_texts(shell) == [
        "Operación",
        "Panel principal",
        "Caja",
        "Inventario",
        "Negocio",
        "Equipo",
        "Ajustes",
    ]
    assert shell.brand_name.text() == "SuiteLocal"
    assert shell.brand_business.text() == "Tienda Sol"


def test_rail_for_a_cashier_has_no_business_group(qapp, env):
    database, auth, owner = env
    cashier = auth.create_cashier(Session(owner), "cajero", "clave-segura-2", "clave-segura-2")
    window = build_shell(database, auth, cashier)

    assert nav_texts(window) == ["Operación", "Panel principal", "Caja"]
    assert window.user_role.text() == "Cajero"
    destroy(window)


def test_ctrl_number_opens_the_page_in_rail_order(qapp, shell):
    shell.show()
    shell.activateWindow()
    QTest.qWaitForWindowActive(shell)
    expected = {"Ctrl+1": 0, "Ctrl+2": 1, "Ctrl+3": 2, "Ctrl+4": 3, "Ctrl+5": 4}

    for shortcut, index in expected.items():
        QTest.keySequence(shell, shortcut)
        assert shell.pages.currentIndex() == index
        current = shell.navigation.currentItem()
        assert current is not None
        assert current.data(Qt.ItemDataRole.UserRole) == index
    assert nav_texts(shell)[shell.navigation.currentRow()] == "Ajustes"


def test_register_card_shows_closed_register_and_user(shell):
    assert shell.register_status.text() == "Caja cerrada"
    assert shell.register_base_row.isHidden()
    assert shell.register_expected_row.isHidden()
    assert shell.user_avatar.text() == "OW"
    assert shell.user_name.text() == "owner"
    assert shell.user_role.text() == "Dueño"


def test_register_card_shows_exact_base_and_expected_cash(qapp, env):
    open_register(env, 15_000)
    register_cash_sale(env)
    database, auth, owner = env

    window = build_shell(database, auth, owner)

    assert re.fullmatch(r"Caja abierta · \d{1,2}:\d{2} [ap]\. m\.", window.register_status.text())
    assert window.register_base.text() == "$ 150,00"
    assert window.register_expected.text() == "$ 155,00"
    assert not window.register_base_row.isHidden()
    assert not window.register_expected_row.isHidden()
    destroy(window)


def test_status_bar_without_open_register(shell):
    assert shell.status_offline.text() == "Funcionando sin internet"
    assert shell.status_printer.text() == "Impresora: sin configurar"
    assert shell.status_cash.isHidden()
    texts = [label.text().lower() for label in shell.status_bar.findChildren(QLabel)]
    assert not any("respaldo" in text for text in texts)


def test_status_bar_shows_cash_and_refreshes_after_each_sale(qapp, env):
    open_register(env, 15_000)
    database, auth, owner = env
    window = build_shell(database, auth, owner)
    assert status_cash_text(window) == "Base de caja $ 150,00 · Efectivo esperado $ 150,00"
    assert window.register_expected.text() == "$ 150,00"

    register_cash_sale(env)
    window.pos_widget.sale_registered.emit()

    assert status_cash_text(window) == "Base de caja $ 150,00 · Efectivo esperado $ 155,00"
    assert window.register_expected.text() == "$ 155,00"
    destroy(window)


def test_register_card_follows_opening_and_closing_when_refreshed(qapp, env, shell):
    assert shell.register_status.text() == "Caja cerrada"
    open_register(env, 2_000)

    shell.refresh_register()

    assert shell.register_status.text().startswith("Caja abierta · ")
    assert shell.register_base.text() == "$ 20,00"
    CashRegisterService(env[0]).close(Session(env[2]), 2_000)
    shell.refresh_register()
    assert shell.register_status.text() == "Caja cerrada"
    assert shell.status_cash.isHidden()


def test_collapsed_rail_shows_only_mark_and_avatar_without_clipping(qapp, env):
    open_register(env)
    database, auth, owner = env
    window = build_shell(database, auth, owner)
    window.resize(1100, 760)
    window.show()
    QTest.qWait(50)

    assert window.sidebar.maximumWidth() == 72
    assert sorted(sidebar_texts(window)) == ["OW", "S"]
    entries = [window.navigation.item(row) for row in range(window.navigation.count())]
    assert [item.text() for item in entries if not item.isHidden()] == [""] * 5
    assert all(item.toolTip() for item in entries if not item.isHidden())
    assert window.logout_button.accessibleName() == "Cerrar sesión"
    for child in [window.brand_mark, window.user_avatar, window.logout_button, window.navigation]:
        corner = child.mapTo(window.sidebar, child.rect().bottomRight())
        assert corner.x() <= window.sidebar.width()
    destroy(window)


def test_expanding_the_rail_restores_text(qapp, env):
    database, auth, owner = env
    window = build_shell(database, auth, owner)
    window.resize(1100, 760)
    window.show()
    QTest.qWait(50)

    window.resize(1300, 760)
    QTest.qWait(320)

    texts = sidebar_texts(window)
    assert "SuiteLocal" in texts
    assert "Cerrar sesión" in texts
    assert "Caja cerrada" in texts
    assert nav_texts(window)[1] == "Panel principal"
    destroy(window)


def test_rail_shows_mesas_after_caja_when_the_module_is_on_for_the_owner(qapp, env):
    enable_tables(env)
    window = build_shell(*env)

    assert nav_texts(window) == [
        "Operación",
        "Panel principal",
        "Caja",
        "Mesas",
        "Inventario",
        "Negocio",
        "Equipo",
        "Ajustes",
    ]
    destroy(window)


def test_rail_shows_mesas_to_a_cashier_when_the_module_is_on(qapp, env):
    enable_tables(env)
    window = build_shell(env[0], env[1], cashier_of(env))

    assert nav_texts(window) == ["Operación", "Panel principal", "Caja", "Mesas"]
    destroy(window)


def test_rail_hides_mesas_when_the_module_is_off_for_owner_and_cashier(qapp, env, shell):
    assert "Mesas" not in nav_texts(shell)
    assert shell.tables_widget is None
    window = build_shell(env[0], env[1], cashier_of(env))

    assert "Mesas" not in nav_texts(window)
    destroy(window)


def press_each_shortcut_and_collect(window, count: int) -> list[str]:
    window.show()
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    opened: list[str] = []
    for number in range(1, count + 1):
        QTest.keySequence(window, f"Ctrl+{number}")
        current = window.navigation.currentItem()
        assert current is not None
        assert window.pages.currentIndex() == current.data(Qt.ItemDataRole.UserRole)
        opened.append(current.text())
    return opened


def test_ctrl_number_follows_the_visible_order_with_mesas_for_the_owner(qapp, env):
    enable_tables(env)
    window = build_shell(*env)

    assert press_each_shortcut_and_collect(window, 6) == [
        "Panel principal",
        "Caja",
        "Mesas",
        "Inventario",
        "Equipo",
        "Ajustes",
    ]
    destroy(window)


def test_ctrl_number_follows_the_visible_order_with_mesas_for_a_cashier(qapp, env):
    enable_tables(env)
    window = build_shell(env[0], env[1], cashier_of(env))

    assert press_each_shortcut_and_collect(window, 3) == ["Panel principal", "Caja", "Mesas"]
    destroy(window)


class ChargeDialog:
    """Stands in for the modal payment dialog so the test never blocks on ``exec``."""

    def __init__(self, payments: tuple[Payment, ...]) -> None:
        self.payments = payments

    def exec(self):
        return QDialog.DialogCode.Accepted

    def deleteLater(self) -> None:
        pass


def test_a_table_charge_refreshes_the_status_bar_and_toasts(qapp, env):
    enable_tables(env)
    open_register(env, 15_000)
    database, auth, owner = env
    window = build_shell(database, auth, owner)
    assert status_cash_text(window) == "Base de caja $ 150,00 · Efectivo esperado $ 150,00"
    session = Session(owner)
    service = TablesService(database)
    product = ProductRepository(database).add("A-1", "Arroz", 250, 100)
    table = service.create_table(session, "Mesa 1")
    order = service.open_order(session, table.id)
    service.add_product(session, order.id, product.id, 2)
    assert window.tables_widget is not None
    window.tables_widget.refresh()
    window.tables_widget.payment_dialog_factory = lambda **_: ChargeDialog((Payment("cash", 500),))
    toasts: list[tuple[str, str]] = []
    window.toasts.show_toast = lambda message, state: toasts.append((message, state))  # type: ignore[method-assign]
    window.tables_widget.select_table(table.id)

    window.tables_widget.charge_order()

    assert status_cash_text(window) == "Base de caja $ 150,00 · Efectivo esperado $ 155,00"
    assert window.register_expected.text() == "$ 155,00"
    assert [state for _, state in toasts] == ["success"]
    assert "Mesa 1 cobrada" in toasts[0][0]
    destroy(window)


def test_a_table_charge_refreshes_the_counter_pos_stock(qapp, env):
    enable_tables(env)
    database, auth, owner = env
    product = ProductRepository(database).add("A-1", "Arroz", 250, 10)
    window = build_shell(database, auth, owner)
    assert window.pos_widget.product_list.card_at(0).meta_label.text() == "10 en stock"
    session = Session(owner)
    service = TablesService(database)
    table = service.create_table(session, "Mesa 1")
    order = service.open_order(session, table.id)
    service.add_product(session, order.id, product.id, 2)
    assert window.tables_widget is not None
    window.tables_widget.refresh()
    window.tables_widget.payment_dialog_factory = lambda **_: ChargeDialog((Payment("cash", 500),))
    window.toasts.show_toast = lambda message, state: None  # type: ignore[method-assign]
    window.tables_widget.select_table(table.id)

    window.tables_widget.charge_order()

    assert window.pos_widget.product_list.card_at(0).meta_label.text() == "8 en stock"
    destroy(window)
