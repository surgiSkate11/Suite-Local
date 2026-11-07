import hashlib
from dataclasses import replace
from datetime import UTC, date, timedelta, timezone
from pathlib import Path

import pytest
from lxml import etree

from suitelocal.application.auth import AuthService
from suitelocal.application.business_profile import BusinessProfileService
from suitelocal.application.einvoice import build_invoice_data
from suitelocal.domain.auth import Session, User
from suitelocal.domain.einvoice import (
    Buyer,
    InvoiceData,
    InvoiceEmission,
    InvoiceIssuer,
    InvoiceLine,
    InvoicePayment,
    access_key,
)
from suitelocal.domain.models import Payment, Sale, SaleItem
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import (
    CategoryRepository,
    ProductRepository,
    SaleRepository,
)
from suitelocal.infrastructure.settings import BusinessSettingsRepository
from suitelocal.infrastructure.sri.invoice_xml import build_invoice_xml, validate_against_xsd

FIXTURES = Path(__file__).parent / "fixtures" / "sri"
XSD_DIR = Path(__file__).parent.parent / "suitelocal" / "infrastructure" / "sri" / "xsd"
ECUADOR = timezone(timedelta(hours=-5))
XSD_ERROR = "El XML no cumple el esquema del SRI"
EMISSION = InvoiceEmission("1", "001", "002", "000000042", "12345678")


def make_issuer(**changes) -> InvoiceIssuer:
    values = {
        "ruc": "1790012345001",
        "legal_name": "Tienda Sol S.A.",
        "main_address": "Av. Amazonas 123",
    }
    return InvoiceIssuer(**{**values, **changes})


def mixed_invoice(**changes) -> InvoiceData:
    """2 x 1,15 at 15 % (base 2,00 / IVA 0,30) and 3 x 0,50 at 0 %: total 3,80, base 3,50."""
    invoice = InvoiceData(
        make_issuer(),
        EMISSION,
        date(2026, 3, 5),
        Buyer("05", "1712345678", "Ana Pérez"),
        (
            InvoiceLine("A-1", "Arroz", 2, 230, 1500),
            InvoiceLine("B-2", "Leche", 3, 150, 0),
        ),
        (InvoicePayment("cash", 380),),
    )
    return replace(invoice, **changes)


def parse(xml: bytes):
    return etree.fromstring(xml)


def values(root, path: str) -> list[str]:
    return [element.text for element in root.findall(path)]


# -- structure and totals ------------------------------------------------------------------


def test_mixed_sale_builds_xml_that_validates_against_the_xsd():
    xml = build_invoice_xml(mixed_invoice())

    validate_against_xsd(xml)
    assert xml.startswith(b'<?xml version="1.0" encoding="UTF-8"?>')


def test_mixed_sale_has_the_exact_totals_by_iva_code():
    root = parse(build_invoice_xml(mixed_invoice()))

    assert root.tag == "factura"
    assert root.get("id") == "comprobante"
    assert root.get("version") == "1.1.0"
    info = root.find("infoFactura")
    assert info is not None
    assert info.findtext("totalSinImpuestos") == "3.50"
    assert info.findtext("totalDescuento") == "0.00"
    assert info.findtext("propina") == "0.00"
    assert info.findtext("importeTotal") == "3.80"
    assert info.findtext("moneda") == "DOLAR"
    totals = [
        (
            tax.findtext("codigo"),
            tax.findtext("codigoPorcentaje"),
            tax.findtext("baseImponible"),
            tax.findtext("valor"),
        )
        for tax in info.findall("totalConImpuestos/totalImpuesto")
    ]
    assert totals == [("2", "4", "2.00", "0.30"), ("2", "0", "1.50", "0.00")]


def test_info_tributaria_carries_the_issuer_and_the_access_key():
    root = parse(build_invoice_xml(mixed_invoice()))

    tributaria = root.find("infoTributaria")
    assert tributaria is not None
    assert [child.tag for child in tributaria] == [
        "ambiente",
        "tipoEmision",
        "razonSocial",
        "ruc",
        "claveAcceso",
        "codDoc",
        "estab",
        "ptoEmi",
        "secuencial",
        "dirMatriz",
    ]
    assert tributaria.findtext("ambiente") == "1"
    assert tributaria.findtext("tipoEmision") == "1"
    assert tributaria.findtext("razonSocial") == "Tienda Sol S.A."
    assert tributaria.findtext("ruc") == "1790012345001"
    assert tributaria.findtext("codDoc") == "01"
    assert tributaria.findtext("estab") == "001"
    assert tributaria.findtext("ptoEmi") == "002"
    assert tributaria.findtext("secuencial") == "000000042"
    assert tributaria.findtext("dirMatriz") == "Av. Amazonas 123"
    assert tributaria.findtext("claveAcceso") == access_key(
        date(2026, 3, 5), "01", "1790012345001", "1", "001", "002", "000000042", "12345678"
    )


