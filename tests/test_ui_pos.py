import inspect
import os
import sqlite3
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QPushButton
from sale_owner import owner_session

from suitelocal.application.auth import AuthService
from suitelocal.application.receipts import ReceiptService
from suitelocal.domain.auth import Session
from suitelocal.domain.business import BusinessSettings
from suitelocal.domain.models import Payment
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import (
    CategoryRepository,
    ProductRepository,
    SaleRepository,
)
from suitelocal.infrastructure.settings import BusinessSettingsRepository
from suitelocal.ui.components import ElidedLabel, KeyHint
from suitelocal.ui.components.product import ProductCard
from suitelocal.ui.pos import PosWidget, format_money
from suitelocal.ui.theme.manager import current_tokens, set_theme


def wait_until(condition, timeout_ms: int = 5000) -> bool:
    """Process events until ``condition()`` holds; True when it did before the timeout."""
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if condition():
            return True
        QTest.qWait(10)
    return bool(condition())


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_settings(qapp, tmp_path):
    """Keep the theme choice out of the user's real settings and start every test light."""
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings")
    )
    set_theme(qapp, "light", persist=False)
    yield
    set_theme(qapp, "light", persist=False)
    QSettings.setDefaultFormat(QSettings.Format.NativeFormat)


@pytest.fixture
def pos(qapp, tmp_path):
    database = Database(tmp_path / "pos.db")
    database.initialize()
    products = ProductRepository(database)
    products.add("A-1", "Arroz", 250, 10)
    products.add("B-2", "Frijol", 300, 5)
    widget = PosWidget(
        products,
        SaleRepository(database),
        ("cash", "transfer", "card"),
        # The general regime charges IVA, which these tests read from the totals.
        tax_regime="general",
        session=owner_session(database),
    )
    yield widget
    widget.deleteLater()


def shortcuts_for(widget: PosWidget, sequence: str) -> list[QShortcut]:
    expected = QKeySequence(sequence)
    return [shortcut for shortcut in widget.findChildren(QShortcut) if expected in shortcut.keys()]


def show_active(widget: PosWidget, width: int = 1208, height: int = 800) -> None:
    widget.resize(width, height)
    widget.show()
    widget.activateWindow()
    QTest.qWaitForWindowActive(widget)


def sale_count(widget: PosWidget) -> int:
    return widget.sales.today_summary()[0]


def stock_of(widget: PosWidget, code: str) -> int:
    return next(p.stock for p in widget.products.find_active(code) if p.code == code)


class FakeDialog:
    """Stands in for the modal PaymentDialog so no test ever blocks on ``exec``."""

    def __init__(self, payments: tuple[Payment, ...], accepted: bool = True) -> None:
        self.payments = payments if accepted else ()
        self.print_ticket = False
        self._accepted = accepted

    def exec(self) -> QDialog.DialogCode:
        return QDialog.DialogCode.Accepted if self._accepted else QDialog.DialogCode.Rejected

    def deleteLater(self) -> None:
        pass


def test_crossing_the_breakpoint_does_not_duplicate_shortcuts(pos):
    for width in (1200, 900, 1200, 900):
        pos._relayout(width)

    assert len(shortcuts_for(pos, "Delete")) == 1
    assert len(shortcuts_for(pos, "F2")) == 1
    assert len(shortcuts_for(pos, "F4")) == 1
    assert len(shortcuts_for(pos, "F9")) == 1


def test_crossing_the_breakpoint_keeps_the_selected_product(pos):
    pos.product_list.setCurrentRow(1)

    pos._relayout(1200)

    assert pos.product_list.currentRow() == 1


def test_confirm_shortcut_accepts_main_keyboard_enter(pos):
    assert len(shortcuts_for(pos, "Ctrl+Return")) == 1
    assert len(shortcuts_for(pos, "Ctrl+Enter")) == 1


# -- header, scanner, quantity prefix -----------------------------------------------------


def test_header_shows_the_serif_title_and_real_indicators(pos):
    assert pos.title_label.text() == "Nueva venta"
    assert pos.title_label.property("role") == "display"
    assert pos.eyebrow_label.text()
    assert [pos.kpi_sales.text(), pos.kpi_revenue.text(), pos.kpi_average.text()] == [
        "0",
        "$ 0,00",
        "—",
    ]


def test_scanner_texts_and_default_hint(pos):
    assert pos.search_input.placeholderText() == (
        "Escaneá el código o escribí el nombre del producto"
    )
    assert pos.quantity_hint.text() == "Cantidad ×1 · 3* multiplica"
    assert pos.reader_status.text() == "Lector listo"


