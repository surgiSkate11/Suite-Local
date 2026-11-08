import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QImage, QTextDocument
from PySide6.QtWidgets import QApplication

from suitelocal.domain.business import BusinessSettings
from suitelocal.domain.einvoice import (
    AUTHORIZED,
    PENDING,
    Buyer,
    EInvoice,
    InvoiceData,
    InvoiceEmission,
    InvoiceIssuer,
    InvoiceLine,
    InvoicePayment,
)
from suitelocal.ui.ride import (
    Ride,
    RidePrinter,
    build_ride_document,
    render_ride_html,
)

KEY = "0503202601179001234500110010010000001231234567810"
AUTH_AT = datetime(2026, 3, 5, 21, 15, 30, tzinfo=UTC)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def make_invoice(**changes) -> InvoiceData:
    invoice = InvoiceData(
        InvoiceIssuer(
            ruc="1790012345001",
            legal_name="Tienda Sol S.A.",
            main_address="Av. Amazonas 123",
            trade_name="Tienda Sol",
            accounting_required=True,
            rimpe=False,
        ),
        InvoiceEmission("1", "001", "001", "000000123", "12345678"),
        date(2026, 3, 5),
        Buyer("05", "0912345678", "Ana Pérez", "Calle 9 y Av. 1"),
        (
            InvoiceLine("A1", "Arroz", 2, 230, 1500),
            InvoiceLine("L1", "Leche", 3, 150, 0),
        ),
        (InvoicePayment("transfer", 200), InvoicePayment("cash", 180)),
    )
    return replace(invoice, **changes)


def make_einvoice(**changes) -> EInvoice:
    einvoice = EInvoice(
        id=1,
        business_id=1,
        sale_id=7,
        establishment="001",
        emission_point="001",
        sequential="000000123",
        access_key=KEY,
        environment="pruebas",
        status=PENDING,
        signed_xml=b"<x/>",
        buyer=Buyer("05", "0912345678", "Ana Pérez", "Calle 9 y Av. 1"),
        messages=(),
        attempts=0,
        next_attempt_at=None,
        issued_at=datetime(2026, 3, 5, 20, 0, tzinfo=UTC),
        authorized_at=None,
        authorization_number=None,
    )
    return replace(einvoice, **changes)


def authorized() -> EInvoice:
    return make_einvoice(status=AUTHORIZED, authorization_number=KEY, authorized_at=AUTH_AT)


def html(invoice=None, einvoice=None, paper=80, separator=",") -> str:
    return render_ride_html(
        Ride(invoice or make_invoice(), einvoice or make_einvoice()), separator, paper, 280
    )


def test_it_shows_the_business_and_its_tax_status(qapp):
    text = html()

    for expected in (
        "Tienda Sol S.A.",
        "Nombre comercial: Tienda Sol",
        "RUC: 1790012345001",
        "Dirección: Av. Amazonas 123",
        "Obligado a llevar contabilidad: SI",
    ):
        assert expected in text, expected
    assert "RIMPE" not in text


def test_it_says_no_when_the_business_is_not_obliged_to_keep_accounts(qapp):
    issuer = replace(make_invoice().issuer, accounting_required=False)

    assert "Obligado a llevar contabilidad: NO" in html(make_invoice(issuer=issuer))


def test_it_shows_the_rimpe_legend_only_for_rimpe_issuers(qapp):
    issuer = replace(make_invoice().issuer, rimpe=True)

    assert "CONTRIBUYENTE RÉGIMEN RIMPE" in html(make_invoice(issuer=issuer))


def test_it_omits_the_trade_name_when_there_is_none(qapp):
    issuer = replace(make_invoice().issuer, trade_name="")

    assert "Nombre comercial" not in html(make_invoice(issuer=issuer))


def test_it_shows_the_document_number_environment_and_emission(qapp):
    text = html()

    for expected in ("FACTURA", "No. 001-001-000000123", "AMBIENTE: PRUEBAS", "EMISIÓN: NORMAL"):
        assert expected in text, expected
    production = html(einvoice=make_einvoice(environment="produccion"))
    assert "AMBIENTE: PRODUCCIÓN" in production
    assert "PRUEBAS" not in production


def test_it_shows_the_access_key_and_its_barcode(qapp):
    text = html()

    assert "CLAVE DE ACCESO" in text
    assert KEY in text
    assert '<img src="ride-barcode"' in text
    assert 'width="280"' in text


def test_a_pending_invoice_says_it_waits_for_the_sri(qapp):
    text = html()

    assert "Pendiente de autorización del SRI" in text
    assert "NÚMERO DE AUTORIZACIÓN" not in text
    assert "FECHA DE AUTORIZACIÓN" not in text


@pytest.mark.parametrize("status", ["recibida", "devuelta", "no_autorizada", "error_local"])
def test_only_an_authorized_invoice_shows_authorization_data(qapp, status):
    text = html(einvoice=make_einvoice(status=status))

    assert "Pendiente de autorización del SRI" in text
    assert "NÚMERO DE AUTORIZACIÓN" not in text


