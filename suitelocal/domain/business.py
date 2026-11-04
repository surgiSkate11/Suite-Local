from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BusinessSettings:
    business_id: int
    name: str
    currency_symbol: str
    low_stock_threshold: int
    enabled_payment_methods: tuple[str, ...]
    tax_rate_basis_points: int = 0

    @property
    def tax_rate_percent(self) -> float:
        return self.tax_rate_basis_points / 100
