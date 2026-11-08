"""What happens after a sale when electronic invoicing is on: issue the invoice, print its RIDE."""

from collections.abc import Callable

from suitelocal.application.einvoice import EInvoiceService
from suitelocal.application.receipts import ReceiptService
from suitelocal.domain.auth import Session
from suitelocal.domain.einvoice import Buyer
from suitelocal.ui.receipt import ReceiptOutput
from suitelocal.ui.ride import Ride, RideOutput

Notify = Callable[[str, str], None]


class InvoiceCheckout:
    """Runs after the sale is saved, so nothing here can undo it: failures only warn."""

    def __init__(
        self,
        einvoices: EInvoiceService,
        session: Session,
        receipts: ReceiptService,
        ticket_output: ReceiptOutput,
        ride_output: RideOutput,
        notify: Notify,
    ) -> None:
        self._einvoices = einvoices
        self._session = session
        self._receipts = receipts
        self._ticket_output = ticket_output
        self._ride_output = ride_output
        self._notify = notify

    def complete(self, sale_id: int, buyer: Buyer, print_ticket: bool) -> None:
        """Issue the invoice of the saved sale and, if asked, print the RIDE instead of the ticket.

        If the invoice cannot be issued the sale stays, a warning says why and the internal
        ticket is printed so the customer still leaves with a receipt.
        """
        try:
            self._einvoices.issue_for_sale(self._session, sale_id, buyer)
        except Exception as error:  # a Spanish ValueError, or a certificate or signing problem
            reason = str(error) or type(error).__name__
            self._notify(
                "La venta quedó registrada, pero no se pudo emitir la factura electrónica. "
                f"{reason}",
                "warning",
            )
        if print_ticket:
            self.print_sale(sale_id)

    def print_sale(self, sale_id: int) -> bool:
        """Print the RIDE of the sale's invoice, or its internal ticket when it has none."""
        einvoice = self._einvoices.get_for_sale(self._session, sale_id)
        what = "el ticket" if einvoice is None else "el RIDE"
        try:
            if einvoice is None:
                self._ticket_output.print_receipt(self._receipts.build(self._session, sale_id))
            else:
                invoice = self._einvoices.invoice_data_for(self._session, einvoice)
                self._ride_output.print_ride(Ride(invoice, einvoice))
        except Exception as error:  # printer drivers raise anything
            self._notify(f"No se pudo imprimir {what}: {error}", "warning")
            return False
        return True
