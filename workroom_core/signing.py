"""A signed record of one released document, and the check a recipient can run.

The record says: this project, this release, these files with these exact bytes (SHA-256), approved by this principal at this time, against these source
files with these hashes. It is signed with an Ed25519 key that lives in Workroom's own data folder, outside every project folder, and that no agent tool is
allowed to read (see adapters/secret_guard.py). Anyone holding the record, the document and the source files can check it with only the public key inside it.

What a good verdict proves: the record was made by whoever holds this key, and the document and sources are byte-for-byte what it names. What it does NOT
prove: that the figures are true, that the key's owner is who they claim to be (the verifier shows the key's fingerprint; trusting it is the recipient's
decision), or that the sources themselves are right.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

VERSION = 1
MAX_FILE = 200 * 1024 * 1024


def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_file(path: Path) -> str | None:
    try:
        if not path.is_file() or path.stat().st_size > MAX_FILE:
            return None
        h = hashlib.sha256()
        with path.open("rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        return h.hexdigest()
    except OSError:
        return None


def fingerprint(public_raw: bytes) -> str:
    return hashlib.sha256(public_raw).hexdigest()[:16]


class Signer:
    def __init__(self, key_dir: Path) -> None:
        self.key_dir = Path(key_dir)
        self.key_path = self.key_dir / "signing.key"

    def _private(self) -> Ed25519PrivateKey:
        if self.key_path.is_file():
            return serialization.load_pem_private_key(self.key_path.read_bytes(), password=None)  # type: ignore[return-value]
        self.key_dir.mkdir(parents=True, exist_ok=True)
        key = Ed25519PrivateKey.generate()
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        tmp = self.key_path.with_suffix(".tmp")
        tmp.write_bytes(pem)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self.key_path)
        return key

    def public_raw(self) -> bytes:
        return self._private().public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)

    def sign(self, payload: dict[str, Any]) -> dict[str, Any]:
        priv = self._private()
        pub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        body = {"version": VERSION, **payload}
        return {"payload": body, "signature": base64.b64encode(priv.sign(_canonical(body))).decode("ascii"),
                "public_key": base64.b64encode(pub).decode("ascii"), "key_fingerprint": fingerprint(pub)}


def verify(envelope: dict[str, Any], folder: Path, source_folder: Path | None = None) -> dict[str, Any]:
    """Check an envelope against files on disk. Returns each check with a plain verdict; ``ok`` only when every one passes."""
    checks: list[dict[str, str]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "result": "pass" if ok else "FAIL", "detail": detail})

    try:
        body = envelope["payload"]
        pub_raw = base64.b64decode(envelope["public_key"])
        Ed25519PublicKey.from_public_bytes(pub_raw).verify(base64.b64decode(envelope["signature"]), _canonical(body))
        add("signature", True, f"valid for key {fingerprint(pub_raw)}; whether you trust that key is your decision")
    except (KeyError, ValueError, InvalidSignature, TypeError):
        add("signature", False, "the record was changed after it was signed, or it is not a Workroom record")
        return {"ok": False, "checks": checks, "proves": PROVES, "does_not_prove": DOES_NOT}
    for f in body.get("files", []):
        got = sha256_file(Path(folder) / f["file"])
        if got is None:
            add(f"document {f['file']}", False, "the file is not there")
        elif got == f["sha256"]:
            add(f"document {f['file']}", True, "byte for byte the released file")
        else:
            add(f"document {f['file']}", False, "the file differs from the released bytes (changed since release, or a different file)")
    for s in body.get("sources", []):
        base = Path(source_folder) if source_folder else Path(folder)
        got = sha256_file(base / s["file"])
        if got is None:
            add(f"source {s['file']}", False, "the source file is not there, so its figures cannot be checked")
        elif got == s["sha256"]:
            add(f"source {s['file']}", True, "the same workbook the figures were taken from")
        else:
            add(f"source {s['file']}", False, "the source has changed since the release, or this is a different workbook")
    return {"ok": all(c["result"] == "pass" for c in checks), "checks": checks, "approved_by": body.get("approved_by"), "approved_at": body.get("approved_at"),
            "release": body.get("release"), "figures": body.get("figures"), "proves": PROVES, "does_not_prove": DOES_NOT}


def verify_embedded(data: bytes) -> dict[str, Any]:
    """Check a file that carries its own signed record, with nothing else to hand: the signature, and that the file's content is what the record names."""
    from . import embed

    env = embed.extract(data)
    if env is None:
        return {"ok": False, "checks": [{"check": "record", "result": "FAIL", "detail": "this file carries no Workroom record (or Office rewrote it and dropped it)"}], "proves": PROVES, "does_not_prove": DOES_NOT}
    out = verify(env, Path("."))  # signature only: the named files are checked below against this file itself
    checks = [c for c in out["checks"] if c["check"] == "signature"]
    ok = bool(checks) and checks[0]["result"] == "pass"
    named = [f for f in (env.get("payload") or {}).get("files", []) if f.get("package_digest")]
    if ok and not named:
        checks.append({"check": "content", "result": "FAIL", "detail": "the record does not name a content digest, so it cannot be tied to this file"})
    elif ok:
        got = embed.package_digest(data)
        match = any(f["package_digest"] == got for f in named)
        checks.append({"check": "content", "result": "pass" if match else "FAIL",
                       "detail": "the content of this file is the released content (the record itself does not count)" if match
                       else "the content differs from the released content: the file was changed, or re-saved by a program that rewrites it, after release"})
    body = env.get("payload") or {}
    return {"ok": all(c["result"] == "pass" for c in checks), "checks": checks, "approved_by": body.get("approved_by"), "approved_at": body.get("approved_at"),
            "release": body.get("release"), "figures": body.get("figures"), "proves": PROVES, "does_not_prove": DOES_NOT}


PROVES = "Who approved these exact bytes, against which exact source files, and that nothing was changed since."
DOES_NOT = "That the figures are true, that the sources are right, or that the person who holds the key is who they say they are."
