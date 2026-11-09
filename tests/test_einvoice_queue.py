import base64
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from test_certificate_store import FakeProtector, make_p12_with_ruc
from test_sri_client import FakeTransport, fixture
from test_xades import make_p12

from suitelocal.application.auth import AuthService
from suitelocal.application.business_profile import BusinessProfileService
from suitelocal.application.einvoice import (
    EInvoiceProcessor,
    EInvoiceService,
    ProcessReport,
    run_processing_pass,
)
from suitelocal.application.receipts import ReceiptService
from suitelocal.domain.auth import Session, User
from suitelocal.domain.einvoice import (
    AUTHORIZED,
    LOCAL_ERROR,
    NOT_AUTHORIZED,
    PENDING,
    RECEIVED,
    RETURNED,
    Buyer,
    SriMessage,
)
from suitelocal.domain.models import Payment, Sale, SaleItem
from suitelocal.infrastructure import database as database_module
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import (
    CategoryRepository,
    ProductRepository,
    SaleRepository,
)
from suitelocal.infrastructure.settings import BusinessSettingsRepository
from suitelocal.infrastructure.sri.certificate_store import CertificateStore, CertificateStoreError
from suitelocal.infrastructure.sri.client import (
    AuthorizationResult,
    ReceptionResult,
    SriClient,
    SriUnavailable,
)
from suitelocal.infrastructure.sri.invoice_xml import validate_against_xsd
from suitelocal.infrastructure.sri.queue import EInvoiceRepository
from suitelocal.infrastructure.sri.xades import SigningError, verify_invoice_signature

NOW = datetime(2026, 3, 5, 20, 0, tzinfo=UTC)
ECUADOR = timezone(timedelta(hours=-5))
RUC = "1790012345001"
SALE_TIME = "2026-03-05 19:30:00"  # UTC; 14:30 in Ecuador, so the invoice date is 05/03/2026
# date 05032026 + 01 + RUC + environment 1 + 001001 + 000000001 + 12345678 + 1 + check digit
FIRST_ACCESS_KEY = "0503202601179001234500110010010000000011234567819"
NOT_ENABLED = "La factura electrónica no está activada para este negocio."
NOT_FOUND = "La venta no existe en este negocio."
ALREADY_INVOICED = "Esta venta ya tiene una factura electrónica."
CORRUPT = "El comprobante guardado no pasa la verificación de la firma y no se puede enviar."


@pytest.fixture(scope="module")
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@dataclass
class Env:
    database: Database
    owner: Session
    cashier: Session
    profile: BusinessProfileService
    service: EInvoiceService
    repository: EInvoiceRepository
    products: ProductRepository
    sales_made: int = 0
    clock: datetime = NOW


@pytest.fixture
def env(tmp_path, rsa_key) -> Env:
    database = Database(tmp_path / "queue.db")
    database.initialize()
    auth = AuthService(database)
    owner = Session(auth.setup_owner("Tienda Sol", "owner", "clave-segura", "clave-segura"))
    cashier = Session(auth.create_cashier(owner, "cajero", "clave-cajero", "clave-cajero"))
    profile = BusinessProfileService(
        BusinessSettingsRepository(database),
        CategoryRepository(database),
        lambda business_id: CertificateStore.for_business(
            tmp_path / "data", business_id, FakeProtector()
        ),
    )
    profile.update_profile(
        owner, tax_regime="rimpe_emprendedor", ruc=RUC, address="Av. Amazonas 123"
    )
    p12 = make_p12(
        rsa_key, b"clave", not_before=NOW - timedelta(days=1), not_after=NOW + timedelta(days=365)
    )
    profile.save_certificate(owner, p12, "clave", now=NOW)
    profile.update_einvoice(owner, enabled=True, trade_name="La Esquina")
    state = Env(
        database,
        owner,
        cashier,
        profile,
        None,  # type: ignore[arg-type]
        EInvoiceRepository(database),
        ProductRepository(database),
    )
    state.service = EInvoiceService(
        database,
        profile.certificates,
        timezone=ECUADOR,
        clock=lambda: state.clock,
        numeric_code=lambda: "12345678",
    )
    return state


def sell(env: Env, session: Session | None = None, created_at: str = SALE_TIME) -> int:
    """2 x 1,15 at 15 % and 3 x 0,50 at 0 %: total 3,80, paid with 4,00 in cash."""
    session = session or env.owner
    env.sales_made += 1
    taxed = env.products.add(f"A-{env.sales_made}", "Arroz", 115, 50, tax_rate_basis_points=1500)
    exempt = env.products.add(f"B-{env.sales_made}", "Leche", 50, 50, tax_rate_basis_points=0)
    sale = Sale(
        (SaleItem(taxed.id, taxed.name, 2, 115, 1500), SaleItem(exempt.id, exempt.name, 3, 50, 0)),
        400,
        (Payment("cash", 400),),
    )
    sale_id = SaleRepository(env.database).register(
        sale, business_id=session.user.business_id, user_id=session.user.id
    )
    with env.database.connect() as connection:
        connection.execute("UPDATE sales SET created_at = ? WHERE id = ?", (created_at, sale_id))
    return sale_id


def issue(env: Env, sale_id: int, buyer: Buyer | None = None, session: Session | None = None):
    return env.service.issue_for_sale(
        session or env.owner, sale_id, buyer or Buyer.final_consumer()
    )


def allocate(
    database: Database,
    business_id: int = 1,
    environment: str = "pruebas",
    establishment: str = "001",
    emission_point: str = "001",
) -> int:
    with database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        return EInvoiceRepository.allocate_sequential(
            connection, business_id, environment, establishment, emission_point
        )


