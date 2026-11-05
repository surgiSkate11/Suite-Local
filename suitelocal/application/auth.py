import sqlite3

from suitelocal.domain.auth import Session, User
from suitelocal.domain.policies import require_owner
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.security import hash_password, verify_password

# Verified when the username does not exist so a failed login always costs one scrypt run.
_DUMMY_PASSWORD_HASH = hash_password("suitelocal-dummy-password")


class AuthService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def has_users(self) -> bool:
        with self.database.connect() as connection:
            row = connection.execute("SELECT 1 FROM users LIMIT 1").fetchone()
        return row is not None

    def setup_owner(
        self,
        business_name: str,
        username: str,
        password: str,
        password_confirmation: str,
    ) -> User:
        business_name = business_name.strip()
        if not business_name or not username:
            raise ValueError("El negocio y el usuario son obligatorios.")
        username = self._validate_username(username)
        self._validate_password_confirmation(password, password_confirmation)
        password_hash = hash_password(password)
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                raise ValueError("La instalación ya tiene un usuario.")
            business = connection.execute(
                "INSERT INTO businesses (name) VALUES (?)", (business_name,)
            )
            business_id = business.lastrowid
            if business_id is None:
                raise RuntimeError("No se pudo crear el negocio.")
            connection.execute(
                """
                INSERT INTO business_settings
                    (
                        business_id, currency_symbol, low_stock_threshold,
                        enabled_payment_methods, tax_rate_basis_points
                    )
                VALUES (?, '$', 3, 'cash,transfer', 1500)
                """,
                (business_id,),
            )
            user = connection.execute(
                """
                INSERT INTO users (business_id, username, password_hash, role)
                VALUES (?, ?, ?, 'owner')
                """,
                (business_id, username, password_hash),
            )
            user_id = user.lastrowid
            if user_id is None:
                raise RuntimeError("No se pudo crear el usuario dueño.")
        return User(user_id, business_id, username, "owner", True)

    def authenticate(self, username: str, password: str) -> Session:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT id, business_id, username, password_hash, role, active
                FROM users WHERE username = ?
                """,
                (username.strip(),),
            ).fetchone()
        stored_hash = _DUMMY_PASSWORD_HASH if row is None else row["password_hash"]
        password_matches = verify_password(password, stored_hash)
        if row is None or not row["active"] or not password_matches:
            raise ValueError("Usuario o contraseña incorrectos.")
        user = User(row["id"], row["business_id"], row["username"], row["role"], True)
        return Session(user)

    def list_users(self, session: Session) -> list[User]:
        require_owner(session)
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, business_id, username, role, active
                FROM users
                WHERE business_id = ?
                ORDER BY role, username
                """,
                (session.user.business_id,),
            ).fetchall()
        return [
            User(row["id"], row["business_id"], row["username"], row["role"], bool(row["active"]))
            for row in rows
        ]

    def create_cashier(
        self,
        session: Session,
        username: str,
        password: str,
        password_confirmation: str,
    ) -> User:
        require_owner(session)
        username = self._validate_username(username)
        self._validate_password_confirmation(password, password_confirmation)
        password_hash = hash_password(password)
        with self.database.connect() as connection:
            count = connection.execute(
                "SELECT COUNT(*) AS total FROM users WHERE business_id = ? AND active = 1",
                (session.user.business_id,),
            ).fetchone()["total"]
            if count >= 5:
                raise ValueError("El negocio no puede tener más de 5 usuarios activos.")
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO users (business_id, username, password_hash, role)
                    VALUES (?, ?, ?, 'cashier')
                    """,
                    (session.user.business_id, username, password_hash),
                )
            except sqlite3.IntegrityError as error:
                if "UNIQUE constraint failed" in str(error):
                    raise ValueError("Ya existe un usuario con ese nombre.") from error
                raise
            user_id = cursor.lastrowid
            if user_id is None:
                raise RuntimeError("No se pudo crear el cajero.")
        return User(user_id, session.user.business_id, username, "cashier", True)

    @staticmethod
    def _validate_username(username: str) -> str:
        normalized = username.strip()
        if not normalized:
            raise ValueError("El usuario es obligatorio.")
        if any(character.isspace() for character in normalized):
            raise ValueError("El usuario no puede contener espacios.")
        return normalized

    @staticmethod
    def _validate_password_confirmation(password: str, confirmation: str) -> None:
        if password != confirmation:
            raise ValueError("Las contraseñas no coinciden.")

    def deactivate_user(self, session: Session, user_id: int) -> None:
        require_owner(session)
        if user_id == session.user.id:
            raise ValueError("No puedes desactivar tu propio usuario.")
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE users SET active = 0
                WHERE id = ? AND business_id = ? AND role = 'cashier' AND active = 1
                """,
                (user_id, session.user.business_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("El cajero no está disponible.")
