from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from suitelocal.domain.models import Payment, Product, Sale, SaleItem


@dataclass(slots=True)
class CartLine:
    product: Product
    quantity: int = 1

    @property
    def total_cents(self) -> int:
        return self.quantity * self.product.price_cents


class Cart:
    def __init__(self, tax_rate_basis_points: int = 0) -> None:
        self._lines: dict[int, CartLine] = {}
        self.tax_rate_basis_points = tax_rate_basis_points

    @property
    def lines(self) -> tuple[CartLine, ...]:
        return tuple(self._lines.values())

    @property
    def total_cents(self) -> int:
        return sum(line.total_cents for line in self._lines.values())

    @property
    def tax_cents(self) -> int:
        return int(
            (
                Decimal(self.total_cents) * Decimal(self.tax_rate_basis_points) / Decimal(10000)
            ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )

    @property
    def grand_total_cents(self) -> int:
        return self.total_cents + self.tax_cents

    def add(self, product: Product) -> None:
        line = self._lines.get(product.id)
        next_quantity = (line.quantity if line else 0) + 1
        if next_quantity > product.stock:
            raise ValueError(f"Stock insuficiente para {product.name}.")
        if line:
            line.quantity = next_quantity
        else:
            self._lines[product.id] = CartLine(product)

    def remove(self, product_id: int) -> None:
        self._lines.pop(product_id, None)

    def set_quantity(self, product_id: int, quantity: int) -> None:
        line = self._lines.get(product_id)
        if line is None:
            raise ValueError("La línea seleccionada ya no está en la venta.")
        if quantity <= 0:
            raise ValueError("La cantidad debe ser mayor que cero.")
        if quantity > line.product.stock:
            raise ValueError(f"Stock insuficiente para {line.product.name}.")
        line.quantity = quantity

    def clear(self) -> None:
        self._lines.clear()

    def to_sale(self, payments: tuple[Payment, ...] | int) -> Sale:
        if isinstance(payments, int):
            payments = (Payment("cash", payments),)
        payment_cents = sum(payment.amount_cents for payment in payments)
        return Sale(
            tuple(
                SaleItem(
                    line.product.id,
                    line.product.name,
                    line.quantity,
                    line.product.price_cents,
                )
                for line in self._lines.values()
            ),
            payment_cents,
            payments,
            self.tax_rate_basis_points,
        )
