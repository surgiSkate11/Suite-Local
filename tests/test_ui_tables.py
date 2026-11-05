import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import re
from datetime import datetime
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QPushButton

from suitelocal.application.auth import AuthService
from suitelocal.application.tables import TablesService
from suitelocal.domain.auth import Session
from suitelocal.domain.models import Payment
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import ProductRepository
from suitelocal.infrastructure.tables_repository import ensure_tables_schema
from suitelocal.ui.tables import TablesWidget

OPENED_AT = "2026-01-01 10:00:00"
NOW = datetime(2026, 1, 1, 10, 7, 30)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class FakeDialog:
    """Stands in for the modal PaymentDialog so no test ever blocks on ``exec``."""

    def __init__(self, payments: tuple[Payment, ...], accepted: bool = True) -> None:
        self.payments = payments if accepted else ()
        self._accepted = accepted

    def exec(self) -> QDialog.DialogCode:
        return QDialog.DialogCode.Accepted if self._accepted else QDialog.DialogCode.Rejected

    def deleteLater(self) -> None:
        pass


class Env:
    def __init__(self, tmp_path: Path) -> None:
        self.database = Database(tmp_path / "ui_tables.db")
        self.database.initialize()
        with self.database.connect() as connection:
            ensure_tables_schema(connection)
        auth = AuthService(self.database)
        self.owner = Session(auth.setup_owner("Café", "dueno", "Clave-segura-1", "Clave-segura-1"))
        self.cashier = Session(
            auth.create_cashier(self.owner, "cajero", "Clave-segura-2", "Clave-segura-2")
        )
        self.products = ProductRepository(self.database)
        self.coffee = self.products.add("C-1", "Café", 150, 10)
        self.cake = self.products.add("T-1", "Torta", 300, 4)
        self.service = TablesService(self.database)
        self.table_1 = self.service.create_table(self.owner, "Mesa 1", "Salón")
        self.table_2 = self.service.create_table(self.owner, "Mesa 2", "Terraza")
        self.notifications: list[tuple[str, str]] = []
        self.dialog_calls: list[dict] = []
        self.dialog_payments: tuple[Payment, ...] = ()
        self.dialog_accepted = True
        self.confirm_answer = False
        self.chosen_table: int | None = None

    def dialog_factory(self, **kwargs) -> FakeDialog:
        self.dialog_calls.append(kwargs)
        return FakeDialog(self.dialog_payments, self.dialog_accepted)

    def build(self, session: Session | None = None) -> TablesWidget:
        widget = TablesWidget(
            self.service,
            self.products,
            session or self.owner,
            currency_symbol="$",
            enabled_payment_methods=("cash", "transfer"),
            tax_rate_basis_points=0,
            payment_dialog_factory=self.dialog_factory,
            now=lambda: NOW,
            table_chooser=lambda _parent, free: self.chosen_table,
            confirmer=lambda _parent, _title, _text: self.confirm_answer,
        )
        widget.notification.connect(lambda text, state: self.notifications.append((text, state)))
        return widget

    def set_opened_at(self, order_id: int) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE table_orders SET opened_at = ? WHERE id = ?", (OPENED_AT, order_id)
            )

    def stock(self, product) -> int:
        return next(p.stock for p in self.products.find_active("") if p.id == product.id)

    def count(self, table: str) -> int:
        with self.database.connect() as connection:
            return connection.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]


@pytest.fixture
def env(qapp, tmp_path):
    return Env(tmp_path)


def card(widget: TablesWidget, table_id: int):
    return next(c for c in widget.cards if c.table_id == table_id)


def type_and_enter(widget: TablesWidget, text: str) -> None:
    widget.search.setText(text)
    QTest.keyClick(widget.search, Qt.Key.Key_Return)


def line_texts(widget: TablesWidget) -> list[tuple[str, ...]]:
    table = widget.lines_table
    return [
        tuple(table.item(row, column).text() for column in range(5))
        for row in range(table.rowCount())
    ]


def open_with_coffee(env: Env, widget: TablesWidget, quantity: int = 2) -> int:
    widget.select_table(env.table_1.id)
    widget.open_account()
    for _ in range(quantity):
        type_and_enter(widget, "caf")
    order = env.service.get_order(env.owner, env.table_1.id)
    assert order is not None
    return order.id


