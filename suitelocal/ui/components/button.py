from PySide6.QtWidgets import QPushButton


class PrimaryButton(QPushButton):
    def __init__(self, text: str, parent: QPushButton | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("primaryAction")
        self.setProperty("variant", "primary")


class SecondaryButton(QPushButton):
    def __init__(self, text: str, parent: QPushButton | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("secondaryAction")
        self.setProperty("variant", "secondary")
