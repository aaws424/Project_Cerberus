"""Evaluation on a labeled split: classification, lanes, priority, extraction, safety flags, how-to.

Gold priority is the same priority formula applied to the gold facts, so the priority metric
measures whether wrong or missing facts pushed a ticket into the wrong band.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date

from . import priority
from .config import categories
from .schemas import Facts, Flags, Result, Understanding
from .textnorm import digits_only, fold

FIELDS = ("amount", "transaction_ref", "incident_date", "phone", "agent")
FLAGS = ("human_requested", "injection", "fraud", "legal_threat", "repeat_contact")


def gold_understanding(label: dict) -> Understanding:
    f = dict(label.get("fields") or {})
    if f.get("incident_date"):
        f["incident_date"] = date.fromisoformat(f["incident_date"])
    return Understanding(category=label["category"], confidence=1.0, facts=Facts(**f),
                         flags=Flags(**(label.get("flags") or {})))


def _same(field: str, gold, pred) -> bool:
    if field == "amount":
        return abs(float(gold) - float(pred)) < 0.5
    if field in ("transaction_ref", "phone"):
        return digits_only(str(gold)) == digits_only(str(pred))
    if field == "agent":
        return fold(str(gold)).strip() == fold(str(pred)).strip()
    return str(gold) == str(pred)


def _prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f1 = 2 * p * r / (p + r) if p and r else (0.0 if p is not None and r is not None else None)
    return {"precision": p, "recall": r, "f1": f1, "tp": tp, "fp": fp, "fn": fn}


def evaluate(results: list[Result]) -> dict:
    labeled = [r for r in results if r.ticket.label]
    work = [r for r in labeled if r.ticket.label.get("expected_lane") != "duplicate"]
    misses: list[dict] = []

    def miss(r: Result, what: str, gold, pred):
        misses.append({"ticket": r.ticket.id, "what": what, "gold": str(gold), "predicted": str(pred), "text": r.ticket.text})

    # classification
    cats = list(categories())
    confusion: dict[str, Counter] = defaultdict(Counter)
    correct = 0
    for r in work:
        gold, pred = r.ticket.label["category"], r.understanding.category
        confusion[gold][pred] += 1
        if gold == pred:
            correct += 1
        else:
            miss(r, "category", gold, pred)
    per_class = {}
    for c in cats:
        tp = confusion[c][c]
        fp = sum(confusion[g][c] for g in cats if g != c)
        fn = sum(confusion[c].values()) - tp
        if tp + fp + fn:
            per_class[c] = _prf(tp, fp, fn)
    f1s = [v["f1"] or 0.0 for c, v in per_class.items() if sum(confusion[c].values())]

    # lanes
    lane_ok = 0
    reason_ok = reason_n = 0
    for r in labeled:
        gold_lane = r.ticket.label.get("expected_lane")
        if r.decision.lane == gold_lane:
            lane_ok += 1
        else:
            miss(r, "lane", f"{gold_lane} ({r.ticket.label.get('expected_reason')})", f"{r.decision.lane} ({r.decision.reason_code})")
        if gold_lane == "needs_you" and r.decision.lane == "needs_you":
            reason_n += 1
            reason_ok += r.decision.reason_code == r.ticket.label.get("expected_reason")
    ready = [r for r in work if r.decision.lane == "ready"]
    ready_ok = sum(r.understanding.category == r.ticket.label["category"] for r in ready)

    # priority (gold band = formula on gold facts, scored at ticket time)
    band_ok = 0
    p1_gold = p1_hit = 0
    for r in work:
        gold_band = priority.score(gold_understanding(r.ticket.label), r.ticket).band
        pred_band = priority.score(r.understanding, r.ticket).band
        band_ok += gold_band == pred_band
        if gold_band == "P1":
            p1_gold += 1
            p1_hit += pred_band == "P1"
        if gold_band != pred_band:
            miss(r, "priority", gold_band, pred_band)

    # extraction
    extraction = {}
    for field in FIELDS:
        tp = fp = fn = 0
        for r in work:
            gold = (r.ticket.label.get("fields") or {}).get(field)
            pred = getattr(r.understanding.facts, field)
            pred = pred.isoformat() if hasattr(pred, "isoformat") else pred
            if gold is not None and pred is not None and _same(field, gold, pred):
                tp += 1
            else:
                if pred is not None:
                    fp += 1
                if gold is not None:
                    fn += 1
                if gold is not None or pred is not None:
                    miss(r, f"field:{field}", gold, pred)
        extraction[field] = _prf(tp, fp, fn)

    # safety flags
    flags = {}
    for flag in FLAGS:
        tp = fp = fn = 0
        for r in work:
            gold = bool((r.ticket.label.get("flags") or {}).get(flag))
            pred = bool(getattr(r.understanding.flags, flag))
            tp += gold and pred
            fp += pred and not gold
            fn += gold and not pred
            if gold != pred:
                miss(r, f"flag:{flag}", gold, pred)
        negatives = sum(not (r.ticket.label.get("flags") or {}).get(flag) for r in work)
        flags[flag] = {**_prf(tp, fp, fn), "false_alarm_rate": fp / negatives if negatives else None}

    # how-to answers
    howto = [r for r in work if r.ticket.label.get("manual_section")]
    howto_ok = sum(r.ticket.label["manual_section"] in r.reply.cited_sections for r in howto)
    gaps = [r for r in work if r.ticket.label.get("expected_reason") == "manual_gap"]
    gaps_ok = sum(r.decision.reason_code == "manual_gap" for r in gaps)

    # duplicates
    dups = [r for r in labeled if r.ticket.label.get("expected_lane") == "duplicate"]
    dups_ok = sum(r.duplicate_of == r.ticket.label.get("duplicate_of") for r in dups)

    return {
        "n": len(labeled),
        "n_work": len(work),
        "category_accuracy": correct / len(work) if work else None,
        "macro_f1": sum(f1s) / len(f1s) if f1s else None,
        "per_class": per_class,
        "confusion": {g: dict(c) for g, c in confusion.items()},
        "lane_accuracy": lane_ok / len(labeled) if labeled else None,
        "needs_you_reason_accuracy": reason_ok / reason_n if reason_n else None,
        "ready_rate": len(ready) / len(work) if work else None,
        "ready_accuracy": ready_ok / len(ready) if ready else None,
        "escalation_rate": 1 - len(ready) / len(work) if work else None,
        "priority_band_accuracy": band_ok / len(work) if work else None,
        "p1_recall": p1_hit / p1_gold if p1_gold else None,
        "extraction": extraction,
        "flags": flags,
        "howto_section_accuracy": howto_ok / len(howto) if howto else None,
        "manual_gap_recall": gaps_ok / len(gaps) if gaps else None,
        "duplicates_found": f"{dups_ok}/{len(dups)}",
        "misses": misses,
    }


def _pct(x) -> str:
    return "n/a" if x is None else f"{x:.0%}"


def to_markdown(m: dict, title: str = "Evaluation") -> str:
    lines = [
        f"# {title}",
        "",
        f"Tickets: {m['n']} ({m['n_work']} excluding duplicates)",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Category accuracy | {_pct(m['category_accuracy'])} |",
        f"| Macro-F1 | {_pct(m['macro_f1'])} |",
        f"| Lane accuracy (ready vs needs you) | {_pct(m['lane_accuracy'])} |",
        f"| Accuracy of tickets NOT escalated | {_pct(m['ready_accuracy'])} |",
        f"| Escalation rate | {_pct(m['escalation_rate'])} |",
        f"| Priority band accuracy | {_pct(m['priority_band_accuracy'])} |",
        f"| P1 recall | {_pct(m['p1_recall'])} |",
        f"| \"I want a human\" recall | {_pct(m['flags']['human_requested']['recall'])} |",
        f"| Injection recall / false alarms | {_pct(m['flags']['injection']['recall'])} / {_pct(m['flags']['injection']['false_alarm_rate'])} |",
        f"| How-to: correct manual section | {_pct(m['howto_section_accuracy'])} |",
        f"| How-to: manual gaps escalated | {_pct(m['manual_gap_recall'])} |",
        f"| Duplicates linked | {m['duplicates_found']} |",
        "",
        "## Extraction",
        "",
        "| Field | Precision | Recall | F1 |",
        "|---|---|---|---|",
        *[f"| {k} | {_pct(v['precision'])} | {_pct(v['recall'])} | {_pct(v['f1'])} |" for k, v in m["extraction"].items()],
        "",
        "## Misses",
        "",
        "| Ticket | What | Gold | Predicted |",
        "|---|---|---|---|",
        *[f"| {x['ticket']} | {x['what']} | {x['gold']} | {x['predicted']} |" for x in m["misses"]],
    ]
    return "\n".join(lines) + "\n"