def test_grid_shows_free_and_occupied_tables_with_amount_and_minutes(env):
    order = env.service.open_order(env.owner, env.table_1.id)
    env.service.add_product(env.owner, order.id, env.coffee.id, 2)
    env.service.add_product(env.owner, order.id, env.cake.id, 1)
    env.set_opened_at(order.id)

    widget = env.build()

    busy, free = card(widget, env.table_1.id), card(widget, env.table_2.id)
    assert (busy.name_text, busy.zone_text, busy.status_text) == ("Mesa 1", "Salón", "Ocupada")
    assert busy.detail_text == "$6.00 · 7 min"
    assert (free.name_text, free.zone_text, free.status_text) == ("Mesa 2", "Terraza", "Libre")
    assert free.detail_text == ""


def test_selecting_a_free_table_offers_to_open_the_account(env):
    widget = env.build()
    assert not widget.open_button.isVisibleTo(widget)
    assert "Elegí una mesa para ver su cuenta." in widget.placeholder_text

    card(widget, env.table_2.id).click()

    assert widget.selected_table_id == env.table_2.id
    assert widget.open_button.text() == "Abrir cuenta"
    assert widget.open_button.isVisibleTo(widget)
    assert not widget.charge_button.isVisibleTo(widget)

    widget.open_button.click()

    assert env.service.get_order(env.owner, env.table_2.id) is not None
    assert not widget.open_button.isVisibleTo(widget)
    assert widget.charge_button.isVisibleTo(widget)
    assert card(widget, env.table_2.id).status_text == "Ocupada"


def test_search_enter_adds_first_match_and_updates_panel_and_card(env):
    widget = env.build()
    widget.select_table(env.table_1.id)
    widget.open_account()

    type_and_enter(widget, "caf")
    type_and_enter(widget, "caf")

    assert line_texts(widget) == [("Café", "2", "$1.50", "$3.00", "Pendiente")]
    assert widget.search.text() == ""
    assert card(widget, env.table_1.id).detail_text.startswith("$3.00")
    assert widget.total_label.text() == "$3.00"
    assert env.stock(env.coffee) == 10


def test_search_without_match_notifies_and_adds_nothing(env):
    widget = env.build()
    widget.select_table(env.table_1.id)
    widget.open_account()

    type_and_enter(widget, "zzz")

    assert widget.lines_table.rowCount() == 0
    assert env.notifications[-1][1] == "info"


def line_button(widget: TablesWidget, row: int, prefix: str) -> QPushButton:
    buttons = widget.lines_table.cellWidget(row, 5).findChildren(QPushButton)
    return next(b for b in buttons if b.accessibleName().startswith(prefix))


def test_quantity_buttons_change_and_remove_lines(env):
    widget = env.build()
    open_with_coffee(env, widget, 1)

    line_button(widget, 0, "Aumentar").click()
    assert line_texts(widget)[0][1] == "2"
    line_button(widget, 0, "Disminuir").click()
    assert line_texts(widget)[0][1] == "1"
    line_button(widget, 0, "Quitar").click()
    assert line_texts(widget) == []
    assert card(widget, env.table_1.id).status_text == "Ocupada"


def test_send_to_kitchen_notifies_and_marks_lines_then_reports_nothing_new(env):
    widget = env.build()
    open_with_coffee(env, widget, 2)
    type_and_enter(widget, "tor")

    widget.send_button.click()

    assert env.notifications[-1][1] == "success"
    assert "2 × Café" in env.notifications[-1][0]
    assert "1 × Torta" in env.notifications[-1][0]
    assert [row[4] for row in line_texts(widget)] == ["En cocina", "En cocina"]

    widget.send_button.click()

    assert env.notifications[-1] == ("No hay productos nuevos para enviar.", "info")


def test_charge_registers_one_sale_decrements_stock_and_frees_the_table(env):
    widget = env.build()
    order_id = open_with_coffee(env, widget, 2)
    env.dialog_payments = (Payment("cash", 500),)

    widget.charge_button.click()

    assert env.dialog_calls[0]["total_cents"] == 300
    assert env.dialog_calls[0]["currency_symbol"] == "$"
    assert env.dialog_calls[0]["enabled_methods"] == ("cash", "transfer")
    assert env.count("sales") == 1
    assert env.stock(env.coffee) == 8
    assert env.service.get_order(env.owner, env.table_1.id) is None
    assert card(widget, env.table_1.id).status_text == "Libre"
    text, state = env.notifications[-1]
    assert state == "success"
    assert text.startswith("Mesa 1 cobrada · Venta N.º ")
    assert order_id


