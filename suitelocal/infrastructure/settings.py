from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from suitelocal.domain.business import BusinessSettings
from suitelocal.infrastructure.database import Database

DEFAULT_PAYMENT_METHODS = ("cash", "transfer")


class BusinessSettingsRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def get(self, business_id: int) -> BusinessSettings:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT b.name, s.currency_symbol, s.low_stock_threshold,
                s.enabled_payment_methods, s.tax_rate_basis_points
                FROM businesses b
                LEFT JOIN business_settings s ON s.business_id = b.id
                WHERE b.id = ?
                """,
                (business_id,),
            ).fetchone()
        if row is None:
            raise ValueError("No se encontró la configuración del negocio.")
        configured_methods = row["enabled_payment_methods"] or ",".join(DEFAULT_PAYMENT_METHODS)
        methods = tuple(method for method in configured_methods.split(",") if method)
        return BusinessSettings(
            business_id,
            row["name"],
            row["currency_symbol"] or "$",
            row["low_stock_threshold"] if row["low_stock_threshold"] is not None else 3,
            methods,
            row["tax_rate_basis_points"] or 0,
        )

    def update(
        self,
        business_id: int,
        name: str,
        currency_symbol: str,
        low_stock_threshold: int,
        enabled_payment_methods: tuple[str, ...],
        tax_rate_percent: str | Decimal | int | float = 0,
    ) -> BusinessSettings:
        name = name.strip()
        currency_symbol = currency_symbol.strip()
        if not name or not currency_symbol:
            raise ValueError("El nombre y la moneda son obligatorios.")
        if low_stock_threshold < 0:
            raise ValueError("El umbral de reposición no puede ser negativo.")
        if "cash" not in enabled_payment_methods:
            raise ValueError("El efectivo debe estar habilitado.")
        try:
            rate = Decimal(str(tax_rate_percent).strip().replace(",", "."))
        except InvalidOperation as error:
            raise ValueError("El IVA debe ser un porcentaje válido.") from error
        if not rate.is_finite() or rate < 0 or rate > 100:
            raise ValueError("El IVA debe estar entre 0 y 100%.")
        if rate != rate.quantize(Decimal("0.01")):
            raise ValueError("El IVA admite como máximo dos decimales.")
        tax_rate_basis_points = int((rate * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        with self.database.connect() as connection:
            connection.execute("UPDATE businesses SET name = ? WHERE id = ?", (name, business_id))
            connection.execute(
                """
                INSERT INTO business_settings
                    (
                        business_id, currency_symbol, low_stock_threshold,
                        enabled_payment_methods, tax_rate_basis_points
                    )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(business_id) DO UPDATE SET
                    currency_symbol = excluded.currency_symbol,
                    low_stock_threshold = excluded.low_stock_threshold,
                    enabled_payment_methods = excluded.enabled_payment_methods,
                    tax_rate_basis_points = excluded.tax_rate_basis_points
                """,
                (
                    business_id,
                    currency_symbol,
                    low_stock_threshold,
                    ",".join(enabled_payment_methods),
                    tax_rate_basis_points,
                ),
            )
        return self.get(business_id)
