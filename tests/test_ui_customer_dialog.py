import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from suitelocal.application.auth import AuthService
from suitelocal.application.customers import CustomerService
from suitelocal.domain.auth import Session
from suitelocal.domain.customers import CustomerData
from suitelocal.infrastructure.database import Database
from suitelocal.ui.components.customer_picker import CustomerPicker
from suitelocal.ui.customer_dialog import CustomerDialog, guess_id_type

ANA = CustomerData("cedula", "1712345678", "Ana Pérez", email="ana@correo.com")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class Env:
    def __init__(self, tmp_path) -> None:
        self.database = Database(tmp_path / "customer_ui.db")
        self.database.initialize()
        auth = AuthService(self.database)
        self.owner = Session(
            auth.setup_owner("Barbería", "dueno", "Clave-segura-1", "Clave-segura-1")
        )
        self.service = CustomerService(self.database)


@pytest.fixture
def env(qapp, tmp_path):
    return Env(tmp_path)


def fill(dialog: CustomerDialog, number: str, name: str, email: str = "", offers: bool = False):
    dialog.id_edit.setText(number)
    dialog.name_edit.setText(name)
    dialog.email_edit.setText(email)
    if offers:
        dialog.offers_check.setChecked(True)


# -- guess_id_type -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("number", "expected"),
    [("1712345678", "cedula"), ("1712345678001", "ruc"), ("AB123456", "pasaporte"), ("", "cedula")],
)
def test_the_identification_type_is_guessed_from_the_number(number, expected):
    assert guess_id_type(number) == expected


# -- CustomerDialog ------------------------------------------------------------------------


def test_a_new_dialog_is_prefilled_with_the_number_and_guesses_its_type(env):
    dialog = CustomerDialog(env.service, env.owner, id_number="1790012345001")

    assert dialog.id_edit.text() == "1790012345001"
    assert dialog.type_combo.currentText() == "RUC"
    assert dialog.customer is None


def test_saving_creates_the_customer_and_exposes_it(env):
    dialog = CustomerDialog(env.service, env.owner)
    fill(dialog, "1712345678", "  Ana   Pérez ", "Ana@Correo.com", offers=True)

    dialog.save()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.customer is not None
    assert (dialog.customer.full_name, dialog.customer.email) == ("Ana Pérez", "ana@correo.com")
    assert dialog.customer.accepts_offers
    assert env.service.find_by_id_number(env.owner, "1712345678") == dialog.customer


def test_an_invalid_customer_shows_the_spanish_error_and_stays_open(env):
    dialog = CustomerDialog(env.service, env.owner)
    fill(dialog, "1712345678", "")

    dialog.save()

    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.customer is None
    assert "nombre del cliente es obligatorio" in dialog.message.text()
    assert env.service.search(env.owner, "") == []


def test_the_offers_box_needs_an_email(env):
    dialog = CustomerDialog(env.service, env.owner)

    assert not dialog.offers_check.isEnabled()
    dialog.email_edit.setText("ana@correo.com")
    assert dialog.offers_check.isEnabled()
    dialog.offers_check.setChecked(True)
    dialog.email_edit.setText("")
    assert not dialog.offers_check.isEnabled()
    assert not dialog.offers_check.isChecked()


def test_editing_loads_the_customer_and_updates_it(env):
    saved = env.service.create(env.owner, ANA)
    dialog = CustomerDialog(env.service, env.owner, customer=saved)

    assert dialog.id_edit.text() == "1712345678"
    assert dialog.name_edit.text() == "Ana Pérez"
    assert dialog.email_edit.text() == "ana@correo.com"
    dialog.name_edit.setText("Ana Pérez Mora")
    dialog.save()

    assert dialog.customer is not None and dialog.customer.id == saved.id
    assert env.service.find_by_id_number(env.owner, "1712345678").full_name == "Ana Pérez Mora"


def test_a_taken_identification_shows_the_domain_message(env):
    env.service.create(env.owner, ANA)
    dialog = CustomerDialog(env.service, env.owner)
    fill(dialog, "1712345678", "Otra Ana")

    dialog.save()

    assert dialog.customer is None
    assert "Ana Pérez" in dialog.message.text()


# -- CustomerPicker ------------------------------------------------------------------------