def test_quantity_prefix_multiplies_the_scanned_product_and_resets(pos):
    pos.search_input.setText("3*B-2")
    assert pos.quantity_hint.text() == "Cantidad ×3 · 3* multiplica"

    pos.add_selected_product()

    assert [(line.product.code, line.quantity) for line in pos.cart.lines] == [("B-2", 3)]
    assert pos.search_input.text() == ""
    assert pos.quantity_hint.text() == "Cantidad ×1 · 3* multiplica"


def test_prefix_alone_arms_the_next_scan(pos):
    pos.search_input.setText("3*")
    QTest.keyClick(pos.search_input, Qt.Key.Key_Return)

    assert pos.cart.lines == ()
    assert pos.search_input.text() == ""
    assert pos.quantity_hint.text() == "Cantidad ×3 · 3* multiplica"

    pos.search_input.setText("B-2")
    QTest.keyClick(pos.search_input, Qt.Key.Key_Return)

    assert [(line.product.code, line.quantity) for line in pos.cart.lines] == [("B-2", 3)]
    assert pos.quantity_hint.text() == "Cantidad ×1 · 3* multiplica"


def test_prefix_beyond_stock_changes_nothing_and_reports_an_error(pos):
    notifications: list[tuple[str, str]] = []
    pos.notification.connect(lambda text, state: notifications.append((text, state)))
    pos.search_input.setText("2*B-2")
    pos.add_selected_product()
    pos.search_input.setText("4*B-2")

    pos.add_selected_product()

    assert [(line.product.code, line.quantity) for line in pos.cart.lines] == [("B-2", 2)]
    assert notifications and notifications[-1][1] == "danger"
    assert "Stock insuficiente" in notifications[-1][0]


def test_scanner_is_refocused_after_each_add(pos):
    show_active(pos)
    pos.quick_buttons[0].setFocus()

    pos.add_quick_product(0)

    assert QApplication.focusWidget() is pos.search_input


# -- quick keys ---------------------------------------------------------------------------


def test_quick_keys_show_the_first_four_products_with_name_and_price(pos):
    assert len(pos.quick_buttons) == 4
    first = pos.quick_buttons[0]
    assert "Arroz" in first.property("productName")
    assert first.property("priceText") == "$ 2,50"
    assert not pos.quick_buttons[2].isEnabled()


def test_quick_key_adds_the_product_when_focus_is_not_in_a_text_field(pos):
    show_active(pos)
    pos.quick_buttons[3].setFocus()

    QTest.keyClick(pos.quick_buttons[3], Qt.Key.Key_1)

    assert [(line.product.code, line.quantity) for line in pos.cart.lines] == [("A-1", 1)]


def test_quick_key_pressed_alone_in_the_empty_scanner_adds_after_a_short_pause(pos):
    show_active(pos)
    pos.quick_key_delay_ms = 10
    pos.search_input.setFocus()

    QTest.keyClick(pos.search_input, Qt.Key.Key_2)
    wait_until(lambda: bool(pos.cart.lines), 1000)

    assert [(line.product.code, line.quantity) for line in pos.cart.lines] == [("B-2", 1)]
    assert pos.search_input.text() == ""


def test_quick_key_is_ignored_while_typing_in_the_scanner(pos):
    show_active(pos)
    pos.quick_key_delay_ms = 10
    pos.search_input.setFocus()

    QTest.keyClicks(pos.search_input, "A-1")
    QTest.keyClick(pos.search_input, Qt.Key.Key_1)
    QTest.qWait(80)

    assert pos.cart.lines == ()
    assert pos.search_input.text() == "A-11"


def test_digits_of_a_barcode_never_trigger_a_quick_key(pos):
    show_active(pos)
    pos.quick_key_delay_ms = 40
    pos.search_input.setFocus()

    QTest.keyClicks(pos.search_input, "1234")
    QTest.qWait(120)

    assert pos.cart.lines == ()
    assert pos.search_input.text() == "1234"


# -- catalog grid -------------------------------------------------------------------------


def test_product_cards_show_name_meta_price_and_cart_quantity(pos):
    pos.search_input.setText("2*A-1")
    pos.add_selected_product()

    card = pos.product_list.card_at(0)

    assert card.name_label.full_text() == "Arroz"
    assert isinstance(card.name_label, ElidedLabel)
    assert card.meta_label.text() == "10 en stock"
    assert card.price_label.text() == "$ 2,50"
    assert card.badge.text() == "2"
    assert card.property("inCart") is True
    assert pos.product_list.card_at(1).badge.text() == "+"
    assert pos.product_list.card_at(1).property("inCart") is False


def test_art_tile_uses_a_deterministic_tint_and_the_initials(pos):
    card = pos.product_list.card_at(0)

    assert card.art.text() == "A"
    assert card.art.property("tint") in {1, 2, 3, 4, 5}
    again = PosWidget(pos.products, pos.sales).product_list.card_at(0)
    assert again.art.property("tint") == card.art.property("tint")


