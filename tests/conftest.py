import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication


@pytest.fixture(autouse=True)
def release_test_widgets():
    """Destroy every window a test leaves behind once the test ends.

    Button lambdas capture their widget, so a window a test merely drops is never garbage
    collected, and tests never run the event loop that processes deleteLater(). Leftovers
    would pile up and every later stylesheet change would repolish all of them.
    No fixture shares a window across tests (module scope only holds the QApplication).
    """
    yield
    application = QApplication.instance()
    if application is None:
        return
    for widget in application.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()
