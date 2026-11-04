from PySide6.QtCore import QDate, QEasingCurve, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QKeySequence, QResizeEvent, QShortcut
from PySide6.QtWidgets import (
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
from suitelocal.domain.auth import Session
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import ProductRepository, SaleRepository
from suitelocal.infrastructure.settings import BusinessSettingsRepository
from suitelocal.ui.components import ToastHost
from suitelocal.ui.dashboard import DashboardWidget
from suitelocal.ui.inventory import InventoryWidget
from suitelocal.ui.pos import PosWidget
from suitelocal.ui.theme.icons import icon
from suitelocal.ui.theme.tokens import TOKENS


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
    ) -> None:
        super().__init__()
        self.setWindowTitle("SuiteLocal")
        self.resize(1250, 760)
        business = settings.get(session.user.business_id)
        self.setWindowTitle(f"SuiteLocal — {business.name}")
        self.dashboard = DashboardWidget(
            products,
            sales,
            business.currency_symbol,
            business.low_stock_threshold,
            session.user.username,
            business.name,
        )
        self.pos_widget = PosWidget(
            products,
            sales,
            business.enabled_payment_methods,
            business.currency_symbol,
            business.tax_rate_basis_points,
        )
        self.pages = QStackedWidget()
        self._add_page(self.dashboard)
        self._add_page(self.pos_widget)
        labels = ["Panel principal", "Caja"]
        if session.is_owner:
            inventory = InventoryWidget(products, session)
            inventory.notification.connect(self._show_toast)
            self._add_page(inventory)
            from suitelocal.ui.settings import SettingsWidget
            from suitelocal.ui.users import UsersWidget

            settings_page = SettingsWidget(settings, session.user.business_id, database)
            settings_page.notification.connect(self._show_toast)
            self._add_page(settings_page)
            users = UsersWidget(auth, session)
            users.notification.connect(self._show_toast)
            self._add_page(users)
            labels.extend(["Inventario", "Configuración", "Usuarios"])

        navigation = QListWidget()
        self.navigation = navigation
        navigation.setObjectName("navigation")
        navigation.setMinimumWidth(0)
        navigation.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        navigation.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        icon_names = ("dashboard", "cash", "box", "settings", "users")
        page_index = 0
        section_items = {"OPERACIÓN": labels[:2]}
        if session.is_owner:
            section_items["ADMINISTRACIÓN"] = labels[2:]
        for section_name, section_labels in section_items.items():
            if not section_labels:
                continue
            section = QListWidgetItem(section_name)
            section.setFlags(Qt.ItemFlag.NoItemFlags)
            section.setData(Qt.ItemDataRole.UserRole, "section")
            section.setData(Qt.ItemDataRole.UserRole + 2, "section")
            navigation.addItem(section)
            for label in section_labels:
                index = labels.index(label)
                item = QListWidgetItem(label, navigation)
                item.setData(Qt.ItemDataRole.UserRole, page_index)
                item.setData(Qt.ItemDataRole.UserRole + 1, label)
                item.setIcon(icon(icon_names[index], TOKENS.surface, 18))
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                page_index += 1

        def select_page(row: int) -> None:
            item = navigation.item(row)
            target = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(target, int):
                self.pages.setCurrentIndex(target)

        navigation.currentRowChanged.connect(select_page)
        for number in range(1, page_index + 1):
            page_shortcut = QShortcut(QKeySequence(f"Ctrl+{number}"), self)
            page_shortcut.activated.connect(lambda index=number - 1: self.show_page(index))
        navigation.setCurrentRow(1)
        self.pages.currentChanged.connect(self._focus_page)
        self._focus_page(self.pages.currentIndex())

        brand = QLabel("<b>SuiteLocal</b><br><small>Gestión</small>")
        self.brand = brand
        brand.setObjectName("brand")
        role_labels = {"owner": "Dueño", "cashier": "Cajero"}
        role_label = role_labels.get(session.user.role, session.user.role)
        user = QLabel(f"<b>{session.user.username}</b><br><span>{role_label}</span>")
        user.setObjectName("currentUser")
        logout = QPushButton("Cerrar sesión")
        logout.setObjectName("logoutButton")
        logout.setIcon(icon("logout", TOKENS.surface, 16))
        logout.clicked.connect(self._logout)
        sidebar_layout = QVBoxLayout()
        sidebar_layout.setContentsMargins(16, 18, 16, 18)
        sidebar_layout.setSpacing(10)
        sidebar_layout.addWidget(brand)
        sidebar_layout.addWidget(navigation)
        sidebar_layout.addStretch()
        sidebar_layout.addWidget(user)
        sidebar_layout.addWidget(logout)
        sidebar = QWidget()
        self.sidebar = sidebar
        sidebar.setObjectName("sidebar")
        sidebar.setLayout(sidebar_layout)

        search = QLineEdit()
        self.global_search = search
        search.setObjectName("topSearch")
        search.setMinimumWidth(0)
        search.setPlaceholderText(f"Buscar en {business.name}...")
        search.addAction(
            icon("search", TOKENS.text_500, 18), QLineEdit.ActionPosition.LeadingPosition
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
        header = QWidget()
        header.setObjectName("topbar")
        header.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 12, 24, 12)
        header_layout.addWidget(search, 1)
        header_layout.addWidget(date)
        header_layout.addWidget(account)
        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addWidget(header)
        content_layout.addWidget(self.pages)
        content = QWidget()
        content.setObjectName("content")
        content.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        content.setLayout(content_layout)
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(sidebar)
        layout.addWidget(content)
        container = QWidget()
        container.setObjectName("centralContainer")
        container.setLayout(layout)
        self.setCentralWidget(container)
        self.toasts = ToastHost(container)
        self.pos_widget.notification.connect(self._show_toast)
        self.top_date = date
        self.top_account = account
        self._sidebar_collapsed = False
        self.sidebar_animation: QVariantAnimation | None = None
        self._set_sidebar_collapsed(self.width() < 1200)
        self.pos_widget.sale_registered.connect(self.dashboard.refresh)
        self.dashboard.quick_action.clicked.connect(lambda: self.pages.setCurrentIndex(1))

    def show_page(self, index: int) -> None:
        """Select the navigation entry that opens page ``index``."""
        for row in range(self.navigation.count()):
            if self.navigation.item(row).data(Qt.ItemDataRole.UserRole) == index:
                self.navigation.setCurrentRow(row)
                return

    def _focus_search(self) -> None:
        if self.pages.currentIndex() == 1:
            self.pos_widget.search_input.setFocus(Qt.FocusReason.ShortcutFocusReason)
            self.pos_widget.search_input.selectAll()
        else:
            self.global_search.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _show_toast(self, message: str, state: str) -> None:
        self.toasts.show_toast(message, state)

    def _logout(self) -> None:
        self.logout_requested.emit()
        self.close()

    def _add_page(self, page: QWidget) -> None:
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
        self.pages.addWidget(scroll)

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
        self.navigation.setProperty("collapsed", collapsed)
        self.top_date.setVisible(not collapsed)
        self.top_account.setVisible(not collapsed)
        self._animate_sidebar(72 if collapsed else 248)
        brand_text = "<b>SuiteLocal</b><br><small>Gestión</small>"
        self.brand.setText("SL" if collapsed else brand_text)
        for row in range(self.navigation.count()):
            item = self.navigation.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == "section":
                item.setHidden(collapsed)
                continue
            label = str(item.data(Qt.ItemDataRole.UserRole + 1))
            item.setText("" if collapsed else label)
            item.setTextAlignment(
                Qt.AlignmentFlag.AlignCenter
                if collapsed
                else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            item.setToolTip(label if collapsed else "")
        self.navigation.style().unpolish(self.navigation)
        self.navigation.style().polish(self.navigation)
