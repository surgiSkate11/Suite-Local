import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from suitelocal.infrastructure.database import REQUIRED_TABLES, Database


class BackupError(RuntimeError):
    """Raised when a database backup or restore cannot be completed safely."""


def create_backup(database: Database, destination: Path | str) -> Path:
    source_path = database.path
    destination_path = Path(destination)
    if not source_path.exists():
        raise BackupError("No existe una base de datos para respaldar.")
    if source_path.resolve() == destination_path.resolve():
        raise BackupError("El respaldo debe guardarse en una ubicación diferente.")

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = _temporary_path(destination_path)
    try:
        with (
            closing(sqlite3.connect(source_path)) as source,
            closing(sqlite3.connect(temporary_path)) as target,
        ):
            source.backup(target)
            target.commit()
            _ensure_healthy(target)
        os.replace(temporary_path, destination_path)
    except (OSError, sqlite3.Error) as error:
        raise BackupError("No se pudo crear el respaldo de la base de datos.") from error
    finally:
        temporary_path.unlink(missing_ok=True)
    return destination_path


def restore_backup(
    database: Database,
    backup_path: Path | str,
    safety_backup_path: Path | str | None = None,
) -> Path | None:
    source_path = Path(backup_path)
    if not source_path.exists():
        raise BackupError("No existe el archivo de respaldo indicado.")
    if source_path.resolve() == database.path.resolve():
        raise BackupError("El respaldo y la base de datos no pueden ser el mismo archivo.")

    try:
        # Validate the backup completely before the live database is touched.
        with closing(
            sqlite3.connect(f"{source_path.resolve().as_uri()}?mode=ro", uri=True)
        ) as source:
            _ensure_healthy(source)
            _ensure_suitelocal_schema(source)
        safety_path = None
        if safety_backup_path is not None:
            safety_path = create_backup(database, safety_backup_path)
        with (
            closing(sqlite3.connect(source_path)) as source,
            closing(sqlite3.connect(database.path)) as target,
        ):
            source.backup(target)
            target.commit()
            _ensure_healthy(target)
    except (OSError, sqlite3.Error) as error:
        raise BackupError("No se pudo restaurar el respaldo de la base de datos.") from error
    return safety_path


def _ensure_healthy(connection: sqlite3.Connection) -> None:
    result = connection.execute("PRAGMA integrity_check").fetchone()
    if result is None or result[0] != "ok":
        raise BackupError("La base de datos no superó la comprobación de integridad.")


def _ensure_suitelocal_schema(connection: sqlite3.Connection) -> None:
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    if not REQUIRED_TABLES <= {row[0] for row in rows}:
        raise BackupError("El archivo indicado no pertenece a SuiteLocal.")


def _temporary_path(target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, path = tempfile.mkstemp(
        prefix=f".{target.stem}-", suffix=".sqlite.tmp", dir=target.parent
    )
    os.close(file_descriptor)
    return Path(path)
