"""The factura 1.1.0 XML of the SRI, built from InvoiceData and validated against its XSD."""

import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from xml.sax.saxutils import escape

from suitelocal.domain.einvoice import (
    INVOICE_DOC_TYPE,
    InvoiceData,
    InvoiceLine,
    access_key,
    iva_percentage_code,
    payment_code,
    validate_buyer,
)
from suitelocal.domain.tax import split_tax_included, validate_tax_rate
from suitelocal.infrastructure.sri._xml import schema_errors

XSD_PATH = Path(__file__).parent / "xsd" / "factura_V1.1.0.xsd"
SCHEMA_VERSION = "1.1.0"
RIMPE_LEGEND = "CONTRIBUYENTE RÉGIMEN RIMPE"
CURRENCY = "DOLAR"
TEXT_MAX_LENGTH = 300
CODE_MAX_LENGTH = 25

_ISSUER_RUC = re.compile(r"[0-9]{10}001")
_SPECIAL_TAXPAYER = re.compile(r"[A-Za-z0-9]{3,13}")
_SIX_PLACES = Decimal("0.000001")
_SURROGATES = range(0xD800, 0xE000)
_NON_CHARACTERS = (0xFFFE, 0xFFFF)


def _is_invalid_xml_char(char: str) -> bool:
    """XML 1.0 cannot carry control characters other than whitespace, nor lone surrogates."""
    code = ord(char)
    return (code < 0x20 and char not in "\t\n\r") or code in _SURROGATES or code in _NON_CHARACTERS


def _text(value: str, label: str, max_length: int, *, required: bool = True) -> str:
    """Normalize user text for the XSD: single-line, trimmed, at most `max_length` characters."""
    if any(_is_invalid_xml_char(char) for char in value):
        raise ValueError(f"{label} contiene caracteres no válidos.")
    # Line breaks and runs of spaces collapse into one space: the schema forbids new lines.
    value = " ".join(value.split())
    if not value:
        if required:
            ending = "obligatoria" if label.startswith("La ") else "obligatorio"
            raise ValueError(f"{label} es {ending}.")
        return ""
    if len(value) > max_length:
        raise ValueError(f"{label} no puede superar {max_length} caracteres.")
    return value


