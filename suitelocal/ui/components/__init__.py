"""Componentes visuales reutilizables de SuiteLocal."""

from suitelocal.ui.components.badge import KeyHint, StatusBadge
from suitelocal.ui.components.button import (
    DangerButton,
    PrimaryButton,
    SecondaryButton,
    SegmentedControl,
    SwitchButton,
    set_variant,
)
from suitelocal.ui.components.card import Card
from suitelocal.ui.components.elided import ElidedLabel
from suitelocal.ui.components.feedback import (
    EmptyState,
    InlineMessage,
    Skeleton,
    Toast,
    ToastHost,
)
from suitelocal.ui.components.field import SearchField, TextField
from suitelocal.ui.components.kpi import KpiCard
from suitelocal.ui.components.navigation import Sidebar, Topbar
from suitelocal.ui.components.overlay import (
    AppDialog,
    Drawer,
    build_confirmation,
    confirm_action,
)
from suitelocal.ui.components.table import DataTable

__all__ = [
    "AppDialog",
    "Card",
    "DangerButton",
    "DataTable",
    "Drawer",
    "ElidedLabel",
    "EmptyState",
    "InlineMessage",
    "KeyHint",
    "KpiCard",
    "PrimaryButton",
    "SearchField",
    "SecondaryButton",
    "SegmentedControl",
    "Skeleton",
    "StatusBadge",
    "SwitchButton",
    "Sidebar",
    "TextField",
    "Topbar",
    "Toast",
    "ToastHost",
    "build_confirmation",
    "set_variant",
    "confirm_action",
]
