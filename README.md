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

🟢 **Pipeline skeleton working end to end** (offline rules mode; LLM mode wired, waiting for API keys).
Design brief submitted 22 Oct 2026 · MVP due 08 Nov 2026.

- [ROADMAP.md](ROADMAP.md): goal, scope, data plan, architecture, evaluation plan, failure modes, week-by-week plan
- [Design brief (5 slides)](docs/design_brief/AawsOdayTami_SupportPipelineAutomation.pdf) · [selection-round slides](<docs/slides/Aaws Oday Tami Support pipeline.pdf>)
- [DISCLOSURE.md](DISCLOSURE.md) · [data card](data/README.md)

## Run it

**Windows:** double-click **`run.bat`**. The first time, it creates a private Python environment in `.venv` and
installs the packages (a few minutes); after that it starts in seconds and opens the console in your browser.
Stop it with Ctrl+C in its window.

| File | What it does |
|---|---|
| `run.bat` | build if needed, then open the admin console |
| `run.bat batch` | process the seed tickets in the terminal and print the run report |
| `run.bat eval` | print the evaluation on the seed set |
| `build.bat` | build or update `.venv`, then run the tests |
| `build.bat clean` | delete `.venv` and build from scratch |

Needs Python 3.10 or newer ([python.org](https://www.python.org/downloads/), tick "Add python.exe to PATH").

**Any OS, by hand:**

```bash
pip install -r requirements.txt
```

```bash
python -m cerberus ui
```

The admin console opens in your browser (Arabic by default, with an English toggle). Press **▶ Run batch** to load
the 53 seed tickets, then work the queue, or paste any ticket into **⚡ Live ticket** and watch every step.

Command line:

```bash
python -m cerberus run --reset --as-of-last
```

```bash
python -m cerberus eval
```

```bash
python -m pytest -q
```

No API key is needed: the default **rules** mode uses keyword rules and regex extraction, and is also the baseline
the LLM has to beat. To use an LLM, copy `.env.example` to `.env`, add a Groq or Gemini key (or start Ollama), and
pick **LLM** mode in the console or pass `--mode llm`. Check with `python -m cerberus providers`.

## How it is built

| Step | Code | LLM? |
|---|---|---|
| ① Guard: clean Arabic, regex pre-extraction, injection scan, "want a human" phrases | `cerberus/guard.py`, `extract.py` | no |
| ② Understand: category, confidence, facts with evidence quotes, flags | `understand.py` (+ `heuristics.py` in rules mode) | 1 call |
| ③ Priority: points from amount, days stuck, risk, repeat contact, waiting | `priority.py` + `config/priority.yaml` | no |
| ④ Decide: "Ready to approve" or "Needs you", first matching rule wins | `policy.py` + `config/policy.yaml` | no |
| ⑤ Prepare reply: dialect template or app-manual answer, then a safety validator | `draft.py`, `manual.py` + `config/templates.yaml`, `docs/app_manual/` | 0–1 call |
| ⑥ Admin queue: approve / edit / reject / reassign / re-prioritise, audit log, outbox | `queue.py` (SQLite) | no |
| Run report and evaluation | `report.py`, `evaluate.py` | no |
| One gateway for every LLM call: providers, cache, backoff, fallback | `llm.py` + `config/providers.yaml` | |

`queue.py`'s `approve()` is the only code that writes to the outbox, and it needs a named person. A test checks that
no other module does, and every run report shows `sent without approval = 0`.

## Principles

1. Never guess — escalate.
2. Never send — a human approves every reply.
3. The model understands the dialect; readable rules decide priority, escalation and routing.
4. Numbers before demo: frozen test set, opened once, confusions discussed.
5. Sounds like Iraq: data and drafts are checked by native speakers.
6. Disclose everything.

## Disclosure

See [DISCLOSURE.md](DISCLOSURE.md). The pipeline runs on free-tier models (Groq, Google AI Studio, Mistral, local Ollama), and every run logs the provider and model it used. Planning, documents and code are written with help from Claude Code (Anthropic) as the AI coding assistant.

## License

MIT
