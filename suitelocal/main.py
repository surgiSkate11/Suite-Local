import argparse
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from suitelocal.application.auth import AuthService
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

    login = LoginDialog(auth)
    if login.exec() != LoginDialog.DialogCode.Accepted or login.session is None:
        return 0

    window = AppShell(
        ProductRepository(database),
        SaleRepository(database),
        login.session,
        BusinessSettingsRepository(database),
        auth,
        database,
    )
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
