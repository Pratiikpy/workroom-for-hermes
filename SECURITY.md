# Security policy

## Reporting a problem

Please report a suspected vulnerability privately, through a GitHub security advisory on this repository ("Report a vulnerability" under the Security tab). Do not open a public issue for it. Include the Workroom and Hermes versions, what you did, and what happened. You will get an acknowledgement and an assessment; fixes are listed in the changelog without exploit details.

## What Workroom promises, and where it stops

- **No Workroom tool approves or publishes a release.** Only the owner can, in an authenticated Hermes Desktop session or in an approved chat. Approval is bound to the exact files and changes shown, expires, and works once.
- **Workroom reads and writes only inside the folders registered as projects**, plus its own storage. Output paths are validated; child processes get an allowlisted environment.
- **Releases are journaled and recoverable.** A crash at any step recovers; a backup of every replaced file is kept; a restore refuses when the files changed since.

What it does not promise: it cannot stop another program, or an agent that is also given a general shell or file-write tool, from changing a file directly, because those run with your own operating-system permissions. Workroom blocks the common ways and asks you first, but that is a heuristic, not isolation. The signing key is readable by any process running as you. A rollback of every copy of Workroom's state to an older valid point is not detected. The full list is in [docs/LIMITS.md](docs/LIMITS.md).

## For agent operators

Give checking agents the read-only toolset `workroom_ro` and no shell. Do not run Hermes in an auto-approve mode if you rely on Workroom's approval prompt: in that mode the prompt answers itself.

## Supported versions

Only the latest release receives fixes.
