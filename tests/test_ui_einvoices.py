import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from einvoice_env import EInvoiceEnv, build_env
from PySide6.QtWidgets import QApplication

from suitelocal.domain.auth import Session, User
from suitelocal.domain.einvoice import (
    AUTHORIZED,
    LOCAL_ERROR,
    NOT_AUTHORIZED,
    PENDING,
    RECEIVED,
    REPLACED,
    RETURNED,
    Buyer,
    SriMessage,
)
from suitelocal.infrastructure.sri.queue import EInvoiceRepository
from suitelocal.ui.components import StatusBadge
from suitelocal.ui.einvoices import EInvoicesWidget
from suitelocal.ui.ride import Ride

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
BUYER = Buyer("05", "0912345678", "Ana Pérez")
HEADERS = ["Fecha", "Número", "Cliente", "Total", "Estado", "Último mensaje"]
STATUS_LABELS = {
    PENDING: "Pendiente",
    RECEIVED: "Recibida",
    AUTHORIZED: "Autorizada",
    RETURNED: "Devuelta",
    NOT_AUTHORIZED: "No autorizada",
    LOCAL_ERROR: "Error",
    REPLACED: "Reemplazada",
}


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeRideOutput:
    def __init__(self) -> None:
        self.rides: list[Ride] = []
        self.failure: Exception | None = None

    def print_ride(self, ride: Ride) -> None:
        if self.failure:
            raise self.failure
        self.rides.append(ride)


class Page:
    def __init__(self, env: EInvoiceEnv, qapp) -> None:
        self.env = env
        self.repository = EInvoiceRepository(env.database)
        self.rides = FakeRideOutput()
        self.notices: list[tuple[str, str]] = []
        self.confirmations: list[tuple[str, str]] = []
        self.confirm_answer = True
        self.viewed: list[tuple[str, str]] = []
        self.process_calls = 0
        self.process_answer = True
        self.widget = EInvoicesWidget(
            env.service,
            env.owner,
            process_now=self._process,
            ride_output=self.rides,
            confirmer=self._confirm,
            message_viewer=lambda _parent, title, text: self.viewed.append((title, text)),
            clock=lambda: NOW,
        )
        self.widget.notification.connect(lambda text, state: self.notices.append((text, state)))

    def _process(self) -> bool:
        self.process_calls += 1
        return self.process_answer

    def _confirm(self, _parent, title: str, text: str) -> bool:
        self.confirmations.append((title, text))
        return self.confirm_answer

    def add(self, status: str = PENDING, messages=(), issued_at=None, price=115) -> int:
        sale_id = self.env.sell(price)
        invoice = self.env.service.issue_for_sale(self.env.owner, sale_id, BUYER)
        if issued_at is not None:
            with self.env.database.connect() as connection:
                connection.execute(
                    "UPDATE einvoices SET issued_at = ? WHERE id = ?",
                    (issued_at.isoformat(timespec="seconds"), invoice.id),
                )
        if status != PENDING or messages:
            extra = {}
            if status == AUTHORIZED:
                extra = {"authorization_number": "1" * 49, "authorized_at": NOW}
            self.repository.record(
                invoice.id,
                status=status,
                attempts=0,
                next_attempt_at=None,
                messages=tuple(messages),
                **extra,
            )
        return invoice.id

    def select(self, row: int) -> None:
        self.widget.table.selectRow(row)

    def cell(self, row: int, column: int) -> str:
        item = self.widget.table.item(row, column)
        if item is not None:
            return item.text()
        badge = self.widget.table.cellWidget(row, column)
        assert isinstance(badge, StatusBadge)
        return badge.text()


@pytest.fixture
def page(qapp, tmp_path, rsa_key):
    value = Page(build_env(tmp_path, rsa_key), qapp)
    yield value
    value.widget.deleteLater()


def test_the_table_has_the_agreed_columns(page):
    assert [page.widget.table.horizontalHeaderItem(column).text() for column in range(6)] == HEADERS


def test_an_empty_page_shows_the_empty_state_and_no_rows(page):
    page.widget.refresh()

    assert page.widget.table.rowCount() == 0
    assert not page.widget.empty_state.isHidden()


