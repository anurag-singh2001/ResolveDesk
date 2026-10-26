"""One rounding rule (half up, from integer basis points) for every percentage we print."""

import pytest

from app.modules.growth.signals import format_pct, template_diagnosis


@pytest.mark.parametrize(
    ("bp", "text"),
    [(7645, "76.5"), (7644, "76.4"), (4085, "40.9"), (4084, "40.8"), (0, "0.0"), (5, "0.1")],
)
def test_format_pct_rounds_half_up_from_basis_points(bp, text):
    assert format_pct(bp) == text


def test_diagnosis_uses_the_same_figures_as_the_headline_rule():
    evidence = {
        "baseline": {"repeat_bp": 7645, "orders": 200},
        "recent": {"repeat_bp": 4085, "orders": 120},
        "drop_bp": 3560,
        "tickets_baseline": {},
        "tickets_recent": {},
    }
    text = template_diagnosis(evidence).findings[0]
    assert "76.5%" in text and "40.9%" in text and "35.6 points" in text
