from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

ICONS: dict[str, str] = {
    "search": '<path d="m21 21-4.3-4.3M10.8 18a7.2 7.2 0 1 1 0-14.4 7.2 7.2 0 0 1 0 14.4Z"/>',
    "check": '<path d="m5 12 4 4L19 6"/>',
    "close": '<path d="M6 6l12 12M18 6 6 18"/>',
    "box": '<path d="m3 7 9-4 9 4v10l-9 4-9-4V7Zm9-4v18M3 7l9 4 9-4"/>',
    "dashboard": (
        '<rect x="3" y="3" width="7" height="7" rx="1"/>'
        '<rect x="14" y="3" width="7" height="7" rx="1"/>'
        '<rect x="3" y="14" width="7" height="7" rx="1"/>'
        '<rect x="14" y="14" width="7" height="7" rx="1"/>'
    ),
    "cash": '<rect x="3" y="6" width="18" height="12" rx="2"/><circle cx="12" cy="12" r="3"/>',
    "settings": (
        '<path d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z"/>'
        '<path d="m19.4 15 .1.1a2 2 0 1 1-2.8 2.8l-.1-.1a2 2 0 0 0-3.4 1.4'
        "v.3a2 2 0 1 1-4 0v-.2A2 2 0 0 0 5.8 18l-.1.1a2 2 0 1 1-2.8-2.8"
        "l.1-.1A2 2 0 0 0 1.6 12a2 2 0 1 1 4 0 2 2 0 0 0 3.4-1.4v-.3"
        'a2 2 0 1 1 4 0v.2a2 2 0 0 0 3.4 1.4l.1-.1a2 2 0 1 1 2.8 2.8Z"/>'
    ),
    "calendar": (
        '<rect x="3" y="4" width="18" height="17" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>'
    ),
    "users": (
        '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2'
        "m8-10a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm8 10v-2a4 4 0 0 0-3-3.87"
        'M16 3.13a4 4 0 0 1 0 7.75"/>'
    ),
    "table": '<rect x="3" y="6" width="18" height="4" rx="1"/><path d="M6 10v9M18 10v9"/>',
    "logout": '<path d="M10 17l5-5-5-5M15 12H3M21 19V5a2 2 0 0 0-2-2h-6"/>',
    "moon": '<path d="M21 13A9 9 0 1 1 11 3a7 7 0 0 0 10 10Z"/>',
    "sun": (
        '<circle cx="12" cy="12" r="4"/>'
        '<path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2'
        'M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>'
    ),
}


def svg_markup(name: str, color: str, size: int, stroke_width: float = 1.75) -> str:
    path = ICONS.get(name)
    if path is None:
        raise ValueError(f"Icono no registrado: {name}")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="{stroke_width}" '
        f'stroke-linecap="round" stroke-linejoin="round">{path}</svg>'
    )


def icon_file(name: str, color: str, size: int, stroke_width: float = 1.75) -> Path:
    """Write an icon as an SVG file so Qt style sheets can reference it by path."""
    svg = svg_markup(name, color, size, stroke_width)
    digest = hashlib.sha256(svg.encode("utf-8")).hexdigest()[:12]
    directory = Path(tempfile.gettempdir()) / "suitelocal-icons"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{name}-{digest}.svg"
    if not target.exists():
        target.write_text(svg, encoding="utf-8")
    return target


def _pixmap(name: str, color: str, size: int) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(svg_markup(name, color, size).encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return pixmap


def icon(
    name: str, color: str | None = None, size: int = 20, selected_color: str | None = None
) -> QIcon:
    """Render an icon; ``color`` defaults to the active theme's accent.

    ``selected_color`` paints the variant item views use for the selected row.
    """
    from suitelocal.ui.theme.manager import current_tokens

    result = QIcon(_pixmap(name, color or current_tokens().brand_500, size))
    if selected_color is not None:
        result.addPixmap(_pixmap(name, selected_color, size), QIcon.Mode.Selected)
    return result