def test_rows_show_number_client_total_and_status_newest_first(page):
    page.add(price=115)
    page.add(price=230)
    page.widget.refresh()

    table = page.widget.table
    assert table.rowCount() == 2
    assert page.widget.empty_state.isHidden()
    assert page.cell(0, 1) == "001-001-000000002"
    assert page.cell(0, 2) == "Ana Pérez"
    assert page.cell(0, 3) == "$ 2,30"
    assert page.cell(1, 1) == "001-001-000000001"
    assert page.cell(1, 3) == "$ 1,15"
    assert page.cell(0, 4) == "•  Pendiente"


def test_the_date_is_the_sale_time_in_local_hours(page):
    page.add()
    page.widget.refresh()

    stored = page.env.service.list_for_business(page.env.owner)[0]
    assert page.cell(0, 0) == f"{stored.issued_at.astimezone():%d/%m/%Y %H:%M}"


@pytest.mark.parametrize("status", list(STATUS_LABELS))
def test_every_status_has_its_chip(page, status):
    page.add(status)
    page.widget.refresh()

    assert page.cell(0, 4) == f"•  {STATUS_LABELS[status]}"


def test_the_last_message_of_the_sri_is_shown(page):
    page.add(
        RETURNED,
        (
            SriMessage("35", "ARCHIVO NO CUMPLE ESTRUCTURA XML", "línea 3", "ERROR"),
            SriMessage("39", "FIRMA INVALIDA", "", "ERROR"),
        ),
    )
    page.widget.refresh()

    assert page.cell(0, 5) == "39: FIRMA INVALIDA"


def test_the_last_message_includes_the_additional_info_when_there_is_one(page):
    page.add(RETURNED, (SriMessage("35", "ARCHIVO NO CUMPLE ESTRUCTURA XML", "línea 3", "ERROR"),))
    page.widget.refresh()

    assert page.cell(0, 5) == "35: ARCHIVO NO CUMPLE ESTRUCTURA XML (línea 3)"


def test_without_messages_the_last_message_is_empty(page):
    page.add()
    page.widget.refresh()

    assert page.cell(0, 5) == ""


def test_the_actions_need_a_selected_invoice(page):
    page.add(RETURNED)
    page.widget.refresh()

    for button in (
        page.widget.reissue_button,
        page.widget.messages_button,
        page.widget.reprint_button,
    ):
        assert not button.isEnabled()
    assert page.widget.process_button.isEnabled()


def test_reissue_is_only_enabled_for_states_that_can_be_issued_again(page):
    for status in STATUS_LABELS:
        page.add(status)
    page.widget.refresh()

    enabled: dict[str, bool] = {}
    for row in range(page.widget.table.rowCount()):
        page.select(row)
        label = page.cell(row, 4).removeprefix("•  ")
        enabled[label] = page.widget.reissue_button.isEnabled()

    assert enabled == {
        "Pendiente": False,
        "Recibida": False,
        "Autorizada": False,
        "Devuelta": True,
        "No autorizada": True,
        "Error": True,
        "Reemplazada": False,
    }


def test_reissue_asks_first_and_does_nothing_when_declined(page):
    page.add(RETURNED)
    page.widget.refresh()
    page.select(0)
    page.confirm_answer = False

    page.widget.reissue_button.click()

    assert page.confirmations == [
        (
            "Reemitir la factura",
            "¿Reemitir la factura 001-001-000000001? Se reemplaza por una nueva con otro número.",
        )
    ]
    assert page.widget.table.rowCount() == 1
    assert page.notices == []


def test_confirmed_reissue_creates_the_new_invoice_and_refreshes(page):
    page.add(NOT_AUTHORIZED)
    page.widget.refresh()
    page.select(0)

    page.widget.reissue_button.click()

    assert page.widget.table.rowCount() == 2
    assert page.cell(0, 1) == "001-001-000000002"
    assert page.cell(0, 4) == "•  Pendiente"
    assert page.cell(1, 4) == "•  Reemplazada"
    assert page.notices == [("Factura reemitida: 001-001-000000002.", "success")]


def test_a_failed_reissue_shows_the_reason_as_a_warning(page, monkeypatch):
    page.add(RETURNED)
    page.widget.refresh()
    page.select(0)

    def refuse(*_args, **_kwargs):
        raise ValueError("No hay certificado.")

    monkeypatch.setattr(page.env.service, "reissue_for_sale", refuse)

    page.widget.reissue_button.click()

    assert page.notices == [("No se pudo reemitir la factura. No hay certificado.", "warning")]
    assert page.widget.table.rowCount() == 1


