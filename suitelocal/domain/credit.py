"""Credit sales (fiado): what a customer owes is the cargos of the ledger minus its abonos."""

from dataclasses import dataclass
from datetime import datetime

from suitelocal.domain.customers import Customer
from suitelocal.domain.money import format_usd

FIADO_MODULE = "fiado"
CREDIT_METHOD = "credit"
CARGO = "cargo"
ABONO = "abono"
# How a customer may pay a debt down: the money goes into the drawer or the bank account.
ABONO_METHODS = ("cash", "transfer")
NOTE_MAX_LENGTH = 200


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    id: int
    customer_id: int
    kind: str
    amount_cents: int
    sale_id: int | None
    method: str | None
    note: str
    user_id: int
    created_at: datetime

    @property
    def signed_cents(self) -> int:
        """What the entry does to the balance: a cargo adds, an abono subtracts."""
        return self.amount_cents if self.kind == CARGO else -self.amount_cents


@dataclass(frozen=True, slots=True)
class Debtor:
    customer: Customer
    balance_cents: int


def check_credit_available(
    balance_cents: int, charge_cents: int, limit_cents: int | None, decimal_separator: str = ","
) -> None:
    """Raise when charging ``charge_cents`` more would take the debt over the customer's limit."""
    if limit_cents is None or balance_cents + charge_cents <= limit_cents:
        return
    available = max(0, limit_cents - balance_cents)
    raise ValueError(
        "El fiado supera el límite de crédito del cliente. "
        f"Disponible: {format_usd(available, decimal_separator)}."
    )


def validate_abono(
    amount_cents: int,
    method: str,
    reference: str,
    balance_cents: int,
    decimal_separator: str = ",",
) -> str:
    """Check an abono against the balance; return the cleaned reference."""
    if amount_cents <= 0:
        raise ValueError("El abono debe ser mayor que cero.")
    if method not in ABONO_METHODS:
        raise ValueError("La forma de pago del abono no es válida.")
    reference = reference.strip()
    if method == "transfer" and not reference:
        raise ValueError("La transferencia necesita un número de referencia.")
    if len(reference) > NOTE_MAX_LENGTH:
        raise ValueError(f"La referencia no puede superar {NOTE_MAX_LENGTH} caracteres.")
    if amount_cents > balance_cents:
        raise ValueError(
            "El abono supera el saldo pendiente. "
            f"Saldo: {format_usd(balance_cents, decimal_separator)}."
        )
    return reference
