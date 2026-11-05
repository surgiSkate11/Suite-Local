import pytest

from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.settings import BusinessSettingsRepository


def test_business_settings_have_safe_defaults(tmp_path):
    database = Database(tmp_path / "settings.db")
    database.initialize()
    with database.connect() as connection:
        business_id = connection.execute(
            "INSERT INTO businesses (name) VALUES (?)", ("Tienda Sol",)
        ).lastrowid
    settings = BusinessSettingsRepository(database).get(business_id)

    assert settings.currency_symbol == "$"
    assert settings.low_stock_threshold == 3
    assert settings.enabled_payment_methods == ("cash", "transfer")


def test_business_settings_require_cash(tmp_path):
    database = Database(tmp_path / "settings.db")
    database.initialize()
    with database.connect() as connection:
        business_id = connection.execute(
            "INSERT INTO businesses (name) VALUES (?)", ("Tienda Sol",)
        ).lastrowid
    repository = BusinessSettingsRepository(database)

    with pytest.raises(ValueError, match="efectivo"):
        repository.update(business_id, "Tienda Sol", "$", 3, ("transfer",))


def test_business_settings_validate_and_store_tax_rate(tmp_path):
    database = Database(tmp_path / "settings-tax.db")
    database.initialize()
    with database.connect() as connection:
        business_id = connection.execute(
            "INSERT INTO businesses (name) VALUES (?)", ("Tienda Sol",)
        ).lastrowid
    repository = BusinessSettingsRepository(database)

    repository.update(business_id, "Tienda Sol", "$", 3, ("cash",), "5")

    assert repository.get(business_id).tax_rate_basis_points == 500


@pytest.mark.parametrize(
    "value",
    ["-1", "100,01", "19,999", "no válido", "19,5", "12"]
    + [
        "1e999999999",
        "-1e999999999",
        "1e-999999999",
        "NaN",
        "sNaN",
        "Infinity",
        "-Infinity",
        "inf",
    ],
)
def test_business_settings_reject_invalid_tax_rate(tmp_path, value):
    database = Database(tmp_path / "settings-invalid-tax.db")
    database.initialize()
    with database.connect() as connection:
        business_id = connection.execute(
            "INSERT INTO businesses (name) VALUES (?)", ("Tienda Sol",)
        ).lastrowid
    repository = BusinessSettingsRepository(database)

    with pytest.raises(ValueError, match="IVA"):
        repository.update(business_id, "Tienda Sol", "$", 3, ("cash",), value)
