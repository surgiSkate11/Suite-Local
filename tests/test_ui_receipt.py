import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QApplication

from suitelocal.application.receipts import (
    Receipt,
    ReceiptBusiness,
    ReceiptLine,
    ReceiptPayment,
    ReceiptTax,
)
from suitelocal.domain.business import BusinessSettings
from suitelocal.ui.receipt import (
    QtReceiptDevice,
    ReceiptPrinter,
    ReceiptPrintError,
    build_receipt_document,
    printer_status_text,
    render_receipt_html,
)

LEGEND = "Comprobante interno, no válido como documento tributario."


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def make_receipt(**changes) -> Receipt:
    receipt = Receipt(
        business=ReceiptBusiness(
            "Tienda Sol",
            "1790012345001",
            "Av. Amazonas 123",
            "022345678",
            "Régimen general",
            "Gracias por su compra",
        ),
        number="000042",
        issued_at=datetime(2026, 3, 5, 15, 30, tzinfo=timezone(timedelta(hours=-5))),
        cashier="cajero",
        lines=(
            ReceiptLine("Arroz", 2, 115, 230, 1500),
            ReceiptLine("Leche", 3, 50, 150, 0),
        ),
        subtotal_cents=350,
        taxes=(ReceiptTax(1500, 200, 30), ReceiptTax(0, 150, 0)),
        total_cents=380,
        payments=(ReceiptPayment("transfer", 200, "TR-889"), ReceiptPayment("cash", 500, "")),
        cash_received_cents=500,
        change_cents=320,
        legend=LEGEND,
    )
    return replace(receipt, **changes)


def settings_for(paper_mm=80, printer_name="", decimal_separator=",") -> BusinessSettings:
    return BusinessSettings(
        1,
        "Tienda Sol",
        "$",
        3,
        ("cash",),
        receipt_paper_mm=paper_mm,
        printer_name=printer_name,
        decimal_separator=decimal_separator,
    )


class FakeDevice:
    """Records what the printer would receive; nothing reaches a real printer."""

    def __init__(self) -> None:
        self.printer_names: list[str] = []
        self.pdf_paths: list[Path] = []
        self.papers: list[tuple[float, float, float]] = []
        self.documents: list[QTextDocument] = []

    def use_printer(self, name: str) -> None:
        self.printer_names.append(name)

    def use_pdf(self, path: Path) -> None:
        self.pdf_paths.append(path)

    def set_paper(self, width_mm: float, height_mm: float, margin_mm: float) -> None:
        self.papers.append((width_mm, height_mm, margin_mm))

    def print_document(self, document: QTextDocument) -> None:
        self.documents.append(document)


# -- HTML ----------------------------------------------------------------------------------


def test_html_shows_every_part_of_the_receipt_with_comma_money(qapp):
    text = render_receipt_html(make_receipt(), ",", 80)

    for expected in (
        "Tienda Sol",
        "RUC: 1790012345001",
        "Av. Amazonas 123",
        "Tel.: 022345678",
        "Régimen general",
        "Ticket N.º 000042",
        "05/03/2026 15:30",
        "Cajero: cajero",
        "Arroz",
        "2 × $ 1,15 (IVA 15 %)",
        "$ 2,30",
        "3 × $ 0,50 (IVA 0 %)",
        "$ 1,50",
        "Subtotal",
        "$ 3,50",
        "Base 15 %",
        "$ 2,00",
        "IVA 15 %",
        "$ 0,30",
        "Base 0 %",
        "TOTAL",
        "$ 3,80",
        "Transferencia (TR-889)",
        "$ 2,00",
        "Efectivo",
        "$ 5,00",
        "Cambio",
        "$ 3,20",
        LEGEND,
        "Gracias por su compra",
    ):
        assert expected in text, expected
    # A 0 % line has no IVA to show.
    assert 'IVA 0 %</td><td align="right">$ 0,00' not in text


def test_html_formats_money_with_the_dot_separator(qapp):
    text = render_receipt_html(make_receipt(total_cents=123456), ".", 80)

    assert "$ 1,234.56" in text


def test_html_omits_what_the_business_did_not_fill_in(qapp):
    bare = ReceiptBusiness("Kiosco", "", "", "", "Sin registro en el SRI", "")

    text = render_receipt_html(make_receipt(business=bare, cashier="", change_cents=0), ",", 80)

    for missing in ("RUC:", "Tel.:", "Cajero:", "Nota de venta", "Cambio", "Gracias"):
        assert missing not in text
    assert "Kiosco" in text and LEGEND in text


