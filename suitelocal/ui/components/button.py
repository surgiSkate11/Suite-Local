from PySide6.QtCore import QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QPushButton,
    QWidget,
)

from suitelocal.ui.theme.manager import current_tokens


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


class SwitchButton(QCheckBox):
    """Checkbox painted as an on/off switch; the label sits to the right of the track."""

    TRACK_WIDTH = 38
    TRACK_HEIGHT = 22
    KNOB_SIZE = 16
    GAP = 10

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:
        label_width = self.fontMetrics().horizontalAdvance(self.text())
        return QSize(self.TRACK_WIDTH + self.GAP + label_width, 32)

    def hitButton(self, pos: QPoint) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(
            0, (self.height() - self.TRACK_HEIGHT) / 2, self.TRACK_WIDTH, self.TRACK_HEIGHT
        )
        tokens = current_tokens()
        if not self.isEnabled():
            track_color = tokens.border_strong
        else:
            track_color = tokens.brand_800 if self.isChecked() else tokens.border_input
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(track_color))
        radius = self.TRACK_HEIGHT / 2
        painter.drawRoundedRect(track, radius, radius)
        inset = (self.TRACK_HEIGHT - self.KNOB_SIZE) / 2
        knob_x = track.right() - inset - self.KNOB_SIZE if self.isChecked() else track.x() + inset
        painter.setBrush(QColor(tokens.on_brand if self.isChecked() else tokens.surface))
        painter.drawEllipse(QRectF(knob_x, track.y() + inset, self.KNOB_SIZE, self.KNOB_SIZE))
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QColor(tokens.focus))
            painter.drawRoundedRect(track.adjusted(-2, -2, 2, 2), radius + 2, radius + 2)
        painter.setPen(QColor(tokens.text_700 if self.isEnabled() else tokens.text_400))
        text_rect = QRectF(
            self.TRACK_WIDTH + self.GAP,
            0,
            self.width() - self.TRACK_WIDTH - self.GAP,
            self.height(),
        )
        painter.drawText(
            text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text()
        )


class SegmentedControl(QFrame):
    """Exclusive row of pill options (filters, payment methods) on a sunken track."""

    selected = Signal(str)

    def __init__(
        self, options: list[str], current: str | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("segmented")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        for option in options:
            button = QPushButton(option)
            button.setCheckable(True)
            button.setProperty("variant", "segment")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, value=option: self.selected.emit(value))
            self._group.addButton(button)
            self._buttons[option] = button
            layout.addWidget(button)
        initial = current if current in self._buttons else (options[0] if options else None)
        if initial is not None:
            self._buttons[initial].setChecked(True)

    @property
    def current(self) -> str | None:
        checked = self._group.checkedButton()
        return None if checked is None else checked.text()

    def select(self, option: str) -> None:
        self._buttons[option].setChecked(True)
