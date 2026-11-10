from pathlib import Path

import pytest

from suitelocal.application.auth import AuthService
from suitelocal.application.categories import CategoryService
from suitelocal.application.inventory import InventoryService
from suitelocal.application.product_import import (
    ImportPlan,
    ProductImportRow,
    ProductImportService,
    RowError,
    parse_product_csv,
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
