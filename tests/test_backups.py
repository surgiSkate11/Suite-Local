import sqlite3
from contextlib import closing

import pytest

from suitelocal.application.auth import AuthService
from suitelocal.infrastructure.backups import BackupError, create_backup, restore_backup
from suitelocal.infrastructure.database import SCHEMA, Database


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


def test_restore_accepts_a_backup_made_before_the_tables_feature(tmp_path):
    old_backup = tmp_path / "old.sqlite"
    with closing(sqlite3.connect(old_backup)) as connection:
        connection.executescript(SCHEMA)
        connection.execute("INSERT INTO businesses (name) VALUES ('Tienda vieja')")
        connection.commit()
    database = setup_database(tmp_path)

    restore_backup(database, old_backup)

    with database.connect() as connection:
        assert connection.execute("SELECT name FROM businesses").fetchone()[0] == "Tienda vieja"
        assert not {"tables", "table_orders", "order_lines"} & {
            row[0] for row in connection.execute("SELECT name FROM sqlite_master")
        }
    # The next start-up creates what the old backup lacks.
    database.initialize()
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM tables").fetchone()[0] == 0
