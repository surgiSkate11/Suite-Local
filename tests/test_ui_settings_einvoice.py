import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from PySide6.QtWidgets import QApplication
from test_certificate_store import FakeProtector

from suitelocal.application.auth import AuthService
from suitelocal.application.business_profile import BusinessProfileService
from suitelocal.domain.auth import Session
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import CategoryRepository
from suitelocal.infrastructure.settings import BusinessSettingsRepository
from suitelocal.infrastructure.sri.certificate_store import CertificateStore
from suitelocal.ui.settings import SettingsWidget

NOW = datetime(2026, 11, 7, 15, 0, tzinfo=UTC)
RUC = "1790012345001"
PASSWORD = "clave-del-p12"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def make_certificate(
    key: rsa.RSAPrivateKey, *, ruc: str | None = RUC, days: int = 365, not_after=None
) -> bytes:
    attributes = [
        x509.NameAttribute(NameOID.COUNTRY_NAME, "EC"),
        x509.NameAttribute(NameOID.COMMON_NAME, "MARIA PEREZ"),
    ]
    if ruc is not None:
        attributes.append(x509.NameAttribute(NameOID.SERIAL_NUMBER, ruc))
    name = x509.Name(attributes)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(NOW - timedelta(days=1))
        .not_valid_after(not_after or NOW + timedelta(days=days))
        .sign(key, hashes.SHA256())
    )
    return pkcs12.serialize_key_and_certificates(
        b"firma",
        key,
        certificate,
        None,
        serialization.BestAvailableEncryption(PASSWORD.encode()),
    )


class Confirmations:
    def __init__(self, answer: bool = True) -> None:
        self.answer = answer
        self.asked: list[tuple[str, str]] = []

    def __call__(self, parent, title: str, text: str) -> bool:
        self.asked.append((title, text))
        return self.answer


class Picker:
    """Stands in for the file dialog: answers with the next scripted file, or nothing."""

    def __init__(self) -> None:
        self.files: list[Path | None] = []
        self.calls = 0

    def __call__(self, parent) -> Path | None:
        self.calls += 1
        return self.files.pop(0) if self.files else None


@dataclass
class Env:
    database: Database
    owner: Session
    cashier: Session
    root: Path
    confirm: Confirmations = field(default_factory=Confirmations)
    picker: Picker = field(default_factory=Picker)

    def profile(self) -> BusinessProfileService:
        return BusinessProfileService(
            BusinessSettingsRepository(self.database),
            CategoryRepository(self.database),
            self.certificates,
        )

    def certificates(self, business_id: int) -> CertificateStore:
        return CertificateStore.for_business(self.root, business_id, FakeProtector())

    def stored(self):
        return BusinessSettingsRepository(self.database).get(self.owner.user.business_id)

    def build(self, session: Session | None = None) -> SettingsWidget:
        return SettingsWidget(
            BusinessSettingsRepository(self.database),
            session or self.owner,
            self.database,
            confirm=self.confirm,
            printer_names=lambda: (),
            certificates=self.certificates,
            pick_certificate=self.picker,
            clock=lambda: NOW,
        )

    def write_p12(self, tmp_path: Path, data: bytes, name: str = "firma.p12") -> Path:
        path = tmp_path / name
        path.write_bytes(data)
        return path


@pytest.fixture
def env(qapp, tmp_path) -> Env:
    database = Database(tmp_path / "settings.db")
    database.initialize()
    auth = AuthService(database)
    owner = Session(auth.setup_owner("Tienda Sol", "owner", "clave-segura", "clave-segura"))
    cashier = Session(auth.create_cashier(owner, "cajero", "clave-cajero", "clave-cajero"))
    return Env(database, owner, cashier, tmp_path / "data")


@pytest.fixture
def invoicing(env) -> Env:
    """A business of a regime that issues invoices, with the RUC filled in."""
    env.profile().update_profile(
        env.owner, tax_regime="rimpe_emprendedor", ruc=RUC, address="Av. Amazonas 123"
    )
    return env


def save_certificate(env: Env, key, **options) -> None:
    env.profile().save_certificate(env.owner, make_certificate(key, **options), PASSWORD, now=NOW)


