"""Keyword rules: the offline "rules" mode, and the keyword baseline the LLM has to beat.

Each category in config/categories.yaml has weighted phrases. A ticket's score for a category
is the sum of the weights of the phrases it contains. Confidence comes from how far the best
category is ahead of the runner-up, scaled down when the evidence is thin.
"""

from __future__ import annotations

import re
from functools import lru_cache

from .config import categories, load
from .textnorm import clean, fold


def _matcher(phrase: str) -> re.Pattern:
    folded = re.escape(fold(clean(phrase)))
    if phrase.isascii():
        return re.compile(r"(?<![a-z0-9])" + folded + r"(?![a-z0-9])")
    return re.compile(folded)


@lru_cache(maxsize=1)
def _keywords() -> dict[str, list[tuple[str, re.Pattern, float]]]:
    return {
        cat: [(k, _matcher(k), float(w)) for k, w in (spec.get("keywords") or {}).items()]
        for cat, spec in categories().items()
    }


@lru_cache(maxsize=1)
def _how_to() -> tuple[list[re.Pattern], list[re.Pattern], float]:
    cfg = load("categories")["how_to_boost"]
    return [_matcher(c) for c in cfg["cues"]], [_matcher(c) for c in cfg["complaint_cues"]], float(cfg["points"])


def score_categories(folded: str) -> tuple[dict[str, float], dict[str, list[str]]]:
    scores: dict[str, float] = {}
    matched: dict[str, list[str]] = {}
    for cat, keywords in _keywords().items():
        hits = [(k, w) for k, rx, w in keywords if rx.search(folded)]
        if hits:
            scores[cat] = sum(w for _, w in hits)
            matched[cat] = [k for k, _ in hits]
    cues, complaints, points = _how_to()
    if any(rx.search(folded) for rx in cues) and not any(rx.search(folded) for rx in complaints):
        scores["how_to_question"] = scores.get("how_to_question", 0.0) + points
        matched.setdefault("how_to_question", []).append("(question with no complaint)")
    return scores, matched


def classify(folded: str) -> dict:
    """Return {category, confidence, secondary, scores, matched}."""
    scores, matched = score_categories(folded)
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    if not ranked:
        return {"category": "unclear", "confidence": 0.0, "secondary": None, "scores": {}, "matched": {}}
    best, s1 = ranked[0]
    s2 = ranked[1][1] if len(ranked) > 1 else 0.0
    margin = (s1 - s2) / (s1 + s2 + 0.5)
    strength = min(1.0, s1 / 3) ** 0.5
    confidence = round(min(0.95, (0.5 + 0.5 * margin) * strength), 2)
    multi = load("policy")["multi_issue"]
    secondary = None
    if len(ranked) > 1 and s2 >= multi["min_points"] and s2 >= multi["ratio"] * s1:
        secondary = ranked[1][0]
    return {"category": best, "confidence": confidence, "secondary": secondary,
            "scores": {k: round(v, 1) for k, v in ranked}, "matched": matched}
