import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QGuiApplication  # noqa: E402

from suitelocal.ui import barcode  # noqa: E402
from suitelocal.ui.barcode import code128_symbols, code128_widths, render_code128  # noqa: E402

ACCESS_KEY = "0711202601179000000100110010010000001231234567810"


@pytest.fixture(scope="module", autouse=True)
def _app() -> QGuiApplication:
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _decode(widths: tuple[int, ...]) -> tuple[list[int], str]:
    """Independent reader: widths -> symbol values, then the text, verifying checksum and stop."""
    lookup = {pattern: value for value, pattern in enumerate(barcode._PATTERNS)}
    text_widths = "".join(str(width) for width in widths)
    values = [lookup[text_widths[index : index + 6]] for index in range(0, len(text_widths) - 7, 6)]
    assert text_widths[-7:] == barcode._PATTERNS[106]
    *body, checksum = values
    assert checksum == (body[0] + sum(i * v for i, v in enumerate(body[1:], 1))) % 103
    code_set = {104: "B", 105: "C"}[body[0]]
    text = ""
    for value in body[1:]:
        if value == 99:
            code_set = "C"
        elif value == 100:
            code_set = "B"
        elif code_set == "C":
            text += f"{value:02d}"
        else:
            text += chr(value + 32)
    return values, text


def test_every_symbol_is_six_elements_adding_eleven_modules() -> None:
    assert len(barcode._PATTERNS) == 107
    assert len(set(barcode._PATTERNS)) == 107
    for pattern in barcode._PATTERNS[:106]:
        assert len(pattern) == 6
        assert sum(int(width) for width in pattern) == 11
    # The stop symbol has seven elements and thirteen modules (it ends with the final bar).
    assert sum(int(width) for width in barcode._PATTERNS[106]) == 13


def test_known_vector_pjj123c_in_code_set_b() -> None:
    # The classic worked example: start B, P J J 1 2 3 C, check symbol 55 and stop.
    assert code128_symbols("PJJ123C") == (104, 48, 42, 42, 17, 18, 19, 35, 55, 106)
    assert "".join(map(str, code128_widths("PJJ123C"))) == (
        "211214313121112133112133123221223211221132131321311321" + "2331112"
    )


def test_digit_pairs_use_code_set_c() -> None:
    # Start C, 12 -> 12, 34 -> 34, 56 -> 56, check (105 + 12 + 68 + 168) % 103 = 44.
    assert code128_symbols("123456") == (105, 12, 34, 56, 44, 106)


def test_odd_digit_run_keeps_its_first_digit_in_set_b() -> None:
    assert code128_symbols("12345")[:5] == (104, 17, 99, 23, 45)


def test_short_digit_runs_stay_in_set_b_and_letters_switch_back() -> None:
    assert code128_symbols("A12")[:4] == (104, 33, 17, 18)
    values = code128_symbols("AB123456C")
    assert values[:3] == (104, 33, 34)
    assert 99 in values and 100 in values


def test_access_key_round_trips_through_an_independent_reader() -> None:
    assert len(ACCESS_KEY) == 49
    widths = code128_widths(ACCESS_KEY)
    values, text = _decode(widths)
    assert text == ACCESS_KEY
    # Start B + one digit + switch to C + 24 pairs + check (the stop is checked in _decode).
    assert len(values) == 1 + 1 + 1 + 24 + 1
    assert values[0] == 104 and values[2] == 99
    assert len(widths) == 28 * 6 + 7


@pytest.mark.parametrize("text", ["", "ñ", "tab\t"])
def test_rejects_empty_and_unprintable_text(text: str) -> None:
    with pytest.raises(ValueError):
        code128_symbols(text)


def test_render_draws_bars_at_the_requested_module_width_and_height() -> None:
    image = render_code128("PJJ123C", 2, 40)
    widths = code128_widths("PJJ123C")
    assert image.height() == 40
    assert image.width() == (sum(widths) + 2 * barcode.QUIET_MODULES) * 2
    white, black = 0xFFFFFFFF, 0xFF000000
    assert image.pixel(0, 0) == white
    start = barcode.QUIET_MODULES * 2
    # Start B is 2-1-1-2-1-4: a 2-module bar, a 1-module space, a 1-module bar...
    assert [image.pixel(start + offset, 20) for offset in (0, 4, 6, 8, 12, 14)] == [
        black,
        white,
        black,
        white,
        black,
        white,
    ]
    assert image.pixel(start, 0) == black and image.pixel(start, 39) == black
    assert image.pixel(image.width() - 1, 20) == white


def test_render_rejects_a_non_positive_size() -> None:
    with pytest.raises(ValueError):
        render_code128("123456", 0, 10)
    with pytest.raises(ValueError):
        render_code128("123456", 1, 0)
