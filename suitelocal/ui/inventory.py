from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from suitelocal.application.inventory import InventoryService
from suitelocal.domain.auth import Session
from suitelocal.infrastructure.repositories import ProductRepository
from suitelocal.ui.components import (
    DataTable,
    Drawer,
    EmptyState,
    InlineMessage,
    SearchField,
    StatusBadge,
    confirm_action,
)
from suitelocal.ui.pos import format_money


class InventoryWidget(QWidget):
    notification = Signal(str, str)

    def __init__(
        self,
        products: ProductRepository,
        session: Session,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.inventory = InventoryService(products)
        self.session = session
        self.editing_id: int | None = None
        self.visible_products = []
        self.code = QLineEdit()
        self.code.setPlaceholderText("SKU, código de barras o código QR")
        self.name = QLineEdit()
        self.price = QLineEdit()
        self.stock = QLineEdit()
        save = QPushButton("Guardar producto")
        save.clicked.connect(self.save_product)
        new = QPushButton("Nuevo")
        new.clicked.connect(self.clear_form)
        deactivate = QPushButton("Desactivar seleccionado")
        deactivate.clicked.connect(self.deactivate_selected)
        self.message = InlineMessage()
        self.search = SearchField("Buscar por código o nombre...")
        self.search.textChanged.connect(self.refresh)

        form = QFormLayout()
        form.addRow("Código:", self.code)
        form.addRow("Nombre:", self.name)
        form.addRow("Precio:", self.price)
        form.addRow("Stock:", self.stock)
        self.drawer = Drawer("Nuevo producto", self)
        self.drawer.content_layout.addLayout(form)
        self.drawer.content_layout.addWidget(save)
        self.drawer.content_layout.addWidget(new)
        deactivate.setObjectName("secondaryAction")
        self.drawer.content_layout.addWidget(deactivate)
        self.drawer.content_layout.addWidget(self.message)
        self.drawer.hide()

        self.table = DataTable(5, ["Código", "Nombre", "Precio", "Stock", "Estado"])
        self.table.itemSelectionChanged.connect(self.load_selected)
        self.empty_state = EmptyState(
            "Tu inventario todavía está vacío",
            "Crea tu primer producto para empezar a vender desde Caja.",
            "Crear el primero",
        )
        self.empty_state.hide()
        if self.empty_state.action is not None:
            self.empty_state.action.clicked.connect(self.open_new_product)
        new_product = QPushButton("Nuevo producto")
        new_product.setObjectName("primaryAction")
        new_product.clicked.connect(self.open_new_product)
        toolbar = QHBoxLayout()
        toolbar.addWidget(self.search)
        self.result_count = QLabel()
        self.result_count.setObjectName("resultCount")
        toolbar.addWidget(self.result_count)
        toolbar.addStretch()
        toolbar.addWidget(new_product)
        self.toolbar = toolbar
        title = QLabel("Inventario")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Administra productos, precios y existencias de tu negocio.")
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        subtitle.setMinimumWidth(0)
        heading = QVBoxLayout()
        heading.addWidget(title)
        heading.addWidget(subtitle)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 28, 30, 30)
        layout.setSpacing(16)
        layout.addLayout(heading)
        layout.addLayout(toolbar)
        table_card = QFrame()
        table_card.setObjectName("contentCard")
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(18, 16, 18, 16)
        table_layout.addWidget(self.table)
        layout.addWidget(table_card)
        layout.addWidget(self.empty_state)
        layout.addWidget(self.drawer)
        self.refresh()

    def save_product(self) -> None:
        try:
            values = (
                self.code.text(),
                self.name.text(),
                self._parse_money(self.price.text()),
                self._parse_integer(self.stock.text(), "El stock"),
            )
            if self.editing_id is None:
                product = self.inventory.create_product(self.session, *values)
            else:
                product = self.inventory.update_product(self.session, self.editing_id, *values)
        except ValueError as error:
            self.message.show_error(str(error))
            return
        self.message.clear_message()
        self.notification.emit(f"{product.name} está disponible en el inventario.", "success")
        self.code.clear()
        self.name.clear()
        self.price.clear()
        self.stock.clear()
        self.editing_id = None
        self.refresh()

    def refresh(self) -> None:
        products = self.inventory.products.find_active(self.search.text())
        self.visible_products = products
        self.table.setRowCount(0)
        for product in products:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = (
                product.code,
                product.name,
                format_money(product.price_cents),
                str(product.stock),
            )
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
            state = (
                "danger" if product.stock == 0 else "warning" if product.stock <= 3 else "success"
            )
            status = (
                "Agotado"
                if product.stock == 0
                else "Stock bajo"
                if product.stock <= 3
                else "Activo"
            )
            self.table.setCellWidget(
                row,
                4,
                StatusBadge(status, state),
            )
        self.empty_state.setVisible(not products)
        self.result_count.setText(f"{len(products)} producto{'s' if len(products) != 1 else ''}")

    def load_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        if row >= len(self.visible_products):
            return
        product = self.visible_products[row]
        self.editing_id = product.id
        self.drawer.setWindowTitle("Editar producto")
        self.drawer.show()
        self.code.setText(product.code)
        self.name.setText(product.name)
        self.price.setText(f"{product.price_cents / 100:.2f}")
        self.stock.setText(str(product.stock))
        self.message.clear_message()

    def clear_form(self) -> None:
        self.editing_id = None
        self.code.clear()
        self.name.clear()
        self.price.clear()
        self.stock.clear()
        self.table.clearSelection()
        self.message.clear_message()
        self.drawer.hide()

    def open_new_product(self) -> None:
        self.clear_form()
        self.drawer.setWindowTitle("Nuevo producto")
        self.drawer.show()

    def deactivate_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.visible_products):
            self.notification.emit("Selecciona un producto de la tabla.", "info")
            return
        product = self.visible_products[row]
        if not confirm_action(
            self,
            "Desactivar producto",
            f"¿Desactivar {product.name}? Dejará de aparecer en Caja.",
        ):
            return
        self.inventory.deactivate_product(self.session, product.id)
        self.clear_form()
        self.refresh()
        self.notification.emit(f"Producto {product.name} desactivado.", "success")

    @staticmethod
    def _parse_money(value: str) -> int:
        try:
            amount = Decimal(value.strip().replace(",", "."))
            cents = int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        except InvalidOperation as error:
            raise ValueError("El precio debe ser un número válido.") from error
        if cents < 0:
            raise ValueError("El precio no puede ser negativo.")
        return cents

    @staticmethod
    def _parse_integer(value: str, label: str) -> int:
        try:
            number = int(value.strip())
        except ValueError as error:
            raise ValueError(f"{label} debe ser un número entero.") from error
        if number < 0:
            raise ValueError(f"{label} no puede ser negativo.")
        return number
