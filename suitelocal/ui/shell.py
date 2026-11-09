import re
from collections.abc import Callable
from datetime import UTC, datetime

from PySide6.QtCore import QDate, QEasingCurve, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QAction, QCloseEvent, QFont, QKeySequence, QResizeEvent, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from suitelocal.application.auth import AuthService
from suitelocal.application.cash_register import CashRegisterService
from suitelocal.application.catalog import CatalogService
from suitelocal.application.categories import CategoryService
from suitelocal.application.customers import CustomerService
from suitelocal.application.einvoice import (
    EInvoiceService,
    PassResult,
    SriGateway,
    run_processing_pass,
)
from suitelocal.application.receipts import ReceiptService
from suitelocal.application.tables import TablesService
from suitelocal.domain.auth import Session
from suitelocal.domain.business import issues_electronic_invoices
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import (
    CategoryRepository,
    ProductRepository,
    SaleRepository,
)
from suitelocal.infrastructure.settings import BusinessSettingsRepository
from suitelocal.infrastructure.sri.certificate_store import CertificateStore
from suitelocal.infrastructure.sri.client import SriClient
from suitelocal.infrastructure.sri.queue import EInvoiceRepository
from suitelocal.ui.components import ElidedLabel, ToastHost
from suitelocal.ui.components.einvoice_runner import EInvoiceRunner, Executor, thread_pool_executor
from suitelocal.ui.customers import CustomersWidget
from suitelocal.ui.dashboard import DashboardWidget
from suitelocal.ui.einvoices import EInvoicesWidget
from suitelocal.ui.inventory import InventoryWidget
from suitelocal.ui.pos import PosWidget, format_money
from suitelocal.ui.receipt import ReceiptOutput, ReceiptPrinter, printer_status_text
from suitelocal.ui.ride import RideOutput, RidePrinter
from suitelocal.ui.settings import SettingsWidget
from suitelocal.ui.tables import TablesWidget
from suitelocal.ui.theme.icons import icon
from suitelocal.ui.theme.manager import current_tokens, set_theme, theme_manager

RAIL_WIDTH = 232
RAIL_COLLAPSED_WIDTH = 72
COLLAPSE_BELOW_WIDTH = 1200
ROLE_LABELS = {"owner": "Dueño", "cashier": "Cajero"}
# Navigation items keep the page index (or "section") in UserRole, plus these two extras.
LABEL_ROLE = Qt.ItemDataRole.UserRole + 1
ICON_ROLE = Qt.ItemDataRole.UserRole + 3


def _no_certificates(_business_id: int) -> CertificateStore:
    raise ValueError("Todavía no hay un certificado para firmar las facturas.")


def initials(name: str) -> str:
    """Two-letter avatar text: first letters of two words, or the first two letters."""
    parts = [part for part in re.split(r"[\s._-]+", name.strip()) if part]
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return (name.strip()[:2] or "?").upper()


def format_clock(opened_at: str) -> str:
    """Local 12-hour clock for a SQLite UTC timestamp, e.g. ``7:02 a. m.``."""
    try:
        moment = datetime.fromisoformat(opened_at).replace(tzinfo=UTC).astimezone()
    except ValueError:
        return opened_at
    suffix = "a. m." if moment.hour < 12 else "p. m."
    return f"{moment.hour % 12 or 12}:{moment.minute:02d} {suffix}"


def _label(text: str, object_name: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName(object_name)
    return label


def _hbox(*widgets: QWidget, spacing: int = 8) -> QHBoxLayout:
    layout = QHBoxLayout()
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)
    for widget in widgets:
        layout.addWidget(widget)
    return layout


