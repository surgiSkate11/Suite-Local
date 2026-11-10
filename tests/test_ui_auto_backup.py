import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QWidget

from suitelocal.application.auth import AuthService
from suitelocal.domain.auth import Session
from suitelocal.infrastructure.auto_backup import (
    AutoBackupResult,
    AutoBackupSettings,
    AutoBackupSettingsRepository,
)
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import ProductRepository, SaleRepository
from suitelocal.infrastructure.settings import BusinessSettingsRepository
from suitelocal.ui.components import Toast
from suitelocal.ui.settings import SettingsWidget
from suitelocal.ui.shell import AppShell, AutoBackupRunner

ECT = timezone(timedelta(hours=-5), "ECT")
MORNING = datetime(2026, 3, 10, 9, 30, tzinfo=ECT)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class Clock:
    def __init__(self, now: datetime = MORNING) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class Executor:
    """Holds the submitted work so a test decides when (and whether) it finishes."""

    def __init__(self) -> None:
        self.pending: list[Callable[[], None]] = []

    def __call__(self, work: Callable[[], None]) -> None:
        self.pending.append(work)

    def finish_all(self) -> None:
        pending, self.pending = self.pending, []
        for work in pending:
            work()


class Folders:
    """Stands in for the folder dialog: answers with the scripted folder, records the calls."""

    def __init__(self, answer: Path | None) -> None:
        self.answer = answer
        self.calls = 0

    def __call__(self, parent: QWidget | None) -> Path | None:
        self.calls += 1
        return self.answer


@pytest.fixture
def env(qapp, tmp_path):
    database = Database(tmp_path / "suite.db")
    database.initialize()
    auth = AuthService(database)
    owner = auth.setup_owner("Tienda Sol", "owner", "clave-segura", "clave-segura")
    destination = tmp_path / "respaldos"
    destination.mkdir()
    return database, auth, owner, destination


def stored(database: Database) -> AutoBackupSettings:
    return AutoBackupSettingsRepository(database).get(1)


# -- the settings card --------------------------------------------------------------------


def build_settings(env, folders: Folders) -> SettingsWidget:
    database, _, owner, _ = env
    return SettingsWidget(
        BusinessSettingsRepository(database),
        Session(owner),
        database,
        printer_names=lambda: (),
        choose_backup_folder=folders,
    )


def test_the_card_starts_with_the_automatic_backup_off_keeping_seven(env):
    widget = build_settings(env, Folders(None))

    assert widget.auto_backup_enabled.text() == "Respaldar automáticamente cada día"
    assert widget.auto_backup_enabled.isChecked() is False
    assert widget.auto_backup_keep.value() == 7
    assert widget.auto_backup_keep.minimum() == 1
    assert widget.auto_backup_folder_label.text() == "Sin carpeta elegida"


def test_the_chosen_folder_is_shown_and_everything_is_saved_with_the_card(env):
    database, _, _, destination = env
    folders = Folders(destination)
    widget = build_settings(env, folders)
    seen: list[tuple[str, str]] = []
    widget.notification.connect(lambda message, state: seen.append((message, state)))

    widget.auto_backup_folder_button.click()
    assert folders.calls == 1
    assert widget.auto_backup_folder_label.text() == str(destination)
    assert stored(database).folder == ""  # nothing is written until the card is saved
    widget.auto_backup_enabled.setChecked(True)
    widget.auto_backup_keep.setValue(3)
    widget.save_button.click()

    assert stored(database) == AutoBackupSettings(True, str(destination), 3, None)
    assert widget.message.isHidden()
    assert seen and seen[-1][1] == "success"


def test_the_saved_values_are_shown_again_when_the_page_is_rebuilt(env):
    database, _, _, destination = env
    AutoBackupSettingsRepository(database).save(1, enabled=True, folder=str(destination), keep=4)

    widget = build_settings(env, Folders(None))

    assert widget.auto_backup_enabled.isChecked() is True
    assert widget.auto_backup_keep.value() == 4
    assert widget.auto_backup_folder_label.text() == str(destination)


def test_cancelling_the_folder_dialog_keeps_the_current_folder(env):
    _, _, _, destination = env
    folders = Folders(destination)
    widget = build_settings(env, folders)
    widget.auto_backup_folder_button.click()
    folders.answer = None

    widget.auto_backup_folder_button.click()

    assert widget.auto_backup_folder_label.text() == str(destination)


