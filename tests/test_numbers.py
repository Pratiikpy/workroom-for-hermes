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