def test_html_shows_the_sales_note_number_only_when_given(qapp):
    with_note = render_receipt_html(make_receipt(sales_note_number="001-001-000123"), ",", 80)
    without = render_receipt_html(make_receipt(), ",", 80)

    assert "Nota de venta N.º 001-001-000123" in with_note
    assert "Nota de venta" not in without


def test_html_escapes_every_user_text(qapp):
    hostile = ReceiptBusiness(
        "<i>Sol</i> & Cía",
        "1790012345001",
        "<script>x</script>",
        "<b>1</b>",
        "Régimen general",
        "<u>Gracias</u>\nvuelva",
    )
    receipt = make_receipt(
        business=hostile,
        cashier="<b>caja</b>",
        sales_note_number="<b>9</b>",
        lines=(ReceiptLine("<b>x</b>", 1, 100, 100, 0),),
        payments=(ReceiptPayment("transfer", 100, "<b>ref</b>"),),
    )

    text = render_receipt_html(receipt, ",", 80)

    assert "&lt;b&gt;x&lt;/b&gt;" in text
    assert "<b>x</b>" not in text
    for raw in ("<i>Sol</i>", "<script>", "<b>1</b>", "<b>caja</b>", "<b>9</b>", "<b>ref</b>"):
        assert raw not in text
    assert "&lt;i&gt;Sol&lt;/i&gt; &amp; Cía" in text
    assert "&lt;u&gt;Gracias&lt;/u&gt;<br/>vuelva" in text
    plain = build_receipt_document(receipt, ",", 80)[0].toPlainText()
    assert "<b>x</b>" in plain


def test_html_is_sized_for_each_paper_width(qapp):
    narrow = render_receipt_html(make_receipt(), ",", 58)
    wide = render_receipt_html(make_receipt(), ",", 80)

    assert "font-size: 7.0pt" in narrow
    assert "font-size: 8.5pt" in wide
    assert "Consolas" in narrow and "monospace" in wide


@pytest.mark.parametrize("paper", [0, 57, 70, 100])
def test_html_rejects_unsupported_paper_widths(qapp, paper):
    with pytest.raises(ValueError, match="58 mm u 80 mm"):
        render_receipt_html(make_receipt(), ",", paper)


def test_the_document_fits_the_printable_width_of_each_paper(qapp):
    for paper in (58, 80):
        document, height_mm = build_receipt_document(make_receipt(), ",", paper)

        assert document.textWidth() > 0
        assert height_mm > 40
        assert "Ticket N.º 000042" in document.toPlainText()


# -- printing ------------------------------------------------------------------------------


def test_print_receipt_sends_one_document_to_the_configured_printer_and_paper(qapp):
    device = FakeDevice()
    printer = ReceiptPrinter(lambda: settings_for(58, "XP-58"), lambda: device)

    printer.print_receipt(make_receipt())

    assert device.printer_names == ["XP-58"]
    assert len(device.documents) == 1
    assert "TOTAL" in device.documents[0].toPlainText()
    ((width, height, margin),) = device.papers
    assert (width, margin) == (58.0, 3.0)
    assert height > 40
    assert device.pdf_paths == []


def test_print_receipt_uses_the_default_printer_when_none_is_chosen(qapp):
    device = FakeDevice()

    ReceiptPrinter(lambda: settings_for(80, ""), lambda: device).print_receipt(make_receipt())

    assert device.printer_names == [""]
    assert device.papers[0][0] == 80.0


def test_settings_are_read_on_every_print(qapp):
    device = FakeDevice()
    current = {"settings": settings_for(80, "A")}
    printer = ReceiptPrinter(lambda: current["settings"], lambda: device)

    printer.print_receipt(make_receipt())
    current["settings"] = settings_for(58, "B", ".")
    printer.print_receipt(make_receipt())

    assert device.printer_names == ["A", "B"]
    assert [paper[0] for paper in device.papers] == [80.0, 58.0]
    assert "$ 3.80" in device.documents[1].toPlainText()
    assert "$ 3,80" in device.documents[0].toPlainText()


