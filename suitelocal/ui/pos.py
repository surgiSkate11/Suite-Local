import re
from collections.abc import Callable, Sequence
from decimal import Decimal

from PySide6.QtCore import QDate, QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QKeyEvent, QKeySequence, QResizeEvent, QShortcut, QShowEvent
from PySide6.QtWidgets import (
    QBoxLayout,
    QDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from suitelocal.application.cart import Cart
from suitelocal.application.einvoice import EInvoiceService
from suitelocal.application.receipts import ReceiptService
from suitelocal.domain.auth import Session
from suitelocal.domain.business import (
    DEFAULT_TAX_REGIME,
    SALES_NOTE_MAX_LENGTH,
    SALES_NOTE_REGIME,
    BusinessSettings,
    issues_electronic_invoices,
)
from suitelocal.domain.einvoice import Buyer
from suitelocal.domain.models import Payment, Product, SaleError
from suitelocal.infrastructure.repositories import Category, ProductRepository, SaleRepository
from suitelocal.ui.components import (
    ElidedLabel,
    EmptyState,
    InlineMessage,
    KeyHint,
    ProductGrid,
    SegmentedControl,
    SwitchButton,
    TicketLine,
    set_variant,
)
from suitelocal.ui.components.buyer_section import BuyerSection
from suitelocal.ui.components.invoice_checkout import InvoiceCheckout
from suitelocal.ui.components.product import repolish
from suitelocal.ui.payment_dialog import (
    METHOD_LABELS,
    PaymentDialog,
    format_money,
    parse_money,
    quick_bill_amounts,
)
from suitelocal.ui.receipt import ReceiptOutput
from suitelocal.ui.ride import RideOutput
from suitelocal.ui.theme.effects import apply_elevation
from suitelocal.ui.theme.icons import ICONS, icon
from suitelocal.ui.theme.manager import current_tokens, theme_manager

__all__ = ["PosWidget", "format_money"]

ICONS.setdefault(
    "barcode", '<path d="M3 7V4h3M21 7V4h-3M3 17v3h3M21 17v3h-3M7 8v8M10 8v8M13 8v8M16 8v8"/>'
)

PaymentDialogFactory = Callable[..., PaymentDialog]


QUICK_KEY_COUNT = 6
TICKET_COLUMN_WIDTH = 440
TICKET_COLUMN_NARROW_WIDTH = 392
COMPACT_BELOW_WIDTH = 900
# Below this width the ticket narrows and secondary hints hide so the catalog keeps 3 columns.
NARROW_BELOW_WIDTH = 1240
FILTER_ALL = "Todos"
FILTER_LOW_STOCK = "Stock bajo"
# "3*" before a code multiplies the quantity; at most three digits so a barcode never matches.
QUANTITY_PREFIX = re.compile(r"^\s*(\d{1,3})\*(.*)$", re.DOTALL)
WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
MONTHS = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)
DIGIT_KEYS = {
    Qt.Key.Key_1: 1,
    Qt.Key.Key_2: 2,
    Qt.Key.Key_3: 3,
    Qt.Key.Key_4: 4,
    Qt.Key.Key_5: 5,
    Qt.Key.Key_6: 6,
}


