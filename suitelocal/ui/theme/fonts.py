from pathlib import Path

from PySide6.QtGui import QFontDatabase


def load_inter_font(font_directory: Path | None = None) -> str:
    directory = font_directory or Path(__file__).parents[3] / "assets" / "fonts"
    if not directory.exists():
        return "Segoe UI"
    for font_path in sorted(directory.glob("Inter*.ttf")):
        if QFontDatabase.addApplicationFont(str(font_path)) >= 0:
            return "Inter"
    return "Segoe UI"
