"""The operations behind both the agent tools and the Desktop routes. No Hermes imports: the data directory is passed in."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .controller.approvals import ApprovalError, sign
from .controller.release import Controller, NotReady, ReleaseError, StaleRelease
from .project import Plan, Project, open_document
from .store.manifest import MANIFEST_NAME, Anchor, Manifest, ManifestError

DESKTOP_PRINCIPAL = "desktop:local-session"
LOCAL_PRINCIPAL = "local:session"
APPROVAL_TTL_SECONDS = 15 * 60


def _restrict_to_owner(path: Path) -> None:
    """Owner-only access. POSIX modes are set at creation; on Windows the ACL is reduced to the current user."""
    if os.name != "nt":
        return
    import getpass
    import subprocess

    try:
        subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{getpass.getuser()}:(R,W)"], check=True, capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        pass


_PART_NAMES = (("word/document.xml", "Body"), ("word/footnotes.xml", "Footnotes"), ("word/endnotes.xml", "Endnotes"))


def location_label(deck, slide: int) -> str:
    """A person's name for where a number sits: a slide, a Word part (Body, Header, Footer), or a sheet."""
    parts = deck.slide_parts()
    part = parts[slide - 1] if 1 <= slide <= len(parts) else ""
    if part.startswith("ppt/"):
        return f"Slide {slide}"
    if part.startswith("xl/"):
        names = getattr(deck, "_sheets", None)
        return f"Sheet {names[slide - 1].name}" if names and 1 <= slide <= len(names) else f"Sheet {slide}"
    for suffix, name in _PART_NAMES:
        if part == suffix:
            return name
    stem = part.rsplit("/", 1)[-1]
    if stem.startswith("header"):
        return "Header"
    if stem.startswith("footer"):
        return "Footer"
    return f"Part {slide}"


def _is_plain_number(text: str) -> bool:
    try:
        float(text)
        return True
    except ValueError:
        return False


def _closing(fn):
    """Close every database opened during the call, so no file stays locked on Windows after a request."""
    import functools

    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        try:
            return fn(self, *args, **kwargs)
        finally:
            self._close_opened()

    return wrapper


class ServiceError(Exception):
    """A request the service refuses; the message is safe to show to the user."""


