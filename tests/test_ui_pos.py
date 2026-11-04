import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication

from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import ProductRepository, SaleRepository
from suitelocal.ui.pos import PosWidget


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def pos(qapp, tmp_path):
    database = Database(tmp_path / "pos.db")
    database.initialize()
    products = ProductRepository(database)
    products.add("A-1", "Arroz", 250, 10)
    products.add("B-2", "Frijol", 300, 5)
    widget = PosWidget(products, SaleRepository(database))
    yield widget
    widget.deleteLater()


def shortcuts_for(widget: PosWidget, sequence: str) -> list[QShortcut]:
    expected = QKeySequence(sequence)
    return [shortcut for shortcut in widget.findChildren(QShortcut) if expected in shortcut.keys()]


def test_crossing_the_breakpoint_does_not_duplicate_shortcuts(pos):
    for width in (1200, 900, 1200, 900):
        pos._relayout(width)

    assert len(shortcuts_for(pos, "Delete")) == 1
    assert len(shortcuts_for(pos, "F2")) == 1


def test_crossing_the_breakpoint_keeps_the_selected_product(pos):
    pos.product_list.setCurrentRow(1)

    pos._relayout(1200)

    assert pos.product_list.currentRow() == 1


def test_confirm_shortcut_accepts_main_keyboard_enter(pos):
    assert len(shortcuts_for(pos, "Ctrl+Return")) == 1
    assert len(shortcuts_for(pos, "Ctrl+Enter")) == 1
