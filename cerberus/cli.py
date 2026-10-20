"""Command line: python -m cerberus {run, eval, ui, providers}."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime

from . import evaluate, llm, pipeline, report
from .config import DATA_DIR, ROOT, RUNS_DIR
from .queue import AdminQueue

DEFAULT_DATA = DATA_DIR / "seed" / "tickets_seed.jsonl"


def _opts(args) -> pipeline.RunOptions:
    return pipeline.RunOptions(mode=args.mode, providers=args.provider.split(",") if args.provider else None)


def cmd_run(args) -> None:
    tickets = pipeline.load_jsonl(args.data)
    queue = AdminQueue(args.db)
    if args.reset:
        queue.reset()
    opts = _opts(args)
    if args.as_of_last:
        opts.as_of = max(t.created_at for t in tickets)
    results, summary = pipeline.run_batch(tickets, opts, queue, progress=lambda i, n, r: print(
        f"[{i:>3}/{n}] {r.ticket.id:<7} {r.decision.lane:<10} {r.priority.band} {r.priority.score:>3}  "
        f"{r.understanding.category:<18} {r.decision.reason_code or ''}", file=sys.stderr))
    out = RUNS_DIR / summary["run_id"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "report.md").write_text(report.to_markdown(summary), encoding="utf-8")
    print(report.to_markdown(summary))
    print(f"Saved to {out}. Queue: {args.db}", file=sys.stderr)


def cmd_eval(args) -> None:
    tickets = pipeline.load_jsonl(args.data)
    results, _ = pipeline.run_batch(tickets, _opts(args), AdminQueue(":memory:"))
    metrics = evaluate.evaluate(results)
    title = f"Evaluation: {args.data} · mode {args.mode} · {datetime.now():%Y-%m-%d %H:%M}"
    md = evaluate.to_markdown(metrics, title)
    out = RUNS_DIR / f"eval-{datetime.now():%Y%m%d-%H%M%S}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "evaluation.md").write_text(md, encoding="utf-8")
    (out / "evaluation.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(md)
    print(f"Saved to {out}", file=sys.stderr)


def cmd_ui(_args) -> None:
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(ROOT / "app" / "streamlit_app.py")], check=False)


def cmd_providers(_args) -> None:
    for name, ok in llm.provider_status().items():
        print(f"{'✓' if ok else '·'} {name}")
    for job in ("understand", "draft", "manual_answer", "generate"):
        print(f"{job:<14} -> {llm.available(job) or 'none (rules mode only)'}")


def main(argv: list[str] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="cerberus", description="Support pipeline: the AI prepares, a human decides.")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--data", default=str(DEFAULT_DATA), help="tickets JSONL")
        p.add_argument("--mode", choices=["rules", "llm"], default="rules", help="rules = offline, no API key")
        p.add_argument("--provider", help="force providers in LLM mode, e.g. groq or groq,gemini")

    p = sub.add_parser("run", help="process a batch into the admin queue and write a run report")
    common(p)
    p.add_argument("--db", default=str(RUNS_DIR / "queue.db"))
    p.add_argument("--reset", action="store_true", help="empty the queue first")
    p.add_argument("--as-of-last", action="store_true", help="score waiting time as of the newest ticket")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("eval", help="run on a labeled file and print metrics")
    common(p)
    p.set_defaults(func=cmd_eval)

    sub.add_parser("ui", help="open the admin console (Streamlit)").set_defaults(func=cmd_ui)
    sub.add_parser("providers", help="show which LLM providers are configured").set_defaults(func=cmd_providers)

    args = parser.parse_args(argv)
    args.func(args)
