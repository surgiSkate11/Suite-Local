from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ApprovedPayment:
    reference: str


class PaymentTerminalPort(Protocol):
    def charge(self, amount_cents: int) -> ApprovedPayment:
        """Charge a card through the configured external terminal."""
        raise NotImplementedError