def test_low_stock_filter_shows_only_low_stock_products(pos):
    pos.products.add("C-3", "Cebolla", 100, 2)
    pos.products.add("D-4", "Dátil", 100, 0)
    pos.refresh_products()
    assert pos.filter_control.current == "Todos"
    assert pos.product_list.count() == 4

    pos.filter_control.select("Stock bajo")
    pos.filter_control.selected.emit("Stock bajo")

    names = [
        pos.product_list.card_at(i).name_label.full_text() for i in range(pos.product_list.count())
    ]
    assert names == ["Cebolla", "Dátil"]
    assert pos.product_list.card_at(0).tag_label.text() == "Quedan 2"
    assert pos.product_list.card_at(1).tag_label.text() == "Sin stock"
    assert pos.filter_control.current == "Stock bajo"


def test_filter_only_offers_all_and_low_stock(pos):
    assert list(pos.filter_control._buttons) == ["Todos", "Stock bajo"]


def test_grid_columns_follow_the_available_width(pos):
    show_active(pos, 1208)
    assert wait_until(lambda: pos.product_list.columns == 4)

    show_active(pos, 1028)
    assert wait_until(lambda: pos.product_list.columns == 3)


def test_clicking_a_card_adds_the_product(pos):
    pos.product_list.card_at(1).click()

    assert [(line.product.code, line.quantity) for line in pos.cart.lines] == [("B-2", 1)]


# -- ticket -------------------------------------------------------------------------------


def test_ticket_panel_lines_stepper_and_summary(pos):
    assert pos.ticket_panel.objectName() == "ticketPanel"
    assert pos.sale_title.text() == "Venta actual"
    assert pos.customer_label.text() == "Consumidor final"
    pos.search_input.setText("2*A-1")
    pos.add_selected_product()
    pos.search_input.setText("B-2")
    pos.add_selected_product()

    first, second = pos.ticket_lines
    assert first.subtitle_label.text() == "2 × $ 2,50"
    assert first.total_label.text() == "$ 5,00"
    assert second.property("highlighted") is True
    assert first.property("highlighted") is False
    assert pos.total_label.text() == "$ 8,00"
    # Prices include IVA: 800 total = 696 base + 104 IVA at 15 % (rounded per line).
    assert pos.subtotal_label.text() == "Subtotal $ 6,96"
    assert pos.tax_label.text() == "IVA incluido $ 1,04"
    assert pos.cart_count.text() == "3 artículos"

    first.plus_button.click()
    assert pos.cart.lines[0].quantity == 3
    first.minus_button.click()
    first.minus_button.click()
    assert pos.cart.lines[0].quantity == 1


def test_stepper_minus_on_the_last_unit_removes_the_line(pos):
    pos.add_quick_product(0)

    pos.ticket_lines[0].minus_button.click()

    assert pos.cart.lines == ()
    assert pos.ticket_lines == []


def test_there_are_no_dead_buttons(pos):
    texts = {button.text() for button in pos.findChildren(QPushButton)}

    assert not texts & {"Descuento", "Suspender", "Asignar cliente", "Asignar"}
    assert "Dividir pago" in texts


def test_no_savings_line_is_shown(pos):
    from PySide6.QtWidgets import QLabel

    assert not any("Ahorro" in label.text() for label in pos.findChildren(QLabel))


# -- inline checkout ----------------------------------------------------------------------


def test_methods_are_limited_to_the_enabled_ones(qapp, pos):
    assert list(pos.method_control._buttons) == ["Efectivo", "Transferencia", "Tarjeta"]
    only_cash = PosWidget(pos.products, pos.sales, ("cash",))
    assert list(only_cash.method_control._buttons) == ["Efectivo"]


def test_cash_change_is_received_minus_total(pos):
    pos.add_quick_product(0)

    pos.received_edit.setText("5.00")

    assert pos.change_value.text() == "$ 2,50"
    pos.received_edit.setText("2.50")
    assert pos.change_value.text() == "$ 0,00"


def test_exact_button_sets_received_to_the_total(pos):
    pos.add_quick_product(0)
    assert pos.bill_buttons[0].text() == "Exacto"

    pos.bill_buttons[0].click()

    assert pos.received_edit.text() == "2.50"
    assert pos.change_value.text() == "$ 0,00"


def test_quick_bills_are_round_amounts_above_the_total(pos):
    pos.add_quick_product(0)

    labels = [button.text() for button in pos.bill_buttons]

    assert labels == ["Exacto", "$ 3,00", "$ 5,00", "$ 10,00"]
    pos.bill_buttons[2].click()
    assert pos.received_edit.text() == "5.00"
    assert pos.change_value.text() == "$ 2,50"


