"""Import products from a CSV exported by Excel: parse, preview, then apply all or nothing."""

import csv
import io
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from suitelocal.domain.auth import Session
from suitelocal.domain.policies import require_owner
from suitelocal.domain.tax import DEFAULT_TAX_RATE_BASIS_POINTS, TAX_RATES_BASIS_POINTS
from suitelocal.infrastructure.product_import_repository import (
    ProductImportRepository,
    ProductImportRow,
    nocase_key,
)
from suitelocal.infrastructure.repositories import CATEGORY_NAME_MAX_LENGTH
from suitelocal.infrastructure.settings import BusinessSettingsRepository

__all__ = [
    "ImportPlan",
    "ImportResult",
    "ParsedCsv",
    "ProductImportRow",
    "ProductImportService",
    "RowError",
    "parse_product_csv",
]

# Header name (lowercase, no accents) -> field. The first four are required.
_HEADER_FIELDS = {
    "codigo": "code",
    "nombre": "name",
    "precio": "price",
    "stock": "stock",
    "categoria": "category",
    "costo": "cost",
    "iva": "tax",
}
_REQUIRED = (("code", "código"), ("name", "nombre"), ("price", "precio"), ("stock", "stock"))
_TAX_RATES = {"15": 1500, "5": 500, "0": 0}


@dataclass(frozen=True, slots=True)
class RowError:
    """What is wrong with one CSV line (1-based, as the spreadsheet shows it)."""

    line: int
    message: str


@dataclass(frozen=True, slots=True)
class ParsedCsv:
    rows: tuple[ProductImportRow, ...]
    errors: tuple[RowError, ...]


@dataclass(frozen=True, slots=True)
class ImportPlan:
    to_create: tuple[ProductImportRow, ...]
    to_update: tuple[ProductImportRow, ...]
    categories_to_create: tuple[str, ...]
    errors: tuple[RowError, ...]

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)


@dataclass(frozen=True, slots=True)
class ImportResult:
    created: int
    updated: int
    categories_created: int


