"""Active theme: current tokens, stylesheet switching and persistence of the choice."""

from __future__ import annotations

from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtWidgets import QApplication

from suitelocal.ui.theme.effects import refresh_elevations
from suitelocal.ui.theme.qss import build_stylesheet
from suitelocal.ui.theme.tokens import THEMES, DesignTokens

DEFAULT_THEME = "light"
SETTINGS_KEY = "ui/theme"


def _settings() -> QSettings:
    # Explicit format so QSettings.setDefaultFormat/setPath can redirect it (tests do).
    return QSettings(
        QSettings.defaultFormat(), QSettings.Scope.UserScope, "SuiteLocal", "SuiteLocal"
    )


class ThemeManager(QObject):
    """Holds the active theme; ``theme_changed`` fires after the stylesheet was replaced."""

    theme_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._name = DEFAULT_THEME

    @property
    def name(self) -> str:
        return self._name

    @property
    def tokens(self) -> DesignTokens:
        return THEMES[self._name]

    def set_theme(self, app: QApplication, name: str, persist: bool = True) -> None:
        if name not in THEMES:
            raise ValueError(f"Tema no registrado: {name}")
        changed = name != self._name
        self._name = name
        app.setStyleSheet(build_stylesheet(self.tokens))
        refresh_elevations(self.tokens)
        if persist:
            settings = _settings()
            settings.setValue(SETTINGS_KEY, name)
            settings.sync()
        if changed:
            self.theme_changed.emit(name)


_manager: ThemeManager | None = None


def theme_manager() -> ThemeManager:
    global _manager
    if _manager is None:
        _manager = ThemeManager()
    return _manager


def current_theme() -> str:
    return theme_manager().name


def current_tokens() -> DesignTokens:
    return theme_manager().tokens


def set_theme(app: QApplication, name: str, persist: bool = True) -> None:
    theme_manager().set_theme(app, name, persist)


def toggle_theme(app: QApplication) -> str:
    """Switch between light and dark, persist the choice and return the new theme."""
    target = "light" if current_theme() == "dark" else "dark"
    set_theme(app, target)
    return target


def saved_theme() -> str:
    value = _settings().value(SETTINGS_KEY, DEFAULT_THEME)
    return value if isinstance(value, str) and value in THEMES else DEFAULT_THEME


def apply_saved_theme(app: QApplication) -> str:
    """Apply the persisted theme at startup without writing it back."""
    name = saved_theme()
    set_theme(app, name, persist=False)
    return name
