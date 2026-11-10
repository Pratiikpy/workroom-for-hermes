"""The static verifier page checked against records signed by the product: valid, tampered record, changed document, changed source.

    python verifier_page_test.py
Makes a published release, exports its signed record, then runs the page's own verifier code under Node (WebCrypto) against it.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT.parent))

from workroom.tests.test_dossier import published  # noqa: E402

JS = r'''
const fs = require('fs')
const html = fs.readFileSync(process.argv[2], 'utf8')
const code = html.split('<script id="verifier">')[1].split('</script>')[0]
const m = { exports: {} }
new Function('module', 'crypto', 'TextEncoder', 'atob', code)(m, globalThis.crypto, TextEncoder, atob)
const { verifyRecord } = m.exports
const scenario = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'))
;(async () => {
  const out = []
  for (const s of scenario) {
    const files = new Map(Object.entries(s.files).map(([k, v]) => [k, Uint8Array.from(Buffer.from(v, 'base64'))]))
    const r = await verifyRecord(s.envelope, files)
    out.push({ name: s.name, ok: r.ok, results: r.checks.map(c => c.check + '=' + c.result) })
  }
  console.log(JSON.stringify(out))
})()
'''


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="wr_vp_"))
    root, svc, pid, rid = published(tmp)
    env = svc.release_proof_export(pid, rid)
    import base64

    def blob(name: str, extra: bytes = b"") -> str:
        return base64.b64encode((root / name).read_bytes() + extra).decode()

    files = {n: blob(n) for n in ("report.docx", "results.xlsx")}
    forged = json.loads(json.dumps(env))
    forged["payload"]["approved_by"] = "someone-else"
    scenarios = [
        {"name": "good", "envelope": env, "files": files},
        {"name": "forged record", "envelope": forged, "files": files},
        {"name": "changed document", "envelope": env, "files": {**files, "report.docx": blob("report.docx", b"x")}},
        {"name": "changed source", "envelope": env, "files": {**files, "results.xlsx": blob("results.xlsx", b"x")}},
        {"name": "document not chosen", "envelope": env, "files": {"results.xlsx": files["results.xlsx"]}},
    ]
    (tmp / "scenarios.json").write_text(json.dumps(scenarios), encoding="utf-8")
    (tmp / "run.js").write_text(JS, encoding="utf-8")
    run = subprocess.run(["node", str(tmp / "run.js"), str(ROOT / "docs" / "verify" / "index.html"), str(tmp / "scenarios.json")], capture_output=True, text=True, timeout=60)
    if run.returncode:
        print("FAIL node:", run.stderr[-500:])
        sys.exit(1)
    got = {r["name"]: r for r in json.loads(run.stdout)}
    want = {"good": True, "forged record": False, "changed document": False, "changed source": False, "document not chosen": False}
    bad = [n for n, ok in want.items() if got[n]["ok"] != ok]
    for n, r in got.items():
        print(("PASS " if r["ok"] == want[n] else "FAIL ") + n, r["results"])
    print(f"{len(want) - len(bad)}/{len(want)} as expected")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
