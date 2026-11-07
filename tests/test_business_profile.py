import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from test_certificate_store import FakeProtector
from test_xades import make_p12

from suitelocal.application.auth import AuthService
from suitelocal.application.business_profile import BusinessProfileService
from suitelocal.application.categories import CategoryService
from suitelocal.domain.auth import Session
from suitelocal.domain.business import (
    BUSINESS_TYPES,
    MODULES,
    TAX_REGIMES,
    issues_electronic_invoices,
    profile_template,
    requires_ruc,
)
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import CategoryRepository
from suitelocal.infrastructure.settings import BusinessSettingsRepository
from suitelocal.infrastructure.sri.certificate_store import CertificateStore
from suitelocal.infrastructure.sri.xades import SigningError


@pytest.fixture
def env(tmp_path):
    database = Database(tmp_path / "profile.db")
    database.initialize()
    auth = AuthService(database)
    owner = Session(auth.setup_owner("Tienda Sol", "owner", "clave-segura", "clave-segura"))
    cashier = Session(auth.create_cashier(owner, "cajero", "clave-cajero", "clave-cajero"))
    settings = BusinessSettingsRepository(database)
    categories = CategoryRepository(database)
    service = BusinessProfileService(settings, categories)
    return database, owner, cashier, settings, categories, service


# -- defaults and labels ------------------------------------------------------------------


def test_new_business_has_a_neutral_profile(env):
    _, owner, _, settings, _, _ = env

    current = settings.get(owner.user.business_id)

    assert current.ruc == ""
    assert current.tax_regime == "sin_registro"
    assert current.business_type == "otro"
    assert current.enabled_modules == frozenset()
    assert current.decimal_separator == ","
    assert (current.address, current.phone, current.receipt_footer) == ("", "", "")


def test_regime_labels_are_in_spanish():
    assert TAX_REGIMES == {
        "sin_registro": "Sin registro en el SRI",
        "rimpe_popular": "RIMPE - Negocio popular",
        "rimpe_emprendedor": "RIMPE - Emprendedor",
        "general": "Régimen general",
    }


def test_known_business_types_and_modules():
    assert tuple(BUSINESS_TYPES) == (
        "tienda",
        "minimarket",
        "cafeteria",
        "restaurante",
        "ferreteria",
        "otro",
    )
    assert MODULES == frozenset({"mesas", "venta_por_peso", "codigo_barras", "categorias"})


@pytest.mark.parametrize(
    ("regime", "invoices", "ruc_required"),
    [
        ("sin_registro", False, False),
        ("rimpe_popular", False, False),
        ("rimpe_emprendedor", True, True),
        ("general", True, True),
    ],
)
def test_regime_rules(regime, invoices, ruc_required):
    assert issues_electronic_invoices(regime) is invoices
    assert requires_ruc(regime) is ruc_required


def test_regime_rules_reject_unknown_regime():
    with pytest.raises(ValueError, match="régimen"):
        issues_electronic_invoices("monotributo")


# -- RUC ----------------------------------------------------------------------------------


def test_valid_ruc_is_stored_trimmed(env):
    _, owner, _, settings, _, service = env

    service.update_profile(owner, ruc=" 1790012345001 ")

    assert settings.get(owner.user.business_id).ruc == "1790012345001"


@pytest.mark.parametrize(
    ("ruc", "message"),
    [
        ("123", "13 dígitos"),
        ("17900123450011", "13 dígitos"),
        ("17900123450ab", "13 dígitos"),
        ("1790012345 01", "13 dígitos"),
        ("１７９００１２３４５００１", "13 dígitos"),
        ("1790012345000", "000"),
    ],
)
def test_invalid_ruc_is_rejected_and_leaves_settings_unchanged(env, ruc, message):
    _, owner, _, settings, _, service = env
    service.update_profile(owner, ruc="1790012345001", address="Av. Amazonas")
    before = settings.get(owner.user.business_id)

    with pytest.raises(ValueError, match=message):
        service.update_profile(owner, ruc=ruc, address="Otra dirección")

    assert settings.get(owner.user.business_id) == before