def test_info_factura_lists_the_buyer_date_and_issuer_flags():
    root = parse(build_invoice_xml(mixed_invoice()))

    info = root.find("infoFactura")
    assert info is not None
    assert [child.tag for child in info] == [
        "fechaEmision",
        "dirEstablecimiento",
        "obligadoContabilidad",
        "tipoIdentificacionComprador",
        "razonSocialComprador",
        "identificacionComprador",
        "totalSinImpuestos",
        "totalDescuento",
        "totalConImpuestos",
        "propina",
        "importeTotal",
        "moneda",
        "pagos",
    ]
    assert info.findtext("fechaEmision") == "05/03/2026"
    assert info.findtext("dirEstablecimiento") == "Av. Amazonas 123"
    assert info.findtext("obligadoContabilidad") == "NO"
    assert info.findtext("tipoIdentificacionComprador") == "05"
    assert info.findtext("razonSocialComprador") == "Ana Pérez"
    assert info.findtext("identificacionComprador") == "1712345678"


def test_each_line_becomes_a_detalle_with_price_without_iva():
    root = parse(build_invoice_xml(mixed_invoice()))

    details = root.findall("detalles/detalle")
    assert len(details) == 2
    first, second = details
    assert [child.tag for child in first] == [
        "codigoPrincipal",
        "descripcion",
        "cantidad",
        "precioUnitario",
        "descuento",
        "precioTotalSinImpuesto",
        "impuestos",
    ]
    assert first.findtext("codigoPrincipal") == "A-1"
    assert first.findtext("descripcion") == "Arroz"
    assert first.findtext("cantidad") == "2.000000"
    assert first.findtext("precioUnitario") == "1.000000"
    assert first.findtext("descuento") == "0.00"
    assert first.findtext("precioTotalSinImpuesto") == "2.00"
    tax = first.find("impuestos/impuesto")
    assert tax is not None
    assert [(child.tag, child.text) for child in tax] == [
        ("codigo", "2"),
        ("codigoPorcentaje", "4"),
        ("tarifa", "15.00"),
        ("baseImponible", "2.00"),
        ("valor", "0.30"),
    ]
    assert second.findtext("cantidad") == "3.000000"
    assert second.findtext("precioUnitario") == "0.500000"
    assert second.findtext("precioTotalSinImpuesto") == "1.50"
    zero_tax = second.find("impuestos/impuesto")
    assert zero_tax is not None
    assert [(child.tag, child.text) for child in zero_tax] == [
        ("codigo", "2"),
        ("codigoPorcentaje", "0"),
        ("tarifa", "0.00"),
        ("baseImponible", "1.50"),
        ("valor", "0.00"),
    ]


def test_unit_price_keeps_six_decimals_when_the_base_does_not_divide_evenly():
    invoice = mixed_invoice(
        lines=(InvoiceLine("T-3", "Tornillo", 3, 100, 0),),
        payments=(InvoicePayment("cash", 100),),
    )

    xml = build_invoice_xml(invoice)

    validate_against_xsd(xml)
    assert parse(xml).findtext("detalles/detalle/precioUnitario") == "0.333333"
    assert parse(xml).findtext("detalles/detalle/precioTotalSinImpuesto") == "1.00"


def test_five_percent_lines_use_codigo_porcentaje_5():
    invoice = mixed_invoice(
        lines=(InvoiceLine("M-1", "Cemento", 1, 105, 500),),
        payments=(InvoicePayment("cash", 105),),
    )

    root = parse(build_invoice_xml(invoice))

    total = root.find("infoFactura/totalConImpuestos/totalImpuesto")
    assert total is not None
    assert [(child.tag, child.text) for child in total] == [
        ("codigo", "2"),
        ("codigoPorcentaje", "5"),
        ("baseImponible", "1.00"),
        ("valor", "0.05"),
    ]
    assert root.findtext("detalles/detalle/impuestos/impuesto/tarifa") == "5.00"


