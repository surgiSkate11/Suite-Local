import pytest

from suitelocal.domain.money import format_usd


@pytest.mark.parametrize(
    ("cents", "expected"),
    [
        (0, "$ 0,00"),
        (5, "$ 0,05"),
        (115, "$ 1,15"),
        (99_999, "$ 999,99"),
        (123_456, "$ 1.234,56"),
        (100_000_000, "$ 1.000.000,00"),
        (-123_456, "-$ 1.234,56"),
        (-5, "-$ 0,05"),
    ],
)
def test_format_usd_with_comma_separator(cents, expected):
    assert format_usd(cents, ",") == expected


@pytest.mark.parametrize(
    ("cents", "expected"),
    [
        (0, "$ 0.00"),
        (115, "$ 1.15"),
        (123_456, "$ 1,234.56"),
        (100_000_000, "$ 1,000,000.00"),
        (-123_456, "-$ 1,234.56"),
    ],
)
def test_format_usd_with_dot_separator(cents, expected):
    assert format_usd(cents, ".") == expected


def test_format_usd_defaults_to_comma():
    assert format_usd(123_456) == "$ 1.234,56"


@pytest.mark.parametrize("separator", ["", ";", " ", ",,"])
def test_format_usd_rejects_unknown_separator(separator):
    with pytest.raises(ValueError, match="separador"):
        format_usd(100, separator)