class FakeCustomerDialog:
    """Stands in for the modal CustomerDialog; "saves" by creating the customer."""

    calls: list[dict] = []
    accept = True

    def __init__(self, customers, session, customer=None, id_number="", parent=None) -> None:
        self.customers = customers
        self.session = session
        self.id_number = id_number
        self.customer = None
        FakeCustomerDialog.calls.append({"id_number": id_number, "customer": customer})

    def exec(self) -> QDialog.DialogCode:
        if not FakeCustomerDialog.accept:
            return QDialog.DialogCode.Rejected
        self.customer = self.customers.create(
            self.session, CustomerData("cedula", self.id_number, "Cliente Nuevo")
        )
        return QDialog.DialogCode.Accepted

    def deleteLater(self) -> None:
        pass


@pytest.fixture
def picker(env):
    FakeCustomerDialog.calls = []
    FakeCustomerDialog.accept = True
    widget = CustomerPicker(env.service, env.owner, FakeCustomerDialog)
    widget.show()
    return widget


def test_the_default_is_no_customer(picker):
    assert picker.customer is None
    assert picker.register_button.isHidden()
    assert picker.clear_button.isHidden()


def test_typing_a_known_identification_and_pressing_enter_selects_the_customer(env, picker):
    saved = env.service.create(env.owner, ANA)
    changes = []
    picker.customer_changed.connect(changes.append)

    picker.id_edit.setText(" 1712345678 ")
    QTest.keyClick(picker.id_edit, Qt.Key.Key_Return)

    assert picker.customer == saved
    assert "Ana Pérez" in picker.status_label.text()
    assert not picker.clear_button.isHidden()
    assert picker.register_button.isHidden()
    assert changes == [saved]


def test_the_search_button_does_the_same(env, picker):
    saved = env.service.create(env.owner, ANA)

    picker.id_edit.setText("1712345678")
    picker.search_button.click()

    assert picker.customer == saved


def test_an_unknown_identification_offers_to_register(picker):
    picker.id_edit.setText("1790012345")
    picker.search_button.click()

    assert picker.customer is None
    assert picker.status_label.text() == "Cliente no registrado"
    assert not picker.register_button.isHidden()


def test_register_opens_the_dialog_prefilled_and_selects_the_saved_customer(env, picker):
    picker.id_edit.setText("1790012345")
    picker.search_button.click()

    picker.register_button.click()

    assert FakeCustomerDialog.calls == [{"id_number": "1790012345", "customer": None}]
    assert picker.customer is not None and picker.customer.id_number == "1790012345"
    assert "Cliente Nuevo" in picker.status_label.text()
    assert picker.register_button.isHidden()


def test_cancelling_the_registration_keeps_no_customer(picker):
    FakeCustomerDialog.accept = False
    picker.id_edit.setText("1790012345")
    picker.search_button.click()

    picker.register_button.click()

    assert picker.customer is None
    assert not picker.register_button.isHidden()


def test_quitar_clears_the_customer_and_the_field(env, picker):
    env.service.create(env.owner, ANA)
    picker.id_edit.setText("1712345678")
    picker.search_button.click()
    changes = []
    picker.customer_changed.connect(changes.append)

    picker.clear_button.click()

    assert picker.customer is None
    assert picker.id_edit.text() == ""
    assert picker.clear_button.isHidden()
    assert changes == [None]


def test_an_empty_field_asks_for_the_identification(picker):
    picker.search_button.click()

    assert picker.customer is None
    assert "identificación" in picker.status_label.text()
    assert picker.register_button.isHidden()


def test_a_deactivated_customer_is_not_found(env, picker):
    saved = env.service.create(env.owner, ANA)
    env.service.deactivate(env.owner, saved.id)

    picker.id_edit.setText("1712345678")
    picker.search_button.click()

    assert picker.customer is None
    assert picker.status_label.text() == "Cliente no registrado"


def test_set_customer_selects_programmatically_without_a_change_signal_loop(env, picker):
    saved = env.service.create(env.owner, ANA)

    picker.set_customer(saved)

    assert picker.customer == saved
    assert picker.id_edit.text() == "1712345678"
    assert picker.id_edit.isReadOnly()
    picker.set_customer(None)
    assert not picker.id_edit.isReadOnly()
