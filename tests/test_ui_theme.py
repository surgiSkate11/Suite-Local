import re
from pathlib import Path

import pytest

from suitelocal.ui.theme.icons import ICONS, svg_markup
from suitelocal.ui.theme.qss import build_stylesheet
from suitelocal.ui.theme.tokens import DARK_TOKENS, LIGHT_TOKENS, TOKENS


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
    ("text_900", "surface"),
    ("text_900", "mist"),
    ("text_700", "surface"),
    ("text_700", "sunken"),
    ("text_700", "brand_50"),
    ("text_500", "surface"),
    ("text_500", "background"),
    ("text_500", "sunken"),
    ("text_500", "brand_100"),
    ("success", "surface"),
    ("success", "success_background"),
    ("success_strong", "success_background"),
    ("warning", "warning_background"),
    ("warning", "surface"),
    ("danger", "danger_background"),
    ("danger", "surface"),
    ("info", "info_background"),
    ("brand_600", "brand_50"),
    ("brand_500", "surface"),
    ("brand_500", "brand_100"),
    ("on_brand", "brand_500"),
    ("on_brand", "brand_600"),
    ("on_danger", "danger"),
    ("champagne_text", "champagne_background"),
    ("champagne_text", "surface"),
    ("on_champagne", "champagne_100"),
    ("on_champagne", "champagne_300"),
    ("on_champagne", "champagne_500"),
    ("on_champagne", "champagne_700"),
    ("hero_text", "hero"),
    ("hero_text", "hero_2"),
    ("hero_muted", "hero"),
    ("hero_muted", "hero_2"),
    ("rail_text", "rail"),
    ("rail_strong", "rail"),
    ("rail_group", "rail"),
    ("rail_live", "rail"),
    ("art_ink", "art_1"),
    ("art_ink", "art_2"),
    ("art_ink", "art_3"),
    ("art_ink", "art_4"),
    ("art_ink", "art_5"),
]

PALETTES = [pytest.param(LIGHT_TOKENS, id="light"), pytest.param(DARK_TOKENS, id="dark")]


@pytest.mark.parametrize("tokens", PALETTES)
@pytest.mark.parametrize(("foreground", "background"), TEXT_PAIRS)
def test_text_tokens_meet_wcag_aa(tokens, foreground, background):
    ratio = contrast_ratio(getattr(tokens, foreground), getattr(tokens, background))

    assert ratio >= 4.5, f"{tokens.name}: {foreground} on {background} is {ratio:.2f}:1"


@pytest.mark.parametrize("tokens", PALETTES)
@pytest.mark.parametrize("background", ["surface", "background", "sunken"])
def test_input_border_and_focus_meet_non_text_contrast(tokens, background):
    for name in ("border_input", "focus"):
        ratio = contrast_ratio(getattr(tokens, name), getattr(tokens, background))

        assert ratio >= 3.0, f"{tokens.name}: {name} on {background} is {ratio:.2f}:1"


def test_themes_are_distinct_and_light_is_the_backward_compatible_default():
    assert TOKENS is LIGHT_TOKENS
    assert (LIGHT_TOKENS.name, DARK_TOKENS.name) == ("light", "dark")
    assert LIGHT_TOKENS.background != DARK_TOKENS.background
    assert LIGHT_TOKENS.on_brand != DARK_TOKENS.on_brand
    assert LIGHT_TOKENS.radius_card == DARK_TOKENS.radius_card == 18
    assert LIGHT_TOKENS.radius_ticket == 26


@pytest.mark.parametrize("tokens", PALETTES)
def test_text_inputs_use_the_accessible_border(tokens):
    stylesheet = build_stylesheet(tokens)

    assert f"border: 1px solid {tokens.border_input}" in stylesheet


@pytest.mark.parametrize("tokens", PALETTES)
def test_stylesheet_uses_serif_display_role_and_artboard_radii(tokens):
    stylesheet = build_stylesheet(tokens)

    display = stylesheet.split('QLabel[role="display"]', 1)[1].split("}", 1)[0]
    assert "Georgia" in display
    assert f"border-radius: {tokens.radius_card}px" in stylesheet
    ticket = stylesheet.split("#ticketPanel {", 1)[1].split("}", 1)[0]
    assert f"border-radius: {tokens.radius_ticket}px" in ticket


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


@pytest.mark.parametrize("tokens", PALETTES)
def test_checked_checkbox_check_mark_follows_on_brand(tokens):
    stylesheet = build_stylesheet(tokens)
    block = stylesheet.split("QCheckBox::indicator:checked {", 1)[1].split("}", 1)[0]
    match = re.search(r"image: url\(([^)]+)\)", block)

    assert match is not None
    svg = Path(match.group(1)).read_text(encoding="utf-8")
    assert f'stroke="{tokens.on_brand}"' in svg
    assert "m5 12 4 4L19 6" in svg


def test_table_icon_is_a_tabletop_with_two_legs_drawn_in_the_requested_color():
    markup = svg_markup("table", "#102030", 18)

    assert "table" in ICONS
    assert markup.count("<rect") == 1
    assert 'stroke="#102030"' in markup
    assert "M6 10v9M18 10v9" in markup
