import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Protocol

from suitelocal.application.receipts import ReceiptService
from suitelocal.domain.auth import Session
from suitelocal.domain.business import issues_electronic_invoices
from suitelocal.domain.einvoice import (
    AUTHORIZED,
    INVOICE_DOC_TYPE,
    LOCAL_ERROR,
    NOT_AUTHORIZED,
    PENDING,
    RECEIVED,
    REISSUABLE_STATUSES,
    RETURNED,
    Buyer,
    EInvoice,
    InvoiceData,
    InvoiceEmission,
    InvoiceIssuer,
    InvoiceLine,
    InvoicePayment,
    SriMessage,
    access_key,
    retry_delay,
    sri_environment_code,
)
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.settings import BusinessSettingsRepository
from suitelocal.infrastructure.sri.certificate_store import CertificateStore
from suitelocal.infrastructure.sri.client import (
    AUTHORIZED_STATE,
    NOT_AUTHORIZED_STATE,
    AuthorizationResult,
    ReceptionResult,
    SriUnavailable,
)
from suitelocal.infrastructure.sri.invoice_xml import build_invoice_xml, validate_against_xsd
from suitelocal.infrastructure.sri.queue import EInvoiceRepository
from suitelocal.infrastructure.sri.xades import (
    SigningError,
    sign_invoice,
    verify_invoice_signature,
)

_RIMPE_REGIME = "rimpe_emprendedor"
_NOT_INVOICING = "El régimen tributario de este negocio no emite facturas electrónicas."
_INCONSISTENT = "La venta no cuadra con su desglose de IVA y no se puede facturar."
_NOT_ENABLED = "La factura electrónica no está activada para este negocio."
_SALE_NOT_FOUND = "La venta no existe en este negocio."
_ALREADY_INVOICED = "Esta venta ya tiene una factura electrónica."
_NO_INVOICE = "La venta no tiene una factura electrónica para reemitir."
_NOT_REISSUABLE = "Solo se puede reemitir una factura devuelta, no autorizada o con error local."
_BAD_SIGNATURE = "La firma generada no se pudo verificar y la factura no se guardó."
_CORRUPT = "El comprobante guardado no pasa la verificación de la firma y no se puede enviar."
# "Clave acceso registrada" (43) and "clave de acceso en procesamiento" (70): the SRI already has
# the invoice, so the right move is to ask for its authorization rather than to fail.
_ALREADY_KNOWN_IDENTIFIERS = frozenset({"43", "70"})
_IN_PROCESS_RETRY = timedelta(minutes=1)


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
            trade_name=settings.trade_name,
            accounting_required=settings.obligado_contabilidad,
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


