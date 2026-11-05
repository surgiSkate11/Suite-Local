import sqlite3

import pytest

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
