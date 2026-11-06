import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from suitelocal.application.auth import AuthService
from suitelocal.application.categories import CategoryService
from suitelocal.domain.auth import Session
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import CategoryRepository, ProductRepository
from suitelocal.infrastructure.settings import BusinessSettingsRepository
from suitelocal.ui.settings import SettingsWidget

REGIME_LABELS = [
    "Sin registro en el SRI",
    "RIMPE - Negocio popular",
    "RIMPE - Emprendedor",
    "Régimen general",
]
VALID_RUC = "1790012345001"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class Confirmations:
    """Stands in for the modal confirmation box: records the questions, answers as told."""

    def __init__(self, answer: bool = True) -> None:
        self.answer = answer
        self.asked: list[tuple[str, str]] = []

    def __call__(self, parent, title: str, text: str) -> bool:
        self.asked.append((title, text))
        return self.answer


@pytest.fixture
def env(qapp, tmp_path):
    database = Database(tmp_path / "settings.db")
    database.initialize()
    auth = AuthService(database)
    owner = Session(auth.setup_owner("Tienda Sol", "owner", "clave-segura", "clave-segura"))
    cashier = Session(auth.create_cashier(owner, "cajero", "clave-cajero", "clave-cajero"))
    return database, owner, cashier


def build(env, session=None, confirm=None) -> SettingsWidget:
    database, owner, _ = env
    return SettingsWidget(
        BusinessSettingsRepository(database),
        session or owner,
        database,
        confirm=confirm or Confirmations(),
    )


def stored(env):
    database, owner, _ = env
    return BusinessSettingsRepository(database).get(owner.user.business_id)


def category_names(env, include_inactive=True) -> list[str]:
    database, owner, _ = env
    service = CategoryService(CategoryRepository(database))
    return [category.name for category in service.list(owner, include_inactive)]


def combo_texts(combo) -> list[str]:
    return [combo.itemText(index) for index in range(combo.count())]


def list_texts(widget: SettingsWidget) -> list[str]:
    return [
        widget.categories_list.item(row).text() for row in range(widget.categories_list.count())
    ]


def select_category(widget: SettingsWidget, name: str) -> None:
    widget.categories_list.setCurrentRow(
        next(row for row, text in enumerate(list_texts(widget)) if text.startswith(name))
    )


def test_form_shows_the_current_business_profile(env):
    settings = build(env)

    assert settings.name.text() == "Tienda Sol"
    assert combo_texts(settings.regime) == REGIME_LABELS
    assert settings.regime.currentText() == "Sin registro en el SRI"
    assert settings.ruc.text() == ""
    assert combo_texts(settings.tax_rate) == ["15 %", "5 %", "0 %"]
    assert settings.tax_rate.currentText() == "15 %"
    assert settings.threshold.value() == 3
    assert combo_texts(settings.decimal_separator) == ["Coma (1.234,56)", "Punto (1,234.56)"]
    assert settings.decimal_separator.currentText() == "Coma (1.234,56)"
    assert settings.transfer.isChecked()
    assert set(settings.module_boxes) == {"mesas", "venta_por_peso", "codigo_barras", "categorias"}


def test_every_module_has_a_checkbox_and_a_short_description(env):
    settings = build(env)

    assert {code: box.text() for code, box in settings.module_boxes.items()} == {
        "mesas": "Mesas y comandas",
        "venta_por_peso": "Venta por peso",
        "codigo_barras": "Códigos de barras",
        "categorias": "Categorías",
    }
    assert {code: label.text() for code, label in settings.module_hints.items()} == {
        "mesas": "Cuentas abiertas por mesa, con envío a cocina. Ideal para cafeterías.",
        "venta_por_peso": "Productos que se venden por kilo o por libra.",
        "codigo_barras": "Vendé escaneando el código de barras del producto.",
        "categorias": "Agrupá los productos y filtrá la caja por categoría.",
    }


