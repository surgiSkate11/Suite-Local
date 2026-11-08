"""RIDE: the printable form of an electronic invoice, laid out like the internal receipt."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from PySide6.QtGui import QImage, QTextDocument

from suitelocal.domain.business import BusinessSettings, validate_receipt_paper_mm
from suitelocal.domain.einvoice import (
    AUTHORIZED,
    BUYER_ID_TYPES,
    NORMAL_EMISSION,
    EInvoice,
    InvoiceData,
    payment_code,
)
from suitelocal.domain.money import format_usd
from suitelocal.ui.barcode import render_code128
from suitelocal.ui.receipt import (
    FONT_POINTS,
    MONOSPACE,
    RULE,
    QtReceiptDevice,
    ReceiptDevice,
    build_html_document,
    escape_html,
    printable_width_px,
    send_document,
)

__all__ = ["Ride", "RideOutput", "RidePrinter", "build_ride_document", "render_ride_html"]

BARCODE_RESOURCE = "ride-barcode"
# The image is drawn at 4 px per module and shown scaled down to the roll's width.
BARCODE_MODULE_PX = 4
BARCODE_QUIET_MODULES = 4
BARCODE_IMAGE_HEIGHT_PX = 160
BARCODE_SHOWN_HEIGHT_PX = 40
ENVIRONMENT_LABELS = {"pruebas": "PRUEBAS", "produccion": "PRODUCCIÓN"}
EMISSION_LABELS = {NORMAL_EMISSION: "NORMAL"}
# SRI "formaPago" names, by the code of each of our payment methods.
SRI_PAYMENT_NAMES = {
    "01": "Sin utilización del sistema financiero",
    "19": "Tarjeta de crédito",
    "20": "Otros con utilización del sistema financiero",
}
PENDING_TEXT = "Pendiente de autorización del SRI"


@dataclass(frozen=True, slots=True)
class Ride:
    """What a RIDE needs: the invoice as issued and its progress at the SRI."""

    invoice: InvoiceData
    einvoice: EInvoice


class RideOutput(Protocol):
    """What a screen needs to print a RIDE; tests inject a fake."""

    def print_ride(self, ride: Ride) -> None: ...


def render_ride_html(
    ride: Ride, decimal_separator: str, paper_mm: int, barcode_width_px: int
) -> str:
    """The RIDE as HTML for QTextDocument; every user text is escaped."""
    validate_receipt_paper_mm(paper_mm)
    invoice, einvoice = ride.invoice, ride.einvoice
    issuer, buyer = invoice.issuer, invoice.buyer

    def money(cents: int) -> str:
        return escape_html(format_usd(cents, decimal_separator))

    def centered(text: str, style: str = "") -> str:
        return f'<div align="center" style="{style}">{text}</div>'

    def pair(left: str, right: str, style: str = "") -> str:
        return (
            '<table width="100%" cellspacing="0" cellpadding="0" '
            f'style="{style}"><tr><td>{left}</td><td align="right">{right}</td></tr></table>'
        )

    parts = [centered(f"<b>{escape_html(issuer.legal_name)}</b>", "font-size: 1.2em;")]
    if issuer.trade_name:
        parts.append(centered(f"Nombre comercial: {escape_html(issuer.trade_name)}"))
    parts.append(centered(f"RUC: {escape_html(issuer.ruc)}"))
    parts.append(centered(f"Dirección: {escape_html(issuer.main_address)}"))
    accounting = "SI" if issuer.accounting_required else "NO"
    parts.append(centered(f"Obligado a llevar contabilidad: {accounting}"))
    if issuer.rimpe:
        parts.append(centered("<b>CONTRIBUYENTE RÉGIMEN RIMPE</b>"))
    parts.append(RULE)
    environment = ENVIRONMENT_LABELS.get(einvoice.environment, einvoice.environment.upper())
    # Only normal emission exists: offline contingency was dropped by the SRI.
    emission = EMISSION_LABELS[NORMAL_EMISSION]
    parts.append(centered("<b>FACTURA</b>", "font-size: 1.3em;"))
    parts.append(
        "<br/>".join(
            [
                f"No. {escape_html(einvoice.number)}",
                f"AMBIENTE: {escape_html(environment)}",
                f"EMISIÓN: {emission}",
            ]
        )
    )
    parts.append(RULE)
    if einvoice.status == AUTHORIZED and einvoice.authorization_number:
        authorized_text = ""
        if einvoice.authorized_at is not None:
            authorized_text = f"{einvoice.authorized_at.astimezone():%d/%m/%Y %H:%M:%S}"
        parts.append(
            "<b>NÚMERO DE AUTORIZACIÓN</b><br/>"
            f"{escape_html(einvoice.authorization_number)}<br/>"
            f"<b>FECHA DE AUTORIZACIÓN</b><br/>{escape_html(authorized_text)}"
        )
    else:
        parts.append(centered(f"<b>{PENDING_TEXT}</b>"))
    parts.append(RULE)
    parts.append("<b>CLAVE DE ACCESO</b>")
    parts.append(
        centered(
            f'<img src="{BARCODE_RESOURCE}" width="{barcode_width_px}" '
            f'height="{BARCODE_SHOWN_HEIGHT_PX}"/>'
        )
    )
    parts.append(centered(escape_html(einvoice.access_key), "font-size: 0.8em;"))
    parts.append(RULE)
    id_label = BUYER_ID_TYPES.get(buyer.id_type, "Identificación")
    buyer_lines = [
        f"Cliente: {escape_html(buyer.name)}",
        f"{escape_html(id_label)}: {escape_html(buyer.identification)}",
    ]
    if buyer.address:
        buyer_lines.append(f"Dirección: {escape_html(buyer.address)}")
    buyer_lines.append(f"Fecha de emisión: {invoice.issue_date:%d/%m/%Y}")
    parts.append("<br/>".join(buyer_lines))
    parts.append(RULE)
    for line in invoice.lines:
        parts.append(f"<div>{escape_html(line.description)}</div>")
        detail = f"{line.quantity} × {money(line.total_cents // line.quantity)}"
        parts.append(pair(detail, money(line.total_cents)))
    parts.append(RULE)
    for rate, base, tax in invoice.taxes:
        percent = f"{rate // 100} %"
        parts.append(pair(f"Subtotal {percent}", money(base)))
        if rate:
            parts.append(pair(f"IVA {percent}", money(tax)))
    parts.append(
        pair("<b>VALOR TOTAL</b>", f"<b>{money(invoice.total_cents)}</b>", "font-size: 1.2em;")
    )
    parts.append(RULE)
    parts.append("<b>FORMA DE PAGO</b>")
    for payment in invoice.payments:
        name = SRI_PAYMENT_NAMES.get(payment_code(payment.method), payment.method)
        parts.append(pair(escape_html(name), money(payment.amount_cents)))
    body = "\n".join(parts)
    return (
        f'<html><body style="font-family: {MONOSPACE}; font-size: {FONT_POINTS[paper_mm]}pt;">'
        f"{body}</body></html>"
    )


def build_ride_document(
    ride: Ride, decimal_separator: str, paper_mm: int
) -> tuple[QTextDocument, float]:
    """The laid-out RIDE with its barcode, and the page height (mm) a roll needs for it."""
    width = int(printable_width_px(paper_mm))
    barcode: QImage = render_code128(
        ride.einvoice.access_key,
        BARCODE_MODULE_PX,
        BARCODE_IMAGE_HEIGHT_PX,
        quiet_modules=BARCODE_QUIET_MODULES,
    )
    html_text = render_ride_html(ride, decimal_separator, paper_mm, width)
    return build_html_document(html_text, paper_mm, {BARCODE_RESOURCE: barcode})


class RidePrinter:
    """Prints a RIDE on the configured printer or saves it as a PDF, like the internal receipt."""

    def __init__(
        self,
        settings: Callable[[], BusinessSettings],
        device_factory: Callable[[], ReceiptDevice] = QtReceiptDevice,
    ) -> None:
        self._settings = settings
        self._device_factory = device_factory

    def print_ride(self, ride: Ride) -> None:
        business = self._settings()
        device = self._device_factory()
        device.use_printer(business.printer_name)
        self._send(device, ride, business)

    def save_pdf(self, ride: Ride, path: Path | str) -> None:
        business = self._settings()
        device = self._device_factory()
        device.use_pdf(Path(path))
        self._send(device, ride, business)

    @staticmethod
    def _send(device: ReceiptDevice, ride: Ride, business: BusinessSettings) -> None:
        document, height_mm = build_ride_document(
            ride, business.decimal_separator, business.receipt_paper_mm
        )
        send_document(device, document, height_mm, business.receipt_paper_mm)
