import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from PySide6.QtWidgets import QApplication
from test_certificate_store import FakeProtector
from test_xades import make_p12

from suitelocal.application.auth import AuthService
from suitelocal.application.business_profile import BusinessProfileService
from suitelocal.domain.auth import Session
from suitelocal.domain.models import Payment, Sale, SaleItem
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import (
    CategoryRepository,
    ProductRepository,
    SaleRepository,
)
from suitelocal.infrastructure.settings import BusinessSettingsRepository
from suitelocal.infrastructure.sri.certificate_store import CertificateStore
from suitelocal.infrastructure.sri.client import AuthorizationResult, ReceptionResult
from suitelocal.ui.components import Toast
from suitelocal.ui.shell import AppShell

RUC = "1790012345001"
NOT_DECIDED = AuthorizationResult("EN PROCESO", None, None, ())
DECIDED = AuthorizationResult("AUTORIZADO", "1" * 49, datetime(2026, 3, 5, tzinfo=UTC), ())


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeGateway:
    def __init__(self, answer: AuthorizationResult = NOT_DECIDED) -> None:
        self.answer = answer
        self.authorized: list[str] = []

    def send(self, signed_xml: bytes) -> ReceptionResult:
        raise AssertionError("these tests never send")

    def authorize(self, access_key: str) -> AuthorizationResult:
        self.authorized.append(access_key)
        return self.answer


@dataclass
class Env:
    database: Database
    auth: AuthService
    owner: Session
    profile: BusinessProfileService
    gateway: FakeGateway
    certificates_root: object
    sales_made: int = 0

    def add_invoice(self, status: str, signed_xml: bytes = b"\x00") -> None:
        self.sales_made += 1
        products = ProductRepository(self.database)
        product = products.add(f"P-{self.sales_made}", "Arroz", 100, 50, tax_rate_basis_points=0)
        sale_id = SaleRepository(self.database).register(
            Sale((SaleItem(product.id, product.name, 1, 100, 0),), 100, (Payment("cash", 100),)),
            business_id=self.owner.user.business_id,
            user_id=self.owner.user.id,
        )
        with self.database.connect() as connection:
            connection.execute(
                "INSERT INTO einvoices (business_id, sale_id, establishment, emission_point,"
                " sequential, access_key, environment, status, signed_xml, buyer_id_type,"
                " buyer_identification, buyer_name, issued_at) VALUES (?, ?, '001', '001', ?, ?,"
                " 'pruebas', ?, ?, '07', '9999999999999', 'CONSUMIDOR FINAL',"
                " '2026-03-05T19:30:00+00:00')",
                (
                    self.owner.user.business_id,
                    sale_id,
                    f"{self.sales_made:09d}",
                    f"{self.sales_made:049d}",
                    status,
                    signed_xml,
                ),
            )


@pytest.fixture
def env(qapp, tmp_path, rsa_key) -> Env:
    database = Database(tmp_path / "shell.db")
    database.initialize()
    auth = AuthService(database)
    owner = Session(auth.setup_owner("Tienda Sol", "owner", "clave-segura", "clave-segura"))
    root = tmp_path / "data"
    profile = BusinessProfileService(
        BusinessSettingsRepository(database),
        CategoryRepository(database),
        lambda business_id: CertificateStore.for_business(root, business_id, FakeProtector()),
    )
    profile.update_profile(owner, tax_regime="rimpe_emprendedor", ruc=RUC, address="Av. 1")
    now = datetime.now(UTC)
    p12 = make_p12(
        rsa_key, b"clave", not_before=now - timedelta(days=1), not_after=now + timedelta(days=365)
    )
    profile.save_certificate(owner, p12, "clave")
    return Env(database, auth, owner, profile, FakeGateway(), root)