def test_saving_valid_data_persists_it_and_announces_the_change(env):
    settings = build(env)
    changes: list[bool] = []
    notifications: list[tuple[str, str]] = []
    settings.business_changed.connect(lambda: changes.append(True))
    settings.notification.connect(lambda text, state: notifications.append((text, state)))
    settings.name.setText("  Ferretería Luna ")
    settings.ruc.setText(VALID_RUC)
    settings.regime.setCurrentText("RIMPE - Emprendedor")
    settings.address.setText("Av. Amazonas N24-03, Quito")
    settings.phone.setText("022345678")
    settings.receipt_footer.setText("Gracias por su compra")
    settings.module_boxes["mesas"].setChecked(True)
    settings.module_boxes["codigo_barras"].setChecked(True)
    settings.tax_rate.setCurrentText("5 %")
    settings.threshold.setValue(7)
    settings.decimal_separator.setCurrentText("Punto (1,234.56)")
    settings.transfer.setChecked(False)

    settings.save()

    saved = stored(env)
    assert (saved.name, saved.ruc, saved.tax_regime) == (
        "Ferretería Luna",
        VALID_RUC,
        "rimpe_emprendedor",
    )
    assert (saved.address, saved.phone, saved.receipt_footer) == (
        "Av. Amazonas N24-03, Quito",
        "022345678",
        "Gracias por su compra",
    )
    assert saved.enabled_modules == {"mesas", "codigo_barras"}
    assert (saved.tax_rate_basis_points, saved.low_stock_threshold) == (500, 7)
    assert saved.decimal_separator == "."
    assert saved.enabled_payment_methods == ("cash",)
    assert settings.message.isHidden()
    assert changes == [True]
    assert notifications == [("Configuración de Ferretería Luna actualizada.", "success")]


def test_saving_stores_exactly_the_checked_modules(env):
    settings = build(env)
    for box in settings.module_boxes.values():
        box.setChecked(False)
    settings.module_boxes["venta_por_peso"].setChecked(True)

    settings.save()

    assert stored(env).enabled_modules == {"venta_por_peso"}


@pytest.mark.parametrize(
    ("ruc", "message"),
    [
        ("123", "El RUC debe tener exactamente 13 dígitos."),
        ("17900123450AB", "El RUC debe tener exactamente 13 dígitos."),
        ("1790012345000", "El RUC no puede terminar en 000."),
    ],
)
def test_an_invalid_ruc_shows_the_backend_message_and_persists_nothing(env, ruc, message):
    settings = build(env)
    changes: list[bool] = []
    settings.business_changed.connect(lambda: changes.append(True))
    settings.name.setText("Otro nombre")
    settings.address.setText("Otra dirección")
    settings.threshold.setValue(9)
    settings.ruc.setText(ruc)

    settings.save()

    assert settings.message.text() == message
    assert not settings.message.isHidden()
    saved = stored(env)
    assert (saved.name, saved.address, saved.ruc, saved.low_stock_threshold) == (
        "Tienda Sol",
        "",
        "",
        3,
    )
    assert changes == []


@pytest.mark.parametrize(
    ("regime", "needs_ruc"),
    [
        ("Sin registro en el SRI", False),
        ("RIMPE - Negocio popular", False),
        ("RIMPE - Emprendedor", True),
        ("Régimen general", True),
    ],
)
def test_the_ruc_is_required_only_for_the_regimes_that_need_it(env, regime, needs_ruc):
    settings = build(env)
    settings.regime.setCurrentText(regime)
    settings.ruc.setText("")

    settings.save()

    if needs_ruc:
        assert settings.message.text() == "El RUC es obligatorio para este régimen tributario."
        assert stored(env).tax_regime == "sin_registro"
    else:
        assert settings.message.isHidden()
        assert stored(env).tax_regime == settings.regime.currentData()


