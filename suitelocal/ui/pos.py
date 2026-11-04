from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QKeySequence, QResizeEvent, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from suitelocal.application.cart import Cart
from suitelocal.domain.models import Payment, SaleError
from suitelocal.infrastructure.repositories import ProductRepository, SaleRepository
from suitelocal.ui.components import DataTable, EmptyState, SearchField


def format_money(cents: int, currency_symbol: str = "$") -> str:
    amount = (Decimal(cents) / Decimal(100)).quantize(Decimal("0.01"))
    return f"{currency_symbol}{amount:,.2f}"


class PosWidget(QWidget):
    sale_registered = Signal()

    def __init__(
        self,
        products: ProductRepository,
        sales: SaleRepository,
        enabled_payment_methods: tuple[str, ...] = ("cash", "transfer"),
        currency_symbol: str = "$",
        tax_rate_basis_points: int = 0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.products = products
        self.sales = sales
        self.currency_symbol = currency_symbol
        self.cart = Cart(tax_rate_basis_points)
        self.tax_rate_basis_points = tax_rate_basis_points
        self.search_input = SearchField("Escribe o escanea un código...")
        self.search_input.setPlaceholderText("Busca o escanea el código del producto...")
        self.search_input.textChanged.connect(self.refresh_products)
        self.search_input.returnPressed.connect(self.add_selected_product)
        self.scanner_status = QLabel("Busca por nombre o escanea un código para agregar productos.")
        self.scanner_status.setObjectName("scannerStatus")
        self.scanner_status.setWordWrap(True)
        self.scanner_status.setMinimumWidth(0)
        self.search_input.textChanged.connect(self._on_scan_text_changed)

        self.product_list = QListWidget()
        self.product_list.setObjectName("productResults")
        self.product_list.itemDoubleClicked.connect(self.add_selected_product)
        self.product_empty = EmptyState(
            "Tu catálogo está listo",
            "Escribe un nombre o código para encontrar el producto que quieres vender.",
        )
        self.product_empty.hide()
        add_button = QPushButton("Agregar al carrito")
        add_button.setMinimumWidth(0)
        add_button.clicked.connect(self.add_selected_product)

        self.cart_table = DataTable(4, ["Producto", "Cantidad", "Precio", "Total"])
        self.cart_table.setObjectName("cartTable")
        self.cart_table.setHorizontalHeaderLabels(["Producto", "Cantidad", "Precio", "Total"])
        self.cart_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.cart_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        remove_button = QPushButton("Quitar seleccionado")
        remove_button.setObjectName("secondaryAction")
        remove_button.setMinimumWidth(0)
        remove_button.clicked.connect(self.remove_selected_line)

        self.total_label = QLabel("$0.00")
        self.total_label.setObjectName("totalLabel")
        self.payment_status = QLabel()
        self.payment_status.setObjectName("paymentStatus")
        self.payment_status.setWordWrap(True)
        self.payment_status.setMinimumWidth(0)
        self.payment_method = QComboBox()
        self.payment_method.addItem("Efectivo", "cash")
        if "transfer" in enabled_payment_methods:
            self.payment_method.addItem("Transferencia", "transfer")
        if "card" in enabled_payment_methods:
            self.payment_method.addItem("Tarjeta (datáfono)", "card")
        self.payment_amount = QLineEdit()
        self.payment_amount.setPlaceholderText("Monto, ej. 10.00")
        self.payment_amount.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.payment_reference = QLineEdit()
        self.payment_reference.setPlaceholderText("Referencia de transferencia")
        add_payment = QPushButton("Agregar pago")
        add_payment.setObjectName("secondaryAction")
        add_payment.setMinimumWidth(0)
        add_payment.clicked.connect(self.add_payment)
        self.payment_table = DataTable(3, ["Forma", "Monto", "Referencia"])
        self.payment_table.setObjectName("paymentTable")
        self.payment_table.setMaximumHeight(100)
        remove_payment = QPushButton("Quitar pago")
        remove_payment.setObjectName("secondaryAction")
        remove_payment.setMinimumWidth(0)
        remove_payment.clicked.connect(self.remove_payment)
        confirm_button = QPushButton("Confirmar venta")
        confirm_button.setObjectName("primaryAction")
        confirm_button.setMinimumWidth(0)
        confirm_button.clicked.connect(self.confirm_sale)
        self.confirm_button = confirm_button

        products_box = QFrame()
        products_box.setObjectName("surfaceCard")
        products_layout = QVBoxLayout(products_box)
        products_title = QLabel("Productos")
        products_title.setObjectName("sectionTitle")
        products_layout.addWidget(products_title)
        products_layout.addWidget(self.search_input)
        products_layout.addWidget(self.scanner_status)
        products_layout.addWidget(self.product_list)
        products_layout.addWidget(self.product_empty)
        products_layout.addWidget(add_button)

        cart_box = QFrame()
        cart_box.setObjectName("surfaceCard")
        cart_layout = QVBoxLayout(cart_box)
        cart_header = QHBoxLayout()
        cart_title = QLabel("Venta actual")
        cart_title.setObjectName("sectionTitle")
        self.cart_count = QLabel("0 artículos")
        self.cart_count.setObjectName("cartCount")
        cart_header.addWidget(cart_title)
        cart_header.addStretch()
        cart_header.addWidget(self.cart_count)
        cart_layout.addLayout(cart_header)
        cart_layout.addWidget(self.cart_table)
        cart_layout.addWidget(remove_button)
        payment_layout = QGridLayout()
        cart_layout.addLayout(payment_layout)

        title = QLabel("Caja")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Registra ventas rápidamente y cobra con el método elegido.")
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        subtitle.setMinimumWidth(0)
        heading = QVBoxLayout()
        heading.addWidget(title)
        heading.addWidget(subtitle)
        summary = QFrame()
        summary.setObjectName("checkoutSummary")
        summary_layout = QHBoxLayout(summary)
        summary_layout.addWidget(QLabel("TOTAL DE LA VENTA"))
        summary_layout.addStretch()
        summary_layout.addWidget(self.total_label)
        self.subtotal_label = QLabel()
        self.subtotal_label.setObjectName("checkoutDetail")
        self.tax_label = QLabel()
        self.tax_label.setObjectName("checkoutDetail")
        summary_layout.addWidget(self.subtotal_label)
        summary_layout.addWidget(self.tax_label)
        payment_layout.addWidget(summary, 0, 0, 1, 2)
        payment_layout.addWidget(self.payment_status, 1, 0, 1, 2)
        payment_layout.addWidget(self.payment_table, 2, 0, 1, 2)
        payment_layout.addWidget(self.payment_method, 3, 0)
        payment_layout.addWidget(self.payment_amount, 3, 1)
        payment_layout.addWidget(self.payment_reference, 4, 0, 1, 2)
        payment_layout.addWidget(add_payment, 5, 0)
        payment_layout.addWidget(remove_payment, 5, 1)
        payment_layout.addWidget(confirm_button, 6, 0, 1, 2)
        self.payment_method.currentIndexChanged.connect(self._update_payment_fields)

        content = QGridLayout()
        content.addWidget(products_box, 0, 0)
        content.addWidget(cart_box, 0, 1)
        content.setColumnStretch(0, 1)
        content.setColumnMinimumWidth(1, 400)
        content.setColumnStretch(1, 0)
        self.content_grid = content
        self.products_box = products_box
        self.cart_box = cart_box
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 28, 30, 30)
        layout.setSpacing(16)
        layout.addLayout(heading)
        layout.addLayout(content)
        for sequence in ("Ctrl+Return", "Ctrl+Enter"):
            confirm_shortcut = QShortcut(QKeySequence(sequence), self)
            confirm_shortcut.activated.connect(confirm_button.click)
        remove_shortcut = QShortcut(QKeySequence("Delete"), self)
        remove_shortcut.activated.connect(self.remove_selected_line)
        quantity_shortcut = QShortcut(QKeySequence("F2"), self)
        quantity_shortcut.activated.connect(self.edit_selected_quantity)
        self._compact_layout = False
        self._relayout(900)
        self.refresh_products()
        self.refresh_cart()
        self._update_payment_fields()
        self.search_input.setFocus()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._relayout(self.width())

    def _relayout(self, width: int) -> None:
        compact = width < 1050
        if compact == self._compact_layout and self.content_grid.count():
            return
        self._compact_layout = compact
        self.content_grid.removeWidget(self.products_box)
        self.content_grid.removeWidget(self.cart_box)
        if compact:
            self.content_grid.addWidget(self.products_box, 0, 0, 1, 2)
            self.content_grid.addWidget(self.cart_box, 1, 0, 1, 2)
            self.content_grid.setColumnMinimumWidth(1, 0)
        else:
            self.content_grid.addWidget(self.products_box, 0, 0)
            self.content_grid.addWidget(self.cart_box, 0, 1)
            self.content_grid.setColumnMinimumWidth(1, 400)

    def refresh_products(self) -> None:
        self.product_list.clear()
        products = self.products.find_active(self.normalize_scan_value(self.search_input.text()))
        self.product_empty.setVisible(not products)
        for product in products:
            item = QListWidgetItem(
                f"{product.name}\n{product.code} · Stock {product.stock}    "
                f"{format_money(product.price_cents, self.currency_symbol)}"
            )
            item.setData(Qt.ItemDataRole.UserRole, product)
            item.setToolTip(f"{product.name} · {product.code}")
            item.setSizeHint(QSize(0, 56))
            self.product_list.addItem(item)
        if products:
            self.product_list.setCurrentRow(0)

    def _on_scan_text_changed(self, value: str) -> None:
        if not value:
            self.scanner_status.setText(
                "Busca por nombre o escanea un código para agregar productos."
            )
            self.scanner_status.setProperty("state", "default")
            self._refresh_scanner_status()

    @staticmethod
    def normalize_scan_value(value: str) -> str:
        return value.replace("\r", "").replace("\n", "").strip()

    def add_selected_product(self) -> None:
        row = self.product_list.currentRow()
        if row < 0:
            query = self.normalize_scan_value(self.search_input.text())
            self.scanner_status.setText(
                f"No encontramos un producto con el código o texto «{query}»."
                if query
                else "Escribe o escanea un código para agregar un producto."
            )
            self.scanner_status.setProperty("state", "error")
            self._refresh_scanner_status()
            return
        item = self.product_list.item(row)
        product = item.data(Qt.ItemDataRole.UserRole)
        try:
            self.cart.add(product)
        except ValueError as error:
            QMessageBox.warning(self, "No se puede agregar", str(error))
            self.scanner_status.setText(str(error))
            self.scanner_status.setProperty("state", "error")
            self._refresh_scanner_status()
            return
        self.refresh_cart()
        self.search_input.clear()
        self.search_input.setFocus()
        self.scanner_status.setText(f"{product.name} agregado a la venta.")
        self.scanner_status.setProperty("state", "success")
        self._refresh_scanner_status()

    def _refresh_scanner_status(self) -> None:
        self.scanner_status.style().unpolish(self.scanner_status)
        self.scanner_status.style().polish(self.scanner_status)

    def remove_selected_line(self) -> None:
        row = self.cart_table.currentRow()
        if row < 0:
            return
        item = self.cart_table.item(row, 0)
        if item is None:
            return
        product_id = item.data(Qt.ItemDataRole.UserRole)
        self.cart.remove(product_id)
        self.refresh_cart()

    def edit_selected_quantity(self) -> None:
        row = self.cart_table.currentRow()
        item = self.cart_table.item(row, 0) if row >= 0 else None
        if item is None:
            return
        product_id = item.data(Qt.ItemDataRole.UserRole)
        line = next((line for line in self.cart.lines if line.product.id == product_id), None)
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
            self.cart.set_quantity(product_id, quantity)
        except ValueError as error:
            QMessageBox.warning(self, "No se puede cambiar la cantidad", str(error))
            return
        self.refresh_cart()

    def refresh_cart(self) -> None:
        self.cart_table.setRowCount(0)
        for line in self.cart.lines:
            row = self.cart_table.rowCount()
            self.cart_table.insertRow(row)
            name_item = QTableWidgetItem(line.product.name)
            name_item.setData(Qt.ItemDataRole.UserRole, line.product.id)
            self.cart_table.setItem(row, 0, name_item)
            quantity_item = QTableWidgetItem(str(line.quantity))
            quantity_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            self.cart_table.setItem(row, 1, quantity_item)
            price_item = QTableWidgetItem(
                format_money(line.product.price_cents, self.currency_symbol)
            )
            price_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.cart_table.setItem(row, 2, price_item)
            total_item = QTableWidgetItem(format_money(line.total_cents, self.currency_symbol))
            total_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.cart_table.setItem(row, 3, total_item)
        self.cart_table.setFixedHeight(max(72, min(178, 38 + self.cart_table.rowCount() * 34)))
        self.total_label.setText(format_money(self.cart.grand_total_cents, self.currency_symbol))
        self.subtotal_label.setText(
            f"Subtotal {format_money(self.cart.total_cents, self.currency_symbol)}"
        )
        self.tax_label.setText(
            f"IVA ({self.tax_rate_basis_points / 100:g}%) "
            f"{format_money(self.cart.tax_cents, self.currency_symbol)}"
        )
        item_count = sum(line.quantity for line in self.cart.lines)
        self.cart_count.setText(f"{item_count} artículo{'s' if item_count != 1 else ''}")
        self.confirm_button.setEnabled(
            bool(self.cart.lines) and self._paid_cents() >= self.cart.grand_total_cents
        )
        self._refresh_payment_status()

    def _update_payment_fields(self) -> None:
        is_transfer = self.payment_method.currentData() == "transfer"
        self.payment_reference.setVisible(is_transfer)
        if not is_transfer:
            self.payment_reference.clear()

    def confirm_sale(self) -> None:
        try:
            payments = self._payments_from_table()
            sale = self.cart.to_sale(payments)
            sale_id = self.sales.register(sale)
        except (ValueError, SaleError) as error:
            QMessageBox.warning(self, "No se puede confirmar", str(error))
            return
        paid = sale.payment_cents
        summary = (
            f"Venta N.º {sale_id} registrada correctamente.\n\n"
            f"Subtotal: {format_money(sale.subtotal_cents, self.currency_symbol)}\n"
            f"IVA ({sale.tax_rate_basis_points / 100:g}%): "
            f"{format_money(sale.tax_cents, self.currency_symbol)}\n"
            f"Total: {format_money(sale.total_cents, self.currency_symbol)}\n"
            f"Pago recibido: {format_money(paid, self.currency_symbol)}\n"
        )
        if sale.change_cents:
            summary += f"Vuelto: {format_money(sale.change_cents, self.currency_symbol)}"
        else:
            summary += "Vuelto: No aplica"
        QMessageBox.information(
            self,
            "Venta completada",
            summary,
        )
        self.cart.clear()
        self.payment_table.setRowCount(0)
        self.payment_amount.clear()
        self.payment_reference.clear()
        self.refresh_cart()
        self._refresh_payment_status()
        self.refresh_products()
        self.sale_registered.emit()

    def add_payment(self) -> None:
        try:
            amount = self._parse_money(self.payment_amount.text())
            method = str(self.payment_method.currentData())
            reference = self.payment_reference.text().strip()
            if method == "transfer" and not reference:
                raise ValueError("La transferencia necesita un número de referencia.")
            if self._has_payment_method(method):
                raise ValueError("Esa forma de pago ya fue agregada.")
        except ValueError as error:
            QMessageBox.warning(self, "No se puede agregar el pago", str(error))
            return
        row = self.payment_table.rowCount()
        self.payment_table.insertRow(row)
        label = {"cash": "Efectivo", "transfer": "Transferencia", "card": "Tarjeta"}[method]
        method_item = QTableWidgetItem(label)
        method_item.setData(Qt.ItemDataRole.UserRole, method)
        self.payment_table.setItem(row, 0, method_item)
        amount_item = QTableWidgetItem(format_money(amount))
        amount_item.setData(Qt.ItemDataRole.UserRole, amount)
        self.payment_table.setItem(row, 1, amount_item)
        self.payment_table.setItem(row, 2, QTableWidgetItem(reference))
        self.payment_table.setFixedHeight(
            max(62, min(100, 38 + self.payment_table.rowCount() * 30))
        )
        self.payment_amount.clear()
        self.payment_reference.clear()
        self._refresh_payment_status()

    def _has_payment_method(self, method: str) -> bool:
        for row in range(self.payment_table.rowCount()):
            item = self.payment_table.item(row, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == method:
                return True
        return False

    def remove_payment(self) -> None:
        row = self.payment_table.currentRow()
        if row >= 0:
            self.payment_table.removeRow(row)
            self.payment_table.setFixedHeight(
                max(62, min(100, 38 + self.payment_table.rowCount() * 30))
            )
            self._refresh_payment_status()

    def _refresh_payment_status(self) -> None:
        total = self.cart.grand_total_cents
        paid = 0
        cash = 0
        for row in range(self.payment_table.rowCount()):
            amount_item = self.payment_table.item(row, 1)
            method_item = self.payment_table.item(row, 0)
            if amount_item is None or method_item is None:
                continue
            amount = amount_item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(amount, int):
                continue
            paid += amount
            if method_item.data(Qt.ItemDataRole.UserRole) == "cash":
                cash += amount
        paid = self._paid_cents()
        if total == 0:
            message = "Agrega productos para comenzar el cobro."
            state = "info"
        elif paid < total:
            message = (
                f"Pagado {format_money(paid, self.currency_symbol)} · "
                f"Falta {format_money(total - paid, self.currency_symbol)}"
            )
            state = "warning"
        else:
            change = max(0, cash - max(0, total - (paid - cash)))
            message = (
                f"Pago completo · Vuelto {format_money(change, self.currency_symbol)}"
                if change
                else "Pago completo · Listo para confirmar"
            )
            state = "success"
        self.payment_status.setText(message)
        self.payment_status.setProperty("state", state)
        self.payment_status.style().unpolish(self.payment_status)
        self.payment_status.style().polish(self.payment_status)
        self.confirm_button.setEnabled(bool(self.cart.lines) and paid >= total)

    def _paid_cents(self) -> int:
        paid = 0
        for row in range(self.payment_table.rowCount()):
            amount_item = self.payment_table.item(row, 1)
            if amount_item is None:
                continue
            amount = amount_item.data(Qt.ItemDataRole.UserRole)
            if isinstance(amount, int):
                paid += amount
        return paid

    def _payments_from_table(self) -> tuple[Payment, ...]:
        payments: list[Payment] = []
        for row in range(self.payment_table.rowCount()):
            method_item = self.payment_table.item(row, 0)
            amount_item = self.payment_table.item(row, 1)
            reference_item = self.payment_table.item(row, 2)
            if method_item is None or amount_item is None or reference_item is None:
                raise ValueError("Hay un pago incompleto.")
            method = method_item.data(Qt.ItemDataRole.UserRole)
            amount = amount_item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(method, str) or not isinstance(amount, int):
                raise ValueError("Hay un pago incompleto.")
            payments.append(
                Payment(
                    method,
                    amount,
                    reference_item.text(),
                )
            )
        return tuple(payments)

    @staticmethod
    def _parse_money(value: str) -> int:
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
