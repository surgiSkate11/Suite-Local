"""Tables screen: floor grid of tables, the open account of the selected one and its checkout."""

from collections.abc import Callable, Sequence
from datetime import datetime

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QKeyEvent, QPainter, QPaintEvent, QPen, QResizeEvent
from PySide6.QtWidgets import (
    QAbstractButton,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from suitelocal.application.catalog import CatalogService
from suitelocal.application.einvoice import EInvoiceService
from suitelocal.application.receipts import ReceiptService
from suitelocal.application.tables import TablesService
from suitelocal.domain.auth import Session
from suitelocal.domain.einvoice import Buyer
from suitelocal.domain.models import Payment, Sale
from suitelocal.domain.tables import OpenOrder, OrderLine, TableStatus
from suitelocal.ui.components import (
    Card,
    DangerButton,
    DataTable,
    EmptyState,
    PrimaryButton,
    SearchField,
    SecondaryButton,
    TextField,
    confirm_action,
    set_variant,
)
from suitelocal.ui.components.buyer_section import BuyerDraft
from suitelocal.ui.components.invoice_checkout import InvoiceCheckout
from suitelocal.ui.payment_dialog import PaymentDialog, format_money
from suitelocal.ui.receipt import ReceiptOutput
from suitelocal.ui.ride import RideOutput
from suitelocal.ui.theme.manager import current_tokens, theme_manager

__all__ = ["TablesWidget"]

PaymentDialogFactory = Callable[..., PaymentDialog]
TableChooser = Callable[[QWidget, Sequence[TableStatus]], int | None]
Confirmer = Callable[[QWidget | None, str, str], bool]

# A cash payment this large always covers any order, so the sale only reports its total.
_COVERS_ANY_TOTAL_CENTS = 10**12

LINE_HEADERS = ["Producto", "Cantidad", "Precio", "Total", "Estado", ""]
ACTIONS_COLUMN = 5
ACTIONS_COLUMN_WIDTH = 132


def choose_free_table(parent: QWidget, free_tables: Sequence[TableStatus]) -> int | None:
    """Ask which free table receives the account; None when the cashier cancels."""
    names = [status.table.name for status in free_tables]
    name, accepted = QInputDialog.getItem(
        parent, "Pasar a otra mesa", "Elegí la mesa de destino:", names, 0, False
    )
    if not accepted:
        return None
    return next((s.table.id for s in free_tables if s.table.name == name), None)


class TableCard(QAbstractButton):
    """One table of the floor: name, zone, free/occupied pill and, if busy, amount and time."""

    RADIUS = 12

    def __init__(self, status: TableStatus, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.table_id = status.table.id
        self.name_text = status.table.name
        self.zone_text = status.table.zone or ""
        self.status_text = "Ocupada" if status.occupied else "Libre"
        self.detail_text = text
        self._selected = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumSize(150, 96)
        parts = [self.name_text, self.zone_text, self.status_text, self.detail_text]
        self.setAccessibleName(", ".join(part for part in parts if part))
        theme_manager().theme_changed.connect(self._on_theme_changed)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.update()

    @property
    def selected(self) -> bool:
        return self._selected

    def sizeHint(self) -> QSize:
        return QSize(190, 104)

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.click()
            return
        super().keyPressEvent(e)

    def _on_theme_changed(self, _name: str) -> None:
        self.update()

    def paintEvent(self, e: QPaintEvent) -> None:
        tokens = current_tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        border = tokens.brand_800 if self._selected else tokens.border_strong
        painter.setPen(QPen(QColor(border), 2 if self._selected else 1))
        painter.setBrush(QColor(tokens.brand_50 if self._selected else tokens.surface))
        painter.drawRoundedRect(rect, self.RADIUS, self.RADIUS)
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(tokens.focus), 2))
            painter.drawRoundedRect(rect.adjusted(-1, -1, 1, 1), self.RADIUS, self.RADIUS)

        bold = painter.font()
        bold.setBold(True)
        regular = painter.font()
        regular.setBold(False)
        occupied = self.status_text == "Ocupada"
        pill_text = self.status_text
        pill_fill = tokens.champagne_background if occupied else tokens.success_background
        pill_ink = tokens.champagne_text if occupied else tokens.success
        painter.setFont(bold)
        pill_width = QFontMetrics(bold).horizontalAdvance(pill_text) + 20
        pill = QRectF(rect.right() - 12 - pill_width, rect.top() + 12, pill_width, 22)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(pill_fill))
        painter.drawRoundedRect(pill, 11, 11)
        painter.setPen(QColor(pill_ink))
        painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, pill_text)

        left = rect.left() + 14
        name_width = int(pill.left() - left - 8)
        painter.setPen(QColor(tokens.text_900))
        name = QFontMetrics(bold).elidedText(
            self.name_text, Qt.TextElideMode.ElideRight, name_width
        )
        painter.drawText(
            QRectF(left, rect.top() + 10, name_width, 28),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            name,
        )
        painter.setFont(regular)
        painter.setPen(QColor(tokens.text_500))
        text_width = int(rect.width() - 28)
        zone = QFontMetrics(regular).elidedText(
            self.zone_text, Qt.TextElideMode.ElideRight, text_width
        )
        painter.drawText(
            QRectF(left, rect.top() + 40, text_width, 20),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            zone,
        )
        painter.setFont(bold)
        painter.setPen(QColor(tokens.text_900))
        painter.drawText(
            QRectF(left, rect.bottom() - 34, text_width, 24),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.detail_text,
        )