def test_enabling_without_a_folder_shows_the_inline_error_and_saves_nothing(env):
    database, _, _, _ = env
    widget = build_settings(env, Folders(None))
    widget.name.setText("Otro nombre")
    widget.auto_backup_enabled.setChecked(True)

    widget.save_button.click()

    assert widget.message.text() == "Elegí una carpeta para los respaldos automáticos."
    assert not widget.message.isHidden()
    assert stored(database) == AutoBackupSettings(False, "", 7, None)
    assert BusinessSettingsRepository(database).get(1).name == "Tienda Sol"


def test_saving_the_card_with_the_backup_off_needs_no_folder(env):
    database, _, _, _ = env
    widget = build_settings(env, Folders(None))
    widget.auto_backup_keep.setValue(10)

    widget.save_button.click()

    assert widget.message.isHidden()
    assert stored(database) == AutoBackupSettings(False, "", 10, None)


# -- the runner ---------------------------------------------------------------------------


class Harness:
    """A runner whose "is it due" answer, backup and executor are all under the test's control."""

    def __init__(self) -> None:
        self.clock = Clock()
        self.executor = Executor()
        self.due = True
        self.runs: list[datetime] = []
        self.outcome = AutoBackupResult(MORNING, Path("x.sqlite"), None)
        self.runner = AutoBackupRunner(
            is_due=self._is_due,
            run=self._run,
            executor=self.executor,
            clock=self.clock,
        )
        self.succeeded: list[datetime] = []
        self.failed: list[str] = []
        self.runner.succeeded.connect(self.succeeded.append)
        self.runner.failed.connect(self.failed.append)

    def _is_due(self, now: datetime) -> bool:
        return self.due

    def _run(self, now: datetime) -> AutoBackupResult:
        self.runs.append(now)
        if self.outcome.error is None:
            self.due = False  # what the real service does: the day is now covered
        return self.outcome


@pytest.fixture
def harness(qapp):
    return Harness()


def test_the_runner_checks_every_hour(harness):
    assert harness.runner.interval_ms == 3_600_000
    assert harness.runner.is_active is False
    harness.runner.start()
    assert harness.runner.is_active is True
    harness.runner.stop()
    assert harness.runner.is_active is False


def test_a_tick_when_nothing_is_due_starts_no_work(harness):
    harness.due = False

    assert harness.runner.tick() is False

    assert harness.executor.pending == []


def test_a_tick_while_a_backup_is_running_is_skipped(harness):
    assert harness.runner.tick() is True
    assert harness.runner.running is True

    assert harness.runner.tick() is False
    assert harness.runner.tick() is False
    assert len(harness.executor.pending) == 1

    harness.executor.finish_all()
    assert harness.runs == [MORNING]
    assert harness.runner.running is False
    assert harness.succeeded == [MORNING]


def test_the_backup_runs_once_per_day(harness):
    harness.runner.tick()
    harness.executor.finish_all()
    harness.clock.now = MORNING + timedelta(hours=1)

    assert harness.runner.tick() is False

    harness.due = True  # the next calendar day
    harness.clock.now = MORNING + timedelta(days=1)
    assert harness.runner.tick() is True
    harness.executor.finish_all()
    assert harness.runs == [MORNING, MORNING + timedelta(days=1)]


def test_the_work_is_handed_to_the_executor_not_run_inline(harness):
    harness.runner.tick()

    assert harness.runs == []
    assert len(harness.executor.pending) == 1


def test_a_failed_attempt_emits_one_warning_and_the_next_tick_can_retry(harness):
    harness.outcome = AutoBackupResult(None, None, "La carpeta no existe")
    harness.runner.tick()
    harness.executor.finish_all()

    assert harness.failed == ["No se pudo hacer el respaldo automático: La carpeta no existe"]
    assert harness.succeeded == []
    assert harness.runner.running is False
    assert harness.runner.tick() is True


def test_a_backup_that_raises_still_frees_the_runner(qapp):
    executor = Executor()
    failures: list[str] = []

    def explode(now: datetime) -> AutoBackupResult:
        raise RuntimeError("disco lleno")

    runner = AutoBackupRunner(
        is_due=lambda now: True, run=explode, executor=executor, clock=Clock()
    )
    runner.failed.connect(failures.append)

    runner.tick()
    executor.finish_all()

    assert failures == ["No se pudo hacer el respaldo automático: disco lleno"]
    assert runner.running is False