def _money(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"


def _percent(basis_points: int) -> str:
    return f"{basis_points // 100}.{basis_points % 100:02d}"


def _six_places(value: Decimal) -> str:
    return f"{value.quantize(_SIX_PLACES, rounding=ROUND_HALF_UP):f}"


def _element(tag: str, value: str) -> str:
    return f"<{tag}>{escape(value)}</{tag}>"


def _validate(invoice: InvoiceData) -> None:
    if not invoice.lines:
        raise ValueError("La factura debe tener al menos un producto.")
    if not invoice.payments:
        raise ValueError("La factura debe tener al menos un pago.")
    for line in invoice.lines:
        if line.quantity <= 0:
            raise ValueError("La cantidad de cada producto debe ser mayor que cero.")
        validate_tax_rate(line.tax_rate_basis_points)
    for payment in invoice.payments:
        payment_code(payment.method)
    if sum(payment.amount_cents for payment in invoice.payments) != invoice.total_cents:
        raise ValueError("Los pagos deben sumar exactamente el total de la factura.")
    validate_buyer(invoice.buyer, invoice.total_cents)


def _info_tributaria(invoice: InvoiceData) -> str:
    issuer = invoice.issuer
    emission = invoice.emission
    if not _ISSUER_RUC.fullmatch(issuer.ruc):
        raise ValueError("El RUC del emisor debe tener 13 dígitos y terminar en 001.")
    key = access_key(
        invoice.issue_date,
        INVOICE_DOC_TYPE,
        issuer.ruc,
        emission.environment,
        emission.establishment,
        emission.emission_point,
        emission.sequential,
        emission.numeric_code,
    )
    parts = [
        _element("ambiente", emission.environment),
        _element("tipoEmision", "1"),
        _element("razonSocial", _text(issuer.legal_name, "La razón social", TEXT_MAX_LENGTH)),
    ]
    trade_name = _text(issuer.trade_name, "El nombre comercial", TEXT_MAX_LENGTH, required=False)
    if trade_name:
        parts.append(_element("nombreComercial", trade_name))
    parts += [
        _element("ruc", issuer.ruc),
        _element("claveAcceso", key),
        _element("codDoc", INVOICE_DOC_TYPE),
        _element("estab", emission.establishment),
        _element("ptoEmi", emission.emission_point),
        _element("secuencial", emission.sequential),
        _element("dirMatriz", _text(issuer.main_address, "La dirección matriz", TEXT_MAX_LENGTH)),
    ]
    if issuer.rimpe:
        parts.append(_element("contribuyenteRimpe", RIMPE_LEGEND))
    return f"<infoTributaria>{''.join(parts)}</infoTributaria>"


def _total_taxes(invoice: InvoiceData) -> str:
    return "".join(
        "<totalImpuesto>"
        + _element("codigo", "2")
        + _element("codigoPorcentaje", iva_percentage_code(rate))
        + _element("baseImponible", _money(base))
        + _element("valor", _money(tax))
        + "</totalImpuesto>"
        for rate, base, tax in invoice.taxes
    )


def _payments(invoice: InvoiceData) -> str:
    # Cash and credit share the code "01"; the invoice states each code once, with their sum.
    totals: dict[str, int] = {}
    for payment in invoice.payments:
        code = payment_code(payment.method)
        totals[code] = totals.get(code, 0) + payment.amount_cents
    return (
        "<pagos>"
        + "".join(
            "<pago>" + _element("formaPago", code) + _element("total", _money(total)) + "</pago>"
            for code, total in totals.items()
        )
        + "</pagos>"
    )


def _info_factura(invoice: InvoiceData) -> str:
    issuer = invoice.issuer
    buyer = invoice.buyer
    issued = invoice.issue_date
    establishment_address = _text(
        issuer.establishment_address or issuer.main_address,
        "La dirección del establecimiento",
        TEXT_MAX_LENGTH,
    )
    parts = [
        _element("fechaEmision", f"{issued.day:02d}/{issued.month:02d}/{issued.year:04d}"),
        _element("dirEstablecimiento", establishment_address),
    ]
    special_taxpayer = issuer.special_taxpayer.strip()
    if special_taxpayer:
        if not _SPECIAL_TAXPAYER.fullmatch(special_taxpayer):
            raise ValueError("El contribuyente especial debe tener entre 3 y 13 letras o dígitos.")
        parts.append(_element("contribuyenteEspecial", special_taxpayer))
    parts += [
        _element("obligadoContabilidad", "SI" if issuer.accounting_required else "NO"),
        _element("tipoIdentificacionComprador", buyer.id_type),
        _element(
            "razonSocialComprador", _text(buyer.name, "El nombre del comprador", TEXT_MAX_LENGTH)
        ),
        _element("identificacionComprador", buyer.identification),
    ]
    buyer_address = _text(
        buyer.address, "La dirección del comprador", TEXT_MAX_LENGTH, required=False
    )
    if buyer_address:
        parts.append(_element("direccionComprador", buyer_address))
    parts += [
        _element("totalSinImpuestos", _money(sum(base for _, base, _ in invoice.taxes))),
        _element("totalDescuento", "0.00"),
        f"<totalConImpuestos>{_total_taxes(invoice)}</totalConImpuestos>",
        _element("propina", "0.00"),
        _element("importeTotal", _money(invoice.total_cents)),
        _element("moneda", CURRENCY),
        _payments(invoice),
    ]
    return f"<infoFactura>{''.join(parts)}</infoFactura>"


def _detail(line: InvoiceLine) -> str:
    base, tax = split_tax_included(line.total_cents, line.tax_rate_basis_points)
    unit_price = Decimal(base) / Decimal(line.quantity) / 100
    code = _text(line.code, "El código del producto", CODE_MAX_LENGTH)
    description = _text(line.description, "La descripción del producto", TEXT_MAX_LENGTH)
    return (
        "<detalle>"
        + _element("codigoPrincipal", code)
        + _element("descripcion", description)
        + _element("cantidad", _six_places(Decimal(line.quantity)))
        + _element("precioUnitario", _six_places(unit_price))
        + _element("descuento", "0.00")
        + _element("precioTotalSinImpuesto", _money(base))
        + "<impuestos><impuesto>"
        + _element("codigo", "2")
        + _element("codigoPorcentaje", iva_percentage_code(line.tax_rate_basis_points))
        + _element("tarifa", _percent(line.tax_rate_basis_points))
        + _element("baseImponible", _money(base))
        + _element("valor", _money(tax))
        + "</impuesto></impuestos></detalle>"
    )


def _info_adicional(buyer_email: str) -> str:
    email = _text(buyer_email, "El correo del comprador", TEXT_MAX_LENGTH, required=False)
    if not email:
        return ""
    field = f'<campoAdicional nombre="Email">{escape(email)}</campoAdicional>'
    return f"<infoAdicional>{field}</infoAdicional>"


def build_invoice_xml(invoice: InvoiceData, buyer_email: str = "") -> bytes:
    """The unsigned factura XML (UTF-8); raises ValueError with a Spanish message if invalid.

    A non-blank ``buyer_email`` goes to ``<infoAdicional>``, where the schema allows free fields.
    """
    _validate(invoice)
    body = (
        _info_tributaria(invoice)
        + _info_factura(invoice)
        + f"<detalles>{''.join(_detail(line) for line in invoice.lines)}</detalles>"
        + _info_adicional(buyer_email)
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<factura id="comprobante" version="{SCHEMA_VERSION}">{body}</factura>'
    )
    return xml.encode("utf-8")


def validate_against_xsd(xml_bytes: bytes) -> None:
    """Raise ValueError if the document does not satisfy the official SRI factura schema."""
    errors = schema_errors(XSD_PATH, xml_bytes)
    if errors:
        raise ValueError("El XML no cumple el esquema del SRI: " + "; ".join(errors[:3]))
