import pytest

from workroom.workroom_core.match.numbers import consistent_with_source, parse_numbers


def one(text: str):
    ms = parse_numbers(text)
    assert len(ms) == 1, ms
    return ms[0]


def test_plain_and_thousands() -> None:
    assert one("Total 1,234").value == 1234.0
    assert one("Total 1,234.56").decimals == 2


def test_percent_and_bps() -> None:
    assert one("grew 12%").unit == "percent"
    assert one("down 25 bps").unit == "bps"
    assert one("up 1.5pp").unit == "pp"


def test_currency_and_scale_words() -> None:
    m = one("revenue of $4.2 billion")
    assert m.unit == "currency:USD" and m.scale == 1e9 and m.scaled == 4.2e9 and m.decimals == 1
    assert one("€350k").scaled == 350000.0


def test_negatives() -> None:
    assert one("loss of (1,200)").value == -1200.0
    assert one("change of -3.5%").value == -3.5


def test_labels_glued_to_letters_are_not_numbers() -> None:
    assert parse_numbers("Q2 FY25 A1") == []
    assert [m.value for m in parse_numbers("Q2 revenue 40")] == [40.0]


def test_several_numbers() -> None:
    assert [m.value for m in parse_numbers("12% of 3,400 in 2024")] == [12.0, 3400.0, 2024.0]


@pytest.mark.parametrize(
    "text,source,expected",
    [
        ("12.3%", 0.123, True),
        ("12%", 0.123, True),          # displayed rounding
        ("13%", 0.123, False),
        ("1,234", 1234.0, True),
        ("1.2 million", 1_200_000.0, True),
        ("1.3 million", 1_200_000.0, False),
        ("4.2 billion", 4_150_000_000.0, True),
        ("$4.2m", 4_200_000.0, True),
        ("25", 25.0, True),
        ("25", 26.0, False),
    ],
)
def test_consistency_allows_scale_percent_and_rounding(text: str, source: float, expected: bool) -> None:
    assert consistent_with_source(one(text), source)[0] is expected


@pytest.mark.parametrize(
    "old,new,transform,expected",
    [
        ("Total 1,234", 1300.0, "exact", "1,300"),
        ("grew 12%", 0.153, "fraction_to_percent", "15%"),
        ("grew 12.3%", 0.1537, "fraction_to_percent", "15.4%"),
        ("revenue of $4.2 billion", 5_150_000_000.0, "scaled", "$5.2 billion"),
        ("loss of (1,200)", -1500.0, "exact", "(1,500)"),
        ("change of -3.5%", -0.041, "fraction_to_percent", "-4.1%"),
        ("only 25", 31.0, "exact", "31"),
        ("share 7%", 0.0, "fraction_to_percent", "0%"),
    ],
)
def test_format_like_keeps_the_original_style(old: str, new: float, transform: str, expected: str) -> None:
    from workroom.workroom_core.match.numbers import format_like

    m = parse_numbers(old)[0]
    assert format_like(m, new, transform) == expected


def test_mention_offsets_point_at_the_first_character() -> None:
    text = "margin was 25% and revenue $4.2 billion"
    for m in parse_numbers(text):
        assert text[m.start : m.end] == m.raw


def test_a_lone_bracket_is_not_part_of_the_number() -> None:
    assert [m.raw for m in parse_numbers("High Value (>$10K)")] == ["$10K"]
    assert [m.raw for m in parse_numbers("(up 12.5%) and (3.1")] == ["12.5%", "3.1"]
    assert [(m.raw, m.negative) for m in parse_numbers("($4.5m) and (7)")] == [("($4.5m)", True), ("(7)", True)]


def test_times_dates_and_versions_are_not_quantities() -> None:
    assert parse_numbers("The Wait (1:50 to 2:10)") == []
    assert parse_numbers("version 2.1.3 shipped on 12/05/2026") == []
    assert [m.raw for m in parse_numbers("SCENE 5 at 1:50")] == ["5"]


def test_a_dash_after_a_figure_is_a_range_not_a_minus() -> None:
    got = [(m.raw, m.value, m.negative) for m in parse_numbers("growth of 10-15% a year")]
    assert got == [("10", 10.0, False), ("15%", 15.0, False)]
    assert [(m.raw, m.negative) for m in parse_numbers("fell to -3.1% from 2%")] == [("-3.1%", True), ("2%", False)]


def test_the_day_of_a_date_and_an_ordinal_are_not_quantities() -> None:
    assert parse_numbers("Prepared: January 30, 2026") == [m for m in parse_numbers("Prepared: January 30, 2026") if m.raw == "2026"]
    assert [m.raw for m in parse_numbers("on 30 January we sold 30 units")] == ["30"]
    assert parse_numbers("our 30th year and the 3rd quarter") == []
    assert [m.raw for m in parse_numbers("Mar 2026 sales were 31 units")] == ["2026", "31"]
