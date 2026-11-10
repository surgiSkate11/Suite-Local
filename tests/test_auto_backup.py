import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from suitelocal.application.auth import AuthService
from suitelocal.infrastructure import auto_backup
from suitelocal.infrastructure.auto_backup import (
    DEFAULT_KEEP,
    AutoBackupService,
    AutoBackupSettings,
    AutoBackupSettingsRepository,
    backup_file_name,
    format_last_backup,
    is_backup_due,
    prune_backups,
)
from suitelocal.infrastructure.database import Database

ECT = timezone(timedelta(hours=-5), "ECT")
NOON = datetime(2026, 3, 10, 12, 0, tzinfo=ECT)


@pytest.fixture
def database(tmp_path) -> Database:
    database = Database(tmp_path / "suite.db")
    database.initialize()
    AuthService(database).setup_owner("Tienda Sol", "owner", "clave-segura", "clave-segura")
    return database


@pytest.fixture
def folder(tmp_path) -> Path:
    path = tmp_path / "respaldos"
    path.mkdir()
    return path


def enabled(folder: Path, keep: int = 7, last: datetime | None = None) -> AutoBackupSettings:
    return AutoBackupSettings(True, str(folder), keep, last)


# -- when a backup is due -----------------------------------------------------------------


def test_a_backup_is_due_when_enabled_with_a_folder_and_none_was_ever_made(folder):
    assert is_backup_due(enabled(folder), NOON) is True


def test_a_disabled_backup_is_never_due(folder):
    assert is_backup_due(AutoBackupSettings(False, str(folder), 7, None), NOON) is False


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_backup_without_a_folder_is_never_due(blank):
    assert is_backup_due(AutoBackupSettings(True, blank, 7, None), NOON) is False


def test_no_second_backup_is_due_on_the_same_calendar_day(folder):
    last = datetime(2026, 3, 10, 0, 0, 1, tzinfo=ECT)

    assert is_backup_due(enabled(folder, last=last), datetime(2026, 3, 10, 23, 59, tzinfo=ECT)) is (
        False
    )


def test_a_backup_is_due_again_right_after_midnight(folder):
    last = datetime(2026, 3, 10, 23, 59, tzinfo=ECT)

    assert is_backup_due(enabled(folder, last=last), datetime(2026, 3, 11, 0, 1, tzinfo=ECT))


def test_the_day_is_the_local_one_not_the_utc_one(folder):
    # 20:00 in Ecuador is already the 11th in UTC; a backup made at noon of the 10th is still
    # today's backup.
    last = datetime(2026, 3, 10, 12, 0, tzinfo=ECT)
    now = datetime(2026, 3, 10, 20, 0, tzinfo=ECT)
    assert last.astimezone(UTC).date() != now.astimezone(UTC).date()

    assert is_backup_due(enabled(folder, last=last), now) is False
    assert is_backup_due(enabled(folder, last=last.astimezone(UTC)), now) is False


# -- file name and pruning ----------------------------------------------------------------


def test_the_file_name_carries_the_local_timestamp():
    assert backup_file_name(datetime(2026, 3, 10, 7, 5, 9, tzinfo=ECT)) == (
        "suitelocal-auto-20260310-070509.sqlite"
    )


def names(folder: Path) -> set[str]:
    return {entry.name for entry in folder.iterdir()}


def test_pruning_keeps_the_newest_copies_and_ignores_files_that_are_not_ours(folder):
    ours = [f"suitelocal-auto-202603{day:02d}-120000.sqlite" for day in range(1, 11)]
    foreign = [
        "notas.txt",
        "suitelocal-respaldo.sqlite",
        "suitelocal-auto-20260301-120000.sqlite.bak",
        "suitelocal-auto-2026-03-01.sqlite",
        "otro-suitelocal-auto-20260301-120000.sqlite",
    ]
    for name in (*ours, *foreign):
        (folder / name).write_bytes(b"x")
    subfolder = folder / "suitelocal-auto-20200101-000000.sqlite"
    subfolder.mkdir()
    (subfolder / "dentro.sqlite").write_bytes(b"x")

    prune_backups(folder, 3)

    assert names(folder) == {*ours[-3:], *foreign, subfolder.name}
    assert (subfolder / "dentro.sqlite").exists()


