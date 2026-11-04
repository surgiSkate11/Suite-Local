import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect, QWidget

from suitelocal.application.auth import AuthService
from suitelocal.domain.auth import Session
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import ProductRepository, SaleRepository
from suitelocal.infrastructure.settings import BusinessSettingsRepository
from suitelocal.ui.components import Toast, ToastHost
from suitelocal.ui.shell import AppShell


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def shell(qapp, tmp_path):
    database = Database(tmp_path / "animation.db")
    database.initialize()
    auth = AuthService(database)
    owner = auth.setup_owner("Tienda Sol", "owner", "clave-segura", "clave-segura")
    window = AppShell(
        ProductRepository(database),
        SaleRepository(database),
        Session(owner),
        BusinessSettingsRepository(database),
        auth,
        database,
    )
    yield window
    window.deleteLater()


def test_hidden_shell_sets_sidebar_width_without_animation(shell):
    shell._set_sidebar_collapsed(True)

    assert shell.sidebar.maximumWidth() == 72
    assert shell.sidebar_animation is None


def test_visible_shell_animates_sidebar_to_target_width(shell):
    shell.resize(1300, 800)
    shell.show()
    shell._set_sidebar_collapsed(False)

    shell._set_sidebar_collapsed(True)
    assert shell.sidebar_animation is not None
    assert shell.sidebar_animation.duration() <= 200
    QTest.qWait(320)

    assert shell.sidebar.minimumWidth() == 72
    assert shell.sidebar.maximumWidth() == 72


def test_toast_fades_in_and_out(qapp):
    parent = QWidget()
    host = ToastHost(parent, duration_ms=50)

    toast = host.show_toast("Guardado")
    effect = toast.graphicsEffect()
    assert isinstance(effect, QGraphicsOpacityEffect)
    QTest.qWait(30)
    assert 0 < effect.opacity() <= 1
    QTest.qWait(400)

    assert [t for t in host.findChildren(Toast) if not t.isHidden()] == []


def test_fade_in_after_interrupted_fade_out_keeps_toast_visible(qapp):
    parent = QWidget()
    host = ToastHost(parent, duration_ms=10_000)
    toast = host.show_toast("Guardado")

    toast.fade_out()
    QTest.qWait(40)
    toast.fade_in()
    QTest.qWait(400)

    assert not toast.isHidden()
