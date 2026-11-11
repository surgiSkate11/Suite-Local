from pathlib import Path

import pytest
from openpyxl import Workbook

from suitelocal.application.auth import AuthService
from suitelocal.application.categories import CategoryService
from suitelocal.application.inventory import InventoryService
from suitelocal.application.product_import import (
    ImportPlan,
    ProductImportRow,
    ProductImportService,
    RowError,
    parse_product_csv,
    parse_product_file,
)
from suitelocal.domain.auth import Session
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.product_import_repository import ProductImportRepository
from suitelocal.infrastructure.repositories import CategoryRepository, ProductRepository
from suitelocal.infrastructure.settings import BusinessSettingsRepository

HEADER = "código;nombre;precio;stock;categoría;costo;iva"


class Env:
    def __init__(self, tmp_path: Path) -> None:
        self.database = Database(tmp_path / "import.db")
        self.database.initialize()
        auth = AuthService(self.database)
        self.owner = Session(
            auth.setup_owner("Tienda Sol", "owner", "clave-segura", "clave-segura")
        )
        self.cashier = Session(
            auth.create_cashier(self.owner, "cajero", "clave-cajero", "clave-cajero")
        )
        self.settings = BusinessSettingsRepository(self.database)
        self.products = ProductRepository(self.database)
        self.categories = CategoryService(CategoryRepository(self.database))
        self.inventory = InventoryService(self.products)
        self.service = ProductImportService(ProductImportRepository(self.database), self.settings)

    def snapshot(self) -> tuple[list[tuple[object, ...]], list[tuple[object, ...]]]:
        with self.database.connect() as connection:
            products = connection.execute(
                "SELECT code, name, price_cents, stock, active, category_id, cost_cents, "
                "tax_rate_basis_points FROM products ORDER BY code"
            ).fetchall()
            categories = connection.execute("SELECT name FROM categories ORDER BY name").fetchall()
        return [tuple(row) for row in products], [tuple(row) for row in categories]

    def product(self, code: str):
        return next(p for p in self.products.find_active(code) if p.code == code)

    def category_name(self, category_id: int | None) -> str | None:
        names = {c.id: c.name for c in self.categories.list(self.owner, include_inactive=True)}
        return None if category_id is None else names[category_id]


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def csv(*lines: str, header: str = HEADER) -> bytes:
    return ("\n".join([header, *lines]) + "\n").encode("utf-8-sig")


# -- parser: encodings and delimiters -----------------------------------------------------


def test_reads_a_utf8_bom_file_with_semicolons():
    plan = parse_product_csv(csv("A-1;Arroz;2,50;10;Granos;1,80;15"))

    assert plan.errors == ()
    assert plan.rows == (ProductImportRow(2, "A-1", "Arroz", 250, 10, "Granos", 180, 1500),)


def test_reads_a_cp1252_file_with_commas_and_accents():
    raw = 'código,nombre,precio,stock,categoría\nA-1,Azúcar morena,"2,50",4,Despensa ñoña\n'

    plan = parse_product_csv(raw.encode("cp1252"), decimal_separator=",")

    assert plan.errors == ()
    assert plan.rows[0].name == "Azúcar morena"
    assert plan.rows[0].category == "Despensa ñoña"
    assert plan.rows[0].price_cents == 250


def test_reads_a_path(tmp_path):
    file = tmp_path / "productos.csv"
    file.write_bytes(csv("A-1;Arroz;2,50;10"))

    assert parse_product_csv(file).rows[0].code == "A-1"
    assert parse_product_csv(str(file)).rows[0].code == "A-1"


@pytest.mark.parametrize(
    "header",
    [
        "Código;Nombre;Precio;Stock",
        "CODIGO;NOMBRE;PRECIO;STOCK",
        "  codigo ; nombre ; precio ; stock ",
        "CÓDIGO;nombre;PRECIO;Stock;Categoria;COSTO;Iva",
    ],
)
def test_header_names_ignore_case_accents_and_spaces(header):
    plan = parse_product_csv(csv("A-1;Arroz;2,50;10", header=header))

    assert plan.errors == ()
    assert plan.rows[0].price_cents == 250


