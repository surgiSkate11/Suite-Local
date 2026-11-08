"""Code 128 barcodes in pure Python: encoding (code sets B and C) and drawing on a QImage."""

import re

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage, QPainter

__all__ = ["code128_symbols", "code128_widths", "render_code128"]

# Bar/space widths (in modules) of the 106 symbols, starting with a bar, then the stop symbol.
_PATTERNS = (
    "212222 222122 222221 121223 121322 131222 122213 122312 132212 221213 "
    "221312 231212 112232 122132 122231 113222 123122 123221 223211 221132 "
    "221231 213212 223112 312131 311222 321122 321221 312212 322112 322211 "
    "212123 212321 232121 111323 131123 131321 112313 132113 132311 211313 "
    "231113 231311 112133 112331 132131 113123 113321 133121 313121 211331 "
    "231131 213113 213311 213131 311123 311321 331121 312113 312311 332111 "
    "314111 221411 431111 111224 111422 121124 121421 141122 141221 112214 "
    "112412 122114 122411 142112 142211 241211 221114 413111 241112 134111 "
    "111242 121142 121241 114212 124112 124211 411212 421112 421211 212141 "
    "214121 412121 111143 111341 131141 114113 114311 411113 411311 113141 "
    "114131 311141 411131 211412 211214 211232 2331112"
).split()
CODE_B = 100
CODE_C = 99
START_B = 104
START_C = 105
STOP = 106
# Digit runs shorter than this are not worth a code set change.
_MIN_CODE_C_RUN = 4
_SEGMENTS = re.compile(rf"\d{{{_MIN_CODE_C_RUN},}}|\D+|\d+")
QUIET_MODULES = 10


def code128_symbols(text: str) -> tuple[int, ...]:
    """Symbol values of `text`: start, data, checksum and stop.

    Digit runs of four or more use code set C (two digits per symbol) and everything else uses
    code set B (ASCII 32 to 126). An odd digit run keeps its first digit in set B.
    """
    if not text:
        raise ValueError("El código de barras no puede estar vacío.")
    if any(not 32 <= ord(character) <= 126 for character in text):
        raise ValueError("El código de barras solo admite caracteres ASCII imprimibles.")
    values: list[int] = []
    current = ""

    def use(code_set: str) -> None:
        nonlocal current
        if current == code_set:
            return
        if not current:
            values.append(START_C if code_set == "C" else START_B)
        else:
            values.append(CODE_C if code_set == "C" else CODE_B)
        current = code_set

    for match in _SEGMENTS.finditer(text):
        chunk = match.group()
        if chunk.isdigit() and len(chunk) >= _MIN_CODE_C_RUN:
            if len(chunk) % 2:
                use("B")
                values.append(ord(chunk[0]) - 32)
                chunk = chunk[1:]
            use("C")
            values.extend(int(chunk[index : index + 2]) for index in range(0, len(chunk), 2))
        else:
            use("B")
            values.extend(ord(character) - 32 for character in chunk)
    checksum = values[0] + sum(position * value for position, value in enumerate(values[1:], 1))
    values.append(checksum % 103)
    values.append(STOP)
    return tuple(values)


def code128_widths(text: str) -> tuple[int, ...]:
    """Alternating bar and space widths in modules, beginning with a bar, stop included."""
    return tuple(int(width) for value in code128_symbols(text) for width in _PATTERNS[value])


def render_code128(
    text: str, module_px: int, height_px: int, *, quiet_modules: int = QUIET_MODULES
) -> QImage:
    """Black bars on a white image with a quiet zone on both sides."""
    if module_px < 1 or height_px < 1:
        raise ValueError("El módulo y la altura del código de barras deben ser positivos.")
    widths = code128_widths(text)
    image = QImage(
        (sum(widths) + 2 * quiet_modules) * module_px, height_px, QImage.Format.Format_RGB32
    )
    image.fill(QColor("white"))
    painter = QPainter(image)
    try:
        x = quiet_modules * module_px
        for index, width in enumerate(widths):
            if index % 2 == 0:
                painter.fillRect(QRect(x, 0, width * module_px, height_px), QColor("black"))
            x += width * module_px
    finally:
        painter.end()
    return image
