"""Internal sale receipt: HTML layout for 58/80 mm paper, Windows printing and PDF export."""

import html
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QMarginsF, QSizeF
from PySide6.QtGui import (
    QGuiApplication,
    QPagedPaintDevice,
    QPageLayout,
    QPageSize,
    QPdfWriter,
    QTextDocument,
)
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo

from suitelocal.application.receipts import Receipt
from suitelocal.domain.business import BusinessSettings, validate_receipt_paper_mm
from suitelocal.domain.money import format_usd
from suitelocal.ui.payment_dialog import METHOD_LABELS

__all__ = [
    "DEFAULT_PRINTER_LABEL",
    "QtReceiptDevice",
    "ReceiptDevice",
    "ReceiptOutput",
    "ReceiptPrintError",
    "ReceiptPrinter",
    "build_receipt_document",
    "installed_printer_names",
    "printer_status_text",
    "render_receipt_html",
]

DEFAULT_PRINTER_LABEL = "Predeterminada del sistema"
PAGE_MARGIN_MM = 3.0
# Room kept below the last line so the roll is not cut through the text.
TAIL_MM = 6.0
MM_PER_INCH = 25.4
MONOSPACE = "'Consolas', 'Courier New', monospace"
# Font size per roll width: ~32 columns on 58 mm and ~42 on 80 mm.
FONT_POINTS = {58: 7.0, 80: 8.5}
RULE = '<hr style="border-top: 1px dashed black;"/>'


class ReceiptPrintError(RuntimeError):
    """The receipt could not be sent to the printer or the file."""


class ReceiptOutput(Protocol):
    """What a screen needs to print a receipt; tests inject a fake."""

    def print_receipt(self, receipt: Receipt) -> None: ...


class ReceiptDevice(Protocol):
    """Where a laid-out receipt goes: a Windows printer or a PDF file (a QPrinter, or a fake)."""

    def use_printer(self, name: str) -> None:
        """Print on the named Windows printer; an empty name means the system default."""
        ...

    def use_pdf(self, path: Path) -> None: ...

    def set_paper(self, width_mm: float, height_mm: float, margin_mm: float) -> None: ...

    def print_document(self, document: QTextDocument) -> None: ...


class QtReceiptDevice:
    """The real device: a QPrinter (58/80 mm thermal printers work through their driver) or a PDF.

    The target is created only once it is known, because building a QPrinter queries the
    printer driver and a PDF must never touch one.
    """

    # Building a QPrinter queries the driver and can take tens of seconds on some printers,
    # so each printer is built once per run and reused for every later receipt.
    _printers: dict[str, QPrinter] = {}

    def __init__(self) -> None:
        self._target: QPagedPaintDevice | None = None

    def use_printer(self, name: str) -> None:
        if name and name not in QPrinterInfo.availablePrinterNames():
            raise ReceiptPrintError(f"La impresora «{name}» no está instalada.")
        info = QPrinterInfo.printerInfo(name) if name else QPrinterInfo.defaultPrinter()
        if info.isNull():
            raise ReceiptPrintError("No hay una impresora predeterminada en el sistema.")
        key = info.printerName()
        printer = self._printers.get(key)
        if printer is None:
            printer = QPrinter(info, QPrinter.PrinterMode.HighResolution)
            self._printers[key] = printer
        self._target = printer

    def use_pdf(self, path: Path) -> None:
        self._target = QPdfWriter(str(path))

    def set_paper(self, width_mm: float, height_mm: float, margin_mm: float) -> None:
        target = self._require_target()
        target.setPageSize(QPageSize(QSizeF(width_mm, height_mm), QPageSize.Unit.Millimeter))
        target.setPageMargins(
            QMarginsF(margin_mm, margin_mm, margin_mm, margin_mm), QPageLayout.Unit.Millimeter
        )

    def print_document(self, document: QTextDocument) -> None:
        target = self._require_target()
        if isinstance(target, QPrinter) and not target.isValid():
            raise ReceiptPrintError("La impresora no está disponible.")
        document.print_(target)

    def _require_target(self) -> QPagedPaintDevice:
        if self._target is None:
            raise ReceiptPrintError("No se eligió una impresora ni un archivo.")
        return self._target


def installed_printer_names() -> list[str]:
    """Names of the printers Windows has installed, for the settings combo."""
    return list(QPrinterInfo.availablePrinterNames())


def printer_status_text(printer_name: str) -> str:
    return f"Impresora: {printer_name}" if printer_name else "Impresora: predeterminada"


def _escape(text: str) -> str:
    return html.escape(text, quote=True)


def _percent(rate_basis_points: int) -> str:
    return f"{rate_basis_points // 100} %"


