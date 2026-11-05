"""Product catalog widgets: the art tile, the product card and the responsive card grid."""

from collections.abc import Callable, Mapping

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QResizeEvent, QShowEvent
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from suitelocal.domain.models import Product
from suitelocal.ui.components.elided import ElidedLabel

TINT_COUNT = 5


def product_initials(name: str) -> str:
    """Up to two capital letters taken from the first words of the product name."""
    letters = [word[0] for word in name.split() if word[:1].isalnum()]
    return "".join(letters[:2]).upper() or "?"


def product_tint(product: Product) -> int:
    """Art tint 1..5; deterministic so a product keeps its color across sessions."""
    return product.id % TINT_COUNT + 1


def make_art_label(product: Product, size: str = "card") -> QLabel:
    """Tinted tile with the product initials; the stylesheet picks the color per theme."""
    art = QLabel(product_initials(product.name))
    # An object name, not just properties: the card's "#productCard QLabel" rule clears label
    # backgrounds, and only an ID selector is specific enough to win over it.
    art.setObjectName("productArt")
    art.setProperty("role", "art")
    art.setProperty("size", size)
    art.setProperty("tint", product_tint(product))
    art.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return art


def repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class ProductCard(QPushButton):
    """Clickable catalog card: art tile, name, stock, price and the in-cart quantity badge."""

    ART_HEIGHT = 78
    HEIGHT = 176

    def __init__(
        self,
        product: Product,
        currency_symbol: str,
        low_stock_threshold: int,
        format_money: Callable[[int, str], str],
        cart_quantity: int = 0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.product = product
        self.setObjectName("productCard")
        self.setFixedHeight(self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(
            f"{product.name}, {format_money(product.price_cents, currency_symbol)}"
        )
        self.setProperty("inCart", False)
        self.setProperty("current", False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        self.art = make_art_label(product)
        self.art.setFixedHeight(self.ART_HEIGHT)
        layout.addWidget(self.art)
        info = QVBoxLayout()
        info.setContentsMargins(6, 0, 6, 2)
        info.setSpacing(2)
        self.name_label = ElidedLabel(product.name)
        self.name_label.setObjectName("productName")
        self.meta_label = QLabel(f"{product.stock} en stock")
        self.meta_label.setObjectName("productMeta")
        self.price_label = QLabel(format_money(product.price_cents, currency_symbol))
        self.price_label.setObjectName("productPrice")
        self.badge = QLabel("+")
        self.badge.setObjectName("productBadge")
        self.badge.setProperty("inCart", False)
        self.badge.setFixedSize(28, 28)
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        foot = QHBoxLayout()
        foot.setContentsMargins(0, 2, 0, 0)
        foot.addWidget(self.price_label)
        foot.addStretch()
        foot.addWidget(self.badge)
        info.addWidget(self.name_label)
        info.addWidget(self.meta_label)
        info.addLayout(foot)
        layout.addLayout(info)
        self.tag_label = QLabel(self)
        self.tag_label.setObjectName("productTag")
        self._configure_tag(product.stock, low_stock_threshold)
        for child in (self.art, self.name_label, self.meta_label, self.price_label, self.badge):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.tag_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.set_cart_quantity(cart_quantity)

    def _configure_tag(self, stock: int, low_stock_threshold: int) -> None:
        if stock <= 0:
            text, state = "Sin stock", "out"
        elif stock <= low_stock_threshold:
            text, state = f"Quedan {stock}", "low"
        else:
            self.tag_label.hide()
            return
        self.tag_label.setText(text)
        self.tag_label.setProperty("state", state)
        self.tag_label.adjustSize()
        self.tag_label.move(14, 14)
        self.tag_label.show()
        self.tag_label.raise_()

    def set_cart_quantity(self, quantity: int) -> None:
        in_cart = quantity > 0
        self.badge.setText(str(quantity) if in_cart else "+")
        for widget in (self, self.badge):
            widget.setProperty("inCart", in_cart)
            repolish(widget)

    def set_current(self, current: bool) -> None:
        self.setProperty("current", current)
        repolish(self)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        # The tag is only sized correctly once the stylesheet padding is applied.
        self.tag_label.adjustSize()

    def sizeHint(self) -> QSize:
        return QSize(160, self.HEIGHT)


class ProductGrid(QScrollArea):
    """Scrolling grid of product cards whose column count follows the available width."""

    product_chosen = Signal(object)

    CARD_MIN_WIDTH = 160
    GAP = 12
    MAX_COLUMNS = 4
    SCROLLBAR_RESERVE = 14
    MAX_CARDS = 60

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent if isinstance(parent, QWidget) else None)
        self.setObjectName("productGrid")
        self.viewport().setObjectName("productGridViewport")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host = QWidget()
        host.setObjectName("productGridHost")
        self._host_layout = QVBoxLayout(host)
        self._host_layout.setContentsMargins(0, 0, 0, 4)
        self._host_layout.setSpacing(self.GAP)
        self._cards_widget = QWidget()
        self._grid = QGridLayout(self._cards_widget)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(self.GAP)
        self.overflow_label = QLabel()
        self.overflow_label.setObjectName("productOverflow")
        self.overflow_label.hide()
        self._host_layout.addWidget(self._cards_widget)
        self._host_layout.addWidget(self.overflow_label)
        self._host_layout.addStretch()
        self.setWidget(host)
        self._cards: list[ProductCard] = []
        self._current = -1
        self.columns = self.columns_for_width(self.width())

    @classmethod
    def columns_for_width(cls, width: int) -> int:
        usable = width - cls.SCROLLBAR_RESERVE
        return max(1, min(cls.MAX_COLUMNS, (usable + cls.GAP) // (cls.CARD_MIN_WIDTH + cls.GAP)))

    # -- list-like API (kept so keyboard navigation reads like a list) ---------------------

    def count(self) -> int:
        return len(self._cards)

    def currentRow(self) -> int:
        return self._current

    def setCurrentRow(self, row: int) -> None:
        if row >= len(self._cards):
            row = len(self._cards) - 1
        if self._current == row:
            return
        if 0 <= self._current < len(self._cards):
            self._cards[self._current].set_current(False)
        self._current = row
        if row >= 0:
            self._cards[row].set_current(True)
            self.ensureWidgetVisible(self._cards[row], 0, 12)

    def card_at(self, row: int) -> ProductCard:
        return self._cards[row]

    def product_at(self, row: int) -> Product | None:
        return self._cards[row].product if 0 <= row < len(self._cards) else None

    # -- content --------------------------------------------------------------------------

    def set_products(
        self,
        products: list[Product],
        quantities: Mapping[int, int],
        currency_symbol: str,
        low_stock_threshold: int,
        format_money: Callable[[int, str], str],
    ) -> None:
        for card in self._cards:
            self._grid.removeWidget(card)
            card.hide()
            card.deleteLater()
        self._cards = []
        self._current = -1
        for product in products[: self.MAX_CARDS]:
            card = ProductCard(
                product,
                currency_symbol,
                low_stock_threshold,
                format_money,
                quantities.get(product.id, 0),
                self._cards_widget,
            )
            card.clicked.connect(
                lambda _checked=False, item=product: self.product_chosen.emit(item)
            )
            self._cards.append(card)
        hidden = len(products) - len(self._cards)
        self.overflow_label.setText(
            f"Mostrando {len(self._cards)} de {len(products)} productos. "
            "Escribí para afinar la búsqueda."
        )
        self.overflow_label.setVisible(hidden > 0)
        self._reflow()
        if self._cards:
            self.setCurrentRow(0)

    def update_quantities(self, quantities: Mapping[int, int]) -> None:
        for card in self._cards:
            card.set_cart_quantity(quantities.get(card.product.id, 0))

    def _reflow(self) -> None:
        for index, card in enumerate(self._cards):
            self._grid.removeWidget(card)
            self._grid.addWidget(card, index // self.columns, index % self.columns)
            card.show()
        for column in range(self.MAX_COLUMNS):
            self._grid.setColumnStretch(column, 1 if column < self.columns else 0)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        columns = self.columns_for_width(event.size().width())
        if columns != self.columns:
            self.columns = columns
            self._reflow()
