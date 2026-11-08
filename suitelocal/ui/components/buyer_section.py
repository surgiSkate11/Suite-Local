"""The "Comprobante" section of the checkout: who the electronic invoice is issued to."""

from dataclasses import dataclass

from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from suitelocal.domain.einvoice import (
    FINAL_CONSUMER_LIMIT_CENTS,
    Buyer,
    validate_buyer,
)
from suitelocal.ui.components.button import SegmentedControl
from suitelocal.ui.components.feedback import InlineMessage

__all__ = ["BuyerDraft", "BuyerSection", "CONSUMER", "ID_TYPES", "OVER_LIMIT_HINT", "WITH_DATA"]

CONSUMER = "Consumidor final"
WITH_DATA = "Con datos"
# SRI "tipoIdentificacionComprador" by the label shown to the cashier.
ID_TYPES = {"Cédula": "05", "RUC": "04", "Pasaporte": "06"}
OVER_LIMIT_HINT = "Por más de $ 50,00 tenés que identificar al cliente."
_NAME_MAX_LENGTH = 300


@dataclass(frozen=True, slots=True)
class BuyerDraft:
    """What is typed in a section, so another section (the split dialog) can start from it."""

    with_data: bool = False
    id_label: str = "Cédula"
    identification: str = ""
    name: str = ""
    address: str = ""


class BuyerSection(QFrame):
    """Final consumer by default, or the buyer's identification, name and address.

    Above USD 50 the SRI does not accept a final consumer, so that option is disabled and the
    buyer's data become required. Validation is the domain's, shown inline in Spanish.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("buyerSection")
        self._total_cents = 0
        self.title_label = QLabel("Comprobante")
        self.title_label.setObjectName("buyerTitle")
        self.mode_control = SegmentedControl([CONSUMER, WITH_DATA], CONSUMER)
        self.mode_control.selected.connect(self._on_mode_selected)
        self.hint_label = QLabel(OVER_LIMIT_HINT)
        self.hint_label.setObjectName("buyerHint")
        self.hint_label.setWordWrap(True)
        self.hint_label.hide()
        self.type_combo = QComboBox()
        self.type_combo.setAccessibleName("Tipo de identificación")
        self.type_combo.addItems(list(ID_TYPES))
        self.identification_edit = QLineEdit()
        self.identification_edit.setAccessibleName("Número de identificación")
        self.identification_edit.setPlaceholderText("Número de identificación")
        self.identification_edit.setMaxLength(20)
        self.name_edit = QLineEdit()
        self.name_edit.setAccessibleName("Nombre o razón social del cliente")
        self.name_edit.setPlaceholderText("Nombre o razón social")
        self.name_edit.setMaxLength(_NAME_MAX_LENGTH)
        self.address_edit = QLineEdit()
        self.address_edit.setAccessibleName("Dirección del cliente")
        self.address_edit.setPlaceholderText("Dirección (opcional)")
        self.address_edit.setMaxLength(_NAME_MAX_LENGTH)
        self.message = InlineMessage()
        self._fields = (
            self.type_combo,
            self.identification_edit,
            self.name_edit,
            self.address_edit,
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.title_label)
        layout.addWidget(self.mode_control)
        layout.addWidget(self.hint_label)
        # The type and the number share a row to keep the section short in the narrow ticket.
        id_row = QHBoxLayout()
        id_row.setContentsMargins(0, 0, 0, 0)
        id_row.setSpacing(6)
        id_row.addWidget(self.type_combo)
        id_row.addWidget(self.identification_edit, 1)
        layout.addLayout(id_row)
        layout.addWidget(self.name_edit)
        layout.addWidget(self.address_edit)
        layout.addWidget(self.message)
        self._show_fields(False)
        self.type_combo.currentTextChanged.connect(self._on_edited)
        for edit in (self.identification_edit, self.name_edit, self.address_edit):
            edit.textChanged.connect(self._on_edited)

    def _on_edited(self, _text: str) -> None:
        self.message.clear_message()

    # -- state --------------------------------------------------------------------------

    def set_invoicing(self, enabled: bool) -> None:
        """The section only exists while electronic invoicing is on."""
        self.setVisible(enabled)

    def set_total(self, total_cents: int) -> None:
        """Adapt to the amount being charged: a final consumer is only allowed up to USD 50."""
        self._total_cents = total_cents
        consumer_allowed = total_cents <= FINAL_CONSUMER_LIMIT_CENTS
        self.mode_control.set_option_enabled(CONSUMER, consumer_allowed)
        self.hint_label.setVisible(not consumer_allowed)
        if not consumer_allowed and self.mode_control.current == CONSUMER:
            self.mode_control.select(WITH_DATA)
            self._show_fields(True)

    def reset(self) -> None:
        self.load(BuyerDraft())
        self.set_total(self._total_cents)

    def draft(self) -> BuyerDraft:
        return BuyerDraft(
            self.mode_control.current == WITH_DATA,
            self.type_combo.currentText(),
            self.identification_edit.text(),
            self.name_edit.text(),
            self.address_edit.text(),
        )

    def load(self, draft: BuyerDraft) -> None:
        self.mode_control.select(WITH_DATA if draft.with_data else CONSUMER)
        self.type_combo.setCurrentText(draft.id_label)
        self.identification_edit.setText(draft.identification)
        self.name_edit.setText(draft.name)
        self.address_edit.setText(draft.address)
        self._show_fields(draft.with_data)
        self.message.clear_message()
        # The amount may already forbid the final consumer the draft asks for.
        self.set_total(self._total_cents)

    def buyer(self, total_cents: int | None = None) -> Buyer | None:
        """The buyer to invoice, or None after showing why the data are not valid."""
        total = self._total_cents if total_cents is None else total_cents
        if self.mode_control.current == CONSUMER:
            buyer = Buyer.final_consumer()
        else:
            buyer = Buyer(
                ID_TYPES[self.type_combo.currentText()],
                self.identification_edit.text().strip(),
                self.name_edit.text().strip(),
                self.address_edit.text().strip(),
            )
        try:
            validate_buyer(buyer, total)
        except ValueError as error:
            self.message.show_error(str(error))
            return None
        self.message.clear_message()
        return buyer

    # -- behavior -----------------------------------------------------------------------

    def _on_mode_selected(self, option: str) -> None:
        if option == CONSUMER and self._total_cents > FINAL_CONSUMER_LIMIT_CENTS:
            self.mode_control.select(WITH_DATA)
            return
        self._show_fields(option == WITH_DATA)
        self.message.clear_message()

    def _show_fields(self, shown: bool) -> None:
        for field in self._fields:
            field.setVisible(shown)
