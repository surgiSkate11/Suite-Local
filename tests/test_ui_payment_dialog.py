import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton

from suitelocal.domain.models import Payment, Sale, SaleError, SaleItem
from suitelocal.ui.payment_dialog import PaymentDialog, quick_bill_amounts

TOTAL = 5412  # $54.12
BACKSPACE = "⌫"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def make_dialog(qapp):
    created: list[PaymentDialog] = []

    def build(total_cents: int = TOTAL, **kwargs) -> PaymentDialog:
        dialog = PaymentDialog(
            total_cents,
            enabled_methods=kwargs.pop("enabled_methods", ("cash", "transfer", "card")),
            sale_label=kwargs.pop("sale_label", "Venta #1.285 · Café La Esquina"),
            **kwargs,
        )
        dialog.show()
        created.append(dialog)
        return dialog

    yield build
    for dialog in created:
        dialog.close()
        dialog.deleteLater()


def press(dialog: PaymentDialog, *keys: str) -> None:
    for key in keys:
        dialog.pad_buttons[key].click()


def sale_for(total_cents: int, payments: tuple[Payment, ...]) -> Sale:
    item = SaleItem(1, "Producto", 1, total_cents)
    return Sale((item,), sum(p.amount_cents for p in payments), payments)


def test_header_texts_and_accessible_names(make_dialog):
    dialog = make_dialog()

    assert dialog.title_label.text() == "Cobrar la venta"
    assert dialog.eyebrow_label.text() == "Venta #1.285 · Café La Esquina"
    assert dialog.close_button.accessibleName() == "Cerrar sin cobrar"
    assert dialog.pad_buttons[BACKSPACE].accessibleName() == "Borrar"
    assert dialog.total_label.text() == "$ 54,12"
    assert dialog.confirm_button.text().startswith("Confirmar cobro")
    assert dialog.confirm_button.isDefault()


def test_static_labels_and_add_button_are_present(make_dialog):
    dialog = make_dialog()

    texts = {label.text() for label in dialog.findChildren(QLabel)}
    assert {"Efectivo recibido", "Cambio", "Total a cobrar"} <= texts
    buttons = {button.text() for button in dialog.findChildren(QPushButton)}
    assert "+ Agregar otra forma de pago" in buttons


def test_exact_cash_confirms_with_a_single_cash_payment(make_dialog):
    dialog = make_dialog()

    assert dialog.quick_bill_buttons[0].text() == "Exacto"
    dialog.quick_bill_buttons[0].click()
    assert dialog.confirm_button.isEnabled()
    dialog.confirm_button.click()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.payments == (Payment("cash", TOTAL),)
    assert dialog.change_cents == 0


def test_cash_above_total_shows_exact_change(make_dialog):
    dialog = make_dialog()

    press(dialog, "1", "00")
    assert dialog.cash_display.text() == "$ 100,00"
    assert dialog.change_value.text() == "$ 45,88"
    dialog.confirm_button.click()

    payments = dialog.payments
    assert payments == (Payment("cash", 10000),)
    assert sale_for(TOTAL, payments).change_cents == 4588 == dialog.change_cents


def test_split_transfer_and_cash_with_reference(make_dialog):
    dialog = make_dialog()

    assert dialog.add_payment("transfer", 3000, "48219")
    assert dialog.remaining_cents == 2412
    press(dialog, "5", "0")
    assert dialog.cash_display.text() == "$ 50,00"
    assert dialog.change_value.text() == "$ 25,88"
    assert dialog.confirm_button.isEnabled()
    dialog.confirm_button.click()

    assert dialog.payments == (Payment("transfer", 3000, "48219"), Payment("cash", 5000))
    assert sale_for(TOTAL, dialog.payments).change_cents == 2588


def test_payment_rows_show_status_chips(make_dialog):
    dialog = make_dialog()
    dialog.add_payment("transfer", 3000, "48219")

    statuses = [(row.method, row.status_label.text()) for row in dialog.payment_rows]
    assert statuses == [("transfer", "Recibido"), ("cash", "En curso")]
    dialog.quick_bill_buttons[0].click()
    statuses = [(row.method, row.status_label.text()) for row in dialog.payment_rows]
    assert statuses == [("transfer", "Recibido"), ("cash", "Recibido")]


def test_transfer_without_reference_is_rejected_inline(make_dialog):
    dialog = make_dialog()

    assert not dialog.add_payment("transfer", TOTAL, "  ")

    assert dialog.message.text() == "La transferencia necesita un número de referencia."
    assert dialog.message.property("state") == "error"
    assert not dialog.message.isHidden()
    assert not dialog.confirm_button.isEnabled()
    assert dialog.payments == ()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert [row.method for row in dialog.payment_rows] == ["cash"]


def test_non_cash_above_total_and_duplicates_are_rejected(make_dialog):
    dialog = make_dialog()

    assert not dialog.add_payment("transfer", TOTAL + 1, "r-1")
    assert dialog.message.text() == "Los pagos no pueden superar el total sin efectivo."
    assert dialog.add_payment("transfer", 1000, "r-1")
    assert not dialog.add_payment("transfer", 1000, "r-2")
    assert dialog.message.text() == "No se puede repetir una forma de pago."
    assert [row.method for row in dialog.payment_rows] == ["transfer", "cash"]


def test_remove_payment_restores_the_remaining_amount(make_dialog):
    dialog = make_dialog()
    dialog.add_payment("transfer", 3000, "48219")

    dialog.remove_payment("transfer")

    assert dialog.remaining_cents == TOTAL
    assert [row.method for row in dialog.payment_rows] == ["cash"]


