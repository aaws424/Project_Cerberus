# Disclosure

Everything used to build Project Cerberus. Updated as the project changes.

## Models

| Use | Model · provider | Status |
|---|---|---|
| Understand (classify, extract, flags) | GPT-OSS-120B · Groq, fallback Gemini Flash-Lite / OpenRouter / Ollama | wired in `config/providers.yaml`, not yet run with a key |
| Drafts and how-to answers | Gemini Flash-Lite · Google AI Studio, fallback Groq Llama 3.3 70B | wired, not yet run with a key |
| Synthetic data generation | Mistral (free mode) | planned (week 1) |
| Offline mode | none: keyword rules + regex (`cerberus/heuristics.py`, `cerberus/extract.py`) | working |

Every run logs the provider and model used for each ticket (`Result.llm_models`, run report).

## Data

- `data/seed/tickets_seed.jsonl`: 53 tickets written by hand for this project (synthetic, no real people).
- `docs/app_manual/`: 13 articles for a fictional wallet, written for this project.
- No real customer data, transaction histories or identity documents are used anywhere.

## Libraries

Python 3.12+, pydantic, PyYAML, Streamlit, pandas, Altair, pytest. HTTP calls to LLM providers use the
Python standard library (`urllib`), with no SDK.

## AI coding assistants

- **Claude Code (Anthropic)** helped write the roadmap, the slides, the design brief and the code in this
  repository. All design decisions were reviewed by the author.
