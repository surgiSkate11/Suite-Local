from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from suitelocal.ui.theme.effects import apply_elevation
from suitelocal.ui.theme.icons import icon
from suitelocal.ui.theme.tokens import TOKENS


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


class InlineMessage(QLabel):
    """Inline feedback next to a form; red for errors, green for confirmations."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("inlineMessage")
        self.setWordWrap(True)
        self.setMinimumWidth(0)
        self.hide()

    def show_success(self, text: str) -> None:
        self._show(text, "success")

    def show_error(self, text: str) -> None:
        self._show(text, "error")

    def clear_message(self) -> None:
        self.clear()
        self.hide()

    def _show(self, text: str, state: str) -> None:
        self.setText(text)
        self.setProperty("state", state)
        self.style().unpolish(self)
        self.style().polish(self)
        self.show()


class Toast(QFrame):
    closed = Signal()

    def __init__(
        self,
        message: str,
        state: str = "success",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.message = message
        self.setObjectName("toast")
        self.setProperty("state", state)
        self.setAccessibleName(message)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 8, 12)
        layout.setSpacing(8)
        label = QLabel(message)
        label.setObjectName("toastText")
        label.setWordWrap(True)
        close = QPushButton()
        close.setObjectName("toastClose")
        close.setIcon(icon("close", TOKENS.text_500, 16))
        close.setFixedSize(QSize(28, 28))
        close.setAccessibleName("Cerrar aviso")
        close.setToolTip("Cerrar aviso")
        close.clicked.connect(self.dismiss)
        layout.addWidget(label, 1)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)

    def dismiss(self) -> None:
        if self.isHidden():
            return
        self.hide()
        self.closed.emit()
        self.deleteLater()


class ToastHost(QWidget):
    """Stacks toasts in the bottom-right corner of its parent."""

    MAX_VISIBLE = 3
    MARGIN = 24
    WIDTH = 360

    def __init__(self, parent: QWidget, duration_ms: int = 4000) -> None:
        super().__init__(parent)
        self.setObjectName("toastHost")
        self.duration_ms = duration_ms
        self._toasts: list[Toast] = []
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)
        self._layout.addStretch()
        parent.installEventFilter(self)
        self.hide()

    def show_toast(
        self, message: str, state: str = "success", *, persistent: bool = False
    ) -> Toast:
        """Show a toast that closes itself unless it reports a persistence error."""
        toast = Toast(message, state, self)
        apply_elevation(toast, "e2")
        toast.closed.connect(lambda: self._forget(toast))
        self._toasts.append(toast)
        self._layout.addWidget(toast)
        while len(self._toasts) > self.MAX_VISIBLE:
            self._toasts[0].dismiss()
        if not persistent:
            QTimer.singleShot(self.duration_ms, toast, toast.dismiss)
        self.show()
        self.raise_()
        self.reposition()
        return toast

    def _forget(self, toast: Toast) -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
        if not self._toasts:
            self.hide()
        else:
            self.reposition()

    def reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        width = min(self.WIDTH, max(parent.width() - 2 * self.MARGIN, 0))
        height = self._layout.sizeHint().height()
        self.setGeometry(
            parent.width() - width - self.MARGIN,
            parent.height() - height - self.MARGIN,
            width,
            height,
        )

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self.reposition()
        return False
