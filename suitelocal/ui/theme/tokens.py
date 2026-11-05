from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DesignTokens:
    """Atelier + Grafito palette.

    Field defaults are the light theme. ``DARK_TOKENS`` overrides the colors that change;
    everything that is not a color (spacing, radii, sizes) is shared by both themes.
    Soft backgrounds of the dark theme are the artboard's translucent tints already blended
    over ``surface`` so every color stays an opaque hex that can be contrast-tested.
    """

    name: str = "light"
    # Accent scale. ``brand_500``/``brand_800`` are the accent, ``brand_600`` its hover state.
    brand_950: str = "#15193A"
    brand_900: str = "#1E2A5A"
    brand_800: str = "#1E2A5A"
    brand_600: str = "#2E3C7A"
    brand_500: str = "#1E2A5A"
    brand_400: str = "#9AA6D8"
    brand_100: str = "#E9ECF6"
    brand_50: str = "#F2F3F9"
    on_brand: str = "#FFFFFF"
    focus: str = "#3D4FA0"
    focus_ring: str = "#9AA6D8"
    # Neutrals.
    background: str = "#F7F6F3"
    surface: str = "#FFFFFF"
    mist: str = "#FBFAF7"
    sunken: str = "#F1EFEA"
    border: str = "#ECE9E2"
    border_strong: str = "#DDD8CE"
    border_input: str = "#7F8493"
    text_900: str = "#15171E"
    text_700: str = "#3A3F4C"
    text_500: str = "#5F6575"
    text_400: str = "#A3A7B3"
    # Status colors; the *_background fields are the soft tints.
    success: str = "#1B6E4C"
    success_strong: str = "#145A3E"
    success_background: str = "#E4F2EB"
    success_border: str = "#C6E5D5"
    warning: str = "#8A5300"
    warning_background: str = "#FDF0D9"
    warning_border: str = "#EAD3A3"
    danger: str = "#B53A4C"
    on_danger: str = "#FFFFFF"
    danger_background: str = "#FBEAED"
    danger_border: str = "#F0C6CD"
    info: str = "#1E2A5A"
    info_background: str = "#E9ECF6"
    info_border: str = "#C9CFE6"
    accent_purple: str = "#6D44D9"
    # Champagne/gold. ``champagne_text`` is the readable gold; the 100-700 scale paints
    # gradients (brand mark, avatar, charge button) and is the same in both themes.
    champagne: str = "#B08A4E"
    champagne_text: str = "#7A5A26"
    champagne_background: str = "#F6EEDF"
    champagne_border: str = "#E2CFA9"
    champagne_100: str = "#EFD6A6"
    champagne_300: str = "#E4C58C"
    champagne_500: str = "#D4AE6A"
    champagne_700: str = "#A9803F"
    on_champagne: str = "#1A1407"
    # Navy hero band (total to charge, checkout summary, auth panel).
    hero: str = "#1E2A5A"
    hero_2: str = "#2E3C7A"
    hero_text: str = "#FFFFFF"
    hero_muted: str = "#C5CBE6"
    # Rail (sidebar).
    rail: str = "#15193A"
    rail_text: str = "#B9BFDA"
    rail_strong: str = "#FFFFFF"
    rail_group: str = "#8A91AD"
    rail_live: str = "#7FDDB2"
    rail_active: str = "rgba(255,255,255,0.10)"
    rail_hover: str = "rgba(255,255,255,0.05)"
    rail_card: str = "rgba(255,255,255,0.04)"
    rail_border: str = "rgba(255,255,255,0.07)"
    # Product art tints and the ink drawn over them.
    art_1: str = "#F3E6CF"
    art_2: str = "#DCE6F6"
    art_3: str = "#E8E1F2"
    art_4: str = "#DCEFE5"
    art_5: str = "#F6DFDF"
    art_ink: str = "#2A2F3E"
    # Drop shadows are painted in Python (QGraphicsDropShadowEffect).
    shadow_color: str = "#15171E"
    shadow_strength: float = 1.0
    font_serif: str = '"Georgia", "Cambria", "Times New Roman", serif'
    space_1: int = 4
    space_2: int = 8
    space_3: int = 12
    space_4: int = 16
    space_5: int = 20
    space_6: int = 24
    space_7: int = 32
    radius_control: int = 12
    radius_pad: int = 14
    radius_card: int = 18
    radius_panel: int = 20
    radius_ticket: int = 26
    radius_dialog: int = 28
    control_height: int = 44
    large_action_height: int = 56


LIGHT_TOKENS = DesignTokens()

DARK_TOKENS = DesignTokens(
    name="dark",
    brand_950="#0A0C11",
    brand_900="#1A1F33",
    brand_800="#9AA7FF",
    brand_600="#B3BDFF",
    brand_500="#9AA7FF",
    brand_400="#B3BDFF",
    brand_100="#25293C",
    brand_50="#1D212E",
    on_brand="#0D0F14",
    focus="#B3BDFF",
    focus_ring="#F1F3F8",
    background="#0D0F14",
    surface="#151821",
    mist="#191D28",
    sunken="#10131A",
    border="#232837",
    border_strong="#2E3446",
    border_input="#717A93",
    text_900="#F1F3F8",
    text_700="#C2C7D4",
    text_500="#8F96A8",
    text_400="#5B6275",
    success="#6BD6A6",
    success_strong="#6BD6A6",
    success_background="#1F2F31",
    success_border="#2F5149",
    warning="#F2BB66",
    warning_background="#302C29",
    warning_border="#574936",
    danger="#FF8FA0",
    on_danger="#2A0A10",
    danger_background="#312630",
    danger_border="#5B3C47",
    info="#9AA7FF",
    info_background="#25293C",
    info_border="#3D4364",
    accent_purple="#A58BFF",
    champagne="#E6C485",
    champagne_text="#E6C485",
    champagne_background="#2E2D2D",
    champagne_border="#544C3F",
    hero="#1A1F33",
    hero_2="#242B45",
    hero_text="#F1F3F8",
    hero_muted="#A9B0C8",
    rail="#0A0C11",
    rail_text="#8F96A8",
    rail_strong="#F1F3F8",
    rail_group="#7F869B",
    rail_active="rgba(154,167,255,0.14)",
    art_1="#3A2F1F",
    art_2="#1E2A40",
    art_3="#2B2340",
    art_4="#1C3329",
    art_5="#3A2226",
    art_ink="#EDE6D8",
    shadow_color="#000000",
    shadow_strength=3.0,
)

THEMES: dict[str, DesignTokens] = {"light": LIGHT_TOKENS, "dark": DARK_TOKENS}

# Backward-compatible name for the light palette. Code that must follow the active theme
# reads ``current_tokens()`` from ``suitelocal.ui.theme.manager`` at use time instead.
TOKENS = LIGHT_TOKENS