def test_cancelled_payment_dialog_charges_nothing(env):
    widget = env.build()
    open_with_coffee(env, widget, 2)
    env.dialog_accepted = False

    widget.charge_button.click()

    assert env.count("sales") == 0
    assert env.stock(env.coffee) == 10
    assert env.service.get_order(env.owner, env.table_1.id) is not None
    assert env.notifications == []


def test_insufficient_payment_shows_danger_and_keeps_the_order(env):
    widget = env.build()
    open_with_coffee(env, widget, 2)
    env.dialog_payments = (Payment("cash", 100),)

    widget.charge_button.click()

    assert env.notifications[-1][1] == "danger"
    assert env.count("sales") == 0
    assert env.stock(env.coffee) == 10
    assert env.service.get_order(env.owner, env.table_1.id) is not None
    assert card(widget, env.table_1.id).status_text == "Ocupada"
    assert line_texts(widget)[0][1] == "2"


def test_charging_an_empty_account_notifies_without_opening_the_dialog(env):
    widget = env.build()
    widget.select_table(env.table_1.id)
    widget.open_account()

    widget.charge_button.click()

    assert env.dialog_calls == []
    assert env.notifications[-1][1] == "danger"


def test_transfer_moves_the_order_to_the_chosen_free_table(env):
    widget = env.build()
    open_with_coffee(env, widget, 1)
    env.chosen_table = env.table_2.id

    widget.transfer_button.click()

    assert env.service.get_order(env.owner, env.table_1.id) is None
    moved = env.service.get_order(env.owner, env.table_2.id)
    assert moved is not None and moved.item_count == 1
    assert card(widget, env.table_1.id).status_text == "Libre"
    assert card(widget, env.table_2.id).status_text == "Ocupada"
    assert widget.selected_table_id == env.table_2.id
    assert env.notifications[-1][1] == "success"


def test_transfer_without_choice_keeps_the_order_where_it_is(env):
    widget = env.build()
    open_with_coffee(env, widget, 1)
    env.chosen_table = None

    widget.transfer_button.click()

    assert env.service.get_order(env.owner, env.table_1.id) is not None
    assert widget.selected_table_id == env.table_1.id


def test_cancel_account_asks_for_confirmation(env):
    widget = env.build()
    open_with_coffee(env, widget, 1)

    env.confirm_answer = False
    widget.cancel_button.click()
    assert env.service.get_order(env.owner, env.table_1.id) is not None

    env.confirm_answer = True
    widget.cancel_button.click()
    assert env.service.get_order(env.owner, env.table_1.id) is None
    assert card(widget, env.table_1.id).status_text == "Libre"
    assert env.count("sales") == 0
    assert env.stock(env.coffee) == 10


def test_owner_creates_tables_with_the_inline_form(env):
    widget = env.build()
    assert widget.new_table_button.isVisibleTo(widget)

    widget.new_table_name.setText("Barra 1")
    widget.new_table_zone.setText("Barra")
    widget.new_table_button.click()

    created = card(widget, env.service.list_tables(env.owner)[-1].table.id)
    assert (created.name_text, created.zone_text, created.status_text) == (
        "Barra 1",
        "Barra",
        "Libre",
    )
    assert widget.new_table_name.text() == ""

    widget.new_table_name.setText("Barra 1")
    widget.new_table_button.click()
    assert env.notifications[-1][1] == "danger"
    assert len(widget.cards) == 3


def test_cashier_does_not_see_the_new_table_form(env):
    widget = env.build(env.cashier)

    assert not widget.new_table_button.isVisibleTo(widget)
    assert not widget.new_table_name.isVisibleTo(widget)
    assert len(widget.cards) == 2


def test_empty_floor_explains_that_the_owner_creates_tables(env):
    with env.database.connect() as connection:
        connection.execute("DELETE FROM tables")

    widget = env.build()

    assert widget.cards == []
    assert widget.empty_state.isVisibleTo(widget)


def test_icon_only_buttons_have_accessible_names(env):
    widget = env.build()
    open_with_coffee(env, widget, 1)

    names = [
        button.accessibleName()
        for button in widget.lines_table.cellWidget(0, 5).findChildren(QPushButton)
    ]

    assert all(names) and len(names) == 3


def test_tables_ui_has_no_hex_colors_or_tip_strings():
    source = Path(__file__).resolve().parents[1].joinpath("suitelocal", "ui", "tables.py")
    text = source.read_text(encoding="utf-8")

    assert not re.search(r"[\"'\s:]#[0-9A-Fa-f]{6}\b", text)
    assert not re.search(r"propina|\btips?\b|gratuity", text, re.IGNORECASE)
