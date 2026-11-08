import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QLineEdit

from suitelocal.domain.einvoice import Buyer
from suitelocal.ui.components.buyer_section import (
    CONSUMER,
    WITH_DATA,
    BuyerSection,
)

OVER_LIMIT_HINT = "Por más de $ 50,00 tenés que identificar al cliente."


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def section(qapp):
    widget = BuyerSection()
    yield widget
    widget.deleteLater()


def fill(section: BuyerSection, kind="Cédula", number="0912345678", name="Ana Pérez", address=""):
    section.mode_control.select(WITH_DATA)
    section.mode_control.selected.emit(WITH_DATA)
    section.type_combo.setCurrentText(kind)
    section.identification_edit.setText(number)
    section.name_edit.setText(name)
    section.address_edit.setText(address)


def test_it_starts_as_final_consumer_without_the_buyer_fields(section):
    assert section.mode_control.current == CONSUMER
    for field in (section.type_combo, section.identification_edit, section.name_edit):
        assert field.isHidden()
    assert section.address_edit.isHidden()
    assert section.buyer(1000) == Buyer.final_consumer()


def test_the_title_says_comprobante(section):
    assert section.title_label.text() == "Comprobante"


def test_choosing_with_data_shows_the_fields_and_offers_the_three_id_types(section):
    section.mode_control.select(WITH_DATA)
    section.mode_control.selected.emit(WITH_DATA)

    for field in (
        section.type_combo,
        section.identification_edit,
        section.name_edit,
        section.address_edit,
    ):
        assert not field.isHidden()
    assert [section.type_combo.itemText(i) for i in range(3)] == ["Cédula", "RUC", "Pasaporte"]
    assert section.type_combo.count() == 3


def test_there_is_no_email_field(section):
    # Only the number, the name and the address: the app sends no email, so no dead control.
    assert len(section.findChildren(QLineEdit)) == 3


@pytest.mark.parametrize(("kind", "code"), [("Cédula", "05"), ("RUC", "04"), ("Pasaporte", "06")])
def test_the_buyer_carries_the_sri_id_type_and_trimmed_text(section, kind, code):
    number = {"Cédula": "0912345678", "RUC": "0912345678001", "Pasaporte": "AB12345"}[kind]
    fill(section, kind, f"  {number} ", "  Ana Pérez ", " Calle 9 ")

    assert section.buyer(1000) == Buyer(code, number, "Ana Pérez", "Calle 9")


def test_the_address_is_optional(section):
    fill(section)

    buyer = section.buyer(1000)

    assert buyer is not None and buyer.address == ""


@pytest.mark.parametrize(
    ("kind", "number", "name", "message"),
    [
        ("Cédula", "123", "Ana", "La cédula debe tener exactamente 10 dígitos."),
        ("RUC", "0912345678", "Ana", "El RUC del comprador debe tener 13 dígitos."),
        ("RUC", "0912345000000", "Ana", "El RUC del comprador no puede terminar en 000."),
        ("Pasaporte", "", "Ana", "La identificación del comprador es obligatoria."),
        ("Cédula", "0912345678", "  ", "El nombre del comprador es obligatorio."),
        (
            "Cédula",
            "9999999999999",
            "Ana",
            "El número 9999999999999 es solo para consumidor final.",
        ),
    ],
)
def test_invalid_data_shows_the_domain_message_inline_and_gives_no_buyer(
    section, kind, number, name, message
):
    fill(section, kind, number, name)

    assert section.buyer(1000) is None
    assert not section.message.isHidden()
    assert section.message.text() == message


def test_the_inline_error_clears_when_the_cashier_edits_a_field(section):
    fill(section, number="1")
    section.buyer(1000)
    assert not section.message.isHidden()

    section.identification_edit.setText("09")

    assert section.message.isHidden()


def test_a_valid_buyer_clears_an_earlier_error(section):
    fill(section, number="1")
    assert section.buyer(1000) is None

    section.identification_edit.setText("0912345678")

    assert section.buyer(1000) is not None
    assert section.message.isHidden()


def test_up_to_fifty_dollars_final_consumer_stays_available(section):
    section.set_total(5000)

    assert section.mode_control.is_option_enabled(CONSUMER)
    assert section.hint_label.isHidden()
    assert section.buyer(5000) == Buyer.final_consumer()


def test_above_fifty_dollars_final_consumer_is_disabled_with_a_hint(section):
    section.set_total(5001)

    assert not section.mode_control.is_option_enabled(CONSUMER)
    assert section.mode_control.current == WITH_DATA
    assert not section.hint_label.isHidden()
    assert section.hint_label.text() == OVER_LIMIT_HINT
    assert not section.name_edit.isHidden()


def test_above_fifty_dollars_the_buyer_data_are_required(section):
    section.set_total(5001)

    assert section.buyer(5001) is None
    assert section.message.text() == "El nombre del comprador es obligatorio."
    fill(section)
    assert section.buyer(5001) == Buyer("05", "0912345678", "Ana Pérez")


def test_when_the_total_drops_back_final_consumer_is_available_again(section):
    section.set_total(9000)
    section.set_total(1000)

    assert section.mode_control.is_option_enabled(CONSUMER)
    assert section.hint_label.isHidden()


def test_data_typed_above_the_limit_survive_when_the_total_drops(section):
    section.set_total(9000)
    fill(section)
    section.set_total(1000)

    assert section.mode_control.current == WITH_DATA
    assert section.buyer(1000) == Buyer("05", "0912345678", "Ana Pérez")


def test_picking_final_consumer_by_click_while_it_is_disabled_changes_nothing(section):
    section.set_total(9000)

    section.mode_control.selected.emit(CONSUMER)

    assert section.mode_control.current == WITH_DATA


def test_reset_goes_back_to_an_empty_final_consumer(section):
    section.set_total(1000)
    fill(section, address="Calle 9")

    section.reset()

    assert section.mode_control.current == CONSUMER
    assert section.identification_edit.text() == ""
    assert section.name_edit.text() == ""
    assert section.address_edit.text() == ""
    assert section.message.isHidden()
    assert section.buyer(1000) == Buyer.final_consumer()


def test_a_draft_moves_the_typed_data_to_another_section(section, qapp):
    fill(section, "RUC", "0912345678001", "Casa S.A.", "Av. 1")
    other = BuyerSection()

    other.load(section.draft())

    assert other.buyer(1000) == Buyer("04", "0912345678001", "Casa S.A.", "Av. 1")
    other.deleteLater()


def test_the_section_can_be_hidden_when_invoicing_is_off(section):
    section.set_invoicing(False)
    assert section.isHidden()
    section.set_invoicing(True)
    assert not section.isHidden()
