from PySide6.QtWidgets import QLabel


class StatusBadge(QLabel):
    def __init__(self, text: str, state: str = "info", parent: QLabel | None = None) -> None:
        super().__init__(f"•  {text}", parent)
        self.setObjectName("statusBadge")
        self.setProperty("state", state)