def test_an_executor_that_refuses_the_work_frees_the_runner(qapp):
    def refuse(work: Callable[[], None]) -> None:
        raise RuntimeError("sin hilos")

    runner = AutoBackupRunner(
        is_due=lambda now: True,
        run=lambda now: AutoBackupResult(None, None, None),
        executor=refuse,
        clock=Clock(),
    )

    with pytest.raises(RuntimeError):
        runner.tick()

    assert runner.running is False


# -- the shell ----------------------------------------------------------------------------


@pytest.fixture
def make_shell(env):
    database, auth, owner, _ = env
    windows: list[AppShell] = []

    def make(executor: Executor, clock: Clock | None = None) -> AppShell:
        window = AppShell(
            ProductRepository(database),
            SaleRepository(database),
            Session(owner),
            BusinessSettingsRepository(database),
            auth,
            database,
            auto_backup_executor=executor,
            auto_backup_clock=clock or Clock(),
        )
        windows.append(window)
        return window

    yield make
    for window in windows:
        window.close()
        window.deleteLater()


def toasts(shell: AppShell) -> list[Toast]:
    return shell.toasts.findChildren(Toast)


def turn_on(env) -> None:
    database, _, _, destination = env
    AutoBackupSettingsRepository(database).save(1, enabled=True, folder=str(destination), keep=7)


def test_the_status_bar_says_never_when_there_is_no_backup(env, make_shell):
    shell = make_shell(Executor())

    assert shell.status_backup.text() == "Último respaldo: nunca"


def test_the_status_bar_shows_the_persisted_time_on_load(env, make_shell):
    database, _, _, _ = env
    AutoBackupSettingsRepository(database).record_success(
        1, datetime(2026, 3, 8, 18, 5, tzinfo=ECT)
    )

    shell = make_shell(Executor())

    assert shell.status_backup.text() == "Último respaldo: 08/03 18:05"


def test_nothing_runs_at_startup_while_the_backup_is_off(env, make_shell):
    executor = Executor()

    make_shell(executor)

    assert executor.pending == []


def test_a_due_backup_starts_with_the_app_off_the_calling_thread_and_updates_the_status(
    env, make_shell
):
    _, _, _, destination = env
    turn_on(env)
    executor = Executor()

    shell = make_shell(executor)

    assert len(executor.pending) == 1  # started at startup, handed to the executor
    assert list(destination.iterdir()) == []  # ...and not run inline
    executor.finish_all()
    assert [entry.name for entry in destination.iterdir()] == [
        "suitelocal-auto-20260310-093000.sqlite"
    ]
    assert shell.status_backup.text() == "Último respaldo: 10/03 09:30"
    assert stored(env[0]).last_backup_at == MORNING
    assert toasts(shell) == []


def test_the_hourly_tick_does_not_back_up_twice_the_same_day(env, make_shell):
    turn_on(env)
    executor = Executor()
    clock = Clock()
    shell = make_shell(executor, clock)
    executor.finish_all()
    clock.now = MORNING + timedelta(hours=1)

    assert shell.auto_backup_runner.tick() is False

    assert executor.pending == []


def test_a_failed_backup_shows_exactly_one_warning_toast_and_keeps_the_status(env, make_shell):
    database, _, _, destination = env
    turn_on(env)
    destination.rmdir()
    executor = Executor()

    shell = make_shell(executor)
    executor.finish_all()

    shown = toasts(shell)
    assert len(shown) == 1
    assert shown[0].message.startswith("No se pudo hacer el respaldo automático: ")
    assert shown[0].property("state") == "warning"
    assert shell.status_backup.text() == "Último respaldo: nunca"
    assert stored(database).last_backup_at is None


def test_enabling_it_in_settings_backs_up_right_away(env, make_shell):
    database, _, _, destination = env
    executor = Executor()
    shell = make_shell(executor)
    assert executor.pending == []
    page = shell.settings_page
    assert page is not None

    page.choose_backup_folder = Folders(destination)
    page.auto_backup_folder_button.click()
    page.auto_backup_enabled.setChecked(True)
    page.save_button.click()

    assert len(executor.pending) == 1
    executor.finish_all()
    assert shell.status_backup.text() == "Último respaldo: 10/03 09:30"


def test_closing_the_window_stops_the_timer(env, make_shell):
    shell = make_shell(Executor())
    assert shell.auto_backup_runner.is_active is True

    shell.close()

    assert shell.auto_backup_runner.is_active is False
