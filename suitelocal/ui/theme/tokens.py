from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DesignTokens:
    brand_950: str = "#091438"
    brand_900: str = "#0E1E5B"
    brand_800: str = "#162C80"
    brand_600: str = "#2B54D6"
    brand_500: str = "#3B6BF0"
    brand_400: str = "#6B93F5"
    brand_100: str = "#E6EDFE"
    brand_50: str = "#F2F5FF"
    background: str = "#F5F7FB"
    surface: str = "#FFFFFF"
    border: str = "#E5E9F2"
    border_strong: str = "#D3DAE8"
    border_input: str = "#8A94AD"
    text_900: str = "#0F1B3D"
    text_700: str = "#36456B"
    text_500: str = "#5B6785"
    text_400: str = "#94A0BD"
    success: str = "#0B7A3D"
    success_background: str = "#E7F7EE"
    success_border: str = "#BFE8D0"
    warning: str = "#9A6200"
    warning_background: str = "#FFF4D6"
    warning_border: str = "#F6DC9A"
    danger: str = "#C92A45"
    danger_background: str = "#FDEBEE"
    danger_border: str = "#F6C4CC"
    info: str = "#2B54D6"
    info_background: str = "#E6EDFE"
    info_border: str = "#C5D3FB"
    accent_purple: str = "#6D44D9"
    space_1: int = 4
    space_2: int = 8
    space_3: int = 12
    space_4: int = 16
    space_5: int = 20
    space_6: int = 24
    space_7: int = 32
    radius_control: int = 10
    radius_card: int = 14
    radius_panel: int = 18
    control_height: int = 40
    large_action_height: int = 52


TOKENS = DesignTokens()
