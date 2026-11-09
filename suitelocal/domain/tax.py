"""IVA rules for Ecuador: consumer prices already include the tax (LODC art. 9)."""

from collections.abc import Iterable

# Basis points: 15 % general rate (since 2024-04-01), 5 % construction materials, 0 %.
TAX_RATES_BASIS_POINTS = (1500, 500, 0)
DEFAULT_TAX_RATE_BASIS_POINTS = 1500
_BASIS_POINTS = 10_000


def validate_tax_rate(rate_basis_points: int) -> int:
    if rate_basis_points not in TAX_RATES_BASIS_POINTS:
        raise ValueError("La tarifa de IVA debe ser 15 %, 5 % o 0 %.")
    return rate_basis_points


def effective_tax_rate(rate_basis_points: int, *, charges_iva: bool) -> int:
    """The rate a sale line is billed at: the product's own, or 0 when the business charges no IVA.

    The price stays final either way; the product keeps its stored rate for when that changes.
    """
    return rate_basis_points if charges_iva else 0


def split_tax_included(total_cents: int, rate_basis_points: int) -> tuple[int, int]:
    """Split a final price into (taxable base, IVA); base + IVA always equals the total."""
    validate_tax_rate(rate_basis_points)
    divisor = _BASIS_POINTS + rate_basis_points
    # Integer round-half-up of total * 10000 / divisor, with no floating point.
    base = (2 * total_cents * _BASIS_POINTS + divisor) // (2 * divisor)
    return base, total_cents - base


def tax_breakdown(lines: Iterable[tuple[int, int]]) -> tuple[tuple[int, int, int], ...]:
    """Group (line total, rate) pairs into (rate, base, IVA) tuples, highest rate first."""
    grouped: dict[int, tuple[int, int]] = {}
    for total_cents, rate_basis_points in lines:
        base, tax = split_tax_included(total_cents, rate_basis_points)
        known_base, known_tax = grouped.get(rate_basis_points, (0, 0))
        grouped[rate_basis_points] = (known_base + base, known_tax + tax)
    return tuple((rate, base, tax) for rate, (base, tax) in sorted(grouped.items(), reverse=True))
