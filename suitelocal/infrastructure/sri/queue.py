"""Persistence of the electronic-invoice send queue and its sequential counters."""

import json
import sqlite3
from datetime import UTC, datetime

from suitelocal.domain.einvoice import (
    DEADLINE_WARNING_AFTER,
    PENDING,
    REPLACED,
    Buyer,
    EInvoice,
    SriMessage,
)
from suitelocal.infrastructure.database import Database

_COLUMNS = """
    id, business_id, sale_id, establishment, emission_point, sequential, access_key, environment,
    status, signed_xml, buyer_id_type, buyer_identification, buyer_name, buyer_address, messages,
    attempts, next_attempt_at, issued_at, authorized_at, authorization_number, replaced_by
"""
_NO_TRANSACTION = "Un secuencial solo se reserva dentro de una transacción BEGIN IMMEDIATE."
_EXHAUSTED = "Se agotó la numeración de facturas de este punto de emisión."
LAST_SEQUENTIAL = 999_999_999
_SEQUENTIAL_RANGE = f"El próximo secuencial debe estar entre 1 y {LAST_SEQUENTIAL}."


def to_text(moment: datetime) -> str:
    """UTC, whole seconds, fixed width: stored dates compare correctly as text."""
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def _from_text(text: str | None) -> datetime | None:
    return None if text is None else datetime.fromisoformat(text).astimezone(UTC)


def encode_messages(messages: tuple[SriMessage, ...]) -> str:
    return json.dumps(
        [
            {
                "identifier": message.identifier,
                "message": message.message,
                "additional_info": message.additional_info,
                "kind": message.kind,
            }
            for message in messages
        ],
        ensure_ascii=False,
    )


def _decode_messages(text: str) -> tuple[SriMessage, ...]:
    entries: list[dict[str, str]] = json.loads(text)
    return tuple(
        SriMessage(entry["identifier"], entry["message"], entry["additional_info"], entry["kind"])
        for entry in entries
    )


def _einvoice(row: sqlite3.Row) -> EInvoice:
    issued_at = _from_text(row["issued_at"])
    assert issued_at is not None
    return EInvoice(
        id=row["id"],
        business_id=row["business_id"],
        sale_id=row["sale_id"],
        establishment=row["establishment"],
        emission_point=row["emission_point"],
        sequential=row["sequential"],
        access_key=row["access_key"],
        environment=row["environment"],
        status=row["status"],
        signed_xml=bytes(row["signed_xml"]),
        buyer=Buyer(
            row["buyer_id_type"],
            row["buyer_identification"],
            row["buyer_name"],
            row["buyer_address"],
        ),
        messages=_decode_messages(row["messages"]),
        attempts=row["attempts"],
        next_attempt_at=_from_text(row["next_attempt_at"]),
        issued_at=issued_at,
        authorized_at=_from_text(row["authorized_at"]),
        authorization_number=row["authorization_number"],
        replaced_by=row["replaced_by"],
    )