def test_ruc_can_be_cleared_when_the_regime_does_not_require_it(env):
    _, owner, _, settings, _, service = env
    service.update_profile(owner, ruc="1790012345001")

    service.update_profile(owner, ruc="")

    assert settings.get(owner.user.business_id).ruc == ""


@pytest.mark.parametrize("regime", ["general", "rimpe_emprendedor"])
def test_ruc_is_required_for_regimes_that_issue_invoices(env, regime):
    _, owner, _, settings, _, service = env
    before = settings.get(owner.user.business_id)

    with pytest.raises(ValueError, match="RUC"):
        service.update_profile(owner, tax_regime=regime)

    assert settings.get(owner.user.business_id) == before

    service.update_profile(owner, tax_regime=regime, ruc="1790012345001")
    assert settings.get(owner.user.business_id).tax_regime == regime
    with pytest.raises(ValueError, match="RUC"):
        service.update_profile(owner, ruc="")
    assert settings.get(owner.user.business_id).ruc == "1790012345001"


@pytest.mark.parametrize("regime", ["sin_registro", "rimpe_popular"])
def test_ruc_is_optional_for_the_other_regimes(env, regime):
    _, owner, _, settings, _, service = env

    service.update_profile(owner, tax_regime=regime)
    assert settings.get(owner.user.business_id).tax_regime == regime
    assert settings.get(owner.user.business_id).ruc == ""

    service.update_profile(owner, ruc="1790012345001")
    assert settings.get(owner.user.business_id).ruc == "1790012345001"


# -- other fields -------------------------------------------------------------------------


def test_profile_fields_are_stored_and_trimmed(env):
    _, owner, _, settings, _, service = env

    service.update_profile(
        owner,
        tax_regime="rimpe_popular",
        business_type="cafeteria",
        enabled_modules=["mesas", "categorias"],
        decimal_separator=".",
        address="  Av. Amazonas N24 y Colón  ",
        phone=" 0991234567 ",
        receipt_footer="  Gracias por su compra  ",
    )

    current = settings.get(owner.user.business_id)
    assert current.tax_regime == "rimpe_popular"
    assert current.business_type == "cafeteria"
    assert current.enabled_modules == frozenset({"mesas", "categorias"})
    assert current.decimal_separator == "."
    assert current.address == "Av. Amazonas N24 y Colón"
    assert current.phone == "0991234567"
    assert current.receipt_footer == "Gracias por su compra"


def test_modules_are_stored_as_comma_separated_text(env):
    database, owner, _, settings, _, service = env

    service.update_profile(owner, enabled_modules={"mesas", "codigo_barras"})

    with database.connect() as connection:
        stored = connection.execute("SELECT enabled_modules FROM business_settings").fetchone()[0]
    assert stored == "codigo_barras,mesas"
    assert settings.get(owner.user.business_id).enabled_modules == {"codigo_barras", "mesas"}


def test_omitted_fields_keep_their_value(env):
    _, owner, _, settings, _, service = env
    service.update_profile(owner, address="Calle 1", decimal_separator=".")

    service.update_profile(owner, phone="022345678")

    current = settings.get(owner.user.business_id)
    assert (current.address, current.decimal_separator, current.phone) == (
        "Calle 1",
        ".",
        "022345678",
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("tax_regime", "monotributo", "régimen"),
        ("business_type", "banco", "tipo de negocio"),
        ("enabled_modules", ["mesas", "inventado"], "inventado"),
        ("decimal_separator", ";", "separador"),
        ("decimal_separator", "", "separador"),
        ("address", "x" * 201, "dirección"),
        ("phone", "1" * 31, "teléfono"),
        ("receipt_footer", "x" * 301, "pie"),
    ],
)
def test_invalid_values_are_rejected_and_leave_settings_unchanged(env, field, value, message):
    _, owner, _, settings, _, service = env
    service.update_profile(owner, ruc="1790012345001", business_type="tienda")
    before = settings.get(owner.user.business_id)

    with pytest.raises(ValueError, match=message):
        service.update_profile(owner, **{"address": "Cambio parcial", field: value})

    assert settings.get(owner.user.business_id) == before


