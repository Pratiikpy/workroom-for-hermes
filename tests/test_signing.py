"""A signed record of a release: tampering with the record, the document or the source is each detected, and the agent cannot reach the key."""

import json
from pathlib import Path

from workroom.adapters.secret_guard import make_secret_guard
from workroom.tests.test_dossier import published
from workroom.workroom_core.signing import Signer, verify


def exported(tmp_path: Path):
    root, svc, pid, rid = published(tmp_path)
    return root, svc, pid, svc.release_proof_export(pid, rid)


def checks(result) -> dict[str, str]:
    return {c["check"]: c["result"] for c in result["checks"]}


def test_a_fresh_export_verifies_and_says_what_it_does_not_prove(tmp_path: Path) -> None:
    root, svc, pid, env = exported(tmp_path)
    got = svc.verify_proof(pid, env)
    assert got["ok"] and checks(got)["signature"] == "pass" and "document report.docx" in checks(got) and "source results.xlsx" in checks(got)
    assert "not that the figures are true" in got["does_not_prove"] or "figures are true" in got["does_not_prove"]
    assert env["payload"]["approved_by"] and env["key_fingerprint"]


def test_each_kind_of_tampering_is_caught(tmp_path: Path) -> None:
    root, svc, pid, env = exported(tmp_path)
    forged = json.loads(json.dumps(env))
    forged["payload"]["approved_by"] = "someone-else"
    assert checks(verify(forged, root))["signature"] == "FAIL"
    doc = root / "report.docx"
    original = doc.read_bytes()
    doc.write_bytes(original + b"x")
    assert checks(svc.verify_proof(pid, env))["document report.docx"] == "FAIL"
    doc.write_bytes(original)
    book = root / "results.xlsx"
    keep = book.read_bytes()
    book.write_bytes(keep + b"x")
    assert checks(svc.verify_proof(pid, env))["source results.xlsx"] == "FAIL"
    book.unlink()
    assert "not there" in [c["detail"] for c in svc.verify_proof(pid, env)["checks"] if c["check"] == "source results.xlsx"][0]
    book.write_bytes(keep)
    assert svc.verify_proof(pid, env)["ok"]


def test_a_record_signed_by_another_key_still_verifies_only_as_that_keys_record(tmp_path: Path) -> None:
    root, svc, pid, env = exported(tmp_path)
    other = Signer(tmp_path / "other-keys").sign(env["payload"])
    assert other["key_fingerprint"] != env["key_fingerprint"] and verify(other, root)["ok"]  # valid, but the fingerprint tells the recipient it is a different signer


def test_the_key_stays_in_the_data_folder_and_the_secret_guard_blocks_tools_that_name_it(tmp_path: Path) -> None:
    root, svc, pid, env = exported(tmp_path)
    key = svc.data_dir / "keys" / "signing.key"
    assert key.is_file() and not str(key).startswith(str(root))
    g = make_secret_guard(lambda: [svc.data_dir])
    assert g(tool_name="read_file", args={"path": str(key)})["action"] == "block"
    assert g(tool_name="terminal", args={"command": f"cat {key.as_posix()}"})["action"] == "block"
    assert g(tool_name="write_file", args={"path": str(svc.data_dir / "evidence.db"), "content": "x"})["action"] == "block"
    assert g(tool_name="read_file", args={"path": str(root / "report.docx")}) is None
    assert g(tool_name="workroom_verify", args={"project": str(svc.data_dir)}) is None


def test_a_restored_release_cannot_be_exported(tmp_path: Path) -> None:
    import pytest

    from workroom.workroom_core.service import ServiceError

    root, svc, pid, rid = published(tmp_path)
    svc.restore_release(pid, rid)
    with pytest.raises(ServiceError):
        svc.release_proof_export(pid, rid)


def test_a_copy_carries_its_own_record_and_is_checked_on_its_own(tmp_path: Path) -> None:
    import io
    import zipfile

    from workroom.workroom_core import embed

    root, svc, pid, env = exported(tmp_path)
    rid = env["payload"]["release"]
    original = (root / "report.docx").read_bytes()
    out = svc.release_proof_embed(pid, rid, "report.docx")
    assert out["written"] == "report.proven.docx" and (root / "report.docx").read_bytes() == original
    copy = (root / out["written"]).read_bytes()
    assert embed.extract(copy)["signature"] == env["signature"]
    good = svc.verify_embedded_file(pid, out["written"])
    assert good["ok"] and checks(good) == {"signature": "pass", "content": "pass"}
    # the copy's content is the released content: every part but two bookkeeping lists is byte-identical to the released file
    a, b = zipfile.ZipFile(io.BytesIO(original)), zipfile.ZipFile(io.BytesIO(copy))
    assert [n for n in a.namelist() if a.read(n) != b.read(n)] == ["[Content_Types].xml", "word/_rels/document.xml.rels"]
    # changing one part after embedding is caught by the content check, and the signature still holds
    tampered = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(copy)) as zin, zipfile.ZipFile(tampered, "w") as zout:
        for item in zin.infolist():
            body = zin.read(item.filename)
            zout.writestr(item.filename, body.replace(b"120", b"999") if item.filename == "word/document.xml" else body)
    (root / "t.docx").write_bytes(tampered.getvalue())
    bad = svc.verify_embedded_file(pid, "t.docx")
    assert not bad["ok"] and checks(bad) == {"signature": "pass", "content": "FAIL"}
    # a forged record is caught by the signature
    forged = json.loads(json.dumps(env))
    forged["payload"]["approved_by"] = "someone-else"
    (root / "f.docx").write_bytes(embed.embed(original, forged))
    assert checks(svc.verify_embedded_file(pid, "f.docx"))["signature"] == "FAIL"
    # a file with no record says so
    assert not svc.verify_embedded_file(pid, "report.docx")["ok"]


def test_the_copy_is_refused_when_the_file_is_no_longer_the_released_one(tmp_path: Path) -> None:
    import pytest

    from workroom.workroom_core.service import ServiceError

    root, svc, pid, env = exported(tmp_path)
    (root / "report.docx").write_bytes((root / "report.docx").read_bytes() + b"x")
    with pytest.raises(ServiceError):
        svc.release_proof_embed(pid, env["payload"]["release"], "report.docx")
