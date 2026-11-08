"""The environment a child process receives: a short allowlist, never a copy of this process's environment.

Hermes loads provider keys and session flags into its own environment. A program Workroom starts has no use for them, so they
are not passed on. Callers add the few variables a child needs by name."""

from __future__ import annotations

import os

MINIMAL = ("PATH", "TEMP", "TMP", "HOME", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "SYSTEMROOT", "LANG", "LC_ALL")

# what Windows PowerShell and PowerPoint need to start and to open a file; none of it is a credential
OFFICE = MINIMAL + (
    "WINDIR", "SYSTEMDRIVE", "COMSPEC", "PATHEXT", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432",
    "COMMONPROGRAMFILES", "COMMONPROGRAMFILES(X86)", "COMMONPROGRAMW6432", "ALLUSERSPROFILE", "PUBLIC", "COMPUTERNAME",
    "USERNAME", "USERDOMAIN", "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS", "OS", "PSMODULEPATH",
)

_PROFILES = {"minimal": MINIMAL, "office": OFFICE}


def child_env(profile: str = "minimal", **extra: str) -> dict[str, str]:
    """An allowlisted environment for subprocess.run(env=...). Names given in `extra` are added after the allowlist."""
    names = _PROFILES[profile]
    out = {k: v for k, v in os.environ.items() if k.upper() in names}
    for key, value in extra.items():
        if not isinstance(value, str):
            raise TypeError(f"environment value for {key} must be a string")
        out[key] = value
    return out
