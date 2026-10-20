"""Step 2, understand: category, confidence, extracted facts and flags.

Two implementations with the same output (an Understanding):

- understand_rules(): keyword rules + regex extraction. Works offline with no API key, and is
  the keyword baseline the LLM is measured against.
- understand_llm(): one LLM call with a strict JSON contract and no tools. The ticket is wrapped
  in tags with a secret per-ticket nonce and treated as data; every extracted value must quote
  the ticket, and is cross-checked against the regex extraction.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import date

from . import heuristics, llm
from .config import CACHE_DIR, categories, prompt
from .extract import Extracted
from .guard import GuardReport
from .schemas import Facts, Flags, Ticket, Understanding
from .textnorm import digits_only, fold

FIELDS = ("amount", "transaction_ref", "incident_date", "phone", "agent", "feature_asked")


def facts_from_extract(ex: Extracted) -> Facts:
    facts = Facts()
    if (a := ex.first("amounts")) is not None:
        facts.amount, facts.currency = float(a.value), a.currency
        facts.evidence["amount"] = a.quote
    if (r := ex.first("refs")) is not None:
        facts.transaction_ref = str(r.value)
        facts.evidence["transaction_ref"] = r.quote
    if (d := ex.first("dates")) is not None:
        facts.incident_date = d.value
        facts.evidence["incident_date"] = d.quote
    if (p := ex.phones[-1] if ex.phones else None) is not None:  # the last number is usually the recipient
        facts.phone = str(p.value)
        facts.evidence["phone"] = p.quote
    if (g := ex.first("agents")) is not None:
        facts.agent = str(g.value)
        facts.evidence["agent"] = g.quote
    facts.source = {k: "regex" for k in facts.evidence}
    return facts


def flags_from_guard(g: GuardReport) -> Flags:
    return Flags(
        human_requested=bool(g.human_hits),
        fraud=bool(g.fraud_hits),
        legal_threat=bool(g.legal_hits),
        abusive=bool(g.abuse_hits),
        repeat_contact=bool(g.repeat_hits),
        injection=bool(g.injection_hits),
    )


def understand_rules(ticket: Ticket, g: GuardReport, ex: Extracted) -> Understanding:
    c = heuristics.classify(g.folded)
    category = c["category"]
    flags = flags_from_guard(g)
    if category == "how_to_question":
        intent = "how_to"
    elif flags.human_requested and category == "unclear":
        intent = "human_request"
    else:
        intent = "issue"
    top = c["matched"].get(category, [])
    return Understanding(
        intent=intent,
        category=category,
        confidence=c["confidence"],
        secondary_category=c["secondary"],
        language=g.language,
        facts=facts_from_extract(ex),
        flags=flags,
        summary=f"{categories()[category]['en']}" + (f" (keywords: {', '.join(top[:4])})" if top else ""),
        source="rules",
        notes=[f"keyword scores: {c['scores']}"] if c["scores"] else ["no category keywords found"],
    )


# --- LLM ----------------------------------------------------------------------------------------

def _salt() -> bytes:
    """A per-install secret, so ticket authors cannot predict the nonce or canary."""
    path = CACHE_DIR / "salt"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_hex(16), encoding="utf-8")
    return path.read_text(encoding="utf-8").strip().encode()


def _secret(ticket: Ticket, kind: str, n: int) -> str:
    return hmac.new(_salt(), f"{kind}:{ticket.id}:{ticket.text}".encode("utf-8"), hashlib.sha256).hexdigest()[:n]


def _category_list() -> str:
    return "\n".join(f"- {cid}: {spec['description']}" for cid, spec in categories().items())


def _grounded(value, quote: str | None, folded_ticket: str) -> bool:
    """A value counts only if its quote is really in the ticket (or its digits are)."""
    if quote and fold(quote).strip() and fold(quote).strip() in folded_ticket:
        return True
    digits = digits_only(str(value))
    return bool(digits) and len(digits) >= 5 and digits in digits_only(folded_ticket)


def understand_llm(
    ticket: Ticket, g: GuardReport, ex: Extracted, providers: list[str] | None = None
) -> tuple[Understanding, list[str], llm.CallMeta]:
    """Return (understanding, conflicts, call metadata). Raises llm.LLMError if no provider answers."""
    nonce = _secret(ticket, "nonce", 10)
    canary = "CNRY-" + _secret(ticket, "canary", 12)
    system = prompt("understand", CATEGORIES=_category_list(), CANARY=canary, NONCE=nonce)
    created = ticket.created_at
    user = (
        f"Ticket id: {ticket.id}\nChannel: {ticket.channel}\n"
        f"Created at (Iraq time): {created:%Y-%m-%d %H:%M} ({created:%A})\n\n"
        f"<ticket_{nonce}>\n{g.clean_text}\n</ticket_{nonce}>"
    )
    raw, meta = llm.chat_json([{"role": "system", "content": system}, {"role": "user", "content": user}], job="understand", providers=providers)

    notes: list[str] = []
    conflicts: list[str] = []
    cats = categories()
    category = raw.get("category") if raw.get("category") in cats else "unclear"
    if category != raw.get("category"):
        notes.append(f"model returned unknown category {raw.get('category')!r}")
    try:
        confidence = max(0.0, min(1.0, float(raw.get("confidence", 0))))
    except (TypeError, ValueError):
        confidence = 0.0
    secondary = raw.get("secondary_category") if raw.get("secondary_category") in cats else None
    intent = raw.get("intent") if raw.get("intent") in ("issue", "how_to", "human_request") else "issue"

    facts = Facts()
    fields = raw.get("fields") or {}
    for name in FIELDS:
        item = fields.get(name) or {}
        value, quote = item.get("value"), item.get("quote")
        if value in (None, "", []):
            continue
        if name != "feature_asked" and not _grounded(value, quote, g.folded):
            notes.append(f"{name}: quote not found in the ticket, value dropped")
            continue
        try:
            if name == "amount":
                facts.amount = float(str(value).replace(",", ""))
                facts.currency = (item.get("currency") or "IQD").upper()
            elif name == "incident_date":
                facts.incident_date = date.fromisoformat(str(value)[:10])
            else:
                setattr(facts, name, str(value))
        except ValueError:
            notes.append(f"{name}: could not parse {value!r}")
            continue
        facts.evidence[name] = quote or str(value)
        facts.source[name] = "llm"

    # Cross-check the model against the regex extraction; fill gaps from regex.
    regex = facts_from_extract(ex)
    if facts.transaction_ref and regex.transaction_ref and digits_only(facts.transaction_ref) != digits_only(regex.transaction_ref):
        conflicts.append(f"transaction_ref: model {facts.transaction_ref} vs regex {regex.transaction_ref}")
    if facts.amount and regex.amount and facts.currency == regex.currency and abs(facts.amount - regex.amount) > 0.01 * regex.amount:
        conflicts.append(f"amount: model {facts.amount:,.0f} vs regex {regex.amount:,.0f}")
    for name in ("amount", "transaction_ref", "incident_date", "phone", "agent"):
        if getattr(facts, name) is None and getattr(regex, name) is not None:
            setattr(facts, name, getattr(regex, name))
            if name == "amount":
                facts.currency = regex.currency
            facts.evidence[name] = regex.evidence[name]
            facts.source[name] = "regex"

    rf = raw.get("flags") or {}
    flags = Flags(
        human_requested=bool(rf.get("human_requested")),
        fraud=bool(rf.get("fraud")),
        legal_threat=bool(rf.get("legal_threat")),
        abusive=bool(rf.get("abusive")),
        repeat_contact=bool(rf.get("repeat_contact")),
        injection=bool(rf.get("instruction_like_text")),
    )
    if canary in json.dumps(raw, ensure_ascii=False):
        flags.injection = True
        notes.append("canary token leaked into the model output")

    u = Understanding(
        intent=intent,
        category=category,
        confidence=round(confidence, 2),
        secondary_category=secondary,
        language=str(raw.get("language") or g.language),
        facts=facts,
        flags=flags,
        summary=str(raw.get("summary") or "")[:300],
        source=f"llm:{meta.label}",
        notes=notes,
    )
    return u, conflicts, meta
