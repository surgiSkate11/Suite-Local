import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QDialog

from suitelocal.domain.einvoice import Buyer
from suitelocal.ui.components.buyer_section import CONSUMER, WITH_DATA, BuyerDraft
from suitelocal.ui.payment_dialog import PaymentDialog


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def make_dialog(qapp):
    created: list[PaymentDialog] = []

    def build(total_cents: int = 1000, **kwargs) -> PaymentDialog:
        dialog = PaymentDialog(
            total_cents, enabled_methods=("cash", "transfer", "card"), sale_label="Venta", **kwargs
        )
        dialog.show()
        created.append(dialog)
        return dialog

    yield build
    for dialog in created:
        dialog.close()
        dialog.deleteLater()


def pay_exact(dialog: PaymentDialog) -> None:
    dialog.pad_buttons["1"].click()
    dialog.pad_buttons["00"].click()
    dialog.pad_buttons["00"].click()


def fill(dialog: PaymentDialog, number="0912345678", name="Ana Pérez") -> None:
    section = dialog.buyer_section
    section.mode_control.select(WITH_DATA)
    section.mode_control.selected.emit(WITH_DATA)
    section.identification_edit.setText(number)
    section.name_edit.setText(name)


def test_without_invoicing_there_is_no_comprobante_section(make_dialog):
    dialog = make_dialog()

    assert dialog.buyer_section.isHidden()
    assert dialog.buyer is None


def test_with_invoicing_the_section_shows_and_defaults_to_final_consumer(make_dialog):
    dialog = make_dialog(invoicing=True)

    assert not dialog.buyer_section.isHidden()
    assert dialog.buyer_section.mode_control.current == CONSUMER


def test_confirming_with_the_default_hands_back_a_final_consumer(make_dialog):
    dialog = make_dialog(1000, invoicing=True)
    pay_exact(dialog)

    dialog.confirm()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.buyer == Buyer.final_consumer()


def test_invalid_buyer_data_keep_the_dialog_open_with_an_inline_error(make_dialog):
    dialog = make_dialog(1000, invoicing=True)
    pay_exact(dialog)
    fill(dialog, number="12")

    dialog.confirm()

    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.payments == ()
    assert dialog.buyer is None
    assert dialog.buyer_section.message.text() == "La cédula debe tener exactamente 10 dígitos."


def test_valid_buyer_data_are_handed_back_with_the_payments(make_dialog):
    dialog = make_dialog(1000, invoicing=True)
    pay_exact(dialog)
    fill(dialog)

    dialog.confirm()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.buyer == Buyer("05", "0912345678", "Ana Pérez")
    assert len(dialog.payments) == 1


def test_above_fifty_dollars_the_dialog_requires_the_buyer_data(make_dialog):
    dialog = make_dialog(6000, invoicing=True)

    section = dialog.buyer_section
    assert not section.mode_control.is_option_enabled(CONSUMER)
    assert not section.hint_label.isHidden()
    dialog.pad_buttons["6"].click()
    for _ in range(3):
        dialog.pad_buttons["00"].click()
    dialog.confirm()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert section.message.text() == "El nombre del comprador es obligatorio."


def test_the_dialog_starts_from_the_draft_typed_in_the_ticket(make_dialog):
    draft = BuyerDraft(True, "RUC", "0912345678001", "Casa S.A.", "Av. 1")

    dialog = make_dialog(invoicing=True, buyer_draft=draft)

    assert dialog.buyer_section.mode_control.current == WITH_DATA
    assert dialog.buyer_section.buyer(1000) == Buyer("04", "0912345678001", "Casa S.A.", "Av. 1")


def test_a_payment_problem_is_reported_before_the_buyer_is_checked(make_dialog):
    dialog = make_dialog(1000, invoicing=True)
    fill(dialog, number="12")

    dialog.confirm()

    # Nothing was paid yet: the dialog does nothing and does not complain about the buyer.
    assert dialog.buyer_section.message.isHidden()
    assert dialog.result() != QDialog.DialogCode.Accepted
