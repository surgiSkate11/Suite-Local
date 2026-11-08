from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QFont, QKeyEvent, QShowEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from suitelocal.domain.einvoice import Buyer
from suitelocal.domain.models import PAYMENT_METHODS, Payment, Sale, SaleItem
from suitelocal.domain.money import format_usd
from suitelocal.ui.components import InlineMessage, PrimaryButton, SwitchButton
from suitelocal.ui.components.buyer_section import BuyerDraft, BuyerSection
from suitelocal.ui.theme.icons import ICONS, icon
from suitelocal.ui.theme.manager import current_tokens

ICONS.setdefault("transfer", '<path d="M7 7h13l-3-3M17 17H4l3 3"/>')
ICONS.setdefault("card", '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/>')

METHOD_LABELS = {"cash": "Efectivo", "transfer": "Transferencia", "card": "Tarjeta"}
MAX_CASH_UNITS = 99_999_999
QUICK_BILL_MULTIPLIERS = (1, 5, 10, 20, 50, 100, 200, 500, 1000)
QUICK_BILL_COUNT = 3

PaymentValidator = Callable[[tuple[Payment, ...]], object]


def format_money(cents: int, currency_symbol: str = "$", decimal_separator: str = ",") -> str:
    """Format cents for the screen, e.g. "$ 1.234,56"; delegates to the Qt-free formatter."""
    text = format_usd(cents, decimal_separator)
    return text if currency_symbol == "$" else text.replace("$", currency_symbol, 1)


