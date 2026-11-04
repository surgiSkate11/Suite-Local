from PySide6.QtCore import Qt, Signal
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

from suitelocal.application.auth import AuthService
from suitelocal.domain.auth import Session
from suitelocal.ui.components import (
    DataTable,
    Drawer,
    EmptyState,
    InlineMessage,
    StatusBadge,
    confirm_action,
)


class UsersWidget(QWidget):
    notification = Signal(str, str)

    def __init__(
        self,
        auth: AuthService,
        session: Session,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.auth = auth
        self.session = session
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_confirmation = QLineEdit()
        self.password_confirmation.setEchoMode(QLineEdit.EchoMode.Password)
        create = QPushButton("Crear cajero")
        create.clicked.connect(self.create_cashier)
        deactivate = QPushButton("Desactivar seleccionado")
        deactivate.setObjectName("secondaryAction")
        deactivate.clicked.connect(self.deactivate_selected)
        self.message = InlineMessage()
        form = QFormLayout()
        form.addRow("Usuario:", self.username)
        form.addRow("Contraseña:", self.password)
        form.addRow("Confirmar contraseña:", self.password_confirmation)
        self.drawer = Drawer("Nuevo cajero", self)
        self.drawer.content_layout.addLayout(form)
        self.drawer.content_layout.addWidget(create)
        self.drawer.content_layout.addWidget(self.message)
        self.drawer.hide()
        self.table = DataTable(3, ["Usuario", "Rol", "Estado"])
        self.empty_state = EmptyState(
            "Solo está configurado el dueño",
            "Crea un cajero para repartir la operación del negocio con seguridad.",
            "Crear cajero",
        )
        self.empty_state.hide()
        if self.empty_state.action is not None:
            self.empty_state.action.clicked.connect(self.open_new_user)
        new_user = QPushButton("Nuevo cajero")
        new_user.setObjectName("primaryAction")
        new_user.clicked.connect(self.open_new_user)
        title = QLabel("Usuarios y accesos")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Controla quién puede operar el sistema y con qué rol.")
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        subtitle.setMinimumWidth(0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 28, 30, 30)
        layout.setSpacing(16)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        toolbar = QHBoxLayout()
        self.result_count = QLabel()
        self.result_count.setObjectName("resultCount")
        toolbar.addWidget(self.result_count)
        toolbar.addStretch()
        toolbar.addWidget(new_user)
        layout.addLayout(toolbar)
        table_card = QFrame()
        table_card.setObjectName("contentCard")
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(18, 16, 18, 16)
        table_layout.addWidget(self.table)
        layout.addWidget(table_card)
        layout.addWidget(deactivate)
        layout.addWidget(self.empty_state)
        layout.addWidget(self.drawer)
        self.refresh()

    def refresh(self) -> None:
        users = self.auth.list_users(self.session)
        self.table.setRowCount(0)
        for user in users:
            row = self.table.rowCount()
            self.table.insertRow(row)
            username = QTableWidgetItem(user.username)
            username.setData(Qt.ItemDataRole.UserRole, user.id)
            self.table.setItem(row, 0, username)
            role = "Dueño" if user.role == "owner" else "Cajero"
            self.table.setItem(row, 1, QTableWidgetItem(role))
            self.table.setCellWidget(
                row,
                2,
                StatusBadge(
                    "Activo" if user.active else "Inactivo",
                    "success" if user.active else "info",
                ),
            )
        self.empty_state.setVisible(len(users) <= 1)
        self.result_count.setText(f"{len(users)} usuario{'s' if len(users) != 1 else ''}")

    def open_new_user(self) -> None:
        self.drawer.show()

    def create_cashier(self) -> None:
        username = self.username.text().strip()
        try:
            self.auth.create_cashier(
                self.session,
                username,
                self.password.text(),
                self.password_confirmation.text(),
            )
        except ValueError as error:
            self.message.show_error(str(error))
            return
        self.message.clear_message()
        self.username.clear()
        self.password.clear()
        self.password_confirmation.clear()
        self.notification.emit(f"{username} ya puede iniciar sesión como cajero.", "success")
        self.drawer.hide()
        self.refresh()

    def deactivate_selected(self) -> None:
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        if item is None:
            self.notification.emit("Selecciona un cajero de la tabla.", "info")
            return
        if not confirm_action(
            self,
            "Desactivar cajero",
            f"¿Desactivar a {item.text()}? Ya no podrá iniciar sesión.",
        ):
            return
        try:
            user_id = item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(user_id, int):
                self.notification.emit("No se pudo identificar el usuario.", "danger")
                return
            self.auth.deactivate_user(self.session, user_id)
        except ValueError as error:
            self.notification.emit(str(error), "danger")
            return
        self.notification.emit(f"{item.text()} fue desactivado.", "success")
        self.refresh()
