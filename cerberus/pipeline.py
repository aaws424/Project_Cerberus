"""The pipeline: guard → understand → priority → decide → prepare reply → admin queue.

A fixed workflow, not an autonomous agent. At most two LLM calls per ticket (understand, then
draft or manual answer); everything else is code. Every step records a trace entry so the
agent (and the judges) can see why a ticket landed where it did.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import draft, extract, guard, llm, manual, policy, priority, understand
from .queue import AdminQueue
from .schemas import Decision, Priority, Reply, Result, Ticket, TraceStep, Understanding


@dataclass
class RunOptions:
    mode: str = "rules"  # "rules": offline, no API key | "llm": Groq / Gemini / Ollama via llm.py
    providers: list[str] | None = None  # force a provider chain in LLM mode
    as_of: datetime | None = None  # clock for "waiting" points; None = each ticket's own time


def load_jsonl(path: str | Path) -> list[Ticket]:
    with open(path, encoding="utf-8") as f:
        return [Ticket.model_validate(json.loads(line)) for line in f if line.strip()]


def _step(name: str, started: float, detail: dict) -> TraceStep:
    return TraceStep(step=name, ms=round((time.perf_counter() - started) * 1000, 2), detail=detail)


def process(ticket: Ticket, opts: RunOptions, queue: AdminQueue | None = None) -> Result:
    trace: list[TraceStep] = []
    calls, models = 0, []

    # 1. guard + regex pre-extraction (no LLM)
    t0 = time.perf_counter()
    g = guard.scan(ticket.text)
    ex = extract.extract_all(g.clean_text, ticket.created_at)
    duplicate_of = queue.find_duplicate(ticket) if queue else None
    trace.append(_step("guard", t0, {**g.summary(), "pre_extracted": ex.summary(), "duplicate_of": duplicate_of}))
    if duplicate_of:
        u = Understanding(language=g.language, summary=f"Duplicate of {duplicate_of}", notes=["linked, not reprocessed"])
        return Result(ticket=ticket, understanding=u, priority=Priority(score=0, band="P3", breakdown=[]),
                      decision=Decision(lane="duplicate", team="supervisor", detail=duplicate_of),
                      duplicate_of=duplicate_of, trace=trace)

    # 2. understand
    t0 = time.perf_counter()
    conflicts: list[str] = []
    llm_error: str | None = None
    if opts.mode == "llm":
        try:
            u, conflicts, meta = understand.understand_llm(ticket, g, ex, providers=opts.providers)
            calls, models = calls + (0 if meta.cached else 1), models + [meta.label]
        except llm.LLMError as e:
            llm_error = str(e)[:300]
            u = understand.understand_rules(ticket, g, ex)
            u.notes.insert(0, "LLM failed: keyword rules shown as a hint only")
    else:
        u = understand.understand_rules(ticket, g, ex)
    # The guard's own hits are ORed in, so the model does not get the last word on safety flags.
    u.flags.human_requested |= bool(g.human_hits)
    u.flags.injection |= bool(g.injection_hits)
    u.flags.fraud |= bool(g.fraud_hits)
    u.flags.legal_threat |= bool(g.legal_hits)
    u.flags.abusive |= bool(g.abuse_hits)
    u.flags.repeat_contact |= bool(g.repeat_hits)
    earlier = queue.recent_contacts(ticket) if queue else []
    if earlier:
        u.flags.repeat_contact = True
        u.notes.append(f"same customer wrote in the last 7 days: {', '.join(earlier)}")
    trace.append(_step("understand", t0, {
        "source": u.source, "intent": u.intent, "category": u.category, "confidence": u.confidence,
        "secondary": u.secondary_category, "facts": u.facts.model_dump(mode="json", exclude={"source"}),
        "flags": u.flags.model_dump(), "conflicts": conflicts, "notes": u.notes, "llm_error": llm_error,
    }))

    # 3. priority score
    t0 = time.perf_counter()
    pri = priority.score(u, ticket, as_of=opts.as_of)
    trace.append(_step("priority", t0, {"score": pri.score, "band": pri.band, "breakdown": pri.breakdown}))

    # 4. decide
    t0 = time.perf_counter()
    decision = policy.decide(u, pri, mode=opts.mode, conflicts=conflicts, llm_error=llm_error)
    trace.append(_step("decide", t0, decision.model_dump()))

    # 5. prepare a reply (only for tickets that are not already going to a human)
    t0 = time.perf_counter()
    reply = Reply()
    detail: dict = {"skipped": "ticket goes to a human; no AI reply prepared"}
    if decision.lane == "ready":
        if u.category == "how_to_question":
            reply, detail = manual.answer(ticket, u, g.clean_text, opts.mode, opts.providers)
            if reply.kind == "none":
                decision = policy.needs_you(decision, "manual_gap")
            else:
                allowed = draft.allowed_numbers(g.clean_text, u.facts, manual.section_text(reply.cited_sections))
                if issues := draft.validate(reply.text or "", allowed):
                    reply = Reply(kind="manual_answer", source=reply.source, issues=issues, rejected_text=reply.text,
                                  cited_sections=reply.cited_sections)
        else:
            reply, detail = draft.make(ticket, u, g.clean_text, opts.mode, opts.providers)
        if reply.issues:
            decision = policy.needs_you(decision, "validator_failed", "; ".join(reply.issues))
        if reply.source.startswith("llm:"):
            calls, models = calls + 1, models + [reply.source[4:]]
    trace.append(_step("prepare_reply", t0, {**detail, "kind": reply.kind, "cited": reply.cited_sections,
                                             "final_lane": decision.lane, "final_reason": decision.reason_code}))

    return Result(ticket=ticket, understanding=u, priority=pri, decision=decision, reply=reply,
                  trace=trace, llm_calls=calls, llm_models=models)


def run_batch(tickets: list[Ticket], opts: RunOptions, queue: AdminQueue, run_id: str | None = None,
              progress=None) -> tuple[list[Result], dict]:
    """Process tickets oldest first (so history-based checks work) and add them to the queue."""
    from . import report

    run_id = run_id or datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    started = time.perf_counter()
    results = []
    ordered = sorted(tickets, key=lambda t: t.created_at)
    for i, ticket in enumerate(ordered, 1):
        result = process(ticket, opts, queue)
        queue.add(result, run_id)
        results.append(result)
        if progress:
            progress(i, len(ordered), result)
    summary = report.summarize(results, run_id=run_id, mode=opts.mode, seconds=time.perf_counter() - started,
                               as_of=opts.as_of, queue=queue)
    queue.save_run(run_id, summary)
    return results, summary
