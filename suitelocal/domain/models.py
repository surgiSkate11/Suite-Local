from dataclasses import dataclass
from enum import Enum

from suitelocal.domain.tax import (
    DEFAULT_TAX_RATE_BASIS_POINTS,
    TAX_RATES_BASIS_POINTS,
    split_tax_included,
    tax_breakdown,
)

PAYMENT_METHODS = ("cash", "transfer", "card", "credit")


class Keep(Enum):
    KEEP = "keep"


# Passed to an update to say "leave this column as it is" (None would mean "clear it").
KEEP = Keep.KEEP


@dataclass(frozen=True, slots=True)
class Payment:
    method: str
    amount_cents: int
    reference: str = ""


@dataclass(frozen=True, slots=True)
class Product:
    id: int
    code: str
    name: str
    price_cents: int
    stock: int
    category_id: int | None = None
    cost_cents: int | None = None
    # The price is final (IVA included); this rate says how much of it is IVA.
    tax_rate_basis_points: int = DEFAULT_TAX_RATE_BASIS_POINTS


@dataclass(frozen=True, slots=True)
class CashSession:
    id: int
    business_id: int
    user_id: int
    opened_at: str
    opening_cents: int
    closed_at: str | None = None
    counted_cents: int | None = None
    expected_cents: int | None = None
    notes: str = ""

    @property
    def difference_cents(self) -> int | None:
        """Counted minus expected: negative is a shortage, positive an overage."""
        if self.counted_cents is None or self.expected_cents is None:
            return None
        return self.counted_cents - self.expected_cents


@dataclass(frozen=True, slots=True)
class SaleItem:
    product_id: int
    product_name: str
    quantity: int
    unit_price_cents: int
    tax_rate_basis_points: int = 0

    @property
    def total_cents(self) -> int:
        """What the customer pays for the line; the IVA is already inside."""
        return self.quantity * self.unit_price_cents

    @property
    def base_cents(self) -> int:
        return split_tax_included(self.total_cents, self.tax_rate_basis_points)[0]

    @property
    def tax_cents(self) -> int:
        return split_tax_included(self.total_cents, self.tax_rate_basis_points)[1]


class SaleError(ValueError):
    """Raised when a sale violates a business rule."""


def validate_sale(sale: "Sale") -> None:
    if not sale.items:
        raise SaleError("La venta debe tener al menos un producto.")
    if any(item.quantity <= 0 for item in sale.items):
        raise SaleError("La cantidad de cada producto debe ser mayor que cero.")
    if any(item.tax_rate_basis_points not in TAX_RATES_BASIS_POINTS for item in sale.items):
        raise SaleError("La tarifa de IVA de un producto no es válida.")
    if not sale.payments:
        raise SaleError("La venta debe tener al menos un pago.")
    methods: set[str] = set()
    for payment in sale.payments:
        if payment.method not in PAYMENT_METHODS:
            raise SaleError("La forma de pago no es válida.")
        if payment.method in methods:
            raise SaleError("No se puede repetir una forma de pago.")
        if payment.amount_cents <= 0:
            raise SaleError("El monto de cada pago debe ser mayor que cero.")
        if payment.method == "transfer" and not payment.reference.strip():
            raise SaleError("La transferencia necesita un número de referencia.")
        methods.add(payment.method)
    if sum(payment.amount_cents for payment in sale.payments) < sale.total_cents:
        raise SaleError("El pago recibido es menor que el total de la venta.")
    non_cash = sum(payment.amount_cents for payment in sale.payments if payment.method != "cash")
    if non_cash > sale.total_cents:
        raise SaleError("Los pagos no pueden superar el total sin efectivo.")


@dataclass(frozen=True, slots=True)
class Sale:
    items: tuple[SaleItem, ...]
    payment_cents: int
    payments: tuple[Payment, ...] = ()

    def __post_init__(self) -> None:
        if not self.payments:
            object.__setattr__(self, "payments", (Payment("cash", self.payment_cents),))
        validate_sale(self)

    @property
    def total_cents(self) -> int:
        """What the customer is charged: the sum of the final prices, IVA included."""
        return sum(item.total_cents for item in self.items)

    @property
    def subtotal_cents(self) -> int:
        """Sum of the taxable bases."""
        return sum(item.base_cents for item in self.items)

    @property
    def tax_cents(self) -> int:
        return sum(item.tax_cents for item in self.items)

    @property
    def tax_breakdown(self) -> tuple[tuple[int, int, int], ...]:
        return tax_breakdown((item.total_cents, item.tax_rate_basis_points) for item in self.items)

    @property
    def change_cents(self) -> int:
        non_cash = sum(
            payment.amount_cents for payment in self.payments if payment.method != "cash"
        )
        cash = sum(payment.amount_cents for payment in self.payments if payment.method == "cash")
        return max(0, cash - max(0, self.total_cents - non_cash))
