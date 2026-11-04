import re
from pathlib import Path

import pytest

from suitelocal.ui.theme.qss import build_stylesheet
from suitelocal.ui.theme.tokens import TOKENS


def relative_luminance(color: str) -> float:
    channels = [int(color.lstrip("#")[index : index + 2], 16) / 255 for index in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(foreground: str, background: str) -> float:
    lighter, darker = sorted(
        (relative_luminance(foreground), relative_luminance(background)), reverse=True
    )
    return (lighter + 0.05) / (darker + 0.05)


TEXT_PAIRS = [
    ("text_900", "background"),
    ("text_700", "surface"),
    ("text_500", "surface"),
    ("text_500", "background"),
    ("text_500", "brand_100"),
    ("success", "surface"),
    ("success", "success_background"),
    ("warning", "warning_background"),
    ("danger", "danger_background"),
    ("danger", "surface"),
    ("info", "info_background"),
    ("brand_600", "brand_50"),
    ("surface", "brand_500"),
]


@pytest.mark.parametrize(("foreground", "background"), TEXT_PAIRS)
def test_text_tokens_meet_wcag_aa(foreground, background):
    ratio = contrast_ratio(getattr(TOKENS, foreground), getattr(TOKENS, background))

    assert ratio >= 4.5, f"{foreground} on {background} is {ratio:.2f}:1"


def test_input_border_meets_non_text_contrast():
    ratio = contrast_ratio(TOKENS.border_input, TOKENS.surface)

    assert ratio >= 3.0, f"border_input on surface is {ratio:.2f}:1"


def test_text_inputs_use_the_accessible_border():
    stylesheet = build_stylesheet()

    assert f"border: 1px solid {TOKENS.border_input}" in stylesheet


def test_ui_has_no_hard_coded_hex_colors_outside_tokens():
    ui_root = Path(__file__).resolve().parents[1] / "suitelocal" / "ui"
    hex_color = re.compile(r"[\"'\s:]#[0-9A-Fa-f]{6}\b")
    offenders = [
        f"{path.relative_to(ui_root)}:{number}"
        for path in ui_root.rglob("*.py")
        if path.name != "tokens.py"
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if hex_color.search(line)
    ]

    assert offenders == []


def test_checked_checkbox_draws_a_white_check_mark():
    stylesheet = build_stylesheet()
    block = stylesheet.split("QCheckBox::indicator:checked {", 1)[1].split("}", 1)[0]
    match = re.search(r"image: url\(([^)]+)\)", block)

    assert match is not None
    svg = Path(match.group(1)).read_text(encoding="utf-8")
    assert f'stroke="{TOKENS.surface}"' in svg
    assert "m5 12 4 4L19 6" in svg