def _label(text: str, object_name: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName(object_name)
    return label


def _kpi_tile(caption: str) -> tuple[QFrame, QLabel]:
    tile = QFrame()
    tile.setObjectName("kpiTile")
    tile.setMinimumWidth(120)
    layout = QVBoxLayout(tile)
    layout.setContentsMargins(14, 8, 14, 8)
    layout.setSpacing(0)
    value = _label("—", "kpiTileValue")
    layout.addWidget(_label(caption, "kpiTileLabel"))
    layout.addWidget(value)
    return tile, value


def _overlay_row(button: QPushButton, *widgets: QWidget) -> None:
    """Lay labels over a button's right edge; they ignore the mouse so the button gets clicks."""
    layout = QHBoxLayout(button)
    layout.setContentsMargins(20, 0, 16, 0)
    layout.setSpacing(10)
    layout.addStretch()
    for widget in widgets:
        widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(widget)


class PosWidget(QWidget):
    sale_registered = Signal()
    notification = Signal(str, str)
    # After an invoice was attempted for a sale, so the status bar and the invoice page refresh.
    invoice_issued = Signal()

    def __init__(
        self,
        products: ProductRepository,
        sales: SaleRepository,
        enabled_payment_methods: tuple[str, ...] = ("cash", "transfer"),
        currency_symbol: str = "$",
        parent: QWidget | None = None,
        business_name: str = "",
        low_stock_threshold: int = 3,
        decimal_separator: str = ",",
        enabled_modules: frozenset[str] = frozenset(),
        categories: Sequence[Category] = (),
        tax_regime: str = DEFAULT_TAX_REGIME,
        session: Session | None = None,
        receipts: ReceiptService | None = None,
        receipt_output: ReceiptOutput | None = None,
        einvoices: EInvoiceService | None = None,
        ride_output: RideOutput | None = None,
        einvoicing_enabled: bool = False,
    ) -> None:
        super().__init__(parent)
        self.products = products
        self.sales = sales
        # Who sells decides the business and cashier stored on the sale and printed on the ticket.
        self.session = session
        self.receipts = receipts
        self.receipt_output = receipt_output
        self.tax_regime = tax_regime
        self.last_sale_id: int | None = None
        self.currency_symbol = currency_symbol
        self.decimal_separator = decimal_separator
        self.enabled_modules = enabled_modules
        self.categories = tuple(categories)
        self._category_ids: dict[str, int] = {}
        self.enabled_payment_methods = enabled_payment_methods or ("cash",)
        self.low_stock_threshold = low_stock_threshold
        self.sale_label = business_name or "Venta actual"
        self.payment_dialog_factory: PaymentDialogFactory = PaymentDialog
        self.last_print_ticket = False
        self.last_buyer: Buyer | None = None
        # Without a session and a printer wired in, the primary action only charges.
        self.can_print_ticket = (
            session is not None and receipts is not None and receipt_output is not None
        )
        # The Comprobante section and the RIDE need the whole electronic-invoicing wiring.
        self._invoice_checkout: InvoiceCheckout | None = None
        if (
            einvoices is not None
            and ride_output is not None
            and session is not None
            and receipts is not None
            and receipt_output is not None
        ):
            self._invoice_checkout = InvoiceCheckout(
                einvoices,
                session,
                receipts,
                receipt_output,
                ride_output,
                self.notification.emit,
            )
        self.einvoicing_enabled = einvoicing_enabled
        self.cart = Cart()
        self.quick_key_delay_ms = 400
        self.ticket_lines: list[TicketLine] = []
        self._selected_id: int | None = None
        self._armed_quantity = 1
        self._typed_quantity: int | None = None
        self._quick_products: list[Product | None] = [None] * QUICK_KEY_COUNT
        self._bill_amounts: list[int] = []
        self._method = self.enabled_payment_methods[0]
        self._compact = False
        self._empty_input = True
        self._quick_digit = 0
        self._quick_timer = QTimer(self)
        self._quick_timer.setSingleShot(True)
        self._quick_timer.timeout.connect(self._fire_quick_key)

        self.center = self._build_center()
        self.ticket_container = self._build_ticket()
        self._root = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(0)
        self._root.addWidget(self.center, 1)
        self._root.addWidget(self.ticket_container, 0)
        self._install_shortcuts()
        theme_manager().theme_changed.connect(self._apply_theme)
        self._apply_theme()
        self._relayout(TICKET_COLUMN_WIDTH + 768)
        self.refresh_products()
        self.refresh_quick_keys()
        self.refresh_cart()
        self.refresh_kpis()
        self.search_input.setFocus()

    # -- construction -------------------------------------------------------------------

    def _build_center(self) -> QWidget:
        center = QWidget()
        layout = QVBoxLayout(center)
        layout.setContentsMargins(26, 22, 26, 16)
        layout.setSpacing(14)
        layout.addWidget(self._build_header())
        layout.addWidget(self._build_scanner())
        self.scanner_status = _label("", "scannerStatus")
        self.scanner_status.setWordWrap(True)
        self.scanner_status.setMinimumWidth(0)
        layout.addWidget(self.scanner_status)
        layout.addLayout(self._build_quick_keys())
        self._category_ids = self._categories_with_products()
        self.filter_control = self._new_filter_control()
        self._filter_row = QHBoxLayout()
        self._filter_row.addWidget(self.filter_control)
        self._filter_row.addStretch()
        layout.addLayout(self._filter_row)
        self.product_list = ProductGrid()
        self.product_list.setMinimumHeight(170)
        self.product_list.product_chosen.connect(self._on_product_chosen)
        self.product_empty = EmptyState(
            "No hay productos para mostrar",
            "Escribe un nombre o código distinto, o cambia el filtro del catálogo.",
        )
        self.product_empty.hide()
        layout.addWidget(self.product_list, 1)
        layout.addWidget(self.product_empty)
        return center

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("posHeader")
        row = QHBoxLayout(header)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(16)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.eyebrow_label = _label(self._date_text(), "posEyebrow")
        self.eyebrow_label.setProperty("role", "eyebrow")
        self.title_label = QLabel("Nueva venta")
        self.title_label.setProperty("role", "display")
        titles.addWidget(self.eyebrow_label)
        titles.addWidget(self.title_label)
        row.addLayout(titles)
        row.addStretch()
        sales_tile, self.kpi_sales = _kpi_tile("Ventas hoy")
        revenue_tile, self.kpi_revenue = _kpi_tile("Facturado")
        average_tile, self.kpi_average = _kpi_tile("Ticket promedio")
        self.kpi_average_tile = average_tile
        for tile in (sales_tile, revenue_tile, average_tile):
            row.addWidget(tile)
        return header

    @staticmethod
    def _date_text() -> str:
        today = QDate.currentDate()
        weekday = WEEKDAYS[today.dayOfWeek() - 1].capitalize()
        return f"{weekday} {today.day()} de {MONTHS[today.month() - 1]}"

    def _build_scanner(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("scanBar")
        bar.setFixedHeight(62)
        row = QHBoxLayout(bar)
        row.setContentsMargins(18, 0, 14, 0)
        row.setSpacing(14)
        self.scan_icon = QLabel()
        self.scan_icon.setFixedSize(28, 28)
        self.search_input = QLineEdit()
        self.search_input.setObjectName("scanInput")
        self.search_input.setPlaceholderText("Escaneá el código o escribí el nombre del producto")
        self.search_input.setAccessibleName("Buscar producto")
        self.search_input.setProperty("empty", True)
        self.search_input.setClearButtonEnabled(False)
        self.search_input.textChanged.connect(self._on_scan_text_changed)
        self.search_input.returnPressed.connect(self._on_scan_submitted)
        self.search_input.installEventFilter(self)
        self.quantity_hint = _label("", "scanHint")
        self.reader_status = _label("Lector listo", "readerStatus")
        row.addWidget(self.scan_icon)
        row.addWidget(self.search_input, 1)
        row.addWidget(self.quantity_hint)
        row.addWidget(self.reader_status)
        row.addWidget(KeyHint("F2"))
        self._update_quantity_hint()
        return bar

    def _build_quick_keys(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        self.quick_buttons: list[QPushButton] = []
        self._quick_names: list[ElidedLabel] = []
        self._quick_prices: list[QLabel] = []
        for index in range(QUICK_KEY_COUNT):
            button = QPushButton()
            button.setObjectName("quickKey")
            button.setFixedHeight(52)
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            inner = QVBoxLayout(button)
            inner.setContentsMargins(12, 0, 10, 0)
            inner.setSpacing(1)
            top = QHBoxLayout()
            top.setSpacing(6)
            name = ElidedLabel("")
            name.setObjectName("quickName")
            top.addWidget(name, 1)
            top.addWidget(KeyHint(str(index + 1)))
            price = _label("", "quickPrice")
            inner.addLayout(top)
            inner.addWidget(price)
            for child in (name, price):
                child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            button.clicked.connect(lambda _checked=False, key=index: self.add_quick_product(key))
            self.quick_buttons.append(button)
            self._quick_names.append(name)
            self._quick_prices.append(price)
            row.addWidget(button, 1)
        return row

    def _build_ticket(self) -> QWidget:
        container = QWidget()
        container.setObjectName("ticketContainer")
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 14, 14, 10)
        self.ticket_panel = QFrame()
        self.ticket_panel.setObjectName("ticketPanel")
        self.ticket_panel.setProperty("toastKeepClear", True)
        apply_elevation(self.ticket_panel, "e2")
        outer.addWidget(self.ticket_panel)
        layout = QVBoxLayout(self.ticket_panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        head = QHBoxLayout()
        head.setContentsMargins(20, 18, 20, 8)
        self.sale_title = QLabel("Venta actual")
        self.sale_title.setObjectName("saleTitle")
        self.sale_title.setProperty("role", "display")
        # Customers do not exist yet, so the sale is always anonymous and there is no assign action.
        self.customer_label = _label("Consumidor final", "customerLabel")
        head.addWidget(self.sale_title)
        head.addStretch()
        head.addWidget(self.customer_label)
        layout.addLayout(head)

        self.lines_scroll = QScrollArea()
        self.lines_scroll.setObjectName("ticketLines")
        self.lines_scroll.viewport().setObjectName("ticketLinesViewport")
        self.lines_scroll.setWidgetResizable(True)
        self.lines_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.lines_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.lines_scroll.setMinimumHeight(110)
        host = QWidget()
        host.setObjectName("ticketLinesHost")
        self.lines_layout = QVBoxLayout(host)
        self.lines_layout.setContentsMargins(10, 0, 10, 0)
        self.lines_layout.setSpacing(0)
        self.ticket_empty = _label(
            "Escanea o toca un producto para empezar la venta.", "ticketEmpty"
        )
        self.ticket_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ticket_empty.setWordWrap(True)
        self.lines_layout.addWidget(self.ticket_empty)
        self.lines_layout.addStretch()
        self.lines_scroll.setWidget(host)
        layout.addWidget(self.lines_scroll, 1)

        layout.addWidget(self._build_total_band())
        layout.addWidget(self._build_checkout())
        layout.addWidget(self._build_actions())
        return container

    def _build_total_band(self) -> QWidget:
        wrapper = QWidget()
        wrap_layout = QVBoxLayout(wrapper)
        wrap_layout.setContentsMargins(12, 10, 12, 0)
        band = QFrame()
        band.setObjectName("checkoutSummary")
        wrap_layout.addWidget(band)
        layout = QVBoxLayout(band)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(2)
        top = QHBoxLayout()
        caption = _label("Total a cobrar", "heroCaption")
        caption_font = QFont(caption.font())
        caption_font.setCapitalization(QFont.Capitalization.AllUppercase)
        caption_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
        caption.setFont(caption_font)
        self.cart_count = _label("0 artículos", "cartCount")
        top.addWidget(caption)
        top.addStretch()
        top.addWidget(self.cart_count)
        self.total_label = _label(self._money(0), "totalLabel")
        self.subtotal_label = _label("", "checkoutDetail")
        self.tax_label = _label("", "checkoutDetail")
        details = QHBoxLayout()
        details.setSpacing(14)
        details.addWidget(self.subtotal_label)
        details.addWidget(self.tax_label)
        details.addStretch()
        layout.addLayout(top)
        layout.addWidget(self.total_label)
        layout.addLayout(details)
        return wrapper

    def _build_checkout(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(12, 10, 12, 0)
        layout.setSpacing(8)
        self._checkout_layout = layout
        self.method_control = self._new_method_control()
        layout.addWidget(self.method_control)

        self.cash_panel = QWidget()
        cash = QVBoxLayout(self.cash_panel)
        cash.setContentsMargins(0, 0, 0, 0)
        cash.setSpacing(8)
        boxes = QHBoxLayout()
        boxes.setSpacing(8)
        recv = QFrame()
        recv.setObjectName("recvBox")
        recv.setFixedHeight(56)
        recv_layout = QVBoxLayout(recv)
        recv_layout.setContentsMargins(14, 6, 14, 6)
        recv_layout.setSpacing(0)
        self.received_edit = QLineEdit()
        self.received_edit.setObjectName("recvInput")
        self.received_edit.setAccessibleName("Efectivo recibido")
        self.received_edit.setPlaceholderText(self._amount_placeholder())
        self.received_edit.textChanged.connect(self._on_received_changed)
        recv_layout.addWidget(_label("Recibido", "recvCaption"))
        recv_layout.addWidget(self.received_edit)
        change = QFrame()
        change.setObjectName("inlineChange")
        change.setFixedHeight(56)
        change_layout = QVBoxLayout(change)
        change_layout.setContentsMargins(14, 6, 14, 6)
        change_layout.setSpacing(0)
        self.change_value = _label(self._money(0), "inlineChangeValue")
        change_layout.addWidget(_label("Cambio", "inlineChangeCaption"))
        change_layout.addWidget(self.change_value)
        boxes.addWidget(recv, 1)
        boxes.addWidget(change, 1)
        cash.addLayout(boxes)
        bills = QHBoxLayout()
        bills.setSpacing(6)
        self.bill_buttons: list[QPushButton] = []
        for index in range(4):
            button = QPushButton()
            button.setObjectName("billChip")
            button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            button.setAutoDefault(False)
            button.clicked.connect(lambda _checked=False, bill=index: self._pick_bill(bill))
            self.bill_buttons.append(button)
            bills.addWidget(button, 1)
        cash.addLayout(bills)
        layout.addWidget(self.cash_panel)

        self.reference_edit = QLineEdit()
        self.reference_edit.setObjectName("referenceEdit")
        self.reference_edit.setAccessibleName("Referencia de transferencia")
        self.reference_edit.setPlaceholderText("Referencia de la transferencia")
        self.reference_edit.textChanged.connect(self._on_reference_edited)
        layout.addWidget(self.reference_edit)
        self.sales_note_edit = QLineEdit()
        self.sales_note_edit.setObjectName("salesNoteEdit")
        self.sales_note_edit.setAccessibleName("N.º de nota de venta")
        self.sales_note_edit.setPlaceholderText("N.º de nota de venta (opcional)")
        self.sales_note_edit.setMaxLength(SALES_NOTE_MAX_LENGTH)
        self.sales_note_edit.setVisible(self.tax_regime == SALES_NOTE_REGIME)
        layout.addWidget(self.sales_note_edit)
        self.print_switch = SwitchButton("Imprimir ticket")
        self.print_switch.setObjectName("printSwitch")
        self.print_switch.setChecked(True)
        self.print_switch.setVisible(self.can_print_ticket)
        self.print_switch.toggled.connect(self._refresh_charge_label)
        self.buyer_section = BuyerSection()
        self.buyer_section.set_invoicing(self.invoicing_active)
        layout.addWidget(self.buyer_section)
        layout.addWidget(self.print_switch)
        self.checkout_message = InlineMessage()
        layout.addWidget(self.checkout_message)
        self._on_method_selected(self.method_control.current or "")
        return wrapper

    def _build_actions(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(6)
        self.charge_button = QPushButton()
        self.charge_button.setObjectName("chargeButton")
        set_variant(self.charge_button, "champagne")
        self.charge_button.setToolTip("Cobrar la venta (F4)")
        self.charge_button.clicked.connect(lambda: self.confirm_sale())
        self.charge_amount = QLabel(self._money(0))
        self.charge_hint = KeyHint("F4")
        _overlay_row(self.charge_button, self.charge_amount, self.charge_hint)
        self.split_button = QPushButton("Dividir pago")
        self.split_button.setObjectName("splitButton")
        set_variant(self.split_button, "secondary")
        self.split_button.setToolTip("Cobrar con varias formas de pago (F9)")
        self.split_button.clicked.connect(lambda: self.open_split_payment())
        self.split_hint = KeyHint("F9")
        _overlay_row(self.split_button, self.split_hint)
        self.reprint_button = QPushButton("Reimprimir último ticket")
        self.reprint_button.setObjectName("reprintButton")
        set_variant(self.reprint_button, "ghost")
        self.reprint_button.setToolTip("Reimprimir el último ticket (Ctrl+P)")
        self.reprint_button.clicked.connect(lambda: self.reprint_last_ticket())
        _overlay_row(self.reprint_button, KeyHint("Ctrl+P"))
        self.reprint_button.setVisible(self.can_print_ticket)
        layout.addWidget(self.charge_button)
        layout.addWidget(self.split_button)
        layout.addWidget(self.reprint_button)
        self._refresh_charge_label()
        return wrapper

    def _refresh_charge_label(self, _checked: bool = False) -> None:
        prints = self.can_print_ticket and self.print_switch.isChecked()
        self.charge_button.setText("Cobrar e imprimir" if prints else "Cobrar")

    def _install_shortcuts(self) -> None:
        scope = Qt.ShortcutContext.WidgetWithChildrenShortcut
        bindings: list[tuple[str, Callable[[], object]]] = [
            ("Ctrl+Return", self.charge_button.click),
            ("Ctrl+Enter", self.charge_button.click),
            ("F4", self.charge_button.click),
            ("F9", self.split_button.click),
            ("Ctrl+P", self.reprint_button.click),
            ("Delete", self.remove_selected_line),
            ("F2", self._on_f2),
        ]
        for index in range(QUICK_KEY_COUNT):
            bindings.append((str(index + 1), lambda key=index: self.add_quick_product(key)))
        for sequence, slot in bindings:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(scope)
            shortcut.activated.connect(slot)

    # -- events and layout --------------------------------------------------------------

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.search_input and isinstance(event, QKeyEvent):
            if event.type() == QEvent.Type.KeyPress:
                key = Qt.Key(event.key())
                step = {Qt.Key.Key_Down: 1, Qt.Key.Key_Up: -1}.get(key)
                if step is not None:
                    self._move_product_selection(step)
                    return True
                if key == Qt.Key.Key_Delete and not self.search_input.text():
                    # Nothing to delete in an empty scanner, so the key drops the ticket line.
                    self.remove_selected_line()
                    return True
                self._arm_quick_key(event)
        return super().eventFilter(watched, event)

    def _arm_quick_key(self, event: QKeyEvent) -> None:
        """A lone 1-6 in the empty scanner becomes a quick key unless more keys follow.

        Barcodes and the ``3*`` prefix start with digits too, so the digit is typed normally and
        only counts as a quick key when it is still alone after a short pause.
        """
        digit = DIGIT_KEYS.get(Qt.Key(event.key()))
        plain = not event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        if digit is None or not plain or event.isAutoRepeat() or self.search_input.text():
            return
        self._quick_digit = digit
        self._quick_timer.start(self.quick_key_delay_ms)

    def _fire_quick_key(self) -> None:
        if self._quick_digit and self.search_input.text() == str(self._quick_digit):
            self.search_input.clear()
            self.add_quick_product(self._quick_digit - 1)

    def _on_f2(self) -> None:
        """F2 returns to the scanner; pressed inside the scanner it edits the line quantity."""
        if self.search_input.hasFocus():
            self.edit_selected_quantity()
        else:
            self.search_input.setFocus(Qt.FocusReason.ShortcutFocusReason)
            self.search_input.selectAll()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.refresh_kpis()
        if self._refresh_category_filter():
            self.refresh_products()

    # -- business profile ---------------------------------------------------------------

    def _money(self, cents: int) -> str:
        return format_money(cents, self.currency_symbol, self.decimal_separator)

    def _amount_placeholder(self) -> str:
        return f"0{self.decimal_separator}00"

    def _new_method_control(self) -> SegmentedControl:
        labels = [METHOD_LABELS[method] for method in self.enabled_payment_methods]
        control = SegmentedControl(labels)
        # Payment methods share the ticket width instead of forcing it to fit their full text.
        for segment in control.findChildren(QPushButton):
            segment.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        control.selected.connect(self._on_method_selected)
        return control

    def _categories_with_products(self) -> dict[str, int]:
        """Active categories that have at least one active product, by name, when enabled."""
        if "categorias" not in self.enabled_modules or not self.categories:
            return {}
        used = {product.category_id for product in self.products.find_active("")}
        reserved = {FILTER_ALL, FILTER_LOW_STOCK}
        return {
            category.name: category.id
            for category in self.categories
            if category.active and category.id in used and category.name not in reserved
        }

    def _filter_options(self) -> list[str]:
        return [FILTER_ALL, *self._category_ids, FILTER_LOW_STOCK]

    def _new_filter_control(self, current: str | None = None) -> SegmentedControl:
        control = SegmentedControl(self._filter_options(), current)
        control.selected.connect(self._on_filter_selected)
        return control

    def _refresh_category_filter(self) -> bool:
        """Rebuild the filter when its options changed; True when the catalog must reload."""
        category_ids = self._categories_with_products()
        if list(category_ids) == list(self._category_ids) and category_ids == self._category_ids:
            return False
        selected = self.filter_control.current
        self._category_ids = category_ids
        old = self.filter_control
        self.filter_control = self._new_filter_control(selected)
        self._filter_row.removeWidget(old)
        old.hide()
        old.deleteLater()
        self._filter_row.insertWidget(0, self.filter_control)
        return True

    def apply_business(self, business: BusinessSettings, categories: Sequence[Category]) -> None:
        """Adopt saved business settings without rebuilding the screen."""
        methods_changed = (business.enabled_payment_methods or ("cash",)) != (
            self.enabled_payment_methods
        )
        self.currency_symbol = business.currency_symbol
        self.decimal_separator = business.decimal_separator
        self.low_stock_threshold = business.low_stock_threshold
        self.enabled_modules = business.enabled_modules
        self.categories = tuple(categories)
        self.tax_regime = business.tax_regime
        self.einvoicing_enabled = business.einvoice_enabled and issues_electronic_invoices(
            business.tax_regime
        )
        self.buyer_section.set_invoicing(self.invoicing_active)
        self.sales_note_edit.setVisible(self.tax_regime == SALES_NOTE_REGIME)
        if methods_changed:
            self.enabled_payment_methods = business.enabled_payment_methods or ("cash",)
            old = self.method_control
            self.method_control = self._new_method_control()
            self._checkout_layout.removeWidget(old)
            old.hide()
            old.deleteLater()
            self._checkout_layout.insertWidget(0, self.method_control)
            self._on_method_selected(self.method_control.current or "")
        self._refresh_category_filter()
        self.received_edit.setPlaceholderText(self._amount_placeholder())
        self.refresh_products()
        self.refresh_quick_keys()
        self.refresh_kpis()
        self.refresh_cart()

    def _on_filter_selected(self, _option: str) -> None:
        self.refresh_products()

    def _on_reference_edited(self, _text: str) -> None:
        self.checkout_message.clear_message()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._relayout(self.width())

    def _relayout(self, width: int) -> None:
        compact = width < COMPACT_BELOW_WIDTH
        if compact != self._compact or self.ticket_container.minimumWidth() == 0 and not compact:
            self._compact = compact
            self._root.setDirection(
                QBoxLayout.Direction.TopToBottom if compact else QBoxLayout.Direction.LeftToRight
            )
            if compact:
                self.ticket_container.setMinimumWidth(0)
                self.ticket_container.setMaximumWidth(16_777_215)
                self.ticket_container.setMinimumHeight(600)
            else:
                self.ticket_container.setMinimumHeight(0)
                self.ticket_container.setMaximumHeight(16_777_215)
        narrow = not compact and width < NARROW_BELOW_WIDTH
        if not compact:
            self.ticket_container.setFixedWidth(
                TICKET_COLUMN_NARROW_WIDTH if narrow else TICKET_COLUMN_WIDTH
            )
        for secondary in (self.reader_status, self.quantity_hint, self.kpi_average_tile):
            secondary.setVisible(not narrow)

    def _apply_theme(self, _name: str = "") -> None:
        """Redraw what is painted in Python; the stylesheet already carries every color."""
        self.scan_icon.setPixmap(icon("barcode", current_tokens().brand_500, 28).pixmap(28, 28))

    # -- catalog ------------------------------------------------------------------------

    def refresh_products(self) -> None:
        products = self.products.find_active(self._scan_query())
        selected = self.filter_control.current
        if selected == FILTER_LOW_STOCK:
            products = [p for p in products if p.stock <= self.low_stock_threshold]
        elif selected in self._category_ids:
            products = [p for p in products if p.category_id == self._category_ids[selected]]
        self.product_empty.setVisible(not products)
        self.product_list.setVisible(bool(products))
        self.product_list.set_products(
            products,
            self._cart_quantities(),
            self.currency_symbol,
            self.low_stock_threshold,
            lambda cents, symbol: format_money(cents, symbol, self.decimal_separator),
        )

    def refresh_quick_keys(self) -> None:
        """Quick keys 1-6 point at the first six products of the catalog (alphabetical)."""
        catalog = self.products.find_active("")[:QUICK_KEY_COUNT]
        self._quick_products = [*catalog, *[None] * (QUICK_KEY_COUNT - len(catalog))]
        for index, product in enumerate(self._quick_products):
            button = self.quick_buttons[index]
            button.setEnabled(product is not None)
            name = product.name if product else "—"
            price = self._money(product.price_cents) if product else ""
            self._quick_names[index].setText(name)
            self._quick_prices[index].setText(price)
            button.setProperty("productName", name)
            button.setProperty("priceText", price)
            button.setAccessibleName(f"Tecla {index + 1}: {name} {price}".strip())

    def refresh_kpis(self) -> None:
        count, revenue = self.sales.today_summary()
        self.kpi_sales.setText(str(count))
        self.kpi_revenue.setText(self._money(revenue))
        average = self._money(revenue // count) if count else "—"
        self.kpi_average.setText(average)

    def _cart_quantities(self) -> dict[int, int]:
        return {line.product.id: line.quantity for line in self.cart.lines}

    def _move_product_selection(self, step: int) -> None:
        count = self.product_list.count()
        if count == 0:
            return
        row = min(max(self.product_list.currentRow() + step, 0), count - 1)
        self.product_list.setCurrentRow(row)

    # -- scanner ------------------------------------------------------------------------

    @staticmethod
    def normalize_scan_value(value: str) -> str:
        return value.replace("\r", "").replace("\n", "").strip()

    def _scan_query(self) -> str:
        text = self.normalize_scan_value(self.search_input.text())
        match = QUANTITY_PREFIX.match(text)
        return match.group(2).strip() if match else text

    @property
    def multiplier(self) -> int:
        """Units the next add will put in the cart: typed ``N*`` prefix, else an armed one."""
        return self._typed_quantity or self._armed_quantity

    def _update_quantity_hint(self) -> None:
        self.quantity_hint.setText(f"Cantidad ×{self.multiplier} · 3* multiplica")

    def _on_scan_text_changed(self, value: str) -> None:
        empty = not value
        if empty != self._empty_input:
            self._empty_input = empty
            self.search_input.setProperty("empty", empty)
            repolish(self.search_input)
        match = QUANTITY_PREFIX.match(value)
        quantity = int(match.group(1)) if match else 0
        self._typed_quantity = quantity if quantity >= 1 else None
        self._update_quantity_hint()
        if empty:
            self._set_status("", "default")
        self.refresh_products()

    def _on_scan_submitted(self) -> None:
        match = QUANTITY_PREFIX.match(self.search_input.text())
        if match and not match.group(2).strip():
            # "3*" on its own arms the next scan instead of adding whatever is selected.
            self._armed_quantity = max(1, int(match.group(1)))
            self.search_input.clear()
            return
        self.add_selected_product()

    def _set_status(self, text: str, state: str) -> None:
        self.scanner_status.setText(text)
        self.scanner_status.setProperty("state", state)
        repolish(self.scanner_status)

    # -- cart ---------------------------------------------------------------------------

    def add_selected_product(self) -> None:
        product = self.product_list.product_at(self.product_list.currentRow())
        if product is None:
            query = self._scan_query()
            self._set_status(
                f"No encontramos un producto con el código o texto «{query}»."
                if query
                else "Escribe o escanea un código para agregar un producto.",
                "error",
            )
            return
        self._add_product(product)

    def add_quick_product(self, index: int) -> None:
        if 0 <= index < QUICK_KEY_COUNT and (product := self._quick_products[index]) is not None:
            self._add_product(product)

    def _on_product_chosen(self, product: object) -> None:
        if isinstance(product, Product):
            self._add_product(product)

    def _add_product(self, product: Product) -> bool:
        quantity = self.multiplier
        line = next((line for line in self.cart.lines if line.product.id == product.id), None)
        before = line.quantity if line else 0
        try:
            self.cart.add(product)
            if quantity > 1:
                self.cart.set_quantity(product.id, before + quantity)
        except ValueError as error:
            if before:
                self.cart.set_quantity(product.id, before)
            else:
                self.cart.remove(product.id)
            self.notification.emit(f"No se puede agregar. {error}", "danger")
            self._set_status(str(error), "error")
            return False
        self._selected_id = product.id
        self._armed_quantity = 1
        self.search_input.clear()
        self.refresh_cart()
        self._set_status(
            f"{product.name} agregado a la venta."
            if quantity == 1
            else f"{quantity} × {product.name} agregados a la venta.",
            "success",
        )
        self.search_input.setFocus()
        return True

    def _line_for(self, product_id: int | None):  # noqa: ANN202 - CartLine is not exported
        return next((line for line in self.cart.lines if line.product.id == product_id), None)

    def remove_selected_line(self) -> None:
        if self._selected_id is None:
            return
        self.cart.remove(self._selected_id)
        self.refresh_cart()

    def edit_selected_quantity(self) -> None:
        line = self._line_for(self._selected_id)
        if line is None:
            return
        quantity, accepted = QInputDialog.getInt(
            self,
            "Editar cantidad",
            f"Cantidad de {line.product.name}:",
            line.quantity,
            1,
            line.product.stock,
        )
        if not accepted:
            return
        try:
            self.cart.set_quantity(line.product.id, quantity)
        except ValueError as error:
            self.notification.emit(f"No se puede cambiar la cantidad. {error}", "danger")
            return
        self.refresh_cart()

    def _on_line_selected(self, product_id: int) -> None:
        self._selected_id = product_id
        for line in self.ticket_lines:
            line.set_highlighted(line.product_id == product_id)

    def _on_step(self, product_id: int, step: int) -> None:
        line = self._line_for(product_id)
        if line is None:
            return
        quantity = line.quantity + step
        try:
            if quantity <= 0:
                self.cart.remove(product_id)
            else:
                self.cart.set_quantity(product_id, quantity)
        except ValueError as error:
            self.notification.emit(f"No se puede cambiar la cantidad. {error}", "danger")
            return
        self._selected_id = product_id
        self.refresh_cart()
        self.search_input.setFocus()

    def refresh_cart(self) -> None:
        for widget in self.ticket_lines:
            self.lines_layout.removeWidget(widget)
            widget.hide()
            widget.deleteLater()
        self.ticket_lines = []
        lines = self.cart.lines
        ids = [line.product.id for line in lines]
        if self._selected_id not in ids:
            self._selected_id = ids[-1] if ids else None
        for index, line in enumerate(lines):
            widget = TicketLine(
                line.product,
                line.quantity,
                self._money(line.product.price_cents),
                self._money(line.total_cents),
                line.product.id == self._selected_id,
            )
            widget.selected.connect(self._on_line_selected)
            widget.quantity_step.connect(self._on_step)
            self.lines_layout.insertWidget(index, widget)
            self.ticket_lines.append(widget)
        self.ticket_empty.setVisible(not lines)
        self.total_label.setText(self._money(self.cart.grand_total_cents))
        self.subtotal_label.setText(f"Subtotal {self._money(self.cart.subtotal_cents)}")
        self.tax_label.setText(f"IVA incluido {self._money(self.cart.tax_cents)}")
        item_count = sum(line.quantity for line in lines)
        self.cart_count.setText(f"{item_count} artículo{'s' if item_count != 1 else ''}")
        self.product_list.update_quantities(self._cart_quantities())
        self._refresh_checkout()

    # -- inline checkout ----------------------------------------------------------------

    def _on_method_selected(self, label: str) -> None:
        self._method = next(
            (method for method, text in METHOD_LABELS.items() if text == label), self._method
        )
        self.cash_panel.setVisible(self._method == "cash")
        self.reference_edit.setVisible(self._method == "transfer")
        self.checkout_message.clear_message()

    def _received_cents(self) -> int:
        try:
            return parse_money(self.received_edit.text())
        except ValueError:
            return 0

    def _on_received_changed(self, _text: str) -> None:
        self.checkout_message.clear_message()
        self._refresh_checkout()

    def _pick_bill(self, index: int) -> None:
        if index < len(self._bill_amounts):
            self.received_edit.setText(f"{Decimal(self._bill_amounts[index]) / 100:.2f}")

    def _refresh_checkout(self) -> None:
        total = self.cart.grand_total_cents
        received = self._received_cents()
        self.change_value.setText(self._money(max(0, received - total)))
        self.charge_amount.setText(self._money(total))
        self.charge_button.setEnabled(bool(self.cart.lines))
        self.buyer_section.set_total(total)
        self._bill_amounts = [total, *quick_bill_amounts(total)] if total else []
        for index, button in enumerate(self.bill_buttons):
            has_amount = index < len(self._bill_amounts)
            button.setEnabled(has_amount)
            button.setText(
                "Exacto"
                if index == 0
                else self._money(self._bill_amounts[index])
                if has_amount
                else ""
            )
            button.setProperty("selected", has_amount and received == self._bill_amounts[index])
            repolish(button)

    def _inline_payments(self) -> tuple[Payment, ...] | None:
        """The single payment typed in the checkout, or None after showing why it is invalid."""
        total = self.cart.grand_total_cents
        if self._method == "cash":
            received = self._received_cents()
            if received < total:
                self.checkout_message.show_error("El efectivo recibido no cubre el total.")
                return None
            return (Payment("cash", received),)
        if self._method == "transfer":
            reference = self.reference_edit.text().strip()
            if not reference:
                self.checkout_message.show_error(
                    "La transferencia necesita un número de referencia."
                )
                return None
            return (Payment("transfer", total, reference),)
        return (Payment(self._method, total),)

    @property
    def invoicing_active(self) -> bool:
        """True when sales are invoiced: the module is on and issuing and printing are wired."""
        return self.einvoicing_enabled and self._invoice_checkout is not None

    def confirm_sale(
        self,
        payments: tuple[Payment, ...] | None = None,
        print_ticket: bool | None = None,
        buyer: Buyer | None = None,
    ) -> None:
        """Register the sale; without ``payments`` the inline checkout supplies the payment.

        The ticket is printed after the sale is saved when ``print_ticket`` (the dialog's switch)
        or, by default, the inline "Imprimir ticket" switch says so. A printing failure only
        warns: the sale stays registered.

        While invoicing is active the buyer is validated before charging (``buyer`` comes from
        the split dialog, which validated it) and, once the sale is saved, its electronic invoice
        is issued and its RIDE printed in place of the internal ticket.
        """
        if print_ticket is None:
            print_ticket = self.print_switch.isChecked()
        if payments is None:
            if not self.cart.lines:
                self.notification.emit("No se puede cobrar. Agrega al menos un producto.", "danger")
                return
            payments = self._inline_payments()
            if payments is None:
                return
        if self.invoicing_active and buyer is None:
            buyer = self.buyer_section.buyer(self.cart.grand_total_cents)
            if buyer is None:
                return
        try:
            sale = self.cart.to_sale(payments)
            sale_id = self.sales.register(
                sale,
                business_id=None if self.session is None else self.session.user.business_id,
                user_id=None if self.session is None else self.session.user.id,
                sales_note_number=self._sales_note_number(),
            )
        except (ValueError, SaleError) as error:
            self.notification.emit(f"No se puede confirmar. {error}", "danger")
            return
        change = self._money(sale.change_cents) if sale.change_cents else "No aplica"
        self.notification.emit(
            f"Venta N.º {sale_id} registrada · "
            f"Total {self._money(sale.total_cents)} · "
            f"Vuelto: {change}",
            "success",
        )
        self.last_sale_id = sale_id
        self._reset_after_sale()
        self.sale_registered.emit()
        if self._invoice_checkout is not None and self.invoicing_active and buyer is not None:
            self._invoice_checkout.complete(sale_id, buyer, print_ticket)
            self.invoice_issued.emit()
        elif print_ticket:
            self._print_receipt(sale_id)

    def _sales_note_number(self) -> str | None:
        """What the cashier typed, only for the regime that keeps handwritten sales notes."""
        return self.sales_note_edit.text() if self.tax_regime == SALES_NOTE_REGIME else None

    def _print_receipt(self, sale_id: int) -> bool:
        """Print the stored sale; on any failure warn and leave the sale untouched."""
        if self._invoice_checkout is not None and self.invoicing_active:
            return self._invoice_checkout.print_sale(sale_id)
        if self.session is None or self.receipts is None or self.receipt_output is None:
            return False
        try:
            self.receipt_output.print_receipt(self.receipts.build(self.session, sale_id))
        except Exception as error:  # printer drivers raise anything
            self.notification.emit(f"No se pudo imprimir el ticket: {error}", "warning")
            return False
        return True

    def reprint_last_ticket(self) -> bool:
        """Print again the last sale registered on this screen (Ctrl+P)."""
        if not self.can_print_ticket:
            return False
        if self.last_sale_id is None:
            self.notification.emit("Todavía no hay un ticket para reimprimir.", "info")
            return False
        return self._print_receipt(self.last_sale_id)

    def _reset_after_sale(self) -> None:
        self.cart.clear()
        self._selected_id = None
        self._armed_quantity = 1
        self.received_edit.clear()
        self.reference_edit.clear()
        self.sales_note_edit.clear()
        self.buyer_section.reset()
        self.checkout_message.clear_message()
        self.search_input.clear()
        self.refresh_cart()
        self.refresh_products()
        self.refresh_quick_keys()
        self.refresh_kpis()
        self.search_input.setFocus()

    def open_split_payment(self) -> None:
        """Collect several payments in the dialog and, when accepted, charge with them."""
        payments = self._collect_payments()
        if payments is not None:
            self.confirm_sale(payments, self.last_print_ticket, self.last_buyer)

    def _collect_payments(self) -> tuple[Payment, ...] | None:
        """Open the payment dialog; return its payments, or None when the cashier cancels."""
        if not self.cart.lines:
            self.notification.emit("No se puede cobrar. Agrega al menos un producto.", "danger")
            return None
        note = f"IVA incluido {self._money(self.cart.tax_cents)}" if self.cart.tax_cents else ""
        # Only an active invoicing run hands the dialog its Comprobante section.
        invoicing: dict[str, object] = (
            {"invoicing": True, "buyer_draft": self.buyer_section.draft()}
            if self.invoicing_active
            else {}
        )
        dialog = self.payment_dialog_factory(
            total_cents=self.cart.grand_total_cents,
            currency_symbol=self.currency_symbol,
            decimal_separator=self.decimal_separator,
            enabled_methods=self.enabled_payment_methods,
            sale_label=self.sale_label,
            total_note=note,
            validate=self.cart.to_sale,
            parent=self,
            **invoicing,
        )
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        payments = dialog.payments
        self.last_print_ticket = dialog.print_ticket
        self.last_buyer = dialog.buyer if self.invoicing_active else None
        dialog.deleteLater()
        return payments if accepted and payments else None