class EInvoiceService:
    """Turns a stored sale into a signed invoice waiting in the send queue."""

    def __init__(
        self,
        database: Database,
        certificates: Callable[[int], CertificateStore],
        *,
        timezone: tzinfo | None = None,
        clock: Callable[[], datetime] | None = None,
        numeric_code: Callable[[], str] | None = None,
    ) -> None:
        self.database = database
        self.settings = BusinessSettingsRepository(database)
        self.repository = EInvoiceRepository(database)
        self._certificates = certificates
        self.timezone = timezone
        self._clock = clock or (lambda: datetime.now(UTC))
        self._numeric_code = numeric_code or (lambda: f"{secrets.randbelow(10**8):08d}")

    def issue_for_sale(self, session: Session, sale_id: int, buyer: Buyer) -> EInvoice:
        """Build, validate, sign and queue the invoice of a sale as "pendiente".

        Runs after the sale is committed and never writes to it, so a failure here (raised as
        ValueError with a Spanish message) leaves the sale untouched. The sequential number,
        the invoice row and its signature are one transaction: nothing is stored, and no number
        is burned, unless all of it succeeds.
        """
        return self._issue(session, sale_id, buyer, reissue=False)

    def reissue_for_sale(
        self, session: Session, sale_id: int, buyer: Buyer | None = None
    ) -> EInvoice:
        """Issue again the invoice of a sale whose invoice was refused, with a new number.

        Only a "devuelta", "no_autorizada" or "error_local" invoice qualifies: one that is
        pending, received or authorized may still be, or already is, valid at the SRI. The old
        row stays as "reemplazada" and points to the new one, all in one transaction. The buyer
        of the old invoice is kept unless a new one is given.
        """
        return self._issue(session, sale_id, buyer, reissue=True)

    def _issue(
        self, session: Session, sale_id: int, buyer: Buyer | None, *, reissue: bool
    ) -> EInvoice:
        business_id = session.user.business_id
        settings = self.settings.get(business_id)
        if not settings.einvoice_enabled:
            raise ValueError(_NOT_ENABLED)
        p12_bytes, password = self._certificates(business_id).load()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            sale = connection.execute(
                "SELECT created_at FROM sales WHERE id = ? AND business_id = ?",
                (sale_id, business_id),
            ).fetchone()
            if sale is None:
                raise ValueError(_SALE_NOT_FOUND)
            replaced: EInvoice | None = None
            if reissue:
                replaced = self.repository.active_for_sale(connection, sale_id)
                if replaced is None:
                    raise ValueError(_NO_INVOICE)
                if replaced.status not in REISSUABLE_STATUSES:
                    raise ValueError(_NOT_REISSUABLE)
                buyer = buyer or replaced.buyer
            elif self.repository.sale_invoice_exists(connection, sale_id):
                raise ValueError(_ALREADY_INVOICED)
            assert buyer is not None
            sequential = self.repository.allocate_sequential(
                connection,
                business_id,
                settings.sri_environment,
                settings.establishment,
                settings.emission_point,
            )
            emission = InvoiceEmission(
                sri_environment_code(settings.sri_environment),
                settings.establishment,
                settings.emission_point,
                f"{sequential:09d}",
                self._numeric_code(),
            )
            invoice = build_invoice_data(
                self.database, session, sale_id, buyer, emission, timezone=self.timezone
            )
            unsigned = build_invoice_xml(invoice)
            validate_against_xsd(unsigned)
            signed = sign_invoice(unsigned, p12_bytes, password, now=self._clock())
            if not verify_invoice_signature(signed):
                raise SigningError(_BAD_SIGNATURE)
            if replaced is not None:
                # Before the insert: only one non-replaced row per sale can exist.
                self.repository.replace(connection, replaced.id)
            new_id = self.repository.insert(
                connection,
                business_id=business_id,
                sale_id=sale_id,
                establishment=emission.establishment,
                emission_point=emission.emission_point,
                sequential=emission.sequential,
                access_key=access_key(
                    invoice.issue_date,
                    INVOICE_DOC_TYPE,
                    invoice.issuer.ruc,
                    emission.environment,
                    emission.establishment,
                    emission.emission_point,
                    emission.sequential,
                    emission.numeric_code,
                ),
                environment=settings.sri_environment,
                signed_xml=signed,
                buyer=buyer,
                issued_at=datetime.fromisoformat(sale["created_at"]).replace(tzinfo=UTC),
            )
            if replaced is not None:
                self.repository.link_replacement(connection, replaced.id, new_id)
        stored = self.repository.get_for_sale(business_id, sale_id)
        assert stored is not None
        return stored

    def get_for_sale(self, session: Session, sale_id: int) -> EInvoice | None:
        return self.repository.get_for_sale(session.user.business_id, sale_id)

    def list_for_business(self, session: Session, limit: int = 100) -> list[EInvoice]:
        """The business's invoices, newest first."""
        return self.repository.list_for_business(session.user.business_id, limit)


class SriGateway(Protocol):
    """What the processor needs from the SRI: SriClient, or a fake in tests."""

    def send(self, signed_xml: bytes) -> ReceptionResult: ...

    def authorize(self, access_key: str) -> AuthorizationResult: ...


@dataclass(frozen=True, slots=True)
class ProcessReport:
    """What one pass did, as invoice ids."""

    # Received by the SRI in this pass.
    sent: tuple[int, ...] = ()
    authorized: tuple[int, ...] = ()
    # Refused for good: returned, not authorized or a local error.
    rejected: tuple[int, ...] = ()
    # Tried but the SRI was unreachable: they wait for their next attempt.
    deferred: tuple[int, ...] = ()
    # Still not received by the SRI more than 60 hours after the sale (the limit is 72).
    near_deadline: tuple[int, ...] = ()