def test_same_rate_lines_are_grouped_into_one_total_impuesto():
    invoice = mixed_invoice(
        lines=(
            InvoiceLine("A", "Uno", 1, 115, 1500),
            InvoiceLine("B", "Dos", 1, 230, 1500),
        ),
        payments=(InvoicePayment("cash", 345),),
    )

    root = parse(build_invoice_xml(invoice))

    totals = root.findall("infoFactura/totalConImpuestos/totalImpuesto")
    assert len(totals) == 1
    assert totals[0].findtext("baseImponible") == "3.00"
    assert totals[0].findtext("valor") == "0.45"


def test_pagos_block_maps_each_method_to_its_sri_code():
    invoice = mixed_invoice(
        payments=(
            InvoicePayment("cash", 80),
            InvoicePayment("transfer", 100),
            InvoicePayment("card", 200),
        )
    )

    xml = build_invoice_xml(invoice)

    validate_against_xsd(xml)
    pagos = [
        (pago.findtext("formaPago"), pago.findtext("total"))
        for pago in parse(xml).findall("infoFactura/pagos/pago")
    ]
    assert pagos == [("01", "0.80"), ("20", "1.00"), ("19", "2.00")]


def test_rimpe_emprendedor_adds_the_contribuyente_rimpe_legend_after_dir_matriz():
    xml = build_invoice_xml(mixed_invoice(issuer=make_issuer(rimpe=True)))

    validate_against_xsd(xml)
    tributaria = parse(xml).find("infoTributaria")
    assert tributaria is not None
    assert [child.tag for child in tributaria][-2:] == ["dirMatriz", "contribuyenteRimpe"]
    assert tributaria.findtext("contribuyenteRimpe") == "CONTRIBUYENTE RÉGIMEN RIMPE"


def test_general_regime_has_no_rimpe_legend():
    root = parse(build_invoice_xml(mixed_invoice(issuer=make_issuer(rimpe=False))))

    assert root.find("infoTributaria/contribuyenteRimpe") is None


def test_optional_issuer_and_buyer_fields_are_emitted_in_schema_order():
    issuer = make_issuer(
        trade_name="Sol",
        establishment_address="Calle 2 y Calle 3",
        accounting_required=True,
        special_taxpayer="5368",
    )
    buyer = Buyer("04", "1790012345001", "Empresa SA", address="Av. Colón 45")

    xml = build_invoice_xml(mixed_invoice(issuer=issuer, buyer=buyer))

    validate_against_xsd(xml)
    root = parse(xml)
    assert root.findtext("infoTributaria/nombreComercial") == "Sol"
    info = root.find("infoFactura")
    assert info is not None
    assert [child.tag for child in info][:3] == [
        "fechaEmision",
        "dirEstablecimiento",
        "contribuyenteEspecial",
    ]
    assert info.findtext("dirEstablecimiento") == "Calle 2 y Calle 3"
    assert info.findtext("contribuyenteEspecial") == "5368"
    assert info.findtext("obligadoContabilidad") == "SI"
    assert info.findtext("direccionComprador") == "Av. Colón 45"
    assert info.findtext("tipoIdentificacionComprador") == "04"


# -- buyer rules ---------------------------------------------------------------------------


def test_final_consumer_above_usd_50_is_rejected():
    invoice = mixed_invoice(
        buyer=Buyer.final_consumer(),
        lines=(InvoiceLine("A-1", "Arroz", 1, 5100, 1500),),
        payments=(InvoicePayment("cash", 5100),),
    )

    with pytest.raises(ValueError) as error:
        build_invoice_xml(invoice)

    assert str(error.value) == "Una factura a consumidor final no puede superar USD 50."


def test_final_consumer_up_to_usd_50_is_issued_with_the_reserved_data():
    invoice = mixed_invoice(
        buyer=Buyer.final_consumer(),
        lines=(InvoiceLine("A-1", "Arroz", 1, 5000, 0),),
        payments=(InvoicePayment("cash", 5000),),
    )

    xml = build_invoice_xml(invoice)

    validate_against_xsd(xml)
    root = parse(xml)
    assert root.findtext("infoFactura/tipoIdentificacionComprador") == "07"
    assert root.findtext("infoFactura/identificacionComprador") == "9999999999999"
    assert root.findtext("infoFactura/razonSocialComprador") == "CONSUMIDOR FINAL"


# -- text escaping and limits --------------------------------------------------------------


