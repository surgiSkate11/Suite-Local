from datetime import datetime

from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from suitelocal.infrastructure.repositories import ProductRepository, SaleRepository
from suitelocal.ui.components import DataTable, EmptyState, KpiCard, StatusBadge
from suitelocal.ui.pos import format_money


class DashboardWidget(QWidget):
    def __init__(
        self,
        products: ProductRepository,
        sales: SaleRepository,
        currency_symbol: str = "$",
        low_stock_threshold: int = 3,
        username: str = "",
        business_name: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.products = products
        self.sales = sales
        self.currency_symbol = currency_symbol
        self.low_stock_threshold = low_stock_threshold
        self.username = username
        self.business_name = business_name
        self.products_card = KpiCard("Productos activos", accent="blue")
        self.low_stock_card = KpiCard("Por reponer", accent="orange")
        self.sales_card = KpiCard("Ventas del día", accent="green")
        self.revenue_card = KpiCard("Total vendido hoy", accent="purple")
        self.metric_cards = (
            self.products_card,
            self.low_stock_card,
            self.sales_card,
            self.revenue_card,
        )
        self.metrics_grid = QGridLayout()
        self.metrics_grid.setSpacing(16)
        hour = datetime.now().hour
        greeting = "Buenos días" if hour < 12 else "Buenas tardes" if hour < 19 else "Buenas noches"
        title = QLabel(f"{greeting}, equipo de {business_name}" if business_name else greeting)
        title.setObjectName("pageTitle")
        title.setWordWrap(True)
        title.setMinimumWidth(0)
        title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        subtitle = QLabel(
            f"Resumen operativo de hoy para {business_name}."
            if business_name
            else "Resumen operativo de hoy."
        )
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        subtitle.setMinimumWidth(0)
        heading = QHBoxLayout()
        heading.addWidget(title)
        heading.addStretch()
        self.quick_action = QPushButton("Registrar una venta  →")
        self.quick_action.setObjectName("primaryAction")
        self.quick_action.setMinimumWidth(0)
        heading.addWidget(self.quick_action)

        inventory_card = QFrame()
        inventory_card.setObjectName("contentCard")
        inventory_layout = QVBoxLayout(inventory_card)
        inventory_layout.setContentsMargins(18, 16, 18, 16)
        inventory_header = QHBoxLayout()
        inventory_title = QLabel("Productos por reponer")
        inventory_title.setObjectName("sectionTitle")
        inventory_header.addWidget(inventory_title)
        inventory_header.addStretch()
        inventory_layout.addLayout(inventory_header)
        self.products_table = DataTable(4, ["Código", "Producto", "Stock", "Estado"])
        inventory_layout.addWidget(self.products_table)
        self.empty_inventory = EmptyState(
            "Todo en orden",
            f"Ningún producto está bajo el mínimo de {low_stock_threshold} unidades.",
        )
        inventory_layout.addWidget(self.empty_inventory)

        sales_card = QFrame()
        sales_card.setObjectName("contentCard")
        sales_layout = QVBoxLayout(sales_card)
        sales_layout.setContentsMargins(18, 16, 18, 16)
        sales_title = QLabel("Últimas ventas")
        sales_title.setObjectName("sectionTitle")
        sales_layout.addWidget(sales_title)
        self.sales_empty = EmptyState(
            "Aún no hay ventas",
            "Cuando registres una venta aparecerá aquí el resumen de actividad.",
        )
        sales_layout.addWidget(self.sales_empty)
        self.sales_summary = QLabel()
        self.sales_summary.setObjectName("dashboardSummary")
        self.sales_summary.setWordWrap(True)
        sales_layout.addWidget(self.sales_summary)
        panels = QGridLayout()
        panels.setHorizontalSpacing(16)
        panels.addWidget(inventory_card, 0, 0)
        panels.addWidget(sales_card, 0, 1)
        panels.setColumnStretch(0, 3)
        panels.setColumnStretch(1, 2)
        self.panels_grid = panels
        self.inventory_panel = inventory_card
        self.sales_panel = sales_card
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 28, 30, 30)
        layout.setSpacing(16)
        layout.addLayout(heading)
        layout.addWidget(subtitle)
        layout.addLayout(self.metrics_grid)
        layout.addLayout(panels)
        layout.addStretch()
        self._compact_layout = False
        self._relayout(900)
        self.refresh()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._relayout(self.width())

    def _relayout(self, width: int) -> None:
        compact = width < 1100
        if compact == self._compact_layout and self.metrics_grid.count():
            return
        self._compact_layout = compact
        while self.metrics_grid.count():
            self.metrics_grid.takeAt(0)
        columns = 2 if compact else 4
        for index, card in enumerate(self.metric_cards):
            self.metrics_grid.addWidget(card, index // columns, index % columns)
        self.panels_grid.removeWidget(self.inventory_panel)
        self.panels_grid.removeWidget(self.sales_panel)
        if compact:
            self.panels_grid.addWidget(self.inventory_panel, 0, 0, 1, 2)
            self.panels_grid.addWidget(self.sales_panel, 1, 0, 1, 2)
        else:
            self.panels_grid.addWidget(self.inventory_panel, 0, 0)
            self.panels_grid.addWidget(self.sales_panel, 0, 1)

    def refresh(self) -> None:
        products = self.products.find_active()
        low_stock = [product for product in products if product.stock <= self.low_stock_threshold]
        self.products_card.value_label.setText(str(len(products)))
        self.low_stock_card.value_label.setText(str(len(low_stock)))
        sale_count, revenue = self.sales.today_summary()
        self.sales_card.value_label.setText(str(sale_count))
        self.revenue_card.value_label.setText(format_money(revenue, self.currency_symbol))
        self.products_card.trend_label.setText(
            f"{len(products)} producto{'s' if len(products) != 1 else ''} listos para vender"
        )
        low_stock_message = "Revisión recomendada" if low_stock else "Todo en orden"
        self.low_stock_card.trend_label.setText(low_stock_message)
        self.sales_card.trend_label.setText(
            "Sin ventas todavía" if sale_count == 0 else "Ventas registradas hoy"
        )
        self.revenue_card.trend_label.setText(
            "Registra una venta para comenzar" if sale_count == 0 else "Ingresos acumulados hoy"
        )
        self.products_table.setRowCount(0)
        for product in low_stock[:8]:
            row = self.products_table.rowCount()
            self.products_table.insertRow(row)
            values = (
                product.code,
                product.name,
                str(product.stock),
                "Agotado" if product.stock == 0 else "Stock bajo",
            )
            for column, value in enumerate(values):
                self.products_table.setItem(row, column, QTableWidgetItem(value))
            badge = StatusBadge(
                "Agotado" if product.stock == 0 else "Stock bajo",
                "danger" if product.stock == 0 else "warning",
            )
            self.products_table.setCellWidget(row, 3, badge)
        self.products_table.setVisible(bool(low_stock))
        self.empty_inventory.setVisible(not low_stock)
        self.sales_empty.setVisible(sale_count == 0)
        self.sales_summary.setVisible(sale_count > 0)
        self.sales_summary.setText(
            f"<b>{sale_count}</b> venta{'s' if sale_count != 1 else ''} registrada"
            f"{'s' if sale_count != 1 else ''} hoy<br>"
            f"<span>Acumulado del día: {format_money(revenue, self.currency_symbol)}</span>"
        )
