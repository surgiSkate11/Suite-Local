from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from suitelocal.application.auth import AuthService
from suitelocal.domain.auth import Session
from suitelocal.domain.business import (
    BUSINESS_TYPES,
    DEFAULT_BUSINESS_TYPE,
    DEFAULT_TAX_REGIME,
    TAX_REGIMES,
    requires_ruc,
)
from suitelocal.ui.components import InlineMessage
from suitelocal.ui.theme.icons import icon
from suitelocal.ui.theme.tokens import TOKENS


def add_field(form: QFormLayout, label: str, field: QLineEdit) -> None:
    field.setMinimumHeight(40)
    field.setObjectName("authField")
    form.addRow(QLabel(label), field)


def build_brand_panel() -> QWidget:
    panel = QWidget()
    panel.setObjectName("authBrandPanel")
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(44, 44, 44, 44)
    layout.setSpacing(18)
    logo = QLabel("SL")
    logo.setObjectName("authLogo")
    logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
    title = QLabel("SuiteLocal")
    title.setObjectName("authBrandTitle")
    message = QLabel("Tu tienda, siempre en orden.")
    message.setObjectName("authBrandText")
    message.setWordWrap(True)
    layout.addWidget(logo, 0, Qt.AlignmentFlag.AlignLeft)
    layout.addStretch()
    layout.addWidget(title)
    layout.addWidget(message)
    for benefit in ("Rápido para vender", "Funciona sin internet", "Tus datos quedan contigo"):
        mark = QLabel()
        mark.setPixmap(icon("check", TOKENS.surface, 16).pixmap(QSize(16, 16)))
        label = QLabel(benefit)
        label.setObjectName("authBenefit")
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(mark)
        row.addWidget(label, 1)
        layout.addLayout(row)
    layout.addStretch()
    return panel


def configure_dialog(dialog: QDialog, title: str, subtitle: str, height: int = 520) -> QVBoxLayout:
    dialog.setWindowTitle(title)
    dialog.setFixedSize(820, height)
    dialog.setObjectName("authDialog")
    root = QHBoxLayout(dialog)
    root.setContentsMargins(0, 0, 0, 0)
    root.addWidget(build_brand_panel(), 55)
    form_panel = QWidget()
    layout = QVBoxLayout(form_panel)
    layout.setContentsMargins(48, 42, 48, 42)
    layout.setSpacing(14)
    heading = QLabel(title)
    heading.setObjectName("authTitle")
    description = QLabel(subtitle)
    description.setObjectName("authSubtitle")
    description.setWordWrap(True)
    layout.addWidget(heading)
    layout.addWidget(description)
    root.addWidget(form_panel, 45)
    return layout


class SetupDialog(QDialog):
    def __init__(self, auth: AuthService) -> None:
        super().__init__()
        self.auth = auth
        layout = configure_dialog(
            self,
            "Configura tu negocio",
            "Crea el acceso principal para comenzar a usar SuiteLocal.",
            height=700,
        )
        self.business = QLineEdit()
        self.business.setPlaceholderText("Nombre del negocio")
        self.business_type = QComboBox()
        for code, label in BUSINESS_TYPES.items():
            self.business_type.addItem(label, code)
        self.business_type.setCurrentIndex(self.business_type.findData(DEFAULT_BUSINESS_TYPE))
        self.regime = QComboBox()
        for code, label in TAX_REGIMES.items():
            self.regime.addItem(label, code)
        self.regime.setCurrentIndex(self.regime.findData(DEFAULT_TAX_REGIME))
        self.ruc = QLineEdit()
        self.ruc.setMaxLength(13)
        self.ruc.setPlaceholderText("13 dígitos")
        for combo in (self.business_type, self.regime):
            combo.setMinimumHeight(40)
        self.username = QLineEdit()
        self.username.setPlaceholderText("Usuario dueño")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Mínimo 8 caracteres")
        self.password_confirmation = QLineEdit()
        self.password_confirmation.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_confirmation.setPlaceholderText("Repite la contraseña")
        self.message = InlineMessage()
        save = QPushButton("Crear instalación")
        save.setObjectName("authButton")
        save.clicked.connect(self.create_owner)
        form = QFormLayout()
        form.setVerticalSpacing(12)
        add_field(form, "Negocio", self.business)
        form.addRow(QLabel("Tipo de negocio"), self.business_type)
        form.addRow(QLabel("Régimen"), self.regime)
        self.ruc_label = QLabel("RUC")
        self.ruc.setMinimumHeight(40)
        self.ruc.setObjectName("authField")
        form.addRow(self.ruc_label, self.ruc)
        add_field(form, "Usuario dueño", self.username)
        add_field(form, "Contraseña", self.password)
        add_field(form, "Confirmar contraseña", self.password_confirmation)
        layout.addSpacing(20)
        layout.addLayout(form)
        layout.addWidget(self.message)
        layout.addWidget(save)
        layout.addStretch()
        self.regime.currentIndexChanged.connect(self._update_ruc_visibility)
        self._update_ruc_visibility()

    def _update_ruc_visibility(self) -> None:
        """Ask for the RUC only in the regimes that must issue electronic invoices."""
        required = requires_ruc(self.regime.currentData())
        self.ruc_label.setVisible(required)
        self.ruc.setVisible(required)

    def create_owner(self) -> None:
        try:
            self.auth.setup_owner(
                self.business.text(),
                self.username.text(),
                self.password.text(),
                self.password_confirmation.text(),
                business_type=self.business_type.currentData(),
                tax_regime=self.regime.currentData(),
                ruc=self.ruc.text() if requires_ruc(self.regime.currentData()) else "",
            )
        except ValueError as error:
            self.message.show_error(str(error))
            return
        self.accept()


class LoginDialog(QDialog):
    def __init__(self, auth: AuthService) -> None:
        super().__init__()
        self.auth = auth
        self.session: Session | None = None
        layout = configure_dialog(
            self,
            "Bienvenido",
            "Ingresa tus credenciales para administrar tu negocio.",
        )
        self.username = QLineEdit()
        self.username.setPlaceholderText("Escribe tu usuario")
        self.password = QLineEdit()
        self.password.setPlaceholderText("Escribe tu contraseña")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.error_label = QLabel()
        self.error_label.setObjectName("authError")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        login = QPushButton("Iniciar sesión")
        login.setObjectName("authButton")
        login.clicked.connect(self.login)
        self.password.returnPressed.connect(self.login)
        self.username.returnPressed.connect(self.password.setFocus)
        form = QFormLayout()
        form.setVerticalSpacing(12)
        add_field(form, "Usuario", self.username)
        add_field(form, "Contraseña", self.password)
        layout.addSpacing(20)
        layout.addLayout(form)
        layout.addWidget(self.error_label)
        layout.addWidget(login)
        version = QLabel("SuiteLocal · Ventas e inventario sin internet")
        version.setObjectName("authVersion")
        layout.addStretch()
        layout.addWidget(version)
        self.username.setFocus()

    def login(self) -> None:
        self.error_label.hide()
        try:
            self.session = self.auth.authenticate(
                self.username.text(),
                self.password.text(),
            )
        except ValueError as error:
            self.error_label.setText(str(error))
            self.error_label.show()
            return
        self.accept()