def test_user_text_is_escaped_and_round_trips():
    line = InvoiceLine("A&B", "Té <\"grande\"> & 'dulce'", 1, 100, 0)
    buyer = Buyer("05", "1712345678", "Ana <script> & Cía")

    xml = build_invoice_xml(
        mixed_invoice(lines=(line,), buyer=buyer, payments=(InvoicePayment("cash", 100),))
    )

    validate_against_xsd(xml)
    assert b"<script>" not in xml
    root = parse(xml)
    assert root.findtext("detalles/detalle/codigoPrincipal") == "A&B"
    assert root.findtext("detalles/detalle/descripcion") == "Té <\"grande\"> & 'dulce'"
    assert root.findtext("infoFactura/razonSocialComprador") == "Ana <script> & Cía"


def test_line_breaks_in_text_become_single_spaces():
    line = InvoiceLine("A-1", "Arroz\n  extra\r\nfino", 1, 100, 0)

    xml = build_invoice_xml(mixed_invoice(lines=(line,), payments=(InvoicePayment("cash", 100),)))

    validate_against_xsd(xml)
    assert parse(xml).findtext("detalles/detalle/descripcion") == "Arroz extra fino"


def test_control_characters_are_rejected_with_a_spanish_error():
    line = InvoiceLine("A-1", "Arroz\x00", 1, 100, 0)

    with pytest.raises(ValueError) as error:
        build_invoice_xml(mixed_invoice(lines=(line,), payments=(InvoicePayment("cash", 100),)))

    assert str(error.value) == "La descripción del producto contiene caracteres no válidos."


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            {"issuer": make_issuer(legal_name="N" * 301)},
            "La razón social no puede superar 300 caracteres.",
        ),
        (
            {"issuer": make_issuer(main_address="D" * 301)},
            "La dirección matriz no puede superar 300 caracteres.",
        ),
        (
            {"issuer": make_issuer(trade_name="C" * 301)},
            "El nombre comercial no puede superar 300 caracteres.",
        ),
        (
            {"buyer": Buyer("06", "P" * 20, "N" * 301)},
            "El nombre del comprador no puede superar 300 caracteres.",
        ),
        (
            {"buyer": Buyer("05", "1712345678", "Ana", address="D" * 301)},
            "La dirección del comprador no puede superar 300 caracteres.",
        ),
        (
            {"lines": (InvoiceLine("A-1", "D" * 301, 1, 100, 0),)},
            "La descripción del producto no puede superar 300 caracteres.",
        ),
        (
            {"lines": (InvoiceLine("C" * 26, "Arroz", 1, 100, 0),)},
            "El código del producto no puede superar 25 caracteres.",
        ),
    ],
)
def test_xsd_maximum_lengths_are_enforced_with_spanish_errors(change, message):
    invoice = mixed_invoice(
        lines=(InvoiceLine("A-1", "Arroz", 1, 100, 0),),
        payments=(InvoicePayment("cash", 100),),
    )

    with pytest.raises(ValueError) as error:
        build_invoice_xml(replace(invoice, **change))

    assert str(error.value) == message


def test_maximum_length_text_is_accepted():
    line = InvoiceLine("C" * 25, "D" * 300, 1, 100, 0)

    xml = build_invoice_xml(mixed_invoice(lines=(line,), payments=(InvoicePayment("cash", 100),)))

    validate_against_xsd(xml)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"issuer": make_issuer(legal_name="  ")}, "La razón social es obligatoria."),
        ({"issuer": make_issuer(main_address="")}, "La dirección matriz es obligatoria."),
        (
            {"issuer": make_issuer(ruc="1790012345002")},
            "El RUC del emisor debe tener 13 dígitos y terminar en 001.",
        ),
        (
            {"issuer": make_issuer(ruc="179001234")},
            "El RUC del emisor debe tener 13 dígitos y terminar en 001.",
        ),
        ({"lines": ()}, "La factura debe tener al menos un producto."),
        ({"payments": ()}, "La factura debe tener al menos un pago."),
        (
            {"lines": (InvoiceLine("A-1", "Arroz", 0, 100, 0),)},
            "La cantidad de cada producto debe ser mayor que cero.",
        ),
        (
            {"lines": (InvoiceLine("A-1", "Arroz", 1, 100, 1200),)},
            "La tarifa de IVA debe ser 15 %, 5 % o 0 %.",
        ),
        (
            {
                "lines": (InvoiceLine("A-1", "", 1, 100, 0),),
                "payments": (InvoicePayment("cash", 100),),
            },
            "La descripción del producto es obligatoria.",
        ),
        (
            {"payments": (InvoicePayment("cash", 379),)},
            "Los pagos deben sumar exactamente el total de la factura.",
        ),
        (
            {"payments": (InvoicePayment("cheque", 380),)},
            "La forma de pago no es válida.",
        ),
    ],
)
def test_invalid_invoices_are_rejected_with_a_spanish_error(change, message):
    with pytest.raises(ValueError) as error:
        build_invoice_xml(mixed_invoice(**change))

    assert str(error.value) == message