def test_length_limits_accept_the_exact_maximum(env):
    _, owner, _, settings, _, service = env

    service.update_profile(owner, address="a" * 200, phone="1" * 30, receipt_footer="f" * 300)

    current = settings.get(owner.user.business_id)
    assert (len(current.address), len(current.phone), len(current.receipt_footer)) == (200, 30, 300)


def test_general_settings_update_keeps_the_profile(env):
    _, owner, _, settings, _, service = env
    service.update_profile(owner, ruc="1790012345001", tax_regime="general")

    service.update_settings(owner, "Tienda Sol 2", "$", 5, ("cash",), "5")

    current = settings.get(owner.user.business_id)
    assert (current.name, current.low_stock_threshold) == ("Tienda Sol 2", 5)
    assert current.tax_rate_basis_points == 500
    assert (current.ruc, current.tax_regime) == ("1790012345001", "general")


# -- owner only ---------------------------------------------------------------------------


def test_cashier_cannot_write_settings_or_profile(env):
    _, owner, cashier, settings, _, service = env
    before = settings.get(owner.user.business_id)

    with pytest.raises(PermissionError, match="Solo el dueño"):
        service.update_profile(cashier, address="Calle falsa 123")
    with pytest.raises(PermissionError, match="Solo el dueño"):
        service.update_settings(cashier, "Otro", "$", 3, ("cash",), "15")
    with pytest.raises(PermissionError, match="Solo el dueño"):
        service.apply_template(cashier, "cafeteria")

    assert settings.get(owner.user.business_id) == before


def test_cashier_can_read_the_profile(env):
    _, owner, cashier, _, _, service = env
    service.update_profile(owner, business_type="tienda")

    assert service.get(cashier).business_type == "tienda"


# -- templates ----------------------------------------------------------------------------


def test_cafeteria_and_restaurante_templates():
    for business_type in ("cafeteria", "restaurante"):
        template = profile_template(business_type)
        assert template.modules == frozenset({"mesas", "categorias"})
        assert template.categories == ("Café", "Bebidas", "Desayunos", "Postres")


def test_tienda_and_minimarket_templates():
    for business_type in ("tienda", "minimarket"):
        template = profile_template(business_type)
        assert template.modules == frozenset({"codigo_barras", "categorias"})
        assert template.categories == ("Abarrotes", "Bebidas", "Lácteos", "Limpieza", "Snacks")


def test_ferreteria_template_sells_by_weight():
    template = profile_template("ferreteria")

    assert template.modules == frozenset({"codigo_barras", "categorias", "venta_por_peso"})
    assert template.categories


def test_every_type_has_a_template_made_of_known_modules():
    for business_type in BUSINESS_TYPES:
        template = profile_template(business_type)
        assert template.modules <= MODULES
        assert len(set(template.categories)) == len(template.categories)


def test_unknown_type_has_no_template():
    with pytest.raises(ValueError, match="tipo de negocio"):
        profile_template("banco")


def test_changing_the_type_never_applies_the_template_by_itself(env):
    _, owner, _, settings, categories, service = env

    service.update_profile(owner, business_type="cafeteria")

    current = settings.get(owner.user.business_id)
    assert current.business_type == "cafeteria"
    assert current.enabled_modules == frozenset()
    assert categories.list(owner.user.business_id) == []


def test_applying_a_template_sets_type_modules_and_categories(env):
    _, owner, _, settings, categories, service = env

    result = service.apply_template(owner, "cafeteria")

    assert result.business_type == "cafeteria"
    assert result.enabled_modules == frozenset({"mesas", "categorias"})
    assert settings.get(owner.user.business_id) == result
    names = [category.name for category in categories.list(owner.user.business_id)]
    assert names == ["Bebidas", "Café", "Desayunos", "Postres"]


