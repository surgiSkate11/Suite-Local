"""Quick customer registration and edition: what the cashier asks at the counter."""

from collections.abc import Callable

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from suitelocal.application.customers import CustomerService
from suitelocal.domain.auth import Session
from suitelocal.domain.customers import (
    ADDRESS_MAX_LENGTH,
    CUSTOMER_ID_TYPES,
    EMAIL_MAX_LENGTH,
    ID_TYPE_LABELS,
    NAME_MAX_LENGTH,
    PHONE_MAX_LENGTH,
    Customer,
    CustomerData,
)
from suitelocal.ui.components import InlineMessage, set_variant

__all__ = ["CustomerDialog", "CustomerDialogFactory", "guess_id_type"]

CustomerDialogFactory = Callable[..., "CustomerDialog"]

_CEDULA_DIGITS = 10
_RUC_DIGITS = 13


def guess_id_type(number: str) -> str:
    """The identification type a typed number most likely is: 10 digits cédula, 13 RUC."""
    number = number.strip()
    if number.isdigit() and len(number) == _RUC_DIGITS:
        return "ruc"
    if number and not number.isdigit():
        return "pasaporte"
    return "cedula"


class CustomerDialog(QDialog):
    """Registers a customer, or edits ``customer``; the saved one is left in ``self.customer``."""

    def __init__(
        self,
        customers: CustomerService,
        session: Session,
        customer: Customer | None = None,
        id_number: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._customers = customers
        self._session = session
        self._editing = customer
        # The customer as saved by this dialog; None until it is saved.
        self.customer: Customer | None = None
        self.setWindowTitle("Editar cliente" if customer else "Nuevo cliente")
        self.setModal(True)
        self.setMinimumWidth(420)

        self.type_combo = QComboBox()
        self.type_combo.setAccessibleName("Tipo de identificación")
        for id_type in CUSTOMER_ID_TYPES:
            self.type_combo.addItem(ID_TYPE_LABELS[id_type], id_type)
        self.id_edit = self._line_edit("Identificación", "Cédula, RUC o pasaporte", 20)
        self.name_edit = self._line_edit("Nombres", "Nombres y apellidos", NAME_MAX_LENGTH)
        self.phone_edit = self._line_edit("Teléfono", "Teléfono (opcional)", PHONE_MAX_LENGTH)
        self.address_edit = self._line_edit("Dirección", "Dirección (opcional)", ADDRESS_MAX_LENGTH)
        self.email_edit = self._line_edit("Correo", "Correo (opcional)", EMAIL_MAX_LENGTH)
        self.offers_check = QCheckBox("Acepta recibir ofertas")
        self.offers_check.setToolTip("Solo se puede aceptar si el cliente tiene un correo.")
        self.message = InlineMessage()
        self.save_button = QPushButton("Guardar")
        set_variant(self.save_button, "primary")
        self.save_button.setAutoDefault(False)
        self.save_button.clicked.connect(self.save)
        self.cancel_button = QPushButton("Cancelar")
        set_variant(self.cancel_button, "secondary")
        self.cancel_button.setAutoDefault(False)
        self.cancel_button.clicked.connect(self.reject)

        id_row = QHBoxLayout()
        id_row.setContentsMargins(0, 0, 0, 0)
        id_row.addWidget(self.type_combo)
        id_row.addWidget(self.id_edit, 1)
        form = QFormLayout()
        form.addRow("Identificación:", id_row)
        form.addRow("Nombres:", self.name_edit)
        form.addRow("Teléfono:", self.phone_edit)
        form.addRow("Dirección:", self.address_edit)
        form.addRow("Correo:", self.email_edit)
        form.addRow("", self.offers_check)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.save_button)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.message)
        layout.addLayout(buttons)

        self.email_edit.textChanged.connect(self._sync_offers)
        self.id_edit.returnPressed.connect(self.save)
        self.name_edit.returnPressed.connect(self.save)
        if customer is not None:
            self._load(customer)
        else:
            self.id_edit.setText(id_number)
            self.type_combo.setCurrentIndex(self.type_combo.findData(guess_id_type(id_number)))
        self._sync_offers()

    @staticmethod
    def _line_edit(accessible_name: str, placeholder: str, max_length: int) -> QLineEdit:
        edit = QLineEdit()
        edit.setAccessibleName(accessible_name)
        edit.setPlaceholderText(placeholder)
        edit.setMaxLength(max_length)
        return edit

    def _load(self, customer: Customer) -> None:
        self.type_combo.setCurrentIndex(self.type_combo.findData(customer.id_type))
        self.id_edit.setText(customer.id_number)
        self.name_edit.setText(customer.full_name)
        self.phone_edit.setText(customer.phone)
        self.address_edit.setText(customer.address)
        self.email_edit.setText(customer.email)
        self.offers_check.setChecked(customer.accepts_offers)

    def _sync_offers(self, _text: str = "") -> None:
        """Offers need an email to be sent to, so the box only works while there is one."""
        has_email = bool(self.email_edit.text().strip())
        self.offers_check.setEnabled(has_email)
        if not has_email:
            self.offers_check.setChecked(False)

    def _data(self) -> CustomerData:
        return CustomerData(
            self.type_combo.currentData(),
            self.id_edit.text(),
            self.name_edit.text(),
            self.phone_edit.text(),
            self.address_edit.text(),
            self.email_edit.text(),
            self.offers_check.isChecked(),
        )

    def save(self) -> None:
        """Save through the service; a rejected customer shows its Spanish message and stays."""
        try:
            if self._editing is None:
                saved = self._customers.create(self._session, self._data())
            else:
                saved = self._customers.update(self._session, self._editing.id, self._data())
        except ValueError as error:
            self.message.show_error(str(error))
            return
        self.customer = saved
        self.accept()
