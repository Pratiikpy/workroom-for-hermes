"""Repeated update cycles on real public data, scored by an oracle that shares no code with Workroom.

    python cycles.py <fred csv folder> [--cycles N] [--mode owner|hands-off] [out.json]

Real series (FRED: nominal and real GDP, private investment, unemployment, CPI, payrolls) fill a workbook one period at a time, as
they would arrive for a real owner. A deck and a Word report, written here in layouts Workroom did not author, say things about
those series: a figure, a calculated change, "up from", "rose to", "record". Each cycle the next period arrives, Workroom rolls the
documents forward, and the sentences it produced are compared with sentences rendered straight from the data by this script.

Every difference must be one Workroom told the owner about; a difference it did not report is a silent error and is counted as such.
In `owner` mode the owner then fixes what was reported (rewrites the sentence, as a person would) so the next cycle starts honest;
in `hands-off` mode nobody does, and afterwards every release is restored in turn and compared byte for byte.
"""

import argparse
import csv
import json
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from docx import Document  # noqa: E402
from pptx import Presentation  # noqa: E402
from pptx.util import Inches  # noqa: E402
from xlsxwriter import Workbook  # noqa: E402

from workroom.workroom_core.service import NeedsAcknowledgement, Service, ServiceError  # noqa: E402

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def load(folder: Path, sid: str) -> list[tuple[str, float]]:
    rows = []
    with open(folder / f"{sid}.csv", newline="", encoding="utf-8") as fh:
        for r in csv.reader(fh):
            if r and r[0][:2] == "20" and len(r) > 1 and r[1] not in (".", ""):
                rows.append((r[0], float(r[1])))
    return rows


def nums(text: str) -> list[str]:
    return re.findall(r"\d[\d,]*\.?\d*", text)


# --------------------------------------------------------------------------------------------- quarterly deck

QUARTERLY = [("Nominal GDP", "GDP", lambda v: f"${v / 1000:.1f} trillion"), ("Real GDP", "GDPC1", lambda v: f"${v / 1000:.1f} trillion"),
             ("Private investment", "GPDI", lambda v: f"${v / 1000:.2f} trillion")]