def test_applying_a_template_twice_does_not_duplicate_or_resurrect_categories(env):
    _, owner, _, _, categories, service = env
    business_id = owner.user.business_id
    service.apply_template(owner, "tienda")
    custom = CategoryService(categories)
    snacks = next(c for c in categories.list(business_id) if c.name == "Snacks")
    custom.set_active(owner, snacks.id, False)
    custom.create(owner, "Mis ofertas")

    service.apply_template(owner, "tienda")

    all_names = [c.name for c in categories.list(business_id, include_inactive=True)]
    assert len(all_names) == 6
    assert set(all_names) == {
        "Abarrotes",
        "Bebidas",
        "Lácteos",
        "Limpieza",
        "Mis ofertas",
        "Snacks",
    }
    assert "Snacks" not in [c.name for c in categories.list(business_id)]


def test_applying_an_unknown_template_changes_nothing(env):
    _, owner, _, settings, categories, service = env
    before = settings.get(owner.user.business_id)

    with pytest.raises(ValueError, match="tipo de negocio"):
        service.apply_template(owner, "banco")

    assert settings.get(owner.user.business_id) == before
    assert categories.list(owner.user.business_id) == []


# -- migration ----------------------------------------------------------------------------


def old_settings_database(path, extra_columns: str = "", extra_values: str = "") -> Database:
    connection = sqlite3.connect(path)
    connection.executescript(
        f"""
        CREATE TABLE businesses (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE business_settings (
            business_id INTEGER PRIMARY KEY REFERENCES businesses(id),
            currency_symbol TEXT NOT NULL DEFAULT '$',
            low_stock_threshold INTEGER NOT NULL DEFAULT 3,
            enabled_payment_methods TEXT NOT NULL DEFAULT 'cash,transfer',
            tax_rate_basis_points INTEGER NOT NULL DEFAULT 0{extra_columns}
        );
        INSERT INTO businesses (id, name) VALUES (1, 'Tienda Sol');
        INSERT INTO business_settings (business_id{", ruc" if extra_columns else ""})
            VALUES (1{extra_values});
        """
    )
    connection.commit()
    connection.close()
    return Database(path)


def test_migrated_business_without_ruc_is_sin_registro(tmp_path):
    database = old_settings_database(tmp_path / "old.db")

    database.initialize()
    database.initialize()

    current = BusinessSettingsRepository(database).get(1)
    assert current.tax_regime == "sin_registro"
    assert current.ruc == ""
    assert current.decimal_separator == ","


def test_migrated_business_that_already_has_a_ruc_stays_general(tmp_path):
    database = old_settings_database(
        tmp_path / "old.db", ", ruc TEXT NOT NULL DEFAULT ''", ", '1790012345001'"
    )

    database.initialize()
    database.initialize()

    current = BusinessSettingsRepository(database).get(1)
    assert (current.tax_regime, current.ruc) == ("general", "1790012345001")


def test_applying_a_template_is_atomic_when_adding_categories_fails(env):
    database, owner, _, settings, categories, service = env
    business_id = owner.user.business_id
    before = settings.get(business_id)
    with database.connect() as connection:
        connection.execute(
            "CREATE TRIGGER fail_category BEFORE INSERT ON categories "
            "WHEN NEW.name = 'Postres' BEGIN SELECT RAISE(ABORT, 'boom'); END"
        )

    with pytest.raises(ValueError):
        service.apply_template(owner, "cafeteria")

    assert settings.get(business_id) == before
    assert categories.list(business_id, include_inactive=True) == []


# -- first-run setup -------------------------------------------------------------------------


@pytest.fixture
def fresh(tmp_path):
    database = Database(tmp_path / "fresh.db")
    database.initialize()
    return database, AuthService(database)


def test_setup_stores_the_type_and_regime_and_applies_the_template(fresh):
    database, auth = fresh

    owner = auth.setup_owner(
        "Café Sol",
        "dueno",
        "clave-segura",
        "clave-segura",
        business_type="cafeteria",
        tax_regime="rimpe_popular",
    )

    profile = BusinessSettingsRepository(database).get(owner.business_id)
    assert (profile.business_type, profile.tax_regime, profile.ruc) == (
        "cafeteria",
        "rimpe_popular",
        "",
    )
    assert profile.enabled_modules == frozenset({"mesas", "categorias"})
    names = [c.name for c in CategoryRepository(database).list(owner.business_id)]
    assert names == ["Bebidas", "Café", "Desayunos", "Postres"]


