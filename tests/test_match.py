import io

from workroom.workroom_core.match.engine import Mention, SourceIndex, match_mentions, periods, tokens
from workroom.workroom_core.match.numbers import parse_numbers
from workroom.workroom_core.ooxml.package import open_package
from workroom.workroom_core.ooxml.xlsx import index_workbook


def workbook(rows: list[list], title: str = "Sheet1") -> SourceIndex:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = title
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return SourceIndex(index_workbook(open_package(buf.getvalue())))


def mention(text: str, *context: str):
    return Mention("t", parse_numbers(text)[0], context or (text,))


def test_period_normalisation() -> None:
    assert periods("Q2 FY25 revenue, March 2024") == frozenset({"q2", "fy2025", "mar", "2024"})


def test_tokens_drop_stopwords_and_plurals() -> None:
    assert tokens("The Total Revenues of the regions") == ["revenue", "region"]


def test_label_support_accepts_a_unique_match() -> None:
    idx = workbook([["Item", "Q1", "Q2"], ["Revenue", 100, 120], ["Costs", 60, 70]])
    r = match_mentions([mention("Revenue in Q2 was 120", "Revenue in Q2 was 120")], idx)[0]
    assert r.decision == "accept"
    assert r.best.cell.ref == "C2"


def test_same_value_in_two_places_is_not_resolved_by_value_alone() -> None:
    idx = workbook([["Item", "Q1", "Q2"], ["Revenue", 100, 120], ["Costs", 70, 120]])
    r = match_mentions([mention("We reached 120", "We reached 120")], idx)[0]
    assert r.decision == "confirm"
    assert len(r.candidates) == 2


def test_labels_separate_equal_values() -> None:
    idx = workbook([["Item", "Q1", "Q2"], ["Revenue", 100, 120], ["Costs", 70, 120]])
    r = match_mentions([mention("Costs for Q2 totalled 120", "Costs for Q2 totalled 120")], idx)[0]
    assert r.decision == "accept" and r.best.cell.ref == "C3"


def test_a_single_matching_value_without_any_label_still_needs_confirmation() -> None:
    idx = workbook([["Item", "Q1"], ["Revenue", 100]])
    r = match_mentions([mention("The answer is 100", "The answer is 100")], idx)[0]
    assert r.decision == "confirm"


def test_period_conflict_is_not_accepted() -> None:
    idx = workbook([["Item", "Q1", "Q2"], ["Revenue", 100, 120]])
    r = match_mentions([mention("Revenue in Q1 was 120", "Revenue in Q1 was 120")], idx)[0]
    assert r.decision == "confirm"
    assert r.best.period_conflict


def test_no_candidate_is_reported_as_none() -> None:
    idx = workbook([["Item", "Q1"], ["Revenue", 100]])
    assert match_mentions([mention("Revenue was 999", "Revenue was 999")], idx)[0].decision == "none"


def test_scale_and_percent_are_handled() -> None:
    idx = workbook([["Item", "FY2024"], ["Revenue", 4_200_000.0], ["Margin", 0.123]])
    results = match_mentions([
        mention("Revenue FY2024 reached $4.2 million", "Revenue FY2024 reached $4.2 million"),
        mention("Margin FY2024 was 12.3%", "Margin FY2024 was 12.3%"),
    ], idx)
    assert [r.decision for r in results] == ["accept", "accept"]
    assert [r.best.cell.ref for r in results] == ["B2", "B3"]