def test_columns_may_come_in_any_order_and_extra_columns_are_ignored():
    plan = parse_product_csv(
        csv("10;Arroz;nota;2,50;A-1", header="stock;nombre;otro;precio;codigo")
    )

    assert plan.rows == (ProductImportRow(2, "A-1", "Arroz", 250, 10, None, None, None),)


def test_a_missing_required_column_is_reported_and_nothing_is_read():
    plan = parse_product_csv(csv("A-1;Arroz;10", header="codigo;nombre;stock"))

    assert plan.rows == ()
    assert plan.errors == (RowError(1, "Falta la columna «precio»."),)


def test_an_empty_file_or_one_without_products_is_an_error():
    assert parse_product_csv(b"").errors == (RowError(1, "El archivo está vacío."),)
    assert parse_product_csv(csv()).errors == (
        RowError(1, "El archivo no tiene productos para importar."),
    )


def test_bytes_that_are_not_text_are_an_error():
    plan = parse_product_csv(b"codigo;nombre\n\x81\x8d\x8f\x90")

    assert plan.rows == ()
    assert plan.errors[0].message.startswith("No se pudo leer el archivo")


def test_blank_lines_are_skipped_but_still_counted_in_line_numbers():
    plan = parse_product_csv(csv("A-1;Arroz;2,50;10", "", ";;;;;;", "B-2;Sal;;3"))

    assert [row.code for row in plan.rows] == ["A-1"]
    assert plan.errors == (RowError(5, "El precio es obligatorio."),)


# -- parser: values -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("separator", "text", "cents"),
    [
        (",", "2,5", 250),
        (",", "2,50", 250),
        (",", "2", 200),
        (",", "$ 2,50", 250),
        (",", "1.234,56", 123456),
        (",", "1.234.567", 123456700),
        (".", "2.50", 250),
        (".", "1,234.56", 123456),
        (".", "0.05", 5),
    ],
)
def test_prices_use_the_business_decimal_separator(separator, text, cents):
    plan = parse_product_csv(csv(f'A-1;Arroz;"{text}";1'), decimal_separator=separator)

    assert plan.errors == ()
    assert plan.rows[0].price_cents == cents


@pytest.mark.parametrize(
    ("separator", "text"),
    [
        (",", "2.50"),  # the other separator used as a decimal one
        (",", "1.234"),  # ambiguous: thousands or three decimals
        (",", "12.34,5"),  # badly grouped thousands
        (",", "1,234,5"),
        (",", "2,505"),  # more than two decimals
        (",", "-1,00"),
        (",", "abc"),
        (",", "2,"),
        (",", ",5"),
        (".", "2,50"),
        (".", "1,234"),
    ],
)
def test_ambiguous_or_malformed_prices_are_row_errors(separator, text):
    plan = parse_product_csv(csv(f'A-1;Arroz;"{text}";1'), decimal_separator=separator)

    assert plan.rows == ()
    assert len(plan.errors) == 1
    assert plan.errors[0].line == 2
    assert text in plan.errors[0].message


def test_the_cost_follows_the_same_rules_and_may_be_blank():
    plan = parse_product_csv(csv("A-1;Arroz;2,50;1;;1,25;", "B-2;Sal;1,00;1;;;"))

    assert [row.cost_cents for row in plan.rows] == [125, None]
    bad = parse_product_csv(csv("A-1;Arroz;2,50;1;;1.25;"))
    assert bad.errors[0].message.startswith("El costo")


