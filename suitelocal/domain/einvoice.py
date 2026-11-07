"""Rules of the SRI electronic invoice (factura 1.1.0): access key, buyer, IVA and payment codes."""

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from suitelocal.domain.models import PAYMENT_METHODS
from suitelocal.domain.tax import tax_breakdown, validate_tax_rate

INVOICE_DOC_TYPE = "01"
NORMAL_EMISSION = "1"
# SRI "tipoIdentificacionComprador" table.
BUYER_ID_TYPES = {
    "04": "RUC",
    "05": "Cédula",
    "06": "Pasaporte",
    "07": "Consumidor final",
    "08": "Identificación del exterior",
}
FINAL_CONSUMER_ID = "9999999999999"
FINAL_CONSUMER_NAME = "CONSUMIDOR FINAL"
# A final consumer can only be invoiced up to USD 50.
FINAL_CONSUMER_LIMIT_CENTS = 5000
BUYER_ID_MAX_LENGTH = 20

# SRI IVA "codigoPorcentaje" by our rate in basis points.
_IVA_CODES = {1500: "4", 500: "5", 0: "0"}
# Cash is "sin utilización del sistema financiero", a transfer is "otros con utilización del
# sistema financiero" and a card is "tarjeta de crédito" (the POS cannot tell debit apart).
_PAYMENT_CODES = {"cash": "01", "transfer": "20", "card": "19"}
_WEIGHTS = (2, 3, 4, 5, 6, 7)
_DIGITS = re.compile(r"[0-9]+")


def modulo11_check_digit(digits: str) -> str:
    """SRI módulo 11: weights 2..7 cycling from the right; 11 becomes 0 and 10 becomes 1."""
    total = sum(
        int(digit) * _WEIGHTS[position % len(_WEIGHTS)]
        for position, digit in enumerate(reversed(digits))
    )
    result = 11 - total % 11
    if result == 11:
        return "0"
    if result == 10:
        return "1"
    return str(result)


def _numeric(value: str, label: str, length: int) -> str:
    if len(value) != length or not _DIGITS.fullmatch(value):
        raise ValueError(f"{label} debe tener exactamente {length} dígitos.")
    return value


def access_key(
    issue_date: date,
    doc_type: str,
    ruc: str,
    environment: str,
    establishment: str,
    emission_point: str,
    sequential: str,
    numeric_code: str,
    emission_type: str = NORMAL_EMISSION,
) -> str:
    """The 49-digit clave de acceso: 48 digits plus the módulo 11 check digit."""
    if environment not in ("1", "2"):
        raise ValueError("El ambiente debe ser 1 (pruebas) o 2 (producción).")
    if emission_type not in ("1", "2"):
        raise ValueError("El tipo de emisión debe ser 1 o 2.")
    base = (
        f"{issue_date.day:02d}{issue_date.month:02d}{issue_date.year:04d}"
        + _numeric(doc_type, "El tipo de comprobante", 2)
        + _numeric(ruc, "El RUC", 13)
        + environment
        + _numeric(establishment, "El establecimiento", 3)
        + _numeric(emission_point, "El punto de emisión", 3)
        + _numeric(sequential, "El secuencial", 9)
        + _numeric(numeric_code, "El código numérico", 8)
        + emission_type
    )
    return base + modulo11_check_digit(base)


def iva_percentage_code(rate_basis_points: int) -> str:
    """SRI codigoPorcentaje of an IVA rate: 15 % -> 4, 5 % -> 5, 0 % -> 0."""
    return _IVA_CODES[validate_tax_rate(rate_basis_points)]


def payment_code(method: str) -> str:
    """SRI formaPago code of one of our payment methods."""
    if method not in PAYMENT_METHODS:
        raise ValueError("La forma de pago no es válida.")
    return _PAYMENT_CODES[method]


@dataclass(frozen=True, slots=True)
class Buyer:
    id_type: str
    identification: str
    name: str
    address: str = ""

    @classmethod
    def final_consumer(cls) -> "Buyer":
        return cls("07", FINAL_CONSUMER_ID, FINAL_CONSUMER_NAME)


def validate_buyer(buyer: Buyer, total_cents: int) -> None:
    """Check the buyer's identification against its type and the invoice total."""
    if buyer.id_type not in BUYER_ID_TYPES:
        raise ValueError("El tipo de identificación del comprador no es válido.")
    if not buyer.name.strip():
        raise ValueError("El nombre del comprador es obligatorio.")
    identification = buyer.identification
    if buyer.id_type == "07":
        if identification != FINAL_CONSUMER_ID:
            raise ValueError(f"El consumidor final se identifica solo con {FINAL_CONSUMER_ID}.")
        if total_cents > FINAL_CONSUMER_LIMIT_CENTS:
            raise ValueError("Una factura a consumidor final no puede superar USD 50.")
        return
    if identification == FINAL_CONSUMER_ID:
        raise ValueError(f"El número {FINAL_CONSUMER_ID} es solo para consumidor final.")
    if buyer.id_type == "05":
        _numeric(identification, "La cédula", 10)
    elif buyer.id_type == "04":
        if len(identification) != 13 or not _DIGITS.fullmatch(identification):
            raise ValueError("El RUC del comprador debe tener 13 dígitos.")
        if identification.endswith("000"):
            raise ValueError("El RUC del comprador no puede terminar en 000.")
    elif not identification:
        raise ValueError("La identificación del comprador es obligatoria.")
    elif len(identification) > BUYER_ID_MAX_LENGTH:
        raise ValueError(
            f"La identificación del comprador no puede superar {BUYER_ID_MAX_LENGTH} caracteres."
        )


