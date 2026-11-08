import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from einvoice_env import EInvoiceEnv, build_env

from suitelocal.application.receipts import Receipt
from suitelocal.domain.auth import Session, User
from suitelocal.domain.einvoice import PENDING, Buyer
from suitelocal.ui.components.invoice_checkout import InvoiceCheckout
from suitelocal.ui.ride import Ride

BUYER = Buyer("05", "0912345678", "Ana Pérez", "Calle 9")


@pytest.fixture(scope="module")
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeTicketOutput:
    def __init__(self, failure: Exception | None = None) -> None:
        self.receipts: list[Receipt] = []
        self.failure = failure

    def print_receipt(self, receipt: Receipt) -> None:
        if self.failure:
            raise self.failure
        self.receipts.append(receipt)


class FakeRideOutput:
    def __init__(self, failure: Exception | None = None) -> None:
        self.rides: list[Ride] = []
        self.failure = failure

    def print_ride(self, ride: Ride) -> None:
        if self.failure:
            raise self.failure
        self.rides.append(ride)


class Harness:
    def __init__(self, env: EInvoiceEnv, ticket_failure=None, ride_failure=None) -> None:
        self.env = env
        self.ticket = FakeTicketOutput(ticket_failure)
        self.ride = FakeRideOutput(ride_failure)
        self.notices: list[tuple[str, str]] = []
        self.checkout = InvoiceCheckout(
            env.service,
            env.owner,
            env.receipts,
            self.ticket,
            self.ride,
            lambda message, state: self.notices.append((message, state)),
        )


@pytest.fixture
def harness(tmp_path, rsa_key) -> Harness:
    return Harness(build_env(tmp_path, rsa_key))


def test_the_service_rebuilds_the_issued_invoice_from_its_sale(harness):
    sale_id = harness.env.sell(115, 1500, 2)
    issued = harness.env.service.issue_for_sale(harness.env.owner, sale_id, BUYER)

    invoice = harness.env.service.invoice_data_for(harness.env.owner, issued)

    assert invoice.total_cents == 230
    assert invoice.buyer == BUYER
    assert invoice.emission.sequential == issued.sequential
    assert invoice.issuer.trade_name == "La Esquina"
    assert [(line.description, line.quantity) for line in invoice.lines] == [("Arroz", 2)]


def test_the_service_will_not_rebuild_the_invoice_of_another_business(harness):
    sale_id = harness.env.sell()
    issued = harness.env.service.issue_for_sale(harness.env.owner, sale_id, BUYER)
    with harness.env.database.connect() as connection:
        other = connection.execute("INSERT INTO businesses (name) VALUES ('Otra')").lastrowid
        user = connection.execute(
            "INSERT INTO users (business_id, username, password_hash, role) "
            "VALUES (?, 'otro', 'x', 'owner')",
            (other,),
        ).lastrowid
    assert other is not None and user is not None
    stranger = Session(User(user, other, "otro", "owner", True))

    with pytest.raises(ValueError, match="La venta no existe en este negocio."):
        harness.env.service.invoice_data_for(stranger, issued)


def test_completing_a_sale_issues_the_invoice_and_prints_the_ride_instead_of_the_ticket(harness):
    sale_id = harness.env.sell()

    harness.checkout.complete(sale_id, BUYER, print_ticket=True)

    stored = harness.env.service.get_for_sale(harness.env.owner, sale_id)
    assert stored is not None and stored.status == PENDING and stored.buyer == BUYER
    assert len(harness.ride.rides) == 1
    assert harness.ride.rides[0].einvoice.access_key == stored.access_key
    assert harness.ticket.receipts == []
    assert harness.notices == []


def test_without_print_the_invoice_is_issued_and_nothing_is_printed(harness):
    sale_id = harness.env.sell()

    harness.checkout.complete(sale_id, Buyer.final_consumer(), print_ticket=False)

    assert harness.env.service.get_for_sale(harness.env.owner, sale_id) is not None
    assert harness.ride.rides == [] and harness.ticket.receipts == []


def test_a_failed_issue_keeps_the_sale_warns_with_the_reason_and_prints_the_ticket(
    tmp_path, rsa_key
):
    harness = Harness(build_env(tmp_path, rsa_key, enabled=False))
    sale_id = harness.env.sell()

    harness.checkout.complete(sale_id, BUYER, print_ticket=True)

    assert harness.env.service.get_for_sale(harness.env.owner, sale_id) is None
    assert harness.env.sales.today_summary()[0] == 1
    assert harness.notices == [
        (
            "La venta quedó registrada, pero no se pudo emitir la factura electrónica. "
            "La factura electrónica no está activada para este negocio.",
            "warning",
        )
    ]
    assert harness.ride.rides == []
    assert len(harness.ticket.receipts) == 1


def test_a_failed_issue_with_print_off_only_warns(tmp_path, rsa_key):
    harness = Harness(build_env(tmp_path, rsa_key, enabled=False))
    sale_id = harness.env.sell()

    harness.checkout.complete(sale_id, BUYER, print_ticket=False)

    assert len(harness.notices) == 1 and harness.notices[0][1] == "warning"
    assert harness.ticket.receipts == [] and harness.ride.rides == []


def test_an_unexpected_issue_error_is_also_a_warning_and_never_raises(harness, monkeypatch):
    sale_id = harness.env.sell()

    def boom(*_args, **_kwargs):
        raise RuntimeError("certificado ilegible")

    monkeypatch.setattr(harness.env.service, "issue_for_sale", boom)

    harness.checkout.complete(sale_id, BUYER, print_ticket=False)

    assert harness.notices == [
        (
            "La venta quedó registrada, pero no se pudo emitir la factura electrónica. "
            "certificado ilegible",
            "warning",
        )
    ]


def test_a_failing_ride_printer_only_warns_and_the_invoice_stays(tmp_path, rsa_key):
    harness = Harness(build_env(tmp_path, rsa_key), ride_failure=RuntimeError("sin papel"))
    sale_id = harness.env.sell()

    harness.checkout.complete(sale_id, BUYER, print_ticket=True)

    assert harness.env.service.get_for_sale(harness.env.owner, sale_id) is not None
    assert harness.notices == [("No se pudo imprimir el RIDE: sin papel", "warning")]


def test_print_sale_prints_the_ticket_when_the_sale_has_no_invoice(harness):
    sale_id = harness.env.sell()

    assert harness.checkout.print_sale(sale_id) is True

    assert len(harness.ticket.receipts) == 1 and harness.ride.rides == []


def test_print_sale_prints_the_ride_when_the_sale_has_an_invoice(harness):
    sale_id = harness.env.sell()
    harness.env.service.issue_for_sale(harness.env.owner, sale_id, BUYER)

    assert harness.checkout.print_sale(sale_id) is True

    assert len(harness.ride.rides) == 1 and harness.ticket.receipts == []


def test_a_failing_ticket_printer_warns_with_the_ticket_wording(tmp_path, rsa_key):
    harness = Harness(build_env(tmp_path, rsa_key), ticket_failure=RuntimeError("sin papel"))
    sale_id = harness.env.sell()

    assert harness.checkout.print_sale(sale_id) is False

    assert harness.notices == [("No se pudo imprimir el ticket: sin papel", "warning")]
