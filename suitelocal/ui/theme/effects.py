from typing import Literal

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget

Elevation = Literal["e1", "e2", "e3"]


def apply_elevation(widget: QWidget, level: Elevation = "e1") -> QGraphicsDropShadowEffect:
    settings = {
        "e1": (1, 3, 0.06),
        "e2": (6, 20, 0.10),
        "e3": (16, 40, 0.16),
    }
    offset, blur, opacity = settings[level]
    effect = QGraphicsDropShadowEffect(widget)
    effect.setOffset(0, offset)
    effect.setBlurRadius(blur)
    effect.setColor(QColor(15, 27, 61, round(opacity * 255)))
    widget.setGraphicsEffect(effect)
    return effect