def test_a_failing_device_error_reaches_the_caller(qapp):
    class Broken(FakeDevice):
        def print_document(self, document: QTextDocument) -> None:
            raise ReceiptPrintError("La impresora no está disponible.")

    printer = ReceiptPrinter(lambda: settings_for(), Broken)

    with pytest.raises(ReceiptPrintError, match="no está disponible"):
        printer.print_receipt(make_receipt())


def test_a_printer_that_is_not_installed_is_reported_before_printing(qapp):
    printer = ReceiptPrinter(lambda: settings_for(80, "Impresora-que-no-existe-xyz"))

    with pytest.raises(ReceiptPrintError, match="«Impresora-que-no-existe-xyz» no está instalada"):
        printer.print_receipt(make_receipt())


@pytest.mark.parametrize("paper", [58, 80])
def test_save_pdf_writes_a_non_empty_pdf_file(qapp, tmp_path, paper):
    target = tmp_path / f"ticket-{paper}.pdf"
    printer = ReceiptPrinter(lambda: settings_for(paper))

    printer.save_pdf(make_receipt(), target)

    assert target.exists()
    content = target.read_bytes()
    assert len(content) > 500
    assert content.startswith(b"%PDF")


def test_save_pdf_accepts_a_text_path_and_never_touches_a_printer(qapp, tmp_path):
    device = FakeDevice()
    target = tmp_path / "ticket.pdf"

    ReceiptPrinter(lambda: settings_for(), lambda: device).save_pdf(make_receipt(), str(target))

    assert device.pdf_paths == [target]
    assert device.printer_names == []


def test_the_real_device_is_only_exercised_through_pdf(qapp, tmp_path):
    device = QtReceiptDevice()
    document, height_mm = build_receipt_document(make_receipt(), ",", 80)
    target = tmp_path / "direct.pdf"

    device.use_pdf(target)
    device.set_paper(80.0, height_mm, 3.0)
    device.print_document(document)

    assert target.stat().st_size > 0


# -- status text ---------------------------------------------------------------------------


def test_printer_status_text():
    assert printer_status_text("") == "Impresora: predeterminada"
    assert printer_status_text("XP-58") == "Impresora: XP-58"


def test_building_a_real_printer_is_refused_inside_tests(qapp, monkeypatch):
    # Guards the suite: a physical printer would query the driver and could print on paper.
    class FakeInfo:
        @staticmethod
        def availablePrinterNames() -> list[str]:
            return ["XP-58"]

        @staticmethod
        def printerInfo(_name: str) -> "FakeInfo":
            return FakeInfo()

        @staticmethod
        def isNull() -> bool:
            return False

        @staticmethod
        def printerName() -> str:
            return "XP-58"

    monkeypatch.setattr("suitelocal.ui.receipt.QPrinterInfo", FakeInfo)
    monkeypatch.setattr(QtReceiptDevice, "_printers", {})

    with pytest.raises(AssertionError, match="never open a real printer"):
        QtReceiptDevice().use_printer("XP-58")


def test_the_real_device_needs_a_target_before_printing(qapp):
    document, height_mm = build_receipt_document(make_receipt(), ",", 80)

    with pytest.raises(ReceiptPrintError, match="No se eligió una impresora"):
        QtReceiptDevice().print_document(document)


def test_physical_printer_is_built_once_and_reused_across_sales(monkeypatch):
    # Building a QPrinter queries the driver and can take tens of seconds on some printers,
    # so a cashier must pay that cost at most once per printer, never on every sale.
    from suitelocal.ui import receipt as receipt_module

    built: list[str] = []

    class CountingPrinter:
        PrinterMode = receipt_module.QPrinter.PrinterMode

        def __init__(self, info, mode) -> None:
            built.append(info.printerName())

    class FakeInfo:
        def __init__(self, name: str) -> None:
            self._name = name

        def isNull(self) -> bool:
            return False

        def printerName(self) -> str:
            return self._name

    monkeypatch.setattr(receipt_module, "QPrinter", CountingPrinter)
    monkeypatch.setattr(
        receipt_module.QPrinterInfo, "availablePrinterNames", staticmethod(lambda: ["Termica"])
    )
    monkeypatch.setattr(
        receipt_module.QPrinterInfo, "printerInfo", staticmethod(lambda name: FakeInfo(name))
    )
    monkeypatch.setattr(receipt_module.QtReceiptDevice, "_printers", {})

    for _ in range(3):
        receipt_module.QtReceiptDevice().use_printer("Termica")

    assert built == ["Termica"]