def test_messages_are_enabled_only_when_the_invoice_has_some(page):
    page.add()
    page.add(RETURNED, (SriMessage("35", "ESTRUCTURA", "línea 3", "ERROR"),))
    page.widget.refresh()

    page.select(0)
    assert page.widget.messages_button.isEnabled()
    page.select(1)
    assert not page.widget.messages_button.isEnabled()


def test_view_messages_shows_every_message_of_the_selected_invoice(page):
    page.add(
        RETURNED,
        (
            SriMessage("35", "ESTRUCTURA", "línea 3", "ERROR"),
            SriMessage("60", "AVISO", "", "ADVERTENCIA"),
        ),
    )
    page.widget.refresh()
    page.select(0)

    page.widget.messages_button.click()

    assert page.viewed == [
        (
            "Mensajes del SRI · 001-001-000000001",
            "ERROR 35: ESTRUCTURA\nlínea 3\n\nADVERTENCIA 60: AVISO",
        )
    ]


def test_reprint_sends_the_ride_of_the_selected_invoice_to_the_printer(page):
    page.add(AUTHORIZED)
    page.widget.refresh()
    page.select(0)

    page.widget.reprint_button.click()

    assert len(page.rides.rides) == 1
    ride = page.rides.rides[0]
    assert ride.einvoice.number == "001-001-000000001"
    assert ride.einvoice.status == AUTHORIZED
    assert ride.invoice.total_cents == 115
    assert page.notices == [("RIDE enviado a la impresora.", "success")]


def test_a_printer_failure_while_reprinting_is_a_warning(page):
    page.add()
    page.widget.refresh()
    page.select(0)
    page.rides.failure = RuntimeError("sin papel")

    page.widget.reprint_button.click()

    assert page.notices == [("No se pudo imprimir el RIDE: sin papel", "warning")]


def test_process_now_uses_the_runner_and_says_so(page):
    page.widget.process_button.click()

    assert page.process_calls == 1
    assert page.notices == [("Procesando las facturas electrónicas…", "info")]


def test_process_now_explains_when_the_runner_could_not_start(page):
    page.process_answer = False

    page.widget.process_button.click()

    assert page.notices == [
        ("Ya se está procesando o la factura electrónica está desactivada.", "info")
    ]


def test_there_is_no_banner_when_nothing_is_late(page):
    page.add(issued_at=NOW - timedelta(hours=59))
    page.widget.refresh()

    assert page.widget.deadline_banner.isHidden()


def test_a_banner_warns_about_invoices_over_sixty_hours_without_reception(page):
    page.add(issued_at=NOW - timedelta(hours=61))
    page.add(issued_at=NOW - timedelta(hours=70))
    page.add(RECEIVED, issued_at=NOW - timedelta(hours=70))
    page.widget.refresh()

    banner = page.widget.deadline_banner
    assert not banner.isHidden()
    assert banner.text() == (
        "2 facturas llevan más de 60 horas sin que el SRI las reciba. "
        "El plazo es de 72 horas: revisá la conexión y tocá «Procesar ahora»."
    )


def test_the_banner_reads_in_the_singular(page):
    page.add(issued_at=NOW - timedelta(hours=65))
    page.widget.refresh()

    assert page.widget.deadline_banner.text().startswith("1 factura lleva más de 60 horas")


def test_refresh_keeps_the_selected_invoice(page):
    page.add()
    page.add(RETURNED)
    page.widget.refresh()
    page.select(0)

    page.widget.refresh()

    assert page.widget.table.currentRow() == 0
    assert page.widget.reissue_button.isEnabled()


def test_the_service_lists_only_the_invoices_of_the_session_business(page):
    page.add()
    with page.env.database.connect() as connection:
        other = connection.execute("INSERT INTO businesses (name) VALUES ('Otra')").lastrowid
        user = connection.execute(
            "INSERT INTO users (business_id, username, password_hash, role) "
            "VALUES (?, 'otro', 'x', 'owner')",
            (other,),
        ).lastrowid
    assert other is not None and user is not None
    stranger = Session(User(user, other, "otro", "owner", True))

    assert page.env.service.list_rows(stranger) == []
    assert len(page.env.service.list_rows(page.env.owner)) == 1
    assert page.env.service.deadline_warnings(stranger, NOW) == ()