def load_through_the_ui(env: Env, widget: SettingsWidget, tmp_path: Path, data: bytes) -> None:
    env.picker.files.append(env.write_p12(tmp_path, data))
    widget.certificate_password.setText(PASSWORD)
    widget.load_certificate()


# -- who sees the card ------------------------------------------------------------------------


@pytest.mark.parametrize("regime", ["sin_registro", "rimpe_popular"])
def test_the_card_is_hidden_for_regimes_that_do_not_issue_invoices(env, regime):
    env.profile().update_profile(env.owner, tax_regime=regime)

    assert env.build().einvoice_card.isHidden()


@pytest.mark.parametrize("regime", ["rimpe_emprendedor", "general"])
def test_the_card_is_shown_for_regimes_that_issue_invoices(env, regime):
    env.profile().update_profile(env.owner, tax_regime=regime, ruc=RUC)

    assert not env.build().einvoice_card.isHidden()


def test_the_card_is_never_shown_to_a_cashier(invoicing):
    assert invoicing.build(invoicing.cashier).einvoice_card.isHidden()


def test_saving_a_regime_that_issues_invoices_reveals_the_card(env):
    widget = env.build()
    assert widget.einvoice_card.isHidden()

    widget.regime.setCurrentIndex(widget.regime.findData("general"))
    widget.ruc.setText(RUC)
    widget.save()

    assert not widget.einvoice_card.isHidden()


# -- the form ---------------------------------------------------------------------------------


def test_the_form_shows_the_stored_values(invoicing):
    invoicing.profile().update_einvoice(
        invoicing.owner,
        establishment="002",
        emission_point="003",
        obligado_contabilidad=True,
        trade_name="La Esquina",
        next_sequential=45,
    )

    widget = invoicing.build()

    environments = [
        widget.einvoice_environment.itemText(i) for i in range(widget.einvoice_environment.count())
    ]
    assert environments == ["Pruebas", "Producción"]
    assert widget.einvoice_environment.currentData() == "pruebas"
    assert widget.einvoice_enabled.isChecked() is False
    assert widget.einvoice_establishment.text() == "002"
    assert widget.einvoice_point.text() == "003"
    assert widget.einvoice_next_sequential.value() == 45
    assert widget.einvoice_accounting.isChecked() is True
    assert widget.einvoice_trade_name.text() == "La Esquina"
    assert widget.einvoice_accounting.text() == "Obligado a llevar contabilidad"


def test_saving_stores_every_field_and_tells_the_app(invoicing, tmp_path, rsa_key):
    save_certificate(invoicing, rsa_key)
    widget = invoicing.build()
    changes: list[bool] = []
    widget.business_changed.connect(lambda: changes.append(True))
    widget.einvoice_enabled.setChecked(True)
    widget.einvoice_establishment.setText("002")
    widget.einvoice_point.setText("004")
    widget.einvoice_next_sequential.setValue(120)
    widget.einvoice_accounting.setChecked(True)
    widget.einvoice_trade_name.setText("  La Esquina ")

    widget.save_einvoice()

    stored = invoicing.stored()
    assert stored.einvoice_enabled is True
    assert (stored.establishment, stored.emission_point) == ("002", "004")
    assert stored.obligado_contabilidad is True
    assert stored.trade_name == "La Esquina"
    assert invoicing.profile().next_sequential(invoicing.owner) == 120
    assert changes == [True]
    assert widget.einvoice_message.isHidden() is False
    assert widget.einvoice_message.property("state") == "success"


def test_enabling_without_a_certificate_shows_the_backend_message_and_saves_nothing(invoicing):
    widget = invoicing.build()
    widget.einvoice_enabled.setChecked(True)
    widget.einvoice_trade_name.setText("Otro nombre")
    before = invoicing.stored()

    widget.save_einvoice()

    assert "primero se debe cargar el certificado" in widget.einvoice_message.text()
    assert widget.einvoice_message.property("state") == "error"
    assert invoicing.stored() == before
    assert widget.einvoice_enabled.isChecked() is False


def test_an_invalid_establishment_shows_the_message_and_saves_nothing(invoicing):
    widget = invoicing.build()
    widget.einvoice_establishment.setText("12")
    widget.einvoice_trade_name.setText("Otro nombre")
    before = invoicing.stored()

    widget.save_einvoice()

    assert widget.einvoice_message.text() == "El establecimiento debe tener exactamente 3 dígitos."
    assert invoicing.stored() == before