def render_receipt_html(receipt: Receipt, decimal_separator: str, paper_mm: int) -> str:
    """The receipt as HTML for QTextDocument; every user text is escaped."""
    validate_receipt_paper_mm(paper_mm)

    def money(cents: int) -> str:
        return _escape(format_usd(cents, decimal_separator))

    def centered(text: str, style: str = "") -> str:
        return f'<div align="center" style="{style}">{text}</div>'

    def pair(left: str, right: str, style: str = "") -> str:
        return (
            '<table width="100%" cellspacing="0" cellpadding="0" '
            f'style="{style}"><tr><td>{left}</td><td align="right">{right}</td></tr></table>'
        )

    business = receipt.business
    parts = [centered(f"<b>{_escape(business.name)}</b>", "font-size: 1.3em;")]
    if business.ruc:
        parts.append(centered(f"RUC: {_escape(business.ruc)}"))
    if business.address:
        parts.append(centered(_escape(business.address)))
    if business.phone:
        parts.append(centered(f"Tel.: {_escape(business.phone)}"))
    parts.append(centered(_escape(business.regime_label)))
    parts.append(RULE)
    info = [
        f"<b>Ticket N.º {_escape(receipt.number)}</b>",
        f"Fecha: {receipt.issued_at:%d/%m/%Y %H:%M}",
    ]
    if receipt.cashier:
        info.append(f"Cajero: {_escape(receipt.cashier)}")
    if receipt.sales_note_number:
        info.append(f"Nota de venta N.º {_escape(receipt.sales_note_number)}")
    parts.append("<br/>".join(info))
    parts.append(RULE)
    for line in receipt.lines:
        parts.append(f"<div>{_escape(line.name)}</div>")
        detail = (
            f"{line.quantity} × {money(line.unit_price_cents)} "
            f"(IVA {_percent(line.tax_rate_basis_points)})"
        )
        parts.append(pair(detail, money(line.total_cents)))
    parts.append(RULE)
    parts.append(pair("Subtotal", money(receipt.subtotal_cents)))
    for tax in receipt.taxes:
        parts.append(pair(f"Base {_percent(tax.tax_rate_basis_points)}", money(tax.base_cents)))
        if tax.tax_rate_basis_points:
            parts.append(pair(f"IVA {_percent(tax.tax_rate_basis_points)}", money(tax.tax_cents)))
    parts.append(pair("<b>TOTAL</b>", f"<b>{money(receipt.total_cents)}</b>", "font-size: 1.2em;"))
    parts.append(RULE)
    for payment in receipt.payments:
        label = _escape(METHOD_LABELS.get(payment.method, payment.method))
        if payment.reference:
            label += f" ({_escape(payment.reference)})"
        parts.append(pair(label, money(payment.amount_cents)))
    if receipt.change_cents:
        parts.append(pair("Cambio", money(receipt.change_cents)))
    parts.append(RULE)
    parts.append(centered(_escape(receipt.legend), "font-size: 0.9em;"))
    if business.footer:
        parts.append("<br/>")
        parts.append(centered(_escape(business.footer).replace("\n", "<br/>")))
    body = "\n".join(parts)
    return (
        f'<html><body style="font-family: {MONOSPACE}; font-size: {FONT_POINTS[paper_mm]}pt;">'
        f"{body}</body></html>"
    )


def _screen_dpi() -> float:
    return QGuiApplication.primaryScreen().logicalDotsPerInchX()


def build_receipt_document(
    receipt: Receipt, decimal_separator: str, paper_mm: int
) -> tuple[QTextDocument, float]:
    """The laid-out document and the height (mm) a roll page needs to hold all of it."""
    document = QTextDocument()
    document.setDocumentMargin(0)
    document.setHtml(render_receipt_html(receipt, decimal_separator, paper_mm))
    dpi = _screen_dpi()
    document.setTextWidth((paper_mm - 2 * PAGE_MARGIN_MM) / MM_PER_INCH * dpi)
    height_mm = document.size().height() / dpi * MM_PER_INCH
    return document, height_mm + 2 * PAGE_MARGIN_MM + TAIL_MM


class ReceiptPrinter:
    """Prints a receipt on the configured Windows printer or saves it as a PDF.

    Paper width, printer and decimal separator are read from the settings on every call, so a
    change made in Ajustes applies to the next ticket.
    """

    def __init__(
        self,
        settings: Callable[[], BusinessSettings],
        device_factory: Callable[[], ReceiptDevice] = QtReceiptDevice,
    ) -> None:
        self._settings = settings
        self._device_factory = device_factory

    def print_receipt(self, receipt: Receipt) -> None:
        business = self._settings()
        device = self._device_factory()
        device.use_printer(business.printer_name)
        self._send(device, receipt, business)

    def save_pdf(self, receipt: Receipt, path: Path | str) -> None:
        business = self._settings()
        device = self._device_factory()
        device.use_pdf(Path(path))
        self._send(device, receipt, business)

    @staticmethod
    def _send(device: ReceiptDevice, receipt: Receipt, business: BusinessSettings) -> None:
        document, height_mm = build_receipt_document(
            receipt, business.decimal_separator, business.receipt_paper_mm
        )
        device.set_paper(float(business.receipt_paper_mm), height_mm, PAGE_MARGIN_MM)
        device.print_document(document)
