from PySide6.QtWidgets import QPushButton, QWidget


class PrimaryButton(QPushButton):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("primaryAction")
        self.setProperty("variant", "primary")


class SecondaryButton(QPushButton):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("secondaryAction")
        self.setProperty("variant", "secondary")


class DangerButton(QPushButton):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setProperty("variant", "danger")


def set_variant(button: QPushButton, variant: str) -> QPushButton:
    """Apply a visual variant: primary, secondary, danger or ghost."""
    button.setProperty("variant", variant)
    return button