def test_charge_with_enough_cash_registers_the_sale_and_clears_the_checkout(pos):
    notifications: list[tuple[str, str]] = []
    registered: list[bool] = []
    pos.notification.connect(lambda text, state: notifications.append((text, state)))
    pos.sale_registered.connect(lambda: registered.append(True))
    pos.add_quick_product(0)
    pos.received_edit.setText("5.00")

    pos.charge_button.click()

    assert sale_count(pos) == 1
    assert stock_of(pos, "A-1") == 9
    assert registered == [True]
    assert notifications[-1][1] == "success"
    assert "Vuelto: $ 2,50" in notifications[-1][0]
    assert pos.cart.lines == ()
    assert pos.received_edit.text() == ""
    assert not pos.checkout_message.isVisible()


def test_charging_without_a_session_registers_nothing(pos):
    pos.session = None
    notifications: list[tuple[str, str]] = []
    pos.notification.connect(lambda text, state: notifications.append((text, state)))
    pos.add_quick_product(0)
    pos.received_edit.setText("5.00")

    pos.charge_button.click()

    assert notifications[-1] == ("No se puede confirmar. No hay una sesión iniciada.", "danger")
    assert sale_count(pos) == 0
    assert stock_of(pos, "A-1") == 10
    assert len(pos.cart.lines) == 1


def test_charge_with_insufficient_cash_shows_an_inline_error_and_changes_nothing(pos):
    show_active(pos)
    pos.add_quick_product(0)
    pos.received_edit.setText("1.00")

    pos.charge_button.click()

    assert pos.checkout_message.isVisible()
    assert pos.checkout_message.text() == "El efectivo recibido no cubre el total."
    assert pos.checkout_message.property("state") == "error"
    assert sale_count(pos) == 0
    assert stock_of(pos, "A-1") == 10
    assert len(pos.cart.lines) == 1


def test_transfer_without_reference_is_rejected_and_with_reference_charges(pos):
    show_active(pos)
    pos.add_quick_product(0)
    pos.method_control.select("Transferencia")
    pos.method_control.selected.emit("Transferencia")
    assert pos.reference_edit.isVisible()
    assert not pos.received_edit.isVisible()

    pos.charge_button.click()

    assert pos.checkout_message.text() == "La transferencia necesita un número de referencia."
    assert sale_count(pos) == 0
    assert stock_of(pos, "A-1") == 10

    pos.reference_edit.setText("TR-991")
    pos.charge_button.click()

    assert sale_count(pos) == 1
    assert stock_of(pos, "A-1") == 9


def test_card_payment_charges_the_exact_total(pos):
    pos.add_quick_product(0)
    pos.method_control.select("Tarjeta")
    pos.method_control.selected.emit("Tarjeta")

    pos.charge_button.click()

    assert sale_count(pos) == 1


def test_charge_button_label_and_state(pos):
    assert pos.charge_button.text() == "Cobrar"
    assert not pos.charge_button.isEnabled()
    pos.add_quick_product(0)
    assert pos.charge_button.isEnabled()
    assert pos.charge_hint.text() == "F4"
    assert pos.split_button.text() == "Dividir pago"
    assert pos.split_hint.text() == "F9"


def test_split_payment_opens_the_dialog_through_the_injected_factory(pos):
    calls: list[dict] = []

    def factory(**kwargs):
        calls.append(kwargs)
        return FakeDialog((Payment("cash", 300), Payment("transfer", 200, "TR-1")))

    pos.payment_dialog_factory = factory
    pos.search_input.setText("2*A-1")
    pos.add_selected_product()

    pos.split_button.click()

    assert calls and calls[0]["total_cents"] == 500
    # 500 at 15 %: the price is final and 65 of it is IVA.
    assert calls[0]["total_note"] == "IVA incluido $ 0,65"
    assert calls[0]["enabled_methods"] == ("cash", "transfer", "card")
    assert sale_count(pos) == 1
    assert stock_of(pos, "A-1") == 8


def test_format_money_delegates_to_the_usd_formatter():
    assert format_money(123_456) == "$ 1.234,56"
    assert format_money(123_456, "$", ".") == "$ 1,234.56"
    assert format_money(-123_456) == "-$ 1.234,56"
    assert format_money(5, "US$") == "US$ 0,05"


def test_ticket_shows_the_tax_included_in_mixed_rates(pos):
    pos.products.add("Z-9", "Pan", 200, 5, tax_rate_basis_points=0)
    pos.refresh_products()
    pos.search_input.setText("A-1")
    pos.add_selected_product()
    pos.search_input.setText("Z-9")
    pos.add_selected_product()

    assert pos.total_label.text() == "$ 4,50"
    assert pos.subtotal_label.text() == "Subtotal $ 4,17"
    assert pos.tax_label.text() == "IVA incluido $ 0,33"


