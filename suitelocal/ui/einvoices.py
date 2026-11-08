"""Facturas electrónicas page: the send queue, its SRI messages, reissue and RIDE reprint."""

from collections.abc import Callable
from datetime import UTC, datetime

from PySide6.QtCore import Signal
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from suitelocal.application.einvoice import EInvoiceService, InvoiceRow
from suitelocal.domain.auth import Session
from suitelocal.domain.einvoice import (
    AUTHORIZED,
    LOCAL_ERROR,
    NOT_AUTHORIZED,
    PENDING,
    RECEIVED,
    REISSUABLE_STATUSES,
    REPLACED,
    RETURNED,
    SriMessage,
)
from suitelocal.ui.components import (
    DataTable,
    EmptyState,
    InlineMessage,
    StatusBadge,
    confirm_action,
    set_variant,
)
from suitelocal.ui.payment_dialog import format_money
from suitelocal.ui.ride import Ride, RideOutput
from suitelocal.ui.theme.icons import ICONS

ICONS.setdefault("invoice", '<path d="M6 3h9l4 4v14H6zM14 3v5h5M9 13h7M9 17h7"/>')

HEADERS = ["Fecha", "Número", "Cliente", "Total", "Estado", "Último mensaje"]
NUMBER_COLUMN = 1
STATUS_COLUMN = 4
# Chip text and color state of each status in the send queue.
STATUS_CHIPS = {
    PENDING: ("Pendiente", "warning"),
    RECEIVED: ("Recibida", "info"),
    AUTHORIZED: ("Autorizada", "success"),
    RETURNED: ("Devuelta", "danger"),
    NOT_AUTHORIZED: ("No autorizada", "danger"),
    LOCAL_ERROR: ("Error", "danger"),
    REPLACED: ("Reemplazada", "info"),
}

Confirmer = Callable[[QWidget | None, str, str], bool]
MessageViewer = Callable[[QWidget | None, str, str], None]


def show_messages(parent: QWidget | None, title: str, text: str) -> None:
    QMessageBox.information(parent, title, text)


def last_message_text(messages: tuple[SriMessage, ...]) -> str:
    """The latest SRI message in one line, e.g. "35: ARCHIVO NO CUMPLE ESTRUCTURA XML (línea 3)"."""
    if not messages:
        return ""
    last = messages[-1]
    text = f"{last.identifier}: {last.message}"
    return f"{text} ({last.additional_info})" if last.additional_info else text


def messages_text(messages: tuple[SriMessage, ...]) -> str:
    """Every SRI message, one block each, with its additional information below."""
    blocks: list[str] = []
    for message in messages:
        head = f"{message.kind} {message.identifier}".strip()
        block = f"{head}: {message.message}"
        if message.additional_info:
            block += f"\n{message.additional_info}"
        blocks.append(block)
    return "\n\n".join(blocks)


def _late_text(count: int) -> str:
    subject = "1 factura lleva" if count == 1 else f"{count} facturas llevan"
    return (
        f"{subject} más de 60 horas sin que el SRI {'la reciba' if count == 1 else 'las reciba'}. "
        "El plazo es de 72 horas: revisá la conexión y tocá «Procesar ahora»."
    )


