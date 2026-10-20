"""Step 1, guard: pure-Python checks that run before any model sees the ticket.

- clean and fold the text, cap its length
- detect the language (Iraqi Arabic, English, Arabizi, Kurdish)
- scan for prompt-injection patterns
- scan for "I want a human", fraud, legal-threat, abuse and repeat-contact phrases

These hits are independent of the LLM: the policy ORs them with the model's own flags, so a
model that misses an injection or a request for a human does not get the last word.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from .config import load
from .textnorm import clean, fold


@dataclass
class GuardReport:
    clean_text: str
    folded: str
    language: str
    truncated: bool = False
    injection_hits: list[str] = field(default_factory=list)
    human_hits: list[str] = field(default_factory=list)
    fraud_hits: list[str] = field(default_factory=list)
    legal_hits: list[str] = field(default_factory=list)
    abuse_hits: list[str] = field(default_factory=list)
    repeat_hits: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "language": self.language,
            "truncated": self.truncated,
            "injection": self.injection_hits,
            "asks_for_human": self.human_hits,
            "fraud": self.fraud_hits,
            "legal": self.legal_hits,
            "abuse": self.abuse_hits,
            "repeat": self.repeat_hits,
        }


def _matcher(phrase: str) -> re.Pattern:
    folded = re.escape(fold(clean(phrase)))
    if phrase.isascii():  # whole words only for Latin phrases ("fee" must not match "feel")
        return re.compile(r"(?<![a-z0-9])" + folded + r"(?![a-z0-9])")
    return re.compile(folded)  # Arabic: prefixes like و/ب/ال attach to words, so match substrings


@lru_cache(maxsize=None)
def _phrases(name: str) -> list[tuple[str, re.Pattern]]:
    return [(p, _matcher(p)) for p in load("guard")[name]]


@lru_cache(maxsize=1)
def _injection() -> list[re.Pattern]:
    return [re.compile(p) for p in load("guard")["injection_patterns"]]


def _hits(folded: str, name: str) -> list[str]:
    return [phrase for phrase, rx in _phrases(name) if rx.search(folded)]


def detect_language(text: str) -> str:
    cfg = load("guard")
    if sum(text.count(ch) for ch in cfg["kurdish_letters"]) >= 2:
        return "ku"
    arabic = len(re.findall(r"[؀-ۿ]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if arabic == 0 and latin == 0:
        return "unknown"
    if arabic >= 0.6 * (arabic + latin):
        return "ar"
    if latin >= 0.6 * (arabic + latin):
        words = set(re.findall(r"[a-z0-9]+", text.lower()))
        if words & set(cfg["arabizi_words"]) or re.search(r"[a-z][2375][a-z]|(?<![a-z0-9])[2375][a-z]", text.lower()):
            return "arabizi"
        return "en"
    return "mixed"


def scan(text: str) -> GuardReport:
    cfg = load("guard")
    cleaned = clean(text)
    truncated = len(cleaned) > cfg["max_chars"]
    cleaned = cleaned[: cfg["max_chars"]]
    folded = fold(cleaned)
    return GuardReport(
        clean_text=cleaned,
        folded=folded,
        language=detect_language(cleaned),
        truncated=truncated,
        injection_hits=[rx.pattern for rx in _injection() if rx.search(folded)],
        human_hits=_hits(folded, "human_request_phrases"),
        fraud_hits=_hits(folded, "fraud_phrases"),
        legal_hits=_hits(folded, "legal_phrases"),
        abuse_hits=_hits(folded, "abuse_phrases"),
        repeat_hits=_hits(folded, "repeat_phrases"),
    )
