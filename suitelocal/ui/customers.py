"""Clientes page: find, register and edit customers, see their purchases, export offers."""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from suitelocal.application.customers import CustomerService
from suitelocal.domain.auth import Session
from suitelocal.domain.customers import Customer
from suitelocal.ui.components import DataTable, EmptyState, SearchField, confirm_action, set_variant
from suitelocal.ui.customer_dialog import CustomerDialog, CustomerDialogFactory
from suitelocal.ui.payment_dialog import format_money
from suitelocal.ui.theme.icons import ICONS

ICONS.setdefault("customers", ICONS["users"])

HEADERS = ["Nombres", "Identificación", "Teléfono", "Correo", "Ofertas"]
PURCHASE_HEADERS = ["Fecha", "Venta", "Total"]
OFFERS_FILE_NAME = "clientes-con-ofertas.csv"
PICK_ONE = "Elegí un cliente para ver sus compras."

Confirmer = Callable[[QWidget | None, str, str], bool]
SavePathPicker = Callable[[QWidget | None, str], str | None]


def pick_save_path(parent: QWidget | None, suggested_name: str) -> str | None:
    """Ask where to save the CSV; None when the owner cancels."""
    path, _ = QFileDialog.getSaveFileName(
        parent, "Exportar clientes", suggested_name, "CSV (*.csv)"
    )
    return path or None


