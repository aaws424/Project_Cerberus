"""The run report: what the batch did, where tickets went, what was escalated and why."""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from .config import categories, load, teams
from .queue import AdminQueue
from .schemas import Result


def summarize(results: list[Result], *, run_id: str, mode: str, seconds: float,
              as_of: datetime | None, queue: AdminQueue) -> dict:
    work = [r for r in results if r.decision.lane != "duplicate"]
    pending_times = [r.ticket.created_at for r in work]
    clock = as_of or (max(pending_times) if pending_times else None)
    oldest_hours = round((clock - min(pending_times)).total_seconds() / 3600, 1) if pending_times and clock else 0
    return {
        "run_id": run_id,
        "mode": mode,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "as_of": clock.isoformat() if clock else None,
        "processed": len(results),
        "ready": sum(r.decision.lane == "ready" for r in results),
        "needs_you": sum(r.decision.lane == "needs_you" for r in results),
        "duplicates": sum(r.decision.lane == "duplicate" for r in results),
        "reasons": dict(Counter(r.decision.reason_code for r in results if r.decision.lane == "needs_you").most_common()),
        "teams": dict(Counter(r.decision.team for r in work).most_common()),
        "bands": {b: sum(r.priority.band == b for r in work) for b in ("P1", "P2", "P3")},
        "categories": dict(Counter(r.understanding.category for r in work).most_common()),
        "oldest_open_hours": oldest_hours,
        "llm_calls": sum(r.llm_calls for r in results),
        "models": dict(Counter(m for r in results for m in r.llm_models).most_common()),
        "seconds": round(seconds, 2),
        "tickets_per_minute": round(len(results) / seconds * 60, 1) if seconds > 0 else None,
        "sent_without_approval": queue.sent_without_approval(),
    }


def to_markdown(s: dict) -> str:
    reasons = load("policy")["reasons"]
    cats, tms = categories(), teams()
    lines = [
        f"# Run report `{s['run_id']}`",
        "",
        f"- Mode: **{s['mode']}**" + (f" · models: {', '.join(s['models'])}" if s["models"] else " · no LLM calls"),
        f"- Queue as of: {s['as_of']}",
        f"- Processed **{s['processed']}** tickets in {s['seconds']} s ({s['tickets_per_minute']} tickets/min), "
        f"{s['llm_calls']} LLM calls",
        f"- **Ready to approve: {s['ready']}** · **Needs you: {s['needs_you']}** · duplicates linked: {s['duplicates']}",
        f"- Priority: P1 {s['bands']['P1']} · P2 {s['bands']['P2']} · P3 {s['bands']['P3']} · oldest open ticket {s['oldest_open_hours']} h",
        f"- **Sent without approval: {s['sent_without_approval']}** (must always be 0)",
        "",
        "## Why tickets went to a human",
        "",
        "| Reason | Tickets |",
        "|---|---|",
        *[f"| {reasons[k]['en']} | {v} |" for k, v in s["reasons"].items()],
        "",
        "## Per team",
        "",
        "| Team | Tickets |",
        "|---|---|",
        *[f"| {tms.get(k, {}).get('en', k)} | {v} |" for k, v in s["teams"].items()],
        "",
        "## Per category",
        "",
        "| Category | Tickets |",
        "|---|---|",
        *[f"| {cats.get(k, {}).get('en', k)} | {v} |" for k, v in s["categories"].items()],
    ]
    return "\n".join(lines) + "\n"
