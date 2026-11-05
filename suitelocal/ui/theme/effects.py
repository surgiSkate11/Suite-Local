from __future__ import annotations

from typing import Literal
from weakref import WeakKeyDictionary

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget

from suitelocal.ui.theme.tokens import DesignTokens

Elevation = Literal["e1", "e2", "e3"]

_SETTINGS: dict[Elevation, tuple[int, int, float]] = {
    "e1": (1, 3, 0.06),
    "e2": (6, 20, 0.10),
    "e3": (16, 40, 0.16),
}
# Every live shadow with its level, so a theme change can repaint them in place.
_LIVE_EFFECTS: WeakKeyDictionary[QGraphicsDropShadowEffect, Elevation] = WeakKeyDictionary()


def _shadow_color(level: Elevation, tokens: DesignTokens) -> QColor:
    color = QColor(tokens.shadow_color)
    color.setAlpha(min(255, round(_SETTINGS[level][2] * tokens.shadow_strength * 255)))
    return color


def apply_elevation(widget: QWidget, level: Elevation = "e1") -> QGraphicsDropShadowEffect:
    from suitelocal.ui.theme.manager import current_tokens

    offset, blur, _ = _SETTINGS[level]
    effect = QGraphicsDropShadowEffect(widget)
    effect.setOffset(0, offset)
    effect.setBlurRadius(blur)
    effect.setColor(_shadow_color(level, current_tokens()))
    widget.setGraphicsEffect(effect)
    _LIVE_EFFECTS[effect] = level
    return effect


def refresh_elevations(tokens: DesignTokens) -> None:
    """Recolor every shadow created by ``apply_elevation`` for the given theme."""
    for effect, level in list(_LIVE_EFFECTS.items()):
        try:
            effect.setColor(_shadow_color(level, tokens))
        except RuntimeError:  # the C++ effect was destroyed with its widget
            continue
