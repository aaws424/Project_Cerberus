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

🟡 **Build stage.** Selected after the two-slide round. Design brief due 22 Oct 2026, MVP 08 Nov 2026.

- [ROADMAP.md](ROADMAP.md): goal, scope, data plan, architecture, evaluation plan, failure modes, week-by-week plan
- [Design brief (5 slides)](docs/design_brief/AawsOdayTami_SupportPipelineAutomation.pdf): user, architecture, models/tools/data, test plan, risks and plan (source: [design_brief.html](docs/design_brief/design_brief.html))
- [Selection-round slides](<docs/slides/Aaws Oday Tami Support pipeline.pdf>)

## Planned quick start (build stage)

```bash
python -m cerberus run  --in data/dev.jsonl --out runs/latest   # process a batch, write report
python -m cerberus eval --split test                            # metrics on a frozen split (test now, held-out once at the end)
python -m cerberus admin                                        # open the admin approval queue
```

## Principles

1. Never guess — escalate.
2. Never send — a human approves every reply.
3. The model understands the dialect; readable rules decide priority, escalation and routing.
4. Numbers before demo: frozen test set, opened once, confusions discussed.
5. Sounds like Iraq: data and drafts are checked by native speakers.
6. Disclose everything.

## Disclosure

Maintained in `DISCLOSURE.md` from the build stage. The pipeline runs on free-tier models (Groq, Google AI Studio, Mistral, local Ollama), and every run logs the provider and model it used. Planning, documents and code are written with help from Claude Code (Anthropic) as the AI coding assistant.

## License

MIT
