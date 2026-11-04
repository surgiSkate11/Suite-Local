from PySide6.QtWidgets import QVBoxLayout, QWidget

from suitelocal.ui.theme.effects import apply_elevation


class Card(QWidget):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        elevated: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("surfaceCard")
        self.content_layout = QVBoxLayout(self)
        self.content_layout.setContentsMargins(20, 20, 20, 20)
        self.content_layout.setSpacing(12)
        if elevated:
            apply_elevation(self, "e1")