def build_shell(env: Env) -> AppShell:
    return AppShell(
        ProductRepository(env.database),
        SaleRepository(env.database),
        env.owner,
        BusinessSettingsRepository(env.database),
        env.auth,
        env.database,
        certificates=lambda business_id: CertificateStore.for_business(
            env.certificates_root, business_id, FakeProtector()
        ),
        einvoice_client_for=lambda environment: env.gateway,
        einvoice_executor=lambda work: work(),
    )


@pytest.fixture
def make_shell(env):
    windows: list[AppShell] = []

    def make() -> AppShell:
        window = build_shell(env)
        windows.append(window)
        return window

    yield make
    for window in windows:
        window.close()
        window.deleteLater()


def toasts(shell: AppShell) -> list[Toast]:
    return shell.toasts.findChildren(Toast)


def test_nothing_runs_and_no_sri_status_shows_while_invoicing_is_disabled(env, make_shell):
    env.add_invoice("recibida")
    shell = make_shell()

    assert shell.einvoice_runner.tick() is False

    assert env.gateway.authorized == []
    assert shell.status_sri_item.isHidden()


def test_the_status_bar_counts_the_invoices_waiting_for_the_sri(env, make_shell):
    env.profile.update_einvoice(env.owner, enabled=True)
    env.add_invoice("recibida")
    env.add_invoice("pendiente", signed_xml=b"\x00")
    env.add_invoice("autorizada")
    shell = make_shell()

    assert not shell.status_sri_item.isHidden()
    assert shell.status_sri.text() == "SRI: 2 pendientes"


def test_a_single_waiting_invoice_reads_in_the_singular(env, make_shell):
    env.profile.update_einvoice(env.owner, enabled=True)
    env.add_invoice("recibida")

    assert make_shell().status_sri.text() == "SRI: 1 pendiente"


def test_a_pass_asks_the_sri_and_the_count_drops_when_invoices_are_decided(env, make_shell):
    env.profile.update_einvoice(env.owner, enabled=True)
    env.add_invoice("recibida")
    env.add_invoice("recibida")
    shell = make_shell()

    shell.einvoice_runner.tick()
    assert len(env.gateway.authorized) == 2
    assert shell.status_sri.text() == "SRI: 2 pendientes"

    env.gateway.answer = DECIDED
    with env.database.connect() as connection:
        connection.execute("UPDATE einvoices SET next_attempt_at = NULL")
    shell.einvoice_runner.tick()

    assert shell.status_sri_item.isHidden()


def test_a_failed_pass_shows_one_warning_toast_and_not_another_for_the_same_problem(
    env, make_shell
):
    env.profile.update_einvoice(env.owner, enabled=True)
    env.add_invoice("pendiente", signed_xml=b"\x00")
    shell = make_shell()
    spy: list[str] = []
    shell.einvoice_runner.warning.connect(spy.append)

    shell.einvoice_runner.tick()

    assert len(spy) == 1
    assert "El SRI no aceptó 1 factura electrónica" in spy[0]
    assert len(toasts(shell)) == 1
    shell.einvoice_runner.tick()
    assert len(toasts(shell)) == 1


def test_the_timer_runs_every_two_minutes_and_stops_with_the_window(env, make_shell):
    shell = make_shell()

    assert shell.einvoice_runner.interval_ms == 120_000
    assert shell.einvoice_runner.is_active is True
    shell.close()
    assert shell.einvoice_runner.is_active is False


def test_turning_invoicing_off_hides_the_status_and_stops_the_passes(env, make_shell):
    env.profile.update_einvoice(env.owner, enabled=True)
    env.add_invoice("recibida")
    shell = make_shell()
    env.profile.update_einvoice(env.owner, enabled=False)

    shell._on_business_changed()

    assert shell.status_sri_item.isHidden()
    assert shell.einvoice_runner.tick() is False


def test_the_settings_page_receives_the_certificate_store(env, make_shell):
    shell = make_shell()

    assert shell.settings_page is not None
    store = shell.settings_page.profile.certificates(1)
    assert store.path == env.certificates_root / "certificates" / "business-1.bin"
    assert store.exists()
