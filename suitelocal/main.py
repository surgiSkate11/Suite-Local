import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from PySide6.QtWidgets import QApplication

from suitelocal.application.auth import AuthService
from suitelocal.domain.auth import Session
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import ProductRepository, SaleRepository
from suitelocal.infrastructure.settings import BusinessSettingsRepository
from suitelocal.ui.shell import AppShell
from suitelocal.ui.theme.fonts import load_inter_font
from suitelocal.ui.theme.qss import build_stylesheet


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SuiteLocal - sistema de gestión offline")
    parser.add_argument(
        "--database",
        type=Path,
        help="Ruta de la base SQLite que se desea abrir.",
    )
    arguments = parser.parse_args(argv)
    data_directory = Path.home() / "AppData" / "Local" / "SuiteLocal"
    database_path = arguments.database or data_directory / "suitelocal.db"
    database = Database(database_path)
    database.initialize()

    application = QApplication(sys.argv)
    load_inter_font()
    application.setStyleSheet(build_stylesheet())

    auth = AuthService(database)
    if not auth.has_users():
        from suitelocal.ui.login import SetupDialog

        setup = SetupDialog(auth)
        if setup.exec() != SetupDialog.DialogCode.Accepted:
            return 0

    from suitelocal.ui.login import LoginDialog

    def login() -> Session | None:
        dialog = LoginDialog(auth)
        if dialog.exec() != LoginDialog.DialogCode.Accepted:
            return None
        return dialog.session

    def open_shell(session: Session, on_logout: Callable[[], None]) -> AppShell:
        window = AppShell(
            ProductRepository(database),
            SaleRepository(database),
            session,
            BusinessSettingsRepository(database),
            auth,
            database,
        )
        window.logout_requested.connect(on_logout)
        return window

    return run_session_loop(login, open_shell, application.exec)


class SessionWindow(Protocol):
    def show(self) -> None: ...


def run_session_loop(
    login: Callable[[], Session | None],
    open_shell: Callable[[Session, Callable[[], None]], SessionWindow],
    run_event_loop: Callable[[], int],
) -> int:
    """Show login, run the shell, and return to login while the user logs out."""
    logged_out: list[bool] = []
    while True:
        session = login()
        if session is None:
            return 0
        logged_out.clear()
        window = open_shell(session, lambda: logged_out.append(True))
        window.show()
        exit_code = run_event_loop()
        if not logged_out:
            return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