def test_a_sequential_below_the_last_used_is_refused_and_nothing_is_saved(invoicing):
    invoicing.profile().update_einvoice(invoicing.owner, next_sequential=50)
    widget = invoicing.build()
    widget.einvoice_next_sequential.setValue(10)
    widget.einvoice_trade_name.setText("Otro nombre")
    before = invoicing.stored()

    widget.save_einvoice()

    assert widget.einvoice_message.text() == (
        "El próximo secuencial debe ser mayor que el último usado (49)."
    )
    assert invoicing.stored() == before
    assert invoicing.profile().next_sequential(invoicing.owner) == 50


# -- production -------------------------------------------------------------------------------


def test_switching_to_production_asks_and_declining_keeps_testing(invoicing):
    invoicing.confirm.answer = False
    widget = invoicing.build()

    widget.einvoice_environment.setCurrentIndex(widget.einvoice_environment.findData("produccion"))

    assert len(invoicing.confirm.asked) == 1
    assert "producción" in invoicing.confirm.asked[0][1].lower()
    assert widget.einvoice_environment.currentData() == "pruebas"
    widget.save_einvoice()
    assert invoicing.stored().sri_environment == "pruebas"


def test_accepting_production_keeps_it_and_saving_stores_it(invoicing):
    widget = invoicing.build()

    widget.einvoice_environment.setCurrentIndex(widget.einvoice_environment.findData("produccion"))
    widget.save_einvoice()

    assert len(invoicing.confirm.asked) == 1
    assert invoicing.stored().sri_environment == "produccion"


def test_going_back_to_testing_and_loading_the_form_never_asks(invoicing):
    invoicing.profile().update_einvoice(invoicing.owner, sri_environment="produccion")
    widget = invoicing.build()

    widget.einvoice_environment.setCurrentIndex(widget.einvoice_environment.findData("pruebas"))

    assert widget.einvoice_environment.currentData() == "pruebas"
    assert invoicing.confirm.asked == []


# -- the certificate --------------------------------------------------------------------------


def test_without_a_certificate_the_card_says_so_and_offers_to_load_one(invoicing):
    widget = invoicing.build()

    assert widget.certificate_holder.text() == "Sin certificado cargado"
    assert widget.certificate_ruc.isHidden()
    assert widget.certificate_expiry.isHidden()
    assert widget.remove_certificate_button.isHidden()
    assert widget.load_certificate_button.text() == "Cargar certificado (.p12)"


def test_loading_a_certificate_shows_holder_ruc_and_expiry_and_clears_the_password(
    invoicing, tmp_path, rsa_key
):
    widget = invoicing.build()
    not_after = datetime(2027, 3, 15, 12, 0, tzinfo=UTC)

    load_through_the_ui(invoicing, widget, tmp_path, make_certificate(rsa_key, not_after=not_after))

    assert "MARIA PEREZ" in widget.certificate_holder.text()
    assert RUC in widget.certificate_ruc.text()
    assert widget.certificate_expiry.text() == "Válido hasta 15/03/2027"
    assert widget.certificate_warning.isHidden()
    assert widget.certificate_password.text() == ""
    assert not widget.remove_certificate_button.isHidden()
    assert invoicing.certificates(1).exists()


def test_a_certificate_without_a_ruc_says_the_ruc_is_not_in_it(invoicing, tmp_path, rsa_key):
    widget = invoicing.build()

    load_through_the_ui(invoicing, widget, tmp_path, make_certificate(rsa_key, ruc=None))

    assert "no consta" in widget.certificate_ruc.text()


def test_a_certificate_expiring_in_less_than_30_days_is_flagged(invoicing, tmp_path, rsa_key):
    widget = invoicing.build()

    load_through_the_ui(invoicing, widget, tmp_path, make_certificate(rsa_key, days=10))

    assert not widget.certificate_warning.isHidden()
    assert widget.certificate_warning.text().startswith("El certificado vence en 10 días.")


