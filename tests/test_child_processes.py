"""Every program Workroom starts gets an allowlisted environment, and nothing the page shows can send a chat turn by itself."""
import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

from workroom.workroom_core import proof
from workroom.workroom_core.childenv import MINIMAL, OFFICE, child_env

ROOT = Path(__file__).resolve().parents[1]
SHIPPED = [p for p in ROOT.rglob("*.py") if not any(part in ("tests", "bench", "scripts", "__pycache__") for part in p.relative_to(ROOT).parts)]
SECRETS = {"OPENAI_API_KEY": "sk-test-1", "ANTHROPIC_API_KEY": "sk-test-2", "GEMINI_API_KEY": "g-test-3", "HERMES_YOLO_MODE": "1", "HERMES_SESSION_ID": "s-4", "AWS_SECRET_ACCESS_KEY": "aws-5", "GITHUB_TOKEN": "gh-6"}


def test_child_env_never_carries_credentials_or_session_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in SECRETS.items():
        monkeypatch.setenv(k, v)
    for profile in ("minimal", "office"):
        env = child_env(profile)
        assert not set(SECRETS) & {k.upper() for k in env}, f"{profile} profile leaked a secret"
        assert env.get("PATH"), "a child still needs PATH"


def test_a_real_child_cannot_see_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in SECRETS.items():
        monkeypatch.setenv(k, v)
    out = subprocess.run([sys.executable, "-c", "import os,json;print(json.dumps(sorted(os.environ)))"], capture_output=True, text=True, env=child_env("minimal", MARK="x"))
    seen = {k.upper() for k in __import__("json").loads(out.stdout)}
    assert not set(SECRETS) & seen and "MARK" in seen


def test_the_allowlists_name_no_secret_looking_variable() -> None:
    for name in MINIMAL + OFFICE:
        assert not any(w in name.upper() for w in ("KEY", "TOKEN", "SECRET", "PASSWORD", "HERMES")), name


def test_extra_values_must_be_strings() -> None:
    with pytest.raises(TypeError):
        child_env("minimal", N=1)  # type: ignore[arg-type]


def _subprocess_calls(path: Path) -> list[ast.Call]:
    calls = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess" \
                and node.func.attr in {"run", "Popen", "call", "check_call", "check_output"}:
            calls.append(node)
    return calls


def test_every_subprocess_call_in_shipped_code_passes_an_environment() -> None:
    found = 0
    for path in SHIPPED:
        for call in _subprocess_calls(path):
            found += 1
            kw = {k.arg: k.value for k in call.keywords}
            assert "env" in kw, f"{path.relative_to(ROOT)}:{call.lineno} starts a program without an explicit environment"
            assert not (isinstance(kw["env"], ast.Attribute) and kw["env"].attr == "environ"), f"{path.relative_to(ROOT)}:{call.lineno} passes the whole environment"
            assert not any(k.arg == "shell" and getattr(k.value, "value", False) for k in call.keywords), "no shell"
    assert found >= 3, "the guard must actually see the calls it is guarding"


def test_no_shipped_code_bypasses_the_powershell_execution_policy_or_encodes_commands() -> None:
    for path in SHIPPED:
        text = path.read_text(encoding="utf-8").lower()
        assert "executionpolicy" not in text and "-encodedcommand" not in text and "-enc " not in text, path.name


def test_powershell_and_icacls_are_called_by_absolute_path() -> None:
    src = (ROOT / "workroom_core" / "proof.py").read_text(encoding="utf-8") + (ROOT / "workroom_core" / "service.py").read_text(encoding="utf-8")
    assert '["powershell"' not in src and '["icacls"' not in src, "programs must be started by absolute path, not looked up on PATH"


@pytest.mark.skipif(not proof.available(), reason="PowerPoint is not installed")
def test_the_proof_renders_with_the_restricted_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from workroom.tests.test_create_flow import SPEC, _svc

    for k, v in SECRETS.items():
        monkeypatch.setenv(k, v)
    svc, pid, root = _svc(tmp_path)
    made = svc.create_from_spec(pid, SPEC)
    svc.approve_and_publish(pid, made["release_id"], made["digest"])
    images = proof.render_slides(root / "reports/q2.pptx", [1])
    assert images and images[1][:8] == b"\x89PNG\r\n\x1a\n"


def test_the_page_editor_can_only_add_text_to_the_message_box() -> None:
    js = (ROOT / "desktop" / "plugin.js").read_text(encoding="utf-8")
    assert "composer.submit" not in js, "a page message must never send a chat turn as the user"
    assert "composer.insertText" in js
    assert "'block'" in js


def test_every_message_the_page_sends_is_checked_against_its_own_frame() -> None:
    js = (ROOT / "desktop" / "plugin.js").read_text(encoding="utf-8")
    assert "e.source !== w" in js, "messages from any window but the editor frame must be ignored"
