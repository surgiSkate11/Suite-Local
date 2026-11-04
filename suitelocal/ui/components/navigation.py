from PySide6.QtWidgets import QLabel, QListWidget


class Sidebar(QListWidget):
    def __init__(self, parent: QListWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("componentSidebar")


class Topbar(QLabel):
    def __init__(self, text: str = "", parent: QLabel | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("componentTopbar")
