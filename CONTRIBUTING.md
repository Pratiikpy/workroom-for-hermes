# Contributing

Thank you for looking. Workroom is a Hermes plugin that keeps reports and decks in step with their source numbers. Contributions that make a claim more true, more tested or clearer are welcome.

## Run it

```
pip install -r requirements-dev.txt
python -m pytest tests -q
```

The suite runs on Windows, macOS and Linux. Tests that need Microsoft Office, a Chromium-based browser or network access skip where those are missing.

To check the plugin the way the Nous catalog does: `hermes plugins validate workroom --install-deps` (Hermes 0.23.0 or later).

## Ground rules

- **Every claim needs evidence.** If you change behaviour, add a test that fails without the change, and a dated row in [`bench/EVIDENCE.md`](bench/EVIDENCE.md) saying what was measured and what was not.
- **Say what is not verified.** The README and the docs list limits on purpose; do not remove one without evidence.
- **Nothing may write to a user's file outside an approved release.** Discovery, planning, previews and checks are read-only.
- **No secrets, personal paths or private documents** in commits, tests or fixtures. Public test files are described in `NOTICE.md`.
- **Keep the wording consistent.** Use the terms in [`docs/GLOSSARY.md`](docs/GLOSSARY.md).
- Desktop code stays inside the Hermes Desktop SDK: no `eval`, no dynamic `import()`, no querying of the host's markup.

## Pull requests

Describe the problem, the change, the evidence, and what you did not test. Keep one concern per pull request.
