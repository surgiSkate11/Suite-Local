import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from suitelocal.application.einvoice import PassResult, ProcessReport
from suitelocal.ui.components.einvoice_runner import (
    INTERVAL_MS,
    EInvoiceRunner,
    failure_message,
    thread_pool_executor,
)

NOW = datetime(2026, 3, 5, 20, 0, tzinfo=UTC)
OK = PassResult(ProcessReport(), 0)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class Harness:
    """A runner with a scripted pass and an executor the test controls."""

    def __init__(self, enabled: bool = True, hold: bool = False) -> None:
        self.enabled = enabled
        self.hold = hold
        self.results: list[PassResult] = [OK]
        self.passes: list[datetime] = []
        self.held: list[Callable[[], None]] = []
        self.warnings: list[str] = []
        self.pending: list[int] = []
        self.runner = EInvoiceRunner(
            is_enabled=lambda: self.enabled,
            run_pass=self._run_pass,
            executor=self._execute,
            clock=lambda: NOW,
        )
        self.runner.warning.connect(self.warnings.append)
        self.runner.pending_changed.connect(self.pending.append)

    def _run_pass(self, now: datetime) -> PassResult:
        self.passes.append(now)
        return self.results.pop(0) if len(self.results) > 1 else self.results[0]

    def _execute(self, work: Callable[[], None]) -> None:
        if self.hold:
            self.held.append(work)
        else:
            work()


def test_the_runner_checks_every_two_minutes(qapp):
    harness = Harness()

    assert INTERVAL_MS == 120_000
    assert harness.runner.interval_ms == 120_000
    assert harness.runner.is_active is False
    harness.runner.start()
    assert harness.runner.is_active is True
    harness.runner.stop()
    assert harness.runner.is_active is False


def test_nothing_runs_while_electronic_invoicing_is_disabled(qapp):
    harness = Harness(enabled=False)

    assert harness.runner.tick() is False

    assert harness.passes == []
    assert harness.pending == []


def test_an_enabled_tick_runs_one_pass_with_the_clock_time(qapp):
    harness = Harness()

    assert harness.runner.tick() is True

    assert harness.passes == [NOW]
    assert harness.runner.running is False


def test_a_tick_never_overlaps_a_pass_that_is_still_running(qapp):
    harness = Harness(hold=True)

    assert harness.runner.tick() is True
    assert harness.runner.running is True
    assert harness.runner.tick() is False
    assert harness.runner.tick() is False
    assert len(harness.held) == 1

    harness.held.pop()()

    assert harness.runner.running is False
    assert harness.passes == [NOW]
    assert harness.runner.tick() is True


def test_the_open_count_is_reported_after_every_pass(qapp):
    harness = Harness()
    harness.results = [PassResult(ProcessReport(), 3), PassResult(ProcessReport(), 0)]

    harness.runner.tick()
    harness.runner.tick()

    assert harness.pending == [3, 0]


def test_an_unknown_open_count_is_not_reported(qapp):
    harness = Harness()
    harness.results = [PassResult(None, None, "boom")]

    harness.runner.tick()

    assert harness.pending == []


def test_a_clean_pass_shows_no_warning(qapp):
    harness = Harness()
    harness.results = [PassResult(ProcessReport(sent=(1,), authorized=(2,)), 1)]

    harness.runner.tick()

    assert harness.warnings == []


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (PassResult(None, 1, "sin permiso"), "No se pudieron procesar las facturas electrónicas"),
        (PassResult(ProcessReport(rejected=(1,)), 0), "El SRI no aceptó 1 factura electrónica"),
        (
            PassResult(ProcessReport(rejected=(1, 2)), 0),
            "El SRI no aceptó 2 facturas electrónicas",
        ),
        (PassResult(ProcessReport(deferred=(1,)), 1), "No se pudo contactar al SRI"),
        (PassResult(ProcessReport(near_deadline=(1,)), 1), "plazo de 72 horas"),
    ],
)
def test_each_kind_of_failed_pass_shows_exactly_one_warning(qapp, result, expected):
    harness = Harness()
    harness.results = [result]

    harness.runner.tick()

    assert len(harness.warnings) == 1
    assert expected in harness.warnings[0]


def test_a_pass_with_several_problems_still_shows_a_single_warning(qapp):
    harness = Harness()
    harness.results = [
        PassResult(ProcessReport(rejected=(1,), deferred=(2,), near_deadline=(2,)), 1, "boom")
    ]

    harness.runner.tick()

    assert len(harness.warnings) == 1
    assert "No se pudieron procesar" in harness.warnings[0]


def test_the_same_problem_is_not_repeated_every_two_minutes_but_returns_after_a_clean_pass(qapp):
    offline = PassResult(ProcessReport(deferred=(1,)), 1)
    harness = Harness()
    harness.results = [offline, offline, OK, offline]

    for _ in range(4):
        harness.runner.tick()

    assert len(harness.warnings) == 2


def test_failure_message_is_none_for_a_clean_pass():
    assert failure_message(OK) is None
    assert failure_message(PassResult(ProcessReport(sent=(1,), authorized=(2,)), 2)) is None


def test_a_failing_executor_does_not_leave_the_runner_stuck(qapp):
    def broken(work: Callable[[], None]) -> None:
        raise RuntimeError("sin hilos")

    runner = EInvoiceRunner(
        is_enabled=lambda: True, run_pass=lambda now: OK, executor=broken, clock=lambda: NOW
    )

    with pytest.raises(RuntimeError):
        runner.tick()

    assert runner.running is False


def test_the_thread_pool_runs_the_pass_off_the_ui_thread_and_reports_back_on_it(qapp):
    main_thread = threading.get_ident()
    seen: dict[str, int] = {}
    received: list[int] = []

    def run_pass(now: datetime) -> PassResult:
        seen["pass"] = threading.get_ident()
        return PassResult(ProcessReport(), 4)

    runner = EInvoiceRunner(
        is_enabled=lambda: True,
        run_pass=run_pass,
        executor=thread_pool_executor,
        clock=lambda: NOW,
    )

    def on_pending(count: int) -> None:
        seen["slot"] = threading.get_ident()
        received.append(count)

    runner.pending_changed.connect(on_pending)

    assert runner.tick() is True
    deadline = time.monotonic() + 5
    while not received and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.01)

    assert received == [4]
    assert seen["pass"] != main_thread
    assert seen["slot"] == main_thread
    assert runner.running is False
