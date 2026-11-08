"""What a change means for the words around a number: findings the owner must see before approving.

A finding is evidence, not a verdict on the document: it says what the sentence claims, what was true before the update, what is
true after it, and which numbers say so. Severity is fixed by the kind of evidence, never by tone:

  high    a claim that was true and is now false on the sentence's own figures, or on a series the workbook states exactly
  medium  a claim that depends on a baseline the sentence does not name, where every plausible baseline now disagrees
  info    a claim that was already false, a claim that has become true, and anything the check could not read
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

SEVERITIES = ("high", "medium", "info")


@dataclass(frozen=True)
class Finding:
    id: str
    kind: str
    severity: str
    deck: str
    slide: int
    sentence_before: str
    sentence_after: str
    summary: str
    evidence: tuple[str, ...] = ()
    suggestion: str = ""
    where: str = ""

    def view(self) -> dict[str, Any]:
        return {**asdict(self), "evidence": list(self.evidence)}


_FLIP = {"up": "down", "down": "up", "higher": "lower", "lower": "higher", "increase": "decrease", "increased": "decreased", "decrease": "increase", "decreased": "increased",
         "rose": "fell", "fell": "rose", "grew": "declined", "declined": "grew", "above": "below", "below": "above", "exceeded": "fell short of", "beat": "missed", "missed": "beat",
         "record": "", "highest": "", "lowest": ""}


def opposite_word(word: str) -> str:
    """The word that states the opposite direction, when there is exactly one (\"up\" becomes \"down\"); empty when it depends on the sentence."""
    return _FLIP.get(word.lower(), "")


def mask_digits(text: str) -> str:
    return re.sub(r"\d", "#", text)


def sort_findings(items: list[Finding]) -> list[Finding]:
    order = {s: i for i, s in enumerate(SEVERITIES)}
    return sorted(items, key=lambda f: (order.get(f.severity, 9), f.deck, f.slide, f.sentence_before))
