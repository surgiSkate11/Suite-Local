"""Preview of a product import: what will be created or updated, and what is wrong."""

from collections.abc import Callable

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from suitelocal.application.product_import import ImportPlan
from suitelocal.ui.components import DataTable, set_variant

__all__ = ["ProductImportDialog", "ProductImportDialogFactory"]

ProductImportDialogFactory = Callable[..., "ProductImportDialog"]

ERROR_HEADERS = ["Línea", "Mensaje"]


class ProductImportDialog(QDialog):
    """Shows the plan and lets the owner confirm it; it only accepts a plan without errors."""

    def __init__(self, plan: ImportPlan, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.plan = plan
        self.setWindowTitle("Importar productos")
        self.setModal(True)
        self.setMinimumWidth(520)

        creates = len(plan.to_create)
        self.summary = QLabel(
            f"Se van a crear {creates} {'producto' if creates == 1 else 'productos'} "
            f"y actualizar {len(plan.to_update)}."
        )
        self.summary.setWordWrap(True)
        self.categories_label = QLabel(self._categories_text())
        self.categories_label.setWordWrap(True)
        self.categories_label.setVisible(bool(plan.categories_to_create))

        errors = len(plan.errors)
        self.error_label = QLabel(
            f"Hay {errors} {'error' if errors == 1 else 'errores'} en el archivo. "
            "Corregilo y volvé a importar."
            if errors
            else "El archivo no tiene productos para importar."
        )
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(errors > 0 or not (creates or plan.to_update))
        self.error_table = DataTable(len(ERROR_HEADERS), ERROR_HEADERS)
        self.error_table.setMinimumHeight(180)
        for error in plan.errors:
            row = self.error_table.rowCount()
            self.error_table.insertRow(row)
            self.error_table.setItem(row, 0, QTableWidgetItem(str(error.line)))
            self.error_table.setItem(row, 1, QTableWidgetItem(error.message))
        self.error_table.setVisible(errors > 0)

        self.cancel_button = QPushButton("Cancelar")
        set_variant(self.cancel_button, "secondary")
        self.cancel_button.setAutoDefault(False)
        self.cancel_button.clicked.connect(self.reject)
        self.confirm_button = QPushButton("Importar")
        set_variant(self.confirm_button, "primary")
        self.confirm_button.setAutoDefault(False)
        self.confirm_button.setEnabled(errors == 0 and bool(creates or plan.to_update))
        self.confirm_button.clicked.connect(self.accept)

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.confirm_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.summary)
        layout.addWidget(self.categories_label)
        layout.addWidget(self.error_label)
        layout.addWidget(self.error_table)
        layout.addLayout(buttons)

    def _categories_text(self) -> str:
        names = self.plan.categories_to_create
        if len(names) == 1:
            return f"Se va a crear 1 categoría nueva: {names[0]}."
        return f"Se van a crear {len(names)} categorías nuevas: {', '.join(names)}."
