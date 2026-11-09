import argparse
import os
import sys
import tempfile
from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from typing import Protocol

from PySide6.QtWidgets import QApplication

from suitelocal.application.auth import AuthService
from suitelocal.domain.auth import Session
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import ProductRepository, SaleRepository
from suitelocal.infrastructure.settings import BusinessSettingsRepository
from suitelocal.infrastructure.sri._xml import schema_errors
from suitelocal.infrastructure.sri.certificate_store import CertificateStore
from suitelocal.infrastructure.sri.invoice_xml import XSD_PATH
from suitelocal.ui.shell import AppShell
from suitelocal.ui.theme.fonts import load_inter_font
from suitelocal.ui.theme.manager import apply_saved_theme


def certificate_stores(data_directory: Path) -> Callable[[int], CertificateStore]:
    """The protected certificate store of each business, kept under `data_directory`."""

    def store_for(business_id: int) -> CertificateStore:
        return CertificateStore.for_business(data_directory, business_id)

    return store_for


def smoke_test() -> int:
    """Start everything the app needs except its windows, then report 0 (used on the built exe)."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    with tempfile.TemporaryDirectory(prefix="suitelocal-smoke-") as directory:
        database = Database(Path(directory) / "suitelocal.db")
        database.initialize()
        # Fails if the bundled XSD files are missing; the empty document itself is invalid.
        schema_errors(XSD_PATH, b"<factura/>")
        _application = QApplication.instance() or QApplication(sys.argv)
        import_module("suitelocal.ui.login")  # the real start-up imports it lazily
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SuiteLocal - sistema de gestión offline")
    parser.add_argument(
        "--database",
        type=Path,
        help="Ruta de la base SQLite que se desea abrir.",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Verifica el arranque (base temporal, esquema SRI, Qt) y sale sin mostrar ventanas.",
    )
    arguments = parser.parse_args(argv)
    if arguments.smoke_test:
        return smoke_test()
    data_directory = Path.home() / "AppData" / "Local" / "SuiteLocal"
    database_path = arguments.database or data_directory / "suitelocal.db"
    database = Database(database_path)
    database.initialize()
    # Beside the database, so a database opened with --database never sees another one's
    # certificates; by default this is the application data directory.
    certificates = certificate_stores(database_path.parent)

    application = QApplication(sys.argv)
    load_inter_font()
    apply_saved_theme(application)

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
            certificates=certificates,
        )
        window.logout_requested.connect(on_logout)
        return window

    return run_session_loop(login, open_shell, application.exec)


class SessionWindow(Protocol):
    def show(self) -> None: ...

    def deleteLater(self) -> None: ...


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
        # Button lambdas capture the window, so dropping it is not enough: release it
        # explicitly or every logout keeps a whole shell alive and repainting.
        window.deleteLater()
        if not logged_out:
            return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
