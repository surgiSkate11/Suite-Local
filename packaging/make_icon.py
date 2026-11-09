"""Draw the application icon with Qt and save it as packaging/suitelocal.ico (and a PNG)."""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter  # noqa: E402

SIZE = 256


def draw_icon() -> QImage:
    image = QImage(SIZE, SIZE, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#2563EB"))
    painter.drawRoundedRect(QRectF(8, 8, SIZE - 16, SIZE - 16), 52, 52)
    font = QFont("Segoe UI", 120)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor("#FFFFFF"))
    painter.drawText(QRectF(0, 0, SIZE, SIZE), Qt.AlignmentFlag.AlignCenter, "SL")
    painter.end()
    return image


def main() -> int:
    _app = QGuiApplication(sys.argv)
    folder = Path(__file__).parent
    image = draw_icon()
    image.save(str(folder / "suitelocal.png"), "PNG")
    if not image.save(str(folder / "suitelocal.ico"), "ICO"):
        print("No se pudo escribir el .ico", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
