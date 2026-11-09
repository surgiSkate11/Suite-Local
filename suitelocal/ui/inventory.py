from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
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

from suitelocal.application.categories import CategoryService
from suitelocal.application.inventory import InventoryService
from suitelocal.domain.auth import Session
from suitelocal.domain.business import charges_iva
from suitelocal.domain.models import Product
from suitelocal.domain.tax import TAX_RATES_BASIS_POINTS, effective_tax_rate, split_tax_included
from suitelocal.infrastructure.repositories import CategoryRepository, ProductRepository
from suitelocal.infrastructure.settings import BusinessSettingsRepository
from suitelocal.ui.components import (
    DangerButton,
    DataTable,
    Drawer,
    EmptyState,
    InlineMessage,
    SearchField,
    StatusBadge,
    confirm_action,
    set_variant,
)
from suitelocal.ui.payment_dialog import format_money

NO_VALUE = "—"
NO_CATEGORY = "Sin categoría"
TABLE_HEADERS = ["Código", "Nombre", "Categoría", "Precio", "IVA", "Margen", "Stock", "Estado"]
STATUS_COLUMN = len(TABLE_HEADERS) - 1
TAX_COLUMN = TABLE_HEADERS.index("IVA")


def rate_label(rate_basis_points: int) -> str:
    return f"{rate_basis_points // 100} %"


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
        self.settings_repository = BusinessSettingsRepository(products.database)
        self.category_service = CategoryService(CategoryRepository(products.database))
        self.business = self.settings_repository.get(session.user.business_id)
        self.all_categories = self.category_service.list(session, include_inactive=True)
        self.editing_id: int | None = None
        self.visible_products = []
        self.code = QLineEdit()
        self.code.setPlaceholderText("SKU, código de barras o código QR")
        self.name = QLineEdit()
        self.price = QLineEdit()
        self.stock = QLineEdit()
        self.cost = QLineEdit()
        self.cost.setPlaceholderText("Opcional")
        self.category = QComboBox()
        self.tax_rate = QComboBox()
        for rate in TAX_RATES_BASIS_POINTS:
            self.tax_rate.addItem(rate_label(rate), rate)
        for field in (self.code, self.name, self.price, self.cost, self.stock):
            field.returnPressed.connect(self.save_product)
        save = set_variant(QPushButton("Guardar producto"), "primary")
        save.clicked.connect(self.save_product)
        new = set_variant(QPushButton("Nuevo"), "secondary")
        new.clicked.connect(self.clear_form)
        deactivate = DangerButton("Desactivar seleccionado")
        deactivate.clicked.connect(self.deactivate_selected)
        self.message = InlineMessage()
        self.search = SearchField("Buscar por código o nombre...")
        self.search.textChanged.connect(self.refresh)

        form = QFormLayout()
        self.form = form
        form.addRow("Código:", self.code)
        form.addRow("Nombre:", self.name)
        form.addRow("Categoría:", self.category)
        form.addRow("Precio (con IVA):", self.price)
        form.addRow("IVA:", self.tax_rate)
        form.addRow("Costo:", self.cost)
        form.addRow("Stock:", self.stock)
        self.drawer = Drawer("Nuevo producto", self)
        self.drawer.content_layout.addLayout(form)
        self.drawer.content_layout.addWidget(save)
        self.drawer.content_layout.addWidget(new)
        self.drawer.content_layout.addWidget(deactivate)
        self.drawer.content_layout.addWidget(self.message)
        self.drawer.hide()

        self.table = DataTable(len(TABLE_HEADERS), TABLE_HEADERS)
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
        set_variant(new_product, "primary")
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
        self._fill_categories(None)
        self._select_rate(self.business.tax_rate_basis_points)
        self._apply_regime()
        self.refresh()

    def _apply_regime(self) -> None:
        """Without IVA the rate field and column have nothing to say, so they are hidden.

        The products keep their stored rates; the data stays in the hidden column.
        """
        charges = charges_iva(self.business.tax_regime)
        for field in (self.tax_rate, self.form.labelForField(self.tax_rate)):
            field.setVisible(charges)
        price_label = self.form.labelForField(self.price)
        if isinstance(price_label, QLabel):
            price_label.setText("Precio (con IVA):" if charges else "Precio:")
        self.table.setColumnHidden(TAX_COLUMN, not charges)

    def refresh_profile(self) -> None:
        """Reload the business settings and categories after they changed elsewhere."""
        self.business = self.settings_repository.get(self.session.user.business_id)
        self.all_categories = self.category_service.list(self.session, include_inactive=True)
        self._fill_categories(self.category.currentData())
        if self.editing_id is None:
            self._select_rate(self.business.tax_rate_basis_points)
        self._apply_regime()
        self.refresh()

    def _fill_categories(self, selected_id: int | None) -> None:
        """List the active categories, plus the selected one when it was deactivated."""
        self.category.clear()
        self.category.addItem(NO_CATEGORY, None)
        for category in self.all_categories:
            if category.active or category.id == selected_id:
                label = category.name if category.active else f"{category.name} (inactiva)"
                self.category.addItem(label, category.id)
        self.category.setCurrentIndex(max(self.category.findData(selected_id), 0))

    def _select_rate(self, rate_basis_points: int) -> None:
        self.tax_rate.setCurrentIndex(max(self.tax_rate.findData(rate_basis_points), 0))

    def save_product(self) -> None:
        try:
            code, name = self.code.text(), self.name.text()
            price = self._parse_money(self.price.text(), "El precio")
            cost = self._parse_optional_money(self.cost.text(), "El costo")
            stock = self._parse_integer(self.stock.text(), "El stock")
            category_id = self.category.currentData()
            rate = self.tax_rate.currentData()
            if self.editing_id is None:
                product = self.inventory.create_product(
                    self.session,
                    code,
                    name,
                    price,
                    stock,
                    category_id=category_id,
                    cost_cents=cost,
                    tax_rate_basis_points=rate,
                )
            else:
                product = self.inventory.update_product(
                    self.session,
                    self.editing_id,
                    code,
                    name,
                    price,
                    stock,
                    tax_rate_basis_points=rate,
                    category_id=category_id,
                    cost_cents=cost,
                )
        except (ValueError, PermissionError) as error:
            self.message.show_error(str(error))
            return
        self.clear_form()
        self.refresh()
        self.notification.emit(f"{product.name} está disponible en el inventario.", "success")

    def refresh(self) -> None:
        products = self.inventory.products.find_active(self.search.text())
        self.visible_products = products
        names = {category.id: category.name for category in self.all_categories}
        symbol = self.business.currency_symbol
        separator = self.business.decimal_separator
        threshold = self.business.low_stock_threshold
        self.table.setRowCount(0)
        for product in products:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = (
                product.code,
                product.name,
                self._category_name(names, product.category_id),
                format_money(product.price_cents, symbol, separator),
                rate_label(product.tax_rate_basis_points),
                self._margin_text(product, symbol, separator),
                str(product.stock),
            )
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
            if product.stock == 0:
                state, status = "danger", "Agotado"
            elif product.stock <= threshold:
                state, status = "warning", "Stock bajo"
            else:
                state, status = "success", "Activo"
            self.table.setCellWidget(row, STATUS_COLUMN, StatusBadge(status, state))
        self.empty_state.setVisible(not products)
        self.result_count.setText(f"{len(products)} producto{'s' if len(products) != 1 else ''}")

    @staticmethod
    def _category_name(names: dict[int, str], category_id: int | None) -> str:
        return NO_VALUE if category_id is None else names.get(category_id, NO_VALUE)

    def _margin_text(self, product: Product, symbol: str, separator: str) -> str:
        """Price base without IVA minus the cost; a dash when the cost is unknown."""
        if product.cost_cents is None:
            return NO_VALUE
        rate = effective_tax_rate(
            product.tax_rate_basis_points, charges_iva=charges_iva(self.business.tax_regime)
        )
        base, _tax = split_tax_included(product.price_cents, rate)
        return format_money(base - product.cost_cents, symbol, separator)

    def _plain_amount(self, cents: int) -> str:
        """Editable amount: no symbol or grouping, with the business decimal separator."""
        units, remainder = divmod(cents, 100)
        return f"{units}{self.business.decimal_separator}{remainder:02d}"

    def load_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        if row >= len(self.visible_products):
            return
        product = self.visible_products[row]
        self.editing_id = product.id
        self.drawer.set_title("Editar producto")
        self.code.setText(product.code)
        self.name.setText(product.name)
        self.price.setText(self._plain_amount(product.price_cents))
        self.cost.setText(
            "" if product.cost_cents is None else self._plain_amount(product.cost_cents)
        )
        self._fill_categories(product.category_id)
        self._select_rate(product.tax_rate_basis_points)
        self.stock.setText(str(product.stock))
        self.message.clear_message()
        self.drawer.open_with_focus(self.name)

    def clear_form(self) -> None:
        self.editing_id = None
        self.code.clear()
        self.name.clear()
        self.price.clear()
        self.cost.clear()
        self.stock.clear()
        self._fill_categories(None)
        self._select_rate(self.business.tax_rate_basis_points)
        self.table.clearSelection()
        self.message.clear_message()
        self.drawer.hide()

    def open_new_product(self) -> None:
        self.clear_form()
        self.drawer.set_title("Nuevo producto")
        self.drawer.open_with_focus(self.code)

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
    def _parse_money(value: str, label: str) -> int:
        try:
            amount = Decimal(value.strip().replace(",", "."))
            cents = int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        except (InvalidOperation, ValueError) as error:
            raise ValueError(f"{label} debe ser un número válido.") from error
        if cents < 0:
            raise ValueError(f"{label} no puede ser negativo.")
        return cents

    @classmethod
    def _parse_optional_money(cls, value: str, label: str) -> int | None:
        return cls._parse_money(value, label) if value.strip() else None

    @staticmethod
    def _parse_integer(value: str, label: str) -> int:
        try:
            number = int(value.strip())
        except ValueError as error:
            raise ValueError(f"{label} debe ser un número entero.") from error
        if number < 0:
            raise ValueError(f"{label} no puede ser negativo.")
        return number