@pytest.mark.parametrize(
    ("text", "rate"),
    [("15", 1500), ("15%", 1500), (" 15 % ", 1500), ("5", 500), ("5%", 500), ("0", 0), ("0 %", 0)],
)
def test_iva_accepts_15_5_and_0_with_or_without_percent(text, rate):
    plan = parse_product_csv(csv(f"A-1;Arroz;2,50;1;;;{text}"))

    assert plan.errors == ()
    assert plan.rows[0].tax_rate_basis_points == rate


def test_iva_absent_or_blank_stays_unset_so_the_default_applies_on_create():
    no_column = parse_product_csv(csv("A-1;Arroz;2,50;1", header="codigo;nombre;precio;stock"))
    blank = parse_product_csv(csv("A-1;Arroz;2,50;1;;;"))

    assert no_column.rows[0].tax_rate_basis_points is None
    assert blank.rows[0].tax_rate_basis_points is None


@pytest.mark.parametrize("text", ["12", "abc", "-5", "7,5"])
def test_an_invalid_iva_is_a_row_error(text):
    plan = parse_product_csv(csv(f"A-1;Arroz;2,50;1;;;{text}"))

    assert plan.errors == (RowError(2, "El IVA debe ser 15, 5 o 0."),)


@pytest.mark.parametrize("text", ["-1", "1,5", "abc", ""])
def test_stock_must_be_a_non_negative_integer(text):
    plan = parse_product_csv(csv(f'A-1;Arroz;2,50;"{text}"'))

    assert plan.rows == ()
    assert plan.errors[0].line == 2
    assert plan.errors[0].message.startswith("El stock")


def test_code_name_and_category_length_are_validated_with_line_numbers():
    plan = parse_product_csv(
        csv(
            ";Arroz;2,50;1",
            "B-2;;2,50;1",
            f"C-3;Sal;2,50;1;{'x' * 41}",
            "D-4;Ok;2,50;1",
        )
    )

    assert [row.code for row in plan.rows] == ["D-4"]
    assert [error.line for error in plan.errors] == [2, 3, 4]
    assert plan.errors[0].message == "El código es obligatorio."
    assert plan.errors[1].message == "El nombre es obligatorio."
    assert plan.errors[2].message.startswith("La categoría no puede superar")


def test_line_numbers_count_physical_lines_even_with_multiline_cells():
    raw = f'{HEADER}\nA-1;"Arroz\ncorto";2,50;1\nB-2;Sal;mal;1\n'.encode("utf-8-sig")

    plan = parse_product_csv(raw)

    assert plan.errors[0].line == 4


def test_a_short_row_reports_the_missing_cell():
    plan = parse_product_csv(csv("A-1;Arroz"))

    assert plan.errors == (RowError(2, "El precio es obligatorio."),)


# -- preview ------------------------------------------------------------------------------


def test_preview_separates_creates_from_updates_and_lists_new_categories(env):
    env.categories.create(env.owner, "Granos")
    env.inventory.create_product(env.owner, "A-1", "Arroz viejo", 100, 1)
    data = csv(
        "A-1;Arroz;2,50;10;Granos",
        "B-2;Sal;1,00;5;Condimentos",
        "C-3;Aceite;3,00;2;condimentos",
        "D-4;Pan;0,30;9;Panadería",
    )

    plan = env.service.preview(env.owner, data)

    assert plan.errors == ()
    assert [row.code for row in plan.to_update] == ["A-1"]
    assert [row.code for row in plan.to_create] == ["B-2", "C-3", "D-4"]
    assert plan.categories_to_create == ("Condimentos", "Panadería")
    assert not plan.has_errors


def test_preview_reads_the_decimal_separator_from_the_business_settings(env):
    env.settings.update_profile(env.owner.user.business_id, decimal_separator=".")

    ok = env.service.preview(env.owner, csv("A-1;Arroz;2.50;10"))
    bad = env.service.preview(env.owner, csv("A-1;Arroz;2,50;10"))

    assert ok.to_create[0].price_cents == 250
    assert bad.has_errors and bad.errors[0].line == 2


