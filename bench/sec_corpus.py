"""Build a real-world matching corpus from public SEC filings.

For each company: the quarterly earnings press release (8-K exhibit 99.1, real prose and tables) becomes a Word document, and the
XBRL facts the company filed in the matching 10-Q become a workbook (one row per reported concept, one column per period, values
in millions of dollars, as analysts keep them). Nothing is invented: every number in the workbook is a filed XBRL fact, and every
sentence in the document is the company's own.

    SEC_USER_AGENT="Your Name your@email" python sec_corpus.py <output folder>
"""

import datetime as dt
import io
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

from docx import Document
from lxml import html as lhtml
from openpyxl import Workbook

COMPANIES = {"AAPL": 320193, "MSFT": 789019, "NVDA": 1045810, "KO": 21344, "PEP": 77476, "JNJ": 200406, "PG": 80424, "WMT": 104169, "HD": 354950, "COST": 909832}
UA = {"User-Agent": os.environ.get("SEC_USER_AGENT", "")}


def get(url: str) -> bytes:
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                data = r.read()
            time.sleep(0.4)
            return data
        except OSError:
            time.sleep(3 * (attempt + 1))
    raise OSError(f"could not fetch {url}")


def release_to_docx(raw: bytes) -> bytes:
    tree = lhtml.fromstring(raw)
    doc = Document()
    seen = set()
    for el in tree.iter("p", "div", "table"):
        if el.tag == "table":
            rows = []
            for tr in el.iter("tr"):
                cells = [re.sub(r"\s+", " ", "".join(td.itertext())).strip() for td in tr if td.tag in ("td", "th")]
                cells = [c for c in cells if c not in ("", "$", ")", "%")]
                if cells:
                    rows.append(cells)
            if len(rows) >= 2:
                width = max(len(r) for r in rows)
                t = doc.add_table(rows=0, cols=width)
                for r in rows:
                    cs = t.add_row().cells
                    for i, c in enumerate(r):
                        cs[i].text = c
            continue
        if any(a.tag == "table" for a in el.iterancestors()):
            continue
        if el.xpath(".//p|.//div|.//table"):
            continue
        text = re.sub(r"\s+", " ", "".join(el.itertext())).strip()
        if len(text) > 25 and text not in seen:
            seen.add(text)
            doc.add_paragraph(text)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def facts_to_xlsx(facts: dict, accession: str) -> tuple[bytes, int]:
    rows: dict[str, dict[str, float]] = {}
    cols: dict[str, tuple] = {}
    for concept, body in facts["facts"].get("us-gaap", {}).items():
        label = body.get("label") or concept
        for unit, items in body["units"].items():
            if unit != "USD":
                continue
            for f in items:
                if f.get("accn") != accession or "start" not in f:
                    continue
                days = (dt.date.fromisoformat(f["end"]) - dt.date.fromisoformat(f["start"])).days
                span = "3 months" if 80 <= days <= 100 else "6 months" if 170 <= days <= 190 else "9 months" if 260 <= days <= 280 else "12 months" if 350 <= days <= 380 else None
                if span is None:
                    continue
                col = f"{span} ended {f['end']}"
                cols[col] = (f["end"], span)
                rows.setdefault(label, {})[col] = round(f["val"] / 1e6, 3)
    ordered = sorted(cols, key=lambda c: (cols[c][1] != "3 months", cols[c][0]), reverse=False)
    wb = Workbook()
    ws = wb.active
    ws.title = "Financials"
    ws.append(["In millions of USD"] + ordered)
    for label, vals in sorted(rows.items()):
        ws.append([label] + [vals.get(c) for c in ordered])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), len(rows)


def build(out: Path) -> None:
    if not UA["User-Agent"]:
        sys.exit("Set SEC_USER_AGENT to a contact string, as the SEC requires.")
    out.mkdir(parents=True, exist_ok=True)
    summary = {}
    for ticker, cik in COMPANIES.items():
        try:
            sub = json.loads(get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json"))["filings"]["recent"]
        except OSError as exc:
            print(ticker, "skipped:", exc)
            continue
        forms = sub["form"]
        q = next((i for i in range(len(forms)) if forms[i] == "10-Q"), None)
        if q is None:
            continue
        qdate = dt.date.fromisoformat(sub["filingDate"][q])
        e = next((i for i in range(len(forms)) if forms[i] == "8-K" and "2.02" in sub["items"][i] and 0 <= (qdate - dt.date.fromisoformat(sub["filingDate"][i])).days <= 45), None)
        if e is None:
            continue
        nd = sub["accessionNumber"][e].replace("-", "")
        names = [i["name"] for i in json.loads(get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{nd}/index.json"))["directory"]["item"]]
        candidates = [n for n in names if n.lower().endswith((".htm", ".html")) and "index" not in n.lower() and n != sub["primaryDocument"][e]]
        ex = next((n for n in candidates if re.search(r"(ex|d).?99|earnings|release|pr", n, re.I)), candidates[0] if candidates else None)
        if ex is None:
            continue
        release = get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{nd}/{ex}")
        facts = json.loads(get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"))
        xlsx, nrows = facts_to_xlsx(facts, sub["accessionNumber"][q])
        folder = out / ticker
        folder.mkdir(exist_ok=True)
        (folder / f"{ticker}-earnings-release.docx").write_bytes(release_to_docx(release))
        (folder / f"{ticker}-financials.xlsx").write_bytes(xlsx)
        summary[ticker] = {"10-Q": sub["accessionNumber"][q], "8-K": sub["accessionNumber"][e], "concepts": nrows}
        print(ticker, summary[ticker])
    (out / "corpus.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")


if __name__ == "__main__":
    build(Path(sys.argv[1]))