class QuarterlyDeck:
    name = "quarterly deck (periods down the rows, PowerPoint)"
    file = "briefing.pptx"

    def __init__(self, folder: Path, first: str, last: str) -> None:
        self.data = {sid: dict(((self.q(d), v) for d, v in load(folder, sid) if d[5:7] in ("01", "04", "07", "10"))) for _, sid, _ in QUARTERLY}
        self.labels = sorted({k for s in self.data.values() for k in s}, key=lambda q: (int(q[3:]), int(q[1])))
        self.first = self.labels.index(first)
        self.last = self.labels.index(last)

    @staticmethod
    def q(date: str) -> str:
        return f"Q{(int(date[5:7]) - 1) // 3 + 1} {date[:4]}"

    def periods(self) -> int:
        return self.last - self.first

    def value(self, sid: str, n: int) -> float:
        return self.data[sid][self.labels[n]]

    def workbook(self, root: Path, n: int) -> None:
        upto = self.first + n
        with Workbook(str(root / "economy.xlsx")) as wb:
            ws = wb.add_worksheet("Data")
            ws.write_row(0, 0, ["Quarter"] + [f"{nm} ($ billions)" for nm, _, _ in QUARTERLY])
            for r, i in enumerate(range(max(0, upto - 8), upto + 1), 1):
                ws.write(r, 0, self.labels[i])
                for c, (_, sid, _) in enumerate(QUARTERLY, 1):
                    ws.write_number(r, c, self.value(sid, i))
            wb.add_worksheet("Sources").write(0, 0, "Source: FRED, Federal Reserve Bank of St. Louis (public series GDP, GDPC1, GPDI)")

    def sentences(self, n: int) -> dict[str, str | None]:
        i = self.first + n
        out: dict[str, str | None] = {}
        for nm, sid, fmt in QUARTERLY:
            cur, prev = self.value(sid, i), self.value(sid, i - 1)
            pct = abs(cur / prev - 1) * 100
            P, Pp = self.labels[i], self.labels[i - 1]
            out[f"A {nm}"] = f"{nm} reached {fmt(cur)} in {P}, {'up' if cur > prev else 'down'} {pct:.1f}% from {fmt(prev)} in {Pp}."
            out[f"B {nm}"] = f"{nm} {'held steady at' if fmt(cur) == fmt(prev) else 'rose to' if cur > prev else 'fell to'} {fmt(cur)} in {P}."
            history = [self.value(sid, j) for j in range(max(0, i - 8), i)]
            out[f"R {nm}"] = f"Record {nm.lower()} of {fmt(cur)} in {P}." if cur >= max(history) else None
            out[f"N {nm}"] = f"Say: {nm.lower()} was {fmt(cur)} in {P}."
        return out

    def b_wording_true(self, key: str, text: str, n: int) -> bool | None:
        """Is the direction word in a "rose to / fell to / held steady at" sentence true of the data? None when the key is not such a sentence."""
        if not key.startswith("B "):
            return None
        nm = key[2:]
        sid = next(sid for name, sid, _ in QUARTERLY if name == nm)
        fmt = next(f for name, _, f in QUARTERLY if name == nm)
        i = self.first + n
        cur, prev = self.value(sid, i), self.value(sid, i - 1)
        return ("rose to" in text and cur > prev) or ("fell to" in text and cur < prev) or ("held steady at" in text and fmt(cur) == fmt(prev))

    def build(self, root: Path) -> None:
        prs = Presentation()
        first = prs.slides.add_slide(prs.slide_layouts[0])
        first.shapes.title.text = f"{self.labels[self.first]} Macro Briefing"
        want = self.sentences(0)
        for nm, _, _ in QUARTERLY:
            slide = prs.slides.add_slide(prs.slide_layouts[5])
            slide.shapes.title.text = nm
            for j, key in enumerate(("A", "B", "R")):
                text = want[f"{key} {nm}"]
                if text:
                    box = slide.shapes.add_textbox(Inches(0.6), Inches(1.5 + 0.9 * j), Inches(8.8), Inches(0.8))
                    box.name = f"{key} {nm}"
                    box.text_frame.text = text
                    box.text_frame.word_wrap = True
            slide.notes_slide.notes_text_frame.text = want[f"N {nm}"]
        table_slide = prs.slides.add_slide(prs.slide_layouts[5])
        table_slide.shapes.title.text = "At a glance"
        i = self.first
        shape = table_slide.shapes.add_table(len(QUARTERLY) + 1, 4, Inches(0.6), Inches(1.6), Inches(8.8), Inches(2.4))
        shape.name = "Table"
        t = shape.table
        for c, h in enumerate(["Indicator", self.labels[i], self.labels[i - 1], "Change"]):
            t.cell(0, c).text = h
        for r, (nm, sid, fmt) in enumerate(QUARTERLY, 1):
            cur, prev = self.value(sid, i), self.value(sid, i - 1)
            t.cell(r, 0).text = nm
            t.cell(r, 1).text = fmt(cur)
            t.cell(r, 2).text = fmt(prev)
            t.cell(r, 3).text = f"{(cur / prev - 1) * 100:+.1f}%"
        prs.save(str(root / self.file))

    def read(self, root: Path) -> dict[str, str | None]:
        prs = Presentation(root / self.file)
        out: dict[str, str | None] = {}
        for slide in prs.slides:
            title = slide.shapes.title.text if slide.shapes.title is not None else ""
            for sh in slide.shapes:
                if sh.has_text_frame and sh.name[:2] in ("A ", "B ", "R "):
                    out[sh.name] = sh.text_frame.text
            if title in dict((nm, 1) for nm, _, _ in QUARTERLY) and slide.has_notes_slide:
                out[f"N {title}"] = slide.notes_slide.notes_text_frame.text
            for sh in slide.shapes:
                if sh.has_table:
                    tb = sh.table
                    for r in range(len(tb.rows)):
                        out[f"T{r}"] = " | ".join(tb.cell(r, c).text for c in range(len(tb.columns)))
        for key in [f"{k} {nm}" for nm, _, _ in QUARTERLY for k in "ABR"]:
            out.setdefault(key, None)
        out["Title"] = prs.slides[0].shapes.title.text
        return out

    def table_expected(self, n: int) -> dict[str, str]:
        i = self.first + n
        out = {"Title": f"{self.labels[i]} Macro Briefing", "T0": " | ".join(["Indicator", self.labels[i], self.labels[i - 1], "Change"])}
        for r, (nm, sid, fmt) in enumerate(QUARTERLY, 1):
            cur, prev = self.value(sid, i), self.value(sid, i - 1)
            out[f"T{r}"] = " | ".join([nm, fmt(cur), fmt(prev), f"{(cur / prev - 1) * 100:+.1f}%"])
        return out

    def rewrite(self, root: Path, expected: dict[str, str | None]) -> int:
        """The owner reads what Workroom reported and fixes those sentences in PowerPoint. Returns how many sentences were fixed by hand."""
        prs = Presentation(root / self.file)
        fixed = 0
        for slide in prs.slides:
            title = slide.shapes.title.text if slide.shapes.title is not None else ""
            for sh in list(slide.shapes):
                if sh.has_text_frame and sh.name[:2] in ("A ", "B ", "R "):
                    want = expected.get(sh.name)
                    if want is None:
                        sh._element.getparent().remove(sh._element)
                        fixed += 1
                    elif sh.text_frame.text != want:
                        _set_text(sh.text_frame.paragraphs[0], want)
                        fixed += 1
                if sh.has_table:
                    for r in range(len(sh.table.rows)):
                        for c in range(len(sh.table.columns)):
                            cell = sh.table.cell(r, c)
                            want_row = expected.get(f"T{r}", "").split(" | ")
                            if c < len(want_row) and cell.text != want_row[c]:
                                _set_text(cell.text_frame.paragraphs[0], want_row[c])
                                fixed += 1
            if title == "Quarterly" or not slide.has_notes_slide:
                continue
            want = expected.get(f"N {title}")
            if want and slide.notes_slide.notes_text_frame.text != want:
                slide.notes_slide.notes_text_frame.text = want
                fixed += 1
        first = prs.slides[0].shapes.title
        if first.text != expected["Title"]:
            _set_text(first.text_frame.paragraphs[0], expected["Title"])
            fixed += 1
        prs.save(str(root / self.file))
        return fixed