@dataclass(frozen=True, slots=True)
class InvoiceIssuer:
    ruc: str
    legal_name: str
    main_address: str
    trade_name: str = ""
    # Empty means the establishment is at the main address.
    establishment_address: str = ""
    accounting_required: bool = False
    special_taxpayer: str = ""
    # RIMPE emprendedor invoices carry the "CONTRIBUYENTE RÉGIMEN RIMPE" legend.
    rimpe: bool = False


@dataclass(frozen=True, slots=True)
class InvoiceEmission:
    """The numbering of one invoice: environment, series, sequential and numeric code."""

    environment: str
    establishment: str
    emission_point: str
    sequential: str
    numeric_code: str


@dataclass(frozen=True, slots=True)
class InvoiceLine:
    code: str
    description: str
    quantity: int
    # The final line price, IVA included; the XML splits it into base and IVA.
    total_cents: int
    tax_rate_basis_points: int


@dataclass(frozen=True, slots=True)
class InvoicePayment:
    method: str
    # What was actually paid: cash is net of the change given back.
    amount_cents: int


@dataclass(frozen=True, slots=True)
class InvoiceData:
    issuer: InvoiceIssuer
    emission: InvoiceEmission
    issue_date: date
    buyer: Buyer
    lines: tuple[InvoiceLine, ...]
    payments: tuple[InvoicePayment, ...]

    @property
    def total_cents(self) -> int:
        return sum(line.total_cents for line in self.lines)

    @property
    def taxes(self) -> tuple[tuple[int, int, int], ...]:
        """(rate, taxable base, IVA) per rate, highest rate first."""
        return tax_breakdown((line.total_cents, line.tax_rate_basis_points) for line in self.lines)


# -- the send queue ------------------------------------------------------------------------

# Statuses of an invoice in the send queue. "pendiente" waits to be sent, "recibida" was accepted
# by the SRI and waits for its authorization, "devuelta" was refused on reception, "autorizada"
# and "no_autorizada" are the SRI's final verdicts and "error_local" never left this computer.
PENDING = "pendiente"
RECEIVED = "recibida"
RETURNED = "devuelta"
AUTHORIZED = "autorizada"
NOT_AUTHORIZED = "no_autorizada"
LOCAL_ERROR = "error_local"
EINVOICE_STATUSES = (PENDING, RECEIVED, RETURNED, AUTHORIZED, NOT_AUTHORIZED, LOCAL_ERROR)

# The SRI accepts an invoice up to 72 hours after its issue date; the owner is warned from 60.
SEND_DEADLINE = timedelta(hours=72)
DEADLINE_WARNING_AFTER = timedelta(hours=60)

_RETRY_DELAYS = tuple(timedelta(minutes=minutes) for minutes in (1, 5, 15, 30, 60))
_SRI_ENVIRONMENT_CODES = {"pruebas": "1", "produccion": "2"}


def retry_delay(attempts: int) -> timedelta:
    """Wait after the `attempts`-th consecutive failure: 1, 5, 15, 30, 60 minutes, then hourly."""
    if attempts < 1:
        raise ValueError("El primer intento fallido es el número 1.")
    return _RETRY_DELAYS[min(attempts, len(_RETRY_DELAYS)) - 1]


def sri_environment_code(environment: str) -> str:
    """SRI "ambiente" digit of our environment name: pruebas -> 1, produccion -> 2."""
    if environment not in _SRI_ENVIRONMENT_CODES:
        raise ValueError("El ambiente del SRI debe ser pruebas o producción.")
    return _SRI_ENVIRONMENT_CODES[environment]


@dataclass(frozen=True, slots=True)
class SriMessage:
    """One message of an SRI response; `identifier` is the SRI error number (e.g. "43")."""

    identifier: str
    message: str
    additional_info: str = ""
    kind: str = ""


@dataclass(frozen=True, slots=True)
class EInvoice:
    """An invoice of the send queue: its numbering, signed XML, buyer and SRI progress."""

    id: int
    business_id: int
    sale_id: int
    establishment: str
    emission_point: str
    sequential: str
    access_key: str
    environment: str
    status: str
    signed_xml: bytes = field(repr=False)
    buyer: Buyer
    messages: tuple[SriMessage, ...]
    # Consecutive failed attempts with the current step (sending, then asking for authorization).
    attempts: int
    # None means due right away.
    next_attempt_at: datetime | None
    # The moment of the sale: the 72-hour deadline counts from the invoice date.
    issued_at: datetime
    authorized_at: datetime | None
    authorization_number: str | None

    @property
    def number(self) -> str:
        return f"{self.establishment}-{self.emission_point}-{self.sequential}"