def test_setup_without_a_type_keeps_the_neutral_profile(fresh):
    database, auth = fresh

    owner = auth.setup_owner("Tienda", "dueno", "clave-segura", "clave-segura")

    profile = BusinessSettingsRepository(database).get(owner.business_id)
    assert (profile.business_type, profile.tax_regime) == ("otro", "sin_registro")
    assert profile.enabled_modules == frozenset()
    assert CategoryRepository(database).list(owner.business_id) == []


def test_setup_stores_a_ruc_for_a_regime_that_requires_it(fresh):
    database, auth = fresh

    owner = auth.setup_owner(
        "Ferretería Sol",
        "dueno",
        "clave-segura",
        "clave-segura",
        business_type="ferreteria",
        tax_regime="general",
        ruc=" 1790012345001 ",
    )

    profile = BusinessSettingsRepository(database).get(owner.business_id)
    assert (profile.ruc, profile.tax_regime) == ("1790012345001", "general")


@pytest.mark.parametrize(
    ("regime", "ruc", "message"),
    [
        ("general", "", "El RUC es obligatorio para este régimen tributario."),
        ("rimpe_emprendedor", "", "El RUC es obligatorio para este régimen tributario."),
        ("general", "123", "El RUC debe tener exactamente 13 dígitos."),
        ("nada", "", "El régimen tributario no es válido."),
    ],
)
def test_invalid_setup_creates_nothing(fresh, regime, ruc, message):
    database, auth = fresh

    with pytest.raises(ValueError, match=message):
        auth.setup_owner(
            "Tienda",
            "dueno",
            "clave-segura",
            "clave-segura",
            business_type="tienda",
            tax_regime=regime,
            ruc=ruc,
        )

    assert not auth.has_users()
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM businesses").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 0


# -- receipt paper and printer ------------------------------------------------------------


def test_new_business_prints_on_80_mm_paper_on_the_default_printer(env):
    _, owner, _, settings, _, _ = env

    current = settings.get(owner.user.business_id)

    assert (current.receipt_paper_mm, current.printer_name) == (80, "")


def test_owner_saves_the_paper_width_and_the_printer(env):
    _, owner, _, settings, _, service = env

    saved = service.update_profile(owner, receipt_paper_mm=58, printer_name="  XP-58  ")

    assert (saved.receipt_paper_mm, saved.printer_name) == (58, "XP-58")
    assert settings.get(owner.user.business_id) == saved
    # Leaving both out keeps what is stored; an empty printer goes back to the default one.
    assert service.update_profile(owner, address="Calle 1").receipt_paper_mm == 58
    assert service.update_profile(owner, printer_name="").printer_name == ""


@pytest.mark.parametrize("paper", [0, 57, 59, 100, -80, True])
def test_invalid_paper_widths_are_rejected_and_nothing_changes(env, paper):
    _, owner, _, settings, _, service = env
    before = settings.get(owner.user.business_id)

    with pytest.raises(ValueError, match="El ancho del papel debe ser 58 mm u 80 mm."):
        service.update_profile(owner, receipt_paper_mm=paper, address="Cambiada")

    assert settings.get(owner.user.business_id) == before


def test_an_overlong_printer_name_is_rejected(env):
    _, owner, _, settings, _, service = env
    before = settings.get(owner.user.business_id)

    with pytest.raises(ValueError, match="no puede superar 200 caracteres"):
        service.update_profile(owner, printer_name="P" * 201)

    assert settings.get(owner.user.business_id) == before


def test_only_the_owner_changes_the_paper_and_the_printer(env):
    _, owner, cashier, settings, _, service = env

    with pytest.raises(PermissionError):
        service.update_profile(cashier, receipt_paper_mm=58, printer_name="XP-58")

    current = settings.get(owner.user.business_id)
    assert (current.receipt_paper_mm, current.printer_name) == (80, "")


