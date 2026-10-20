"""LLM mode with a fake provider: no network, no key. Checks parsing, grounding and failure handling."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from cerberus import llm, pipeline, understand
from cerberus.queue import AdminQueue
from cerberus.schemas import Ticket

IRAQ = timezone(timedelta(hours=3))
TEXT = "هلو، حولت مليون ونص لاخوي امس ورقم العملية 8823419 وللحد الآن ما وصلته"


def ticket(text=TEXT):
    return Ticket(id="T-X", channel="app", customer_id="C-1", created_at=datetime(2026, 10, 20, 9, 12, tzinfo=IRAQ), text=text)


def fake_reply(**overrides):
    reply = {
        "intent": "issue", "category": "failed_transfer", "confidence": 0.92, "secondary_category": None, "language": "ar",
        "fields": {
            "amount": {"value": 1500000, "currency": "IQD", "quote": "مليون ونص"},
            "transaction_ref": {"value": "8823419", "quote": "رقم العملية 8823419"},
            "incident_date": {"value": "2026-10-19", "quote": "امس"},
            "phone": {"value": None, "quote": None},
            "agent": {"value": None, "quote": None},
            "feature_asked": {"value": None, "quote": None},
        },
        "flags": {"human_requested": False, "fraud": False, "legal_threat": False, "abusive": False,
                  "repeat_contact": False, "instruction_like_text": False},
        "summary": "Transfer of 1.5M IQD not received.",
    }
    reply.update(overrides)
    return reply


@pytest.fixture
def fake_llm(monkeypatch):
    replies = {}

    def chat_json(messages, job, providers=None, **kw):
        if job in replies and isinstance(replies[job], Exception):
            raise replies[job]
        return replies.get(job, {"draft": ""}), llm.CallMeta("fake", "fake-model", False, 1.0)

    monkeypatch.setattr(llm, "chat_json", chat_json)
    return replies


def test_llm_understanding_is_parsed_and_grounded(fake_llm):
    fake_llm["understand"] = fake_reply()
    r = pipeline.process(ticket(), pipeline.RunOptions(mode="llm"), AdminQueue(":memory:"))
    u = r.understanding
    assert u.source == "llm:fake/fake-model"
    assert (u.category, u.facts.amount, u.facts.transaction_ref) == ("failed_transfer", 1_500_000, "8823419")
    assert r.decision.lane == "ready" and r.priority.band == "P1"


def test_invented_value_is_dropped(fake_llm):
    reply = fake_reply()
    reply["fields"]["transaction_ref"] = {"value": "99999999", "quote": "رقم 99999999"}  # not in the ticket
    fake_llm["understand"] = reply
    r = pipeline.process(ticket(), pipeline.RunOptions(mode="llm"), AdminQueue(":memory:"))
    assert r.understanding.facts.transaction_ref == "8823419"  # refilled from the regex extraction
    assert r.understanding.facts.source["transaction_ref"] == "regex"
    assert any("quote not found" in n for n in r.understanding.notes)


def test_canary_leak_flags_injection(fake_llm, monkeypatch):
    t = ticket()
    canary = "CNRY-" + understand._secret(t, "canary", 12)
    fake_llm["understand"] = fake_reply(summary=f"leaked {canary}")
    r = pipeline.process(t, pipeline.RunOptions(mode="llm"), AdminQueue(":memory:"))
    assert r.understanding.flags.injection and r.decision.reason_code == "suspected_injection"


def test_guard_overrides_a_model_that_misses_the_human_request(fake_llm):
    fake_llm["understand"] = fake_reply()  # model says nothing about a human
    r = pipeline.process(ticket(TEXT + "، اريد احچي ويا موظف"), pipeline.RunOptions(mode="llm"), AdminQueue(":memory:"))
    assert r.decision.reason_code == "human_requested"


def test_llm_failure_sends_the_ticket_to_a_person(fake_llm):
    fake_llm["understand"] = llm.LLMError("groq: HTTP 429")
    r = pipeline.process(ticket(), pipeline.RunOptions(mode="llm"), AdminQueue(":memory:"))
    assert (r.decision.lane, r.decision.reason_code) == ("needs_you", "llm_error")


def test_polished_draft_with_an_invented_number_is_refused(fake_llm):
    fake_llm["understand"] = fake_reply()
    fake_llm["draft"] = {"draft": "هلا بيك، حولنالك 750000 دينار تعويض."}
    r = pipeline.process(ticket(), pipeline.RunOptions(mode="llm"), AdminQueue(":memory:"))
    assert r.decision.reason_code == "validator_failed"
    assert r.reply.text is None and "750000" in (r.reply.rejected_text or "")


def test_parse_json_tolerates_fences():
    assert llm.parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert llm.parse_json('Sure! {"a": 2} hope that helps') == {"a": 2}
    with pytest.raises(llm.LLMError):
        llm.parse_json("no json here")
