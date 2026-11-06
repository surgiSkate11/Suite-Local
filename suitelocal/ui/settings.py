from collections.abc import Callable, Iterable, Sequence
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from suitelocal.application.business_profile import BusinessProfileService
from suitelocal.application.categories import CategoryService
from suitelocal.domain.auth import Session
from suitelocal.domain.business import (
    BUSINESS_TYPES,
    RECEIPT_PAPER_WIDTHS_MM,
    TAX_REGIMES,
    BusinessSettings,
    requires_ruc,
)
from suitelocal.domain.tax import TAX_RATES_BASIS_POINTS
from suitelocal.infrastructure.backups import BackupError, create_backup, restore_backup
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import Category, CategoryRepository
from suitelocal.infrastructure.settings import BusinessSettingsRepository
from suitelocal.ui.components import DangerButton, InlineMessage, confirm_action, set_variant
from suitelocal.ui.receipt import DEFAULT_PRINTER_LABEL, installed_printer_names

Confirmer = Callable[[QWidget | None, str, str], bool]
PrinterNames = Callable[[], Sequence[str]]

FIELD_MAX_WIDTH = 460
NO_SELECTION = "Elegí una categoría de la lista."
DECIMAL_SEPARATOR_LABELS = {",": "Coma (1.234,56)", ".": "Punto (1,234.56)"}
# Module code -> (checkbox label, one-line description), in the order they are shown.
MODULE_INFO = {
    "mesas": (
        "Mesas y comandas",
        "Cuentas abiertas por mesa, con envío a cocina. Ideal para cafeterías.",
    ),
    "venta_por_peso": ("Venta por peso", "Productos que se venden por kilo o por libra."),
    "codigo_barras": (
        "Códigos de barras",
        "Vendé escaneando el código de barras del producto.",
    ),
    "categorias": (
        "Categorías",
        "Agrupá los productos y filtrá la caja por categoría.",
    ),
}


def _card(title: str, hint: str | None = None) -> tuple[QFrame, QVBoxLayout]:
    """A titled section card with an optional one-line explanation."""
    card = QFrame()
    card.setObjectName("contentCard")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(20, 18, 20, 18)
    layout.setSpacing(10)
    heading = QLabel(title)
    heading.setObjectName("sectionTitle")
    layout.addWidget(heading)
    if hint is not None:
        layout.addWidget(_hint(hint))
    return card, layout


def _hint(text: str, object_name: str = "pageSubtitle") -> QLabel:
    label = QLabel(text)
    label.setObjectName(object_name)
    label.setWordWrap(True)
    label.setMinimumWidth(0)
    return label


def _form() -> QFormLayout:
    form = QFormLayout()
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    form.setHorizontalSpacing(18)
    form.setVerticalSpacing(12)
    return form


def _limited[Field: QWidget](field: Field) -> Field:
    field.setMaximumWidth(FIELD_MAX_WIDTH)
    return field