class Service:
    def __init__(self, data_dir: Path, approvers: frozenset[str] = frozenset()) -> None:
        self.approvers = frozenset(approvers)
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._key = self._load_key()
        self._opened: list[tuple[Project, Controller]] = []

    # ---- key custody (see ARCHITECTURE section 12 item c: a file with owner-only permissions for now) ----
    def _load_key(self) -> bytes:
        path = self.data_dir / "signing.key"
        if not path.exists():
            self.data_dir.mkdir(parents=True, exist_ok=True)
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                return path.read_bytes()
            with os.fdopen(fd, "wb") as fh:
                fh.write(secrets.token_bytes(32))
            _restrict_to_owner(path)
        return path.read_bytes()

    # ---- projects ----
    def _registry(self) -> dict[str, str]:
        p = self.data_dir / "projects.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    def add_project(self, folder: str) -> dict[str, Any]:
        path = Path(folder).expanduser().resolve()
        if not path.is_dir():
            raise ServiceError(f"{folder} is not a folder")
        pid = hashlib.sha256(str(path).lower().encode()).hexdigest()[:12]
        reg = self._registry()
        reg[pid] = str(path)
        (self.data_dir / "projects.json").write_text(json.dumps(reg, indent=1), encoding="utf-8")
        return {"project": pid, "folder": str(path)}

    def projects(self) -> list[dict[str, str]]:
        return [{"project": k, "folder": v} for k, v in self._registry().items()]

    def _resolve(self, name: str) -> str:
        """A project id, or the project's folder path or folder name when that is unambiguous."""
        reg = self._registry()
        if name in reg:
            return name
        wanted = str(name).strip().rstrip("/\\").lower()
        hits = [k for k, v in reg.items() if v.lower() == wanted or Path(v).name.lower() == wanted]
        if len(hits) == 1:
            return hits[0]
        known = "; ".join(f"{k} ({v})" for k, v in reg.items()) or "none yet"
        why = "is ambiguous" if hits else "is not a known project"
        raise ServiceError(f"{name!r} {why}. Known projects: {known}. Use the project id from workroom_status.")

    def _open(self, pid: str) -> tuple[Project, Controller]:
        pid = self._resolve(pid)
        folder = self._registry()[pid]
        state = self.data_dir / "projects" / pid
        pair = (Project(Path(folder), state), Controller(Path(folder), state, self._key, frozenset({DESKTOP_PRINCIPAL, LOCAL_PRINCIPAL}) | self.approvers))
        self._opened.append(pair)
        return pair

    def _close_opened(self) -> None:
        while self._opened:
            proj, ctl = self._opened.pop()
            for closer in (ctl.journal.close, proj.db.close):
                try:
                    closer()
                except Exception:  # noqa: BLE001  closing is best effort
                    pass

    # ---- integrity: manifest chain + three mirrored release counters ----
    def _integrity(self, pid: str, proj: Project, ctl: Controller) -> tuple[Manifest, Anchor]:
        """Refuse to release anything when the saved state cannot be trusted (recovery mode)."""
        try:
            manifest = Manifest(proj.root / MANIFEST_NAME, self._key, pid)
            anchor = Anchor(self.data_dir / "projects" / pid / "anchor.json", self._key, pid)
            counters = {
                "manifest": manifest.counter(),
                "anchor": anchor.read(),
                "journal": self._published_count(ctl),
            }
        except ManifestError as exc:
            raise ServiceError(f"Workroom is in recovery mode: {exc}. Nothing will be released until you review it.") from exc
        if len(set(counters.values())) != 1:
            raise ServiceError(
                f"Workroom is in recovery mode: its saved history disagrees with itself ({counters}). "
                "Nothing will be released until you review it."
            )
        return manifest, anchor

    @staticmethod
    def _published_count(ctl: Controller) -> int:
        """Releases that were ever published. A later restore does not undo that fact in the history."""
        return sum(1 for rid in ctl.journal.release_ids() if any(r.step == "PUBLISHED" for r in ctl.journal.rows(rid)))

    # ---- recovery: the owner reviews what disagrees, then accepts the current state ----
    def _counters(self, pid: str, proj: Project, ctl: Controller) -> tuple[dict[str, int] | None, str | None]:
        try:
            manifest = Manifest(proj.root / MANIFEST_NAME, self._key, pid)
            anchor = Anchor(self.data_dir / "projects" / pid / "anchor.json", self._key, pid)
            counters = {
                "manifest": manifest.counter(),
                "anchor": anchor.read(),
                "journal": self._published_count(ctl),
            }
        except ManifestError as exc:
            return None, str(exc)
        if len(set(counters.values())) != 1:
            return counters, "the three saved release counters disagree"
        return counters, None

    @_closing
    def history_review(self, pid: str) -> dict[str, Any]:
        proj, ctl = self._open(pid)
        counters, reason = self._counters(pid, proj, ctl)
        return {"state": "ok" if reason is None else "recovery", "counters": counters, "reason": reason}

    @_closing
    def accept_history(self, pid: str, seen: dict[str, int] | None, principal: str = DESKTOP_PRINCIPAL) -> dict[str, Any]:
        """Owner action (an authenticated route, never an agent tool): treat the release journal on this machine as the truth
        and record that decision, with what was seen, in the signed manifest. `seen` must equal what the owner reviewed."""
        proj, ctl = self._open(pid)
        counters, reason = self._counters(pid, proj, ctl)
        if reason is None:
            return {"state": "ok", "counters": counters, "reason": None}
        if (counters or None) != (seen or None):
            raise ServiceError("the saved history changed since you reviewed it; review it again before accepting")
        truth = self._published_count(ctl)
        manifest_path = proj.root / MANIFEST_NAME
        aside = None
        try:
            manifest = Manifest(manifest_path, self._key, pid)
        except ManifestError:
            manifest, aside = Manifest.start_over(manifest_path, self._key, pid)
        manifest.append("recovered", {"counter": truth, "seen": counters, "reason": reason, "by": principal, "at": time.time(),
                                      "set_aside": aside.name if aside else None})
        Anchor(self.data_dir / "projects" / pid / "anchor.json", self._key, pid).write(truth)
        return {"state": "ok", "counters": {"manifest": truth, "anchor": truth, "journal": truth}, "reason": None}

    # ---- discover / plan ----
    @_closing
    def discover(self, pid: str) -> dict[str, Any]:
        proj, _ = self._open(pid)
        found = proj.discover()
        ties = proj.ties()
        return {
            "numbers_found": found.found,
            "accepted": sum(1 for t in ties if t.state == "accepted"),
            "need_confirmation": [self._tie_view(t) for t in ties if t.state == "confirm"],
            "no_source": found.no_source,
            "kept": found.kept,
            "unreadable": list(found.unreadable),
        }

    @staticmethod
    def _tie_view(t) -> dict[str, Any]:
        return {"id": t.id, "deck": t.deck, "slide": t.slide, "text": t.raw, "sentence": t.context,
                "source": f"{t.src_file} {t.sheet}!{t.ref}", "state": t.state}

    @_closing
    def ties(self, pid: str) -> list[dict[str, Any]]:
        proj, _ = self._open(pid)
        return [self._tie_view(t) for t in proj.ties()]

    @_closing
    def skip(self, pid: str, tie_id: int) -> None:
        proj, _ = self._open(pid)
        proj.skip(tie_id)

    @_closing
    def explain(self, pid: str, tie_id: int) -> dict[str, Any]:
        """Ask Why: where a number came from, how it was linked, and what would happen if the source changed."""
        proj, _ = self._open(pid)
        t = proj.tie(tie_id)
        if t is None:
            raise ServiceError(f"unknown link {tie_id}")
        from .ooxml.package import open_package
        from .ooxml.xlsx import read_cell

        path = proj.root / t.src_file
        cell = read_cell(open_package(path.read_bytes()), t.sheet, t.ref)
        current = proj._current_values().get((t.src_file, t.sheet, t.ref))
        row_labels = next((c.row_labels for c in proj.source_index().cells if (c.file, c.sheet, c.ref) == (t.src_file, t.sheet, t.ref)), ())
        col_labels = next((c.col_labels for c in proj.source_index().cells if (c.file, c.sheet, c.ref) == (t.src_file, t.sheet, t.ref)), ())
        how = {
            "accepted": "Workroom linked it automatically because the value, the words around it and the period all point to this cell, and no other cell fits as well.",
            "confirmed": "You confirmed this link.",
            "confirm": "Workroom found this cell but is not sure; it waits for you.",
            "skipped": "You said this number is not tied to that cell.",
        }[t.state]
        changed = current is not None and current != t.linked_value
        return {
            "text": t.raw, "sentence": t.context, "deck": t.deck, "slide": t.slide,
            "source": {"file": t.src_file, "sheet": t.sheet, "cell": t.ref, "row": list(row_labels), "column": list(col_labels),
                       "formula": cell.formula, "value_now": current, "value_at_last_release": t.linked_value},
            "state": t.state, "how": how, "source_changed_since_last_release": changed,
            "displayed_as": t.transform,
            "if_source_changes": "The number in the document would be rewritten in the same style after you approve a release." if t.state in ("accepted", "confirmed") else "Nothing changes: this link is not active.",
        }

    @_closing
    def confirm(self, pid: str, tie_id: int) -> None:
        proj, _ = self._open(pid)
        proj.confirm(tie_id)

    @_closing
    def plan(self, pid: str) -> dict[str, Any]:
        proj, _ = self._open(pid)
        plan = proj.plan_refresh()
        return {"changes": self._changes(proj, plan), "held": plan.skipped, "files": sorted(plan.files)}

    @staticmethod
    def _changes(proj: Project, plan: Plan) -> list[dict[str, Any]]:
        docs: dict[str, Any] = {}
        out = []
        for i in plan.impacts:
            if i.deck not in docs:
                docs[i.deck] = open_document((proj.root / i.deck).read_bytes(), i.deck)
            out.append({**asdict(i), "where": location_label(docs[i.deck], i.slide)})
        return out

    # ---- per-project settings ----
    @_closing
    def settings(self, pid: str) -> dict[str, Any]:
        proj, _ = self._open(pid)
        return {"tracked_changes": bool(proj._config().get("tracked_changes"))}

    @_closing
    def set_settings(self, pid: str, tracked_changes: bool) -> dict[str, Any]:
        proj, _ = self._open(pid)
        proj.set_config(tracked_changes=bool(tracked_changes))
        return {"tracked_changes": bool(tracked_changes)}

    # ---- past releases: list and restore ----
    @_closing
    def releases(self, pid: str) -> list[dict[str, Any]]:
        proj, ctl = self._open(pid)
        out = []
        for rid in ctl.journal.release_ids():
            steps = [r.step for r in ctl.journal.rows(rid)]
            if "PUBLISHED" not in steps:
                continue
            meta_path = self.data_dir / "projects" / pid / "meta" / f"{rid}.json"
            changes = json.loads(meta_path.read_text(encoding="utf-8"))["changes"] if meta_path.exists() else []
            out.append({"release_id": rid, "published_at": ctl.journal.when(rid, "PUBLISHED"), "changes": changes,
                        "restored": "ROLLED_BACK" in steps[steps.index("PUBLISHED"):]})
        return list(reversed(out))

    @_closing
    def restore_release(self, pid: str, release_id: str, principal: str = DESKTOP_PRINCIPAL) -> dict[str, Any]:
        """Owner action (an authenticated route, never an agent tool): put the files of one published release back as they were.
        Refused when any of those files changed since the release, so later work is never overwritten."""
        proj, ctl = self._open(pid)
        manifest, anchor = self._integrity(pid, proj, ctl)
        meta_path = self.data_dir / "projects" / pid / "meta" / f"{release_id}.json"
        changes = json.loads(meta_path.read_text(encoding="utf-8"))["changes"] if meta_path.exists() else []
        try:
            ctl.restore(release_id)
        except StaleRelease as exc:
            raise ServiceError(f"not restored: {exc}") from exc
        except ReleaseError as exc:
            raise ServiceError(f"not restored: {exc}") from exc
        except PermissionError as exc:
            raise ServiceError(f"a file is open in another program ({Path(str(exc.filename or '')).name or 'unknown'}); close it and try again. Nothing was changed.") from exc
        files = {c["deck"] for c in changes}
        restored = {rel: (proj.root / rel).read_bytes() for rel in files}
        override = {}
        for c in changes:
            f, sheet, ref = c["src"].split("!", 2)
            override[(f, sheet, ref)] = c["old_value"]
        proj.commit_snapshot(Plan(files=restored), override=override)
        manifest.append("restored", {"release_id": release_id, "by": principal, "at": time.time(), "files": sorted(files)})
        return {"release_id": release_id, "state": "restored", "files": sorted(files)}

    # ---- stage / approve ----
    @_closing
    def stage(self, pid: str, mode: str = "inplace") -> dict[str, Any]:
        proj, ctl = self._open(pid)
        self._integrity(pid, proj, ctl)
        plan = proj.plan_refresh()
        if not plan.files:
            raise ServiceError("nothing to release: no tied number has changed")
        rid = ctl.stage(plan.files, mode=mode)
        findings = self._check_staged(plan)
        meta_dir = self.data_dir / "projects" / pid / "meta"
        meta_dir.mkdir(parents=True, exist_ok=True)
        (meta_dir / f"{rid}.json").write_text(
            json.dumps({"changes": self._changes(proj, plan), "held": plan.skipped}), encoding="utf-8")
        try:
            ctl.mark_verified(rid, findings)
        except NotReady:
            return {"release_id": rid, "state": "blocked", "findings": findings}
        return {"release_id": rid, "state": "awaiting_approval", "digest": ctl.digest(rid),
                "changes": self._changes(proj, plan), "held": plan.skipped}

    @staticmethod
    def _check_staged(plan: Plan) -> list[str]:
        """Structural verification of the staged bytes: each file must parse and contain the new text."""
        from .project import open_document

        findings: list[str] = []
        for rel, data in plan.files.items():
            try:
                deck = open_document(data, rel)
                text = " ".join(t for s in range(1, len(deck.slide_parts()) + 1) for _, _, t in deck.shapes(s))
                from .match.numbers import parse_numbers

                shown = {n.value for n in parse_numbers(text)} | {float(t) for _, _, t in deck.shapes(1) if _is_plain_number(t)}
                for i in plan.impacts:
                    nv = parse_numbers(i.new_text)
                    if i.deck == rel and i.new_text not in text and not (nv and nv[0].value in shown):
                        findings.append(f"{rel}: new text '{i.new_text}' not found after the edit")
            except Exception as exc:  # noqa: BLE001
                findings.append(f"{rel}: staged file does not open ({type(exc).__name__})")
        return findings

    @_closing
    def approve_and_publish(self, pid: str, release_id: str, digest: str, principal: str = DESKTOP_PRINCIPAL, channel: str = "desktop") -> dict[str, Any]:
        """Called only from the authenticated Desktop route with the digest the human was shown."""
        proj, ctl = self._open(pid)
        manifest, anchor = self._integrity(pid, proj, ctl)
        if ctl.digest(release_id) != digest:
            raise ServiceError("the release changed since it was shown to you; review it again")
        ap = sign(self._key, release_id, digest, principal, channel, time.time() + APPROVAL_TTL_SECONDS, secrets.token_hex(8))
        try:
            ctl.record_approval(release_id, ap)
        except ApprovalError as exc:
            raise ServiceError(f"approval refused: {exc}") from exc
        staged = {c.rel_path: (ctl._staging(release_id) / c.rel_path).read_bytes() for c in ctl._changes(release_id)}
        try:
            ctl.publish(release_id)
        except PermissionError as exc:
            raise ServiceError(f"a file is open in another program ({Path(str(exc.filename or '')).name or 'unknown'}); close it and approve again. Nothing was changed.") from exc
        from .controller.fsio import sha256_bytes

        manifest.append("published", {"release_id": release_id, "digest": digest, "principal": principal,
                                      "files": {rel: sha256_bytes(b) for rel, b in sorted(staged.items())}})
        anchor.write(manifest.counter())
        proj.commit_snapshot(Plan(files=staged))
        return {"release_id": release_id, "state": "published"}

    @_closing
    def release_view(self, pid: str, release_id: str) -> dict[str, Any]:
        """What the owner is shown for one release: its state, its changes, and the digest they approve."""
        import re

        if not re.fullmatch(r"[0-9a-f]{16}", release_id or ""):
            raise ServiceError("not a release id")
        proj, ctl = self._open(pid)
        try:
            steps = [r.step for r in ctl.journal.rows(release_id)]
            digest = ctl.digest(release_id)
        except ReleaseError as exc:
            raise ServiceError("unknown release") from exc
        if "PUBLISHED" in steps:
            state = "published"
        elif "REFUSED_STALE" in steps:
            state = "stale"
        elif "BLOCKED" in steps:
            state = "blocked"
        elif "ROLLED_BACK" in steps:
            state = "rolled_back"
        elif "EXPIRED" in steps:
            state = "expired"
        elif "VERIFIED" in steps:
            state = "awaiting_approval"
        else:
            state = "preparing"
        meta_path = self.data_dir / "projects" / pid / "meta" / f"{release_id}.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {"changes": [], "held": []}
        findings = next((r.detail.get("findings", []) for r in reversed(ctl.journal.rows(release_id)) if r.step == "BLOCKED"), [])
        return {"release_id": release_id, "state": state, "digest": digest, "changes": meta["changes"], "held": meta["held"], "findings": findings}

    def latest_awaiting(self) -> tuple[str, str] | None:
        """The newest release that is waiting for approval, across all projects."""
        best: tuple[float, str, str] | None = None
        for p in self.projects():
            pid = p["project"]
            try:
                proj, ctl = self._open(pid)
                try:
                    for rid in ctl.journal.release_ids():
                        steps = [r.step for r in ctl.journal.rows(rid)]
                        if "VERIFIED" in steps and not any(x in steps for x in ("PUBLISHED", "EXPIRED", "REFUSED_STALE", "BLOCKED", "ROLLED_BACK", "PUBLISHING")):
                            seq = max(r.seq for r in ctl.journal.rows(rid))
                            if best is None or seq > best[0]:
                                best = (seq, pid, rid)
                finally:
                    self._close_opened()
            except ServiceError:
                continue
        return (best[1], best[2]) if best else None

    @_closing
    def recover(self, pid: str) -> dict[str, str]:
        _, ctl = self._open(pid)
        return ctl.recover()
