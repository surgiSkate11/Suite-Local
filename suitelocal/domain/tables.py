from dataclasses import dataclass
from datetime import datetime

from suitelocal.domain.models import SaleItem
from suitelocal.domain.tax import effective_tax_rate

OPENED_AT_FORMAT = "%Y-%m-%d %H:%M:%S"


class TableError(ValueError):
    """Raised when a table or an open order violates a business rule."""


@dataclass(frozen=True, slots=True)
class Table:
    id: int
    business_id: int
    name: str
    zone: str | None
    active: bool = True


@dataclass(frozen=True, slots=True)
class OrderLine:
    product_id: int
    product_name: str
    quantity: int
    unit_price_cents: int
    sent_quantity: int = 0
    # Taken from the product when the line was first added; the price already includes it.
    tax_rate_basis_points: int = 0

    @property
    def total_cents(self) -> int:
        return self.quantity * self.unit_price_cents

    @property
    def pending_quantity(self) -> int:
        """Units not yet sent to the kitchen."""
        return self.quantity - self.sent_quantity


@dataclass(frozen=True, slots=True)
class ComandaLine:
    """One line of a kitchen ticket: only the units sent in that moment."""

    product_id: int
    product_name: str
    quantity: int


@dataclass(frozen=True, slots=True)
class OpenOrder:
    id: int
    table_id: int
    opened_at: str
    lines: tuple[OrderLine, ...] = ()

    @property
    def subtotal_cents(self) -> int:
        return sum(line.total_cents for line in self.lines)

    @property
    def item_count(self) -> int:
        return sum(line.quantity for line in self.lines)

    def minutes_open(self, now: datetime) -> int:
        """Whole minutes since the order was opened; ``opened_at`` and ``now`` share a clock."""
        opened = datetime.strptime(self.opened_at, OPENED_AT_FORMAT)
        return max(0, int((now - opened).total_seconds() // 60))

    def sale_items(self, charges_iva: bool = True) -> tuple[SaleItem, ...]:
        """The lines as sale items; without IVA every line is billed at rate 0."""
        return tuple(
            SaleItem(
                line.product_id,
                line.product_name,
                line.quantity,
                line.unit_price_cents,
                effective_tax_rate(line.tax_rate_basis_points, charges_iva=charges_iva),
            )
            for line in self.lines
        )


@dataclass(frozen=True, slots=True)
class TableStatus:
    table: Table
    order: OpenOrder | None = None

    @property
    def occupied(self) -> bool:
        return self.order is not None


def normalize_table_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise TableError("El nombre de la mesa es obligatorio.")
    return cleaned


def normalize_zone(zone: str | None) -> str | None:
    cleaned = (zone or "").strip()
    return cleaned or None


def require_positive_quantity(quantity: int) -> None:
    if quantity <= 0:
        raise TableError("La cantidad debe ser mayor que cero.")
