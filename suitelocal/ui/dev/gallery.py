from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from suitelocal.ui.components import (
    Card,
    DataTable,
    EmptyState,
    KpiCard,
    PrimaryButton,
    SearchField,
    SecondaryButton,
    Skeleton,
    StatusBadge,
    Toast,
)
from suitelocal.ui.theme.icons import icon
from suitelocal.ui.theme.qss import build_stylesheet


def build_gallery() -> QWidget:
    window = QWidget()
    window.setWindowTitle("SuiteLocal · Catálogo visual")
    window.resize(900, 600)
    layout = QVBoxLayout(window)
    title = QLabel("Catálogo de fundamentos")
    title.setObjectName("pageTitle")
    layout.addWidget(title)
    buttons = QHBoxLayout()
    for label, object_name in (
        ("Primario", "primaryAction"),
        ("Secundario", "secondaryAction"),
        ("Deshabilitado", "secondaryAction"),
    ):
        button = QPushButton(label)
        button.setObjectName(object_name)
        button.setIcon(icon("check"))
        if label == "Deshabilitado":
            button.setEnabled(False)
        buttons.addWidget(button)
    layout.addLayout(buttons)
    layout.addWidget(KpiCard("Ventas del día", "$0.00", "green", "Sin ventas registradas"))
    layout.addWidget(SearchField("Buscar productos..."))
    layout.addWidget(StatusBadge("Activo", "success"))
    layout.addWidget(Toast("Producto actualizado"))
    layout.addWidget(
        EmptyState(
            "Aún no hay datos",
            "Registra una operación para comenzar.",
            "Crear ahora",
        )
    )
    layout.addWidget(Skeleton())
    table = DataTable(2, ["Código", "Producto"])
    layout.addWidget(table)
    card = Card()
    card.content_layout.addWidget(QLabel("Tarjeta reutilizable con elevación"))
    layout.addWidget(card)
    layout.addWidget(PrimaryButton("Acción primaria"))
    layout.addWidget(SecondaryButton("Acción secundaria"))
    return window


def main() -> int:
    application = QApplication([])
    application.setStyleSheet(build_stylesheet())
    window = build_gallery()
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
