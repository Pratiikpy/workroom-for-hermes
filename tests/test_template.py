"""Born-tied creation in the look of a deck the user already has."""

import io
import zipfile
from pathlib import Path

from workroom.tests.test_create_flow import SPEC, _svc
from workroom.workroom_core.build.template import read_theme


def themed_pptx(accent="C2410C", dk1="1F2937", dk2="475569", font="Georgia") -> bytes:
    from pptx import Presentation

    buf = io.BytesIO()
    Presentation().save(buf)
    src = zipfile.ZipFile(io.BytesIO(buf.getvalue()))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for n in src.namelist():
            data = src.read(n)
            if n == "ppt/theme/theme1.xml":
                x = data.decode("utf-8")
                import re

                x = re.sub(r'(<a:accent1>).*?(</a:accent1>)', rf'\1<a:srgbClr val="{accent}"/>\2', x, flags=re.S)
                x = re.sub(r'(<a:dk1>).*?(</a:dk1>)', rf'\1<a:srgbClr val="{dk1}"/>\2', x, flags=re.S)
                x = re.sub(r'(<a:dk2>).*?(</a:dk2>)', rf'\1<a:srgbClr val="{dk2}"/>\2', x, flags=re.S)
                x = re.sub(r'(<a:minorFont>\s*<a:latin typeface=")[^"]*', rf'\1{font}', x)
                data = x.encode("utf-8")
            z.writestr(n, data)
    return out.getvalue()


def test_colours_and_font_come_out_of_the_theme() -> None:
    tokens, notes = read_theme(themed_pptx())
    assert tokens == {"accent": "C2410C", "ink": "1F2937", "muted": "475569", "font": "Georgia"} and notes == []


def test_a_pale_template_colour_is_darkened_and_reported() -> None:
    tokens, notes = read_theme(themed_pptx(accent="FDE68A", dk2="CBD5E1"))
    from workroom.workroom_core.build.brand import MIN_CONTRAST, contrast_on_white

    assert contrast_on_white(tokens["accent"]) >= MIN_CONTRAST["accent"] and contrast_on_white(tokens["muted"]) >= MIN_CONTRAST["muted"]
    assert len(notes) == 2 and "too pale" in notes[0]


def test_a_file_that_is_not_an_office_file_gives_nothing_and_says_so() -> None:
    assert read_theme(b"not a zip") == ({}, ["the template could not be read as an Office file"])


def test_a_deck_is_made_in_the_template_look_and_stays_born_tied(tmp_path: Path) -> None:
    svc, pid, root = _svc(tmp_path)
    (root / "brand-deck.pptx").write_bytes(themed_pptx())
    spec = {**SPEC, "path": "reports/q2-branded.pptx", "template": "brand-deck.pptx"}
    staged = svc.create_from_spec(pid, spec)
    assert staged["state"] == "awaiting_approval", staged
    svc.approve_and_publish(pid, staged["release_id"], staged["digest"])
    from pptx import Presentation

    prs = Presentation(str(root / "reports" / "q2-branded.pptx"))
    colors, fonts = set(), set()
    for shp in prs.slides[0].shapes:
        if shp.has_text_frame:
            for p in shp.text_frame.paragraphs:
                for r in p.runs:
                    fonts.add(r.font.name)
                    try:
                        colors.add(str(r.font.color.rgb))
                    except Exception:  # noqa: BLE001
                        pass
    assert fonts == {"Georgia"} and "1F2937" in colors
    assert any(t["state"] in ("accepted", "confirmed") for t in svc.ties(pid) if t["deck"] == "reports/q2-branded.pptx")  # born tied: no matching questions


def test_a_template_outside_the_project_or_of_the_wrong_kind_is_refused(tmp_path: Path) -> None:
    svc, pid, root = _svc(tmp_path)
    (tmp_path / "outside.pptx").write_bytes(themed_pptx())
    (root / "notes.txt").write_text("x")
    for bad in ("../outside.pptx", "notes.txt", "missing.pptx"):
        got = svc.create_from_spec(pid, {**SPEC, "path": "x.pptx", "template": bad})
        assert got["state"] == "refused" and got["errors"][0]["code"] == "bad_template"
