from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

PAYMENT_METHODS = ("cash", "transfer", "card")


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


@dataclass(frozen=True, slots=True)
class SaleItem:
    product_id: int
    product_name: str
    quantity: int
    unit_price_cents: int

    @property
    def total_cents(self) -> int:
        return self.quantity * self.unit_price_cents


class SaleError(ValueError):
    """Raised when a sale violates a business rule."""


def validate_sale(sale: "Sale") -> None:
    if not sale.items:
        raise SaleError("La venta debe tener al menos un producto.")
    if any(item.quantity <= 0 for item in sale.items):
        raise SaleError("La cantidad de cada producto debe ser mayor que cero.")
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
    tax_rate_basis_points: int = 0

    def __post_init__(self) -> None:
        if not self.payments:
            object.__setattr__(self, "payments", (Payment("cash", self.payment_cents),))
        validate_sale(self)

    @property
    def total_cents(self) -> int:
        return self.subtotal_cents + self.tax_cents

    @property
    def subtotal_cents(self) -> int:
        return sum(item.total_cents for item in self.items)

    @property
    def tax_cents(self) -> int:
        if self.tax_rate_basis_points < 0 or self.tax_rate_basis_points > 10000:
            raise SaleError("El porcentaje de IVA no es válido.")
        return int(
            (
                Decimal(self.subtotal_cents) * Decimal(self.tax_rate_basis_points) / Decimal(10000)
            ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )

    @property
    def change_cents(self) -> int:
        non_cash = sum(
            payment.amount_cents for payment in self.payments if payment.method != "cash"
        )
        cash = sum(payment.amount_cents for payment in self.payments if payment.method == "cash")
        return max(0, cash - max(0, self.total_cents - non_cash))