def test_a_duplicate_code_in_the_file_is_an_error_on_the_later_row(env):
    plan = env.service.preview(
        env.owner, csv("A-1;Arroz;2,50;10", "B-2;Sal;1,00;5", "A-1;Arroz otra vez;3,00;1")
    )

    assert [row.code for row in plan.to_create] == ["A-1", "B-2"]
    assert plan.errors == (RowError(4, "El código A-1 está repetido; ya aparece en la línea 2."),)
    assert plan.has_errors


def test_a_code_of_a_deactivated_product_is_a_row_error(env):
    product = env.inventory.create_product(env.owner, "A-1", "Arroz", 100, 1)
    env.inventory.deactivate_product(env.owner, product.id)

    plan = env.service.preview(env.owner, csv("A-1;Arroz;2,50;10"))

    assert plan.to_create == () and plan.to_update == ()
    assert plan.errors == (RowError(2, "El código A-1 pertenece a un producto desactivado."),)


def test_preview_does_not_touch_the_database(env):
    before = env.snapshot()

    env.service.preview(env.owner, csv("A-1;Arroz;2,50;10;Granos"))

    assert env.snapshot() == before


def test_preview_is_owner_only(env):
    with pytest.raises(PermissionError):
        env.service.preview(env.cashier, csv("A-1;Arroz;2,50;10"))


# -- apply --------------------------------------------------------------------------------


def test_apply_creates_updates_and_creates_missing_categories(env):
    env.categories.create(env.owner, "Granos")
    existing = env.inventory.create_product(
        env.owner, "A-1", "Arroz viejo", 100, 1, tax_rate_basis_points=0
    )
    plan = env.service.preview(
        env.owner,
        csv(
            "A-1;Arroz;2,50;10;granos;1,80;5",
            "B-2;Sal;1,00;5;Condimentos;;",
            "C-3;Pan;0,30;9;;;0",
        ),
    )

    result = env.service.apply(env.owner, plan)

    assert (result.created, result.updated, result.categories_created) == (2, 1, 1)
    updated = env.product("A-1")
    assert updated.id == existing.id
    assert (updated.name, updated.price_cents, updated.stock) == ("Arroz", 250, 10)
    assert (updated.cost_cents, updated.tax_rate_basis_points) == (180, 500)
    assert env.category_name(updated.category_id) == "Granos"
    created = env.product("B-2")
    assert (created.price_cents, created.stock, created.cost_cents) == (100, 5, None)
    assert env.category_name(created.category_id) == "Condimentos"
    assert env.product("C-3").category_id is None
    assert env.product("C-3").tax_rate_basis_points == 0
    names = [c.name for c in env.categories.list(env.owner, include_inactive=True)]
    assert names == ["Condimentos", "Granos"]


def test_created_products_without_iva_get_the_business_default_rate(env):
    env.settings.update(
        env.owner.user.business_id, "Tienda Sol", "$", 3, ("cash",), tax_rate_percent=5
    )

    env.service.apply(env.owner, env.service.preview(env.owner, csv("A-1;Arroz;2,50;1")))

    assert env.product("A-1").tax_rate_basis_points == 500


def test_an_update_keeps_category_cost_and_iva_the_file_leaves_blank(env):
    env.categories.create(env.owner, "Granos")
    category_id = env.categories.list(env.owner)[0].id
    env.inventory.create_product(
        env.owner,
        "A-1",
        "Arroz",
        100,
        1,
        category_id=category_id,
        cost_cents=70,
        tax_rate_basis_points=0,
    )

    env.service.apply(env.owner, env.service.preview(env.owner, csv("A-1;Arroz fino;2,50;7;;;")))

    product = env.product("A-1")
    assert (product.name, product.price_cents, product.stock) == ("Arroz fino", 250, 7)
    assert (product.category_id, product.cost_cents, product.tax_rate_basis_points) == (
        category_id,
        70,
        0,
    )