def table_snapshot(database: Database, *tables: str) -> list[list[tuple]]:
    with database.connect() as connection:
        return [
            [tuple(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY 1")]
            for table in tables
        ]


# -- sequential allocation ------------------------------------------------------------------


def test_sequentials_start_at_one_and_count_up(env):
    assert [allocate(env.database) for _ in range(3)] == [1, 2, 3]


def test_each_business_environment_establishment_and_point_has_its_own_counter(env):
    with env.database.connect() as connection:
        connection.execute("INSERT INTO businesses (id, name) VALUES (2, 'Otra')")
    assert allocate(env.database) == 1
    assert allocate(env.database, environment="produccion") == 1
    assert allocate(env.database, establishment="002") == 1
    assert allocate(env.database, emission_point="002") == 1
    assert allocate(env.database, business_id=2) == 1
    assert allocate(env.database) == 2


def test_concurrent_allocations_never_get_the_same_number(env):
    numbers: list[int] = []
    failures: list[BaseException] = []

    def worker() -> None:
        try:
            for _ in range(5):
                with env.database.connect() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    number = EInvoiceRepository.allocate_sequential(
                        connection, 1, "pruebas", "001", "001"
                    )
                    time.sleep(0.001)  # hold the write lock so the others really wait
                    numbers.append(number)
        except BaseException as error:
            failures.append(error)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert not any(thread.is_alive() for thread in threads)
    assert failures == []
    assert sorted(numbers) == list(range(1, 41))


def test_concurrent_issuing_gives_every_invoice_its_own_number(env):
    sale_ids = [sell(env) for _ in range(6)]
    issued: list[str] = []
    failures: list[BaseException] = []

    def worker(ids: list[int]) -> None:
        try:
            for sale_id in ids:
                issued.append(issue(env, sale_id).sequential)
        except BaseException as error:
            failures.append(error)

    threads = [threading.Thread(target=worker, args=(sale_ids[i::3],)) for i in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)

    assert not any(thread.is_alive() for thread in threads)
    assert failures == []
    assert sorted(issued) == [f"{number:09d}" for number in range(1, 7)]


def test_a_sequential_cannot_be_reserved_outside_a_write_transaction(env):
    with env.database.connect() as connection, pytest.raises(RuntimeError, match="BEGIN IMMEDIATE"):
        EInvoiceRepository.allocate_sequential(connection, 1, "pruebas", "001", "001")

    assert allocate(env.database) == 1


def test_a_rolled_back_allocation_does_not_burn_a_number(env):
    with pytest.raises(RuntimeError), env.database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        assert EInvoiceRepository.allocate_sequential(connection, 1, "pruebas", "001", "001") == 1
        raise RuntimeError("falló después de reservar el número")

    assert allocate(env.database) == 1


def test_the_database_refuses_two_invoices_with_the_same_number(env):
    first = issue(env, sell(env))
    other_sale = sell(env)

    with pytest.raises(sqlite3.IntegrityError), env.database.connect() as connection:
        connection.execute(
            """
            INSERT INTO einvoices
                (business_id, sale_id, establishment, emission_point, sequential, access_key,
                 environment, signed_xml, buyer_id_type, buyer_identification, buyer_name,
                 issued_at)
            VALUES (1, ?, '001', '001', ?, 'otra-clave', 'pruebas', x'00', '07', '9999999999999',
                    'CONSUMIDOR FINAL', '2026-03-05T19:30:00+00:00')
            """,
            (other_sale, first.sequential),
        )


def test_an_exhausted_series_is_reported_in_spanish(env):
    with env.database.connect() as connection:
        connection.execute(
            "INSERT INTO einvoice_sequences VALUES (1, 'pruebas', '001', '001', 999999999)"
        )

    with pytest.raises(ValueError, match="Se agotó la numeración"):
        allocate(env.database)


def test_the_database_refuses_an_unknown_status(env):
    issue(env, sell(env))

    with pytest.raises(sqlite3.IntegrityError), env.database.connect() as connection:
        connection.execute("UPDATE einvoices SET status = 'quien sabe'")


# -- issuing ---------------------------------------------------------------------------------


def test_issuing_stores_a_signed_validated_pending_invoice(env):
    sale_id = sell(env)

    invoice = issue(env, sale_id)

    assert invoice.status == PENDING
    assert (invoice.business_id, invoice.sale_id) == (1, sale_id)
    assert invoice.sequential == "000000001"
    assert (invoice.establishment, invoice.emission_point) == ("001", "001")
    assert invoice.number == "001-001-000000001"
    assert invoice.environment == "pruebas"
    assert invoice.access_key == FIRST_ACCESS_KEY
    assert invoice.buyer == Buyer.final_consumer()
    assert invoice.messages == ()
    assert invoice.attempts == 0
    assert invoice.next_attempt_at is None
    assert invoice.issued_at == datetime(2026, 3, 5, 19, 30, tzinfo=UTC)
    assert invoice.authorized_at is None and invoice.authorization_number is None
    assert verify_invoice_signature(invoice.signed_xml) is True
    validate_against_xsd(invoice.signed_xml)
    assert f"<claveAcceso>{FIRST_ACCESS_KEY}</claveAcceso>".encode() in invoice.signed_xml
    assert b"<secuencial>000000001</secuencial>" in invoice.signed_xml
    assert b"<importeTotal>3.80</importeTotal>" in invoice.signed_xml
    assert b"<nombreComercial>La Esquina</nombreComercial>" in invoice.signed_xml
    assert b"<fechaEmision>05/03/2026</fechaEmision>" in invoice.signed_xml
    assert env.service.get_for_sale(env.owner, sale_id) == invoice


def test_the_buyer_given_at_checkout_is_stored_and_invoiced(env):
    buyer = Buyer("05", "1712345678", "Ana Pérez", "Calle 1")

    invoice = issue(env, sell(env), buyer)

    assert invoice.buyer == buyer
    assert b"<razonSocialComprador>Ana P\xc3\xa9rez</razonSocialComprador>" in invoice.signed_xml
    assert b"<identificacionComprador>1712345678</identificacionComprador>" in invoice.signed_xml


def test_sequentials_follow_one_another_across_sales(env):
    first = issue(env, sell(env))
    second = issue(env, sell(env))

    assert (first.sequential, second.sequential) == ("000000001", "000000002")
    assert first.access_key != second.access_key
    assert second.access_key[30:39] == "000000002"


def test_production_numbers_independently_and_uses_environment_2(env):
    env.profile.update_einvoice(env.owner, sri_environment="produccion")

    invoice = issue(env, sell(env))

    assert invoice.environment == "produccion"
    assert invoice.sequential == "000000001"
    assert invoice.access_key[23] == "2"
    assert b"<ambiente>2</ambiente>" in invoice.signed_xml


def test_the_series_comes_from_the_business_settings(env):
    env.profile.update_einvoice(env.owner, establishment="003", emission_point="007")

    invoice = issue(env, sell(env))

    assert invoice.number == "003-007-000000001"
    assert invoice.access_key[24:30] == "003007"


def test_the_issuer_flags_come_from_the_business_settings(env):
    default = issue(env, sell(env))
    env.profile.update_einvoice(env.owner, obligado_contabilidad=True, trade_name="")

    flagged = issue(env, sell(env))

    assert b"<obligadoContabilidad>NO</obligadoContabilidad>" in default.signed_xml
    assert b"<nombreComercial>La Esquina</nombreComercial>" in default.signed_xml
    assert b"<obligadoContabilidad>SI</obligadoContabilidad>" in flagged.signed_xml
    assert b"<nombreComercial>" not in flagged.signed_xml


def test_a_cashier_can_issue_the_invoice_of_a_sale_of_the_business(env):
    invoice = issue(env, sell(env, env.cashier), session=env.cashier)

    assert invoice.status == PENDING


def test_a_second_invoice_for_the_same_sale_is_rejected_and_burns_no_number(env):
    sale_id = sell(env)
    first = issue(env, sale_id)

    with pytest.raises(ValueError) as error:
        issue(env, sale_id)

    assert str(error.value) == ALREADY_INVOICED
    assert env.service.get_for_sale(env.owner, sale_id) == first
    assert issue(env, sell(env)).sequential == "000000002"


def test_issuing_requires_electronic_invoicing_to_be_enabled(env):
    sale_id = sell(env)
    env.profile.update_einvoice(env.owner, enabled=False)

    with pytest.raises(ValueError) as error:
        issue(env, sale_id)

    assert str(error.value) == NOT_ENABLED
    assert env.service.get_for_sale(env.owner, sale_id) is None
    assert allocate(env.database) == 1


def test_issuing_a_sale_of_another_business_is_rejected(env):
    sale_id = sell(env)
    with env.database.connect() as connection:
        other = connection.execute("INSERT INTO businesses (name) VALUES ('Otra')").lastrowid
        user = connection.execute(
            "INSERT INTO users (business_id, username, password_hash, role) "
            "VALUES (?, 'otro', 'x', 'owner')",
            (other,),
        ).lastrowid
    assert other is not None and user is not None
    stranger = Session(User(user, other, "otro", "owner", True))
    p12 = make_p12(
        rsa.generate_private_key(public_exponent=65537, key_size=2048),
        b"clave",
        not_before=NOW - timedelta(days=1),
        not_after=NOW + timedelta(days=30),
    )
    env.profile.update_profile(
        stranger, tax_regime="general", ruc="0990000001001", address="Otra calle"
    )
    env.profile.save_certificate(stranger, p12, "clave", now=NOW)
    env.profile.update_einvoice(stranger, enabled=True)

    with pytest.raises(ValueError) as error:
        issue(env, sale_id, session=stranger)

    assert str(error.value) == NOT_FOUND
    assert env.service.get_for_sale(env.owner, sale_id) is None
    assert env.service.get_for_sale(stranger, sale_id) is None
    assert allocate(env.database, business_id=other) == 1


def test_issuing_a_sale_that_does_not_exist_is_rejected(env):
    with pytest.raises(ValueError) as error:
        issue(env, 999)

    assert str(error.value) == NOT_FOUND
    assert allocate(env.database) == 1


def test_a_failed_build_does_not_burn_a_sequential_number(env):
    sale_id = sell(env)
    bad_buyer = Buyer("05", "123", "Ana")

    with pytest.raises(ValueError, match="cédula"):
        issue(env, sale_id, bad_buyer)

    assert env.service.get_for_sale(env.owner, sale_id) is None
    assert issue(env, sale_id).sequential == "000000001"


def test_a_failed_signature_does_not_burn_a_sequential_number(env):
    sale_id = sell(env)
    env.clock = NOW + timedelta(days=366)  # the certificate has expired by then

    with pytest.raises(SigningError, match="vencido"):
        issue(env, sale_id)

    env.clock = NOW
    assert env.service.get_for_sale(env.owner, sale_id) is None
    assert issue(env, sale_id).sequential == "000000001"


def test_a_failure_while_storing_does_not_burn_a_sequential_number(env):
    sale_id = sell(env)
    with env.database.connect() as connection:
        connection.execute(
            "CREATE TRIGGER no_insert BEFORE INSERT ON einvoices "
            "BEGIN SELECT RAISE(ABORT, 'boom'); END"
        )

    with pytest.raises(sqlite3.IntegrityError):
        issue(env, sale_id)
    with env.database.connect() as connection:
        connection.execute("DROP TRIGGER no_insert")

    assert issue(env, sale_id).sequential == "000000001"


def test_a_missing_certificate_is_reported_and_burns_no_number(env):
    sale_id = sell(env)
    env.profile.certificates(1).clear()

    with pytest.raises(CertificateStoreError) as error:
        issue(env, sale_id)

    assert str(error.value) == "No hay un certificado de firma guardado."
    assert allocate(env.database) == 1


def test_a_regime_that_does_not_invoice_is_rejected_without_burning_a_number(env):
    sale_id = sell(env)
    with env.database.connect() as connection:
        connection.execute("UPDATE business_settings SET tax_regime = 'rimpe_popular'")

    with pytest.raises(ValueError, match="no emite facturas electrónicas"):
        issue(env, sale_id)

    assert allocate(env.database) == 1


def test_issuing_never_touches_the_sale_and_a_failure_leaves_it_intact(env):
    sale_id = sell(env)
    tables = ("sales", "sale_items", "sale_payments", "products")
    before = table_snapshot(env.database, *tables)

    with pytest.raises(ValueError):
        issue(env, sale_id, Buyer("05", "123", "Ana"))
    assert table_snapshot(env.database, *tables) == before

    issue(env, sale_id)
    assert table_snapshot(env.database, *tables) == before
    assert ReceiptService(env.database, ECUADOR).build(env.owner, sale_id).total_cents == 380


def test_the_invoices_of_a_business_are_listed_newest_first_and_scoped(env):
    first = issue(env, sell(env))
    second = issue(env, sell(env))

    assert env.service.list_for_business(env.owner) == [second, first]
    assert env.service.list_for_business(env.owner, limit=1) == [second]


# -- processing: scripted SRI ------------------------------------------------------------------


class FakeGateway:
    """Answers send() and authorize() with scripted results, or raises scripted errors."""

    def __init__(self, receptions=(), authorizations=()) -> None:
        self.receptions = list(receptions)
        self.authorizations = list(authorizations)
        self.sent: list[bytes] = []
        self.authorized: list[str] = []

    def send(self, signed_xml: bytes) -> ReceptionResult:
        self.sent.append(signed_xml)
        outcome = self.receptions.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def authorize(self, access_key: str) -> AuthorizationResult:
        self.authorized.append(access_key)
        outcome = self.authorizations.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


RECEIVED_OK = ReceptionResult("RECIBIDA", ())
AUTHORIZED_OK = AuthorizationResult(
    "AUTORIZADO",
    FIRST_ACCESS_KEY,
    datetime(2026, 3, 5, 14, 35, 10, tzinfo=ECUADOR),
    (SriMessage("60", "ADVERTENCIA", "", "ADVERTENCIA"),),
)
IN_PROCESS = AuthorizationResult("EN PROCESO", None, None, ())
UNAVAILABLE = SriUnavailable("sin red")


def processor_for(env: Env, gateway: FakeGateway) -> tuple[EInvoiceProcessor, list[str]]:
    environments: list[str] = []

    def client_for(environment: str) -> FakeGateway:
        environments.append(environment)
        return gateway

    return EInvoiceProcessor(env.database, client_for), environments


def test_a_pending_invoice_is_sent_and_becomes_received(env):
    invoice = issue(env, sell(env))
    gateway = FakeGateway([RECEIVED_OK])
    processor, environments = processor_for(env, gateway)

    report = processor.process_pending(NOW)

    stored = env.repository.get(invoice.id)
    assert stored is not None
    assert (stored.status, stored.attempts, stored.next_attempt_at) == (RECEIVED, 0, NOW)
    assert gateway.sent == [invoice.signed_xml]
    assert environments == ["pruebas"]
    assert report == ProcessReport(sent=(invoice.id,), near_deadline=())


def test_a_received_invoice_is_authorized_on_the_next_pass(env):
    invoice = issue(env, sell(env))
    gateway = FakeGateway([RECEIVED_OK], [AUTHORIZED_OK])
    processor, _ = processor_for(env, gateway)
    processor.process_pending(NOW)

    report = processor.process_pending(NOW + timedelta(seconds=30))

    stored = env.repository.get(invoice.id)
    assert stored is not None
    assert stored.status == AUTHORIZED
    assert stored.authorization_number == FIRST_ACCESS_KEY
    assert stored.authorized_at == datetime(2026, 3, 5, 19, 35, 10, tzinfo=UTC)
    assert stored.messages == (SriMessage("60", "ADVERTENCIA", "", "ADVERTENCIA"),)
    assert stored.next_attempt_at is None
    assert gateway.authorized == [FIRST_ACCESS_KEY]
    assert report.authorized == (invoice.id,)
    assert report.sent == ()


def test_an_authorized_invoice_is_never_processed_again(env):
    invoice = issue(env, sell(env))
    gateway = FakeGateway([RECEIVED_OK], [AUTHORIZED_OK])
    processor, _ = processor_for(env, gateway)
    processor.process_pending(NOW)
    processor.process_pending(NOW)

    report = processor.process_pending(NOW + timedelta(days=1))

    assert report == ProcessReport()
    assert (len(gateway.sent), len(gateway.authorized)) == (1, 1)
    assert env.repository.get(invoice.id).status == AUTHORIZED  # type: ignore[union-attr]


def test_a_not_authorized_verdict_is_final_and_keeps_the_sri_messages(env):
    invoice = issue(env, sell(env))
    refusal = (SriMessage("39", "FIRMA INVALIDA", "La firma es inválida", "ERROR"),)
    gateway = FakeGateway(
        [RECEIVED_OK], [AuthorizationResult("NO AUTORIZADO", None, None, refusal)]
    )
    processor, _ = processor_for(env, gateway)
    processor.process_pending(NOW)

    report = processor.process_pending(NOW)
    processor.process_pending(NOW + timedelta(hours=5))

    stored = env.repository.get(invoice.id)
    assert stored is not None
    assert (stored.status, stored.messages) == (NOT_AUTHORIZED, refusal)
    assert stored.authorization_number is None
    assert report.rejected == (invoice.id,)
    assert len(gateway.authorized) == 1


def test_a_returned_invoice_keeps_the_sri_messages_and_is_not_retried(env):
    invoice = issue(env, sell(env))
    problems = (
        SriMessage("35", "ARCHIVO NO CUMPLE ESTRUCTURA XML", "detalle", "ERROR"),
        SriMessage("65", "FECHA EMISION EXTEMPORANEA", "", "ERROR"),
    )
    gateway = FakeGateway([ReceptionResult("DEVUELTA", problems)])
    processor, _ = processor_for(env, gateway)

    report = processor.process_pending(NOW)
    processor.process_pending(NOW + timedelta(hours=5))

    stored = env.repository.get(invoice.id)
    assert stored is not None
    assert (stored.status, stored.messages) == (RETURNED, problems)
    assert gateway.authorized == []
    assert len(gateway.sent) == 1
    assert report.rejected == (invoice.id,)


@pytest.mark.parametrize("identifier", ["43", "70"])
def test_a_returned_invoice_already_registered_is_polled_instead_of_failed(env, identifier):
    invoice = issue(env, sell(env))
    registered = ReceptionResult(
        "DEVUELTA", (SriMessage(identifier, "CLAVE ACCESO REGISTRADA", "", "ERROR"),)
    )
    gateway = FakeGateway([registered], [AUTHORIZED_OK])
    processor, _ = processor_for(env, gateway)

    report = processor.process_pending(NOW)

    stored = env.repository.get(invoice.id)
    assert stored is not None
    assert stored.status == AUTHORIZED
    assert stored.authorization_number == FIRST_ACCESS_KEY
    assert gateway.authorized == [FIRST_ACCESS_KEY]
    assert report.authorized == (invoice.id,)
    assert report.rejected == ()


def test_an_already_registered_invoice_still_in_process_waits_as_received(env):
    invoice = issue(env, sell(env))
    registered = ReceptionResult("DEVUELTA", (SriMessage("43", "CLAVE ACCESO REGISTRADA"),))
    gateway = FakeGateway([registered], [IN_PROCESS])
    processor, _ = processor_for(env, gateway)

    processor.process_pending(NOW)

    stored = env.repository.get(invoice.id)
    assert stored is not None
    assert (stored.status, stored.messages) == (RECEIVED, ())
    assert stored.next_attempt_at == NOW + timedelta(minutes=1)


def test_an_invoice_still_in_process_is_asked_again_a_minute_later(env):
    invoice = issue(env, sell(env))
    gateway = FakeGateway([RECEIVED_OK], [IN_PROCESS, AUTHORIZED_OK])
    processor, _ = processor_for(env, gateway)
    processor.process_pending(NOW)
    processor.process_pending(NOW)

    processor.process_pending(NOW + timedelta(seconds=59))
    assert len(gateway.authorized) == 1
    stored = env.repository.get(invoice.id)
    assert stored is not None
    assert (stored.status, stored.next_attempt_at) == (RECEIVED, NOW + timedelta(minutes=1))

    processor.process_pending(NOW + timedelta(minutes=1))
    assert env.repository.get(invoice.id).status == AUTHORIZED  # type: ignore[union-attr]


def test_sending_backs_off_1_5_15_30_60_minutes_and_then_hourly(env):
    invoice = issue(env, sell(env))
    gateway = FakeGateway([UNAVAILABLE] * 7)
    processor, _ = processor_for(env, gateway)
    moment = NOW

    for attempt, minutes in enumerate((1, 5, 15, 30, 60, 60, 60), start=1):
        report = processor.process_pending(moment)
        stored = env.repository.get(invoice.id)
        assert stored is not None
        assert (stored.status, stored.attempts) == (PENDING, attempt)
        assert stored.next_attempt_at == moment + timedelta(minutes=minutes)
        assert report.deferred == (invoice.id,)
        assert len(gateway.sent) == attempt
        # Not due yet: nothing is sent a second before the scheduled time.
        processor.process_pending(stored.next_attempt_at - timedelta(seconds=1))
        assert len(gateway.sent) == attempt
        moment = stored.next_attempt_at


def test_asking_for_the_authorization_backs_off_the_same_way(env):
    invoice = issue(env, sell(env))
    gateway = FakeGateway([RECEIVED_OK], [UNAVAILABLE, UNAVAILABLE, AUTHORIZED_OK])
    processor, _ = processor_for(env, gateway)
    processor.process_pending(NOW)

    processor.process_pending(NOW)
    first = env.repository.get(invoice.id)
    assert first is not None
    assert (first.status, first.attempts, first.next_attempt_at) == (
        RECEIVED,
        1,
        NOW + timedelta(minutes=1),
    )
    processor.process_pending(NOW + timedelta(minutes=1))
    second = env.repository.get(invoice.id)
    assert second is not None
    assert (second.attempts, second.next_attempt_at) == (2, NOW + timedelta(minutes=6))

    processor.process_pending(NOW + timedelta(minutes=6))
    assert env.repository.get(invoice.id).status == AUTHORIZED  # type: ignore[union-attr]


def test_once_the_sri_is_unavailable_the_rest_of_the_pass_does_not_wait_for_it_again(env):
    invoices = [issue(env, sell(env)) for _ in range(3)]
    gateway = FakeGateway([UNAVAILABLE])
    processor, _ = processor_for(env, gateway)

    report = processor.process_pending(NOW)

    assert len(gateway.sent) == 1
    assert report.deferred == (invoices[0].id,)
    attempts = [env.repository.get(invoice.id).attempts for invoice in invoices]  # type: ignore[union-attr]
    assert attempts == [1, 0, 0]


def test_a_successful_send_resets_the_failure_count_for_the_next_step(env):
    invoice = issue(env, sell(env))
    gateway = FakeGateway([UNAVAILABLE, RECEIVED_OK], [UNAVAILABLE])
    processor, _ = processor_for(env, gateway)
    processor.process_pending(NOW)
    processor.process_pending(NOW + timedelta(minutes=1))

    stored = env.repository.get(invoice.id)
    assert stored is not None
    assert (stored.status, stored.attempts) == (RECEIVED, 0)

    processor.process_pending(NOW + timedelta(minutes=1))
    again = env.repository.get(invoice.id)
    assert again is not None
    assert again.attempts == 1
    assert again.next_attempt_at == NOW + timedelta(minutes=2)


def test_invoices_are_sent_in_the_order_they_were_issued(env):
    first = issue(env, sell(env))
    second = issue(env, sell(env))
    gateway = FakeGateway([RECEIVED_OK, RECEIVED_OK])
    processor, _ = processor_for(env, gateway)

    report = processor.process_pending(NOW)

    assert gateway.sent == [first.signed_xml, second.signed_xml]
    assert report.sent == (first.id, second.id)


def test_each_invoice_is_sent_to_the_environment_it_was_issued_for(env):
    issue(env, sell(env))
    env.profile.update_einvoice(env.owner, sri_environment="produccion")
    issue(env, sell(env))
    gateway = FakeGateway([RECEIVED_OK, RECEIVED_OK])
    processor, environments = processor_for(env, gateway)

    processor.process_pending(NOW)

    assert environments == ["pruebas", "produccion"]


def test_a_stored_invoice_that_no_longer_verifies_is_a_local_error_and_is_not_sent(env):
    invoice = issue(env, sell(env))
    damaged = invoice.signed_xml.replace(b"<importeTotal>3.80", b"<importeTotal>9.80")
    with env.database.connect() as connection:
        connection.execute("UPDATE einvoices SET signed_xml = ?", (damaged,))
    gateway = FakeGateway()
    processor, _ = processor_for(env, gateway)

    report = processor.process_pending(NOW)

    stored = env.repository.get(invoice.id)
    assert stored is not None
    assert stored.status == LOCAL_ERROR
    assert stored.messages == (SriMessage("LOCAL", CORRUPT, "", "ERROR"),)
    assert gateway.sent == []
    assert report.rejected == (invoice.id,)


def test_processing_only_touches_the_requested_business(env):
    invoice = issue(env, sell(env))
    gateway = FakeGateway([RECEIVED_OK])
    processor, _ = processor_for(env, gateway)

    assert processor.process_pending(NOW, business_id=2) == ProcessReport()
    assert gateway.sent == []
    assert processor.process_pending(NOW, business_id=1).sent == (invoice.id,)


def test_invoices_close_to_the_72_hour_limit_are_reported_until_the_sri_receives_them(env):
    fresh = issue(env, sell(env))
    near = issue(env, sell(env))
    late = issue(env, sell(env))
    waiting = issue(env, sell(env))
    issued = {
        fresh.id: NOW - timedelta(hours=59),
        near.id: NOW - timedelta(hours=61),
        late.id: NOW - timedelta(hours=80),
        waiting.id: NOW - timedelta(hours=70),
    }
    with env.database.connect() as connection:
        for invoice_id, moment in issued.items():
            connection.execute(
                "UPDATE einvoices SET issued_at = ? WHERE id = ?",
                (moment.isoformat(timespec="seconds"), invoice_id),
            )
        connection.execute("UPDATE einvoices SET status = 'recibida' WHERE id = ?", (waiting.id,))
    gateway = FakeGateway([UNAVAILABLE], [IN_PROCESS])
    processor, _ = processor_for(env, gateway)

    report = processor.process_pending(NOW)

    assert report.near_deadline == (near.id, late.id)
    assert processor.deadline_warnings(NOW) == (near.id, late.id)
    assert processor.deadline_warnings(NOW, business_id=2) == ()


def test_an_invoice_the_sri_received_is_no_longer_reported_as_close_to_the_limit(env):
    invoice = issue(env, sell(env))
    with env.database.connect() as connection:
        connection.execute(
            "UPDATE einvoices SET issued_at = ?",
            ((NOW - timedelta(hours=65)).isoformat(timespec="seconds"),),
        )
    processor, _ = processor_for(env, FakeGateway([RECEIVED_OK]))

    assert processor.deadline_warnings(NOW) == (invoice.id,)
    processor.process_pending(NOW)

    assert processor.deadline_warnings(NOW) == ()


# -- the whole pipeline with the real client and recorded-shape SOAP bodies --------------------


def test_a_sale_is_issued_signed_sent_received_and_authorized(env):
    sale_id = sell(env)
    invoice = issue(env, sale_id, Buyer("05", "1712345678", "Ana Pérez"))
    assert invoice.status == PENDING
    assert verify_invoice_signature(invoice.signed_xml) is True
    transport = FakeTransport(
        fixture("reception_recibida.xml"), fixture("authorization_autorizado.xml")
    )
    processor = EInvoiceProcessor(
        env.database, lambda environment: SriClient(environment, transport)
    )

    first = processor.process_pending(NOW)
    second = processor.process_pending(NOW + timedelta(seconds=30))

    stored = env.service.get_for_sale(env.owner, sale_id)
    assert stored is not None
    assert stored.status == AUTHORIZED
    assert stored.authorization_number == FIRST_ACCESS_KEY
    assert stored.authorized_at == datetime(2026, 3, 5, 19, 35, 10, tzinfo=UTC)
    assert stored.messages == ()
    assert (first.sent, second.authorized) == ((invoice.id,), (invoice.id,))
    (reception_url, reception_body), (authorization_url, authorization_body) = transport.requests
    assert reception_url.endswith("/RecepcionComprobantesOffline")
    assert authorization_url.endswith("/AutorizacionComprobantesOffline")
    sent_xml = re.search(rb"<xml>([^<]+)</xml>", reception_body)
    assert sent_xml is not None
    assert base64.b64decode(sent_xml.group(1)) == invoice.signed_xml
    assert f"<claveAccesoComprobante>{FIRST_ACCESS_KEY}</claveAccesoComprobante>".encode() in (
        authorization_body
    )


def test_a_returned_invoice_through_the_real_client_keeps_its_messages(env):
    invoice = issue(env, sell(env))
    transport = FakeTransport(fixture("reception_devuelta.xml"))
    processor = EInvoiceProcessor(
        env.database, lambda environment: SriClient(environment, transport)
    )

    processor.process_pending(NOW)

    stored = env.repository.get(invoice.id)
    assert stored is not None
    assert stored.status == RETURNED
    assert [message.identifier for message in stored.messages] == ["35", "65"]
    assert stored.messages[0].additional_info.startswith("Error en la estructura")


def test_an_already_registered_invoice_through_the_real_client_ends_authorized(env):
    invoice = issue(env, sell(env))
    transport = FakeTransport(
        fixture("reception_devuelta_43.xml"), fixture("authorization_autorizado.xml")
    )
    processor = EInvoiceProcessor(
        env.database, lambda environment: SriClient(environment, transport)
    )

    processor.process_pending(NOW)

    stored = env.repository.get(invoice.id)
    assert stored is not None
    assert stored.status == AUTHORIZED
    assert len(transport.requests) == 2


# -- re-issuing, starting sequential and the certificate's RUC ---------------------------------

NOT_REISSUABLE = "Solo se puede reemitir una factura devuelta, no autorizada o con error local."
NO_INVOICE = "La venta no tiene una factura electrónica para reemitir."
OLD_STATUS_CHECK = (
    "'pendiente', 'recibida', 'devuelta', 'autorizada', 'no_autorizada', 'error_local'"
)


def text_of(xml: str | bytes) -> str:
    return xml.decode("utf-8") if isinstance(xml, bytes) else xml


def mark(env: Env, invoice, status: str) -> None:
    env.repository.record(invoice.id, status=status, attempts=0, next_attempt_at=None)


@pytest.mark.parametrize("status", [RETURNED, NOT_AUTHORIZED, LOCAL_ERROR])
def test_a_refused_invoice_is_reissued_with_a_new_number_and_access_key(env, status):
    sale_id = sell(env)
    old = issue(env, sale_id)
    mark(env, old, status)

    new = env.service.reissue_for_sale(env.owner, sale_id)

    assert new.status == PENDING
    assert new.sequential == "000000002"
    assert new.access_key != old.access_key
    assert new.id != old.id
    assert verify_invoice_signature(new.signed_xml)
    assert env.service.get_for_sale(env.owner, sale_id) == new
    replaced = env.repository.get(old.id)
    assert replaced.status == "reemplazada"
    assert replaced.replaced_by == new.id
    assert replaced.sequential == "000000001"
    assert [invoice.id for invoice in env.service.list_for_business(env.owner)] == [new.id, old.id]


@pytest.mark.parametrize(
    ("now", "issue_date", "access_key_date"),
    [
        (datetime(2026, 3, 8, 20, 0, tzinfo=UTC), "08/03/2026", "08032026"),
        # 22:00 in Ecuador is already the next day in UTC: the document uses Ecuador's date.
        (datetime(2026, 3, 9, 3, 0, tzinfo=UTC), "08/03/2026", "08032026"),
    ],
)
def test_a_reissued_invoice_is_dated_when_it_is_reissued_not_when_the_sale_was_made(
    env, now, issue_date, access_key_date
):
    sale_id = sell(env)
    old = issue(env, sale_id)
    mark(env, old, RETURNED)
    env.clock = now

    new = env.service.reissue_for_sale(env.owner, sale_id)

    assert new.issued_at == now
    assert f"<fechaEmision>{issue_date}</fechaEmision>" in text_of(new.signed_xml)
    assert new.access_key.startswith(access_key_date)
    assert old.access_key.startswith("05032026")


def test_the_ride_of_a_reissued_invoice_shows_the_date_of_its_xml(env):
    sale_id = sell(env)
    old = issue(env, sale_id)
    assert env.service.invoice_data_for(env.owner, old).issue_date == date(2026, 3, 5)
    mark(env, old, RETURNED)
    env.clock = datetime(2026, 3, 9, 3, 0, tzinfo=UTC)

    new = env.service.reissue_for_sale(env.owner, sale_id)

    assert env.service.invoice_data_for(env.owner, new).issue_date == date(2026, 3, 8)


@pytest.mark.parametrize("status", [PENDING, RECEIVED, AUTHORIZED])
def test_an_invoice_in_progress_or_authorized_can_never_be_reissued(env, status):
    sale_id = sell(env)
    old = issue(env, sale_id)
    mark(env, old, status)
    before = table_snapshot(env.database, "einvoices", "einvoice_sequences")

    with pytest.raises(ValueError) as error:
        env.service.reissue_for_sale(env.owner, sale_id)

    assert str(error.value) == NOT_REISSUABLE
    assert table_snapshot(env.database, "einvoices", "einvoice_sequences") == before


def test_a_sale_without_an_invoice_cannot_be_reissued(env):
    sale_id = sell(env)

    with pytest.raises(ValueError) as error:
        env.service.reissue_for_sale(env.owner, sale_id)

    assert str(error.value) == NO_INVOICE
    assert allocate(env.database) == 1


def test_a_reissue_that_fails_keeps_the_old_invoice_and_burns_no_number(env):
    sale_id = sell(env)
    old = issue(env, sale_id)
    mark(env, old, RETURNED)
    env.profile.certificates(1).clear()
    before = table_snapshot(env.database, "einvoices", "einvoice_sequences")

    with pytest.raises(CertificateStoreError):
        env.service.reissue_for_sale(env.owner, sale_id)

    assert table_snapshot(env.database, "einvoices", "einvoice_sequences") == before
    assert env.service.get_for_sale(env.owner, sale_id).status == RETURNED


def test_the_reissue_keeps_the_buyer_unless_a_new_one_is_given(env):
    sale_id = sell(env)
    old = issue(env, sale_id, Buyer("05", "1710034065", "Ana Mora"))
    mark(env, old, RETURNED)
    kept = env.service.reissue_for_sale(env.owner, sale_id)
    mark(env, kept, RETURNED)
    changed = env.service.reissue_for_sale(
        env.owner, sale_id, Buyer("05", "0912345674", "Luis Paz")
    )

    assert kept.buyer == Buyer("05", "1710034065", "Ana Mora")
    assert changed.buyer == Buyer("05", "0912345674", "Luis Paz")
    assert changed.sequential == "000000003"


def test_a_sale_has_only_one_active_invoice_after_several_reissues(env):
    sale_id = sell(env)
    first = issue(env, sale_id)
    mark(env, first, RETURNED)
    second = env.service.reissue_for_sale(env.owner, sale_id)
    mark(env, second, NOT_AUTHORIZED)
    third = env.service.reissue_for_sale(env.owner, sale_id)

    statuses = [env.repository.get(invoice.id).status for invoice in (first, second, third)]
    assert statuses == ["reemplazada", "reemplazada", PENDING]
    assert env.repository.get(second.id).replaced_by == third.id
    with pytest.raises(ValueError, match="Solo se puede reemitir"):
        env.service.reissue_for_sale(env.owner, sale_id)


def test_a_replaced_invoice_is_never_processed_again(env):
    sale_id = sell(env)
    old = issue(env, sale_id)
    mark(env, old, RETURNED)
    env.service.reissue_for_sale(env.owner, sale_id)
    with env.database.connect() as connection:
        connection.execute("UPDATE einvoices SET next_attempt_at = NULL")

    assert [invoice.id for invoice in env.repository.due(NOW)] == [2]


def test_the_database_allows_a_replaced_row_beside_an_active_one_but_not_two_active(env):
    sale_id = sell(env)
    old = issue(env, sale_id)
    mark(env, old, RETURNED)
    env.service.reissue_for_sale(env.owner, sale_id)
    insert = (
        "INSERT INTO einvoices (business_id, sale_id, establishment, emission_point, sequential,"
        " access_key, environment, status, signed_xml, buyer_id_type, buyer_identification,"
        " buyer_name, issued_at) VALUES (1, ?, '001', '001', ?, ?, 'pruebas', ?, x'00', '07',"
        " '9999999999999', 'CONSUMIDOR FINAL', '2026-03-05T19:30:00+00:00')"
    )

    with env.database.connect() as connection:
        connection.execute(insert, (sale_id, "000000090", "clave-a", "reemplazada"))
    with pytest.raises(sqlite3.IntegrityError), env.database.connect() as connection:
        connection.execute(insert, (sale_id, "000000091", "clave-b", "pendiente"))


def downgrade_to_the_old_einvoices_table(database: Database) -> None:
    """Recreate `einvoices` the way versions before the re-issue made it."""
    with database.connect() as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.executescript(
            f"""
            CREATE TABLE einvoices_old (
                id INTEGER PRIMARY KEY,
                business_id INTEGER NOT NULL REFERENCES businesses(id),
                sale_id INTEGER NOT NULL UNIQUE REFERENCES sales(id),
                establishment TEXT NOT NULL,
                emission_point TEXT NOT NULL,
                sequential TEXT NOT NULL,
                access_key TEXT NOT NULL UNIQUE,
                environment TEXT NOT NULL CHECK (environment IN ('pruebas', 'produccion')),
                status TEXT NOT NULL DEFAULT 'pendiente' CHECK (status IN ({OLD_STATUS_CHECK})),
                signed_xml BLOB NOT NULL,
                buyer_id_type TEXT NOT NULL,
                buyer_identification TEXT NOT NULL,
                buyer_name TEXT NOT NULL,
                buyer_address TEXT NOT NULL DEFAULT '',
                messages TEXT NOT NULL DEFAULT '[]',
                attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
                next_attempt_at TEXT,
                issued_at TEXT NOT NULL,
                authorized_at TEXT,
                authorization_number TEXT,
                UNIQUE (business_id, environment, establishment, emission_point, sequential)
            );
            INSERT INTO einvoices_old
                SELECT id, business_id, sale_id, establishment, emission_point, sequential,
                       access_key, environment, status, signed_xml, buyer_id_type,
                       buyer_identification, buyer_name, buyer_address, messages, attempts,
                       next_attempt_at, issued_at, authorized_at, authorization_number
                FROM einvoices;
            DROP TABLE einvoices;
            ALTER TABLE einvoices_old RENAME TO einvoices;
            """
        )


def test_an_old_einvoices_table_is_migrated_keeping_its_rows_and_can_reissue(env):
    sale_id = sell(env)
    old = issue(env, sale_id)
    mark(env, old, RETURNED)
    downgrade_to_the_old_einvoices_table(env.database)

    env.database.initialize()
    env.database.initialize()

    assert env.repository.get(old.id).status == RETURNED
    new = env.service.reissue_for_sale(env.owner, sale_id)
    assert env.repository.get(old.id).replaced_by == new.id
    assert new.sequential == "000000002"
    with env.database.connect() as connection:
        indexes = {row["name"] for row in connection.execute("PRAGMA index_list(einvoices)")}
    assert "idx_einvoices_status" in indexes


OLD_COLUMNS = (
    "id, business_id, sale_id, establishment, emission_point, sequential, access_key, "
    "environment, status, signed_xml, buyer_id_type, buyer_identification, buyer_name, "
    "buyer_address, messages, attempts, next_attempt_at, issued_at, authorized_at, "
    "authorization_number"
)


def old_columns_snapshot(database: Database) -> list[tuple]:
    with database.connect() as connection:
        return [
            tuple(row)
            for row in connection.execute(f"SELECT {OLD_COLUMNS} FROM einvoices ORDER BY id")
        ]


def test_the_migration_keeps_every_row_status_and_signed_blob_byte_for_byte(env):
    statuses = [PENDING, RECEIVED, RETURNED, AUTHORIZED, NOT_AUTHORIZED, LOCAL_ERROR]
    for position, status in enumerate(statuses):
        invoice = issue(env, sell(env))
        mark(env, invoice, status)
        blob = bytes(range(256)) + bytes([position, 0, 255, 0])
        with env.database.connect() as connection:
            connection.execute(
                "UPDATE einvoices SET signed_xml = ?, messages = ?, attempts = ?, "
                "authorization_number = ? WHERE id = ?",
                (blob, f'[{{"n": {position}}}]', position, f"auth-{position}", invoice.id),
            )
    downgrade_to_the_old_einvoices_table(env.database)
    before = old_columns_snapshot(env.database)
    assert len(before) == len(statuses)

    env.database.initialize()
    after_first = old_columns_snapshot(env.database)
    env.database.initialize()
    after_second = old_columns_snapshot(env.database)

    assert after_first == before
    assert after_second == before
    assert [row[8] for row in after_second] == statuses
    assert all(isinstance(row[9], bytes) for row in after_second)
    with env.database.connect() as connection:
        replaced = connection.execute(
            "SELECT COUNT(*) FROM einvoices WHERE replaced_by IS NOT NULL"
        )
        assert replaced.fetchone()[0] == 0
        tables = {row["name"] for row in connection.execute("SELECT name FROM sqlite_master")}
    assert "einvoices_rebuilt" not in tables


def test_a_migration_that_loses_a_row_raises_and_leaves_the_old_table_untouched(env, monkeypatch):
    for _ in range(3):
        issue(env, sell(env))
    downgrade_to_the_old_einvoices_table(env.database)
    before = old_columns_snapshot(env.database)
    monkeypatch.setattr(
        database_module, "_EINVOICES_COPY", database_module._EINVOICES_COPY + " WHERE id <> 2"
    )

    with pytest.raises(RuntimeError, match="no copió todas las filas"):
        env.database.initialize()

    monkeypatch.undo()
    assert old_columns_snapshot(env.database) == before
    with env.database.connect() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(einvoices)")}
        tables = {row["name"] for row in connection.execute("SELECT name FROM sqlite_master")}
    assert "replaced_by" not in columns
    assert "einvoices_rebuilt" not in tables
    env.database.initialize()
    assert old_columns_snapshot(env.database) == before


def test_initializing_twice_leaves_the_einvoices_untouched(env):
    issue(env, sell(env))
    before = table_snapshot(env.database, "einvoices", "einvoice_sequences")

    env.database.initialize()

    assert table_snapshot(env.database, "einvoices", "einvoice_sequences") == before


# starting sequential


def test_the_owner_can_start_numbering_higher_and_the_next_invoice_uses_it(env):
    assert env.profile.next_sequential(env.owner) == 1

    env.profile.update_einvoice(env.owner, next_sequential=250)

    assert env.profile.next_sequential(env.owner) == 250
    assert issue(env, sell(env)).sequential == "000000250"
    assert env.profile.next_sequential(env.owner) == 251


def test_the_sequential_can_be_raised_but_never_lowered_below_the_last_used(env):
    for _ in range(3):
        issue(env, sell(env))

    with pytest.raises(ValueError) as error:
        env.profile.update_einvoice(env.owner, next_sequential=3)

    assert str(error.value) == "El próximo secuencial debe ser mayor que el último usado (3)."
    assert env.profile.next_sequential(env.owner) == 4
    env.profile.update_einvoice(env.owner, next_sequential=4)
    env.profile.update_einvoice(env.owner, next_sequential=10)
    with pytest.raises(ValueError, match="mayor que el último usado"):
        env.profile.update_einvoice(env.owner, next_sequential=9)
    assert env.profile.next_sequential(env.owner) == 10


def test_a_rejected_sequential_saves_nothing_else_of_the_same_change(env):
    issue(env, sell(env))
    before = env.profile.get(env.owner)

    with pytest.raises(ValueError):
        env.profile.update_einvoice(env.owner, trade_name="Otro nombre", next_sequential=1)

    assert env.profile.get(env.owner) == before


@pytest.mark.parametrize("value", [0, -5, 1_000_000_000])
def test_the_starting_sequential_must_fit_nine_digits(env, value):
    with pytest.raises(ValueError) as error:
        env.profile.update_einvoice(env.owner, next_sequential=value)

    assert str(error.value) == "El próximo secuencial debe estar entre 1 y 999999999."


def test_the_starting_sequential_applies_to_the_series_saved_in_the_same_change(env):
    env.profile.update_einvoice(env.owner, establishment="002", next_sequential=10)

    assert env.profile.next_sequential(env.owner) == 10
    invoice = issue(env, sell(env))
    assert invoice.number == "002-001-000000010"
    env.profile.update_einvoice(env.owner, establishment="001")
    assert env.profile.next_sequential(env.owner) == 1


def test_only_the_owner_sets_the_starting_sequential(env):
    with pytest.raises(PermissionError):
        env.profile.update_einvoice(env.cashier, next_sequential=50)

    assert env.profile.next_sequential(env.owner) == 1


# certificate RUC


def certificate_with_ruc(ruc: str | None) -> bytes:
    return make_p12_with_ruc(
        rsa.generate_private_key(public_exponent=65537, key_size=2048), ruc, b"clave"
    )


def test_a_certificate_with_another_ruc_is_refused_and_nothing_is_saved(env):
    store = env.profile.certificates(1)
    stored_before = store.path.read_bytes()

    with pytest.raises(ValueError) as error:
        env.profile.save_certificate(env.owner, certificate_with_ruc("0990000001001"), "clave")

    assert str(error.value) == (
        "El RUC del certificado (0990000001001) no coincide con el RUC del negocio (1790012345001)."
    )
    assert store.path.read_bytes() == stored_before


def test_a_certificate_with_the_business_ruc_or_without_any_is_saved(env):
    info = env.profile.save_certificate(env.owner, certificate_with_ruc(RUC), "clave")
    assert info.ruc == RUC

    info = env.profile.save_certificate(env.owner, certificate_with_ruc(None), "clave")
    assert info.ruc == ""


def test_enabling_checks_the_certificate_ruc_against_the_business_ruc(env):
    env.profile.save_certificate(env.owner, certificate_with_ruc(RUC), "clave")
    env.profile.update_einvoice(env.owner, enabled=False)
    env.profile.update_profile(env.owner, ruc="0990000001001")

    with pytest.raises(ValueError) as error:
        env.profile.update_einvoice(env.owner, enabled=True)

    assert str(error.value) == (
        "El RUC del certificado (1790012345001) no coincide con el RUC del negocio (0990000001001)."
    )
    assert env.profile.get(env.owner).einvoice_enabled is False
    env.profile.update_profile(env.owner, ruc=RUC)
    assert env.profile.update_einvoice(env.owner, enabled=True).einvoice_enabled is True


# -- one background pass ---------------------------------------------------------------------


def test_a_pass_counts_the_invoices_still_open_for_the_business(env):
    first = issue(env, sell(env))
    issue(env, sell(env))
    gateway = FakeGateway([RECEIVED_OK, RECEIVED_OK])

    result = run_processing_pass(env.database.path, 1, lambda environment: gateway, NOW)

    # Both were sent; they are asked about in a later pass, so both are still open.
    assert result.error == ""
    assert result.report == ProcessReport(sent=(first.id, first.id + 1), near_deadline=())
    assert result.open_count == 2
    assert EInvoiceRepository(env.database).count_open(1) == 2
    assert EInvoiceRepository(env.database).count_open(2) == 0


def test_a_pass_that_raises_reports_the_error_instead_of_raising(env):
    issue(env, sell(env))

    def broken(environment: str):
        raise RuntimeError("falló el cliente")

    result = run_processing_pass(env.database.path, 1, broken, NOW)

    assert result.report is None
    assert "falló el cliente" in result.error
    assert result.open_count == 1


def test_authorized_and_refused_invoices_are_not_open(env):
    done = issue(env, sell(env))
    refused = issue(env, sell(env))
    waiting = issue(env, sell(env))
    mark(env, done, AUTHORIZED)
    mark(env, refused, RETURNED)
    mark(env, waiting, RECEIVED)

    assert EInvoiceRepository(env.database).count_open(1) == 1