def test_the_database_itself_refuses_a_paper_width_that_is_not_58_or_80(env):
    database, owner, *_ = env

    with pytest.raises(sqlite3.IntegrityError), database.connect() as connection:
        connection.execute(
            "UPDATE business_settings SET receipt_paper_mm = 70 WHERE business_id = ?",
            (owner.user.business_id,),
        )


def test_migrated_business_gets_80_mm_and_the_default_printer_once(tmp_path):
    database = old_settings_database(tmp_path / "old.db")

    database.initialize()
    BusinessSettingsRepository(database).update_profile(
        1, receipt_paper_mm=58, printer_name="XP-58"
    )
    database.initialize()

    current = BusinessSettingsRepository(database).get(1)
    assert (current.receipt_paper_mm, current.printer_name) == (58, "XP-58")
    fresh = old_settings_database(tmp_path / "old2.db")
    fresh.initialize()
    assert BusinessSettingsRepository(fresh).get(1).receipt_paper_mm == 80
    with fresh.connect() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute("UPDATE business_settings SET receipt_paper_mm = 70")


# -- electronic invoicing settings ---------------------------------------------------------

NOT_INVOICING = "El régimen tributario de este negocio no emite facturas electrónicas."
NEEDS_RUC = "Para facturar se necesita un RUC de 13 dígitos que termine en 001."
NEEDS_CERTIFICATE = (
    "Para activar la factura electrónica primero se debe cargar el certificado de firma (.p12)."
)
CERTIFICATE_PASSWORD = "clave-del-p12"


@pytest.fixture(scope="module")
def signing_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def invoicing(env, tmp_path):
    _, owner, cashier, settings, categories, _ = env
    service = BusinessProfileService(
        settings,
        categories,
        lambda business_id: CertificateStore.for_business(
            tmp_path / "data", business_id, FakeProtector()
        ),
    )
    return service, owner, cashier, settings


def make_emprendedor(service, owner, ruc="1790012345001") -> None:
    service.update_profile(owner, tax_regime="rimpe_emprendedor", ruc=ruc)


def einvoice_fields(current) -> tuple:
    return (
        current.einvoice_enabled,
        current.sri_environment,
        current.establishment,
        current.emission_point,
        current.obligado_contabilidad,
        current.trade_name,
    )


def p12_for(key, not_after: datetime | None = None, password: str = CERTIFICATE_PASSWORD) -> bytes:
    return make_p12(key, password.encode(), not_after=not_after)


def test_a_new_business_has_electronic_invoicing_off_with_the_pruebas_defaults(env):
    _, owner, _, settings, _, _ = env

    current = settings.get(owner.user.business_id)

    assert einvoice_fields(current) == (False, "pruebas", "001", "001", False, "")


def test_electronic_invoicing_columns_are_added_to_an_old_database_once(tmp_path):
    database = old_settings_database(tmp_path / "old.db")

    database.initialize()
    BusinessSettingsRepository(database).update_einvoice(
        1, establishment="002", trade_name="Sol", enabled=False
    )
    database.initialize()

    current = BusinessSettingsRepository(database).get(1)
    assert einvoice_fields(current) == (False, "pruebas", "002", "001", False, "Sol")
    assert current.name == "Tienda Sol"


def test_the_database_itself_refuses_an_unknown_sri_environment(env):
    database, *_ = env

    with pytest.raises(sqlite3.IntegrityError), database.connect() as connection:
        connection.execute("UPDATE business_settings SET sri_environment = 'otro'")


def test_the_owner_configures_the_invoice_numbering_and_issuer_data(invoicing):
    service, owner, _, settings = invoicing

    updated = service.update_einvoice(
        owner,
        sri_environment="produccion",
        establishment="002",
        emission_point="015",
        obligado_contabilidad=True,
        trade_name="  La Esquina  ",
    )

    assert einvoice_fields(updated) == (False, "produccion", "002", "015", True, "La Esquina")
    assert settings.get(owner.user.business_id) == updated


