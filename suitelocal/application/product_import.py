"""Import products from an Excel (.xlsx) or CSV file: parse, preview, then apply all or nothing."""

import csv
import io
import unicodedata
import zipfile
from collections.abc import Generator, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

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
    "parse_product_file",
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

# Bounds that keep every imported number far from the int64 limits of the database.
MAX_MONEY_CENTS = 9_999_999_999  # 99.999.999,99
MAX_STOCK = 1_000_000
_MAX_MONEY_TEXT = "99.999.999,99"
_MAX_STOCK_TEXT = "1.000.000"

_XLSX_MAGIC = b"PK\x03\x04"
_XLS_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_XLS_MESSAGE = "No se puede leer el formato .xls antiguo. Guardá el archivo como .xlsx o CSV."
_XLSX_READ_ERRORS = (zipfile.BadZipFile, InvalidFileException, KeyError, ValueError, SyntaxError)

# A cell is text, or an exact Decimal when the spreadsheet stored a number.
Cell = str | Decimal


@dataclass(frozen=True, slots=True)
class RowError:
    """What is wrong with one line or row (1-based, as the spreadsheet shows it)."""

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


def _too_big(label: str) -> ValueError:
    return ValueError(f"{label} no puede superar {_MAX_MONEY_TEXT}.")


def _show(value: Decimal) -> str:
    return format(value.normalize(), "f") if value.is_finite() else str(value)


def _text(cell: Cell) -> str:
    return _show(cell) if isinstance(cell, Decimal) else cell


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
    if len(whole.lstrip("0")) > len(str(MAX_MONEY_CENTS)):
        raise _too_big(label)
    return int(whole) * 100 + int(fraction.ljust(2, "0") or "0")