def test_apply_works_from_a_file_without_the_optional_columns(env):
    plan = env.service.preview(
        env.owner, csv("A-1;Arroz;2,50;10", header="Código;Nombre;Precio;Stock")
    )

    result = env.service.apply(env.owner, plan)

    assert (result.created, result.updated, result.categories_created) == (1, 0, 0)


def test_a_cashier_cannot_apply_and_nothing_changes(env):
    plan = env.service.preview(env.owner, csv("A-1;Arroz;2,50;10;Granos"))
    before = env.snapshot()

    with pytest.raises(PermissionError):
        env.service.apply(env.cashier, plan)

    assert env.snapshot() == before


def test_a_plan_with_errors_is_refused(env):
    plan = env.service.preview(env.owner, csv("A-1;Arroz;2,50;10;Granos", "B-2;Sal;mal;1"))
    before = env.snapshot()

    with pytest.raises(ValueError, match="errores"):
        env.service.apply(env.owner, plan)

    assert env.snapshot() == before


def test_a_forged_plan_with_errors_is_still_refused(env):
    plan = ImportPlan(
        to_create=(ProductImportRow(2, "A-1", "Arroz", 250, 1, None, None, None),),
        to_update=(),
        categories_to_create=(),
        errors=(RowError(3, "x"),),
    )

    with pytest.raises(ValueError):
        env.service.apply(env.owner, plan)

    assert env.snapshot() == ([], [])


def test_a_failure_in_the_last_update_rolls_back_creates_updates_and_categories(env):
    first = env.inventory.create_product(env.owner, "A-1", "Arroz", 100, 1)
    second = env.inventory.create_product(env.owner, "Z-9", "Zanahoria", 100, 1)
    plan = env.service.preview(
        env.owner,
        csv(
            "A-1;Arroz fino;2,50;10;Granos",
            "B-2;Sal;1,00;5;Condimentos",
            "Z-9;Zanahoria grande;4,00;2;Verduras",
        ),
    )
    # Between the preview and the confirmation another user deactivates a product of the plan.
    env.inventory.deactivate_product(env.owner, second.id)
    before = env.snapshot()

    with pytest.raises(ValueError, match="Z-9"):
        env.service.apply(env.owner, plan)

    assert env.snapshot() == before
    assert env.product("A-1").name == first.name


def test_a_code_that_appears_after_the_preview_rolls_everything_back(env):
    plan = env.service.preview(
        env.owner, csv("A-1;Arroz;2,50;10;Granos", "B-2;Sal;1,00;5;Condimentos")
    )
    env.inventory.create_product(env.owner, "B-2", "Sal de otro", 100, 1)
    before = env.snapshot()

    with pytest.raises(ValueError, match="B-2"):
        env.service.apply(env.owner, plan)

    assert env.snapshot() == before


def test_the_connection_is_released_after_a_failed_apply(env):
    plan = env.service.preview(env.owner, csv("A-1;Arroz;2,50;10"))
    env.inventory.create_product(env.owner, "A-1", "Otro", 100, 1)

    with pytest.raises(ValueError):
        env.service.apply(env.owner, plan)

    env.inventory.create_product(env.owner, "C-3", "Sigue funcionando", 100, 1)


# -- .xlsx files and number bounds --------------------------------------------------------


def xlsx(tmp_path: Path, *rows: tuple[object, ...], name: str = "productos.xlsx") -> Path:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    for row in rows:
        sheet.append(row)
    path = tmp_path / name
    workbook.save(path)
    workbook.close()
    return path


XLSX_HEADER = ("Código", "Nombre", "Precio", "Stock", "Categoría", "Costo", "IVA")


