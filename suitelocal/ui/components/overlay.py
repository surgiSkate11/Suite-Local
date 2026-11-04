from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


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
        heading = QLabel(title)
        heading.setObjectName("drawerTitle")
        close = QPushButton("×")
        close.setObjectName("ghostButton")
        close.setFixedSize(32, 32)
        close.clicked.connect(self.hide)
        header.addWidget(heading)
        header.addStretch()
        header.addWidget(close)
        layout.addLayout(header)
