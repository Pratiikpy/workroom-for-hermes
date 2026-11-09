from workroom.workroom_core.match.engine import Mention, SourceIndex, match_mentions
from workroom.workroom_core.match.numbers import parse_numbers
from workroom.workroom_core.ooxml.xlsx import SourceCell


def cell(ref: str, value: float, label: str, period: str = "Q2") -> SourceCell:
    return SourceCell("S", ref, 2, 2, value, False, False, (label,), (period,), False, "b.xlsx")


def decide(text: str, shown: str, cells: list[SourceCell], heads: tuple[str, ...] = ()):
    pos = text.rfind(shown)
    nm = parse_numbers(shown)[0]
    return match_mentions([Mention("t", nm, (text,) + heads, (pos, pos + len(shown)))], SourceIndex(cells))[0]


def test_a_bare_short_number_is_never_accepted_by_scaling_a_big_cell() -> None:
    r = decide("Other income was 3 in the quarter", "3", [cell("B2", 3280.0, "Other income")])
    assert r.decision == "confirm"


def test_a_percentage_never_matches_a_scaled_money_cell() -> None:
    r = decide("Operating income grew 7.3% in the quarter", "7.3%", [cell("B2", 7286.0, "Operating income")])
    assert r.decision == "none"


def test_a_long_number_that_fits_exactly_one_cell_is_accepted_when_the_text_names_the_row() -> None:
    r = decide("Q2 net sales 94,036", "94,036", [cell("B2", 94036.0, "Revenue from contract with customer net sales")])
    assert r.decision == "accept"


def test_a_long_unique_number_is_accepted_even_when_the_text_names_no_period() -> None:
    # measured on 10 real earnings releases: demanding a period in the sentence cut 265 auto links to 40 and added no measured precision
    assert decide("Net sales 94,036", "94,036", [cell("B2", 94036.0, "Net sales")]).decision == "accept"
    c = SourceCell("S", "B2", 2, 2, 94036.0, False, False, ("Net sales",), (), False, "b.xlsx")
    assert decide("Net sales 94,036", "94,036", [c]).decision == "accept"


def test_a_long_number_that_fits_one_cell_but_whose_text_names_nothing_still_goes_to_a_person() -> None:
    r = decide("Reference 94,036", "94,036", [cell("B2", 94036.0, "Gross profit")])
    assert r.decision == "confirm"


def test_only_the_words_near_a_number_describe_it_in_a_long_paragraph() -> None:
    filler = "The quarter included many one-time items across regions and product lines, as described in the notes. " * 4
    far = "Accounts receivable fell in the period. " + filler + "Another figure was 6.15 for the quarter."
    near = "Accounts receivable fell in the period to 6.15"
    cells = [cell("B2", 6.15, "Accounts receivable")]
    assert decide(far, "6.15", cells).best.label_score == 0.0
    assert decide(near, "6.15", cells).best.label_score > 0.0


def test_numbers_alone_in_a_label_do_not_make_a_link() -> None:
    """A row called "Item 17" is not evidence for a sentence that happens to contain 17; some word must agree."""
    from workroom.workroom_core.match.engine import Mention, SourceIndex, match_mentions
    from workroom.workroom_core.match.numbers import parse_numbers
    from workroom.workroom_core.ooxml.xlsx import SourceCell

    cells = [SourceCell("Data", f"B{i}", i, 2, 1000.0 + i, False, False, (f"Item {i}",), ("Value",), False) for i in range(2, 30)]
    index = SourceIndex(cells)
    mention = Mention("m", parse_numbers("Between 17 offices and 2,017 staff")[1], ("Between 17 offices and 2,017 staff",))
    res = match_mentions([mention], index)[0]
    assert res.decision != "accept"


def test_a_figure_a_thousand_times_smaller_than_its_cell_is_not_linked_unless_the_unit_is_named() -> None:
    plain = decide("Q2 revenue was 4,100", "4,100", [cell("B2", 4_100_000.0, "Revenue")])
    assert plain.decision == "confirm"
    assert "1,000 times" in plain.reason
    assert decide("Q2 revenue was 4,100", "4,100", [cell("B2", 4_100_000.0, "Revenue")], heads=("(in thousands)",)).decision == "accept"
    assert decide("Q2 revenue was 4,100", "4,100", [cell("B2", 4_100_000.0, "Revenue ($000)")]).decision == "accept"


def test_a_named_unit_must_be_the_unit_that_explains_the_difference() -> None:
    wrong_unit = decide("Q2 revenue was 4,100", "4,100", [cell("B2", 4_100_000.0, "Revenue")], heads=("(in millions)",))
    assert wrong_unit.decision == "confirm"
    assert decide("Q2 revenue was 4.12", "4.12", [cell("B2", 4_120_000.0, "Revenue ($M)")]).decision == "accept"
    assert decide("Q2 revenue was 4.12", "4.12", [cell("B2", 4_120_000.0, "Revenue")]).decision == "confirm"


def test_a_digit_run_inside_a_longer_number_is_not_the_thousands_marker() -> None:
    r = decide("Q2 revenue was 4,100", "4,100", [cell("B2", 4_100_000.0, "Revenue 2,000")])
    assert r.decision == "confirm"
