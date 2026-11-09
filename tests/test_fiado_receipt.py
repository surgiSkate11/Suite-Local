import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from sale_owner import owner_session

from suitelocal.application.credit import CreditService
from suitelocal.application.customers import CustomerService
from suitelocal.application.receipts import ReceiptService
from suitelocal.domain.customers import CustomerData
from suitelocal.domain.models import Payment, Sale, SaleItem
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import ProductRepository, SaleRepository
from suitelocal.infrastructure.settings import BusinessSettingsRepository
from suitelocal.ui.receipt import render_receipt_html


@pytest.fixture
def env(tmp_path):
    database = Database(tmp_path / "fiado_receipt.db")
    database.initialize()
    owner = owner_session(database)
    BusinessSettingsRepository(database).update_profile(
        owner.user.business_id, enabled_modules={"fiado"}
    )
    product = ProductRepository(database).add("A-1", "Arroz", 250, 500, tax_rate_basis_points=0)
    customer = CustomerService(database).create(
        owner, CustomerData("cedula", "1712345678", "Ana Pérez")
    )

    def sell(payments, customer_id=customer.id, quantity=4):
        sale = Sale(
            (SaleItem(product.id, product.name, quantity, 250),),
            sum(payment.amount_cents for payment in payments),
            tuple(payments),
        )
        return SaleRepository(database).register(
            sale,
            business_id=owner.user.business_id,
            user_id=owner.user.id,
            customer_id=customer_id,
        )

    return database, owner, customer, sell


def test_the_receipt_of_a_fiado_sale_carries_the_balance_after_the_sale(env):
    database, owner, _, sell = env
    first = sell([Payment("credit", 1000)])
    second = sell([Payment("credit", 500)], quantity=2)

    receipts = ReceiptService(database)

    assert receipts.build(owner, first).credit_balance_cents == 1000
    assert receipts.build(owner, second).credit_balance_cents == 1500


def test_a_later_abono_does_not_change_a_printed_balance(env):
    database, owner, customer, sell = env
    sale_id = sell([Payment("credit", 1000)])
    CreditService(database).register_payment(owner, customer.id, 400, "cash")

    assert ReceiptService(database).build(owner, sale_id).credit_balance_cents == 1000


def test_a_sale_without_fiado_has_no_balance_even_for_a_customer_who_owes(env):
    database, owner, _, sell = env
    sell([Payment("credit", 1000)])
    cash_sale = sell([Payment("cash", 500)], quantity=2)

    assert ReceiptService(database).build(owner, cash_sale).credit_balance_cents is None


def test_the_ticket_shows_the_fiado_payment_and_the_pending_balance(env):
    database, owner, _, sell = env
    sale_id = sell([Payment("cash", 600), Payment("credit", 400)])
    receipt = ReceiptService(database).build(owner, sale_id)

    html = render_receipt_html(receipt, ",", 80)

    assert "Fiado" in html
    assert "<b>Saldo pendiente: $ 4,00</b>" in html
    # The change line comes before the balance, and the legend after it.
    assert html.index("Saldo pendiente") < html.index(receipt.legend)


def test_the_ticket_of_a_cash_sale_has_no_pending_balance(env):
    database, owner, _, sell = env
    sale_id = sell([Payment("cash", 1000)], customer_id=None)

    html = render_receipt_html(ReceiptService(database).build(owner, sale_id), ",", 80)

    assert "Saldo pendiente" not in html