class EInvoicesWidget(QWidget):
    """The owner's view of every electronic invoice and what the SRI answered."""

    notification = Signal(str, str)

    def __init__(
        self,
        service: EInvoiceService,
        session: Session,
        process_now: Callable[[], bool],
        ride_output: RideOutput,
        confirmer: Confirmer = confirm_action,
        message_viewer: MessageViewer = show_messages,
        clock: Callable[[], datetime] | None = None,
        currency_symbol: str = "$",
        decimal_separator: str = ",",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.session = session
        self.currency_symbol = currency_symbol
        self.decimal_separator = decimal_separator
        self._process_now = process_now
        self._ride_output = ride_output
        self._confirmer = confirmer
        self._message_viewer = message_viewer
        self._clock = clock or (lambda: datetime.now(UTC))
        self._rows: list[InvoiceRow] = []
        self._build()
        self.refresh()

    # -- construction -------------------------------------------------------------------

    def _build(self) -> None:
        title = QLabel("Facturas electrónicas")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Los comprobantes que se envían al SRI y cómo van.")
        subtitle.setObjectName("pageSubtitle")
        self.deadline_banner = InlineMessage()
        self.process_button = QPushButton("Procesar ahora")
        set_variant(self.process_button, "primary")
        self.process_button.clicked.connect(self.process_now)
        self.reissue_button = QPushButton("Reemitir")
        set_variant(self.reissue_button, "secondary")
        self.reissue_button.clicked.connect(self.reissue_selected)
        self.messages_button = QPushButton("Ver mensajes del SRI")
        set_variant(self.messages_button, "secondary")
        self.messages_button.clicked.connect(self.show_selected_messages)
        self.reprint_button = QPushButton("Reimprimir RIDE")
        set_variant(self.reprint_button, "secondary")
        self.reprint_button.clicked.connect(self.reprint_selected)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        for button in (
            self.process_button,
            self.reissue_button,
            self.messages_button,
            self.reprint_button,
        ):
            button.setAutoDefault(False)
            actions.addWidget(button)
        actions.addStretch()
        self.table = DataTable(len(HEADERS), HEADERS)
        self.table.itemSelectionChanged.connect(self._update_actions)
        self.empty_state = EmptyState(
            "Todavía no hay facturas electrónicas",
            "Se crean solas al cobrar una venta con la factura electrónica activada.",
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 22, 26, 18)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self.deadline_banner)
        layout.addLayout(actions)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.empty_state)

    # -- data ---------------------------------------------------------------------------

    def refresh(self) -> None:
        """Reload the queue, keeping the selected invoice selected."""
        selected = self._selected_row()
        selected_id = None if selected is None else selected.einvoice.id
        self._rows = self.service.list_rows(self.session)
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for row_data in self._rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            invoice = row_data.einvoice
            values = (
                f"{invoice.issued_at.astimezone():%d/%m/%Y %H:%M}",
                invoice.number,
                invoice.buyer.name,
                format_money(row_data.total_cents, self.currency_symbol, self.decimal_separator),
            )
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
            text, state = STATUS_CHIPS.get(invoice.status, (invoice.status, "info"))
            self.table.setCellWidget(row, STATUS_COLUMN, StatusBadge(text, state))
            self.table.setItem(
                row, STATUS_COLUMN + 1, QTableWidgetItem(last_message_text(invoice.messages))
            )
            if invoice.id == selected_id:
                self.table.selectRow(row)
        self.table.blockSignals(False)
        self.empty_state.setVisible(not self._rows)
        self.table.setVisible(bool(self._rows))
        late = self.service.deadline_warnings(self.session, self._clock())
        if late:
            self.deadline_banner.show_warning(_late_text(len(late)))
        else:
            self.deadline_banner.clear_message()
        self._update_actions()

    def _selected_row(self) -> InvoiceRow | None:
        row = self.table.currentRow() if self.table.selectedItems() else -1
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def _update_actions(self) -> None:
        selected = self._selected_row()
        invoice = None if selected is None else selected.einvoice
        self.reissue_button.setEnabled(
            invoice is not None and invoice.status in REISSUABLE_STATUSES
        )
        self.messages_button.setEnabled(invoice is not None and bool(invoice.messages))
        self.reprint_button.setEnabled(invoice is not None)

    # -- actions ------------------------------------------------------------------------

    def process_now(self) -> None:
        if self._process_now():
            self.notification.emit("Procesando las facturas electrónicas…", "info")
        else:
            self.notification.emit(
                "Ya se está procesando o la factura electrónica está desactivada.", "info"
            )

    def reissue_selected(self) -> None:
        selected = self._selected_row()
        if selected is None or selected.einvoice.status not in REISSUABLE_STATUSES:
            return
        invoice = selected.einvoice
        question = (
            f"¿Reemitir la factura {invoice.number}? Se reemplaza por una nueva con otro número."
        )
        if not self._confirmer(self, "Reemitir la factura", question):
            return
        try:
            issued = self.service.reissue_for_sale(self.session, invoice.sale_id)
        except Exception as error:  # a Spanish ValueError, or a certificate or signing problem
            self.refresh()
            self.notification.emit(f"No se pudo reemitir la factura. {error}", "warning")
            return
        self.refresh()
        self.notification.emit(f"Factura reemitida: {issued.number}.", "success")

    def show_selected_messages(self) -> None:
        selected = self._selected_row()
        if selected is None or not selected.einvoice.messages:
            return
        invoice = selected.einvoice
        self._message_viewer(
            self, f"Mensajes del SRI · {invoice.number}", messages_text(invoice.messages)
        )

    def reprint_selected(self) -> None:
        selected = self._selected_row()
        if selected is None:
            return
        try:
            invoice = self.service.invoice_data_for(self.session, selected.einvoice)
            self._ride_output.print_ride(Ride(invoice, selected.einvoice))
        except Exception as error:  # printer drivers raise anything
            self.notification.emit(f"No se pudo imprimir el RIDE: {error}", "warning")
            return
        self.notification.emit("RIDE enviado a la impresora.", "success")

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.refresh()
