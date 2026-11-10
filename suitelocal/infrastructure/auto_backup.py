"""Daily automatic backup to a folder the owner chose (a USB drive or a cloud-synced folder).

Everything here is Qt-free: when a backup is due, how a copy is named and pruned, and the
settings persisted per business. The hourly timer and the worker thread live in the UI shell.
"""

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, tzinfo
from pathlib import Path

from suitelocal.infrastructure.backups import BackupError, create_backup
from suitelocal.infrastructure.database import Database

DEFAULT_KEEP = 7
FILE_PREFIX = "suitelocal-auto-"
# Pruning only ever touches files with exactly this name, so a folder shared with other
# files (or with manual backups) is never cleaned beyond our own copies.
FILE_PATTERN = re.compile(r"suitelocal-auto-\d{8}-\d{6}\.sqlite")
FOLDER_REQUIRED = "Elegí una carpeta para los respaldos automáticos."
KEEP_REQUIRED = "Conservá al menos 1 respaldo."


@dataclass(frozen=True)
class AutoBackupSettings:
    enabled: bool = False
    folder: str = ""
    keep: int = DEFAULT_KEEP
    last_backup_at: datetime | None = None


@dataclass(frozen=True)
class AutoBackupResult:
    """Outcome of one attempt: `at` and `path` on success, `error` (a message) on failure."""

    at: datetime | None
    path: Path | None
    error: str | None


def is_backup_due(settings: AutoBackupSettings, now: datetime) -> bool:
    """A backup is due when it is on, has a folder and none was made today (local date)."""
    if not settings.enabled or not settings.folder.strip():
        return False
    last = settings.last_backup_at
    if last is None:
        return True
    return last.astimezone(now.tzinfo).date() != now.date()


def backup_file_name(now: datetime) -> str:
    return f"{FILE_PREFIX}{now:%Y%m%d-%H%M%S}.sqlite"


def prune_backups(folder: Path, keep: int) -> None:
    """Delete our oldest copies beyond `keep`; other files and subfolders are never touched.

    Best effort: a copy that cannot be deleted stays, and the backup just made is not undone.
    """
    try:
        entries = [
            entry
            for entry in folder.iterdir()
            if FILE_PATTERN.fullmatch(entry.name) and entry.is_file() and not entry.is_symlink()
        ]
    except OSError:
        return
    # The name starts with the timestamp, so alphabetical order is chronological order.
    entries.sort(key=lambda entry: entry.name, reverse=True)
    for entry in entries[keep:]:
        try:
            entry.unlink()
        except OSError:
            continue


def format_last_backup(last: datetime | None, zone: tzinfo | None) -> str:
    """The status bar text, with the time shown in `zone`."""
    if last is None:
        return "Último respaldo: nunca"
    return f"Último respaldo: {last.astimezone(zone):%d/%m %H:%M}"


def format_backup_failure(at: datetime, zone: tzinfo | None) -> str:
    """The status bar text after a failed attempt, so the problem stays visible."""
    return f"Último respaldo: falló {at.astimezone(zone):%d/%m %H:%M}"


class AutoBackupSettingsRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def get(self, business_id: int) -> AutoBackupSettings:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT auto_backup_enabled, auto_backup_folder, auto_backup_keep,
                    last_auto_backup_at
                FROM business_settings WHERE business_id = ?
                """,
                (business_id,),
            ).fetchone()
        if row is None:
            return AutoBackupSettings()
        return AutoBackupSettings(
            bool(row["auto_backup_enabled"]),
            row["auto_backup_folder"],
            row["auto_backup_keep"],
            _parse_time(row["last_auto_backup_at"]),
        )

    def save(
        self, business_id: int, *, enabled: bool, folder: str, keep: int
    ) -> AutoBackupSettings:
        """Validate and store the owner's choices; the last backup time is kept as it is."""
        folder = folder.strip()
        if enabled and not folder:
            raise ValueError(FOLDER_REQUIRED)
        if keep < 1:
            raise ValueError(KEEP_REQUIRED)
        with self.database.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO business_settings (business_id) VALUES (?)", (business_id,)
            )
            connection.execute(
                """
                UPDATE business_settings
                SET auto_backup_enabled = ?, auto_backup_folder = ?, auto_backup_keep = ?
                WHERE business_id = ?
                """,
                (int(enabled), folder, keep, business_id),
            )
        return self.get(business_id)

    def record_success(self, business_id: int, at: datetime) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO business_settings (business_id) VALUES (?)", (business_id,)
            )
            connection.execute(
                "UPDATE business_settings SET last_auto_backup_at = ? WHERE business_id = ?",
                (at.isoformat(timespec="seconds"), business_id),
            )


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    # A stored time always carries its offset; a bare one is read in the system's zone.
    return parsed if parsed.tzinfo is not None else parsed.astimezone()


class AutoBackupService:
    """Decides and performs the automatic backup of one business. Safe to run on a worker."""

    def __init__(self, database: Database, business_id: int) -> None:
        self.database = database
        self.business_id = business_id
        self.settings = AutoBackupSettingsRepository(database)

    def last_backup_at(self) -> datetime | None:
        return self.settings.get(self.business_id).last_backup_at

    def is_due(self, now: datetime) -> bool:
        return is_backup_due(self.settings.get(self.business_id), now)

    def run(self, now: datetime) -> AutoBackupResult:
        """Back up through `create_backup`, prune old copies and store the time on success.

        A failure never raises and never changes the stored time, so the next tick retries.
        """
        settings = self.settings.get(self.business_id)
        folder = Path(settings.folder)
        try:
            # Never create the folder: a missing one usually means an unplugged drive.
            if not folder.is_dir():
                raise BackupError("La carpeta de respaldos no existe o no está disponible.")
            path = create_backup(self.database, folder / backup_file_name(now))
            self.settings.record_success(self.business_id, now)
        except (BackupError, OSError, sqlite3.Error) as error:
            return AutoBackupResult(None, None, _reason(error))
        prune_backups(folder, settings.keep)
        return AutoBackupResult(now, path, None)


def _reason(error: Exception) -> str:
    cause = error.__cause__
    return str(cause or error) or type(cause or error).__name__