def test_pruning_with_fewer_copies_than_the_limit_deletes_nothing(folder):
    (folder / "suitelocal-auto-20260301-120000.sqlite").write_bytes(b"x")

    prune_backups(folder, 7)

    assert len(names(folder)) == 1


def test_pruning_a_missing_folder_does_nothing(tmp_path):
    prune_backups(tmp_path / "no-existe", 3)


# -- the backup itself --------------------------------------------------------------------


def test_the_service_makes_a_valid_sqlite_copy_through_create_backup(database, folder, monkeypatch):
    repository = AutoBackupSettingsRepository(database)
    repository.save(1, enabled=True, folder=str(folder), keep=7)
    calls: list[Path] = []
    real = auto_backup.create_backup

    def spy(source: Database, destination: Path | str) -> Path:
        calls.append(Path(destination))
        return real(source, destination)

    monkeypatch.setattr(auto_backup, "create_backup", spy)

    result = AutoBackupService(database, 1).run(NOON)

    expected = folder / "suitelocal-auto-20260310-120000.sqlite"
    assert calls == [expected]
    assert result.error is None and result.at == NOON and result.path == expected
    with closing(sqlite3.connect(expected)) as copy:
        assert copy.execute("SELECT name FROM businesses").fetchone()[0] == "Tienda Sol"
        assert copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_a_successful_run_stores_the_time_and_is_not_due_again_that_day(database, folder):
    repository = AutoBackupSettingsRepository(database)
    repository.save(1, enabled=True, folder=str(folder), keep=7)
    service = AutoBackupService(database, 1)
    assert service.is_due(NOON) is True

    service.run(NOON)

    assert repository.get(1).last_backup_at == NOON
    assert service.is_due(NOON + timedelta(hours=5)) is False
    assert service.is_due(NOON + timedelta(hours=13)) is True


def test_a_run_prunes_beyond_the_configured_number(database, folder):
    AutoBackupSettingsRepository(database).save(1, enabled=True, folder=str(folder), keep=2)
    service = AutoBackupService(database, 1)

    for day in (8, 9, 10):
        service.run(datetime(2026, 3, day, 12, 0, tzinfo=ECT))

    assert names(folder) == {
        "suitelocal-auto-20260309-120000.sqlite",
        "suitelocal-auto-20260310-120000.sqlite",
    }


def test_a_missing_folder_fails_without_creating_it_or_storing_the_time(database, tmp_path):
    missing = tmp_path / "pendrive" / "respaldos"
    repository = AutoBackupSettingsRepository(database)
    repository.save(1, enabled=True, folder=str(missing), keep=7)

    result = AutoBackupService(database, 1).run(NOON)

    assert result.error is not None and result.at is None
    assert not missing.exists()
    assert repository.get(1).last_backup_at is None


def test_a_failing_backup_leaves_the_stored_time_unchanged(database, folder, monkeypatch):
    repository = AutoBackupSettingsRepository(database)
    repository.save(1, enabled=True, folder=str(folder), keep=7)
    yesterday = NOON - timedelta(days=1)
    repository.record_success(1, yesterday)

    def refuse(source: Database, destination: Path | str) -> Path:
        raise PermissionError("Acceso denegado")

    monkeypatch.setattr(auto_backup, "create_backup", refuse)

    result = AutoBackupService(database, 1).run(NOON)

    assert result.error == "Acceso denegado"
    assert repository.get(1).last_backup_at == yesterday
    assert names(folder) == set()


# -- the status text ----------------------------------------------------------------------


def test_the_status_text_shows_day_month_and_24_hour_clock():
    assert format_last_backup(datetime(2026, 3, 5, 18, 7, tzinfo=ECT), ECT) == (
        "Último respaldo: 05/03 18:07"
    )


def test_the_status_text_is_shown_in_the_given_zone():
    utc = datetime(2026, 3, 6, 1, 7, tzinfo=UTC)

    assert format_last_backup(utc, ECT) == "Último respaldo: 05/03 20:07"


