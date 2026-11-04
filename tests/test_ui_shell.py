import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QPushButton

from suitelocal.application.auth import AuthService
from suitelocal.domain.auth import Session
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import ProductRepository, SaleRepository
from suitelocal.infrastructure.settings import BusinessSettingsRepository
from suitelocal.main import run_session_loop
from suitelocal.ui.shell import AppShell


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def shell(qapp, tmp_path):
    database = Database(tmp_path / "shell.db")
    database.initialize()
    auth = AuthService(database)
    owner = auth.setup_owner("Tienda Sol", "owner", "clave-segura", "clave-segura")
    window = AppShell(
        ProductRepository(database),
        SaleRepository(database),
        Session(owner),
        BusinessSettingsRepository(database),
        auth,
        database,
    )
    yield window
    window.deleteLater()


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

    def show(self) -> None:
        pass


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


def test_session_loop_stops_when_login_is_cancelled():
    opened: list[object] = []

    exit_code = run_session_loop(lambda: None, lambda *args: opened.append(args), lambda: 3)

    assert exit_code == 0
    assert opened == []
