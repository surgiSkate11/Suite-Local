import pytest
from lxml import etree

from suitelocal.application.auth import AuthService
from suitelocal.application.business_profile import BusinessProfileService
from suitelocal.application.customers import CustomerService
from suitelocal.application.einvoice import build_invoice_data
from suitelocal.domain.auth import Session
from suitelocal.domain.customers import CustomerData
from suitelocal.domain.einvoice import InvoiceEmission, InvoicePayment, payment_code
from suitelocal.domain.models import Payment, Sale, SaleItem
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import (
    CategoryRepository,
    ProductRepository,
    SaleRepository,
)
from suitelocal.infrastructure.settings import BusinessSettingsRepository
from suitelocal.infrastructure.sri.invoice_xml import build_invoice_xml, validate_against_xsd

EMISSION = InvoiceEmission("1", "001", "002", "000000042", "12345678")


@pytest.fixture
def env(tmp_path):
    database = Database(tmp_path / "fiado_einvoice.db")
    database.initialize()
    owner = Session(
        AuthService(database).setup_owner("Tienda Sol", "owner", "clave-segura", "clave-segura")
    )
    BusinessProfileService(
        BusinessSettingsRepository(database), CategoryRepository(database)
    ).update_profile(
        owner,
        ruc="1790012345001",
        tax_regime="general",
        address="Av. Amazonas 123",
        enabled_modules={"fiado"},
    )
    customer = CustomerService(database).create(
        owner, CustomerData("cedula", "1712345678", "Ana Pérez")
    )
    product = ProductRepository(database).add("A-1", "Arroz", 115, 50, tax_rate_basis_points=1500)
    return database, owner, customer, product


def sell(env, payments):
    database, owner, customer, product = env
    total = 2 * 115
    sale = Sale(
        (SaleItem(product.id, product.name, 2, 115, 1500),),
        sum(payment.amount_cents for payment in payments),
        tuple(payments),
    )
    assert sale.total_cents == total
    return SaleRepository(database).register(
        sale, business_id=owner.user.business_id, user_id=owner.user.id, customer_id=customer.id
    )


def pagos(xml: bytes):
    root = etree.fromstring(xml)
    return [
        (pago.findtext("formaPago"), pago.findtext("total"))
        for pago in root.findall("infoFactura/pagos/pago")
    ]


def test_credit_maps_to_sri_code_01():
    assert payment_code("credit") == "01"


def test_fully_credit_sale_is_invoiced_as_01_without_plazo_and_validates(env):
    database, owner, customer, _ = env
    sale_id = sell(env, [Payment("credit", 230)])

    invoice = build_invoice_data(database, owner, sale_id, customer.as_buyer(), EMISSION)
    xml = build_invoice_xml(invoice)

    assert invoice.payments == (InvoicePayment("credit", 230),)
    validate_against_xsd(xml)
    assert pagos(xml) == [("01", "2.30")]
    root = etree.fromstring(xml)
    assert root.find("infoFactura/pagos/pago/plazo") is None
    assert root.find("infoFactura/pagos/pago/unidadTiempo") is None


def test_cash_plus_fiado_is_one_01_payment_that_adds_up_to_the_total(env):
    database, owner, customer, _ = env
    # Total 230: 100 on credit leaves 130 in cash, paid with 200 (change 70).
    sale_id = sell(env, [Payment("cash", 200), Payment("credit", 100)])

    invoice = build_invoice_data(database, owner, sale_id, customer.as_buyer(), EMISSION)
    xml = build_invoice_xml(invoice)

    assert invoice.payments == (InvoicePayment("cash", 130), InvoicePayment("credit", 100))
    validate_against_xsd(xml)
    assert pagos(xml) == [("01", "2.30")]


def test_transfer_plus_fiado_keeps_two_codes(env):
    database, owner, customer, _ = env
    sale_id = sell(env, [Payment("transfer", 80, "TR-1"), Payment("credit", 150)])

    invoice = build_invoice_data(database, owner, sale_id, customer.as_buyer(), EMISSION)
    xml = build_invoice_xml(invoice)

    validate_against_xsd(xml)
    assert pagos(xml) == [("20", "0.80"), ("01", "1.50")]
