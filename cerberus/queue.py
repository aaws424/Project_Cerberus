"""Step 6, the admin queue (SQLite): the only place a reply can leave the system.

Every processed ticket lands here in one of two lanes, "ready" (draft prepared) or "needs_you"
(a human has to handle it, with a reason). An agent approves, edits, rejects, reassigns or
re-prioritises; every action is logged. approve() is the only code that writes to the outbox,
and it requires a named human actor. There is no auto-approve path and no confidence threshold
that skips it.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .schemas import Result, Ticket
from .textnorm import norm

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    ticket_id    TEXT PRIMARY KEY,
    run_id       TEXT,
    created_at   TEXT,
    channel      TEXT,
    customer_id  TEXT,
    text         TEXT,
    folded       TEXT,
    lane         TEXT,
    status       TEXT,
    team         TEXT,
    category     TEXT,
    confidence   REAL,
    score        INTEGER,
    band         TEXT,
    reason_code  TEXT,
    reply_kind   TEXT,
    draft        TEXT,
    duplicate_of TEXT,
    result_json  TEXT,
    updated_at   TEXT
);
CREATE TABLE IF NOT EXISTS actions (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id TEXT,
    action    TEXT,
    actor     TEXT,
    at        TEXT,
    detail    TEXT
);
CREATE TABLE IF NOT EXISTS outbox (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id   TEXT,
    text        TEXT,
    approved_by TEXT,
    approved_at TEXT,
    action_id   INTEGER
);
CREATE TABLE IF NOT EXISTS runs (
    run_id       TEXT PRIMARY KEY,
    finished_at  TEXT,
    summary_json TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class QueueError(RuntimeError):
    """`code` lets the console show the message in the agent's language."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class AdminQueue:
    def __init__(self, path: str | Path = ":memory:"):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    # --- writing results -------------------------------------------------------------------
    def add(self, r: Result, run_id: str) -> None:
        t = r.ticket
        status = "duplicate" if r.decision.lane == "duplicate" else "pending"
        self.db.execute(
            "INSERT OR REPLACE INTO items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (t.id, run_id, t.created_at.isoformat(), t.channel, t.customer_id, t.text, norm(t.text),
             r.decision.lane, status, r.decision.team, r.understanding.category, r.understanding.confidence,
             r.priority.score, r.priority.band, r.decision.reason_code, r.reply.kind, r.reply.text,
             r.duplicate_of, r.model_dump_json(), _now()),
        )
        self.db.commit()

    def reset(self) -> None:
        for table in ("items", "actions", "outbox", "runs"):
            self.db.execute(f"DELETE FROM {table}")
        self.db.commit()

    def save_run(self, run_id: str, summary: dict) -> None:
        self.db.execute("INSERT OR REPLACE INTO runs VALUES (?,?,?)", (run_id, _now(), json.dumps(summary, ensure_ascii=False, default=str)))
        self.db.commit()

    # --- history (used by the pipeline for duplicates and repeat contact) ---------------------
    def find_duplicate(self, t: Ticket, within_hours: int = 24) -> str | None:
        if not t.customer_id:
            return None
        since = (t.created_at - timedelta(hours=within_hours)).isoformat()
        row = self.db.execute(
            "SELECT ticket_id FROM items WHERE customer_id=? AND folded=? AND created_at>=? AND created_at<=? "
            "AND ticket_id<>? AND lane<>'duplicate' ORDER BY created_at LIMIT 1",
            (t.customer_id, norm(t.text), since, t.created_at.isoformat(), t.id),
        ).fetchone()
        return row["ticket_id"] if row else None

    def recent_contacts(self, t: Ticket, days: int = 7) -> list[str]:
        if not t.customer_id:
            return []
        since = (t.created_at - timedelta(days=days)).isoformat()
        rows = self.db.execute(
            "SELECT ticket_id FROM items WHERE customer_id=? AND created_at>=? AND created_at<? "
            "AND ticket_id<>? AND lane<>'duplicate'",
            (t.customer_id, since, t.created_at.isoformat(), t.id),
        ).fetchall()
        return [r["ticket_id"] for r in rows]

    # --- reading ----------------------------------------------------------------------------
    def pending(self, lane: str | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM items WHERE status='pending'"
        args: tuple = ()
        if lane:
            sql += " AND lane=?"
            args = (lane,)
        # band first (an agent's re-prioritisation wins), then score, then oldest first
        return self.db.execute(sql + " ORDER BY band ASC, score DESC, created_at ASC", args).fetchall()

    def get(self, ticket_id: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM items WHERE ticket_id=?", (ticket_id,)).fetchone()

    def all_items(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM items ORDER BY created_at").fetchall()

    def outbox(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM outbox ORDER BY id DESC").fetchall()

    def actions(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM actions ORDER BY id DESC").fetchall()

    def runs(self) -> list[dict]:
        rows = self.db.execute("SELECT * FROM runs ORDER BY finished_at DESC").fetchall()
        return [json.loads(r["summary_json"]) for r in rows]

    def sent_without_approval(self) -> int:
        """Outbox rows with no matching 'approve' action by a named person. Must always be 0."""
        return self.db.execute(
            "SELECT COUNT(*) FROM outbox o LEFT JOIN actions a ON a.id=o.action_id AND a.action='approve' "
            "AND a.actor IS NOT NULL AND a.actor<>'' WHERE a.id IS NULL"
        ).fetchone()[0]

    # --- human actions ------------------------------------------------------------------------
    def _log(self, ticket_id: str, action: str, actor: str, detail: dict) -> int:
        cur = self.db.execute(
            "INSERT INTO actions (ticket_id, action, actor, at, detail) VALUES (?,?,?,?,?)",
            (ticket_id, action, actor, _now(), json.dumps(detail, ensure_ascii=False)),
        )
        return cur.lastrowid

    def _pending_item(self, ticket_id: str, actor: str) -> sqlite3.Row:
        if not actor or not actor.strip():
            raise QueueError("no_actor", "a named human actor is required")
        item = self.get(ticket_id)
        if item is None or item["status"] != "pending":
            raise QueueError("not_pending", f"{ticket_id} is not pending")
        return item

    def approve(self, ticket_id: str, text: str, actor: str) -> int:
        """A human approves (and may have edited) the reply. The only writer of the outbox."""
        item = self._pending_item(ticket_id, actor)
        if not text or not text.strip():
            raise QueueError("empty_reply", "cannot send an empty reply")
        if "[[" in text:
            raise QueueError("placeholders", "fill in the [[...]] placeholders before approving")
        edited = (item["draft"] or "").strip() != text.strip()
        action_id = self._log(ticket_id, "approve", actor, {"lane": item["lane"], "edited": edited, "had_ai_draft": bool(item["draft"])})
        self.db.execute(
            "INSERT INTO outbox (ticket_id, text, approved_by, approved_at, action_id) VALUES (?,?,?,?,?)",
            (ticket_id, text.strip(), actor, _now(), action_id),
        )
        self.db.execute("UPDATE items SET status='approved', updated_at=? WHERE ticket_id=?", (_now(), ticket_id))
        self.db.commit()
        return action_id

    def reject(self, ticket_id: str, actor: str, note: str = "") -> None:
        self._pending_item(ticket_id, actor)
        self._log(ticket_id, "reject", actor, {"note": note})
        self.db.execute("UPDATE items SET status='rejected', updated_at=? WHERE ticket_id=?", (_now(), ticket_id))
        self.db.commit()

    def reassign(self, ticket_id: str, team: str, actor: str) -> None:
        item = self._pending_item(ticket_id, actor)
        self._log(ticket_id, "reassign", actor, {"from": item["team"], "to": team})
        self.db.execute("UPDATE items SET team=?, updated_at=? WHERE ticket_id=?", (team, _now(), ticket_id))
        self.db.commit()

    def reprioritise(self, ticket_id: str, band: str, actor: str) -> None:
        """Logged so we can report how often agents disagree with the score."""
        item = self._pending_item(ticket_id, actor)
        self._log(ticket_id, "reprioritise", actor, {"from": item["band"], "to": band, "score": item["score"]})
        self.db.execute("UPDATE items SET band=?, updated_at=? WHERE ticket_id=?", (band, _now(), ticket_id))
        self.db.commit()
