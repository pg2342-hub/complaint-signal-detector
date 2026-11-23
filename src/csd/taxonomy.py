"""Failure modes for one product, and the phrases that identify each one.

The same phrase list drives two things, so they can never drift apart:
- the openFDA search that counts every report in a mode, server-side, by month
- the local rules tagger that labels one narrative (used in the eval and as a guardrail)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Mode:
    id: str
    label: str
    description: str
    phrases: list[str]
    safety: bool = False  # a patient could miss a low or high, or be hurt
    _patterns: list[re.Pattern] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._patterns = [re.compile(phrase_regex(p), re.I) for p in self.phrases]

    def first_match(self, text: str) -> tuple[int, str] | None:
        """Earliest position where any phrase of this mode appears, and the matched text."""
        best = None
        for pat in self._patterns:
            m = pat.search(text)
            if m and (best is None or m.start() < best[0]):
                best = (m.start(), m.group(0))
        return best

    def openfda_query(self) -> str:
        """openFDA search clause, e.g. mdr_text.text:("signal loss occurred" OR "pairing issue occurred")."""
        quoted = " OR ".join(f'"{p}"' for p in self.phrases)
        return f"mdr_text.text:({quoted})"


def phrase_regex(phrase: str) -> str:
    """Match a phrase the way openFDA's phrase search does: case-insensitive, punctuation and spacing ignored."""
    words = re.findall(r"[a-z0-9]+", phrase.lower())
    return r"\b" + r"[^a-z0-9]+".join(re.escape(w) for w in words) + r"\b"


@dataclass
class Product:
    name: str
    search: str  # openFDA search clause selecting the product's reports
    modes: list[Mode]
    events: list[dict]
    detection: dict

    @property
    def mode_ids(self) -> list[str]:
        return [m.id for m in self.modes]

    def mode(self, mode_id: str) -> Mode:
        for m in self.modes:
            if m.id == mode_id:
                return m
        raise KeyError(mode_id)


OTHER = "other"
NEEDS_REVIEW = "needs_review"


def load_product(path: str | Path) -> Product:
    cfg = yaml.safe_load(Path(path).read_text())
    modes = [Mode(**m) for m in cfg["modes"]]
    return Product(
        name=cfg["name"],
        search=cfg["search"],
        modes=modes,
        events=cfg.get("events", []),
        detection=cfg.get("detection", {}),
    )