# -- XSD validation ------------------------------------------------------------------------


def test_xsd_rejects_a_document_with_elements_out_of_order():
    xml = build_invoice_xml(mixed_invoice())
    root = parse(xml)
    info = root.find("infoFactura")
    assert info is not None
    payments = info.find("pagos")
    assert payments is not None
    info.remove(payments)
    info.insert(0, payments)

    with pytest.raises(ValueError, match=XSD_ERROR):
        validate_against_xsd(etree.tostring(root))


def test_xsd_rejects_text_that_is_not_xml():
    with pytest.raises(ValueError, match=XSD_ERROR):
        validate_against_xsd(b"esto no es xml")


def test_xsd_accepts_the_reference_original_and_signed_invoices():
    validate_against_xsd((FIXTURES / "original.xml").read_bytes())
    validate_against_xsd((FIXTURES / "signed.xml").read_bytes())


def test_bundled_xsd_files_are_the_official_unmodified_ones():
    expected = {
        "factura_V1.1.0.xsd": "62db9bf0ecceb00ef2b7ed136e59224815e5e5e33c77efc6a0552001e052eb8b",
        "xmldsig-core-schema.xsd": (
            "35cf8197da812c85e40d57891b35c94187569ed474a2dac813ce5090dafcd35c"
        ),
    }
    manifest = (XSD_DIR / "MANIFEST.md").read_text(encoding="utf-8")

    for name, digest in expected.items():
        # Git may convert line endings, so hash the LF form like the SRI manifest does.
        content = (XSD_DIR / name).read_bytes().replace(b"\r\n", b"\n")
        assert hashlib.sha256(content).hexdigest() == digest
        assert digest in manifest


# -- building the invoice data from a stored sale ------------------------------------------


@pytest.fixture
def env(tmp_path):
    database = Database(tmp_path / "einvoice.db")
    database.initialize()
    auth = AuthService(database)
    owner = Session(auth.setup_owner("Tienda Sol", "owner", "clave-segura", "clave-segura"))
    products = ProductRepository(database)
    profile = BusinessProfileService(
        BusinessSettingsRepository(database), CategoryRepository(database)
    )
    profile.update_profile(
        owner, ruc="1790012345001", tax_regime="general", address="Av. Amazonas 123"
    )
    return database, owner, products, profile


def sell_mixed(env, payments=None, payment_cents=400) -> int:
    database, owner, products, _ = env
    taxed = products.add("A-1", "Arroz", 115, 50, tax_rate_basis_points=1500)
    exempt = products.add("B-2", "Leche", 50, 50, tax_rate_basis_points=0)
    sale = Sale(
        (
            SaleItem(taxed.id, taxed.name, 2, 115, 1500),
            SaleItem(exempt.id, exempt.name, 3, 50, 0),
        ),
        payment_cents,
        payments or (),
    )
    return SaleRepository(database).register(
        sale, business_id=owner.user.business_id, user_id=owner.user.id
    )


def test_invoice_data_is_built_from_the_stored_sale_and_the_business_settings(env):
    database, owner, _, _ = env
    sale_id = sell_mixed(env)
    buyer = Buyer("05", "1712345678", "Ana Pérez")

    invoice = build_invoice_data(database, owner, sale_id, buyer, EMISSION, timezone=ECUADOR)

    assert invoice.issuer == InvoiceIssuer(
        ruc="1790012345001",
        legal_name="Tienda Sol",
        main_address="Av. Amazonas 123",
        rimpe=False,
    )
    assert invoice.emission == EMISSION
    assert invoice.buyer == buyer
    assert invoice.lines == (
        InvoiceLine("A-1", "Arroz", 2, 230, 1500),
        InvoiceLine("B-2", "Leche", 3, 150, 0),
    )
    assert invoice.total_cents == 380
    assert invoice.payments == (InvoicePayment("cash", 380),)
    xml = build_invoice_xml(invoice)
    validate_against_xsd(xml)
    root = parse(xml)
    assert root.findtext("infoFactura/importeTotal") == "3.80"
    assert root.findtext("infoFactura/totalSinImpuestos") == "3.50"


