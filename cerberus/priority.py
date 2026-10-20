"""Step 3, priority: arithmetic on extracted facts (config/priority.yaml), never the model's opinion."""

from __future__ import annotations

from datetime import datetime, time

from .config import categories, load
from .schemas import Facts, Priority, Ticket, Understanding


def amount_in_iqd(facts: Facts) -> float:
    if not facts.amount:
        return 0.0
    if (facts.currency or "IQD").upper() == "USD":
        return facts.amount * load("priority")["usd_to_iqd"]
    return facts.amount


def hours_since_incident(u: Understanding, ticket: Ticket) -> float | None:
    if not u.facts.incident_date:
        return None
    start = datetime.combine(u.facts.incident_date, time.min, tzinfo=ticket.created_at.tzinfo)
    return max(0.0, (ticket.created_at - start).total_seconds() / 3600)


def score(u: Understanding, ticket: Ticket, as_of: datetime | None = None) -> Priority:
    cfg = load("priority")
    spec = categories().get(u.category, {})
    items: list[tuple[str, int]] = [(f"category:{u.category}", int(spec.get("base_points", 0)))]

    iqd = amount_in_iqd(u.facts)
    for row in cfg["amount_points"]:
        if iqd >= row["min"]:
            items.append(("amount", row["points"]))
            break

    hours = hours_since_incident(u, ticket)
    if hours is not None and spec.get("money_at_stake"):
        for row in cfg["money_stuck_points"]:
            if hours >= row["min_hours"]:
                items.append(("money_stuck", row["points"]))
                break
        rev = cfg["still_reversible"]
        if u.category in rev["categories"] and hours < rev["max_hours"]:
            items.append(("still_reversible", rev["points"]))

    fp = cfg["flag_points"]
    if u.flags.fraud:
        items.append(("fraud", fp["fraud"]))
    if u.flags.human_requested:
        items.append(("asked_for_human", fp["human_requested"]))
    if u.flags.repeat_contact:
        items.append(("repeat_contact", fp["repeat_contact"]))
    if u.flags.legal_threat or u.flags.abusive:
        items.append(("legal_or_abuse", fp["legal_or_abuse"]))

    if as_of is not None:
        waited = (as_of - ticket.created_at).total_seconds() / 3600
        points = min(cfg["waiting"]["max_points"], int(waited * cfg["waiting"]["points_per_hour"]))
        if points > 0:
            items.append(("waiting", points))

    total = sum(p for _, p in items)
    bands = cfg["bands"]
    band = "P1" if total >= bands["P1"] else "P2" if total >= bands["P2"] else "P3"
    if any(getattr(u.flags, flag) for flag in cfg.get("force_p1_flags", [])):
        band = "P1"
    return Priority(score=total, band=band, breakdown=[i for i in items if i[1]])
