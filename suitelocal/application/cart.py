from dataclasses import dataclass

from suitelocal.domain.models import Payment, Product, Sale, SaleItem
from suitelocal.domain.tax import effective_tax_rate, split_tax_included, tax_breakdown


@dataclass(slots=True)
class CartLine:
    product: Product
    quantity: int = 1
    # False when the business charges no IVA: the line is then billed at rate 0.
    charges_iva: bool = True

    @property
    def tax_rate_basis_points(self) -> int:
        return effective_tax_rate(self.product.tax_rate_basis_points, charges_iva=self.charges_iva)

    @property
    def total_cents(self) -> int:
        return self.quantity * self.product.price_cents

    @property
    def base_cents(self) -> int:
        return split_tax_included(self.total_cents, self.tax_rate_basis_points)[0]

    @property
    def tax_cents(self) -> int:
        return split_tax_included(self.total_cents, self.tax_rate_basis_points)[1]


class Cart:
    """Prices already include IVA, so the total is the sum of the lines and nothing is added."""

    def __init__(self, charges_iva: bool = True) -> None:
        self._lines: dict[int, CartLine] = {}
        self._charges_iva = charges_iva

    @property
    def charges_iva(self) -> bool:
        """False when the business charges no IVA: every line is billed at rate 0."""
        return self._charges_iva

    @charges_iva.setter
    def charges_iva(self, value: bool) -> None:
        self._charges_iva = value
        for line in self._lines.values():
            line.charges_iva = value

    @property
    def lines(self) -> tuple[CartLine, ...]:
        return tuple(self._lines.values())

    @property
    def total_cents(self) -> int:
        """What the customer pays."""
        return sum(line.total_cents for line in self._lines.values())

    @property
    def grand_total_cents(self) -> int:
        return self.total_cents

    @property
    def subtotal_cents(self) -> int:
        """Sum of the taxable bases."""
        return sum(line.base_cents for line in self._lines.values())

    @property
    def tax_cents(self) -> int:
        """IVA contained in the total."""
        return sum(line.tax_cents for line in self._lines.values())

    @property
    def tax_breakdown(self) -> tuple[tuple[int, int, int], ...]:
        """(rate in basis points, taxable base, IVA) per rate in use, highest rate first."""
        return tax_breakdown(
            (line.total_cents, line.tax_rate_basis_points) for line in self._lines.values()
        )

    def add(self, product: Product) -> None:
        line = self._lines.get(product.id)
        next_quantity = (line.quantity if line else 0) + 1
        if next_quantity > product.stock:
            raise ValueError(f"Stock insuficiente para {product.name}.")
        if line:
            line.quantity = next_quantity
        else:
            self._lines[product.id] = CartLine(product, charges_iva=self._charges_iva)

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
                    line.tax_rate_basis_points,
                )
                for line in self._lines.values()
            ),
            payment_cents,
            payments,
        )
