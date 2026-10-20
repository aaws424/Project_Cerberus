"""The two promises that must never break: nothing is sent without a human, and drafts carry no invented facts."""

import ast
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from cerberus import draft, pipeline
from cerberus.config import DATA_DIR
from cerberus.queue import AdminQueue, QueueError
from cerberus.schemas import Facts

PACKAGE = Path(__file__).resolve().parent.parent / "cerberus"
IRAQ = timezone(timedelta(hours=3))


def test_only_the_queue_writes_to_the_outbox():
    writers = [p.name for p in PACKAGE.glob("*.py") if re.search(r"INSERT\s+INTO\s+outbox", p.read_text(encoding="utf-8"), re.I)]
    assert writers == ["queue.py"]


def test_pipeline_never_calls_approve():
    """No module in the package calls .approve(); only a human, through the console, does."""
    for p in PACKAGE.glob("*.py"):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "approve"]
        assert not calls, p.name


@pytest.fixture(scope="module")
def seed_run():
    queue = AdminQueue(":memory:")
    results, summary = pipeline.run_batch(pipeline.load_jsonl(DATA_DIR / "seed" / "tickets_seed.jsonl"),
                                          pipeline.RunOptions(mode="rules"), queue)
    return queue, results, summary


def test_batch_sends_nothing(seed_run):
    queue, results, summary = seed_run
    assert len(results) == 53
    assert queue.outbox() == []
    assert summary["sent_without_approval"] == 0


def test_every_injection_and_human_request_goes_to_a_person(seed_run):
    _, results, _ = seed_run
    for r in results:
        flags = (r.ticket.label or {}).get("flags", {})
        if flags.get("injection") or flags.get("human_requested"):
            assert r.decision.lane == "needs_you", r.ticket.id
            assert r.reply.text is None, r.ticket.id


def test_every_ready_draft_passes_the_validator(seed_run):
    _, results, _ = seed_run
    for r in results:
        if r.decision.lane == "ready":
            assert r.reply.text and not r.reply.issues, r.ticket.id


def test_approve_needs_a_named_person_and_filled_placeholders(seed_run):
    queue, _, _ = seed_run
    row = queue.pending("ready")[0]
    with pytest.raises(QueueError):
        queue.approve(row["ticket_id"], "تم", actor="")
    with pytest.raises(QueueError):
        queue.approve(row["ticket_id"], "راح نرجعلك خلال [[المدة]]", actor="Noor")
    queue.approve(row["ticket_id"], "هلا بيك، راح نرجعلك خلال يوم.", actor="Noor")
    assert len(queue.outbox()) == 1 and queue.sent_without_approval() == 0
    with pytest.raises(QueueError):  # cannot be sent twice
        queue.approve(row["ticket_id"], "مرة ثانية", actor="Noor")


@pytest.mark.parametrize("text, problem", [
    ("حولنا لك 750000 دينار", "numbers"),
    ("تفضل الرابط https://example.com", "link"),
    ("دزلنا رمز التحقق حتى نتأكد", "PIN"),
    ("راح نرجعلك الفلوس كاملة", "refund"),
])
def test_validator_rejects(text, problem):
    allowed = draft.allowed_numbers("حولت ٥٠٠ الف", Facts(amount=500000))
    issues = draft.validate(text, allowed)
    assert any(problem.lower() in i.lower() for i in issues), issues


def test_validator_accepts_facts_from_the_ticket():
    facts = Facts(amount=1_500_000, transaction_ref="8823419", incident_date=date(2026, 10, 19))
    text = "راجعنا حوالتك رقم 8823419 بمبلغ 1,500,000 دينار بتاريخ 19/10. راح نرجعلك بالنتيجة خلال يوم."
    assert draft.validate(text, draft.allowed_numbers("ticket", facts)) == []


def test_repeat_customer_and_duplicate_are_linked(seed_run):
    _, results, _ = seed_run
    by_id = {r.ticket.id: r for r in results}
    assert by_id["T-052"].duplicate_of == "T-027"
    assert by_id["T-051"].understanding.flags.repeat_contact
