from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QWidget


class StatusBadge(QLabel):
    def __init__(self, text: str, state: str = "info", parent: QLabel | None = None) -> None:
        super().__init__(f"•  {text}", parent)
        self.setObjectName("statusBadge")
        self.setProperty("state", state)


class KeyHint(QLabel):
    """Keyboard shortcut hint drawn like a key cap, e.g. ``F4``."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setProperty("role", "kbd")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