def test_an_xlsx_reads_numeric_and_text_cells_into_the_same_rows_as_a_csv(tmp_path):
    path = xlsx(
        tmp_path,
        XLSX_HEADER,
        ("A-1", "Arroz", 2.5, 10, "Granos", 1.8, 15),
        ("B-2", "Sal", "1,00", "5", "Granos", "0,40", "5%"),
        (123, "Pan", 0.3, 9.0, None, None, 0.05),
    )

    parsed = parse_product_file(path)

    assert parsed.errors == ()
    assert parsed.rows == (
        ProductImportRow(2, "A-1", "Arroz", 250, 10, "Granos", 180, 1500),
        ProductImportRow(3, "B-2", "Sal", 100, 5, "Granos", 40, 500),
        ProductImportRow(4, "123", "Pan", 30, 9, None, None, 500),
    )
    assert parsed.rows[0] == parse_product_csv(csv("A-1;Arroz;2,50;10;Granos;1,80;15")).rows[0]


@pytest.mark.parametrize(
    ("value", "cents"),
    [(1.15, 115), (0.1 + 0.2, 30), (2.675, 268), (19.99, 1999), (1.005, 101), (0, 0), (7, 700)],
)
def test_xlsx_money_is_rounded_to_cents_exactly(tmp_path, value, cents):
    path = xlsx(tmp_path, XLSX_HEADER, ("A-1", "Arroz", value, 1, None, value, None))

    row = parse_product_file(path).rows[0]

    assert (row.price_cents, row.cost_cents) == (cents, cents)


def test_an_xlsx_ignores_empty_rows_and_keeps_the_sheet_row_numbers(tmp_path):
    path = xlsx(
        tmp_path,
        (None, None, None),
        XLSX_HEADER,
        (None, None, None, None),
        ("A-1", "Arroz", 2.5, 10),
        ("   ", None, ""),
        ("B-2", "Sal", -1, 5),
    )

    parsed = parse_product_file(path)

    assert [row.line for row in parsed.rows] == [4]
    assert [error.line for error in parsed.errors] == [6]


def test_an_xlsx_reads_only_the_first_worksheet_and_ignores_extra_columns(tmp_path):
    workbook = Workbook()
    first = workbook.active
    assert first is not None
    first.append(("Notas", "Stock", "Precio", "Nombre", "Código"))
    first.append(("x", 4, 3.5, "Aceite", "C-3"))
    workbook.create_sheet().append(("otra", "hoja"))
    path = tmp_path / "dos-hojas.xlsx"
    workbook.save(path)
    workbook.close()

    assert parse_product_file(path).rows == (
        ProductImportRow(2, "C-3", "Aceite", 350, 4, None, None, None),
    )


def test_an_xlsx_can_be_read_from_bytes_and_str_paths(tmp_path):
    path = xlsx(tmp_path, XLSX_HEADER, ("A-1", "Arroz", 2.5, 10))

    assert parse_product_file(path.read_bytes()).rows[0].code == "A-1"
    assert parse_product_file(str(path)).rows[0].code == "A-1"


def test_an_xlsx_is_closed_after_reading_so_it_can_be_deleted(tmp_path):
    path = xlsx(tmp_path, XLSX_HEADER, ("A-1", "Arroz", 2.5, 10))
    parse_product_file(path)

    path.unlink()  # fails on Windows while the workbook still holds the file open

    assert not path.exists()


def test_an_xlsx_without_products_or_with_a_missing_column_is_an_error(tmp_path):
    only_header = xlsx(tmp_path, XLSX_HEADER, name="a.xlsx")
    missing = xlsx(tmp_path, ("Código", "Nombre", "Precio"), ("A", "B", 1), name="b.xlsx")

    assert parse_product_file(only_header).errors == (
        RowError(1, "El archivo no tiene productos para importar."),
    )
    assert parse_product_file(missing).errors == (RowError(1, "Falta la columna «stock»."),)


