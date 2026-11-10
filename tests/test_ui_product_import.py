import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog

from suitelocal.application.auth import AuthService
from suitelocal.application.product_import import ImportPlan, ProductImportRow, RowError
from suitelocal.domain.auth import Session
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import ProductRepository
from suitelocal.ui.inventory import InventoryWidget
from suitelocal.ui.product_import_dialog import ProductImportDialog

HEADER = "código;nombre;precio;stock;categoría"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class FakeDialog:
    """Stands in for ProductImportDialog: records the plan and answers without exec()ing."""

    answer = QDialog.DialogCode.Accepted
    plans: list[ImportPlan] = []

    def __init__(self, plan: ImportPlan, parent=None) -> None:
        FakeDialog.plans.append(plan)

    def exec(self) -> QDialog.DialogCode:
        return FakeDialog.answer

    def deleteLater(self) -> None:
        pass


class Env:
    def __init__(self, tmp_path) -> None:
        self.tmp_path = tmp_path
        self.database = Database(tmp_path / "ui-import.db")
        self.database.initialize()
        auth = AuthService(self.database)
        self.owner = Session(
            auth.setup_owner("Tienda Sol", "owner", "clave-segura", "clave-segura")
        )
        self.cashier = Session(
            auth.create_cashier(self.owner, "cajero", "clave-cajero", "clave-cajero")
        )
        self.chosen: str | None = None
        self.notices: list[tuple[str, str]] = []
        FakeDialog.plans = []
        FakeDialog.answer = QDialog.DialogCode.Accepted

    def write(self, *lines: str, name: str = "productos.csv") -> str:
        path = self.tmp_path / name
        path.write_bytes(("\n".join([HEADER, *lines]) + "\n").encode("utf-8-sig"))
        return str(path)

    def build(self, session: Session | None = None) -> InventoryWidget:
        widget = InventoryWidget(
            ProductRepository(self.database),
            session or self.owner,
            import_file_chooser=lambda _parent: self.chosen,
            import_dialog_factory=FakeDialog,
        )
        widget.notification.connect(lambda text, state: self.notices.append((text, state)))
        return widget


@pytest.fixture
def env(qapp, tmp_path):
    return Env(tmp_path)


def codes(widget: InventoryWidget) -> list[str]:
    return [widget.table.item(row, 0).text() for row in range(widget.table.rowCount())]


def plan_with(creates=0, updates=0, categories=(), errors=()) -> ImportPlan:
    def row(index: int) -> ProductImportRow:
        return ProductImportRow(index + 2, f"P-{index}", "Producto", 100, 1, None, None, None)

    return ImportPlan(
        to_create=tuple(row(i) for i in range(creates)),
        to_update=tuple(row(i + creates) for i in range(updates)),
        categories_to_create=tuple(categories),
        errors=tuple(errors),
    )


# -- Inventario button --------------------------------------------------------------------


def test_the_import_button_is_there_for_the_owner_and_hidden_for_the_cashier(env):
    owner_view = env.build()
    cashier_view = env.build(env.cashier)

    assert owner_view.import_button.text() == "Importar productos"
    assert not owner_view.import_button.isHidden()
    assert cashier_view.import_button.isHidden()


def test_the_default_chooser_asks_for_csv_files_through_qfiledialog(env, monkeypatch):
    from suitelocal.ui.inventory import choose_import_file

    calls: list[tuple[object, ...]] = []

    def fake(parent, title, directory, name_filter):
        calls.append((title, directory, name_filter))
        return "C:/x/productos.csv", name_filter

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(fake))

    assert choose_import_file(None) == "C:/x/productos.csv"
    assert calls == [("Importar productos", "", "CSV (*.csv)")]

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a: ("", "")))
    assert choose_import_file(None) is None


def test_the_owner_flow_applies_the_plan_refreshes_the_table_and_notifies(env):
    widget = env.build()
    assert codes(widget) == []
    env.chosen = env.write("A-1;Arroz;2,50;10;Granos", "B-2;Sal;1,00;5;")

    widget.import_button.click()

    assert len(FakeDialog.plans) == 1
    assert len(FakeDialog.plans[0].to_create) == 2
    assert sorted(codes(widget)) == ["A-1", "B-2"]
    assert [c.name for c in widget.all_categories] == ["Granos"]
    assert env.notices == [("Importación lista: 2 productos creados y 0 actualizados.", "success")]