def test_cancelled_split_dialog_registers_nothing(pos):
    pos.payment_dialog_factory = lambda **kwargs: FakeDialog((), accepted=False)
    pos.add_quick_product(0)

    pos.split_button.click()

    assert sale_count(pos) == 0
    assert len(pos.cart.lines) == 1


def test_confirm_sale_seam_accepts_explicit_payments(pos):
    pos.add_quick_product(0)

    pos.confirm_sale((Payment("cash", 250),))

    assert sale_count(pos) == 1


def test_confirm_sale_on_an_empty_cart_reports_a_danger_notification(pos):
    notifications: list[tuple[str, str]] = []
    pos.notification.connect(lambda text, state: notifications.append((text, state)))

    pos.confirm_sale()

    assert notifications == [("No se puede cobrar. Agrega al menos un producto.", "danger")]


def test_kpis_show_real_values_after_a_sale(pos):
    pos.search_input.setText("2*A-1")
    pos.add_selected_product()
    pos.received_edit.setText("5.00")
    pos.charge_button.click()
    pos.add_quick_product(1)
    pos.received_edit.setText("3.00")
    pos.charge_button.click()

    assert pos.kpi_sales.text() == "2"
    assert pos.kpi_revenue.text() == "$ 8,00"
    assert pos.kpi_average.text() == "$ 4,00"


# -- theme --------------------------------------------------------------------------------