def _decimal_cents(value: Decimal, label: str) -> int:
    """Cents from a numeric cell, rounded half up with Decimal (never through float math)."""
    if not value.is_finite() or value < 0:
        raise ValueError(f"{label} «{_show(value)}» no es válido. Debe ser un número positivo.")
    if value > Decimal(MAX_MONEY_CENTS):
        raise _too_big(label)
    return int((value * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _money(cell: Cell, label: str, decimal_separator: str) -> int:
    if isinstance(cell, Decimal):
        cents = _decimal_cents(cell, label)
    else:
        cents = _parse_money(cell, label, decimal_separator)
    if cents > MAX_MONEY_CENTS:
        raise _too_big(label)
    return cents


def _stock(cell: Cell) -> int:
    invalid = ValueError(f"El stock «{_text(cell)}» debe ser un número entero, sin negativos.")
    too_big = ValueError(f"El stock no puede superar {_MAX_STOCK_TEXT}.")
    if isinstance(cell, Decimal):
        if not cell.is_finite() or cell < 0 or cell != cell.to_integral_value():
            raise invalid
        if cell > MAX_STOCK:
            raise too_big
        return int(cell)
    if not (cell.isascii() and cell.isdigit()):
        raise invalid
    if len(cell.lstrip("0")) > len(str(MAX_STOCK)) or int(cell) > MAX_STOCK:
        raise too_big
    return int(cell)


def _tax_text(cell: Cell) -> str:
    """The IVA as text; a numeric cell may hold 15 or, formatted as a percentage, 0.15."""
    if not isinstance(cell, Decimal):
        return cell.replace("%", "").replace(" ", "")
    if not cell.is_finite():
        return str(cell)
    percent = cell * 100 if 0 < cell < 1 else cell
    return str(int(percent)) if percent == percent.to_integral_value() else _show(percent)


def _parse_row(line: int, cells: dict[str, Cell], decimal_separator: str) -> ProductImportRow:
    code, name = _text(cells["code"]), _text(cells["name"])
    if not code:
        raise ValueError("El código es obligatorio.")
    if not name:
        raise ValueError("El nombre es obligatorio.")
    if cells["price"] == "":
        raise ValueError("El precio es obligatorio.")
    price = _money(cells["price"], "El precio", decimal_separator)
    if cells["stock"] == "":
        raise ValueError("El stock es obligatorio.")
    stock = _stock(cells["stock"])
    category = _text(cells["category"]) or None
    if category is not None and len(category) > CATEGORY_NAME_MAX_LENGTH:
        raise ValueError(f"La categoría no puede superar {CATEGORY_NAME_MAX_LENGTH} caracteres.")
    cost = _money(cells["cost"], "El costo", decimal_separator) if cells["cost"] != "" else None
    tax_text = _tax_text(cells["tax"])
    if tax_text and tax_text not in _TAX_RATES:
        raise ValueError("El IVA debe ser 15, 5 o 0.")
    rate = _TAX_RATES[tax_text] if tax_text else None
    return ProductImportRow(line, code, name, price, stock, category, cost, rate)


def _cell(value: object) -> Cell:
    """A raw cell as stripped text, or as an exact Decimal when it is a number."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return Decimal(str(value))  # the shortest repr of the number, never float math
    return str(value).strip()


class _RowCollector:
    """Turns records (a header, then product rows) into valid rows and per-line errors."""

    def __init__(self, decimal_separator: str) -> None:
        self.decimal_separator = decimal_separator
        self.columns: dict[str, int] | None = None
        self.rows: list[ProductImportRow] = []
        self.errors: list[RowError] = []
        self.header_line = 1
        self.fatal: tuple[RowError, ...] | None = None

    def add(self, line: int, record: Sequence[object]) -> bool:
        """Take one record; False when the file as a whole is unusable and reading must stop."""
        values = [_cell(value) for value in record]
        if not any(value != "" for value in values):
            return True
        if self.columns is None:
            return self._header(line, values)
        cells: dict[str, Cell] = {
            field: values[index] if index < len(values) else ""
            for field, index in self.columns.items()
        }
        for field in _HEADER_FIELDS.values():
            cells.setdefault(field, "")
        try:
            self.rows.append(_parse_row(line, cells, self.decimal_separator))
        except ValueError as error:
            self.errors.append(RowError(line, str(error)))
        return True

    def _header(self, line: int, values: list[Cell]) -> bool:
        self.header_line = line
        columns: dict[str, int] = {}
        for index, header in enumerate(values):
            field = _HEADER_FIELDS.get(_fold(_text(header)))
            if field is not None and field not in columns:
                columns[field] = index
        self.columns = columns
        missing = [label for field, label in _REQUIRED if field not in columns]
        if missing:
            self.fatal = tuple(RowError(line, f"Falta la columna «{m}».") for m in missing)
            return False
        return True

    def finish(self) -> ParsedCsv:
        if self.fatal is not None:
            return ParsedCsv((), self.fatal)
        if not self.rows and not self.errors:
            message = "El archivo no tiene productos para importar."
            self.errors.append(RowError(self.header_line, message))
        return ParsedCsv(tuple(self.rows), tuple(self.errors))


def _parse_csv(data: bytes, decimal_separator: str) -> ParsedCsv:
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
    collector = _RowCollector(decimal_separator)
    while True:
        line = reader.line_num + 1
        try:
            record = next(reader)
        except StopIteration:
            break
        except csv.Error as error:
            collector.errors.append(RowError(line, f"No se pudo leer el archivo: {error}"))
            break
        if not collector.add(line, record):
            break
    return collector.finish()


def _xlsx_records(
    source: Path | io.BytesIO,
) -> Generator[tuple[int, tuple[object, ...]], None, None]:
    """The rows of the first worksheet with their 1-based row numbers; always closes the file."""
    workbook = load_workbook(source, read_only=True, data_only=True)
    try:
        if not workbook.worksheets:
            return
        sheet = workbook.worksheets[0]
        for number, row in enumerate(sheet.iter_rows(values_only=True), start=1):
            yield number, tuple(row)
    finally:
        workbook.close()


def _parse_xlsx(source: Path | io.BytesIO, decimal_separator: str) -> ParsedCsv:
    collector = _RowCollector(decimal_separator)
    records = _xlsx_records(source)
    try:
        for number, record in records:
            if not collector.add(number, record):
                break
    except _XLSX_READ_ERRORS:
        message = "No se pudo leer el archivo: no es un Excel (.xlsx) válido."
        return ParsedCsv((), (RowError(1, message),))
    finally:
        records.close()
    return collector.finish()


def parse_product_file(source: bytes | Path | str, *, decimal_separator: str = ",") -> ParsedCsv:
    """Read an .xlsx or CSV (bytes, or the path of a file) into valid rows and per-line errors.

    An .xlsx is read from its first worksheet; the old .xls format is refused. A CSV is decoded
    as UTF-8 (with or without BOM), else cp1252, the two encodings Excel writes, and its
    delimiter, ``;`` or ``,``, is taken from the header line. Problems with the file as a
    whole (no header, a missing column) are reported as errors of its header line.
    """
    if isinstance(source, bytes):
        data = source
    else:
        path = Path(source)
        suffix = path.suffix.lower()
        if suffix == ".xls":
            return ParsedCsv((), (RowError(1, _XLS_MESSAGE),))
        if suffix == ".xlsx":
            return _parse_xlsx(path, decimal_separator)
        data = path.read_bytes()
    if data.startswith(_XLS_MAGIC):
        return ParsedCsv((), (RowError(1, _XLS_MESSAGE),))
    if data.startswith(_XLSX_MAGIC):
        return _parse_xlsx(io.BytesIO(data), decimal_separator)
    return _parse_csv(data, decimal_separator)


parse_product_csv = parse_product_file


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
        parsed = parse_product_file(
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
