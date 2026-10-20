"""Data shapes passed between pipeline steps."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

Lane = Literal["ready", "needs_you", "duplicate"]
Band = Literal["P1", "P2", "P3"]


class Ticket(BaseModel):
    id: str
    channel: str = "app"
    customer_id: str | None = None
    created_at: datetime
    text: str
    label: dict | None = None  # gold labels; only present in labeled datasets


class Facts(BaseModel):
    amount: float | None = None
    currency: str | None = None  # IQD | USD
    transaction_ref: str | None = None
    incident_date: date | None = None
    phone: str | None = None
    agent: str | None = None
    feature_asked: str | None = None
    evidence: dict[str, str] = Field(default_factory=dict)  # field -> quote from the ticket
    source: dict[str, str] = Field(default_factory=dict)  # field -> "llm" | "regex"


class Flags(BaseModel):
    human_requested: bool = False
    fraud: bool = False
    legal_threat: bool = False
    abusive: bool = False
    repeat_contact: bool = False
    injection: bool = False


class Understanding(BaseModel):
    intent: Literal["issue", "how_to", "human_request"] = "issue"
    category: str = "unclear"
    confidence: float = 0.0
    secondary_category: str | None = None
    language: str = "ar"
    facts: Facts = Field(default_factory=Facts)
    flags: Flags = Field(default_factory=Flags)
    summary: str = ""
    source: str = "rules"  # "rules" or "llm:<provider>/<model>"
    notes: list[str] = Field(default_factory=list)  # grounding and cross-check notes for the agent


class Priority(BaseModel):
    score: int
    band: Band
    breakdown: list[tuple[str, int]]


class Decision(BaseModel):
    lane: Lane
    team: str
    reason_code: str | None = None
    reason_ar: str | None = None
    reason_en: str | None = None
    detail: str | None = None


class Reply(BaseModel):
    kind: Literal["draft", "manual_answer", "none"] = "none"
    text: str | None = None
    cited_sections: list[str] = Field(default_factory=list)
    source: str = ""
    issues: list[str] = Field(default_factory=list)  # validator findings
    rejected_text: str | None = None  # a draft the validator refused, kept for the audit trail


class TraceStep(BaseModel):
    step: str
    ms: float
    detail: dict


class Result(BaseModel):
    ticket: Ticket
    understanding: Understanding
    priority: Priority
    decision: Decision
    reply: Reply = Field(default_factory=Reply)
    duplicate_of: str | None = None
    trace: list[TraceStep] = Field(default_factory=list)
    llm_calls: int = 0
    llm_models: list[str] = Field(default_factory=list)