class CustomersWidget(QWidget):
    """Customers of the business. Deactivating and exporting are the owner's, so the cashier's
    page simply does not have those buttons."""

    notification = Signal(str, str)

    def __init__(
        self,
        service: CustomerService,
        session: Session,
        dialog_factory: CustomerDialogFactory = CustomerDialog,
        confirmer: Confirmer = confirm_action,
        save_path_picker: SavePathPicker = pick_save_path,
        currency_symbol: str = "$",
        decimal_separator: str = ",",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.session = session
        self._dialog_factory = dialog_factory
        self._confirmer = confirmer
        self._save_path_picker = save_path_picker
        self.currency_symbol = currency_symbol
        self.decimal_separator = decimal_separator
        self._customers: list[Customer] = []
        self.deactivate_button: QPushButton | None = None
        self.export_button: QPushButton | None = None
        self._build()
        self.refresh()

    # -- construction -------------------------------------------------------------------

    def _build(self) -> None:
        title = QLabel("Clientes")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Buscalos por nombre o identificación y mirá qué compraron.")
        subtitle.setObjectName("pageSubtitle")
        self.search_edit = SearchField("Buscar por nombre o identificación")
        self.search_edit.setAccessibleName("Buscar clientes")
        self.search_edit.textChanged.connect(self._on_search_edited)
        self.new_button = self._button("Nuevo cliente", "primary", self.new_customer)
        self.edit_button = self._button("Editar", "secondary", self.edit_selected)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addWidget(self.search_edit, 1)
        actions.addWidget(self.new_button)
        actions.addWidget(self.edit_button)
        if self.session.is_owner:
            self.deactivate_button = self._button("Desactivar", "danger", self.deactivate_selected)
            self.export_button = self._button(
                "Exportar clientes con ofertas (CSV)", "secondary", self.export_offers
            )
            actions.addWidget(self.deactivate_button)
            actions.addWidget(self.export_button)
        self.table = DataTable(len(HEADERS), HEADERS)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.empty_state = EmptyState(
            "Todavía no hay clientes",
            "Registralos desde acá o al cobrar: escribís la cédula y listo.",
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 22, 26, 18)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addLayout(actions)
        layout.addWidget(self.table, 3)
        layout.addWidget(self.empty_state)
        layout.addWidget(self._build_detail(), 2)

    def _build_detail(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("customerDetail")
        self.detail_title = QLabel(PICK_ONE)
        self.detail_title.setObjectName("buyerTitle")
        self.total_label = QLabel()
        self.total_label.setObjectName("pageSubtitle")
        self.purchases_table = DataTable(len(PURCHASE_HEADERS), PURCHASE_HEADERS)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.detail_title)
        layout.addWidget(self.total_label)
        layout.addWidget(self.purchases_table, 1)
        return panel

    @staticmethod
    def _button(text: str, variant: str, handler: Callable[[], None]) -> QPushButton:
        button = QPushButton(text)
        set_variant(button, variant)
        button.setAutoDefault(False)
        button.clicked.connect(lambda _checked=False: handler())
        return button

    def _on_search_edited(self, _text: str) -> None:
        self.refresh()

    # -- data ---------------------------------------------------------------------------

    def refresh(self, select_id: int | None = None) -> None:
        """Reload the list for the current search, keeping (or moving to) a selected customer."""
        if select_id is None:
            current = self.selected_customer()
            select_id = None if current is None else current.id
        self._customers = self.service.search(self.session, self.search_edit.text())
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for customer in self._customers:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = (
                customer.full_name,
                customer.id_number,
                customer.phone,
                customer.email,
                "Sí" if customer.accepts_offers else "No",
            )
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
            if customer.id == select_id:
                self.table.selectRow(row)
        self.table.blockSignals(False)
        self.empty_state.setVisible(not self._customers and not self.search_edit.text().strip())
        self.table.setVisible(bool(self._customers) or bool(self.search_edit.text().strip()))
        self._on_selection_changed()

    def selected_customer(self) -> Customer | None:
        row = self.table.currentRow() if self.table.selectedItems() else -1
        return self._customers[row] if 0 <= row < len(self._customers) else None

    def _on_selection_changed(self) -> None:
        customer = self.selected_customer()
        has_selection = customer is not None
        self.edit_button.setEnabled(has_selection)
        if self.deactivate_button is not None:
            self.deactivate_button.setEnabled(has_selection)
        self.purchases_table.setRowCount(0)
        if customer is None:
            self.detail_title.setText(PICK_ONE)
            self.total_label.setText("")
            return
        history = self.service.history(self.session, customer.id)
        self.detail_title.setText(f"Últimas compras de {customer.full_name}")
        self.total_label.setText(
            "Total comprado: "
            + format_money(history.total_cents, self.currency_symbol, self.decimal_separator)
        )
        for purchase in history.purchases:
            row = self.purchases_table.rowCount()
            self.purchases_table.insertRow(row)
            values = (
                f"{purchase.created_at.astimezone():%d/%m/%Y %H:%M}",
                f"N.º {purchase.sale_id}",
                format_money(purchase.total_cents, self.currency_symbol, self.decimal_separator),
            )
            for column, value in enumerate(values):
                self.purchases_table.setItem(row, column, QTableWidgetItem(value))

    # -- actions ------------------------------------------------------------------------

    def _run_dialog(self, customer: Customer | None) -> None:
        dialog = self._dialog_factory(self.service, self.session, customer=customer, parent=self)
        accepted = dialog.exec() == CustomerDialog.DialogCode.Accepted
        saved = dialog.customer
        dialog.deleteLater()
        if accepted and saved is not None:
            self.search_edit.blockSignals(True)
            self.search_edit.clear()
            self.search_edit.blockSignals(False)
            self.refresh(select_id=saved.id)
            self.notification.emit(f"Cliente guardado: {saved.full_name}.", "success")

    def new_customer(self) -> None:
        self._run_dialog(None)

    def edit_selected(self) -> None:
        customer = self.selected_customer()
        if customer is not None:
            self._run_dialog(customer)

    def deactivate_selected(self) -> None:
        customer = self.selected_customer()
        if customer is None or self.deactivate_button is None:
            return
        question = (
            f"¿Desactivar a {customer.full_name}? Deja de aparecer en las búsquedas, "
            "pero sus compras anteriores se conservan."
        )
        if not self._confirmer(self, "Desactivar cliente", question):
            return
        try:
            self.service.deactivate(self.session, customer.id)
        except ValueError as error:
            self.notification.emit(f"No se pudo desactivar. {error}", "danger")
            return
        self.refresh()
        self.notification.emit(f"{customer.full_name} quedó desactivado.", "success")

    def export_offers(self) -> None:
        if self.export_button is None:
            return
        path = self._save_path_picker(self, OFFERS_FILE_NAME)
        if not path:
            return
        try:
            target = self.service.export_offers_csv(self.session, Path(path))
        except (OSError, ValueError) as error:
            self.notification.emit(f"No se pudo exportar. {error}", "danger")
            return
        self.notification.emit(f"Clientes con ofertas exportados a {target}.", "success")

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.refresh()
