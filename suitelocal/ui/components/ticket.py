"""One line of the floating sale ticket: thumb, name, "qty × price", total and stepper."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QWidget

from suitelocal.domain.models import Product
from suitelocal.ui.components.elided import ElidedLabel
from suitelocal.ui.components.product import make_art_label, repolish


class TicketLine(QFrame):
    selected = Signal(int)
    quantity_step = Signal(int, int)

    def __init__(
        self,
        product: Product,
        quantity: int,
        unit_text: str,
        total_text: str,
        highlighted: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.product_id = product.id
        self.setObjectName("ticketLine")
        self.setProperty("highlighted", highlighted)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QGridLayout(self)
        layout.setContentsMargins(10, 9, 14, 9)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(2)
        self.thumb = make_art_label(product, "thumb")
        self.thumb.setFixedSize(36, 36)
        self.name_label = ElidedLabel(product.name)
        self.name_label.setObjectName("lineName")
        self.total_label = QLabel(total_text)
        self.total_label.setObjectName("lineTotal")
        self.total_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.subtitle_label = QLabel(f"{quantity} × {unit_text}")
        self.subtitle_label.setObjectName("lineSub")
        self.minus_button = self._step_button("−", "Quitar uno", -1)
        self.plus_button = self._step_button("+", "Agregar uno", 1)
        self.quantity_label = QLabel(str(quantity))
        self.quantity_label.setObjectName("stepQty")
        self.quantity_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.quantity_label.setMinimumWidth(22)
        stepper = QFrame()
        stepper.setObjectName("stepper")
        stepper_layout = QHBoxLayout(stepper)
        stepper_layout.setContentsMargins(2, 2, 2, 2)
        stepper_layout.setSpacing(0)
        stepper_layout.addWidget(self.minus_button)
        stepper_layout.addWidget(self.quantity_label)
        stepper_layout.addWidget(self.plus_button)
        layout.addWidget(self.thumb, 0, 0, 2, 1)
        layout.addWidget(self.name_label, 0, 1)
        layout.addWidget(self.total_label, 0, 2)
        layout.addWidget(self.subtitle_label, 1, 1)
        layout.addWidget(stepper, 1, 2, Qt.AlignmentFlag.AlignRight)
        layout.setColumnStretch(1, 1)

    def _step_button(self, text: str, tooltip: str, step: int) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("stepButton")
        button.setFixedSize(26, 26)
        button.setAccessibleName(tooltip)
        button.setToolTip(tooltip)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(
            lambda _checked=False: self.quantity_step.emit(self.product_id, step)
        )
        return button

    def set_highlighted(self, highlighted: bool) -> None:
        self.setProperty("highlighted", highlighted)
        repolish(self)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.selected.emit(self.product_id)
        super().mousePressEvent(event)
