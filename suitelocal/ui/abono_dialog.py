"""Registrar abono: what the cashier does when a customer pays part of their fiado."""

from collections.abc import Callable

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from suitelocal.application.credit import CreditService
from suitelocal.domain.auth import Session
from suitelocal.domain.credit import LedgerEntry
from suitelocal.domain.customers import Customer
from suitelocal.ui.components import InlineMessage, set_variant
from suitelocal.ui.payment_dialog import format_money, parse_money

__all__ = ["AbonoDialog", "AbonoDialogFactory"]

AbonoDialogFactory = Callable[..., "AbonoDialog"]

_METHODS = (("Efectivo", "cash"), ("Transferencia", "transfer"))


class AbonoDialog(QDialog):
    """Takes an abono from ``customer``; the saved movement is left in ``self.entry``."""

    def __init__(
        self,
        credit: CreditService,
        session: Session,
        customer: Customer,
        balance_cents: int,
        currency_symbol: str = "$",
        decimal_separator: str = ",",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._credit = credit
        self._session = session
        self._customer = customer
        self.entry: LedgerEntry | None = None
        self.setWindowTitle("Registrar abono")
        self.setModal(True)
        self.setMinimumWidth(380)

        owed = format_money(balance_cents, currency_symbol, decimal_separator)
        self.summary_label = QLabel(f"{customer.full_name} debe {owed}.")
        self.summary_label.setWordWrap(True)
        self.amount_edit = QLineEdit(
            f"{balance_cents // 100}{decimal_separator}{balance_cents % 100:02d}"
        )
        self.amount_edit.setAccessibleName("Monto del abono")
        self.amount_edit.selectAll()
        self.method_combo = QComboBox()
        self.method_combo.setAccessibleName("Forma de pago del abono")
        for label, method in _METHODS:
            self.method_combo.addItem(label, method)
        self.reference_edit = QLineEdit()
        self.reference_edit.setAccessibleName("Referencia de la transferencia")
        self.reference_edit.setPlaceholderText("Número de referencia")
        self.message = InlineMessage()
        self.save_button = QPushButton("Registrar abono")
        set_variant(self.save_button, "primary")
        self.save_button.setAutoDefault(False)
        self.save_button.clicked.connect(self.save)
        self.cancel_button = QPushButton("Cancelar")
        set_variant(self.cancel_button, "secondary")
        self.cancel_button.setAutoDefault(False)
        self.cancel_button.clicked.connect(self.reject)

        self.method_combo.currentIndexChanged.connect(self._sync_reference)
        self.amount_edit.returnPressed.connect(self.save)
        self.reference_edit.returnPressed.connect(self.save)
        form = QFormLayout()
        form.addRow("Monto:", self.amount_edit)
        form.addRow("Forma de pago:", self.method_combo)
        self.reference_row_label = QLabel("Referencia:")
        form.addRow(self.reference_row_label, self.reference_edit)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.save_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.summary_label)
        layout.addLayout(form)
        layout.addWidget(self.message)
        layout.addLayout(buttons)
        self._sync_reference()

    def _sync_reference(self) -> None:
        transfer = self.method_combo.currentData() == "transfer"
        self.reference_edit.setVisible(transfer)
        self.reference_row_label.setVisible(transfer)

    def save(self) -> None:
        """Register through the service; a rejected abono shows its Spanish message and stays."""
        try:
            self.entry = self._credit.register_payment(
                self._session,
                self._customer.id,
                parse_money(self.amount_edit.text()),
                self.method_combo.currentData(),
                self.reference_edit.text(),
            )
        except ValueError as error:
            self.message.show_error(str(error))
            return
        self.accept()