def test_the_ruc_field_tells_whether_the_regime_requires_it(env):
    settings = build(env)

    settings.regime.setCurrentText("Régimen general")
    assert settings.ruc.placeholderText() == "Obligatorio para este régimen"
    settings.regime.setCurrentText("Sin registro en el SRI")
    assert settings.ruc.placeholderText() == "Opcional para este régimen"


def test_a_failure_after_the_profile_step_leaves_nothing_saved(env):
    settings = build(env)
    settings.address.setText("Calle nueva")
    settings.module_boxes["mesas"].setChecked(True)
    settings.name.setText("   ")

    settings.save()

    assert settings.message.text() == "El nombre y la moneda son obligatorios."
    saved = stored(env)
    assert (saved.name, saved.address, "mesas" in saved.enabled_modules) == (
        "Tienda Sol",
        "",
        False,
    )


def test_a_cashier_cannot_save_or_manage_categories(env):
    _, _, cashier = env
    settings = build(env, cashier)
    settings.name.setText("Hackeado")

    settings.save()

    assert settings.message.text() == "Solo el dueño puede realizar esta acción."
    assert stored(env).name == "Tienda Sol"
    settings.category_name.setText("Intrusa")
    settings.add_category()
    assert settings.category_message.text() == "Solo el dueño puede realizar esta acción."
    assert category_names(env) == []


def test_apply_template_with_confirmation_adopts_type_modules_and_categories(env):
    confirm = Confirmations(True)
    settings = build(env, confirm=confirm)
    changes: list[bool] = []
    settings.business_changed.connect(lambda: changes.append(True))
    settings.business_type.setCurrentText("Cafetería")

    settings.apply_template()

    assert len(confirm.asked) == 1
    assert confirm.asked[0][0] == "Aplicar plantilla"
    assert "Cafetería" in confirm.asked[0][1]
    saved = stored(env)
    assert saved.business_type == "cafeteria"
    assert saved.enabled_modules == {"mesas", "categorias"}
    assert category_names(env) == ["Bebidas", "Café", "Desayunos", "Postres"]
    assert list_texts(settings) == ["Bebidas", "Café", "Desayunos", "Postres"]
    assert {code for code, box in settings.module_boxes.items() if box.isChecked()} == {
        "mesas",
        "categorias",
    }
    assert changes == [True]


def test_apply_template_keeps_the_unsaved_fields_of_the_form(env):
    settings = build(env)
    settings.address.setText("Sin guardar")
    settings.business_type.setCurrentText("Tienda")

    settings.apply_template()

    assert settings.address.text() == "Sin guardar"


def test_apply_template_declined_changes_nothing(env):
    confirm = Confirmations(False)
    settings = build(env, confirm=confirm)
    changes: list[bool] = []
    settings.business_changed.connect(lambda: changes.append(True))
    settings.business_type.setCurrentText("Restaurante")

    settings.apply_template()

    assert len(confirm.asked) == 1
    assert stored(env).business_type == "otro"
    assert category_names(env) == []
    assert changes == []


def test_apply_template_does_not_duplicate_existing_categories(env):
    database, owner, _ = env
    CategoryService(CategoryRepository(database)).create(owner, "bebidas")
    settings = build(env)
    settings.business_type.setCurrentText("Tienda")

    settings.apply_template()

    assert category_names(env) == ["Abarrotes", "bebidas", "Limpieza", "Lácteos", "Snacks"]


def test_a_category_can_be_added_and_the_field_is_cleared(env):
    settings = build(env)
    changes: list[bool] = []
    settings.business_changed.connect(lambda: changes.append(True))
    settings.category_name.setText("  Lácteos ")

    settings.add_category()

    assert category_names(env) == ["Lácteos"]
    assert list_texts(settings) == ["Lácteos"]
    assert settings.category_name.text() == ""
    assert settings.category_message.isHidden()
    assert changes == [True]


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("", "El nombre de la categoría es obligatorio."),
        ("   ", "El nombre de la categoría es obligatorio."),
        ("Snacks", "Ya existe una categoría con ese nombre."),
        ("snacks", "Ya existe una categoría con ese nombre."),
        ("x" * 41, "El nombre de la categoría no puede superar 40 caracteres."),
    ],
)
def test_category_names_are_validated_by_the_backend(env, name, message):
    database, owner, _ = env
    CategoryService(CategoryRepository(database)).create(owner, "Snacks")
    settings = build(env)
    changes: list[bool] = []
    settings.business_changed.connect(lambda: changes.append(True))
    settings.category_name.setText(name)

    settings.add_category()

    assert settings.category_message.text() == message
    assert category_names(env) == ["Snacks"]
    assert changes == []