class EInvoiceRepository:
    """Reads and writes the `einvoices` queue; business scoping is the caller's decision."""

    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def allocate_sequential(
        connection: sqlite3.Connection,
        business_id: int,
        environment: str,
        establishment: str,
        emission_point: str,
    ) -> int:
        """Hand out the next sequential of a series.

        The caller must already hold a write transaction (`BEGIN IMMEDIATE`) and keep it until
        the invoice that uses the number is stored: if that transaction rolls back, the counter
        goes back with it and the number is not burned.
        """
        if not connection.in_transaction:
            raise RuntimeError(_NO_TRANSACTION)
        try:
            row = connection.execute(
                """
                INSERT INTO einvoice_sequences
                    (business_id, environment, establishment, emission_point, last_sequential)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT (business_id, environment, establishment, emission_point)
                DO UPDATE SET last_sequential = last_sequential + 1
                RETURNING last_sequential
                """,
                (business_id, environment, establishment, emission_point),
            ).fetchone()
        except sqlite3.IntegrityError as error:
            if "last_sequential" not in str(error):
                raise
            raise ValueError(_EXHAUSTED) from error
        return int(row["last_sequential"])

    @staticmethod
    def last_sequential(
        connection: sqlite3.Connection,
        business_id: int,
        environment: str,
        establishment: str,
        emission_point: str,
    ) -> int:
        """The last number handed out in a series; 0 when none has been."""
        row = connection.execute(
            """
            SELECT last_sequential FROM einvoice_sequences
            WHERE business_id = ? AND environment = ? AND establishment = ? AND emission_point = ?
            """,
            (business_id, environment, establishment, emission_point),
        ).fetchone()
        return 0 if row is None else int(row["last_sequential"])

    @staticmethod
    def raise_next_sequential(
        connection: sqlite3.Connection,
        business_id: int,
        environment: str,
        establishment: str,
        emission_point: str,
        next_sequential: int,
    ) -> None:
        """Make `next_sequential` the next number of a series; it can only go up.

        The caller's connection decides the transaction, so it can be undone with other changes.
        Asking for the number that is already next is allowed and changes nothing.
        """
        if isinstance(next_sequential, bool) or not 1 <= next_sequential <= LAST_SEQUENTIAL:
            raise ValueError(_SEQUENTIAL_RANGE)
        last = EInvoiceRepository.last_sequential(
            connection, business_id, environment, establishment, emission_point
        )
        if next_sequential <= last:
            raise ValueError(f"El próximo secuencial debe ser mayor que el último usado ({last}).")
        connection.execute(
            """
            INSERT INTO einvoice_sequences
                (business_id, environment, establishment, emission_point, last_sequential)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (business_id, environment, establishment, emission_point)
            DO UPDATE SET last_sequential = excluded.last_sequential
            """,
            (business_id, environment, establishment, emission_point, next_sequential - 1),
        )

    @staticmethod
    def active_for_sale(connection: sqlite3.Connection, sale_id: int) -> EInvoice | None:
        """The sale's invoice that has not been replaced, read inside the caller's transaction."""
        row = connection.execute(
            f"SELECT {_COLUMNS} FROM einvoices WHERE sale_id = ? AND status <> ?",
            (sale_id, REPLACED),
        ).fetchone()
        return None if row is None else _einvoice(row)

    @staticmethod
    def replace(connection: sqlite3.Connection, einvoice_id: int) -> None:
        """Mark an invoice as replaced; call `link_replacement` once its successor exists."""
        connection.execute(
            "UPDATE einvoices SET status = ?, next_attempt_at = NULL WHERE id = ?",
            (REPLACED, einvoice_id),
        )

    @staticmethod
    def link_replacement(connection: sqlite3.Connection, einvoice_id: int, new_id: int) -> None:
        connection.execute(
            "UPDATE einvoices SET replaced_by = ? WHERE id = ?", (new_id, einvoice_id)
        )

    @staticmethod
    def sale_invoice_exists(connection: sqlite3.Connection, sale_id: int) -> bool:
        return (
            connection.execute("SELECT 1 FROM einvoices WHERE sale_id = ?", (sale_id,)).fetchone()
            is not None
        )

    @staticmethod
    def insert(
        connection: sqlite3.Connection,
        *,
        business_id: int,
        sale_id: int,
        establishment: str,
        emission_point: str,
        sequential: str,
        access_key: str,
        environment: str,
        signed_xml: bytes,
        buyer: Buyer,
        issued_at: datetime,
    ) -> int:
        cursor = connection.execute(
            """
            INSERT INTO einvoices
                (business_id, sale_id, establishment, emission_point, sequential, access_key,
                 environment, status, signed_xml, buyer_id_type, buyer_identification,
                 buyer_name, buyer_address, issued_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                business_id,
                sale_id,
                establishment,
                emission_point,
                sequential,
                access_key,
                environment,
                PENDING,
                signed_xml,
                buyer.id_type,
                buyer.identification,
                buyer.name,
                buyer.address,
                to_text(issued_at),
            ),
        )
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    def get(self, einvoice_id: int) -> EInvoice | None:
        with self.database.connect() as connection:
            row = connection.execute(
                f"SELECT {_COLUMNS} FROM einvoices WHERE id = ?", (einvoice_id,)
            ).fetchone()
        return None if row is None else _einvoice(row)

    def get_for_sale(self, business_id: int, sale_id: int) -> EInvoice | None:
        with self.database.connect() as connection:
            row = connection.execute(
                f"""
                SELECT {_COLUMNS} FROM einvoices
                WHERE sale_id = ? AND business_id = ? AND status <> '{REPLACED}'
                """,
                (sale_id, business_id),
            ).fetchone()
        return None if row is None else _einvoice(row)

    def list_for_business(self, business_id: int, limit: int = 100) -> list[EInvoice]:
        with self.database.connect() as connection:
            rows = connection.execute(
                f"SELECT {_COLUMNS} FROM einvoices WHERE business_id = ? ORDER BY id DESC LIMIT ?",
                (business_id, limit),
            ).fetchall()
        return [_einvoice(row) for row in rows]

    def due(self, now: datetime, business_id: int | None = None) -> list[EInvoice]:
        """Pending and received invoices whose next attempt time has come, oldest first."""
        with self.database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT {_COLUMNS} FROM einvoices
                WHERE status IN ('pendiente', 'recibida')
                  AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                  AND (? IS NULL OR business_id = ?)
                ORDER BY id
                """,
                (to_text(now), business_id, business_id),
            ).fetchall()
        return [_einvoice(row) for row in rows]

    def count_open(self, business_id: int) -> int:
        """Invoices of the business still waiting on the SRI: pending or received."""
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total FROM einvoices
                WHERE business_id = ? AND status IN ('pendiente', 'recibida')
                """,
                (business_id,),
            ).fetchone()
        return int(row["total"])

    def near_deadline(self, now: datetime, business_id: int | None = None) -> list[int]:
        """Ids of the invoices still not received more than 60 hours after the sale."""
        limit = to_text(now - DEADLINE_WARNING_AFTER)
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id FROM einvoices
                WHERE status = 'pendiente' AND issued_at <= ? AND (? IS NULL OR business_id = ?)
                ORDER BY id
                """,
                (limit, business_id, business_id),
            ).fetchall()
        return [row["id"] for row in rows]

    def record(
        self,
        einvoice_id: int,
        *,
        status: str,
        attempts: int,
        next_attempt_at: datetime | None,
        messages: tuple[SriMessage, ...] | None = None,
        authorization_number: str | None = None,
        authorized_at: datetime | None = None,
    ) -> None:
        """Store the outcome of one processing step; None messages keep the stored ones."""
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE einvoices
                SET status = ?, attempts = ?, next_attempt_at = ?,
                    messages = COALESCE(?, messages),
                    authorization_number = COALESCE(?, authorization_number),
                    authorized_at = COALESCE(?, authorized_at)
                WHERE id = ?
                """,
                (
                    status,
                    attempts,
                    None if next_attempt_at is None else to_text(next_attempt_at),
                    None if messages is None else encode_messages(messages),
                    authorization_number,
                    None if authorized_at is None else to_text(authorized_at),
                    einvoice_id,
                ),
            )
