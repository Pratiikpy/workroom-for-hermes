"""Period labels: what is read, what is refused, how two periods relate, and how a shifted period is written in the style it was found in."""
import pytest

from workroom.workroom_core.meaning.periods import Period, parse_period, period_label

Q = lambda y, q: Period("q", y * 4 + q - 1)  # noqa: E731


@pytest.mark.parametrize("label,expected", [
    ("Q3 2026", Q(2026, 3)), ("q3 2026", Q(2026, 3)), ("Q3'26", Q(2026, 3)), ("Q3-26", Q(2026, 3)), ("Q3 FY26", Q(2026, 3)), ("3Q26", Q(2026, 3)),
    ("3Q 2026", Q(2026, 3)), ("Third quarter 2026", Q(2026, 3)), ("third quarter of fiscal 2026", Q(2026, 3)), ("Q4 FY2025", Q(2025, 4)),
    ("H1 2026", Period("h", 2026 * 2)), ("Second half of 2025", Period("h", 2025 * 2 + 1)),
    ("FY2026", Period("y", 2026)), ("FY26", Period("y", 2026)), ("Fiscal 2026", Period("y", 2026)), ("Fiscal year 2026", Period("y", 2026)), ("2026", Period("y", 2026)),
    ("Jan 2026", Period("m", 2026 * 12)), ("January 2026", Period("m", 2026 * 12)), ("Dec-25", Period("m", 2025 * 12 + 11)), ("2026-03", Period("m", 2026 * 12 + 2)),
    ("Three months ended September 27, 2025", Q(2025, 3)), ("3 months ended 2025-12-31", Q(2025, 4)), ("Twelve months ended Dec 31, 2025", Period("y", 2025)),
    ("9 months ended 2025-09-27", Period("ytd", 2025 * 12 + 8, 9)),
])
def test_labels_that_name_one_period(label: str, expected: Period) -> None:
    assert parse_period(label) == expected


@pytest.mark.parametrize("label", ["Revenue", "", "Q5 2026", "Q3", "Q3 2026 vs Q2 2026", "2026 2025", "12345", "Total", "Net income (loss)", "x" * 80, "1999999", "Q3 2026 to Q4 2026", "Marketing 2026", "Mayor 25", "Decision 2025"])
def test_labels_that_are_not_a_single_period_are_not_read(label: str) -> None:
    assert parse_period(label) is None


def test_previous_and_year_earlier_are_plain_subtraction() -> None:
    q = Q(2026, 1)
    assert q.previous == Q(2025, 4) and q.year_ago == Q(2025, 1)
    assert Period("m", 2026 * 12).year_ago == Period("m", 2025 * 12)
    assert Period("y", 2026).previous == Period("y", 2025) and Period("ytd", 5, 9).previous is None


@pytest.mark.parametrize("template,shift,expected", [
    ("Q3 2026", 1, "Q4 2026"), ("Q4 2026", 1, "Q1 2027"), ("Q1 2026", -1, "Q4 2025"), ("Q3'26", 1, "Q4'26"), ("3Q26", 2, "1Q27"),
    ("Third quarter 2026", 1, "Fourth quarter 2026"), ("third quarter of fiscal 2026", 2, "first quarter of fiscal 2027"), ("Q3 FY26", 3, "Q2 FY27"),
    ("H1 2026", 1, "H2 2026"), ("H2 2026", 1, "H1 2027"), ("Second half of 2025", 1, "First half of 2026"),
    ("FY2026", 1, "FY2027"), ("FY26", 1, "FY27"), ("Fiscal 2026", 1, "Fiscal 2027"), ("2026", 1, "2027"),
    ("Jan 2026", 1, "Feb 2026"), ("Dec 2025", 1, "Jan 2026"), ("January 2026", 1, "February 2026"), ("Dec-25", 1, "Jan-26"),
])
def test_a_shifted_period_keeps_the_style_it_was_written_in(template: str, shift: int, expected: str) -> None:
    p = parse_period(template)
    assert p is not None
    out = period_label(p.shifted(shift), template)
    assert out == expected and parse_period(out) == p.shifted(shift)


def test_a_period_cannot_be_written_in_the_style_of_a_different_kind() -> None:
    with pytest.raises(ValueError):
        period_label(Period("y", 2027), "Q3 2026")