def test_selecting_a_category_loads_its_name_for_renaming(env):
    database, owner, _ = env
    CategoryService(CategoryRepository(database)).create(owner, "Snacks")
    settings = build(env)

    select_category(settings, "Snacks")
    assert settings.category_name.text() == "Snacks"
    settings.category_name.setText("Botanas")
    settings.rename_category()

    assert category_names(env) == ["Botanas"]
    assert list_texts(settings) == ["Botanas"]


def test_renaming_without_a_selection_or_to_a_duplicate_is_rejected(env):
    database, owner, _ = env
    service = CategoryService(CategoryRepository(database))
    service.create(owner, "Snacks")
    service.create(owner, "Bebidas")
    settings = build(env)
    settings.category_name.setText("Otra")

    settings.rename_category()
    assert settings.category_message.text() == "Elegí una categoría de la lista."

    select_category(settings, "Snacks")
    settings.category_name.setText("Bebidas")
    settings.rename_category()
    assert settings.category_message.text() == "Ya existe una categoría con ese nombre."
    assert category_names(env) == ["Bebidas", "Snacks"]


def test_a_category_can_be_deactivated_and_activated_again(env):
    database, owner, _ = env
    CategoryService(CategoryRepository(database)).create(owner, "Snacks")
    settings = build(env)
    select_category(settings, "Snacks")
    assert settings.toggle_category_button.text() == "Desactivar"

    settings.toggle_category()

    assert list_texts(settings) == ["Snacks (inactiva)"]
    assert category_names(env, include_inactive=False) == []
    assert settings.toggle_category_button.text() == "Activar"
    settings.toggle_category()
    assert list_texts(settings) == ["Snacks"]
    assert category_names(env, include_inactive=False) == ["Snacks"]


def test_a_category_without_products_is_deleted_after_confirming(env):
    database, owner, _ = env
    CategoryService(CategoryRepository(database)).create(owner, "Snacks")
    confirm = Confirmations(True)
    settings = build(env, confirm=confirm)
    select_category(settings, "Snacks")

    settings.delete_category()

    assert confirm.asked == [
        ("Eliminar categoría", "¿Eliminar la categoría «Snacks»? Esta acción no se puede deshacer.")
    ]
    assert category_names(env) == []
    assert list_texts(settings) == []


def test_deleting_is_cancelled_when_the_owner_declines(env):
    database, owner, _ = env
    CategoryService(CategoryRepository(database)).create(owner, "Snacks")
    settings = build(env, confirm=Confirmations(False))
    select_category(settings, "Snacks")

    settings.delete_category()

    assert category_names(env) == ["Snacks"]


def test_a_category_with_products_cannot_be_deleted(env):
    database, owner, _ = env
    snacks = CategoryService(CategoryRepository(database)).create(owner, "Snacks")
    ProductRepository(database).add("A-1", "Papas", 100, 5, category_id=snacks.id)
    settings = build(env)
    select_category(settings, "Snacks")

    settings.delete_category()

    assert settings.category_message.text() == (
        "La categoría tiene productos; desactivala en lugar de eliminarla."
    )
    assert category_names(env) == ["Snacks"]


def test_the_backup_section_is_kept(env):
    settings = build(env)

    labels = {button.text() for button in settings.findChildren(type(settings.save_button))}

    assert {"Crear respaldo", "Restaurar respaldo", "Guardar configuración"} <= labels