def test_omitted_fields_keep_their_current_value(invoicing):
    service, owner, _, _ = invoicing
    service.update_einvoice(owner, establishment="004", trade_name="Sol")

    updated = service.update_einvoice(owner, emission_point="009")

    assert einvoice_fields(updated) == (False, "pruebas", "004", "009", False, "Sol")


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"sri_environment": "otro"}, "El ambiente del SRI debe ser pruebas o producción."),
        ({"sri_environment": "1"}, "El ambiente del SRI debe ser pruebas o producción."),
        ({"establishment": "1"}, "El establecimiento debe tener exactamente 3 dígitos."),
        ({"establishment": "0001"}, "El establecimiento debe tener exactamente 3 dígitos."),
        ({"establishment": "ab1"}, "El establecimiento debe tener exactamente 3 dígitos."),
        ({"establishment": "000"}, "El establecimiento debe estar entre 001 y 999."),
        ({"emission_point": "12"}, "El punto de emisión debe tener exactamente 3 dígitos."),
        ({"emission_point": "000"}, "El punto de emisión debe estar entre 001 y 999."),
        ({"trade_name": "x" * 301}, "El nombre comercial no puede superar 300 caracteres."),
    ],
)
def test_invalid_invoicing_values_are_rejected_and_nothing_changes(invoicing, changes, message):
    service, owner, _, settings = invoicing
    before = settings.get(owner.user.business_id)

    with pytest.raises(ValueError) as error:
        service.update_einvoice(owner, obligado_contabilidad=True, **changes)

    assert str(error.value) == message
    assert settings.get(owner.user.business_id) == before


def test_enabling_requires_a_regime_that_issues_electronic_invoices(invoicing, signing_key):
    service, owner, _, settings = invoicing
    service.save_certificate(owner, p12_for(signing_key), CERTIFICATE_PASSWORD)
    service.update_profile(owner, tax_regime="rimpe_popular")
    before = settings.get(owner.user.business_id)

    with pytest.raises(ValueError) as error:
        service.update_einvoice(owner, enabled=True, establishment="005")

    assert str(error.value) == NOT_INVOICING
    assert settings.get(owner.user.business_id) == before


def test_enabling_requires_a_ruc_that_ends_in_001(invoicing, signing_key):
    service, owner, _, settings = invoicing
    service.save_certificate(owner, p12_for(signing_key), CERTIFICATE_PASSWORD)
    make_emprendedor(service, owner, ruc="1790012345002")
    before = settings.get(owner.user.business_id)

    with pytest.raises(ValueError) as error:
        service.update_einvoice(owner, enabled=True)

    assert str(error.value) == NEEDS_RUC
    assert settings.get(owner.user.business_id) == before


def test_enabling_requires_a_stored_certificate(invoicing):
    service, owner, _, settings = invoicing
    make_emprendedor(service, owner)
    before = settings.get(owner.user.business_id)

    with pytest.raises(ValueError) as error:
        service.update_einvoice(owner, enabled=True, trade_name="Sol")

    assert str(error.value) == NEEDS_CERTIFICATE
    assert settings.get(owner.user.business_id) == before


def test_enabling_without_a_certificate_store_configured_is_refused(env):
    _, owner, _, settings, _, service = env
    make_emprendedor(service, owner)

    with pytest.raises(ValueError) as error:
        service.update_einvoice(owner, enabled=True)

    assert str(error.value) == NEEDS_CERTIFICATE
    assert settings.get(owner.user.business_id).einvoice_enabled is False


@pytest.mark.parametrize("regime", ["rimpe_emprendedor", "general"])
def test_enabling_works_with_regime_ruc_and_certificate_and_can_be_switched_off(
    invoicing, signing_key, regime
):
    service, owner, _, _ = invoicing
    service.update_profile(owner, tax_regime=regime, ruc="1790012345001")
    service.save_certificate(owner, p12_for(signing_key), CERTIFICATE_PASSWORD)

    enabled = service.update_einvoice(owner, enabled=True)
    disabled = service.update_einvoice(owner, enabled=False)

    assert enabled.einvoice_enabled is True
    assert disabled.einvoice_enabled is False


