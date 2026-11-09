import csv
import os
import tempfile
from pathlib import Path

from suitelocal.application.reports import CSV_DELIMITER
from suitelocal.domain.auth import Session
from suitelocal.domain.credit import FIADO_MODULE
from suitelocal.domain.customers import (
    Customer,
    CustomerData,
    CustomerHistory,
    fold_text,
    validate_customer,
)
from suitelocal.domain.policies import require_owner
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import CustomerRepository
from suitelocal.infrastructure.settings import BusinessSettingsRepository

SEARCH_LIMIT = 50
HISTORY_LIMIT = 20
OFFERS_CSV_HEADER = ("Nombres", "Cédula/RUC/Pasaporte", "Teléfono", "Correo")


class CustomerService:
    """Customers of the session's business.

    Any signed-in user registers, edits and finds customers (the cashier does it at the counter);
    deactivating one and exporting the offers list are the owner's.
    """

    def __init__(self, database: Database) -> None:
        self.customers = CustomerRepository(database)
        self.settings = BusinessSettingsRepository(database)

    def credit_enabled(self, session: Session) -> bool:
        """True when the business sells on credit (fiado), so customers carry a credit limit."""
        modules = self.settings.get(session.user.business_id).enabled_modules
        return FIADO_MODULE in modules

    def find_by_id_number(self, session: Session, id_number: str) -> Customer | None:
        """The active customer with exactly this identification, or None."""
        return self.customers.find_active_by_id_number(session.user.business_id, id_number.strip())

    def search(self, session: Session, text: str) -> list[Customer]:
        """Active customers whose identification starts with ``text`` or whose name contains it.

        The name match ignores case and accents; blank text lists everybody by name.
        """
        needle = fold_text(" ".join(text.split()))
        matches = [
            customer
            for customer in self.customers.list_active(session.user.business_id)
            if not needle
            or fold_text(customer.id_number).startswith(needle)
            or needle in fold_text(customer.full_name)
        ]
        matches.sort(key=lambda customer: (fold_text(customer.full_name), customer.id))
        return matches[:SEARCH_LIMIT]

    def create(self, session: Session, data: CustomerData) -> Customer:
        return self.customers.add(session.user.business_id, validate_customer(data))

    def update(self, session: Session, customer_id: int, data: CustomerData) -> Customer:
        return self.customers.update(session.user.business_id, customer_id, validate_customer(data))

    def deactivate(self, session: Session, customer_id: int) -> None:
        require_owner(session)
        self.customers.deactivate(session.user.business_id, customer_id)

    def history(self, session: Session, customer_id: int) -> CustomerHistory:
        """The last 20 sales of the customer and the lifetime total, in cents."""
        return self.customers.history(session.user.business_id, customer_id, HISTORY_LIMIT)

    def export_offers_csv(self, session: Session, path: Path | str) -> Path:
        """Write the active customers who accepted offers as a CSV for Spanish-locale Excel."""
        require_owner(session)
        recipients = self.customers.offer_recipients(session.user.business_id)
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle, delimiter=CSV_DELIMITER)
                writer.writerow(OFFERS_CSV_HEADER)
                for customer in recipients:
                    writer.writerow(
                        [customer.full_name, customer.id_number, customer.phone, customer.email]
                    )
            os.replace(temp_name, target)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise
        return target