@pytest.mark.parametrize(
    ("price", "stock", "message"),
    [
        (-2, 1, "El precio «-2» no es válido. Debe ser un número positivo."),
        (2, 1.5, "El stock «1.5» debe ser un número entero, sin negativos."),
        (2, -1, "El stock «-1» debe ser un número entero, sin negativos."),
    ],
)
def test_xlsx_invalid_numbers_are_row_errors(tmp_path, price, stock, message):
    path = xlsx(tmp_path, XLSX_HEADER, ("A-1", "Arroz", price, stock))

    parsed = parse_product_file(path)

    assert parsed.rows == ()
    assert parsed.errors == (RowError(2, message),)


def test_xlsx_text_cells_follow_the_csv_rules(tmp_path):
    path = xlsx(tmp_path, XLSX_HEADER, ("A-1", "Arroz", "abc", 1), ("B-2", "Sal", "1.234,50", 1))

    parsed = parse_product_file(path, decimal_separator=",")

    assert [row.price_cents for row in parsed.rows] == [123450]
    assert [error.line for error in parsed.errors] == [2]


def test_the_old_xls_format_is_rejected_with_a_clear_message(tmp_path):
    message = "No se puede leer el formato .xls antiguo. Guardá el archivo como .xlsx o CSV."
    by_name = tmp_path / "productos.XLS"
    by_name.write_bytes(csv("A-1;Arroz;2,50;10"))
    by_content = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + bytes(64)

    assert parse_product_file(by_name).errors == (RowError(1, message),)
    assert parse_product_file(by_content).errors == (RowError(1, message),)


def test_a_corrupt_xlsx_is_an_error_not_an_exception(tmp_path):
    broken = tmp_path / "roto.xlsx"
    broken.write_bytes(b"PK\x03\x04 esto no es un zip")
    expected = (RowError(1, "No se pudo leer el archivo: no es un Excel (.xlsx) válido."),)

    assert parse_product_file(broken).errors == expected
    assert parse_product_file(broken.read_bytes()).errors == expected


def test_a_missing_xlsx_raises_oserror(tmp_path):
    with pytest.raises(OSError):
        parse_product_file(tmp_path / "no-existe.xlsx")


# Bounds: price/cost at most 99.999.999,99 and stock at most 1.000.000, in either format.
PRICE_BOUND = "El precio no puede superar 99.999.999,99."
COST_BOUND = "El costo no puede superar 99.999.999,99."
STOCK_BOUND = "El stock no puede superar 1.000.000."


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ("A-1;Arroz;100000000,00;1", PRICE_BOUND),
        ("A-1;Arroz;99.999.999,99;1;;100000000;", COST_BOUND),
        ("A-1;Arroz;" + "9" * 40 + ";1", PRICE_BOUND),
        ("A-1;Arroz;1;1000001", STOCK_BOUND),
        ("A-1;Arroz;1;" + "9" * 5000, STOCK_BOUND),
    ],
)
def test_csv_numbers_over_the_bounds_are_row_errors(row, message):
    parsed = parse_product_csv(csv(row))

    assert parsed.rows == ()
    assert parsed.errors == (RowError(2, message),)


def test_csv_numbers_at_the_bounds_are_accepted():
    parsed = parse_product_csv(csv("A-1;Arroz;99.999.999,99;1000000;;99.999.999,99;"))

    assert parsed.errors == ()
    assert (parsed.rows[0].price_cents, parsed.rows[0].cost_cents) == (9_999_999_999,) * 2
    assert parsed.rows[0].stock == 1_000_000


@pytest.mark.parametrize(
    ("price", "cost", "stock", "message"),
    [
        (100_000_000, None, 1, PRICE_BOUND),
        (99_999_999.995, None, 1, PRICE_BOUND),
        (1e300, None, 1, PRICE_BOUND),
        (1, 100_000_000.01, 1, COST_BOUND),
        (1, None, 1_000_001, STOCK_BOUND),
        (1, None, 1e30, STOCK_BOUND),
    ],
)
def test_xlsx_numbers_over_the_bounds_are_row_errors(tmp_path, price, cost, stock, message):
    path = xlsx(tmp_path, XLSX_HEADER, ("A-1", "Arroz", price, stock, None, cost, None))

    parsed = parse_product_file(path)

    assert parsed.rows == ()
    assert parsed.errors == (RowError(2, message),)