def test_a_certificate_with_30_days_or_more_is_not_flagged(invoicing, tmp_path, rsa_key):
    widget = invoicing.build()

    load_through_the_ui(invoicing, widget, tmp_path, make_certificate(rsa_key, days=30))

    assert widget.certificate_warning.isHidden()


def test_a_stored_certificate_that_has_expired_is_flagged_when_the_card_opens(invoicing, rsa_key):
    save_certificate(invoicing, rsa_key, days=20)
    widget = invoicing.build()
    assert "vence en" in widget.certificate_warning.text()

    later = SettingsWidget(
        BusinessSettingsRepository(invoicing.database),
        invoicing.owner,
        invoicing.database,
        confirm=invoicing.confirm,
        printer_names=lambda: (),
        certificates=invoicing.certificates,
        pick_certificate=invoicing.picker,
        clock=lambda: NOW + timedelta(days=40),
    )

    assert later.certificate_warning.text().startswith("El certificado venció el 27/11/2026.")


def test_a_wrong_password_shows_the_backend_message_and_stores_nothing(
    invoicing, tmp_path, rsa_key
):
    widget = invoicing.build()
    invoicing.picker.files.append(invoicing.write_p12(tmp_path, make_certificate(rsa_key)))
    widget.certificate_password.setText("otra-clave")

    widget.load_certificate()

    assert "la contraseña es incorrecta" in widget.einvoice_message.text()
    assert widget.einvoice_message.property("state") == "error"
    assert invoicing.certificates(1).exists() is False
    assert widget.certificate_holder.text() == "Sin certificado cargado"


def test_a_certificate_of_another_ruc_is_refused_and_the_stored_one_stays(
    invoicing, tmp_path, rsa_key
):
    save_certificate(invoicing, rsa_key)
    before = invoicing.certificates(1).path.read_bytes()
    widget = invoicing.build()

    load_through_the_ui(invoicing, widget, tmp_path, make_certificate(rsa_key, ruc="0990000001001"))

    assert "no coincide con el RUC del negocio" in widget.einvoice_message.text()
    assert invoicing.certificates(1).path.read_bytes() == before


def test_loading_needs_a_password_before_the_file_dialog_opens(invoicing):
    widget = invoicing.build()

    widget.load_certificate()

    assert widget.einvoice_message.text() == "Escribí la contraseña del certificado."
    assert invoicing.picker.calls == 0


def test_cancelling_the_file_dialog_changes_nothing(invoicing):
    widget = invoicing.build()
    widget.certificate_password.setText(PASSWORD)

    widget.load_certificate()

    assert invoicing.picker.calls == 1
    assert widget.einvoice_message.isHidden()
    assert widget.certificate_password.text() == PASSWORD
    assert invoicing.certificates(1).exists() is False


def test_a_file_that_cannot_be_read_shows_a_message(invoicing, tmp_path):
    widget = invoicing.build()
    invoicing.picker.files.append(tmp_path / "no-existe.p12")
    widget.certificate_password.setText(PASSWORD)

    widget.load_certificate()

    assert widget.einvoice_message.text() == "No se pudo leer el archivo del certificado."
    assert invoicing.certificates(1).exists() is False


def test_removing_the_certificate_asks_and_declining_keeps_it(invoicing, rsa_key):
    save_certificate(invoicing, rsa_key)
    invoicing.confirm.answer = False
    widget = invoicing.build()

    widget.remove_certificate()

    assert len(invoicing.confirm.asked) == 1
    assert invoicing.certificates(1).exists()


def test_removing_the_certificate_after_confirming_clears_it(invoicing, rsa_key):
    save_certificate(invoicing, rsa_key)
    widget = invoicing.build()

    widget.remove_certificate()

    assert invoicing.certificates(1).exists() is False
    assert widget.certificate_holder.text() == "Sin certificado cargado"
    assert widget.remove_certificate_button.isHidden()


def test_the_certificate_cannot_be_removed_while_invoicing_is_enabled(invoicing, rsa_key):
    save_certificate(invoicing, rsa_key)
    invoicing.profile().update_einvoice(invoicing.owner, enabled=True)
    widget = invoicing.build()

    widget.remove_certificate()

    assert "desactivar la factura electrónica" in widget.einvoice_message.text()
    assert invoicing.certificates(1).exists()
