from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from suitelocal.ui.theme.icons import icon
from suitelocal.ui.theme.manager import current_tokens, theme_manager


class AppDialog(QDialog):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("appDialog")
        self.setModal(True)
        self.setWindowTitle(title)
        self.setMinimumWidth(440)
        self.content = QVBoxLayout(self)
        self.content.setContentsMargins(28, 24, 28, 24)
        self.content.setSpacing(16)
        heading = QLabel(title)
        heading.setObjectName("dialogTitle")
        self.content.addWidget(heading)


class Drawer(QFrame):
    def __init__(
        self,
        title: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("drawer")
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        self.content_layout = layout
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        header = QHBoxLayout()
        self.heading = QLabel(title)
        self.heading.setObjectName("drawerTitle")
        close = QPushButton()
        self._close_button = close
        close.setObjectName("drawerClose")
        self._refresh_icon()
        theme_manager().theme_changed.connect(self._refresh_icon)
        close.setFixedSize(40, 40)
        close.setAccessibleName("Cerrar panel")
        close.setToolTip("Cerrar panel (Esc)")
        close.clicked.connect(self.hide)
        escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        escape.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        escape.activated.connect(self.hide)
        header.addWidget(self.heading)
        header.addStretch()
        header.addWidget(close)
        layout.addLayout(header)

    def _refresh_icon(self, _theme: str = "") -> None:
        self._close_button.setIcon(icon("close", current_tokens().text_500, 18))

    def set_title(self, title: str) -> None:
        self.heading.setText(title)
        self.setAccessibleName(title)

    def open_with_focus(self, field: QWidget) -> None:
        """Show the drawer and move the keyboard focus to its first useful field."""
        self.show()
        field.setFocus(Qt.FocusReason.PopupFocusReason)


def build_confirmation(parent: QWidget | None, title: str, text: str) -> QMessageBox:
    """Build a Spanish yes/no confirmation where "No" is the safe default."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(title)
    box.setText(text)
    yes = box.addButton("Sí", QMessageBox.ButtonRole.AcceptRole)
    yes.setObjectName("dangerAction")
    no = box.addButton("No", QMessageBox.ButtonRole.RejectRole)
    no.setObjectName("secondaryAction")
    box.setDefaultButton(no)
    box.setEscapeButton(no)
    return box


def confirm_action(parent: QWidget | None, title: str, text: str) -> bool:
    box = build_confirmation(parent, title, text)
    box.exec()
    return box.buttonRole(box.clickedButton()) == QMessageBox.ButtonRole.AcceptRole