def test_declining_the_preview_changes_nothing(env):
    widget = env.build()
    env.chosen = env.write("A-1;Arroz;2,50;10")
    FakeDialog.answer = QDialog.DialogCode.Rejected

    widget.import_button.click()

    assert codes(widget) == []
    assert env.notices == []


def test_cancelling_the_file_chooser_does_nothing(env):
    widget = env.build()
    env.chosen = None

    widget.import_button.click()

    assert FakeDialog.plans == []
    assert env.notices == []


def test_an_unreadable_file_is_a_danger_notice_and_no_dialog(env):
    widget = env.build()
    env.chosen = str(env.tmp_path / "no-existe.csv")

    widget.import_button.click()

    assert FakeDialog.plans == []
    assert len(env.notices) == 1
    assert env.notices[0][1] == "danger"
    assert env.notices[0][0].startswith("No se pudo leer el archivo")


def test_a_failure_while_applying_is_a_danger_notice_and_leaves_the_table_alone(env):
    widget = env.build()
    env.chosen = env.write("A-1;Arroz;2,50;10")

    def stale_dialog(plan, parent=None):
        # Someone else creates the code between the preview and the confirmation.
        ProductRepository(env.database).add("A-1", "Otro", 100, 1)
        return FakeDialog(plan, parent)

    widget._import_dialog_factory = stale_dialog

    widget.import_button.click()

    assert env.notices == [
        ("No se pudo importar: Línea 2: ya existe un producto con el código A-1.", "danger")
    ]
    assert codes(widget) == []  # the table was not refreshed with half the import


def test_a_file_with_errors_still_opens_the_dialog_but_is_never_applied(env):
    widget = env.build()
    env.chosen = env.write("A-1;Arroz;mal;10")

    widget.import_button.click()

    assert FakeDialog.plans[0].has_errors
    assert codes(widget) == []
    assert [state for _, state in env.notices] == ["danger"]


# -- ProductImportDialog ------------------------------------------------------------------


def test_the_dialog_shows_the_counts_and_the_new_categories(qapp):
    dialog = ProductImportDialog(plan_with(creates=3, updates=2, categories=("Bebidas", "Snacks")))

    assert dialog.summary.text() == "Se van a crear 3 productos y actualizar 2."
    assert dialog.categories_label.text() == "Se van a crear 2 categorías nuevas: Bebidas, Snacks."
    assert dialog.confirm_button.isEnabled()
    assert dialog.error_table.rowCount() == 0
    assert dialog.error_table.isHidden()


def test_the_dialog_uses_the_singular_and_hides_the_categories_line_when_there_are_none(qapp):
    dialog = ProductImportDialog(plan_with(creates=1, updates=1, categories=("Bebidas",)))

    assert dialog.summary.text() == "Se van a crear 1 producto y actualizar 1."
    assert dialog.categories_label.text() == "Se va a crear 1 categoría nueva: Bebidas."
    assert ProductImportDialog(plan_with(creates=2)).categories_label.isHidden()


def test_the_dialog_lists_row_errors_and_disables_confirm(qapp):
    errors = (
        RowError(3, "El precio «abc» no es válido."),
        RowError(7, "El IVA debe ser 15, 5 o 0."),
    )
    dialog = ProductImportDialog(plan_with(creates=1, errors=errors))

    assert not dialog.confirm_button.isEnabled()
    assert not dialog.error_table.isHidden()
    assert [dialog.error_table.horizontalHeaderItem(i).text() for i in range(2)] == [
        "Línea",
        "Mensaje",
    ]
    assert [
        (dialog.error_table.item(row, 0).text(), dialog.error_table.item(row, 1).text())
        for row in range(dialog.error_table.rowCount())
    ] == [("3", "El precio «abc» no es válido."), ("7", "El IVA debe ser 15, 5 o 0.")]
    assert "2 errores" in dialog.error_label.text()


def test_the_dialog_with_nothing_to_import_cannot_be_confirmed(qapp):
    assert not ProductImportDialog(plan_with()).confirm_button.isEnabled()


def test_confirm_accepts_and_cancel_rejects_without_exec(qapp):
    confirmed = ProductImportDialog(plan_with(creates=1))
    confirmed.confirm_button.click()
    cancelled = ProductImportDialog(plan_with(creates=1))
    cancelled.cancel_button.click()

    assert confirmed.result() == QDialog.DialogCode.Accepted
    assert cancelled.result() == QDialog.DialogCode.Rejected
