"""Sales always belong to a business and a cashier; tests that do not care use this owner."""

from suitelocal.application.auth import AuthService
from suitelocal.domain.auth import Session
from suitelocal.infrastructure.database import Database


def owner_of(database: Database) -> dict[str, int]:
    """``business_id``/``user_id`` of the first user, creating a business and owner if none exist.

    Spread it into ``SaleRepository.register(sale, **owner_of(database))``.
    """
    with database.connect() as connection:
        row = connection.execute("SELECT business_id, id FROM users ORDER BY id LIMIT 1").fetchone()
        if row is None:
            business_id = connection.execute(
                "INSERT INTO businesses (name) VALUES ('Negocio de prueba')"
            ).lastrowid
            user_id = connection.execute(
                "INSERT INTO users (business_id, username, password_hash, role) "
                "VALUES (?, 'dueno', 'x', 'owner')",
                (business_id,),
            ).lastrowid
            assert business_id is not None and user_id is not None
            return {"business_id": business_id, "user_id": user_id}
    return {"business_id": row["business_id"], "user_id": row["id"]}


def owner_session(database: Database) -> Session:
    """A logged-in owner for screens that need a session to sell (the database must be empty)."""
    return Session(
        AuthService(database).setup_owner("Tienda Sol", "owner", "clave-segura", "clave-segura")
    )
