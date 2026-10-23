import pytest

from app.core.money import format_inr, percent_of, require_paise


@pytest.mark.parametrize(
    "paise,text",
    [
        (0, "₹0.00"),
        (5, "₹0.05"),
        (34900, "₹349.00"),
        (123456, "₹1,234.56"),
        (1234567800, "₹1,23,45,678.00"),
    ],
)
def test_format_inr_uses_indian_grouping(paise, text):
    assert format_inr(paise) == text


@pytest.mark.parametrize(
    "amount,percent,expected",
    [(69800, 50, 34900), (69801, 50, 34900), (999, 33, 329), (100, 0, 0), (100, 100, 100)],
)
def test_percent_of_floors_never_rounds_up(amount, percent, expected):
    assert percent_of(amount, percent) == expected


@pytest.mark.parametrize("bad", [349.0, "34900", True, None, -1])
def test_require_paise_rejects_non_integer_or_negative(bad):
    with pytest.raises((TypeError, ValueError)):
        require_paise(bad)


@pytest.mark.parametrize("percent", [50.0, -1, 101, True])
def test_percent_must_be_integer_0_to_100(percent):
    with pytest.raises(ValueError):
        percent_of(100, percent)