def _fold(header: str) -> str:
    """Lowercase without accents, so «Código», «CODIGO» and « codigo » are the same column."""
    decomposed = unicodedata.normalize("NFKD", header.strip().lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _decode(data: bytes) -> str | None:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def _parse_money(text: str, label: str, decimal_separator: str) -> int:
    """Integer cents from a price written with the business decimal separator.

    A thousands separator (the other character) is accepted only when it cannot be mistaken
    for a decimal one: well-grouped digits and either the decimal separator or several groups.
    """
    invalid = ValueError(
        f"{label} «{text}» no es válido. Escribilo con «{decimal_separator}» como separador "
        "decimal y hasta dos decimales."
    )
    other = "." if decimal_separator == "," else ","
    value = text.strip().removeprefix("$").strip()
    whole, found, fraction = value.partition(decimal_separator)
    if decimal_separator in fraction or other in fraction:
        raise invalid
    if other in whole:
        groups = whole.split(other)
        grouped = 1 <= len(groups[0]) <= 3 and all(len(group) == 3 for group in groups[1:])
        if not grouped or not (found or len(groups) > 2):
            raise invalid
        whole = "".join(groups)
    if not (whole.isascii() and whole.isdigit()):
        raise invalid
    if found and not (fraction.isascii() and fraction.isdigit() and len(fraction) <= 2):
        raise invalid
    return int(whole) * 100 + int(fraction.ljust(2, "0") or "0")


def _parse_row(line: int, cells: dict[str, str], decimal_separator: str) -> ProductImportRow:
    code, name = cells["code"], cells["name"]
    if not code:
        raise ValueError("El código es obligatorio.")
    if not name:
        raise ValueError("El nombre es obligatorio.")
    if not cells["price"]:
        raise ValueError("El precio es obligatorio.")
    price = _parse_money(cells["price"], "El precio", decimal_separator)
    stock_text = cells["stock"]
    if not stock_text:
        raise ValueError("El stock es obligatorio.")
    if not (stock_text.isascii() and stock_text.isdigit()):
        raise ValueError(f"El stock «{stock_text}» debe ser un número entero, sin negativos.")
    category = cells["category"] or None
    if category is not None and len(category) > CATEGORY_NAME_MAX_LENGTH:
        raise ValueError(f"La categoría no puede superar {CATEGORY_NAME_MAX_LENGTH} caracteres.")
    cost = _parse_money(cells["cost"], "El costo", decimal_separator) if cells["cost"] else None
    tax_text = cells["tax"].replace("%", "").replace(" ", "")
    if tax_text and tax_text not in _TAX_RATES:
        raise ValueError("El IVA debe ser 15, 5 o 0.")
    rate = _TAX_RATES[tax_text] if tax_text else None
    return ProductImportRow(line, code, name, price, int(stock_text), category, cost, rate)


def parse_product_csv(source: bytes | Path | str, *, decimal_separator: str = ",") -> ParsedCsv:
    """Read the CSV (bytes, or the path of a file) into valid rows and per-line errors.

    Decoded as UTF-8 (with or without BOM), else cp1252, the two encodings Excel writes. The
    delimiter, ``;`` or ``,``, is taken from the header line. Problems with the file as a
    whole (no header, a missing column) are reported as errors of its header line.
    """
    data = source if isinstance(source, bytes) else Path(source).read_bytes()
    text = _decode(data)
    if text is None:
        return ParsedCsv(
            (), (RowError(1, "No se pudo leer el archivo: no es un CSV de texto válido."),)
        )
    first_line = next((line for line in text.splitlines() if line.strip()), None)
    if first_line is None:
        return ParsedCsv((), (RowError(1, "El archivo está vacío."),))
    delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    columns: dict[str, int] | None = None
    rows: list[ProductImportRow] = []
    errors: list[RowError] = []
    header_line = 1
    while True:
        line = reader.line_num + 1
        try:
            record = next(reader)
        except StopIteration:
            break
        except csv.Error as error:
            errors.append(RowError(line, f"No se pudo leer el archivo: {error}"))
            break
        if not any(cell.strip() for cell in record):
            continue
        if columns is None:
            header_line = line
            columns = {}
            for index, header in enumerate(record):
                field = _HEADER_FIELDS.get(_fold(header))
                if field is not None and field not in columns:
                    columns[field] = index
            missing = [label for field, label in _REQUIRED if field not in columns]
            if missing:
                return ParsedCsv(
                    (), tuple(RowError(line, f"Falta la columna «{m}».") for m in missing)
                )
            continue
        cells = {
            field: record[index].strip() if index < len(record) else ""
            for field, index in columns.items()
        }
        for field in _HEADER_FIELDS.values():
            cells.setdefault(field, "")
        try:
            rows.append(_parse_row(line, cells, decimal_separator))
        except ValueError as error:
            errors.append(RowError(line, str(error)))
    if not rows and not errors:
        errors.append(RowError(header_line, "El archivo no tiene productos para importar."))
    return ParsedCsv(tuple(rows), tuple(errors))


class ProductImportService:
    """Owner-only bulk import of products into the session's business."""

    def __init__(
        self, repository: ProductImportRepository, settings: BusinessSettingsRepository
    ) -> None:
        self.repository = repository
        self.settings = settings

    def preview(self, session: Session, source: bytes | Path | str) -> ImportPlan:
        """Work out what importing the file would do, without writing anything."""
        require_owner(session)
        business_id = session.user.business_id
        parsed = parse_product_csv(
            source, decimal_separator=self.settings.get(business_id).decimal_separator
        )
        states = self.repository.product_states()
        known_categories = self.repository.category_keys(business_id)
        first_lines: dict[str, int] = {}
        to_create: list[ProductImportRow] = []
        to_update: list[ProductImportRow] = []
        new_categories: list[str] = []
        errors = list(parsed.errors)
        for row in parsed.rows:
            if row.code in first_lines:
                errors.append(
                    RowError(
                        row.line,
                        f"El código {row.code} está repetido; "
                        f"ya aparece en la línea {first_lines[row.code]}.",
                    )
                )
                continue
            first_lines[row.code] = row.line
            active = states.get(row.code)
            if active is False:
                errors.append(
                    RowError(row.line, f"El código {row.code} pertenece a un producto desactivado.")
                )
                continue
            (to_update if active else to_create).append(row)
            if row.category is not None and nocase_key(row.category) not in known_categories:
                known_categories.add(nocase_key(row.category))
                new_categories.append(row.category)
        errors.sort(key=lambda error: error.line)
        return ImportPlan(tuple(to_create), tuple(to_update), tuple(new_categories), tuple(errors))

    def apply(self, session: Session, plan: ImportPlan) -> ImportResult:
        """Write the plan in one transaction; a plan with errors is never applied."""
        require_owner(session)
        if plan.has_errors:
            raise ValueError("El archivo tiene errores; corregilos y volvé a importar.")
        business_id = session.user.business_id
        rate = self.settings.get(business_id).tax_rate_basis_points
        self.repository.apply(
            business_id,
            plan.categories_to_create,
            plan.to_create,
            plan.to_update,
            rate if rate in TAX_RATES_BASIS_POINTS else DEFAULT_TAX_RATE_BASIS_POINTS,
        )
        return ImportResult(
            len(plan.to_create), len(plan.to_update), len(plan.categories_to_create)
        )
