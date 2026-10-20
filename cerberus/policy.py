"""Step 4, decide: "Ready to approve" or "Needs you", in a fixed order where the first match wins.

Rule 1 is "the customer asked for a human": it beats everything, including a 0.99-confidence
routine case. Every "Needs you" ticket carries a one-line reason in Arabic and English.
"""

from __future__ import annotations

from .config import categories, load
from .schemas import Decision, Priority, Understanding


def _team(u: Understanding) -> str:
    return categories().get(u.category, {}).get("team", "supervisor")


def needs_you(decision_or_team: Decision | str, code: str, detail: str | None = None) -> Decision:
    reason = load("policy")["reasons"][code]
    team = decision_or_team.team if isinstance(decision_or_team, Decision) else decision_or_team
    return Decision(lane="needs_you", team=team, reason_code=code, reason_ar=reason["ar"], reason_en=reason["en"], detail=detail)


def decide(
    u: Understanding,
    pri: Priority,
    *,
    mode: str,
    conflicts: list[str] | None = None,
    llm_error: str | None = None,
) -> Decision:
    cfg = load("policy")
    threshold = cfg["confidence_threshold"]["llm" if mode == "llm" else "rules"]
    missing_ref = cfg["missing_reference"]
    checks = {
        "human_requested": (u.flags.human_requested or u.intent == "human_request", None),
        "suspected_injection": (u.flags.injection, None),
        "sensitive": (
            u.flags.fraud or u.flags.legal_threat or u.flags.abusive,
            ", ".join(k for k in ("fraud", "legal_threat", "abusive") if getattr(u.flags, k)),
        ),
        "llm_error": (llm_error is not None, llm_error),
        "unsupported_language": (u.language in cfg["unsupported_languages"], u.language),
        "unclear": (u.category == "unclear", None),
        "low_confidence": (u.confidence < threshold, f"{u.confidence:.2f} < {threshold:.2f}"),
        "multi_issue": (u.secondary_category is not None, f"{u.category} + {u.secondary_category}"),
        "extraction_conflict": (bool(conflicts), "; ".join(conflicts or [])),
        "missing_reference": (
            u.category in missing_ref["categories"] and pri.band in missing_ref["bands"] and not u.facts.transaction_ref,
            None,
        ),
    }
    for code in cfg["order"]:
        hit, detail = checks[code]
        if hit:
            return needs_you(_team(u), code, detail)
    return Decision(lane="ready", team=_team(u))
