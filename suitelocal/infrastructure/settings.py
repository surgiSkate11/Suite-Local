import sqlite3
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation

from suitelocal.domain.business import (
    ADDRESS_MAX_LENGTH,
    DEFAULT_BUSINESS_TYPE,
    DEFAULT_RECEIPT_PAPER_MM,
    DEFAULT_SERIES_CODE,
    DEFAULT_SRI_ENVIRONMENT,
    DEFAULT_TAX_REGIME,
    PHONE_MAX_LENGTH,
    PRINTER_NAME_MAX_LENGTH,
    RECEIPT_FOOTER_MAX_LENGTH,
    TRADE_NAME_MAX_LENGTH,
    BusinessSettings,
    format_modules,
    issues_electronic_invoices,
    normalize_ruc,
    normalize_text,
    parse_modules,
    validate_business_type,
    validate_decimal_separator,
    validate_einvoice_activation,
    validate_receipt_paper_mm,
    validate_ruc_for_regime,
    validate_series_code,
    validate_sri_environment,
    validate_tax_regime,
)
from suitelocal.domain.tax import (
    DEFAULT_TAX_RATE_BASIS_POINTS,
    TAX_RATES_BASIS_POINTS,
    validate_tax_rate,
)
from suitelocal.infrastructure.database import Database

DEFAULT_PAYMENT_METHODS = ("cash", "transfer")


def _parse_tax_rate_percent(value: str | Decimal | int | float) -> int:
    """Turn "15", "5,0" or 0 into basis points, accepting only the legal Ecuadorian rates."""
    try:
        rate = Decimal(str(value).strip().replace(",", "."))
    except InvalidOperation as error:
        raise ValueError("El IVA debe ser un porcentaje válido.") from error
    # Only exact comparisons: arithmetic on "1e999999999" overflows and "1e-999999999" rounds
    # to zero. Basis points / 100 is the percentage, e.g. 1500 -> 15.
    if rate.is_finite():
        for allowed in TAX_RATES_BASIS_POINTS:
            if rate == Decimal(allowed) / 100:
                return validate_tax_rate(allowed)
    raise ValueError("El IVA debe ser 15 %, 5 % o 0 %.")


class BusinessSettingsRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def get(self, business_id: int) -> BusinessSettings:
        with self.database.connect() as connection:
            return self._load(connection, business_id)

    @staticmethod
    def _load(connection: sqlite3.Connection, business_id: int) -> BusinessSettings:
        row = connection.execute(
            """
                SELECT b.name, s.currency_symbol, s.low_stock_threshold,
                s.enabled_payment_methods, s.tax_rate_basis_points, s.ruc, s.tax_regime,
                s.business_type, s.enabled_modules, s.decimal_separator, s.address, s.phone,
                s.receipt_footer, s.receipt_paper_mm, s.printer_name, s.einvoice_enabled,
                s.sri_environment, s.establishment, s.emission_point, s.obligado_contabilidad,
                s.trade_name
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
        tax_rate = row["tax_rate_basis_points"]
        return BusinessSettings(
            business_id,
            row["name"],
            row["currency_symbol"] or "$",
            row["low_stock_threshold"] if row["low_stock_threshold"] is not None else 3,
            methods,
            DEFAULT_TAX_RATE_BASIS_POINTS if tax_rate is None else tax_rate,
            row["ruc"] or "",
            row["tax_regime"] or DEFAULT_TAX_REGIME,
            row["business_type"] or DEFAULT_BUSINESS_TYPE,
            parse_modules(row["enabled_modules"] or ""),
            row["decimal_separator"] or ",",
            row["address"] or "",
            row["phone"] or "",
            row["receipt_footer"] or "",
            row["receipt_paper_mm"] or DEFAULT_RECEIPT_PAPER_MM,
            row["printer_name"] or "",
            bool(row["einvoice_enabled"]),
            row["sri_environment"] or DEFAULT_SRI_ENVIRONMENT,
            row["establishment"] or DEFAULT_SERIES_CODE,
            row["emission_point"] or DEFAULT_SERIES_CODE,
            bool(row["obligado_contabilidad"]),
            row["trade_name"] or "",
        )

    def update(
        self,
        business_id: int,
        name: str,
        currency_symbol: str,
        low_stock_threshold: int,
        enabled_payment_methods: tuple[str, ...],
        tax_rate_percent: str | Decimal | int | float | None = None,
    ) -> BusinessSettings:
        """Update the general settings.

        The IVA rate is the default for NEW products only and keeps its value when omitted.
        """
        name = name.strip()
        currency_symbol = currency_symbol.strip()
        if not name or not currency_symbol:
            raise ValueError("El nombre y la moneda son obligatorios.")
        if low_stock_threshold < 0:
            raise ValueError("El umbral de reposición no puede ser negativo.")
        if "cash" not in enabled_payment_methods:
            raise ValueError("El efectivo debe estar habilitado.")
        if tax_rate_percent is None:
            tax_rate_basis_points = self.get(business_id).tax_rate_basis_points
        else:
            tax_rate_basis_points = _parse_tax_rate_percent(tax_rate_percent)
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

    def update_profile(
        self,
        business_id: int,
        *,
        ruc: str | None = None,
        tax_regime: str | None = None,
        business_type: str | None = None,
        enabled_modules: Iterable[str] | None = None,
        decimal_separator: str | None = None,
        address: str | None = None,
        phone: str | None = None,
        receipt_footer: str | None = None,
        receipt_paper_mm: int | None = None,
        printer_name: str | None = None,
    ) -> BusinessSettings:
        """Change the given profile fields (None keeps the current value) in one transaction.

        Everything is validated against the resulting profile before anything is written.
        """
        with self.database.connect() as connection:
            self.write_profile(
                connection,
                business_id,
                ruc=ruc,
                tax_regime=tax_regime,
                business_type=business_type,
                enabled_modules=enabled_modules,
                decimal_separator=decimal_separator,
                address=address,
                phone=phone,
                receipt_footer=receipt_footer,
                receipt_paper_mm=receipt_paper_mm,
                printer_name=printer_name,
            )
        return self.get(business_id)

    def write_profile(
        self,
        connection: sqlite3.Connection,
        business_id: int,
        *,
        ruc: str | None = None,
        tax_regime: str | None = None,
        business_type: str | None = None,
        enabled_modules: Iterable[str] | None = None,
        decimal_separator: str | None = None,
        address: str | None = None,
        phone: str | None = None,
        receipt_footer: str | None = None,
        receipt_paper_mm: int | None = None,
        printer_name: str | None = None,
    ) -> None:
        """Validate and write profile fields on the caller's connection and transaction."""
        current = self._load(connection, business_id)
        new_ruc = current.ruc if ruc is None else normalize_ruc(ruc)
        new_regime = current.tax_regime if tax_regime is None else validate_tax_regime(tax_regime)
        validate_ruc_for_regime(new_ruc, new_regime)
        if current.einvoice_enabled and not issues_electronic_invoices(new_regime):
            raise ValueError(
                "Primero se debe desactivar la factura electrónica "
                "para cambiar a un régimen que no la emite."
            )
        new_type = current.business_type if business_type is None else business_type
        validate_business_type(new_type)
        new_modules = (
            current.enabled_modules if enabled_modules is None else parse_modules(enabled_modules)
        )
        new_separator = (
            current.decimal_separator
            if decimal_separator is None
            else validate_decimal_separator(decimal_separator)
        )
        new_address = (
            current.address
            if address is None
            else normalize_text(address, "La dirección", ADDRESS_MAX_LENGTH)
        )
        new_phone = (
            current.phone
            if phone is None
            else normalize_text(phone, "El teléfono", PHONE_MAX_LENGTH)
        )
        new_footer = (
            current.receipt_footer
            if receipt_footer is None
            else normalize_text(receipt_footer, "El pie del comprobante", RECEIPT_FOOTER_MAX_LENGTH)
        )
        new_paper = (
            current.receipt_paper_mm
            if receipt_paper_mm is None
            else validate_receipt_paper_mm(receipt_paper_mm)
        )
        new_printer = (
            current.printer_name
            if printer_name is None
            else normalize_text(printer_name, "El nombre de la impresora", PRINTER_NAME_MAX_LENGTH)
        )
        connection.execute(
            "INSERT OR IGNORE INTO business_settings (business_id) VALUES (?)", (business_id,)
        )
        connection.execute(
            """
            UPDATE business_settings
            SET ruc = ?, tax_regime = ?, business_type = ?, enabled_modules = ?,
                decimal_separator = ?, address = ?, phone = ?, receipt_footer = ?,
                receipt_paper_mm = ?, printer_name = ?
            WHERE business_id = ?
            """,
            (
                new_ruc,
                new_regime,
                new_type,
                format_modules(new_modules),
                new_separator,
                new_address,
                new_phone,
                new_footer,
                new_paper,
                new_printer,
                business_id,
            ),
        )

    def update_einvoice(
        self,
        business_id: int,
        *,
        enabled: bool | None = None,
        sri_environment: str | None = None,
        establishment: str | None = None,
        emission_point: str | None = None,
        obligado_contabilidad: bool | None = None,
        trade_name: str | None = None,
        has_certificate: bool = False,
    ) -> BusinessSettings:
        """Change the given electronic-invoicing fields (None keeps the current value).

        Everything is validated before anything is written. Turning invoicing on needs a
        regime that issues invoices, a valid RUC and a stored certificate (`has_certificate`).
        """
        with self.database.connect() as connection:
            current = self._load(connection, business_id)
            new_environment = (
                current.sri_environment
                if sri_environment is None
                else validate_sri_environment(sri_environment)
            )
            new_establishment = (
                current.establishment
                if establishment is None
                else validate_series_code(establishment, "El establecimiento")
            )
            new_point = (
                current.emission_point
                if emission_point is None
                else validate_series_code(emission_point, "El punto de emisión")
            )
            new_trade_name = (
                current.trade_name
                if trade_name is None
                else normalize_text(trade_name, "El nombre comercial", TRADE_NAME_MAX_LENGTH)
            )
            new_accounting = (
                current.obligado_contabilidad
                if obligado_contabilidad is None
                else obligado_contabilidad
            )
            new_enabled = current.einvoice_enabled if enabled is None else enabled
            # Only turning it on is checked: a certificate that disappears later must not lock
            # the owner out of unrelated edits.
            if new_enabled and not current.einvoice_enabled:
                validate_einvoice_activation(
                    current.tax_regime, current.ruc, has_certificate=has_certificate
                )
            connection.execute(
                "INSERT OR IGNORE INTO business_settings (business_id) VALUES (?)",
                (business_id,),
            )
            connection.execute(
                """
                UPDATE business_settings
                SET einvoice_enabled = ?, sri_environment = ?, establishment = ?,
                    emission_point = ?, obligado_contabilidad = ?, trade_name = ?
                WHERE business_id = ?
                """,
                (
                    int(new_enabled),
                    new_environment,
                    new_establishment,
                    new_point,
                    int(new_accounting),
                    new_trade_name,
                    business_id,
                ),
            )
        return self.get(business_id)