def test_theme_switch_retints_the_pos_widgets(qapp, pos):
    # Qt applies style sheets only to polished widgets, so the screen must be shown first.
    show_active(pos)
    card = pos.product_list.card_at(0)
    tint = card.art.property("tint")
    light = current_tokens()
    light_pixel = card.art.grab().toImage().pixelColor(card.art.width() // 2, 3).name()
    light_icon = pos.scan_icon.pixmap().toImage()
    assert light_pixel.upper() == getattr(light, f"art_{tint}").upper()

    set_theme(qapp, "dark", persist=False)

    dark = current_tokens()
    dark_pixel = card.art.grab().toImage().pixelColor(card.art.width() // 2, 3).name()
    assert dark_pixel.upper() == getattr(dark, f"art_{tint}").upper()
    assert dark_pixel != light_pixel
    assert pos.scan_icon.pixmap().toImage() != light_icon


# -- layout regressions found in rendered screenshots ---------------------------------------


def test_pos_fits_the_content_area_of_a_1366_px_screen(pos):
    # 1366 px minus the expanded rail leaves about 1134 px for the page.
    assert pos.minimumSizeHint().width() <= 1100


def test_fixed_size_controls_are_not_squashed_by_the_stylesheet(pos):
    show_active(pos, 1100, 760)
    card = pos.product_list.card_at(0)

    assert card.height() >= ProductCard.HEIGHT
    assert pos.quick_buttons[0].height() >= 52
    for hint in pos.findChildren(KeyHint):
        if hint.isVisible():
            assert hint.height() < 30, hint.text()


def test_product_art_paints_an_opaque_tint(pos):
    show_active(pos)
    art = pos.product_list.card_at(0).art

    pixel = art.grab().toImage().pixelColor(art.width() // 2, art.height() // 2)

    assert pixel.alpha() == 255
    assert pixel.name().upper() == getattr(current_tokens(), f"art_{art.property('tint')}").upper()


# -- business profile: categories filter, separator, live settings --------------------------


@pytest.fixture
def catalog(qapp, tmp_path):
    """A catalog with two categories, one empty category and one inactive category."""
    database = Database(tmp_path / "catalog.db")
    database.initialize()
    with database.connect() as connection:
        business_id = connection.execute(
            "INSERT INTO businesses (name) VALUES ('Tienda')"
        ).lastrowid
    assert business_id is not None
    categories = CategoryRepository(database)
    bebidas = categories.add(business_id, "Bebidas")
    snacks = categories.add(business_id, "Snacks")
    categories.add(business_id, "Vacía")
    hidden = categories.add(business_id, "Oculta")
    categories.set_active(business_id, hidden.id, False)
    products = ProductRepository(database)
    products.add("C-1", "Cola", 150, 10, category_id=bebidas.id)
    products.add("S-1", "Papas", 100, 2, category_id=snacks.id)
    products.add("H-1", "Fantasma", 100, 5, category_id=hidden.id)
    products.add("X-1", "Sin categoría", 200, 5)
    sales = SaleRepository(database)
    return products, sales, categories.list(business_id)


def filter_options(widget: PosWidget) -> list[str]:
    return [button.text() for button in widget.filter_control.findChildren(QPushButton)]


def product_names(widget: PosWidget) -> list[str]:
    shown = (widget.product_list.product_at(row) for row in range(widget.product_list.count()))
    return [product.name for product in shown if product is not None]


def test_pos_drops_the_ignored_tax_rate_parameter():
    assert "tax_rate_basis_points" not in inspect.signature(PosWidget).parameters


def test_filter_lists_categories_with_products_when_the_module_is_on(catalog):
    products, sales, categories = catalog

    pos = PosWidget(
        products,
        sales,
        enabled_modules=frozenset({"categorias"}),
        categories=categories,
    )

    assert filter_options(pos) == ["Todos", "Bebidas", "Snacks", "Stock bajo"]


def test_filter_by_category_shows_only_its_products(catalog):
    products, sales, categories = catalog
    pos = PosWidget(
        products, sales, enabled_modules=frozenset({"categorias"}), categories=categories
    )
    assert product_names(pos) == ["Cola", "Fantasma", "Papas", "Sin categoría"]

    pos.filter_control.select("Snacks")
    pos.filter_control.selected.emit("Snacks")

    assert product_names(pos) == ["Papas"]
    pos.filter_control.select("Stock bajo")
    pos.filter_control.selected.emit("Stock bajo")
    assert product_names(pos) == ["Papas"]
    pos.filter_control.select("Todos")
    pos.filter_control.selected.emit("Todos")
    assert len(product_names(pos)) == 4


def test_filter_stays_as_today_without_the_module_or_without_categories(catalog):
    products, sales, categories = catalog

    module_off = PosWidget(products, sales, categories=categories)
    no_categories = PosWidget(products, sales, enabled_modules=frozenset({"categorias"}))

    assert filter_options(module_off) == ["Todos", "Stock bajo"]
    assert filter_options(no_categories) == ["Todos", "Stock bajo"]


def test_a_selected_category_that_disappears_falls_back_to_all(catalog):
    products, sales, categories = catalog
    pos = PosWidget(
        products, sales, enabled_modules=frozenset({"categorias"}), categories=categories
    )
    pos.filter_control.select("Snacks")
    pos.filter_control.selected.emit("Snacks")

    pos.apply_business(business_settings(), [])

    assert filter_options(pos) == ["Todos", "Stock bajo"]
    assert pos.filter_control.current == "Todos"
    assert len(product_names(pos)) == 4


def business_settings(**changes) -> BusinessSettings:
    values = {
        "business_id": 1,
        "name": "Tienda",
        "currency_symbol": "$",
        "low_stock_threshold": 3,
        "enabled_payment_methods": ("cash", "transfer"),
        "tax_regime": "general",
    }
    return BusinessSettings(**{**values, **changes})


def test_apply_business_reformats_money_with_the_new_separator(pos):
    pos.add_quick_product(0)
    assert pos.total_label.text() == "$ 2,50"
    assert pos.quick_buttons[0].property("priceText") == "$ 2,50"
    assert pos.received_edit.placeholderText() == "0,00"

    pos.apply_business(business_settings(decimal_separator="."), [])

    assert pos.total_label.text() == "$ 2.50"
    assert pos.subtotal_label.text() == "Subtotal $ 2.17"
    assert pos.tax_label.text() == "IVA incluido $ 0.33"
    assert pos.quick_buttons[0].property("priceText") == "$ 2.50"
    assert pos.product_list.card_at(0).price_label.text() == "$ 2.50"
    assert pos.received_edit.placeholderText() == "0.00"
    assert pos.charge_amount.text() == "$ 2.50"


def test_apply_business_updates_payment_methods_and_low_stock_threshold(pos):
    pos.apply_business(
        business_settings(enabled_payment_methods=("cash",), low_stock_threshold=7), []
    )

    assert [b.text() for b in pos.method_control.findChildren(QPushButton)] == ["Efectivo"]
    assert pos.enabled_payment_methods == ("cash",)
    assert pos.low_stock_threshold == 7


def test_split_payment_dialog_receives_the_decimal_separator(pos):
    calls: list[dict] = []

    def factory(**kwargs):
        calls.append(kwargs)
        return FakeDialog((Payment("cash", 250),))

    pos.payment_dialog_factory = factory
    pos.apply_business(business_settings(decimal_separator="."), [])
    pos.add_quick_product(0)

    pos.split_button.click()

    assert calls[0]["decimal_separator"] == "."
    assert calls[0]["total_note"] == "IVA incluido $ 0.33"


# -- ticket printing -----------------------------------------------------------------------


class FakeReceiptOutput:
    """Records the receipts it is asked to print; nothing reaches a printer."""

    def __init__(self, error: Exception | None = None) -> None:
        self.printed: list = []
        self.error = error

    def print_receipt(self, receipt) -> None:
        if self.error is not None:
            raise self.error
        self.printed.append(receipt)


class Wired:
    """A POS with a signed-in user and a fake printer, plus what it announced."""

    def __init__(self, tmp_path, regime: str = "sin_registro", error: Exception | None = None):
        self.database = Database(tmp_path / "wired.db")
        self.database.initialize()
        auth = AuthService(self.database)
        self.owner = Session(
            auth.setup_owner("Tienda Sol", "owner", "clave-segura", "clave-segura")
        )
        self.cashier = Session(
            auth.create_cashier(self.owner, "cajero", "clave-cajero", "clave-cajero")
        )
        if regime != "sin_registro":
            BusinessSettingsRepository(self.database).update_profile(
                self.owner.user.business_id, tax_regime=regime, ruc="1790012345001"
            )
        self.products = ProductRepository(self.database)
        self.rice = self.products.add("A-1", "Arroz", 250, 10)
        self.output = FakeReceiptOutput(error)
        self.pos = PosWidget(
            self.products,
            SaleRepository(self.database),
            ("cash", "transfer", "card"),
            tax_regime=regime,
            session=self.cashier,
            receipts=ReceiptService(self.database),
            receipt_output=self.output,
        )
        self.notifications: list[tuple[str, str]] = []
        self.registered = 0
        self.pos.notification.connect(lambda text, state: self.notifications.append((text, state)))
        self.pos.sale_registered.connect(self._count)

    def _count(self) -> None:
        self.registered += 1

    def add_rice(self) -> None:
        self.pos._add_product(self.products.find_active("A-1")[0])

    def sale_row(self) -> sqlite3.Row:
        with self.database.connect() as connection:
            return connection.execute("SELECT * FROM sales ORDER BY id DESC LIMIT 1").fetchone()


@pytest.fixture
def wired(qapp, tmp_path):
    return Wired(tmp_path)


def test_a_wired_pos_offers_the_print_switch_on_by_default(wired):
    assert wired.pos.can_print_ticket is True
    assert wired.pos.print_switch.isChecked() is True
    assert wired.pos.print_switch.isVisibleTo(wired.pos)
    assert wired.pos.charge_button.text() == "Cobrar e imprimir"


def test_toggling_the_switch_changes_the_charge_label(wired):
    wired.pos.print_switch.setChecked(False)
    assert wired.pos.charge_button.text() == "Cobrar"

    wired.pos.print_switch.setChecked(True)
    assert wired.pos.charge_button.text() == "Cobrar e imprimir"


def test_a_pos_without_a_printer_has_no_switch_and_never_prints(pos):
    assert pos.can_print_ticket is False
    assert not pos.print_switch.isVisibleTo(pos)
    assert not pos.reprint_button.isVisibleTo(pos)
    assert pos.charge_button.text() == "Cobrar"


def test_inline_sale_prints_the_stored_receipt_once(wired):
    wired.add_rice()
    wired.pos.received_edit.setText("5.00")

    wired.pos.confirm_sale()

    assert wired.registered == 1
    assert len(wired.output.printed) == 1
    receipt = wired.output.printed[0]
    assert (receipt.number, receipt.total_cents, receipt.change_cents) == ("000001", 250, 250)
    assert receipt.cashier == "cajero"
    assert [(line.name, line.quantity) for line in receipt.lines] == [("Arroz", 1)]


def test_inline_sale_does_not_print_when_the_switch_is_off(wired):
    wired.add_rice()
    wired.pos.received_edit.setText("5.00")
    wired.pos.print_switch.setChecked(False)

    wired.pos.confirm_sale()

    assert wired.output.printed == []
    assert wired.registered == 1


def test_split_sale_follows_the_dialog_switch(wired):
    wired.pos.payment_dialog_factory = lambda **_kwargs: dialog
    for wanted in (True, False):
        wired.add_rice()
        dialog = FakeDialog((Payment("cash", 250),))
        dialog.print_ticket = wanted

        wired.pos.open_split_payment()

    assert wired.registered == 2
    assert len(wired.output.printed) == 1


def test_a_failed_sale_does_not_print(wired):
    wired.add_rice()
    wired.pos.received_edit.setText("1.00")

    wired.pos.confirm_sale()

    assert wired.registered == 0
    assert wired.output.printed == []


def test_a_printer_failure_warns_and_keeps_the_sale(qapp, tmp_path):
    wired = Wired(tmp_path, error=RuntimeError("La impresora no está disponible."))
    wired.add_rice()
    wired.pos.received_edit.setText("5.00")

    wired.pos.confirm_sale()

    assert wired.notifications[-1] == (
        "No se pudo imprimir el ticket: La impresora no está disponible.",
        "warning",
    )
    assert wired.registered == 1
    assert wired.pos.sales.today_summary() == (1, 250)
    assert stock_of(wired.pos, "A-1") == 9
    assert wired.pos.cart.lines == ()


def test_the_sale_stores_the_business_and_the_seller(wired):
    wired.add_rice()
    wired.pos.received_edit.setText("5.00")

    wired.pos.confirm_sale()

    row = wired.sale_row()
    assert (row["business_id"], row["user_id"]) == (
        wired.cashier.user.business_id,
        wired.cashier.user.id,
    )


def test_ctrl_p_reprints_the_last_ticket(wired):
    assert len(shortcuts_for(wired.pos, "Ctrl+P")) == 1
    wired.add_rice()
    wired.pos.received_edit.setText("5.00")
    wired.pos.confirm_sale()
    wired.output.printed.clear()

    show_active(wired.pos)
    QTest.keyClick(wired.pos, Qt.Key.Key_P, Qt.KeyboardModifier.ControlModifier)

    assert [receipt.number for receipt in wired.output.printed] == ["000001"]


def test_reprint_button_prints_the_last_ticket_even_when_it_was_not_printed_before(wired):
    wired.add_rice()
    wired.pos.received_edit.setText("5.00")
    wired.pos.print_switch.setChecked(False)
    wired.pos.confirm_sale()
    assert wired.output.printed == []

    wired.pos.reprint_button.click()

    assert [receipt.number for receipt in wired.output.printed] == ["000001"]


def test_reprint_without_any_sale_explains_itself(wired):
    wired.pos.reprint_button.click()

    assert wired.output.printed == []
    assert wired.notifications[-1] == ("Todavía no hay un ticket para reimprimir.", "info")


def test_reprint_failure_warns(qapp, tmp_path):
    wired = Wired(tmp_path)
    wired.add_rice()
    wired.pos.received_edit.setText("5.00")
    wired.pos.confirm_sale()
    wired.output.error = RuntimeError("sin papel")

    wired.pos.reprint_last_ticket()

    assert wired.notifications[-1] == ("No se pudo imprimir el ticket: sin papel", "warning")


def test_ctrl_p_does_nothing_without_a_printer(pos):
    notifications: list[tuple[str, str]] = []
    pos.notification.connect(lambda text, state: notifications.append((text, state)))

    assert pos.reprint_last_ticket() is False

    assert notifications == []


# -- sales note number (RIMPE popular) -----------------------------------------------------


def test_the_sales_note_field_exists_only_for_rimpe_popular(qapp, tmp_path):
    popular = Wired(tmp_path / "a", "rimpe_popular")
    general = Wired(tmp_path / "b", "general")
    unregistered = Wired(tmp_path / "c")

    assert popular.pos.sales_note_edit.isVisibleTo(popular.pos)
    assert not general.pos.sales_note_edit.isVisibleTo(general.pos)
    assert not unregistered.pos.sales_note_edit.isVisibleTo(unregistered.pos)
    assert popular.pos.sales_note_edit.placeholderText() == "N.º de nota de venta (opcional)"


def test_the_sales_note_field_follows_the_saved_regime(wired):
    repo = BusinessSettingsRepository(wired.database)
    business_id = wired.owner.user.business_id

    wired.pos.apply_business(repo.update_profile(business_id, tax_regime="rimpe_popular"), ())
    assert wired.pos.sales_note_edit.isVisibleTo(wired.pos)

    wired.pos.apply_business(repo.update_profile(business_id, tax_regime="sin_registro"), ())
    assert not wired.pos.sales_note_edit.isVisibleTo(wired.pos)


def test_popular_sale_stores_the_note_shows_it_on_the_receipt_and_clears_the_field(qapp, tmp_path):
    wired = Wired(tmp_path, "rimpe_popular")
    wired.add_rice()
    wired.pos.received_edit.setText("5.00")
    wired.pos.sales_note_edit.setText("  001-001-000123 ")

    wired.pos.confirm_sale()

    assert wired.sale_row()["sales_note_number"] == "001-001-000123"
    assert wired.output.printed[0].sales_note_number == "001-001-000123"
    assert wired.pos.sales_note_edit.text() == ""


def test_popular_sale_without_a_note_stores_none(qapp, tmp_path):
    wired = Wired(tmp_path, "rimpe_popular")
    wired.add_rice()
    wired.pos.received_edit.setText("5.00")

    wired.pos.confirm_sale()

    assert wired.sale_row()["sales_note_number"] is None
    assert wired.output.printed[0].sales_note_number is None


def test_a_hidden_sales_note_is_never_stored_for_other_regimes(wired):
    wired.add_rice()
    wired.pos.received_edit.setText("5.00")
    wired.pos.sales_note_edit.setText("001-001-000123")

    wired.pos.confirm_sale()

    assert wired.sale_row()["sales_note_number"] is None
    assert wired.output.printed[0].sales_note_number is None


def test_sales_note_input_is_limited_to_the_stored_length(qapp, tmp_path):
    wired = Wired(tmp_path, "rimpe_popular")

    assert wired.pos.sales_note_edit.maxLength() == 30
