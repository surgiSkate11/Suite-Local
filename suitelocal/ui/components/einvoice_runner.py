"""Periodic, off-thread processing of the electronic-invoice queue.

The runner is only a clock and a gate: what a pass does lives in `application.einvoice`, and
how it is executed is injected, so tests run it synchronously and the app uses a thread pool.
"""

from collections.abc import Callable
from datetime import UTC, datetime

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

from suitelocal.application.einvoice import PassResult

INTERVAL_MS = 120_000

Executor = Callable[[Callable[[], None]], None]


class _Job(QRunnable):
    def __init__(self, work: Callable[[], None]) -> None:
        super().__init__()
        self._work = work

    def run(self) -> None:
        self._work()


def thread_pool_executor(work: Callable[[], None]) -> None:
    """Run `work` on Qt's global thread pool, never on the UI thread."""
    QThreadPool.globalInstance().start(_Job(work))


def _invoices(count: int) -> str:
    return "1 factura electrónica" if count == 1 else f"{count} facturas electrónicas"


def failure_message(result: PassResult) -> str | None:
    """One warning for a failed pass, the most important problem first; None if it went well."""
    if result.error:
        return f"No se pudieron procesar las facturas electrónicas: {result.error}"
    report = result.report
    if report is None:
        return None
    if report.rejected:
        return (
            f"El SRI no aceptó {_invoices(len(report.rejected))}. "
            "Revisalas en Facturas electrónicas."
        )
    if report.near_deadline:
        return (
            f"{_invoices(len(report.near_deadline))} sin enviar al SRI "
            "están cerca del plazo de 72 horas."
        )
    if report.deferred:
        return "No se pudo contactar al SRI. Las facturas pendientes se reintentarán solas."
    return None


class EInvoiceRunner(QObject):
    """Every `interval_ms`, runs one pass on an executor; a pass never starts over another."""

    # Both are emitted on the UI thread, whatever thread the pass ran on.
    warning = Signal(str)
    pending_changed = Signal(int)
    # After every pass, whatever its outcome, so a page showing the queue can reload.
    pass_completed = Signal()
    _finished = Signal(object)

    def __init__(
        self,
        *,
        is_enabled: Callable[[], bool],
        run_pass: Callable[[datetime], PassResult],
        executor: Executor = thread_pool_executor,
        clock: Callable[[], datetime] | None = None,
        interval_ms: int = INTERVAL_MS,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._is_enabled = is_enabled
        self._run_pass = run_pass
        self._executor = executor
        self._clock = clock or (lambda: datetime.now(UTC))
        self._running = False
        self._last_warning: str | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.tick)
        self._finished.connect(self._on_finished)

    @property
    def interval_ms(self) -> int:
        return self._timer.interval()

    @property
    def is_active(self) -> bool:
        return self._timer.isActive()

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def tick(self) -> bool:
        """Start a pass unless invoicing is off or the previous pass has not finished."""
        if self._running or not self._is_enabled():
            return False
        self._running = True
        now = self._clock()

        def work() -> None:
            try:
                result = self._run_pass(now)
            except Exception as failure:
                # Whatever the pass raises still has to reach the UI thread, or the running
                # flag would never clear and every later pass would be skipped.
                result = PassResult(None, None, str(failure) or type(failure).__name__)
            try:
                self._finished.emit(result)
            except RuntimeError:
                # The window was closed while the pass ran: nobody is left to tell.
                pass

        try:
            self._executor(work)
        except BaseException:
            self._running = False
            raise
        return True

    def _on_finished(self, result: object) -> None:
        try:
            if not isinstance(result, PassResult):
                return
            if result.open_count is not None:
                self.pending_changed.emit(result.open_count)
            message = failure_message(result)
            if message is None:
                self._last_warning = None
            elif message != self._last_warning:
                # Offline is the normal state of this app: say it once, not every two minutes.
                self._last_warning = message
                self.warning.emit(message)
        finally:
            # Cleared even if a listener raises, so the next tick can always run.
            self._running = False
            self.pass_completed.emit()
