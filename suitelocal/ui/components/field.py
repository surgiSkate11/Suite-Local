from PySide6.QtWidgets import QLineEdit

from suitelocal.ui.theme.icons import icon


class TextField(QLineEdit):
    def __init__(
        self,
        placeholder: str = "",
        parent: QLineEdit | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("textField")
        self.setPlaceholderText(placeholder)
        self.setMinimumHeight(40)

    def set_error(self, message: str | None) -> None:
        self.setProperty("state", "error" if message else "default")
        self.setToolTip(message or "")
        self.style().unpolish(self)
        self.style().polish(self)


class SearchField(TextField):
    def __init__(
        self,
        placeholder: str = "Buscar...",
        parent: QLineEdit | None = None,
    ) -> None:
        super().__init__(placeholder, parent)
        self.setObjectName("searchField")
        self.addAction(icon("search"), QLineEdit.ActionPosition.LeadingPosition)
