from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class EmptyState(QFrame):
    def __init__(
        self,
        title: str,
        description: str,
        action_text: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("emptyState")
        self.action: QPushButton | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        title_label = QLabel(title)
        title_label.setObjectName("emptyTitle")
        title_label.setWordWrap(True)
        title_label.setMinimumWidth(0)
        description_label = QLabel(description)
        description_label.setObjectName("emptyDescription")
        description_label.setWordWrap(True)
        description_label.setMinimumWidth(0)
        layout.addWidget(title_label)
        layout.addWidget(description_label)
        if action_text:
            self.action = QPushButton(action_text)
            self.action.setObjectName("secondaryAction")
            layout.addWidget(self.action, 0)


class Skeleton(QFrame):
    def __init__(self, height: int = 20, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("skeleton")
        self.setMinimumHeight(height)


class Toast(QFrame):
    def __init__(
        self,
        message: str,
        state: str = "success",
        *,
        persistent: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("toast")
        self.setProperty("state", state)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        label = QLabel(message)
        label.setWordWrap(True)
        layout.addWidget(label)
        if not persistent:
            QTimer.singleShot(4000, self.deleteLater)