class FloorGrid(QScrollArea):
    """Scrolling grid of table cards whose column count follows the available width."""

    CARD_MIN_WIDTH = 170
    GAP = 12
    MAX_COLUMNS = 5
    SCROLLBAR_RESERVE = 14

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("productGrid")
        self.viewport().setObjectName("productGridViewport")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host = QWidget()
        host.setObjectName("productGridHost")
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 0, 4)
        self._cards_widget = QWidget()
        self._grid = QGridLayout(self._cards_widget)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(self.GAP)
        host_layout.addWidget(self._cards_widget)
        host_layout.addStretch()
        self.setWidget(host)
        self._cards: list[TableCard] = []
        self.columns = self.columns_for_width(self.width())

    @classmethod
    def columns_for_width(cls, width: int) -> int:
        usable = width - cls.SCROLLBAR_RESERVE
        return max(1, min(cls.MAX_COLUMNS, (usable + cls.GAP) // (cls.CARD_MIN_WIDTH + cls.GAP)))

    def set_cards(self, cards: list[TableCard]) -> None:
        for card in self._cards:
            self._grid.removeWidget(card)
            card.hide()
            card.deleteLater()
        self._cards = cards
        for card in cards:
            card.setParent(self._cards_widget)
        self._reflow()

    def _reflow(self) -> None:
        for index, card in enumerate(self._cards):
            self._grid.removeWidget(card)
            self._grid.addWidget(card, index // self.columns, index % self.columns)
            card.show()
        for column in range(self.MAX_COLUMNS):
            self._grid.setColumnStretch(column, 1 if column < self.columns else 0)

    def resizeEvent(self, arg__1: QResizeEvent) -> None:
        super().resizeEvent(arg__1)
        columns = self.columns_for_width(arg__1.size().width())
        if columns != self.columns:
            self.columns = columns
            self._reflow()


def _label(text: str, name: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    return label


class TablesWidget(QWidget):
    notification = Signal(str, str)
    sale_registered = Signal()
    # After an invoice was attempted for a charge, so the status bar and invoice page refresh.
    invoice_issued = Signal()

    def __init__(
        self,
        service: TablesService,
        catalog: CatalogService,
        session: Session,
        currency_symbol: str = "$",
        decimal_separator: str = ",",
        enabled_payment_methods: tuple[str, ...] = ("cash", "transfer"),
        payment_dialog_factory: PaymentDialogFactory | None = None,
        now: Callable[[], datetime] = datetime.now,
        table_chooser: TableChooser | None = None,
        confirmer: Confirmer | None = None,
        parent: QWidget | None = None,
        receipts: ReceiptService | None = None,
        receipt_output: ReceiptOutput | None = None,
        einvoices: EInvoiceService | None = None,
        ride_output: RideOutput | None = None,
        einvoicing_enabled: bool = False,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.catalog = catalog
        self.session = session
        self.currency_symbol = currency_symbol
        self.decimal_separator = decimal_separator
        self.enabled_payment_methods = enabled_payment_methods or ("cash",)
        self.payment_dialog_factory: PaymentDialogFactory = payment_dialog_factory or PaymentDialog
        self.now = now
        self.table_chooser: TableChooser = table_chooser or choose_free_table
        self.confirmer: Confirmer = confirmer or confirm_action
        self.receipts = receipts
        self.receipt_output = receipt_output
        self.last_print_ticket = False
        self.last_buyer: Buyer | None = None
        self.einvoicing_enabled = einvoicing_enabled
        self._invoice_checkout: InvoiceCheckout | None = None
        if (
            einvoices is not None
            and ride_output is not None
            and receipts is not None
            and receipt_output is not None
        ):
            self._invoice_checkout = InvoiceCheckout(
                einvoices, session, receipts, receipt_output, ride_output, self.notification.emit
            )
        self.cards: list[TableCard] = []
        self.statuses: list[TableStatus] = []
        self.selected_table_id: int | None = None
        self.order: OpenOrder | None = None
        self._build()
        self.refresh()

    # -- construction ---------------------------------------------------------------------

    def _build(self) -> None:
        title = _label("Mesas", "pageTitle")
        subtitle = _label("Cuentas abiertas por mesa, de la comanda al cobro.", "pageSubtitle")

        self.new_table_name = TextField("Nombre de la mesa")
        self.new_table_zone = TextField("Zona (opcional)")
        self.new_table_button = SecondaryButton("Nueva mesa")
        self.new_table_name.returnPressed.connect(self.create_table)
        self.new_table_zone.returnPressed.connect(self.create_table)
        self.new_table_button.clicked.connect(self.create_table)
        self.new_table_box = QWidget()
        form = QHBoxLayout(self.new_table_box)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)
        form.addWidget(self.new_table_name, 2)
        form.addWidget(self.new_table_zone, 1)
        form.addWidget(self.new_table_button)
        self.new_table_box.setVisible(self.session.is_owner)

        self.floor = FloorGrid()
        empty_hint = (
            "Creá la primera mesa con el formulario de arriba."
            if self.session.is_owner
            else "El dueño del negocio puede crear las mesas."
        )
        self.empty_state = EmptyState("Todavía no hay mesas", empty_hint)

        left = QVBoxLayout()
        left.setSpacing(12)
        left.addWidget(title)
        left.addWidget(subtitle)
        left.addWidget(self.new_table_box)
        left.addWidget(self.floor, 1)
        left.addWidget(self.empty_state)
        left.addStretch()

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)
        root.addLayout(left, 3)
        root.addWidget(self._build_panel(), 2)

    def _build_panel(self) -> Card:
        panel = Card()
        panel.setMinimumWidth(380)
        layout = panel.content_layout

        self.placeholder_label = _label("Elegí una mesa para ver su cuenta.", "pageSubtitle")
        self.placeholder_label.setWordWrap(True)
        self.panel_title = _label("", "sectionTitle")
        self.panel_subtitle = _label("", "pageSubtitle")
        self.open_button = PrimaryButton("Abrir cuenta")
        self.open_button.clicked.connect(self.open_account)

        self.search = SearchField("Buscá un producto por nombre o código...")
        self.search.setAccessibleName("Buscar producto para agregar a la cuenta")
        self.search.returnPressed.connect(self.add_first_match)
        self.lines_table = DataTable(len(LINE_HEADERS), LINE_HEADERS)
        self.lines_table.setSelectionMode(DataTable.SelectionMode.NoSelection)
        header = self.lines_table.horizontalHeader()
        header.setSectionResizeMode(ACTIONS_COLUMN, QHeaderView.ResizeMode.Fixed)
        self.lines_table.setColumnWidth(ACTIONS_COLUMN, ACTIONS_COLUMN_WIDTH)
        self.total_label = _label("", "kpiValue")
        self.total_note = _label("", "pageSubtitle")

        self.send_button = SecondaryButton("Enviar a cocina")
        self.send_button.clicked.connect(self.send_to_kitchen)
        self.transfer_button = SecondaryButton("Pasar a otra mesa")
        self.transfer_button.clicked.connect(self.transfer_order)
        self.cancel_button = DangerButton("Anular cuenta")
        self.cancel_button.clicked.connect(self.cancel_order)
        self.charge_button = PrimaryButton("Cobrar mesa")
        self.charge_button.clicked.connect(self.charge_order)

        total_row = QHBoxLayout()
        total_row.addWidget(_label("Total", "kpiLabel"))
        total_row.addStretch()
        total_row.addWidget(self.total_label)
        secondary_row = QHBoxLayout()
        secondary_row.setSpacing(8)
        secondary_row.addWidget(self.send_button)
        secondary_row.addWidget(self.transfer_button)
        secondary_row.addWidget(self.cancel_button)

        self.order_controls: list[QWidget] = [
            self.search,
            self.lines_table,
            self.total_note,
            self.send_button,
            self.transfer_button,
            self.cancel_button,
            self.charge_button,
            self.total_label,
        ]
        layout.addWidget(self.placeholder_label)
        layout.addWidget(self.panel_title)
        layout.addWidget(self.panel_subtitle)
        layout.addWidget(self.open_button)
        layout.addWidget(self.search)
        layout.addWidget(self.lines_table, 1)
        layout.addLayout(total_row)
        layout.addWidget(self.total_note)
        layout.addLayout(secondary_row)
        layout.addWidget(self.charge_button)
        layout.addStretch()
        return panel

    # -- rendering ------------------------------------------------------------------------

    def refresh(self) -> None:
        """Reload tables and open accounts from the database and redraw both sides."""
        self.statuses = self.service.list_tables(self.session)
        now = self.now()
        cards: list[TableCard] = []
        for status in self.statuses:
            card = TableCard(status, self._card_detail(status, now))
            card.clicked.connect(lambda _checked=False, id=status.table.id: self.select_table(id))
            card.set_selected(status.table.id == self.selected_table_id)
            cards.append(card)
        self.cards = cards
        self.floor.set_cards(cards)
        has_tables = bool(cards)
        self.floor.setVisible(has_tables)
        self.empty_state.setVisible(not has_tables)
        self._render_panel()

    def _card_detail(self, status: TableStatus, now: datetime) -> str:
        if status.order is None:
            return ""
        amount = self._money(status.order.subtotal_cents)
        return f"{amount} · {status.order.minutes_open(now)} min"

    def _selected_status(self) -> TableStatus | None:
        return next((s for s in self.statuses if s.table.id == self.selected_table_id), None)

    @property
    def placeholder_text(self) -> str:
        return self.placeholder_label.text()

    def _render_panel(self) -> None:
        status = self._selected_status()
        if status is None:
            self.selected_table_id = None
        self.order = status.order if status else None
        self.placeholder_label.setVisible(status is None)
        self.panel_title.setVisible(status is not None)
        self.panel_subtitle.setVisible(status is not None)
        self.open_button.setVisible(status is not None and status.order is None)
        for widget in self.order_controls:
            widget.setVisible(self.order is not None)
        if status is None:
            return
        self.panel_title.setText(status.table.name)
        zone = status.table.zone or ""
        if self.order is None:
            self.panel_subtitle.setText(" · ".join(part for part in (zone, "Libre") if part))
            return
        minutes = f"Abierta hace {self.order.minutes_open(self.now())} min"
        self.panel_subtitle.setText(" · ".join(part for part in (zone, minutes) if part))
        self._fill_lines(self.order)
        self.total_label.setText(self._money(self._grand_total(self.order)))
        note = self._tax_note(self.order)
        self.total_note.setText(note)
        self.total_note.setVisible(bool(note))

    def _fill_lines(self, order: OpenOrder) -> None:
        table = self.lines_table
        table.setRowCount(0)
        table.setRowCount(len(order.lines))
        for row, line in enumerate(order.lines):
            status = "Pendiente" if line.pending_quantity > 0 else "En cocina"
            values = [
                line.product_name,
                str(line.quantity),
                self._money(line.unit_price_cents),
                self._money(line.total_cents),
                status,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column in (1, 2, 3):
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                table.setItem(row, column, item)
            table.setCellWidget(row, ACTIONS_COLUMN, self._line_actions(line))

    def _line_actions(self, line: OrderLine) -> QWidget:
        increase = self._step_button("+", f"Aumentar cantidad de {line.product_name}")
        increase.clicked.connect(lambda: self.change_quantity(line.product_id, 1))
        decrease = self._step_button("−", f"Disminuir cantidad de {line.product_name}")
        decrease.clicked.connect(lambda: self.change_quantity(line.product_id, -1))
        remove = self._step_button("×", f"Quitar {line.product_name} de la cuenta")
        remove.clicked.connect(lambda: self.remove_line(line.product_id))
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(4, 0, 4, 0)
        row.setSpacing(4)
        for button in (decrease, increase, remove):
            row.addWidget(button)
        return host

    @staticmethod
    def _step_button(text: str, accessible_name: str) -> QPushButton:
        button = set_variant(QPushButton(text), "ghost")
        button.setFixedSize(34, 34)
        button.setAccessibleName(accessible_name)
        button.setToolTip(accessible_name)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def _sale_for(self, order: OpenOrder, payments: Sequence[Payment]) -> Sale:
        """The sale the domain would register; totals and tax are always computed by it."""
        return Sale(
            order.sale_items(),
            sum(payment.amount_cents for payment in payments),
            tuple(payments),
        )

    def _covering_sale(self, order: OpenOrder) -> Sale:
        return self._sale_for(order, (Payment("cash", _COVERS_ANY_TOTAL_CENTS),))

    def _money(self, cents: int) -> str:
        return format_money(cents, self.currency_symbol, self.decimal_separator)

    def _grand_total(self, order: OpenOrder) -> int:
        return self._covering_sale(order).total_cents if order.lines else 0

    def _tax_note(self, order: OpenOrder) -> str:
        """The IVA already inside the total, as the counter POS shows it; empty when none."""
        tax_cents = self._covering_sale(order).tax_cents if order.lines else 0
        return f"IVA incluido {self._money(tax_cents)}" if tax_cents else ""

    # -- selection and actions ------------------------------------------------------------

    def select_table(self, table_id: int) -> None:
        self.selected_table_id = table_id
        for card in self.cards:
            card.set_selected(card.table_id == table_id)
        self.search.clear()
        self._render_panel()
        if self.order is not None:
            self.search.setFocus()

    def _fail(self, prefix: str, error: Exception) -> None:
        self.notification.emit(f"{prefix} {error}", "danger")

    def create_table(self) -> None:
        name = self.new_table_name.text()
        try:
            table = self.service.create_table(self.session, name, self.new_table_zone.text())
        except ValueError as error:
            self._fail("No se puede crear la mesa.", error)
            return
        self.new_table_name.clear()
        self.new_table_zone.clear()
        self.refresh()
        self.notification.emit(f"Se creó {table.name}.", "success")

    def open_account(self) -> None:
        status = self._selected_status()
        if status is None or status.order is not None:
            return
        try:
            self.service.open_order(self.session, status.table.id)
        except ValueError as error:
            self._fail("No se puede abrir la cuenta.", error)
            self.refresh()
            return
        self.refresh()
        self.search.setFocus()

    def add_first_match(self) -> None:
        if self.order is None:
            return
        text = self.search.text().strip()
        if not text:
            return
        matches = self.catalog.search(self.session, text)
        if not matches:
            self.notification.emit(f"No hay productos que coincidan con «{text}».", "info")
            return
        try:
            self.service.add_product(self.session, self.order.id, matches[0].id, 1)
        except ValueError as error:
            self._fail("No se puede agregar.", error)
            self.refresh()
            return
        self.search.clear()
        self.refresh()
        self.search.setFocus()

    def change_quantity(self, product_id: int, delta: int) -> None:
        if self.order is None:
            return
        line = next((item for item in self.order.lines if item.product_id == product_id), None)
        if line is None:
            return
        quantity = line.quantity + delta
        if quantity <= 0:
            self.remove_line(product_id)
            return
        try:
            self.service.set_quantity(self.session, self.order.id, product_id, quantity)
        except ValueError as error:
            self._fail("No se puede cambiar la cantidad.", error)
        self.refresh()

    def remove_line(self, product_id: int) -> None:
        if self.order is None:
            return
        try:
            self.service.remove_line(self.session, self.order.id, product_id)
        except ValueError as error:
            self._fail("No se puede quitar el producto.", error)
        self.refresh()

    def send_to_kitchen(self) -> None:
        if self.order is None:
            return
        try:
            sent = self.service.send_to_kitchen(self.session, self.order.id)
        except ValueError as error:
            self._fail("No se puede enviar a cocina.", error)
            self.refresh()
            return
        if not sent:
            self.notification.emit("No hay productos nuevos para enviar.", "info")
            return
        items = ", ".join(f"{line.quantity} × {line.product_name}" for line in sent)
        self.refresh()
        self.notification.emit(f"Enviado a cocina: {items}.", "success")

    def transfer_order(self) -> None:
        status = self._selected_status()
        if status is None or status.order is None:
            return
        free = [s for s in self.statuses if s.order is None]
        if not free:
            self.notification.emit("No hay mesas libres para pasar la cuenta.", "info")
            return
        target_id = self.table_chooser(self, free)
        if target_id is None:
            return
        try:
            self.service.transfer(self.session, status.order.id, target_id)
        except ValueError as error:
            self._fail("No se puede pasar la cuenta.", error)
            self.refresh()
            return
        target = next((s.table.name for s in free if s.table.id == target_id), "la otra mesa")
        self.selected_table_id = target_id
        self.refresh()
        self.notification.emit(f"La cuenta de {status.table.name} pasó a {target}.", "success")

    def cancel_order(self) -> None:
        status = self._selected_status()
        if status is None or status.order is None:
            return
        question = f"¿Anular la cuenta de {status.table.name}? Se pierden los productos cargados."
        if not self.confirmer(self, "Anular cuenta", question):
            return
        try:
            self.service.cancel(self.session, status.order.id)
        except ValueError as error:
            self._fail("No se puede anular la cuenta.", error)
            self.refresh()
            return
        self.refresh()
        self.notification.emit(f"Se anuló la cuenta de {status.table.name}.", "info")

    @property
    def invoicing_active(self) -> bool:
        """True when charges are invoiced: the module is on and the wiring to issue exists."""
        return self.einvoicing_enabled and self._invoice_checkout is not None

    def charge_order(self) -> None:
        status = self._selected_status()
        order = self.order
        if status is None or order is None:
            return
        if not order.lines:
            self.notification.emit("No se puede cobrar. Agregá al menos un producto.", "danger")
            return
        payments = self._collect_payments(status.table.name, order)
        if payments is None:
            return
        try:
            sale_id = self.service.charge(self.session, order.id, payments)
        except ValueError as error:
            self._fail("No se puede cobrar.", error)
            self.refresh()
            return
        total = self._money(self._grand_total(order))
        self.refresh()
        self.notification.emit(
            f"{status.table.name} cobrada · Venta N.º {sale_id} · Total {total}", "success"
        )
        self.sale_registered.emit()
        if self._invoice_checkout is not None and self.invoicing_active and self.last_buyer:
            self._invoice_checkout.complete(sale_id, self.last_buyer, self.last_print_ticket)
            self.invoice_issued.emit()
        elif self.last_print_ticket:
            self._print_receipt(sale_id)

    def _print_receipt(self, sale_id: int) -> None:
        """Print the stored sale; the charge is already saved, so a failure only warns."""
        if self._invoice_checkout is not None and self.invoicing_active:
            self._invoice_checkout.print_sale(sale_id)
            return
        if self.receipts is None or self.receipt_output is None:
            return
        try:
            self.receipt_output.print_receipt(self.receipts.build(self.session, sale_id))
        except Exception as error:  # printer drivers raise anything
            self.notification.emit(f"No se pudo imprimir el ticket: {error}", "warning")

    def _collect_payments(self, table_name: str, order: OpenOrder) -> tuple[Payment, ...] | None:
        """Open the payment dialog; return its payments, or None when the cashier cancels."""

        def validate(payments: tuple[Payment, ...]) -> Sale:
            return self._sale_for(order, payments)

        # Only an active invoicing run hands the dialog its Comprobante section.
        invoicing: dict[str, object] = (
            {"invoicing": True, "buyer_draft": BuyerDraft()} if self.invoicing_active else {}
        )
        dialog = self.payment_dialog_factory(
            total_cents=self._grand_total(order),
            currency_symbol=self.currency_symbol,
            decimal_separator=self.decimal_separator,
            enabled_methods=self.enabled_payment_methods,
            sale_label=table_name,
            total_note=self._tax_note(order),
            validate=validate,
            parent=self,
            **invoicing,
        )
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        payments = dialog.payments
        self.last_buyer = dialog.buyer if accepted and self.invoicing_active else None
        self.last_print_ticket = accepted and dialog.print_ticket
        dialog.deleteLater()
        return payments if accepted and payments else None