def test_xlsx_numbers_at_the_bounds_are_accepted(tmp_path):
    path = xlsx(
        tmp_path, XLSX_HEADER, ("A-1", "Arroz", 99_999_999.99, 1_000_000, None, 99_999_999.99, None)
    )

    row = parse_product_file(path).rows[0]

    assert (row.price_cents, row.cost_cents, row.stock) == (9_999_999_999, 9_999_999_999, 1_000_000)


def test_an_out_of_bounds_row_does_not_stop_the_good_rows(tmp_path):
    path = xlsx(tmp_path, XLSX_HEADER, ("A-1", "Arroz", 1e12, 1), ("B-2", "Sal", 1, 1))

    parsed = parse_product_file(path)

    assert [row.code for row in parsed.rows] == ["B-2"]
    assert [error.line for error in parsed.errors] == [2]


# -- .xlsx through the service: same plan and same apply as a CSV -------------------------


def test_the_plan_from_an_xlsx_equals_the_plan_from_the_equivalent_csv(env, tmp_path):
    env.categories.create(env.owner, "Granos")
    env.inventory.create_product(env.owner, "A-1", "Arroz viejo", 100, 1)
    path = xlsx(
        tmp_path,
        XLSX_HEADER,
        ("A-1", "Arroz", 2.5, 10, "Granos", 1.8, 15),
        ("B-2", "Sal", 1, 5, "Condimentos", None, None),
        ("B-2", "Repetido", 1, 1),
        ("C-3", "Mal", "x", 1),
    )
    equivalent = csv(
        "A-1;Arroz;2,50;10;Granos;1,80;15",
        "B-2;Sal;1,00;5;Condimentos;;",
        "B-2;Repetido;1,00;1;;;",
        "C-3;Mal;x;1;;;",
    )

    from_xlsx = env.service.preview(env.owner, path)

    assert from_xlsx == env.service.preview(env.owner, equivalent)
    assert [row.code for row in from_xlsx.to_update] == ["A-1"]
    assert [row.code for row in from_xlsx.to_create] == ["B-2"]
    assert from_xlsx.categories_to_create == ("Condimentos",)
    assert [error.line for error in from_xlsx.errors] == [4, 5]


def test_apply_from_an_xlsx_creates_the_products_and_the_category(env, tmp_path):
    path = xlsx(
        tmp_path,
        XLSX_HEADER,
        ("A-1", "Arroz", 1.15, 10, "Granos", 0.7, 5),
        ("B-2", "Sal", 1, 5, None, None, None),
    )

    plan = env.service.preview(env.owner, path)
    result = env.service.apply(env.owner, plan)

    assert (result.created, result.updated, result.categories_created) == (2, 0, 1)
    rice = env.product("A-1")
    assert (rice.price_cents, rice.stock, rice.cost_cents) == (115, 10, 70)
    assert rice.tax_rate_basis_points == 500
    assert env.category_name(rice.category_id) == "Granos"
    assert env.product("B-2").price_cents == 100


def test_xlsx_preview_is_owner_only_and_a_plan_with_bound_errors_is_refused(env, tmp_path):
    path = xlsx(tmp_path, XLSX_HEADER, ("A-1", "Arroz", 1e12, 1))
    before = env.snapshot()

    with pytest.raises(PermissionError):
        env.service.preview(env.cashier, path)
    plan = env.service.preview(env.owner, path)
    with pytest.raises(ValueError, match="errores"):
        env.service.apply(env.owner, plan)

    assert env.snapshot() == before