def test_the_status_text_says_never_without_a_backup():
    assert format_last_backup(None, ECT) == "Último respaldo: nunca"


# -- settings persistence -----------------------------------------------------------------


def test_the_defaults_are_off_no_folder_and_seven_copies(database):
    stored = AutoBackupSettingsRepository(database).get(1)

    assert stored == AutoBackupSettings(False, "", DEFAULT_KEEP, None)
    assert DEFAULT_KEEP == 7


def test_the_settings_round_trip(database, folder):
    repository = AutoBackupSettingsRepository(database)

    saved = repository.save(1, enabled=True, folder=str(folder), keep=3)

    assert saved == AutoBackupSettings(True, str(folder), 3, None)
    assert repository.get(1) == saved


def test_saving_does_not_forget_the_last_backup_time(database, folder):
    repository = AutoBackupSettingsRepository(database)
    repository.save(1, enabled=True, folder=str(folder), keep=3)
    repository.record_success(1, NOON)

    repository.save(1, enabled=True, folder=str(folder), keep=5)

    assert repository.get(1).last_backup_at == NOON


def test_enabling_without_a_folder_is_rejected_and_nothing_is_saved(database):
    repository = AutoBackupSettingsRepository(database)

    with pytest.raises(ValueError, match="Elegí una carpeta para los respaldos automáticos."):
        repository.save(1, enabled=True, folder="  ", keep=7)

    assert repository.get(1) == AutoBackupSettings(False, "", 7, None)


@pytest.mark.parametrize("keep", [0, -1])
def test_keeping_fewer_than_one_copy_is_rejected(database, folder, keep):
    repository = AutoBackupSettingsRepository(database)

    with pytest.raises(ValueError, match="al menos 1"):
        repository.save(1, enabled=False, folder=str(folder), keep=keep)

    assert repository.get(1).keep == 7


def test_a_folder_can_be_kept_while_the_backup_is_off(database, folder):
    repository = AutoBackupSettingsRepository(database)

    saved = repository.save(1, enabled=False, folder=str(folder), keep=7)

    assert saved.folder == str(folder) and saved.enabled is False


# -- migration ----------------------------------------------------------------------------

NEW_COLUMNS = {
    "auto_backup_enabled",
    "auto_backup_folder",
    "auto_backup_keep",
    "last_auto_backup_at",
}


def columns(database: Database) -> set[str]:
    with database.connect() as connection:
        return {row["name"] for row in connection.execute("PRAGMA table_info(business_settings)")}


def old_database(path: Path) -> Database:
    """A business_settings table as it was before the automatic backup existed."""
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE businesses (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE business_settings (
            business_id INTEGER PRIMARY KEY REFERENCES businesses(id),
            currency_symbol TEXT NOT NULL DEFAULT '$',
            low_stock_threshold INTEGER NOT NULL DEFAULT 3,
            enabled_payment_methods TEXT NOT NULL DEFAULT 'cash,transfer',
            tax_rate_basis_points INTEGER NOT NULL DEFAULT 0
        );
        INSERT INTO businesses (id, name) VALUES (1, 'Tienda Sol');
        INSERT INTO business_settings (business_id) VALUES (1);
        """
    )
    connection.commit()
    connection.close()
    return Database(path)


def test_the_migration_adds_the_columns_to_an_old_schema_and_is_idempotent(tmp_path):
    database = old_database(tmp_path / "old.db")
    assert NEW_COLUMNS.isdisjoint(columns(database))

    database.initialize()
    database.initialize()

    assert NEW_COLUMNS <= columns(database)
    assert AutoBackupSettingsRepository(database).get(1) == AutoBackupSettings(False, "", 7, None)


def test_a_fresh_database_has_the_columns_and_initializing_again_keeps_the_values(database, folder):
    assert NEW_COLUMNS <= columns(database)
    AutoBackupSettingsRepository(database).save(1, enabled=True, folder=str(folder), keep=4)

    database.initialize()

    assert AutoBackupSettingsRepository(database).get(1).keep == 4
