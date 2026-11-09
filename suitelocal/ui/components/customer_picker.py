"""The "Cliente" field of the checkout: find a customer by identification, or register one."""

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from suitelocal.application.credit import CreditService
from suitelocal.application.customers import CustomerService
from suitelocal.domain.auth import Session
from suitelocal.domain.customers import Customer
from suitelocal.domain.money import format_usd
from suitelocal.ui.components.button import set_variant
from suitelocal.ui.customer_dialog import CustomerDialog, CustomerDialogFactory

__all__ = ["CustomerPicker"]

NOT_REGISTERED = "Cliente no registrado"
ASK_FOR_IDENTIFICATION = "Escribí la identificación del cliente."


class CustomerPicker(QFrame):
    """No customer by default. Type the identification and press Enter or "Buscar".

    A known customer stays selected (its name is shown); an unknown one offers "Registrar",
    which opens the quick registration prefilled with the number. "Quitar" clears it.
    """

    customer_changed = Signal(object)

    def __init__(
        self,
        customers: CustomerService,
        session: Session,
        dialog_factory: CustomerDialogFactory = CustomerDialog,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("customerPicker")
        self._customers = customers
        self._session = session
        self._dialog_factory = dialog_factory
        self.customer: Customer | None = None
        # Set by show_credit(): the selected customer then shows what they owe.
        self._credit: CreditService | None = None
        self._decimal_separator = ","

        self.title_label = QLabel("Cliente")
        self.title_label.setObjectName("buyerTitle")
        self.id_edit = QLineEdit()
        self.id_edit.setAccessibleName("Identificación del cliente")
        self.id_edit.setPlaceholderText("Cédula, RUC o pasaporte (Enter para buscar)")
        self.id_edit.setMaxLength(20)
        # Enter would otherwise reach the default button of a dialog, so it is taken here.
        self.id_edit.installEventFilter(self)
        self.id_edit.textChanged.connect(self._on_text_edited)
        self.search_button = QPushButton("Buscar")
        set_variant(self.search_button, "secondary")
        self.search_button.setAutoDefault(False)
        self.search_button.clicked.connect(self.lookup)
        self.status_label = QLabel()
        self.status_label.setObjectName("customerStatus")
        self.status_label.setWordWrap(True)
        self.register_button = QPushButton("Registrar")
        set_variant(self.register_button, "primary")
        self.register_button.setAutoDefault(False)
        self.register_button.clicked.connect(self.register)
        self.clear_button = QPushButton("Quitar")
        set_variant(self.clear_button, "ghost")
        self.clear_button.setAutoDefault(False)
        self.clear_button.clicked.connect(self.clear)

        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.setSpacing(6)
        search_row.addWidget(self.id_edit, 1)
        search_row.addWidget(self.search_button)
        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(6)
        status_row.addWidget(self.status_label, 1)
        status_row.addWidget(self.register_button)
        status_row.addWidget(self.clear_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.title_label)
        layout.addLayout(search_row)
        layout.addLayout(status_row)
        self._show_state()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            watched is self.id_edit
            and event.type() == QEvent.Type.KeyPress
            and isinstance(event, QKeyEvent)
            and Qt.Key(event.key()) in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        ):
            self.lookup()
            return True
        return super().eventFilter(watched, event)

    def _on_text_edited(self, _text: str) -> None:
        """A new number makes the previous "no registrado" answer stale."""
        if self.customer is None:
            self._show_state()

    # -- state --------------------------------------------------------------------------

    def set_customer(self, customer: Customer | None) -> None:
        """Select ``customer`` (or none) and tell the checkout when that changed it."""
        changed = customer != self.customer
        self.customer = customer
        self.id_edit.setReadOnly(customer is not None)
        if customer is not None:
            self.id_edit.setText(customer.id_number)
        self._show_state()
        if changed:
            self.customer_changed.emit(customer)

    def show_credit(self, credit: CreditService | None, decimal_separator: str = ",") -> None:
        """Show (or stop showing) the balance of the selected customer next to their name."""
        self._credit = credit
        self._decimal_separator = decimal_separator
        self._show_state()

    def clear(self) -> None:
        """ "Quitar": back to no customer, with an empty field."""
        self.id_edit.setReadOnly(False)
        self.id_edit.clear()
        self.set_customer(None)

    def _show_state(self, not_registered: bool = False, hint: str = "") -> None:
        customer = self.customer
        if customer is not None:
            self.status_label.setText(f"✓ {customer.full_name}{self._balance_text(customer)}")
        else:
            self.status_label.setText(NOT_REGISTERED if not_registered else hint)
        self.status_label.setVisible(customer is not None or bool(self.status_label.text()))
        self.register_button.setVisible(customer is None and not_registered)
        self.clear_button.setVisible(customer is not None)
        self.search_button.setEnabled(customer is None)

    def _balance_text(self, customer: Customer) -> str:
        if self._credit is None:
            return ""
        try:
            balance = self._credit.balance_cents(self._session, customer.id)
        except ValueError:
            return ""
        return f" · Saldo pendiente: {format_usd(balance, self._decimal_separator)}"

    # -- behavior -----------------------------------------------------------------------

    def lookup(self) -> None:
        """Find the customer with the typed identification and select it."""
        if self.customer is not None:
            return
        number = self.id_edit.text().strip()
        if not number:
            self._show_state(hint=ASK_FOR_IDENTIFICATION)
            return
        found = self._customers.find_by_id_number(self._session, number)
        if found is not None:
            self.set_customer(found)
        else:
            self._show_state(not_registered=True)

    def register(self) -> None:
        """Open the registration with the typed number; the saved customer gets selected."""
        dialog = self._dialog_factory(
            self._customers, self._session, id_number=self.id_edit.text().strip(), parent=self
        )
        accepted = dialog.exec() == CustomerDialog.DialogCode.Accepted
        saved = dialog.customer
        dialog.deleteLater()
        if accepted and saved is not None:
            self.set_customer(saved)