def test_changing_other_fields_while_enabled_does_not_ask_again_for_the_certificate(
    invoicing, signing_key
):
    service, owner, _, _ = invoicing
    make_emprendedor(service, owner)
    service.save_certificate(owner, p12_for(signing_key), CERTIFICATE_PASSWORD)
    service.update_einvoice(owner, enabled=True)
    service.certificates(owner.user.business_id).clear()

    updated = service.update_einvoice(owner, trade_name="Nuevo nombre")

    assert (updated.einvoice_enabled, updated.trade_name) == (True, "Nuevo nombre")


def test_the_regime_cannot_change_to_one_that_does_not_invoice_while_enabled(
    invoicing, signing_key
):
    service, owner, _, settings = invoicing
    make_emprendedor(service, owner)
    service.save_certificate(owner, p12_for(signing_key), CERTIFICATE_PASSWORD)
    service.update_einvoice(owner, enabled=True)
    before = settings.get(owner.user.business_id)

    with pytest.raises(ValueError) as error:
        service.update_profile(owner, tax_regime="rimpe_popular", address="Otra calle")

    assert str(error.value) == (
        "Primero se debe desactivar la factura electrónica "
        "para cambiar a un régimen que no la emite."
    )
    assert settings.get(owner.user.business_id) == before
    assert service.update_profile(owner, tax_regime="general").tax_regime == "general"


def test_only_the_owner_can_change_invoicing_settings_or_the_certificate(invoicing, signing_key):
    service, owner, cashier, settings = invoicing
    before = settings.get(owner.user.business_id)

    with pytest.raises(PermissionError, match="Solo el dueño"):
        service.update_einvoice(cashier, establishment="009")
    with pytest.raises(PermissionError, match="Solo el dueño"):
        service.save_certificate(cashier, p12_for(signing_key), CERTIFICATE_PASSWORD)
    with pytest.raises(PermissionError, match="Solo el dueño"):
        service.remove_certificate(cashier)
    with pytest.raises(PermissionError, match="Solo el dueño"):
        service.certificate_info(cashier)

    assert settings.get(owner.user.business_id) == before
    assert service.certificate_info(owner) is None


def test_the_certificate_is_saved_through_the_service_and_described_without_secrets(
    invoicing, signing_key
):
    service, owner, _, _ = invoicing

    service.save_certificate(owner, p12_for(signing_key), CERTIFICATE_PASSWORD)

    info = service.certificate_info(owner)
    assert info is not None
    assert info.subject == "Firma de prueba"
    assert CERTIFICATE_PASSWORD not in repr(info)


def test_a_wrong_password_or_expired_certificate_is_not_stored(invoicing, signing_key):
    service, owner, _, _ = invoicing
    expired = p12_for(signing_key, datetime.now(UTC) - timedelta(days=1))

    with pytest.raises(SigningError):
        service.save_certificate(owner, p12_for(signing_key), "incorrecta")
    with pytest.raises(SigningError):
        service.save_certificate(owner, expired, CERTIFICATE_PASSWORD)

    assert service.certificate_info(owner) is None


def test_the_certificate_can_be_removed_only_while_invoicing_is_off(invoicing, signing_key):
    service, owner, _, _ = invoicing
    make_emprendedor(service, owner)
    service.save_certificate(owner, p12_for(signing_key), CERTIFICATE_PASSWORD)
    service.update_einvoice(owner, enabled=True)

    with pytest.raises(ValueError) as error:
        service.remove_certificate(owner)
    assert str(error.value) == (
        "Primero se debe desactivar la factura electrónica para quitar el certificado."
    )
    assert service.certificate_info(owner) is not None

    service.update_einvoice(owner, enabled=False)
    service.remove_certificate(owner)
    assert service.certificate_info(owner) is None


def test_the_certificate_of_one_business_is_not_visible_to_another(invoicing, env, signing_key):
    service, owner, _, _ = invoicing
    database = env[0]
    service.save_certificate(owner, p12_for(signing_key), CERTIFICATE_PASSWORD)
    with database.connect() as connection:
        business_id = connection.execute("INSERT INTO businesses (name) VALUES ('Otra')").lastrowid
    assert business_id is not None

    assert service.certificates(business_id).exists() is False
    assert service.certificates(owner.user.business_id).exists() is True
