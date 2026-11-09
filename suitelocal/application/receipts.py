from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo

from suitelocal.application.credit import CreditService
from suitelocal.domain.auth import Session
from suitelocal.domain.business import SALES_NOTE_REGIME, TAX_REGIMES, charges_iva
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.settings import BusinessSettingsRepository

# Electronic invoices (T7b) are the only tax documents; this ticket never is one.
RECEIPT_LEGEND = "Comprobante interno, no válido como documento tributario."
_NUMBER_WIDTH = 6
_NOT_FOUND = "La venta no existe en este negocio."
_NO_TAX_BREAKDOWN = "Esta venta es anterior al desglose de IVA y no tiene ticket."


@dataclass(frozen=True, slots=True)
class ReceiptBusiness:
    name: str
    ruc: str
    address: str
    phone: str
    regime_label: str
    footer: str


@dataclass(frozen=True, slots=True)
class ReceiptLine:
    name: str
    quantity: int
    unit_price_cents: int
    total_cents: int
    tax_rate_basis_points: int


@dataclass(frozen=True, slots=True)
class ReceiptTax:
    """The taxable base and IVA of the lines sold at one rate."""

    tax_rate_basis_points: int
    base_cents: int
    tax_cents: int


@dataclass(frozen=True, slots=True)
class ReceiptPayment:
    method: str
    amount_cents: int
    reference: str


@dataclass(frozen=True, slots=True)
class Receipt:
    business: ReceiptBusiness
    number: str
    issued_at: datetime
    cashier: str
    lines: tuple[ReceiptLine, ...]
    subtotal_cents: int
    taxes: tuple[ReceiptTax, ...]
    total_cents: int
    payments: tuple[ReceiptPayment, ...]
    cash_received_cents: int
    change_cents: int
    legend: str = RECEIPT_LEGEND
    sales_note_number: str | None = None
    # False for the regimes that sell without IVA: the ticket then shows no IVA at all.
    charges_iva: bool = True
    # What the customer owes right after this sale; None when the sale had no fiado.
    credit_balance_cents: int | None = None


class ReceiptService:
    """Builds the internal receipt of a stored sale; nothing is recomputed from a cart."""

    def __init__(self, database: Database, timezone: tzinfo | None = None) -> None:
        self.database = database
        self.settings = BusinessSettingsRepository(database)
        # None means the computer's own time zone, which is what the cashier's clock shows.
        self.timezone = timezone

    def build(self, session: Session, sale_id: int) -> Receipt:
        business_id = session.user.business_id
        with self.database.connect() as connection:
            # A sale without a business (NULL) matches no session, so it is never readable.
            sale = connection.execute(
                """
                SELECT s.created_at, s.subtotal_cents, s.total_cents, s.change_cents,
                       s.sales_note_number, u.username
                FROM sales s
                LEFT JOIN users u ON u.id = s.user_id
                WHERE s.id = ? AND s.business_id = ?
                """,
                (sale_id, business_id),
            ).fetchone()
            if sale is None:
                raise ValueError(_NOT_FOUND)
            items = connection.execute(
                """
                SELECT product_name, quantity, unit_price_cents, tax_rate_basis_points, tax_cents
                FROM sale_items WHERE sale_id = ? ORDER BY id
                """,
                (sale_id,),
            ).fetchall()
            payments = connection.execute(
                "SELECT method, amount_cents, reference FROM sale_payments "
                "WHERE sale_id = ? ORDER BY id",
                (sale_id,),
            ).fetchall()
        if any(
            item["tax_rate_basis_points"] is None or item["tax_cents"] is None for item in items
        ):
            raise ValueError(_NO_TAX_BREAKDOWN)
        business = self.settings.get(business_id)
        lines = tuple(
            ReceiptLine(
                item["product_name"],
                item["quantity"],
                item["unit_price_cents"],
                item["quantity"] * item["unit_price_cents"],
                item["tax_rate_basis_points"],
            )
            for item in items
        )
        grouped: dict[int, tuple[int, int]] = {}
        for item, line in zip(items, lines, strict=True):
            base, tax = grouped.get(line.tax_rate_basis_points, (0, 0))
            grouped[line.tax_rate_basis_points] = (
                base + line.total_cents - item["tax_cents"],
                tax + item["tax_cents"],
            )
        taxes = tuple(
            ReceiptTax(rate, base, tax)
            for rate, (base, tax) in sorted(grouped.items(), reverse=True)
        )
        issued_at = datetime.fromisoformat(sale["created_at"]).replace(tzinfo=UTC)
        return Receipt(
            ReceiptBusiness(
                business.name,
                business.ruc,
                business.address,
                business.phone,
                TAX_REGIMES[business.tax_regime],
                business.receipt_footer,
            ),
            f"{sale_id:0{_NUMBER_WIDTH}d}",
            issued_at.astimezone(self.timezone),
            sale["username"] or "",
            lines,
            sale["subtotal_cents"],
            taxes,
            sale["total_cents"],
            tuple(
                ReceiptPayment(row["method"], row["amount_cents"], row["reference"])
                for row in payments
            ),
            sum(row["amount_cents"] for row in payments if row["method"] == "cash"),
            sale["change_cents"],
            sales_note_number=(
                sale["sales_note_number"] if business.tax_regime == SALES_NOTE_REGIME else None
            ),
            charges_iva=charges_iva(business.tax_regime),
            credit_balance_cents=CreditService(self.database).balance_after_sale(session, sale_id),
        )
