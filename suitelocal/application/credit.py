import csv
import os
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from suitelocal.application.reports import CSV_DELIMITER
from suitelocal.domain.auth import Session
from suitelocal.domain.credit import (
    ABONO,
    CARGO,
    Debtor,
    LedgerEntry,
    validate_abono,
)
from suitelocal.domain.customers import Customer
from suitelocal.domain.money import format_usd
from suitelocal.domain.policies import require_owner
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import CustomerRepository
from suitelocal.infrastructure.settings import BusinessSettingsRepository

STATEMENT_LIMIT = 100
DEBTORS_CSV_HEADER = ("Nombres", "Cédula/RUC/Pasaporte", "Teléfono", "Saldo", "Activo")

_BALANCE_SQL = """
    SELECT COALESCE(SUM(CASE kind WHEN 'cargo' THEN amount_cents ELSE -amount_cents END), 0)
    FROM customer_ledger WHERE business_id = ? AND customer_id = ?
"""
_ENTRY_COLUMNS = "id, customer_id, kind, amount_cents, sale_id, method, note, user_id, created_at"


def _to_entry(row: sqlite3.Row) -> LedgerEntry:
    return LedgerEntry(
        row["id"],
        row["customer_id"],
        row["kind"],
        row["amount_cents"],
        row["sale_id"],
        row["method"],
        row["note"],
        row["user_id"],
        datetime.fromisoformat(row["created_at"]).replace(tzinfo=UTC),
    )


def _require_customer(connection: sqlite3.Connection, customer_id: int, business_id: int) -> None:
    owned = connection.execute(
        "SELECT 1 FROM customers WHERE id = ? AND business_id = ?", (customer_id, business_id)
    ).fetchone()
    if owned is None:
        raise ValueError("El cliente no existe.")


class CreditService:
    """The credit (fiado) account of the customers of the session's business.

    Any signed-in user may read an account and take an abono (the cashier does it at the
    counter); exporting the debtors list is the owner's. A credit sale itself is registered by
    ``SaleRepository.register``, which writes the cargo in the sale's own transaction.
    """

    def __init__(self, database: Database) -> None:
        self.database = database
        self.customers = CustomerRepository(database)
        self.settings = BusinessSettingsRepository(database)

    def balance_cents(self, session: Session, customer_id: int) -> int:
        """What the customer owes: cargos minus abonos."""
        business_id = session.user.business_id
        with self.database.connect() as connection:
            _require_customer(connection, customer_id, business_id)
            balance: int = connection.execute(_BALANCE_SQL, (business_id, customer_id)).fetchone()[
                0
            ]
        return balance

    def available_cents(self, session: Session, customer_id: int) -> int | None:
        """How much more the customer may take on credit, or None when there is no limit."""
        customer = self._customer(session, customer_id)
        if customer.credit_limit_cents is None:
            return None
        return max(0, customer.credit_limit_cents - self.balance_cents(session, customer_id))

    def statement(
        self, session: Session, customer_id: int, limit: int = STATEMENT_LIMIT
    ) -> list[LedgerEntry]:
        """The movements of the account, newest first."""
        business_id = session.user.business_id
        with self.database.connect() as connection:
            _require_customer(connection, customer_id, business_id)
            rows = connection.execute(
                f"SELECT {_ENTRY_COLUMNS} FROM customer_ledger "
                "WHERE business_id = ? AND customer_id = ? ORDER BY id DESC LIMIT ?",
                (business_id, customer_id, limit),
            ).fetchall()
        return [_to_entry(row) for row in rows]

    def register_payment(
        self,
        session: Session,
        customer_id: int,
        amount_cents: int,
        method: str,
        reference: str = "",
    ) -> LedgerEntry:
        """Take an abono (cash or transfer); it can never exceed what the customer owes.

        A cash abono is linked to the open cash session, so it counts in the expected cash.
        """
        business_id = session.user.business_id
        separator = self.settings.get(business_id).decimal_separator
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            _require_customer(connection, customer_id, business_id)
            balance = connection.execute(_BALANCE_SQL, (business_id, customer_id)).fetchone()[0]
            reference = validate_abono(amount_cents, method, reference, balance, separator)
            open_session = connection.execute(
                "SELECT id FROM cash_sessions WHERE business_id = ? AND closed_at IS NULL",
                (business_id,),
            ).fetchone()
            cursor = connection.execute(
                """
                INSERT INTO customer_ledger
                    (business_id, customer_id, kind, amount_cents, method, note, user_id,
                     cash_session_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    business_id,
                    customer_id,
                    ABONO,
                    amount_cents,
                    method,
                    reference,
                    session.user.id,
                    None if open_session is None else open_session["id"],
                ),
            )
            row = connection.execute(
                f"SELECT {_ENTRY_COLUMNS} FROM customer_ledger WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return _to_entry(row)

    def balance_after_sale(self, session: Session, sale_id: int) -> int | None:
        """The customer's balance right after the sale's cargo, or None if it had no fiado."""
        business_id = session.user.business_id
        with self.database.connect() as connection:
            cargo = connection.execute(
                "SELECT id, customer_id FROM customer_ledger "
                "WHERE business_id = ? AND sale_id = ? AND kind = ?",
                (business_id, sale_id, CARGO),
            ).fetchone()
            if cargo is None:
                return None
            balance: int = connection.execute(
                """
                SELECT COALESCE(
                    SUM(CASE kind WHEN 'cargo' THEN amount_cents ELSE -amount_cents END), 0)
                FROM customer_ledger WHERE business_id = ? AND customer_id = ? AND id <= ?
                """,
                (business_id, cargo["customer_id"], cargo["id"]),
            ).fetchone()[0]
        return balance

    def debtors(self, session: Session) -> list[Debtor]:
        """Customers who owe something, active or not, the biggest debt first."""
        business_id = session.user.business_id
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT customer_id,
                       SUM(CASE kind WHEN 'cargo' THEN amount_cents ELSE -amount_cents END)
                           AS balance
                FROM customer_ledger WHERE business_id = ?
                GROUP BY customer_id HAVING balance > 0
                """,
                (business_id,),
            ).fetchall()
        debtors: list[Debtor] = []
        for row in rows:
            customer = self.customers.get(business_id, row["customer_id"])
            if customer is not None:
                debtors.append(Debtor(customer, row["balance"]))
        debtors.sort(key=lambda debtor: (-debtor.balance_cents, debtor.customer.full_name))
        return debtors

    def total_owed_cents(self, session: Session) -> int:
        return sum(debtor.balance_cents for debtor in self.debtors(session))

    def export_debtors_csv(self, session: Session, path: Path | str) -> Path:
        """Write who owes what as a CSV for Spanish-locale Excel; owner only."""
        require_owner(session)
        debtors = self.debtors(session)
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle, delimiter=CSV_DELIMITER)
                writer.writerow(DEBTORS_CSV_HEADER)
                for debtor in debtors:
                    customer = debtor.customer
                    writer.writerow(
                        [
                            customer.full_name,
                            customer.id_number,
                            customer.phone,
                            _plain_amount(debtor.balance_cents),
                            "Sí" if customer.active else "No",
                        ]
                    )
            os.replace(temp_name, target)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise
        return target

    def _customer(self, session: Session, customer_id: int) -> Customer:
        customer = self.customers.get(session.user.business_id, customer_id)
        if customer is None:
            raise ValueError("El cliente no existe.")
        return customer


def _plain_amount(cents: int) -> str:
    """Cents as "10,50" (no symbol, no thousands separator), the way reports write amounts."""
    return format_usd(cents).removeprefix("$ ").replace(".", "")
