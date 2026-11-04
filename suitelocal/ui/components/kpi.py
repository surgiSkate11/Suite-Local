from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from suitelocal.ui.theme.icons import icon


class KpiCard(QWidget):
    def __init__(
        self,
        title: str,
        value: str = "—",
        accent: str = "blue",
        trend: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("kpiCard")
        self.setProperty("accent", accent)
        self.value_label = QLabel(value)
        self.value_label.setObjectName("kpiValue")
        self.trend_label = QLabel(trend)
        self.trend_label.setObjectName("kpiTrend")
        self.trend_label.setWordWrap(True)
        self.trend_label.setMinimumWidth(0)
        self.trend_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        label = QLabel(title)
        label.setObjectName("kpiLabel")
        label.setMinimumWidth(0)
        icon_name = {
            "blue": "box",
            "orange": "box",
            "green": "cash",
            "purple": "dashboard",
        }.get(accent, "dashboard")
        icon_label = QLabel()
        icon_label.setObjectName("kpiIcon")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setPixmap(icon(icon_name, "#3B6BF0", 20).pixmap(QSize(20, 20)))
        icon_label.setFixedSize(40, 40)
        header = QHBoxLayout()
        header.addWidget(label)
        header.addStretch()
        header.addWidget(icon_label)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(6)
        layout.addLayout(header)
        layout.addWidget(self.value_label)
        layout.addWidget(self.trend_label)