class AppShell(QMainWindow):
    logout_requested = Signal()

    def __init__(
        self,
        products: ProductRepository,
        sales: SaleRepository,
        session: Session,
        settings: BusinessSettingsRepository,
        auth: AuthService,
        database: Database,
        receipt_output: ReceiptOutput | None = None,
        certificates: Callable[[int], CertificateStore] | None = None,
        einvoice_client_for: Callable[[str], SriGateway] | None = None,
        einvoice_executor: Executor = thread_pool_executor,
        ride_output: RideOutput | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("SuiteLocal")
        self.resize(1250, 760)
        business = settings.get(session.user.business_id)
        self.setWindowTitle(f"SuiteLocal — {business.name}")
        self._session = session
        self._settings = settings
        self._database = database
        self._currency_symbol = business.currency_symbol
        self._printer_name = business.printer_name
        # The rail is built once per login, so module changes are compared with what it shows.
        self._enabled_modules = business.enabled_modules
        self.inventory_page: InventoryWidget | None = None
        self.einvoices_page: EInvoicesWidget | None = None
        self.settings_page: SettingsWidget | None = None
        self.cash_register = CashRegisterService(database)
        business_id = session.user.business_id
        # The printer reads paper and printer from the saved settings on every ticket.
        # Printing runs on a worker thread; a failure there comes back as this warning toast.
        self.receipt_output: ReceiptOutput = receipt_output or ReceiptPrinter(
            lambda: settings.get(business_id), on_failure=self._warn
        )
        # Same printer and paper as the internal ticket: the RIDE is printed in its place.
        self.ride_output: RideOutput = ride_output or RidePrinter(
            lambda: settings.get(business_id), on_failure=self._warn
        )
        self.einvoice_service = EInvoiceService(database, certificates or _no_certificates)
        einvoicing = self._einvoicing_enabled()
        receipts = ReceiptService(database)
        self.dashboard = DashboardWidget(
            products,
            sales,
            business.currency_symbol,
            business.low_stock_threshold,
            session.user.username,
            business.name,
        )
        self.categories = CategoryService(CategoryRepository(database))
        customers = CustomerService(database)
        self.pos_widget = PosWidget(
            products,
            sales,
            business.enabled_payment_methods,
            business.currency_symbol,
            business_name=business.name,
            low_stock_threshold=business.low_stock_threshold,
            decimal_separator=business.decimal_separator,
            enabled_modules=business.enabled_modules,
            categories=self.categories.list(session),
            tax_regime=business.tax_regime,
            session=session,
            receipts=receipts,
            receipt_output=self.receipt_output,
            einvoices=self.einvoice_service,
            ride_output=self.ride_output,
            einvoicing_enabled=einvoicing,
            customers=customers,
        )
        self.pages = QStackedWidget()
        self._add_page(self.dashboard)
        self._add_page(self.pos_widget)
        # Pages are added in rail order, and Ctrl+1..N picks the Nth rail entry.
        operation = [("Panel principal", 0, "dashboard"), ("Caja", 1, "cash")]
        groups = [("Operación", operation)]
        self.tables_widget: TablesWidget | None = None
        if "mesas" in business.enabled_modules:
            self.tables_widget = TablesWidget(
                TablesService(database),
                CatalogService(products),
                session,
                currency_symbol=business.currency_symbol,
                decimal_separator=business.decimal_separator,
                enabled_payment_methods=tuple(business.enabled_payment_methods),
                receipts=receipts,
                receipt_output=self.receipt_output,
                einvoices=self.einvoice_service,
                ride_output=self.ride_output,
                einvoicing_enabled=einvoicing,
                customers=customers,
            )
            operation.append(("Mesas", self._add_page(self.tables_widget), "table"))
        self.customers_widget = CustomersWidget(
            customers,
            session,
            currency_symbol=business.currency_symbol,
            decimal_separator=business.decimal_separator,
        )
        self.customers_widget.notification.connect(self._show_toast)
        operation.append(("Clientes", self._add_page(self.customers_widget), "users"))
        if session.is_owner:
            inventory = InventoryWidget(products, session)
            inventory.notification.connect(self._show_toast)
            self.inventory_page = inventory
            inventory_index = self._add_page(inventory)
            from suitelocal.ui.users import UsersWidget

            users = UsersWidget(auth, session)
            users.notification.connect(self._show_toast)
            users_index = self._add_page(users)
            settings_page = SettingsWidget(settings, session, database, certificates=certificates)
            settings_page.notification.connect(self._show_toast)
            settings_page.business_changed.connect(self._on_business_changed)
            self.settings_page = settings_page
            settings_index = self._add_page(settings_page)
            operation.append(("Inventario", inventory_index, "box"))
            business_entries = [
                ("Equipo", users_index, "users"),
                ("Ajustes", settings_index, "settings"),
            ]
            if einvoicing:
                # The runner is built after the pages, so "Procesar ahora" reaches it late.
                einvoices_page = EInvoicesWidget(
                    self.einvoice_service,
                    session,
                    process_now=lambda: self.einvoice_runner.tick(),
                    ride_output=self.ride_output,
                    currency_symbol=business.currency_symbol,
                    decimal_separator=business.decimal_separator,
                )
                einvoices_page.notification.connect(self._show_toast)
                self.einvoices_page = einvoices_page
                business_entries.insert(
                    0, ("Facturas electrónicas", self._add_page(einvoices_page), "invoice")
                )
            groups.append(("Negocio", business_entries))

        navigation = QListWidget()
        self.navigation = navigation
        navigation.setObjectName("navigation")
        navigation.setMinimumWidth(0)
        navigation.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        navigation.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        navigation.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        page_count = 0
        for group_name, entries in groups:
            section = QListWidgetItem(group_name)
            section.setFlags(Qt.ItemFlag.NoItemFlags)
            section.setData(Qt.ItemDataRole.UserRole, "section")
            section.setSizeHint(QSize(0, 34))
            section_font = QFont(section.font())
            section_font.setPointSizeF(8)
            section_font.setBold(True)
            section_font.setCapitalization(QFont.Capitalization.AllUppercase)
            section_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.4)
            section.setFont(section_font)
            navigation.addItem(section)
            for label, page_index, icon_name in entries:
                item = QListWidgetItem(label, navigation)
                item.setData(Qt.ItemDataRole.UserRole, page_index)
                item.setData(LABEL_ROLE, label)
                item.setData(ICON_ROLE, icon_name)
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                page_count += 1

        def select_page(row: int) -> None:
            item = navigation.item(row)
            target = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(target, int):
                self.pages.setCurrentIndex(target)

        navigation.currentRowChanged.connect(select_page)
        for number in range(1, page_count + 1):
            page_shortcut = QShortcut(QKeySequence(f"Ctrl+{number}"), self)
            page_shortcut.activated.connect(lambda position=number - 1: self._show_entry(position))
        navigation.setCurrentRow(1)
        self.pages.currentChanged.connect(self._focus_page)
        self._focus_page(self.pages.currentIndex())

        sidebar = self._build_rail(business.name, session)

        search = QLineEdit()
        self.global_search = search
        search.setObjectName("topSearch")
        search.setMinimumWidth(0)
        search.setPlaceholderText(f"Buscar en {business.name}...")
        self._search_action: QAction = search.addAction(
            icon("search", current_tokens().text_500, 18), QLineEdit.ActionPosition.LeadingPosition
        )
        search.setAccessibleName("Búsqueda global")
        search_shortcut = QShortcut(QKeySequence("Ctrl+K"), self)
        search_shortcut.activated.connect(self._focus_search)
        clear_search_shortcut = QShortcut(QKeySequence("Escape"), search)
        clear_search_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        clear_search_shortcut.activated.connect(search.clear)
        date = QLabel(self._format_date(QDate.currentDate()))
        date.setObjectName("topDate")
        account = QLabel(f"<b>{business.name}</b>")
        account.setObjectName("topAccount")
        self.theme_toggle = QPushButton()
        self.theme_toggle.setObjectName("themeToggle")
        self.theme_toggle.setCheckable(True)
        self.theme_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_toggle.clicked.connect(self._switch_theme)
        theme_shortcut = QShortcut(QKeySequence("Ctrl+Shift+L"), self)
        theme_shortcut.activated.connect(self._toggle_theme)
        header = QWidget()
        header.setObjectName("topbar")
        header.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 12, 24, 12)
        header_layout.setSpacing(16)
        header_layout.addWidget(search, 1)
        header_layout.addWidget(date)
        header_layout.addWidget(account)
        header_layout.addWidget(self.theme_toggle)
        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(header)
        content_layout.addWidget(self.pages, 1)
        content_layout.addWidget(self._build_status_bar())
        content = QWidget()
        content.setObjectName("content")
        content.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        content.setLayout(content_layout)
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(sidebar)
        layout.addWidget(content)
        container = QWidget()
        container.setObjectName("centralContainer")
        container.setLayout(layout)
        self.setCentralWidget(container)
        self.toasts = ToastHost(container)
        self.pos_widget.notification.connect(self._show_toast)
        self.pos_widget.invoice_issued.connect(self._on_invoice_issued)
        if self.tables_widget is not None:
            self.tables_widget.notification.connect(self._show_toast)
            self.tables_widget.invoice_issued.connect(self._on_invoice_issued)
        self.top_date = date
        self.top_account = account
        self._sidebar_collapsed = False
        self.sidebar_animation: QVariantAnimation | None = None
        self._set_sidebar_width(RAIL_WIDTH)
        self._set_sidebar_collapsed(self.width() < COLLAPSE_BELOW_WIDTH)
        self.pos_widget.sale_registered.connect(self.dashboard.refresh)
        self.pos_widget.sale_registered.connect(self.refresh_register)
        if self.tables_widget is not None:
            self.tables_widget.sale_registered.connect(self.dashboard.refresh)
            self.tables_widget.sale_registered.connect(self.refresh_register)
            # A table charge lowers stock, so the counter catalog must not keep stale counts.
            self.tables_widget.sale_registered.connect(self.pos_widget.refresh_products)
        self.pages.currentChanged.connect(self._refresh_register_on_page_change)
        self._start_einvoice_runner(einvoice_client_for, einvoice_executor)
        self.dashboard.quick_action.clicked.connect(lambda: self.pages.setCurrentIndex(1))
        theme_manager().theme_changed.connect(self._apply_theme)
        self._apply_theme(theme_manager().name)
        self.refresh_register()

    def _build_rail(self, business_name: str, session: Session) -> QWidget:
        self.brand_mark = QLabel("S")
        self.brand_mark.setObjectName("brandMark")
        self.brand_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.brand_name = QLabel("SuiteLocal")
        self.brand_name.setObjectName("brandName")
        self.brand_business = ElidedLabel(business_name)
        self.brand_business.setObjectName("brandBusiness")
        self.brand_text = QWidget()
        self.brand_text.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        brand_text_layout = QVBoxLayout(self.brand_text)
        brand_text_layout.setContentsMargins(0, 0, 0, 0)
        brand_text_layout.setSpacing(0)
        brand_text_layout.addWidget(self.brand_name)
        brand_text_layout.addWidget(self.brand_business)
        brand_row = QWidget()
        self.brand_layout = QHBoxLayout(brand_row)
        self.brand_layout.setContentsMargins(8, 2, 8, 22)
        self.brand_layout.setSpacing(12)
        self.brand_layout.addWidget(self.brand_mark)
        self.brand_layout.addWidget(self.brand_text, 1)

        self.register_status = QLabel("Caja cerrada")
        self.register_status.setObjectName("registerStatus")
        self.register_status.setProperty("state", "closed")
        self.register_base = QLabel()
        self.register_expected = QLabel()
        for value in (self.register_base, self.register_expected):
            value.setObjectName("registerValue")
        self.register_base_row = QWidget()
        self.register_base_row.setLayout(_hbox(_label("Base", "registerLabel"), self.register_base))
        self.register_expected_row = QWidget()
        self.register_expected_row.setLayout(
            _hbox(_label("Efectivo esperado", "registerLabel"), self.register_expected)
        )
        for row in (self.register_base_row, self.register_expected_row):
            row_layout = row.layout()
            if isinstance(row_layout, QHBoxLayout):
                row_layout.insertStretch(1)
        self.register_divider = QFrame()
        self.register_divider.setObjectName("registerDivider")
        self.register_divider.setFrameShape(QFrame.Shape.NoFrame)
        self.register_detail = QWidget()
        detail_layout = QVBoxLayout(self.register_detail)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(9)
        detail_layout.addWidget(self.register_status)
        detail_layout.addWidget(self.register_base_row)
        detail_layout.addWidget(self.register_expected_row)

        self.user_avatar = QLabel(initials(session.user.username))
        self.user_avatar.setObjectName("avatar")
        self.user_avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.user_name = ElidedLabel(session.user.username)
        self.user_name.setObjectName("userName")
        self.user_role = ElidedLabel(ROLE_LABELS.get(session.user.role, session.user.role))
        self.user_role.setObjectName("userRole")
        self.user_text = QWidget()
        self.user_text.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        user_text_layout = QVBoxLayout(self.user_text)
        user_text_layout.setContentsMargins(0, 0, 0, 0)
        user_text_layout.setSpacing(0)
        user_text_layout.addWidget(self.user_name)
        user_text_layout.addWidget(self.user_role)
        who_row = QWidget()
        self.who_layout = QHBoxLayout(who_row)
        self.who_layout.setContentsMargins(0, 0, 0, 0)
        self.who_layout.setSpacing(10)
        self.who_layout.addWidget(self.user_avatar)
        self.who_layout.addWidget(self.user_text, 1)

        self.register_card = QFrame()
        self.register_card.setObjectName("registerCard")
        self.register_card_layout = QVBoxLayout(self.register_card)
        self.register_card_layout.setContentsMargins(14, 14, 14, 14)
        self.register_card_layout.setSpacing(10)
        self.register_card_layout.addWidget(self.register_detail)
        self.register_card_layout.addWidget(self.register_divider)
        self.register_card_layout.addWidget(who_row)

        self.logout_button = QPushButton("Cerrar sesión")
        self.logout_button.setObjectName("logoutButton")
        self.logout_button.setAccessibleName("Cerrar sesión")
        self.logout_button.clicked.connect(self._logout)

        sidebar_layout = QVBoxLayout()
        sidebar_layout.setContentsMargins(14, 22, 14, 14)
        sidebar_layout.setSpacing(4)
        sidebar_layout.addWidget(brand_row)
        sidebar_layout.addWidget(self.navigation, 1)
        sidebar_layout.addWidget(self.register_card)
        sidebar_layout.addWidget(self.logout_button)
        sidebar = QWidget()
        self.sidebar = sidebar
        sidebar.setObjectName("sidebar")
        sidebar.setLayout(sidebar_layout)
        return sidebar

    def _build_status_bar(self) -> QWidget:
        def item(text: str, state: str) -> tuple[QWidget, QLabel]:
            dot = QLabel("●")
            dot.setObjectName("statusDot")
            dot.setProperty("state", state)
            label = QLabel(text)
            holder = QWidget()
            holder.setLayout(_hbox(dot, label, spacing=6))
            return holder, label

        offline, self.status_offline = item("Funcionando sin internet", "ok")
        # The backups module records no last-backup time, so only what is true today is shown.
        printer, self.status_printer = item(printer_status_text(self._printer_name), "idle")
        self.status_sri_item, self.status_sri = item("", "warn")
        self.status_sri_item.hide()
        self.status_cash_base = QLabel()
        self.status_cash_expected = QLabel()
        for value in (self.status_cash_base, self.status_cash_expected):
            value.setObjectName("statusValue")
        self.status_cash = QWidget()
        self.status_cash.setLayout(
            _hbox(
                QLabel("Base de caja"),
                self.status_cash_base,
                QLabel("·"),
                QLabel("Efectivo esperado"),
                self.status_cash_expected,
                spacing=6,
            )
        )
        self.status_bar = QWidget()
        self.status_bar.setObjectName("statusBar")
        self.status_bar.setFixedHeight(40)
        layout = QHBoxLayout(self.status_bar)
        layout.setContentsMargins(26, 0, 26, 0)
        layout.setSpacing(22)
        layout.addWidget(offline)
        layout.addWidget(printer)
        layout.addWidget(self.status_sri_item)
        layout.addStretch()
        layout.addWidget(self.status_cash)
        return self.status_bar

    # -- business profile -------------------------------------------------------------------

    def _on_business_changed(self) -> None:
        """Adopt saved settings in every open page; only the rail's entries need a new login."""
        business = self._settings.get(self._session.user.business_id)
        self._currency_symbol = business.currency_symbol
        self.setWindowTitle(f"SuiteLocal — {business.name}")
        self.brand_business.setText(business.name)
        self.top_account.setText(f"<b>{business.name}</b>")
        self.global_search.setPlaceholderText(f"Buscar en {business.name}...")
        self.dashboard.currency_symbol = business.currency_symbol
        self.dashboard.low_stock_threshold = business.low_stock_threshold
        self.dashboard.refresh()
        self.pos_widget.apply_business(business, self.categories.list(self._session))
        self._printer_name = business.printer_name
        self.status_printer.setText(printer_status_text(business.printer_name))
        if self.tables_widget is not None:
            self.tables_widget.currency_symbol = business.currency_symbol
            self.tables_widget.decimal_separator = business.decimal_separator
            self.tables_widget.einvoicing_enabled = self._einvoicing_enabled()
            self.tables_widget.enabled_payment_methods = business.enabled_payment_methods or (
                "cash",
            )
            self.tables_widget.refresh()
        if self.inventory_page is not None:
            self.inventory_page.refresh_profile()
        self.refresh_register()
        if ("mesas" in business.enabled_modules) != ("mesas" in self._enabled_modules):
            self._show_toast(
                "El módulo de mesas se aplica la próxima vez que inicies sesión.", "info"
            )
        self._enabled_modules = business.enabled_modules
        if self._session.is_owner and self._einvoicing_enabled() and self.einvoices_page is None:
            self._show_toast(
                "La página de Facturas electrónicas aparece la próxima vez que inicies sesión.",
                "info",
            )
        if self.einvoices_page is not None:
            self.einvoices_page.currency_symbol = business.currency_symbol
            self.einvoices_page.decimal_separator = business.decimal_separator
            self.einvoices_page.refresh()
        self._refresh_einvoice_status()

    # -- electronic invoices ----------------------------------------------------------------

    def _einvoicing_enabled(self) -> bool:
        business = self._settings.get(self._session.user.business_id)
        return business.einvoice_enabled and issues_electronic_invoices(business.tax_regime)

    def _start_einvoice_runner(
        self, client_for: Callable[[str], SriGateway] | None, executor: Executor
    ) -> None:
        """Process the invoice queue every two minutes, off the UI thread, while it is enabled."""
        database_path = self._database.path
        business_id = self._session.user.business_id
        gateway_for = client_for or SriClient

        def run_pass(now: datetime) -> PassResult:
            return run_processing_pass(database_path, business_id, gateway_for, now)

        self.einvoice_runner = EInvoiceRunner(
            is_enabled=self._einvoicing_enabled, run_pass=run_pass, executor=executor, parent=self
        )
        self.einvoice_runner.warning.connect(self._show_einvoice_warning)
        self.einvoice_runner.pending_changed.connect(self._show_sri_pending)
        if self.einvoices_page is not None:
            self.einvoice_runner.pass_completed.connect(self.einvoices_page.refresh)
        self.einvoice_runner.start()
        self._refresh_einvoice_status()

    def _on_invoice_issued(self) -> None:
        """A sale just tried to issue its invoice: show the new queue size and reload the page."""
        self._refresh_einvoice_status()
        if self.einvoices_page is not None:
            self.einvoices_page.refresh()

    def _show_einvoice_warning(self, message: str) -> None:
        self._show_toast(message, "warning")

    def _refresh_einvoice_status(self) -> None:
        """Show how many invoices wait for the SRI, read right now from the queue."""
        if not self._einvoicing_enabled():
            self.status_sri_item.hide()
            return
        self._show_sri_pending(
            EInvoiceRepository(self._database).count_open(self._session.user.business_id)
        )

    def _show_sri_pending(self, count: int) -> None:
        if count <= 0 or not self._einvoicing_enabled():
            self.status_sri_item.hide()
            return
        noun = "pendiente" if count == 1 else "pendientes"
        self.status_sri.setText(f"SRI: {count} {noun}")
        self.status_sri_item.show()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.einvoice_runner.stop()
        super().closeEvent(event)

    # -- cash register ----------------------------------------------------------------------

    def refresh_register(self) -> None:
        """Reload the open cash session into the rail card and the status bar."""
        current = self.cash_register.current(self._session)
        expected = None if current is None else self.cash_register.expected_cents(self._session)
        is_open = current is not None and expected is not None
        if current is not None and expected is not None:
            self.register_status.setText(f"Caja abierta · {format_clock(current.opened_at)}")
            base_text = format_money(current.opening_cents, self._currency_symbol)
            expected_text = format_money(expected, self._currency_symbol)
            self.register_base.setText(base_text)
            self.register_expected.setText(expected_text)
            self.status_cash_base.setText(base_text)
            self.status_cash_expected.setText(expected_text)
        else:
            self.register_status.setText("Caja cerrada")
        self.register_status.setProperty("state", "open" if is_open else "closed")
        self.register_status.style().unpolish(self.register_status)
        self.register_status.style().polish(self.register_status)
        self.register_base_row.setVisible(is_open)
        self.register_expected_row.setVisible(is_open)
        self.status_cash.setVisible(is_open)

    def _refresh_register_on_page_change(self, _index: int) -> None:
        self.refresh_register()

    # -- theme --------------------------------------------------------------------------------

    def _toggle_theme(self) -> None:
        self._switch_theme(theme_manager().name != "dark")

    def _switch_theme(self, dark: bool) -> None:
        app = QApplication.instance()
        if isinstance(app, QApplication):
            set_theme(app, "dark" if dark else "light")

    def _apply_theme(self, name: str) -> None:
        """Redraw what is painted in Python; the stylesheet was already replaced."""
        tokens = current_tokens()
        dark = name == "dark"
        label = "Modo claro" if dark else "Modo oscuro"
        self.theme_toggle.setText(label)
        self.theme_toggle.setAccessibleName(label)
        self.theme_toggle.setToolTip(f"{label} (Ctrl+Shift+L)")
        self.theme_toggle.setIcon(icon("sun" if dark else "moon", tokens.text_700, 16))
        self.theme_toggle.setChecked(dark)
        self._search_action.setIcon(icon("search", tokens.text_500, 18))
        self.logout_button.setIcon(icon("logout", tokens.rail_text, 16))
        for row in range(self.navigation.count()):
            item = self.navigation.item(row)
            icon_name = item.data(ICON_ROLE)
            if isinstance(icon_name, str):
                nav_icon = icon(icon_name, tokens.rail_text, 18, selected_color=tokens.rail_strong)
                item.setIcon(nav_icon)

    def show_page(self, index: int) -> None:
        """Select the navigation entry that opens page ``index``."""
        for row in range(self.navigation.count()):
            if self.navigation.item(row).data(Qt.ItemDataRole.UserRole) == index:
                self.navigation.setCurrentRow(row)
                return

    def _show_entry(self, position: int) -> None:
        """Select the ``position``-th page entry of the rail, counting from zero."""
        rows = [
            row
            for row in range(self.navigation.count())
            if isinstance(self.navigation.item(row).data(Qt.ItemDataRole.UserRole), int)
        ]
        if 0 <= position < len(rows):
            self.navigation.setCurrentRow(rows[position])

    def _focus_search(self) -> None:
        if self.pages.currentIndex() == 1:
            self.pos_widget.search_input.setFocus(Qt.FocusReason.ShortcutFocusReason)
            self.pos_widget.search_input.selectAll()
        else:
            self.global_search.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _show_toast(self, message: str, state: str) -> None:
        self.toasts.show_toast(message, state)

    def _warn(self, message: str) -> None:
        self._show_toast(message, "warning")

    def _logout(self) -> None:
        self.logout_requested.emit()
        self.close()

    def _add_page(self, page: QWidget) -> int:
        """Add a page to the stack and return its index."""
        page.setObjectName("pageContent")
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        scroll = QScrollArea()
        scroll.setObjectName("pageScroll")
        scroll.viewport().setObjectName("pageViewport")
        scroll.viewport().setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        return self.pages.addWidget(scroll)

    def _focus_page(self, index: int) -> None:
        if index == 1:
            self.pos_widget.search_input.setFocus()

    @staticmethod
    def _format_date(date: QDate) -> str:
        weekdays = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")
        months = (
            "ene",
            "feb",
            "mar",
            "abr",
            "may",
            "jun",
            "jul",
            "ago",
            "sept",
            "oct",
            "nov",
            "dic",
        )
        weekday = weekdays[date.dayOfWeek() - 1]
        month = months[date.month() - 1]
        return f"{weekday}, {date.day()} {month} {date.year()}"

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._set_sidebar_collapsed(self.width() < 1200)

    def _animate_sidebar(self, target: int) -> None:
        """Resize the sidebar, animating only while the window is on screen."""
        if self.sidebar_animation is not None:
            self.sidebar_animation.stop()
        if not self.isVisible():
            self._set_sidebar_width(target)
            return
        animation = QVariantAnimation(self)
        animation.setDuration(180)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.setStartValue(self.sidebar.width())
        animation.setEndValue(target)
        animation.valueChanged.connect(self._on_sidebar_width_changed)
        animation.finished.connect(lambda: self._set_sidebar_width(target))
        self.sidebar_animation = animation
        animation.start()

    def _on_sidebar_width_changed(self, value: object) -> None:
        if isinstance(value, int):
            self._set_sidebar_width(value)

    def _set_sidebar_width(self, width: int) -> None:
        self.sidebar.setMinimumWidth(width)
        self.sidebar.setMaximumWidth(width)

    def _set_sidebar_collapsed(self, collapsed: bool) -> None:
        if getattr(self, "_sidebar_collapsed", None) == collapsed:
            return
        self._sidebar_collapsed = collapsed
        self._animate_sidebar(RAIL_COLLAPSED_WIDTH if collapsed else RAIL_WIDTH)
        self.top_date.setVisible(not collapsed)
        self.top_account.setVisible(not collapsed)
        # Collapsed, the rail keeps only the brand mark, the nav icons and the avatar.
        self.brand_text.setVisible(not collapsed)
        self.brand_layout.setContentsMargins(*((0, 2, 0, 18) if collapsed else (8, 2, 8, 22)))
        self.brand_layout.setAlignment(
            self.brand_mark,
            Qt.AlignmentFlag.AlignHCenter if collapsed else Qt.AlignmentFlag.AlignLeft,
        )
        self.register_detail.setVisible(not collapsed)
        self.register_divider.setVisible(not collapsed)
        self.user_text.setVisible(not collapsed)
        margin = 6 if collapsed else 14
        self.register_card_layout.setContentsMargins(margin, margin, margin, margin)
        self.who_layout.setAlignment(
            self.user_avatar,
            Qt.AlignmentFlag.AlignHCenter if collapsed else Qt.AlignmentFlag.AlignLeft,
        )
        self.logout_button.setText("" if collapsed else "Cerrar sesión")
        self.logout_button.setToolTip("Cerrar sesión" if collapsed else "")
        for widget in (self.navigation, self.logout_button):
            widget.setProperty("collapsed", collapsed)
        for row in range(self.navigation.count()):
            item = self.navigation.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == "section":
                item.setHidden(collapsed)
                continue
            label = str(item.data(LABEL_ROLE))
            item.setText("" if collapsed else label)
            item.setTextAlignment(
                Qt.AlignmentFlag.AlignCenter
                if collapsed
                else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            item.setToolTip(label if collapsed else "")
        for widget in (self.navigation, self.logout_button):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