def _set_text(paragraph, text: str) -> None:
    runs = paragraph.runs
    if not runs:
        paragraph.text = text
        return
    runs[0].text = text
    for r in runs[1:]:
        r._r.getparent().remove(r._r)


# --------------------------------------------------------------------------------------------- monthly report

MONTHLY = [("Unemployment rate", "UNRATE"), ("CPI index", "CPIAUCSL"), ("Nonfarm payrolls", "PAYEMS")]


class MonthlyReport:
    name = "monthly report (periods across the columns, Word)"
    file = "labour_and_prices.docx"

    def __init__(self, folder: Path, first: str, last: str) -> None:
        self.data = {sid: {self.m(d): v for d, v in load(folder, sid)} for _, sid in MONTHLY}
        self.labels = sorted(self.data["UNRATE"], key=lambda m: (int(m[4:]), MONTHS.index(m[:3])))
        self.first = self.labels.index(first)
        self.last = self.labels.index(last)

    @staticmethod
    def m(date: str) -> str:
        return f"{MONTHS[int(date[5:7]) - 1]} {date[:4]}"

    def periods(self) -> int:
        return self.last - self.first

    def value(self, sid: str, n: int) -> float:
        return self.data[sid][self.labels[n]]

    def workbook(self, root: Path, n: int) -> None:
        upto = self.first + n
        with Workbook(str(root / "labour.xlsx")) as wb:
            ws = wb.add_worksheet("Monthly")
            span = range(max(0, upto - 11), upto + 1)
            ws.write_row(0, 0, ["Indicator"] + [self.labels[i] for i in span])
            for r, (nm, sid) in enumerate(MONTHLY, 1):
                ws.write(r, 0, nm)
                for c, i in enumerate(span, 1):
                    ws.write_number(r, c, self.value(sid, i))

    def fmt(self, sid: str, v: float) -> str:
        return {"UNRATE": f"{v:.1f}%", "CPIAUCSL": f"{v:.1f}", "PAYEMS": f"{v / 1000:.1f} million"}[sid]

    def delta(self, sid: str, cur: float, prev: float) -> str:
        d = cur - prev
        if sid == "UNRATE":
            return f"{abs(d):.1f} percentage points"
        if sid == "CPIAUCSL":
            return f"{abs(cur / prev - 1) * 100:.1f}%"
        return f"{abs(d):,.0f} thousand"

    def sentences(self, n: int) -> dict[str, str | None]:
        i = self.first + n
        out: dict[str, str | None] = {}
        for nm, sid in MONTHLY:
            cur, prev = self.value(sid, i), self.value(sid, i - 1)
            P, Pp = self.labels[i], self.labels[i - 1]
            out[f"A {nm}"] = f"The {nm.lower()} was {self.fmt(sid, cur)} in {P}, {'up' if cur > prev else 'down'} {self.delta(sid, cur, prev)} from {self.fmt(sid, prev)} in {Pp}."
            out[f"B {nm}"] = f"The {nm.lower()} {'held steady at' if self.fmt(sid, cur) == self.fmt(sid, prev) else 'rose to' if cur > prev else 'fell to'} {self.fmt(sid, cur)} in {P}."
        return out

    def b_wording_true(self, key: str, text: str, n: int) -> bool | None:
        if not key.startswith("B "):
            return None
        nm = key[2:]
        sid = next(sid for name, sid in MONTHLY if name == nm)
        i = self.first + n
        cur, prev = self.value(sid, i), self.value(sid, i - 1)
        return ("rose to" in text and cur > prev) or ("fell to" in text and cur < prev) or ("held steady at" in text and self.fmt(sid, cur) == self.fmt(sid, prev))

    def build(self, root: Path) -> None:
        doc = Document()
        doc.add_heading(f"Labour and prices, {self.labels[self.first]}", 0)
        want = self.sentences(0)
        for nm, _ in MONTHLY:
            doc.add_heading(nm, 1)
            doc.add_paragraph(want[f"A {nm}"])
            doc.add_paragraph(want[f"B {nm}"])
        doc.save(str(root / self.file))

    def read(self, root: Path) -> dict[str, str | None]:
        doc = Document(root / self.file)
        paras = [p.text for p in doc.paragraphs]
        out: dict[str, str | None] = {"Title": paras[0]}
        for nm, _ in MONTHLY:
            k = paras.index(nm)
            out[f"A {nm}"], out[f"B {nm}"] = paras[k + 1], paras[k + 2]
        return out

    def table_expected(self, n: int) -> dict[str, str]:
        return {"Title": f"Labour and prices, {self.labels[self.first + n]}"}

    def rewrite(self, root: Path, expected: dict[str, str | None]) -> int:
        doc = Document(root / self.file)
        fixed = 0
        paras = doc.paragraphs
        for p in paras:
            for key, want in expected.items():
                pass
        names = [p.text for p in paras]
        for nm, _ in MONTHLY:
            k = names.index(nm)
            for off, key in ((1, f"A {nm}"), (2, f"B {nm}")):
                if paras[k + off].text != expected[key]:
                    _set_text(paras[k + off], expected[key])
                    fixed += 1
        if paras[0].text != expected["Title"]:
            _set_text(paras[0], expected["Title"])
            fixed += 1
        doc.save(str(root / self.file))
        return fixed


