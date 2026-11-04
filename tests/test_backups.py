import sqlite3

import pytest

from suitelocal.application.auth import AuthService
from suitelocal.infrastructure.backups import BackupError, create_backup, restore_backup
from suitelocal.infrastructure.database import Database


def setup_database(tmp_path):
    database = Database(tmp_path / "suite.db")
    database.initialize()
    AuthService(database).setup_owner("Tienda Sol", "owner", "clave-segura", "clave-segura")
    return database


def test_create_backup_preserves_database_contents(tmp_path):
    database = setup_database(tmp_path)
    backup_path = tmp_path / "backups" / "suite-backup.sqlite"

    result = create_backup(database, backup_path)

    assert result == backup_path
    with sqlite3.connect(backup_path) as connection:
        assert connection.execute("SELECT name FROM businesses").fetchone()[0] == "Tienda Sol"
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_restore_backup_replaces_database_contents(tmp_path):
    database = setup_database(tmp_path)
    backup_path = tmp_path / "suite-backup.sqlite"
    create_backup(database, backup_path)

    with database.connect() as connection:
        connection.execute("UPDATE businesses SET name = 'Nombre incorrecto'")

    restore_backup(database, backup_path)

    with database.connect() as connection:
        assert connection.execute("SELECT name FROM businesses").fetchone()[0] == "Tienda Sol"


def test_restore_backup_creates_safety_copy_before_replacing(tmp_path):
    database = setup_database(tmp_path)
    backup_path = tmp_path / "suite-backup.sqlite"
    safety_path = tmp_path / "before-restore.sqlite"
    create_backup(database, backup_path)

    with database.connect() as connection:
        connection.execute("UPDATE businesses SET name = 'Nombre incorrecto'")

    result = restore_backup(database, backup_path, safety_path)

    assert result == safety_path
    with sqlite3.connect(safety_path) as connection:
        assert (
            connection.execute("SELECT name FROM businesses").fetchone()[0] == "Nombre incorrecto"
        )


def test_backup_rejects_missing_or_same_path(tmp_path):
    database = setup_database(tmp_path)
    missing_database = Database(tmp_path / "missing.db")

    with pytest.raises(BackupError, match="No existe"):
        create_backup(missing_database, tmp_path / "backup.sqlite")
    with pytest.raises(BackupError, match="ubicación diferente"):
        create_backup(database, database.path)
