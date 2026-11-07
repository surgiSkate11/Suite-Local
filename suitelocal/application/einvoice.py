from datetime import tzinfo

from suitelocal.application.receipts import ReceiptService
from suitelocal.domain.auth import Session
from suitelocal.domain.business import issues_electronic_invoices
from suitelocal.domain.einvoice import (
    Buyer,
    InvoiceData,
    InvoiceEmission,
    InvoiceIssuer,
    InvoiceLine,
    InvoicePayment,
)
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.settings import BusinessSettingsRepository

_RIMPE_REGIME = "rimpe_emprendedor"
_NOT_INVOICING = "El régimen tributario de este negocio no emite facturas electrónicas."
_INCONSISTENT = "La venta no cuadra con su desglose de IVA y no se puede facturar."


def build_invoice_data(
    database: Database,
    session: Session,
    sale_id: int,
    buyer: Buyer,
    emission: InvoiceEmission,
    *,
    timezone: tzinfo | None = None,
) -> InvoiceData:
    """Assemble the invoice of a stored sale from its receipt, the business settings and the buyer.

    Nothing is recomputed from a cart: lines, IVA and payments are the ones stored with the sale.
    """
    # The receipt service enforces that the sale belongs to the session's business.
    receipt = ReceiptService(database, timezone).build(session, sale_id)
    settings = BusinessSettingsRepository(database).get(session.user.business_id)
    if not issues_electronic_invoices(settings.tax_regime):
        raise ValueError(_NOT_INVOICING)
    with database.connect() as connection:
        codes = [
            row["code"]
            for row in connection.execute(
                """
                SELECT p.code FROM sale_items i JOIN products p ON p.id = i.product_id
                WHERE i.sale_id = ? ORDER BY i.id
                """,
                (sale_id,),
            )
        ]
    if len(codes) != len(receipt.lines):
        raise ValueError(_INCONSISTENT)
    lines = tuple(
        InvoiceLine(code, line.name, line.quantity, line.total_cents, line.tax_rate_basis_points)
        for code, line in zip(codes, receipt.lines, strict=True)
    )
    # Cash is stored as received; the SRI wants what was paid, so the change comes off the cash.
    payments: list[InvoicePayment] = []
    for payment in receipt.payments:
        paid = payment.amount_cents - (receipt.change_cents if payment.method == "cash" else 0)
        if paid > 0:
            payments.append(InvoicePayment(payment.method, paid))
    invoice = InvoiceData(
        InvoiceIssuer(
            ruc=settings.ruc,
            legal_name=settings.name,
            main_address=settings.address,
            rimpe=settings.tax_regime == _RIMPE_REGIME,
        ),
        emission,
        receipt.issued_at.date(),
        buyer,
        lines,
        tuple(payments),
    )
    stored_taxes = tuple(
        (tax.tax_rate_basis_points, tax.base_cents, tax.tax_cents) for tax in receipt.taxes
    )
    if invoice.total_cents != receipt.total_cents or invoice.taxes != stored_taxes:
        raise ValueError(_INCONSISTENT)
    return invoice
