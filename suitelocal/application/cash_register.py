import sqlite3

from suitelocal.domain.auth import Session
from suitelocal.domain.models import CashSession
from suitelocal.domain.policies import require_owner
from suitelocal.infrastructure.database import Database

_COLUMNS = (
    "id, business_id, user_id, opened_at, opening_cents, "
    "closed_at, counted_cents, expected_cents, notes"
)


def _to_session(row: sqlite3.Row) -> CashSession:
    return CashSession(
        row["id"],
        row["business_id"],
        row["user_id"],
        row["opened_at"],
        row["opening_cents"],
        row["closed_at"],
        row["counted_cents"],
        row["expected_cents"],
        row["notes"],
    )


class CashRegisterService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def open(self, session: Session, opening_cents: int) -> CashSession:
        if opening_cents < 0:
            raise ValueError("El monto inicial no puede ser negativo.")
        business_id = session.user.business_id
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if self._find_open(connection, business_id) is not None:
                raise ValueError("Ya hay una caja abierta. Ciérrala antes de abrir otra.")
            cursor = connection.execute(
                "INSERT INTO cash_sessions (business_id, user_id, opening_cents) VALUES (?, ?, ?)",
                (business_id, session.user.id, opening_cents),
            )
            row = connection.execute(
                f"SELECT {_COLUMNS} FROM cash_sessions WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return _to_session(row)

    def current(self, session: Session) -> CashSession | None:
        with self.database.connect() as connection:
            row = self._find_open(connection, session.user.business_id)
        return None if row is None else _to_session(row)

    def close(self, session: Session, counted_cents: int, notes: str = "") -> CashSession:
        if counted_cents < 0:
            raise ValueError("El efectivo contado no puede ser negativo.")
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            open_row = self._find_open(connection, session.user.business_id)
            if open_row is None:
                raise ValueError("No hay una caja abierta para cerrar.")
            totals = connection.execute(
                """
                SELECT
                    COALESCE((
                        SELECT SUM(p.amount_cents)
                        FROM sale_payments p
                        JOIN sales s ON s.id = p.sale_id
                        WHERE s.cash_session_id = ? AND p.method = 'cash'
                    ), 0) AS cash_in,
                    COALESCE((
                        SELECT SUM(change_cents) FROM sales WHERE cash_session_id = ?
                    ), 0) AS change_out
                """,
                (open_row["id"], open_row["id"]),
            ).fetchone()
            expected = open_row["opening_cents"] + totals["cash_in"] - totals["change_out"]
            connection.execute(
                """
                UPDATE cash_sessions
                SET closed_at = CURRENT_TIMESTAMP, counted_cents = ?,
                    expected_cents = ?, notes = ?
                WHERE id = ?
                """,
                (counted_cents, expected, notes.strip(), open_row["id"]),
            )
            row = connection.execute(
                f"SELECT {_COLUMNS} FROM cash_sessions WHERE id = ?", (open_row["id"],)
            ).fetchone()
        return _to_session(row)

    def history(self, session: Session, limit: int = 30) -> list[CashSession]:
        require_owner(session)
        with self.database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT {_COLUMNS} FROM cash_sessions
                WHERE business_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (session.user.business_id, limit),
            ).fetchall()
        return [_to_session(row) for row in rows]

    @staticmethod
    def _find_open(connection: sqlite3.Connection, business_id: int) -> sqlite3.Row | None:
        row: sqlite3.Row | None = connection.execute(
            f"SELECT {_COLUMNS} FROM cash_sessions WHERE business_id = ? AND closed_at IS NULL",
            (business_id,),
        ).fetchone()
        return row
