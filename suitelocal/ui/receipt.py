"""Internal sale receipt: HTML layout for 58/80 mm paper, Windows printing and PDF export."""

import html
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import (
    QCoreApplication,
    QMarginsF,
    QObject,
    QRunnable,
    QSizeF,
    QThreadPool,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QGuiApplication,
    QImage,
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
    "InlineExecutor",
    "PrintExecutor",
    "PrintJob",
    "QtPrintExecutor",
    "QtReceiptDevice",
    "ReceiptDevice",
    "ReceiptOutput",
    "ReceiptPrintError",
    "ReceiptPrinter",
    "build_html_document",
    "build_receipt_document",
    "escape_html",
    "installed_printer_names",
    "printable_width_px",
    "printer_status_text",
    "render_receipt_html",
    "default_print_executor",
    "log_print_failure",
    "make_print_job",
    "send_document",
    "submit_print",
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


class PrintExecutor(Protocol):
    """Runs a print job away from the sale screen; tests inject a synchronous one."""

    def run(self, job: Callable[[], None], on_error: Callable[[Exception], None]) -> None:
        """Run `job` once; if it raises, call `on_error` with the exception on the UI thread."""
        ...


class InlineExecutor:
    """Runs the job right away on the caller's thread (tests, scripts)."""

    def run(self, job: Callable[[], None], on_error: Callable[[Exception], None]) -> None:
        try:
            job()
        except Exception as error:  # printer drivers raise anything
            on_error(error)


class _Job(QRunnable):
    def __init__(
        self,
        executor: "QtPrintExecutor",
        job: Callable[[], None],
        on_error: Callable[[Exception], None],
    ) -> None:
        super().__init__()
        self._executor = executor
        self._job = job
        self._on_error = on_error

    def run(self) -> None:
        try:
            self._job()
        except Exception as error:  # printer drivers raise anything
            self._executor.failed.emit(self._on_error, error)


class QtPrintExecutor(QObject):
    """Runs print jobs one at a time on a dedicated worker thread.

    Create it on the UI thread: failures come back there through a queued signal, so the
    callbacks may touch widgets. The pool is deliberately limited to ONE thread: tickets keep
    their order and the QPrinter cache in `QtReceiptDevice` is only ever touched by that single
    worker, never by two threads at once.
    """

    failed = Signal(object, object)

    def __init__(self) -> None:
        super().__init__()
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self.failed.connect(self._deliver)

    def run(self, job: Callable[[], None], on_error: Callable[[Exception], None]) -> None:
        self._pool.start(_Job(self, job, on_error))

    def wait_for_done(self, timeout_ms: int) -> bool:
        """Block until the queue is empty (shutdown and tests); False if it timed out."""
        return self._pool.waitForDone(timeout_ms)

    @staticmethod
    def _deliver(on_error: Callable[[Exception], None], error: Exception) -> None:
        on_error(error)


_default_executor: QtPrintExecutor | None = None


def default_print_executor() -> QtPrintExecutor:
    """The shared worker, created on first use (always from the UI thread)."""
    global _default_executor
    if _default_executor is None:
        _default_executor = QtPrintExecutor()
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(_wait_for_default_executor)
    return _default_executor


def _wait_for_default_executor() -> None:
    """Let a ticket that is already printing finish before the app exits."""
    if _default_executor is not None:
        _default_executor.wait_for_done(5_000)


def log_print_failure(message: str) -> None:
    """Fallback when nobody listens for print failures."""
    logging.getLogger(__name__).warning(message)


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


def escape_html(text: str) -> str:
    return html.escape(text, quote=True)


def _percent(rate_basis_points: int) -> str:
    return f"{rate_basis_points // 100} %"


def render_receipt_html(receipt: Receipt, decimal_separator: str, paper_mm: int) -> str:
    """The receipt as HTML for QTextDocument; every user text is escaped."""
    validate_receipt_paper_mm(paper_mm)

    def money(cents: int) -> str:
        return escape_html(format_usd(cents, decimal_separator))

    def centered(text: str, style: str = "") -> str:
        return f'<div align="center" style="{style}">{text}</div>'

    def pair(left: str, right: str, style: str = "") -> str:
        return (
            '<table width="100%" cellspacing="0" cellpadding="0" '
            f'style="{style}"><tr><td>{left}</td><td align="right">{right}</td></tr></table>'
        )

    business = receipt.business
    parts = [centered(f"<b>{escape_html(business.name)}</b>", "font-size: 1.3em;")]
    if business.ruc:
        parts.append(centered(f"RUC: {escape_html(business.ruc)}"))
    if business.address:
        parts.append(centered(escape_html(business.address)))
    if business.phone:
        parts.append(centered(f"Tel.: {escape_html(business.phone)}"))
    parts.append(centered(escape_html(business.regime_label)))
    parts.append(RULE)
    info = [
        f"<b>Ticket N.º {escape_html(receipt.number)}</b>",
        f"Fecha: {receipt.issued_at:%d/%m/%Y %H:%M}",
    ]
    if receipt.cashier:
        info.append(f"Cajero: {escape_html(receipt.cashier)}")
    if receipt.sales_note_number:
        info.append(f"Nota de venta N.º {escape_html(receipt.sales_note_number)}")
    parts.append("<br/>".join(info))
    parts.append(RULE)
    for line in receipt.lines:
        parts.append(f"<div>{escape_html(line.name)}</div>")
        detail = f"{line.quantity} × {money(line.unit_price_cents)}"
        if receipt.charges_iva:
            detail += f" (IVA {_percent(line.tax_rate_basis_points)})"
        parts.append(pair(detail, money(line.total_cents)))
    parts.append(RULE)
    if receipt.charges_iva:
        parts.append(pair("Subtotal", money(receipt.subtotal_cents)))
        for tax in receipt.taxes:
            parts.append(pair(f"Base {_percent(tax.tax_rate_basis_points)}", money(tax.base_cents)))
            if tax.tax_rate_basis_points:
                parts.append(
                    pair(f"IVA {_percent(tax.tax_rate_basis_points)}", money(tax.tax_cents))
                )
    parts.append(pair("<b>TOTAL</b>", f"<b>{money(receipt.total_cents)}</b>", "font-size: 1.2em;"))
    parts.append(RULE)
    for payment in receipt.payments:
        label = escape_html(METHOD_LABELS.get(payment.method, payment.method))
        if payment.reference:
            label += f" ({escape_html(payment.reference)})"
        parts.append(pair(label, money(payment.amount_cents)))
    if receipt.change_cents:
        parts.append(pair("Cambio", money(receipt.change_cents)))
    if receipt.credit_balance_cents is not None:
        parts.append(f"<div><b>Saldo pendiente: {money(receipt.credit_balance_cents)}</b></div>")
    parts.append(RULE)
    parts.append(centered(escape_html(receipt.legend), "font-size: 0.9em;"))
    if business.footer:
        parts.append("<br/>")
        parts.append(centered(escape_html(business.footer).replace("\n", "<br/>")))
    body = "\n".join(parts)
    return (
        f'<html><body style="font-family: {MONOSPACE}; font-size: {FONT_POINTS[paper_mm]}pt;">'
        f"{body}</body></html>"
    )


def _screen_dpi() -> float:
    return QGuiApplication.primaryScreen().logicalDotsPerInchX()


def build_html_document(
    html_text: str,
    paper_mm: int,
    resources: Mapping[str, QImage] | None = None,
    dpi: float | None = None,
) -> tuple[QTextDocument, float]:
    """Lay out HTML for a roll of `paper_mm`; returns it with the page height (mm) it needs.

    `resources` are images the HTML refers to by name (`<img src="name">`). A caller that is not
    on the UI thread passes `dpi`, because the screen may only be asked there.
    """
    document = QTextDocument()
    document.setDocumentMargin(0)
    for name, image in (resources or {}).items():
        document.addResource(QTextDocument.ResourceType.ImageResource, QUrl(name), image)
    document.setHtml(html_text)
    dpi = dpi or _screen_dpi()
    document.setTextWidth(printable_width_px(paper_mm, dpi))
    height_mm = document.size().height() / dpi * MM_PER_INCH
    return document, height_mm + 2 * PAGE_MARGIN_MM + TAIL_MM


def printable_width_px(paper_mm: int, dpi: float | None = None) -> float:
    """Width of the text area of a roll, in the document's logical pixels."""
    return (paper_mm - 2 * PAGE_MARGIN_MM) / MM_PER_INCH * (dpi or _screen_dpi())


def build_receipt_document(
    receipt: Receipt, decimal_separator: str, paper_mm: int
) -> tuple[QTextDocument, float]:
    """The laid-out document and the height (mm) a roll page needs to hold all of it."""
    return build_html_document(render_receipt_html(receipt, decimal_separator, paper_mm), paper_mm)


def send_document(
    device: ReceiptDevice, document: QTextDocument, height_mm: float, paper_mm: int
) -> None:
    """Size the page to the document and send it to the device."""
    device.set_paper(float(paper_mm), height_mm, PAGE_MARGIN_MM)
    device.print_document(document)


@dataclass(frozen=True, slots=True)
class PrintJob:
    """Everything a worker needs to print, as plain data.

    No QObject crosses to the worker: the QTextDocument and the QPrinter are both created there.
    (QImage is an implicitly shared value type, safe to hand over.)
    """

    html_text: str
    paper_mm: int
    printer_name: str
    dpi: float
    resources: Mapping[str, QImage] = field(default_factory=dict[str, QImage])


def make_print_job(
    html_text: str,
    business: BusinessSettings,
    resources: Mapping[str, QImage] | None = None,
) -> PrintJob:
    """Capture the settings and the screen dpi; call it on the UI thread."""
    return PrintJob(
        html_text,
        business.receipt_paper_mm,
        business.printer_name,
        _screen_dpi(),
        dict(resources or {}),
    )


def submit_print(
    executor: PrintExecutor,
    device_factory: Callable[[], ReceiptDevice],
    print_job: PrintJob,
    on_error: Callable[[Exception], None],
) -> None:
    """Queue a print job and return at once.

    The worker lays the document out, builds the printer (slow on some drivers) and spools it.
    """

    def job() -> None:
        document, height_mm = build_html_document(
            print_job.html_text, print_job.paper_mm, print_job.resources, print_job.dpi
        )
        device = device_factory()
        device.use_printer(print_job.printer_name)
        send_document(device, document, height_mm, print_job.paper_mm)

    executor.run(job, on_error)


class ReceiptPrinter:
    """Prints a receipt on the configured Windows printer or saves it as a PDF.

    Paper width, printer and decimal separator are read from the settings on every call, so a
    change made in Ajustes applies to the next ticket. Printing is queued and returns at once;
    a failure reaches `on_failure` as a ready-to-show message.
    """

    def __init__(
        self,
        settings: Callable[[], BusinessSettings],
        device_factory: Callable[[], ReceiptDevice] = QtReceiptDevice,
        executor: PrintExecutor | None = None,
        on_failure: Callable[[str], None] = log_print_failure,
    ) -> None:
        self._settings = settings
        self._device_factory = device_factory
        self._executor = executor
        self._on_failure = on_failure

    def print_receipt(self, receipt: Receipt) -> None:
        business = self._settings()
        html_text = render_receipt_html(
            receipt, business.decimal_separator, business.receipt_paper_mm
        )
        submit_print(
            self._executor or default_print_executor(),
            self._device_factory,
            make_print_job(html_text, business),
            lambda error: self._on_failure(f"No se pudo imprimir el ticket: {error}"),
        )

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
        send_document(device, document, height_mm, business.receipt_paper_mm)