class EInvoiceProcessor:
    """Sends the pending invoices and follows the received ones to their authorization.

    A pure API: the caller (a timer in the UI) decides when to call it and passes the time.
    `client_for` maps an environment name to a gateway; it is required so that nothing can
    reach the network by accident.
    """

    def __init__(self, database: Database, client_for: Callable[[str], SriGateway]) -> None:
        self.repository = EInvoiceRepository(database)
        self._client_for = client_for

    def process_pending(self, now: datetime, business_id: int | None = None) -> ProcessReport:
        sent: list[int] = []
        authorized: list[int] = []
        rejected: list[int] = []
        deferred: list[int] = []
        gateways: dict[str, SriGateway] = {}
        unreachable: set[str] = set()
        for invoice in self.repository.due(now, business_id):
            # One unreachable answer is enough for this pass: skip the rest instead of waiting
            # for the same timeout once per invoice.
            if invoice.environment in unreachable:
                continue
            if invoice.environment not in gateways:
                gateways[invoice.environment] = self._client_for(invoice.environment)
            gateway = gateways[invoice.environment]
            try:
                if invoice.status == PENDING:
                    outcome = self._send(invoice, gateway, now)
                else:
                    outcome = self._poll(invoice, gateway, now)
            except SriUnavailable:
                unreachable.add(invoice.environment)
                attempts = invoice.attempts + 1
                self.repository.record(
                    invoice.id,
                    status=invoice.status,
                    attempts=attempts,
                    next_attempt_at=now + retry_delay(attempts),
                )
                deferred.append(invoice.id)
                continue
            if outcome == RECEIVED and invoice.status == PENDING:
                sent.append(invoice.id)
            elif outcome == AUTHORIZED:
                authorized.append(invoice.id)
            elif outcome in (RETURNED, NOT_AUTHORIZED, LOCAL_ERROR):
                rejected.append(invoice.id)
        return ProcessReport(
            tuple(sent),
            tuple(authorized),
            tuple(rejected),
            tuple(deferred),
            self.deadline_warnings(now, business_id),
        )

    def deadline_warnings(self, now: datetime, business_id: int | None = None) -> tuple[int, ...]:
        """Invoices the SRI still has not received 60+ hours after the sale (limit: 72 hours)."""
        return tuple(self.repository.near_deadline(now, business_id))

    def _send(self, invoice: EInvoice, gateway: SriGateway, now: datetime) -> str:
        if not verify_invoice_signature(invoice.signed_xml):
            self.repository.record(
                invoice.id,
                status=LOCAL_ERROR,
                attempts=invoice.attempts,
                next_attempt_at=None,
                messages=(SriMessage("LOCAL", _CORRUPT, "", "ERROR"),),
            )
            return LOCAL_ERROR
        result = gateway.send(invoice.signed_xml)
        if result.received:
            self.repository.record(
                invoice.id,
                status=RECEIVED,
                attempts=0,
                next_attempt_at=now,
                messages=result.messages,
            )
            return RECEIVED
        if _ALREADY_KNOWN_IDENTIFIERS.intersection(result.identifiers):
            return self._poll(invoice, gateway, now)
        self.repository.record(
            invoice.id,
            status=RETURNED,
            attempts=invoice.attempts,
            next_attempt_at=None,
            messages=result.messages,
        )
        return RETURNED

    def _poll(self, invoice: EInvoice, gateway: SriGateway, now: datetime) -> str:
        result = gateway.authorize(invoice.access_key)
        if result.state == AUTHORIZED_STATE:
            self.repository.record(
                invoice.id,
                status=AUTHORIZED,
                attempts=0,
                next_attempt_at=None,
                messages=result.messages,
                authorization_number=result.authorization_number or invoice.access_key,
                authorized_at=result.authorized_at or now,
            )
            return AUTHORIZED
        if result.state == NOT_AUTHORIZED_STATE:
            self.repository.record(
                invoice.id,
                status=NOT_AUTHORIZED,
                attempts=0,
                next_attempt_at=None,
                messages=result.messages,
            )
            return NOT_AUTHORIZED
        # The SRI has it but has not decided yet: ask again in a minute.
        self.repository.record(
            invoice.id,
            status=RECEIVED,
            attempts=0,
            next_attempt_at=now + _IN_PROCESS_RETRY,
            messages=result.messages,
        )
        return RECEIVED


@dataclass(frozen=True, slots=True)
class PassResult:
    """The outcome of one background pass: what it did, how many invoices are still open."""

    report: ProcessReport | None
    # None when it could not even be counted.
    open_count: int | None
    error: str = ""


def run_processing_pass(
    database_path: Path | str,
    business_id: int,
    client_for: Callable[[str], SriGateway],
    now: datetime,
) -> PassResult:
    """One processing pass over a business, safe to run on a worker thread.

    It opens its own database handle, so it shares no connection with the caller, and it never
    raises: whatever goes wrong comes back as `error`, because nobody can catch it on a worker.
    """
    database = Database(database_path)
    repository = EInvoiceRepository(database)
    report: ProcessReport | None = None
    error = ""
    try:
        report = EInvoiceProcessor(database, client_for).process_pending(now, business_id)
    except Exception as failure:  # reported to the caller instead
        error = str(failure) or type(failure).__name__
    try:
        open_count: int | None = repository.count_open(business_id)
    except Exception:  # an unreadable count must not hide the pass result
        open_count = None
    return PassResult(report, open_count, error)
