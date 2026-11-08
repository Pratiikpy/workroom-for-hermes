import pytest

from workroom.workroom_core.build.formats import FormatError, format_value, format_class
from workroom.workroom_core.match.numbers import consistent_with_source, parse_numbers


@pytest.mark.parametrize("fmt,value,text", [
    ("#,##0", 1234567.4, "1,234,567"),
    ("$#,##0.0M", 94036000000.0, "$94,036.0M"),
    ("$#,##0.0M", 1250000.0, "$1.3M"),
    ("0.0%", 0.257, "25.7%"),
    ("0%", 0.3, "30%"),
    ("#,##0.00", 3.14159, "3.14"),
    ("$#,##0", 4200.0, "$4,200"),
    ("#,##0K", 12500.0, "13K"),
    ("#,##0.0B", 2.5e9, "2.5B"),
])
def test_formats_render_as_a_reader_expects(fmt, value, text) -> None:
    assert format_value(fmt, value) == text


@pytest.mark.parametrize("fmt,value", [("$#,##0.0M", 94036000000.0), ("0.0%", 0.257), ("#,##0", 1234.0), ("#,##0.0B", 2.5e9), ("#,##0K", 12500.0)])
def test_every_rendered_number_reads_back_as_its_source_value(fmt, value) -> None:
    text = format_value(fmt, value)
    nm = parse_numbers(text)[0]
    ok, _ = consistent_with_source(nm, value)
    assert ok, (text, value)


def test_negative_numbers_use_a_minus_sign() -> None:
    assert format_value("$#,##0", -250.0) == "-$250"


@pytest.mark.parametrize("bad", ["", "abc", "#,##0 dollars", "$$#", "0.0.0"])
def test_unknown_formats_are_refused(bad) -> None:
    with pytest.raises(FormatError):
        format_value(bad, 1.0)


def test_format_class_tells_money_percent_and_plain_apart() -> None:
    assert format_class("$#,##0.0M") == "currency"
    assert format_class("0.0%") == "percent"
    assert format_class("#,##0") == "plain"