def test_invoice_data_pays_cash_net_of_the_change_given(env):
    database, owner, _, _ = env
    sale_id = sell_mixed(env, payment_cents=1000)

    invoice = build_invoice_data(
        database, owner, sale_id, Buyer.final_consumer(), EMISSION, timezone=ECUADOR
    )

    assert invoice.payments == (InvoicePayment("cash", 380),)
    validate_against_xsd(build_invoice_xml(invoice))


def test_invoice_data_keeps_split_payments_in_order_with_cash_net_of_change(env):
    database, owner, _, _ = env
    payments = (Payment("transfer", 100, "REF-1"), Payment("cash", 300))
    sale_id = sell_mixed(env, payments=payments, payment_cents=400)

    invoice = build_invoice_data(
        database, owner, sale_id, Buyer.final_consumer(), EMISSION, timezone=ECUADOR
    )

    assert invoice.payments == (InvoicePayment("transfer", 100), InvoicePayment("cash", 280))
    xml = build_invoice_xml(invoice)
    pagos = [
        (pago.findtext("formaPago"), pago.findtext("total"))
        for pago in parse(xml).findall("infoFactura/pagos/pago")
    ]
    assert pagos == [("20", "1.00"), ("01", "2.80")]


def test_invoice_data_uses_the_local_date_of_the_sale(env):
    database, owner, _, _ = env
    sale_id = sell_mixed(env)
    with database.connect() as connection:
        connection.execute(
            "UPDATE sales SET created_at = '2026-03-05 03:30:00' WHERE id = ?", (sale_id,)
        )

    invoice = build_invoice_data(
        database, owner, sale_id, Buyer.final_consumer(), EMISSION, timezone=ECUADOR
    )

    # 03:30 UTC is still the evening of March 4th in Ecuador (UTC-5).
    assert invoice.issue_date == date(2026, 3, 4)


def test_invoice_data_marks_rimpe_emprendedor_issuers(env):
    database, owner, _, profile = env
    profile.update_profile(owner, tax_regime="rimpe_emprendedor")
    sale_id = sell_mixed(env)

    invoice = build_invoice_data(
        database, owner, sale_id, Buyer("05", "1712345678", "Ana"), EMISSION, timezone=ECUADOR
    )

    assert invoice.issuer.rimpe is True


def test_regimes_that_do_not_issue_invoices_cannot_build_one(env):
    database, owner, _, profile = env
    sale_id = sell_mixed(env)
    profile.update_profile(owner, tax_regime="rimpe_popular")

    with pytest.raises(ValueError) as error:
        build_invoice_data(database, owner, sale_id, Buyer.final_consumer(), EMISSION)

    assert (
        str(error.value) == "El régimen tributario de este negocio no emite facturas electrónicas."
    )


def test_a_sale_of_another_business_cannot_be_invoiced(env):
    database, owner, _, _ = env
    sale_id = sell_mixed(env)
    with database.connect() as connection:
        business_id = connection.execute("INSERT INTO businesses (name) VALUES ('Otra')").lastrowid
        user_id = connection.execute(
            "INSERT INTO users (business_id, username, password_hash, role) "
            "VALUES (?, 'otro', 'x', 'owner')",
            (business_id,),
        ).lastrowid
    assert business_id is not None and user_id is not None
    stranger = Session(User(user_id, business_id, "otro", "owner", True))

    with pytest.raises(ValueError) as error:
        build_invoice_data(database, stranger, sale_id, Buyer.final_consumer(), EMISSION)

    assert str(error.value) == "La venta no existe en este negocio."


def test_invoice_data_of_a_final_consumer_sale_above_the_limit_fails_when_building_the_xml(env):
    database, owner, products, _ = env
    product = products.add("C-9", "Cocina", 6000, 5, tax_rate_basis_points=1500)
    sale = Sale((SaleItem(product.id, product.name, 1, 6000, 1500),), 6000)
    sale_id = SaleRepository(database).register(
        sale, business_id=owner.user.business_id, user_id=owner.user.id
    )
    invoice = build_invoice_data(
        database, owner, sale_id, Buyer.final_consumer(), EMISSION, timezone=UTC
    )

    with pytest.raises(ValueError, match="consumidor final"):
        build_invoice_xml(invoice)