def parse_money(value: str) -> int:
    value = value.strip().replace(",", ".")
    if not value:
        raise ValueError("Ingresa el monto del pago.")
    try:
        amount = int((Decimal(value) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except InvalidOperation as error:
        raise ValueError("El pago debe ser un número válido.") from error
    if amount <= 0:
        raise ValueError("El pago debe ser mayor que cero.")
    return amount


def quick_bill_amounts(due_cents: int) -> list[int]:
    """Round amounts strictly above ``due_cents``, scaled to the magnitude of the due amount."""
    units = max(1, -(-due_cents // 100))
    step = 10 ** (len(str(units)) - 1) * 100
    amounts: list[int] = []
    for multiplier in QUICK_BILL_MULTIPLIERS:
        size = step * multiplier
        candidate = (due_cents // size + 1) * size
        if not amounts or candidate > amounts[-1]:
            amounts.append(candidate)
        if len(amounts) == QUICK_BILL_COUNT:
            break
    return amounts


def method_icon_color(method: str) -> str:
    """Icon color of a payment method in the active theme (read at paint time, not import)."""
    tokens = current_tokens()
    return {
        "cash": tokens.champagne_text,
        "transfer": tokens.brand_800,
        "card": tokens.success,
    }.get(method, tokens.brand_800)


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class PaymentRow(QFrame):
    """One line of the split-payment list: method, subtitle, amount and status chip."""

    def __init__(
        self,
        method: str,
        subtitle: str,
        amount_text: str,
        received: bool,
        active: bool,
        removable: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.method = method
        self.setObjectName("paymentRow")
        self.setProperty("active", active)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(14)
        badge = QLabel()
        badge.setObjectName("paymentIcon")
        badge.setProperty("method", method)
        badge.setFixedSize(44, 44)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setPixmap(icon(method, method_icon_color(method), 22).pixmap(22, 22))
        texts = QVBoxLayout()
        texts.setSpacing(2)
        title = QLabel(METHOD_LABELS.get(method, method))
        title.setObjectName("paymentRowTitle")
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("paymentRowSubtitle")
        texts.addWidget(title)
        texts.addWidget(self.subtitle_label)
        self.amount_label = QLabel(amount_text)
        self.amount_label.setObjectName("paymentRowAmount")
        self.status_label = QLabel("Recibido" if received else "En curso")
        self.status_label.setObjectName("paymentState")
        self.status_label.setProperty("state", "received" if received else "pending")
        layout.addWidget(badge)
        layout.addLayout(texts, 1)
        layout.addWidget(self.amount_label)
        layout.addWidget(self.status_label)
        self.remove_button: QPushButton | None = None
        if removable:
            self.remove_button = QPushButton()
            self.remove_button.setObjectName("paymentRemove")
            self.remove_button.setIcon(icon("close", current_tokens().text_500, 14))
            self.remove_button.setFixedSize(28, 28)
            self.remove_button.setAccessibleName("Quitar pago")
            self.remove_button.setToolTip("Quitar pago")
            self.remove_button.setAutoDefault(False)
            layout.addWidget(self.remove_button)


class PaymentDialog(QDialog):
    """Modal checkout: split payments on the left, cash tender and confirmation on the right."""

    WIDTH = 980
    HEIGHT = 700

    def __init__(
        self,
        total_cents: int,
        currency_symbol: str = "$",
        enabled_methods: tuple[str, ...] = ("cash", "transfer"),
        sale_label: str = "",
        total_note: str = "",
        validate: PaymentValidator | None = None,
        parent: QWidget | None = None,
        decimal_separator: str = ",",
        invoicing: bool = False,
        buyer_draft: BuyerDraft | None = None,
    ) -> None:
        super().__init__(parent)
        self.total_cents = total_cents
        self.currency_symbol = currency_symbol
        self.decimal_separator = decimal_separator
        self.payments: tuple[Payment, ...] = ()
        # Who the electronic invoice goes to; only set when invoicing and the data are valid.
        self.buyer: Buyer | None = None
        self.invoicing = invoicing
        self.buyer_section = BuyerSection()
        self.buyer_section.set_total(total_cents)
        if buyer_draft is not None:
            self.buyer_section.load(buyer_draft)
        self.buyer_section.set_invoicing(invoicing)
        self._enabled = tuple(
            method for method in PAYMENT_METHODS if method != "cash" and method in enabled_methods
        )
        self._validate = validate or self._validate_with_sale
        self._noncash: list[Payment] = []
        self._cash_cents = 0
        self._typing = False
        self._scrim: QWidget | None = None
        self.payment_rows: list[PaymentRow] = []
        self.rows_scroll: QScrollArea | None = None
        self.setWindowTitle("Cobrar la venta")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        card = QFrame()
        card.setObjectName("paymentCard")
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)
        columns = QHBoxLayout(card)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(0)
        columns.addWidget(self._build_left(sale_label, total_note), 1)
        columns.addWidget(self._build_right())

        self.setTabOrder(self.close_button, self.add_button)
        self._refresh()
        self.setFocus()

    # -- construction -------------------------------------------------------------------

    def _build_left(self, sale_label: str, total_note: str) -> QWidget:
        left = QFrame()
        left.setObjectName("paymentLeft")
        layout = QVBoxLayout(left)
        layout.setContentsMargins(38, 34, 38, 30)
        layout.setSpacing(20)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(6)
        self.eyebrow_label = QLabel(sale_label)
        self.eyebrow_label.setObjectName("paymentEyebrow")
        eyebrow_font = QFont(self.eyebrow_label.font())
        eyebrow_font.setCapitalization(QFont.Capitalization.AllUppercase)
        eyebrow_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.4)
        self.eyebrow_label.setFont(eyebrow_font)
        self.eyebrow_label.setVisible(bool(sale_label))
        self.title_label = QLabel("Cobrar la venta")
        self.title_label.setObjectName("paymentTitle")
        titles.addWidget(self.eyebrow_label)
        titles.addWidget(self.title_label)
        self.close_button = QPushButton()
        self.close_button.setObjectName("paymentClose")
        self.close_button.setIcon(icon("close", current_tokens().text_700, 16))
        self.close_button.setFixedSize(40, 40)
        self.close_button.setAccessibleName("Cerrar sin cobrar")
        self.close_button.setToolTip("Cerrar sin cobrar (Esc)")
        self.close_button.setAutoDefault(False)
        self.close_button.clicked.connect(self.reject)
        header.addLayout(titles, 1)
        header.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        band = QFrame()
        band.setObjectName("paymentDue")
        band_layout = QHBoxLayout(band)
        band_layout.setContentsMargins(24, 20, 24, 20)
        caption = QVBoxLayout()
        caption.setSpacing(2)
        due_title = QLabel("Total a cobrar")
        due_title.setObjectName("paymentDueTitle")
        caption.addWidget(due_title)
        if total_note:
            note = QLabel(total_note)
            note.setObjectName("paymentDueNote")
            caption.addWidget(note)
        self.total_label = QLabel(self._money(self.total_cents))
        self.total_label.setObjectName("paymentDueAmount")
        band_layout.addLayout(caption)
        band_layout.addStretch()
        band_layout.addWidget(self.total_label)
        layout.addWidget(band)

        self.split_label = QLabel()
        self.split_label.setObjectName("paymentSectionLabel")
        layout.addWidget(self.split_label)
        self.rows_layout = QVBoxLayout()
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(10)
        rows_host = QWidget()
        rows_host.setObjectName("paymentRows")
        host_layout = QVBoxLayout(rows_host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(10)
        host_layout.addLayout(self.rows_layout)
        host_layout.addWidget(self._build_form())
        self.add_button = QPushButton("+ Agregar otra forma de pago")
        self.add_button.setObjectName("addPayment")
        self.add_button.setAutoDefault(False)
        self.add_button.clicked.connect(self._toggle_form)
        host_layout.addWidget(self.add_button)
        host_layout.addWidget(self.buyer_section)
        host_layout.addStretch()
        scroll = QScrollArea()
        scroll.setObjectName("paymentScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(rows_host)
        self.rows_scroll = scroll
        layout.addWidget(scroll, 1)

        self.message = InlineMessage()
        layout.addWidget(self.message)
        return left

    def _build_form(self) -> QWidget:
        self.form = QFrame()
        self.form.setObjectName("paymentForm")
        layout = QHBoxLayout(self.form)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)
        self.method_combo = QComboBox()
        self.method_combo.setAccessibleName("Forma de pago")
        self.method_combo.currentIndexChanged.connect(self._on_method_changed)
        self.amount_edit = QLineEdit()
        self.amount_edit.setAccessibleName("Monto del pago")
        self.amount_edit.setPlaceholderText("Monto")
        self.amount_edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.reference_edit = QLineEdit()
        self.reference_edit.setAccessibleName("Referencia de transferencia")
        self.reference_edit.setPlaceholderText("Referencia")
        submit = QPushButton("Agregar")
        submit.setObjectName("secondaryAction")
        submit.setAutoDefault(False)
        submit.clicked.connect(self._submit_form)
        for edit in (self.amount_edit, self.reference_edit):
            edit.installEventFilter(self)
        layout.addWidget(self.method_combo, 1)
        layout.addWidget(self.amount_edit, 1)
        layout.addWidget(self.reference_edit, 1)
        layout.addWidget(submit)
        self.form.hide()
        return self.form

    def _build_right(self) -> QWidget:
        right = QFrame()
        right.setObjectName("paymentRight")
        right.setFixedWidth(420)
        layout = QVBoxLayout(right)
        layout.setContentsMargins(30, 30, 30, 28)
        layout.setSpacing(12)

        self.cash_panel = QWidget()
        panel = QVBoxLayout(self.cash_panel)
        panel.setContentsMargins(0, 0, 0, 0)
        panel.setSpacing(12)
        label = QLabel("Efectivo recibido")
        label.setObjectName("paymentFieldLabel")
        self.cash_display = QLabel()
        self.cash_display.setObjectName("cashDisplay")
        self.cash_display.setAccessibleName("Efectivo recibido")
        self.cash_display.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.cash_display.setFixedHeight(76)
        panel.addWidget(label)
        panel.addWidget(self.cash_display)

        bills = QGridLayout()
        bills.setSpacing(8)
        self.quick_bill_buttons: list[QPushButton] = []
        for column in range(QUICK_BILL_COUNT + 1):
            button = QPushButton()
            button.setObjectName("billButton")
            button.setAutoDefault(False)
            button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            button.clicked.connect(lambda _checked=False, index=column: self._pick_bill(index))
            self.quick_bill_buttons.append(button)
            bills.addWidget(button, 0, column)
        panel.addLayout(bills)

        pad = QGridLayout()
        pad.setSpacing(8)
        self.pad_buttons: dict[str, QPushButton] = {}
        keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "00", "0", "⌫"]
        for index, key in enumerate(keys):
            button = QPushButton(key)
            button.setObjectName("padButton")
            button.setAutoDefault(False)
            button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            if key == "⌫":
                button.setAccessibleName("Borrar")
                button.setToolTip("Borrar (Retroceso)")
                button.clicked.connect(self._backspace)
            else:
                button.clicked.connect(lambda _checked=False, digits=key: self._type_digits(digits))
            self.pad_buttons[key] = button
            pad.addWidget(button, index // 3, index % 3)
        panel.addLayout(pad)
        layout.addWidget(self.cash_panel)

        change_box = QFrame()
        change_box.setObjectName("changeBox")
        change_layout = QHBoxLayout(change_box)
        change_layout.setContentsMargins(18, 14, 18, 14)
        change_title = QLabel("Cambio")
        change_title.setObjectName("changeLabel")
        self.change_value = QLabel()
        self.change_value.setObjectName("changeValue")
        change_layout.addWidget(change_title)
        change_layout.addStretch()
        change_layout.addWidget(self.change_value)
        layout.addWidget(change_box)

        self.print_switch = SwitchButton("Imprimir ticket al confirmar")
        self.print_switch.setChecked(True)
        layout.addWidget(self.print_switch)
        layout.addStretch()

        self.confirm_button = PrimaryButton("Confirmar cobro  ·  Enter")
        self.confirm_button.setProperty("size", "hero")
        self.confirm_button.setAccessibleName("Confirmar cobro")
        self.confirm_button.setDefault(True)
        self.confirm_button.clicked.connect(self.confirm)
        layout.addWidget(self.confirm_button)
        return right

    # -- state --------------------------------------------------------------------------

    @property
    def print_ticket(self) -> bool:
        return self.print_switch.isChecked()

    @property
    def noncash_cents(self) -> int:
        return sum(payment.amount_cents for payment in self._noncash)

    @property
    def remaining_cents(self) -> int:
        return max(0, self.total_cents - self.noncash_cents)

    @property
    def cash_cents(self) -> int:
        """Cash handed over; ignored once the other forms of payment already cover the total."""
        return self._cash_cents if self.remaining_cents > 0 else 0

    @property
    def change_cents(self) -> int:
        return max(0, self.cash_cents - self.remaining_cents)

    @property
    def covered(self) -> bool:
        return self.noncash_cents + self.cash_cents >= self.total_cents

    @property
    def payment_methods(self) -> tuple[str, ...]:
        """Non-cash methods that can still be added."""
        used = {payment.method for payment in self._noncash}
        return tuple(method for method in self._enabled if method not in used)

    def _build_payments(self) -> tuple[Payment, ...]:
        payments = list(self._noncash)
        if self.cash_cents > 0:
            payments.append(Payment("cash", self.cash_cents))
        return tuple(payments)

    def _validate_with_sale(self, payments: tuple[Payment, ...]) -> object:
        item = SaleItem(0, "Venta", 1, self.total_cents)
        return Sale((item,), sum(p.amount_cents for p in payments), payments)

    # -- actions ------------------------------------------------------------------------

    def add_payment(self, method: str, amount_cents: int, reference: str = "") -> bool:
        """Add a non-cash payment; on failure show a Spanish inline message and return False."""
        reference = reference.strip()
        error = ""
        if method not in self._enabled:
            error = "La forma de pago no está habilitada."
        elif method in {payment.method for payment in self._noncash}:
            error = "No se puede repetir una forma de pago."
        elif amount_cents <= 0:
            error = "El monto de cada pago debe ser mayor que cero."
        elif method == "transfer" and not reference:
            error = "La transferencia necesita un número de referencia."
        elif amount_cents > self.remaining_cents:
            error = "Los pagos no pueden superar el total sin efectivo."
        if error:
            self.message.show_error(error)
            return False
        self._noncash.append(Payment(method, amount_cents, reference))
        self.message.clear_message()
        self._refresh()
        return True

    def remove_payment(self, method: str) -> None:
        self._noncash = [payment for payment in self._noncash if payment.method != method]
        self.message.clear_message()
        self._refresh()

    def confirm(self) -> None:
        if not self.covered:
            return
        payments = self._build_payments()
        try:
            self._validate(payments)
        except ValueError as error:
            self.message.show_error(str(error))
            return
        if self.invoicing:
            buyer = self.buyer_section.buyer(self.total_cents)
            if buyer is None:
                if self.rows_scroll is not None:
                    self.rows_scroll.ensureWidgetVisible(self.buyer_section)
                return
            self.buyer = buyer
        self.payments = payments
        self.accept()

    def _type_digits(self, digits: str) -> None:
        units = self._cash_cents // 100 if self._typing else 0
        value = int(f"{units}{digits}")
        if value > MAX_CASH_UNITS:
            return
        self._cash_cents = value * 100
        self._typing = True
        self._after_cash_change()

    def _backspace(self) -> None:
        self._cash_cents = self._cash_cents // 100 // 10 * 100 if self._typing else 0
        self._after_cash_change()

    def _pick_bill(self, index: int) -> None:
        if index == 0:
            self._cash_cents = self.remaining_cents
        else:
            self._cash_cents = quick_bill_amounts(self.remaining_cents)[index - 1]
        self._typing = False
        self._after_cash_change()

    def _after_cash_change(self) -> None:
        self.message.clear_message()
        self._refresh()

    def _toggle_form(self) -> None:
        if self.form.isVisible():
            self.form.hide()
            self.setFocus()
            return
        self._fill_form()
        self.form.show()
        self.amount_edit.setFocus()
        self.amount_edit.selectAll()

    def _fill_form(self) -> None:
        self.method_combo.blockSignals(True)
        self.method_combo.clear()
        for method in self.payment_methods:
            self.method_combo.addItem(METHOD_LABELS[method], method)
        self.method_combo.blockSignals(False)
        units, cents = divmod(self.remaining_cents, 100)
        self.amount_edit.setText(f"{units}{self.decimal_separator}{cents:02d}")
        self.reference_edit.clear()
        self._on_method_changed()

    def _on_method_changed(self) -> None:
        self.reference_edit.setVisible(self.method_combo.currentData() == "transfer")

    def _submit_form(self) -> None:
        try:
            amount = parse_money(self.amount_edit.text())
        except ValueError as error:
            self.message.show_error(str(error))
            return
        method = self.method_combo.currentData()
        if not isinstance(method, str):
            return
        if self.add_payment(method, amount, self.reference_edit.text()):
            self.form.hide()
            self.setFocus()

    # -- rendering ----------------------------------------------------------------------

    def _money(self, cents: int) -> str:
        return format_money(cents, self.currency_symbol, self.decimal_separator)

    def _refresh(self) -> None:
        self.cash_display.setText(self._money(self.cash_cents))
        self.change_value.setText(self._money(self.change_cents))
        self.confirm_button.setEnabled(self.covered)
        self.cash_panel.setEnabled(self.remaining_cents > 0)
        self._refresh_bills()
        self._rebuild_rows()
        self.add_button.setVisible(bool(self.payment_methods))
        if not self.payment_methods:
            self.form.hide()
        elif self.form.isVisible():
            self._fill_form()

    def _refresh_bills(self) -> None:
        remaining = self.remaining_cents
        amounts = [remaining, *quick_bill_amounts(remaining)]
        for index, (button, amount) in enumerate(
            zip(self.quick_bill_buttons, amounts, strict=True)
        ):
            button.setText("Exacto" if index == 0 else self._money(amount))
            button.setProperty("selected", self._cash_cents == amount and self._cash_cents > 0)
            _repolish(button)

    def _rebuild_rows(self) -> None:
        for row in self.payment_rows:
            self.rows_layout.removeWidget(row)
            row.hide()
            row.deleteLater()
        self.payment_rows = []
        for payment in self._noncash:
            reference = f"ref. {payment.reference}" if payment.reference else "Pago recibido"
            row = PaymentRow(
                payment.method,
                reference,
                self._money(payment.amount_cents),
                received=True,
                active=False,
                removable=True,
            )
            if row.remove_button is not None:
                row.remove_button.clicked.connect(
                    lambda _checked=False, method=payment.method: self.remove_payment(method)
                )
            self.payment_rows.append(row)
        if self.remaining_cents > 0:
            cash_done = self.covered
            subtitle = (
                f"Recibido {self._money(self.cash_cents)}" if cash_done else "Restante por cobrar"
            )
            self.payment_rows.append(
                PaymentRow(
                    "cash",
                    subtitle,
                    self._money(self.remaining_cents),
                    received=cash_done,
                    active=not cash_done,
                    removable=False,
                )
            )
        for row in self.payment_rows:
            self.rows_layout.addWidget(row)
        count = len(self.payment_rows)
        self.split_label.setText(
            f"Pago dividido · {count} formas" if count > 1 else "Forma de pago"
        )

    # -- events -------------------------------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:
        modifiers = event.modifiers()
        blocked = (
            Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.AltModifier
            | Qt.KeyboardModifier.MetaModifier
        )
        text = event.text()
        if len(text) == 1 and text in "0123456789" and not modifiers & blocked:
            if self.cash_panel.isEnabled():
                self._type_digits(text)
            return
        if Qt.Key(event.key()) == Qt.Key.Key_Backspace:
            if self.cash_panel.isEnabled():
                self._backspace()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            watched in (self.amount_edit, self.reference_edit)
            and event.type() == QEvent.Type.KeyPress
            and isinstance(event, QKeyEvent)
            and Qt.Key(event.key()) in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        ):
            self._submit_form()
            return True
        return super().eventFilter(watched, event)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        parent = self.parentWidget()
        if parent is None or self._scrim is not None:
            return
        window = parent.window()
        self._scrim = QWidget(window)
        self._scrim.setObjectName("paymentScrim")
        self._scrim.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._scrim.setGeometry(window.rect())
        self._scrim.show()
        self._scrim.raise_()

    def done(self, result: int) -> None:
        if self._scrim is not None:
            self._scrim.hide()
            self._scrim.deleteLater()
            self._scrim = None
        super().done(result)
