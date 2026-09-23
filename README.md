# Project Cerberus

**Support Pipeline Automation for Iraqi-dialect support queues.**
A back-office batch pipeline that classifies, prioritises, extracts details from, routes and pre-drafts support tickets — so human agents spend their time on the hard ones.

Submission for the **Agentic AI Hackathon Iraq**, Topic 06.

## What it does

```
tickets ─► guard ─► understand ─► priority score ─► decide ─► draft / manual answer ─► ADMIN QUEUE ─► admin approves ─► customer
                                                       │
                                                       └─► "Needs you": asked for a human · low confidence ·
                                                            suspected injection · sensitive · manual gap
```

- **The AI never replies directly**, even at 99% confidence. An admin approves, edits or rejects every message.
- **"I want to talk to a human"** overrides everything. The ticket goes straight to an admin with no AI reply.
- **"How do I…?" questions** are answered from the app manual, citing the section used. If the manual doesn't cover the question, the ticket goes to an admin.
- **Priority is a visible score** built from the amount, how long the money has been stuck, the category, fraud risk, repeat contact and time waiting.
- **Low confidence → admin**, with a one-line reason. Never guesses.
- **Prompt-injection stoppers in 6 layers.** Ticket text is treated as data, never as instructions.
- **Not a chatbot:** it runs over a batch, produces a run report, and is measured on a frozen held-out test set.

## Status

🟡 **Selection round** — roadmap and two-slide proposal. Build stage starts after 28 Sep 2026.

- [ROADMAP.md](ROADMAP.md) — goal, scope, data plan, architecture, evaluation plan, failure modes, timeline
- [docs/slides/SLIDES.md](docs/slides/SLIDES.md) — the two selection-round slides

## Planned quick start (build stage)

```bash
python -m cerberus run  --in data/dev.jsonl --out runs/latest   # process a batch, write report
python -m cerberus eval --test data/test.jsonl                  # metrics on the frozen held-out set
python -m cerberus review                                       # open the human review queue
```

## Principles

1. Never guess — escalate.
2. Never send — a human approves every reply.
3. The model understands the dialect; readable rules decide priority, escalation and routing.
4. Numbers before demo: frozen test set, opened once, confusions discussed.
5. Sounds like Iraq: data and drafts are checked by native speakers.
6. Disclose everything.

## Disclosure

Maintained in `DISCLOSURE.md` from the build stage. Planning so far used Claude (Anthropic) via Claude Code.

## License

MIT