def test_confirm_is_disabled_while_the_total_is_uncovered(make_dialog):
    dialog = make_dialog()
    assert not dialog.confirm_button.isEnabled()

    press(dialog, "1")
    assert dialog.cash_display.text() == "$ 1,00"
    assert not dialog.confirm_button.isEnabled()
    assert dialog.change_value.text() == "$ 0,00"

    press(dialog, "00")
    assert dialog.confirm_button.isEnabled()


def test_pad_and_quick_bills_update_the_display(make_dialog):
    dialog = make_dialog()

    press(dialog, "1", "0", "00")
    assert dialog.cash_display.text() == "$ 1.000,00"
    press(dialog, BACKSPACE)
    assert dialog.cash_display.text() == "$ 100,00"

    labels = [button.text() for button in dialog.quick_bill_buttons]
    assert labels == ["Exacto", "$ 60,00", "$ 100,00", "$ 200,00"]
    dialog.quick_bill_buttons[3].click()
    assert dialog.cash_display.text() == "$ 200,00"
    dialog.quick_bill_buttons[0].click()
    assert dialog.cash_display.text() == "$ 54,12"


def test_quick_bills_follow_the_remaining_amount(make_dialog):
    assert quick_bill_amounts(2_412_000) == [3_000_000, 5_000_000, 10_000_000]
    assert quick_bill_amounts(250) == [300, 500, 1000]
    dialog = make_dialog()
    dialog.add_payment("transfer", 3000, "48219")

    labels = [button.text() for button in dialog.quick_bill_buttons]
    assert labels == ["Exacto", "$ 30,00", "$ 50,00", "$ 100,00"]


def test_keyboard_digits_and_backspace_feed_the_cash_display(make_dialog):
    dialog = make_dialog()

    QTest.keyClick(dialog, Qt.Key.Key_5)
    QTest.keyClick(dialog, Qt.Key.Key_0)
    assert dialog.cash_display.text() == "$ 50,00"
    QTest.keyClick(dialog, Qt.Key.Key_Backspace)
    assert dialog.cash_display.text() == "$ 5,00"


def test_enter_confirms_only_when_enabled(make_dialog):
    dialog = make_dialog()

    QTest.keyClick(dialog, Qt.Key.Key_Return)
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.payments == ()

    press(dialog, "1", "00")
    QTest.keyClick(dialog, Qt.Key.Key_Return)
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.payments == (Payment("cash", 10000),)


def test_escape_closes_without_charging(make_dialog):
    dialog = make_dialog()
    dialog.quick_bill_buttons[0].click()

    QTest.keyClick(dialog, Qt.Key.Key_Escape)

    assert dialog.result() == QDialog.DialogCode.Rejected
    assert dialog.payments == ()


def test_close_button_rejects_without_payments(make_dialog):
    dialog = make_dialog()
    dialog.quick_bill_buttons[0].click()

    dialog.close_button.click()

    assert dialog.result() == QDialog.DialogCode.Rejected
    assert dialog.payments == ()


def test_print_ticket_switch_defaults_to_on(make_dialog):
    dialog = make_dialog()

    assert dialog.print_ticket is True
    assert dialog.print_switch.text() == "Imprimir ticket al confirmar"
    dialog.print_switch.click()
    assert dialog.print_ticket is False


def test_validator_errors_are_shown_inline_and_nothing_is_accepted(make_dialog):
    def reject(payments: tuple[Payment, ...]) -> None:
        raise SaleError("Stock insuficiente para Arroz.")

    dialog = make_dialog(validate=reject)
    dialog.quick_bill_buttons[0].click()

    dialog.confirm_button.click()

    assert dialog.message.text() == "Stock insuficiente para Arroz."
    assert dialog.message.property("state") == "error"
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.payments == ()


def test_only_enabled_methods_can_be_added(make_dialog):
    dialog = make_dialog(enabled_methods=("cash", "transfer"))

    assert not dialog.add_payment("card", 1000)
    assert dialog.message.text() == "La forma de pago no está habilitada."
    assert dialog.payment_methods == ("transfer",)


def test_dialog_formats_money_with_the_comma_separator_by_default(make_dialog):
    dialog = make_dialog(1_234_567)

    assert dialog.total_label.text() == "$ 12.345,67"
    press(dialog, "5", "00")
    assert dialog.cash_display.text() == "$ 500,00"
    assert dialog.change_value.text() == "$ 0,00"


def test_dialog_formats_money_with_the_business_dot_separator(make_dialog):
    assert make_dialog(1_234_567, decimal_separator=".").total_label.text() == "$ 12,345.67"
    dialog = make_dialog(TOTAL, decimal_separator=".")

    press(dialog, "5", "00")
    assert dialog.cash_display.text() == "$ 500.00"
    assert [button.text() for button in dialog.quick_bill_buttons] == [
        "Exacto",
        "$ 60.00",
        "$ 100.00",
        "$ 200.00",
    ]
    dialog.add_payment("transfer", 3000, "TR-1")
    assert dialog.payment_rows[0].amount_label.text() == "$ 30.00"


def test_dialog_uses_the_business_currency_symbol_and_separator(make_dialog):
    dialog = make_dialog(250, currency_symbol="US$", decimal_separator=".")

    assert dialog.total_label.text() == "US$ 2.50"


def test_manual_payment_amount_is_prefilled_with_the_separator(make_dialog):
    dialog = make_dialog(5412, decimal_separator=",")

    dialog.add_button.click()

    assert dialog.amount_edit.text() == "54,12"