class SettingsWidget(QWidget):
    """Owner-only settings: business data, type, modules, checkout, categories and backups."""

    notification = Signal(str, str)
    # Emitted after any saved change the rest of the app has to pick up without a restart.
    business_changed = Signal()

    def __init__(
        self,
        settings: BusinessSettingsRepository,
        session: Session,
        database: Database,
        confirm: Confirmer = confirm_action,
        parent: QWidget | None = None,
        printer_names: PrinterNames = installed_printer_names,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.printer_names = printer_names
        self.session = session
        self.database = database
        self.confirm = confirm
        categories = CategoryRepository(database)
        self.profile = BusinessProfileService(settings, categories)
        self.category_service = CategoryService(categories)
        current = self.profile.get(session)

        self.name = _limited(QLineEdit())
        self.ruc = _limited(QLineEdit())
        self.ruc.setMaxLength(13)
        self.regime = _limited(QComboBox())
        for code, label in TAX_REGIMES.items():
            self.regime.addItem(label, code)
        self.address = _limited(QLineEdit())
        self.phone = _limited(QLineEdit())
        self.receipt_footer = _limited(QLineEdit())
        self.receipt_footer.setPlaceholderText("Ej. Gracias por su compra")
        self.business_type = _limited(QComboBox())
        for code, label in BUSINESS_TYPES.items():
            self.business_type.addItem(label, code)
        self.module_boxes: dict[str, QCheckBox] = {}
        self.module_hints: dict[str, QLabel] = {}
        self.transfer = QCheckBox("Transferencia")
        self.card = QCheckBox("Tarjeta con datáfono configurado")
        self.card.setEnabled(False)
        self.card.setToolTip("Se habilitará al configurar un proveedor de datáfono.")
        self.card.setMinimumWidth(0)
        self.tax_rate = _limited(QComboBox())
        for rate in TAX_RATES_BASIS_POINTS:
            self.tax_rate.addItem(f"{rate // 100} %", rate)
        self.threshold = _limited(QSpinBox())
        self.threshold.setRange(0, 1_000_000)
        self.decimal_separator = _limited(QComboBox())
        for separator, label in DECIMAL_SEPARATOR_LABELS.items():
            self.decimal_separator.addItem(label, separator)
        self.receipt_paper = _limited(QComboBox())
        for width in RECEIPT_PAPER_WIDTHS_MM:
            self.receipt_paper.addItem(f"{width} mm", width)
        self.printer = _limited(QComboBox())
        self.regime.currentIndexChanged.connect(self._update_ruc_hint)
        for field in (self.name, self.ruc, self.address, self.phone, self.receipt_footer):
            field.returnPressed.connect(self.save)

        self.message = InlineMessage()
        self.save_button = set_variant(QPushButton("Guardar configuración"), "primary")
        self.save_button.clicked.connect(self.save)

        title = QLabel("Configuración")
        title.setObjectName("pageTitle")
        subtitle = _hint("Adaptá SuiteLocal a la forma de trabajar de tu negocio.")
        heading = QVBoxLayout()
        heading.addWidget(title)
        heading.addWidget(subtitle)
        header = QHBoxLayout()
        header.addLayout(heading, 1)
        header.addWidget(self.save_button, 0, Qt.AlignmentFlag.AlignTop)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 28, 30, 30)
        layout.setSpacing(16)
        layout.addLayout(header)
        layout.addWidget(self.message)
        layout.addWidget(self._build_business_card())
        layout.addWidget(self._build_type_card())
        layout.addWidget(self._build_modules_card())
        layout.addWidget(self._build_checkout_card())
        layout.addWidget(self._build_categories_card())
        layout.addWidget(self._build_backup_card())
        layout.addStretch()

        self._load(current)
        self._reload_categories()

    # -- construction -----------------------------------------------------------------------

    def _build_business_card(self) -> QFrame:
        card, layout = _card(
            "Datos del negocio",
            "Aparecen en tus comprobantes. El RUC solo es obligatorio si "
            "emitís facturas electrónicas.",
        )
        form = _form()
        form.addRow("Nombre del negocio:", self.name)
        form.addRow("Régimen tributario:", self.regime)
        form.addRow("RUC:", self.ruc)
        form.addRow("Dirección:", self.address)
        form.addRow("Teléfono:", self.phone)
        form.addRow("Pie del comprobante:", self.receipt_footer)
        layout.addLayout(form)
        return card

    def _build_type_card(self) -> QFrame:
        card, layout = _card(
            "Tipo de negocio",
            "Aplicar la plantilla activa los módulos del tipo elegido y agrega sus categorías "
            "sugeridas. No borra tus categorías ni tus productos.",
        )
        self.apply_template_button = set_variant(QPushButton("Aplicar plantilla"), "secondary")
        self.apply_template_button.clicked.connect(self.apply_template)
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(self.business_type, 1)
        row.addWidget(self.apply_template_button)
        row.addStretch(1)
        layout.addLayout(row)
        return card

    def _build_modules_card(self) -> QFrame:
        card, layout = _card("Módulos", "Activá solo lo que tu negocio necesita.")
        for code, (label, description) in MODULE_INFO.items():
            box = QCheckBox(label)
            hint = _hint(description, "moduleHint")
            self.module_boxes[code] = box
            self.module_hints[code] = hint
            layout.addWidget(box)
            layout.addWidget(hint)
        return card

    def _build_checkout_card(self) -> QFrame:
        card, layout = _card("Cobro", "Cómo cobra y cómo muestra los montos tu negocio.")
        layout.addWidget(QLabel("Efectivo: siempre habilitado"))
        layout.addWidget(self.transfer)
        layout.addWidget(self.card)
        form = _form()
        form.addRow("IVA para productos nuevos:", self.tax_rate)
        form.addRow("Avisar stock bajo en:", self.threshold)
        form.addRow("Separador decimal:", self.decimal_separator)
        form.addRow("Ancho del papel del ticket:", self.receipt_paper)
        form.addRow("Impresora de tickets:", self.printer)
        layout.addLayout(form)
        return card

    def _build_categories_card(self) -> QFrame:
        card, layout = _card(
            "Categorías",
            "Agrupá tus productos. Si una categoría ya tiene productos, desactivala en lugar de "
            "eliminarla.",
        )
        self.categories_list = QListWidget()
        self.categories_list.setObjectName("categoryList")
        self.categories_list.setMinimumHeight(180)
        self.categories_list.currentRowChanged.connect(self._on_category_selected)
        self.category_name = QLineEdit()
        self.category_name.setPlaceholderText("Nombre de la categoría")
        self.category_name.returnPressed.connect(self.add_category)
        add = set_variant(QPushButton("Agregar"), "secondary")
        add.clicked.connect(self.add_category)
        rename = set_variant(QPushButton("Renombrar"), "secondary")
        rename.clicked.connect(self.rename_category)
        self.toggle_category_button = set_variant(QPushButton("Desactivar"), "secondary")
        self.toggle_category_button.clicked.connect(self.toggle_category)
        delete = DangerButton("Eliminar")
        delete.clicked.connect(self.delete_category)
        self.category_message = InlineMessage()
        actions = QVBoxLayout()
        actions.setSpacing(8)
        actions.addWidget(self.category_name)
        for button in (add, rename, self.toggle_category_button, delete):
            actions.addWidget(button)
        actions.addStretch()
        body = QHBoxLayout()
        body.setSpacing(18)
        body.addWidget(self.categories_list, 3)
        body.addLayout(actions, 2)
        layout.addLayout(body)
        layout.addWidget(self.category_message)
        return card

    def _build_backup_card(self) -> QFrame:
        card, layout = _card(
            "Respaldo y recuperación",
            "Protege la información de tu negocio con una copia local. "
            "Restaurar reemplaza los datos actuales.",
        )
        actions = QHBoxLayout()
        backup_button = set_variant(QPushButton("Crear respaldo"), "secondary")
        backup_button.clicked.connect(self.create_backup)
        restore_button = DangerButton("Restaurar respaldo")
        restore_button.clicked.connect(self.restore_backup)
        actions.addWidget(backup_button)
        actions.addWidget(restore_button)
        actions.addStretch()
        layout.addLayout(actions)
        return card

    # -- loading ----------------------------------------------------------------------------

    def _load(self, current: BusinessSettings) -> None:
        """Fill every field from the stored settings."""
        self.name.setText(current.name)
        self.ruc.setText(current.ruc)
        self.regime.setCurrentIndex(self.regime.findData(current.tax_regime))
        self.address.setText(current.address)
        self.phone.setText(current.phone)
        self.receipt_footer.setText(current.receipt_footer)
        self.business_type.setCurrentIndex(self.business_type.findData(current.business_type))
        self._load_modules(current.enabled_modules)
        self.transfer.setChecked("transfer" in current.enabled_payment_methods)
        self.card.setChecked("card" in current.enabled_payment_methods)
        self.tax_rate.setCurrentIndex(max(self.tax_rate.findData(current.tax_rate_basis_points), 0))
        self.threshold.setValue(current.low_stock_threshold)
        self.decimal_separator.setCurrentIndex(
            max(self.decimal_separator.findData(current.decimal_separator), 0)
        )
        self.receipt_paper.setCurrentIndex(
            max(self.receipt_paper.findData(current.receipt_paper_mm), 0)
        )
        self._load_printers(current.printer_name)
        self._update_ruc_hint()

    def _load_printers(self, selected: str) -> None:
        """List the installed printers; a saved one that is gone stays selectable, flagged."""
        self.printer.clear()
        self.printer.addItem(DEFAULT_PRINTER_LABEL, "")
        installed = list(self.printer_names())
        for name in installed:
            self.printer.addItem(name, name)
        if selected and selected not in installed:
            self.printer.addItem(f"{selected} (no instalada)", selected)
        self.printer.setCurrentIndex(max(self.printer.findData(selected), 0))

    def _load_modules(self, enabled: Iterable[str]) -> None:
        enabled = set(enabled)
        for code, box in self.module_boxes.items():
            box.setChecked(code in enabled)

    def _update_ruc_hint(self) -> None:
        required = requires_ruc(self.regime.currentData())
        self.ruc.setPlaceholderText(
            "Obligatorio para este régimen" if required else "Opcional para este régimen"
        )

    # -- business data ----------------------------------------------------------------------

    def save(self) -> None:
        """Save data, type, modules and checkout together, or save nothing."""
        before = self.profile.get(self.session)
        methods = ["cash"]
        if self.transfer.isChecked():
            methods.append("transfer")
        if self.card.isChecked():
            methods.append("card")
        try:
            self.profile.update_profile(
                self.session,
                ruc=self.ruc.text(),
                tax_regime=self.regime.currentData(),
                business_type=self.business_type.currentData(),
                enabled_modules=[
                    code for code, box in self.module_boxes.items() if box.isChecked()
                ],
                decimal_separator=self.decimal_separator.currentData(),
                address=self.address.text(),
                phone=self.phone.text(),
                receipt_footer=self.receipt_footer.text(),
                receipt_paper_mm=self.receipt_paper.currentData(),
                printer_name=self.printer.currentData(),
            )
        except (ValueError, PermissionError) as error:
            self.message.show_error(str(error))
            return
        try:
            saved = self.profile.update_settings(
                self.session,
                self.name.text(),
                before.currency_symbol,
                self.threshold.value(),
                tuple(methods),
                str(self.tax_rate.currentData() // 100),
            )
        except (ValueError, PermissionError) as error:
            self._restore_profile(before)
            self.message.show_error(str(error))
            return
        self._load(saved)
        self.message.clear_message()
        self.notification.emit(f"Configuración de {saved.name} actualizada.", "success")
        self.business_changed.emit()

    def _restore_profile(self, before: BusinessSettings) -> None:
        """Undo the profile step when the general settings step is rejected."""
        self.profile.update_profile(
            self.session,
            ruc=before.ruc,
            tax_regime=before.tax_regime,
            business_type=before.business_type,
            enabled_modules=before.enabled_modules,
            decimal_separator=before.decimal_separator,
            address=before.address,
            phone=before.phone,
            receipt_footer=before.receipt_footer,
            receipt_paper_mm=before.receipt_paper_mm,
            printer_name=before.printer_name,
        )

    def apply_template(self) -> None:
        """Adopt the chosen business type after asking; unsaved fields stay as typed."""
        code = self.business_type.currentData()
        label = BUSINESS_TYPES[code]
        if not self.confirm(
            self,
            "Aplicar plantilla",
            f"Se activarán los módulos de {label} y se agregarán sus categorías sugeridas. "
            "No se borra ninguna categoría ni producto. ¿Querés continuar?",
        ):
            return
        try:
            saved = self.profile.apply_template(self.session, code)
        except (ValueError, PermissionError) as error:
            self.message.show_error(str(error))
            return
        self.message.clear_message()
        self._load_modules(saved.enabled_modules)
        self._reload_categories()
        self.notification.emit(f"Plantilla de {label} aplicada.", "success")
        self.business_changed.emit()

    # -- categories -------------------------------------------------------------------------

    def _reload_categories(self, select_id: int | None = None) -> None:
        categories = self.category_service.list(self.session, include_inactive=True)
        self.categories_list.blockSignals(True)
        self.categories_list.clear()
        for category in categories:
            text = category.name if category.active else f"{category.name} (inactiva)"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, category)
            self.categories_list.addItem(item)
            if category.id == select_id:
                self.categories_list.setCurrentItem(item)
        self.categories_list.blockSignals(False)
        self._on_category_selected(self.categories_list.currentRow())

    def _selected_category(self) -> Category | None:
        row = self.categories_list.currentRow()
        if row < 0:
            return None
        item = self.categories_list.item(row)
        category = item.data(Qt.ItemDataRole.UserRole)
        return category if isinstance(category, Category) else None

    def _on_category_selected(self, _row: int) -> None:
        category = self._selected_category()
        if category is not None:
            self.category_name.setText(category.name)
        self.toggle_category_button.setText(
            "Activar" if category is not None and not category.active else "Desactivar"
        )

    def _change_category(
        self, change: Callable[[], Category | None], select_id: int | None = None
    ) -> bool:
        """Run a category write; show the backend message on failure, refresh on success."""
        try:
            changed = change()
        except (ValueError, PermissionError) as error:
            self.category_message.show_error(str(error))
            return False
        self.category_message.clear_message()
        self._reload_categories(changed.id if changed is not None else select_id)
        self.business_changed.emit()
        return True

    def add_category(self) -> None:
        if self._change_category(
            lambda: self.category_service.create(self.session, self.category_name.text())
        ):
            self.category_name.clear()

    def rename_category(self) -> None:
        category = self._selected_category()
        if category is None:
            self.category_message.show_error(NO_SELECTION)
            return
        self._change_category(
            lambda: self.category_service.rename(
                self.session, category.id, self.category_name.text()
            )
        )

    def toggle_category(self) -> None:
        category = self._selected_category()
        if category is None:
            self.category_message.show_error(NO_SELECTION)
            return

        def change() -> None:
            self.category_service.set_active(self.session, category.id, not category.active)

        self._change_category(change, select_id=category.id)

    def delete_category(self) -> None:
        category = self._selected_category()
        if category is None:
            self.category_message.show_error(NO_SELECTION)
            return
        if not self.confirm(
            self,
            "Eliminar categoría",
            f"¿Eliminar la categoría «{category.name}»? Esta acción no se puede deshacer.",
        ):
            return

        def change() -> None:
            self.category_service.delete(self.session, category.id)

        if self._change_category(change):
            self.category_name.clear()

    # -- backups ----------------------------------------------------------------------------

    def create_backup(self) -> None:
        destination, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar respaldo",
            str(Path.home() / "SuiteLocal-respaldo.sqlite"),
            "Base SQLite (*.sqlite *.db);;Todos los archivos (*)",
        )
        if not destination:
            return
        try:
            path = create_backup(self.database, destination)
        except BackupError as error:
            self.message.show_error(f"No se pudo crear el respaldo. {error}")
            return
        self.message.clear_message()
        self.notification.emit(f"Respaldo creado: {path.name}.", "success")

    def restore_backup(self) -> None:
        source, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar respaldo",
            str(Path.home()),
            "Base SQLite (*.sqlite *.db);;Todos los archivos (*)",
        )
        if not source:
            return
        if not self.confirm(
            self,
            "Confirmar restauración",
            "La restauración reemplazará los datos actuales del negocio. ¿Deseas continuar?",
        ):
            return
        try:
            safety_path = (
                self.database.path.parent
                / "backups"
                / f"antes-restauracion-{datetime.now():%Y%m%d-%H%M%S}.sqlite"
            )
            restore_backup(self.database, source, safety_path)
        except BackupError as error:
            self.message.show_error(f"No se pudo restaurar. {error}")
            return
        self.message.show_success(
            "Restauración completada. "
            f"Copia de seguridad previa: {safety_path.name}. "
            "Reinicia SuiteLocal para cargar los datos restaurados."
        )