# --------------------------------------------------------------------------------------------- the trial


def settle(svc, pid: str) -> dict:
    """What the owner does once a project is read: confirm the proposed sources, accept calculations that exactly one reading reproduces.
    Returns how many decisions that took and how many were left because several readings fit."""
    confirmed = 0
    for t in svc.ties(pid):
        if t["state"] == "confirm":
            svc._open(pid)[0].confirm(t["id"])
            confirmed += 1
    svc._close_opened()
    accepted = left = 0
    for c in svc.calculations(pid)["candidates"]:
        if len(c["options"]) == 1:
            svc.accept_calculation(pid, c["id"], 0)
            accepted += 1
        else:
            left += 1
    return {"sources_confirmed": confirmed, "calculations_accepted": accepted, "calculations_left_ambiguous": left}


def run(kind, folder: Path, cycles: int, mode: str) -> dict:
    root = Path(tempfile.mkdtemp(prefix="cycles_"))
    state = Path(tempfile.mkdtemp(prefix="cycles_state_"))
    kind.workbook(root, 0)
    kind.build(root)
    svc = Service(state)
    pid = svc.add_project(str(root))["project"]
    found = svc.discover(pid)
    setup = settle(svc, pid)
    saved = {0: (root / kind.file).read_bytes()}
    report: dict = {"project": kind.name, "mode": mode, "first_period": kind.labels[kind.first], "links": {k: (v if not isinstance(v, list) else len(v)) for k, v in found.items()}, "setup_decisions": setup, "cycles": []}
    releases: list[str] = []
    for n in range(1, cycles + 1):
        t0 = time.time()
        kind.workbook(root, n)
        row: dict = {"cycle": n, "to": kind.labels[kind.first + n]}
        try:
            staged = svc.stage_rollforward(pid)
        except ServiceError as exc:
            row["blocked"] = str(exc)[:200]
            report["cycles"].append(row)
            break
        flags = staged["flags"]
        high = [f for f in flags if f["severity"] == "high"]
        try:
            svc.approve_and_publish(pid, staged["release_id"], staged["digest"], acknowledge=False)
            acked = False
        except NeedsAcknowledgement:
            svc.approve_and_publish(pid, staged["release_id"], staged["digest"], acknowledge=True)
            acked = True
        releases.append(staged["release_id"])
        got, want = kind.read(root), {**kind.sentences(n), **kind.table_expected(n)}
        wrong_silent, wrong_reported, ok, equivalent = [], [], 0, 0
        for key, expect in want.items():
            actual = got.get(key)
            if actual is None and expect is None:
                continue
            if actual == expect:
                ok += 1
                continue
            if actual is None:
                continue  # a sentence the template now writes that the owner's document never had: nothing for Workroom to roll
            if kind.b_wording_true(key, actual, n) and nums(actual) == nums(expect or ""):
                equivalent += 1  # the sentence says something else than the template does, but it is still true of the data
                continue
            told = [f for f in flags if f["sentence_after"] and (f["sentence_after"] == actual or f["sentence_after"] in actual or f["sentence_before"] == actual)]
            (wrong_reported if told else wrong_silent).append({"element": key, "found": actual, "expected": expect})
        correct = {got[k] for k in got if got.get(k) is not None and got.get(k) == want.get(k)}
        false_alarms = [f["summary"][:80] for f in flags if f["severity"] in ("high", "medium") and f["sentence_after"] in correct]
        row.update({"seconds": round(time.time() - t0, 1), "figures_rolled": staged["figures"], "period_words": staged["period_words"], "flags": {s: sum(1 for f in flags if f["severity"] == s) for s in ("high", "medium", "info")},
                    "acknowledged": acked, "elements_exact": ok, "still_true_other_wording": equivalent, "differences_reported": len(wrong_reported), "differences_silent": len(wrong_silent), "false_alarms": len(false_alarms),
                    "claims_read": staged["coverage"].get("claims_read"), "not_checked": staged["coverage"].get("not_checked_count"), "silent_detail": wrong_silent[:3], "false_alarm_detail": false_alarms[:2]})
        saved[n] = (root / kind.file).read_bytes()
        if mode == "owner":
            fixed = kind.rewrite(root, want)
            svc.discover(pid)
            again = settle(svc, pid)
            row["owner_edits"] = fixed
            row["owner_decisions"] = again["sources_confirmed"] + again["calculations_accepted"]
            row["owner_actions"] = 1 + (1 if acked else 0) + fixed + row["owner_decisions"]  # approve, acknowledge once, each sentence rewritten, each proposal confirmed
        report["cycles"].append(row)
    if mode == "hands-off":
        back = []
        for k in range(len(releases), 0, -1):
            try:
                svc.restore_release(pid, releases[k - 1])
            except ServiceError as exc:
                back.append({"to_cycle": k - 1, "error": str(exc)[:120]})
                break
            back.append({"to_cycle": k - 1, "byte_identical": (root / kind.file).read_bytes() == saved[k - 1]})
        report["restore"] = back
    shutil.rmtree(root, ignore_errors=True)
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--cycles", type=int, default=6)
    ap.add_argument("--mode", default="owner", choices=["owner", "hands-off"])
    ns = ap.parse_args()
    folder = Path(ns.folder)
    trials = [QuarterlyDeck(folder, "Q1 2025", "Q3 2026"), MonthlyReport(folder, "Jan 2025", "Oct 2026")]
    results = []
    for k in trials:
        n = min(ns.cycles, k.periods())
        r = run(k, folder, n, ns.mode)
        results.append(r)
        print(json.dumps({k2: v for k2, v in r.items() if k2 != "cycles"}))
        for c in r["cycles"]:
            print("  ", json.dumps({a: b for a, b in c.items() if a != "silent_detail"}))
            for d in c.get("silent_detail", []):
                print("      SILENT:", json.dumps(d)[:420])
            for d in c.get("false_alarm_detail", []):
                print("      FALSE ALARM:", d)
    if ns.out:
        Path(ns.out).write_text(json.dumps(results, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