def test_an_authorized_invoice_shows_its_authorization(qapp):
    text = html(einvoice=authorized())

    assert "NÚMERO DE AUTORIZACIÓN" in text
    assert "FECHA DE AUTORIZACIÓN" in text
    assert f"{AUTH_AT.astimezone():%d/%m/%Y %H:%M:%S}" in text
    assert "Pendiente de autorización del SRI" not in text


def test_it_shows_the_buyer(qapp):
    text = html()

    for expected in (
        "Cliente: Ana Pérez",
        "Cédula: 0912345678",
        "Dirección: Calle 9 y Av. 1",
        "Fecha de emisión: 05/03/2026",
    ):
        assert expected in text, expected


def test_a_final_consumer_is_shown_by_its_fixed_identification(qapp):
    buyer = Buyer.final_consumer()

    text = html(make_invoice(buyer=buyer), make_einvoice(buyer=buyer))

    assert "CONSUMIDOR FINAL" in text
    assert "9999999999999" in text
    assert "Consumidor final: 9999999999999" in text


def test_it_lists_the_lines_with_their_unit_price_and_total(qapp):
    text = html()

    for expected in ("Arroz", "2 × $ 1,15", "$ 2,30", "Leche", "3 × $ 0,50", "$ 1,50"):
        assert expected in text, expected


def test_it_breaks_the_subtotals_down_by_iva_rate_with_the_total(qapp):
    text = html()

    # 15 %: 230 cents including IVA -> base 200 and IVA 30; 0 %: 150 cents.
    for expected in (
        "Subtotal 15 %",
        "$ 2,00",
        "Subtotal 0 %",
        "$ 1,50",
        "IVA 15 %",
        "$ 0,30",
        "VALOR TOTAL",
        "$ 3,80",
    ):
        assert expected in text, expected
    assert "IVA 0 %" not in text


def test_it_shows_the_payments_with_their_sri_names(qapp):
    text = html()

    assert "Otros con utilización del sistema financiero" in text
    assert "Sin utilización del sistema financiero" in text
    assert "$ 2,00" in text and "$ 1,80" in text
    card = make_invoice(payments=(InvoicePayment("card", 380),))
    assert "Tarjeta de crédito" in html(card)


def test_it_formats_money_with_the_dot_separator(qapp):
    assert "$ 3.80" in html(separator=".")


def test_it_escapes_every_user_text(qapp):
    issuer = replace(
        make_invoice().issuer,
        legal_name="<b>Mal</b> & Co",
        trade_name="<i>x</i>",
        main_address="<u>calle</u>",
    )
    buyer = Buyer("06", "<s>P1</s>", "<script>alert(1)</script>", "<a>dir</a>")
    lines = (InvoiceLine("A1", "<h1>Arroz</h1>", 1, 115, 1500),)
    invoice = make_invoice(
        issuer=issuer, buyer=buyer, lines=lines, payments=(InvoicePayment("cash", 115),)
    )

    text = html(invoice)

    for raw in ("<script>", "<h1>", "<b>Mal", "<i>x", "<u>calle", "<s>P1", "<a>dir"):
        assert raw not in text, raw
    for escaped in ("&lt;script&gt;", "&lt;h1&gt;Arroz", "&lt;b&gt;Mal&lt;/b&gt; &amp; Co"):
        assert escaped in text, escaped


@pytest.mark.parametrize("paper", [58, 80])
def test_the_document_embeds_a_barcode_that_fits_each_paper_width(qapp, paper):
    document, height_mm = build_ride_document(Ride(make_invoice(), authorized()), ",", paper)

    assert isinstance(document, QTextDocument)
    assert height_mm > 40
    text = document.toPlainText()
    assert KEY in text and "NÚMERO DE AUTORIZACIÓN" in text
    image = document.resource(QTextDocument.ResourceType.ImageResource, QUrl("ride-barcode"))
    assert isinstance(image, QImage) and not image.isNull()
    assert document.size().width() <= document.textWidth() + 1


class FakeDevice:
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


def settings_for(paper_mm=80, printer_name="") -> BusinessSettings:
    return BusinessSettings(
        1, "Tienda Sol", "$", 3, ("cash",), receipt_paper_mm=paper_mm, printer_name=printer_name
    )


def test_print_ride_uses_the_receipt_printer_and_paper_width(qapp):
    device = FakeDevice()
    printer = RidePrinter(lambda: settings_for(58, "Epson TM"), lambda: device)

    printer.print_ride(Ride(make_invoice(), make_einvoice()))

    assert device.printer_names == ["Epson TM"]
    assert len(device.documents) == 1
    assert device.papers[0][0] == 58.0 and device.papers[0][1] > 40
    assert KEY in device.documents[0].toPlainText()


def test_save_pdf_writes_a_non_empty_pdf_and_never_picks_a_printer(qapp, tmp_path):
    device_less = RidePrinter(lambda: settings_for(80))
    target = tmp_path / "ride.pdf"

    device_less.save_pdf(Ride(make_invoice(), authorized()), target)

    assert target.read_bytes().startswith(b"%PDF")
