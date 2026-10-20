"""One function for every LLM call: OpenAI-compatible chat completions over plain HTTP.

Providers come from config/providers.yaml. A provider is available when its API key is set
(Ollama needs no key, only a running server). Responses are cached on disk by provider, model
and messages, so re-runs are free and repeatable. On 429 / 5xx errors we back off and retry,
then move on to the next provider in the job's chain. If every provider fails, LLMError is
raised and the pipeline sends the ticket to a human with the reason "LLM call failed".
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from functools import lru_cache

from .config import CACHE_DIR, load, load_dotenv

load_dotenv()

RETRY_STATUS = {429, 500, 502, 503, 504}
BACKOFF_SECONDS = (2, 5, 10)


class LLMError(RuntimeError):
    pass


@dataclass
class CallMeta:
    provider: str
    model: str
    cached: bool
    ms: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    @property
    def label(self) -> str:
        return f"{self.provider}/{self.model}"


@lru_cache(maxsize=1)
def _ollama_running() -> bool:
    base = load("providers")["providers"]["ollama"]["base_url"].replace("/v1", "")
    try:
        with urllib.request.urlopen(base + "/api/tags", timeout=0.5):
            return True
    except Exception:
        return False


def provider_status() -> dict[str, bool]:
    status = {}
    for name, spec in load("providers")["providers"].items():
        key_env = spec.get("key_env")
        status[name] = _ollama_running() if name == "ollama" else bool(key_env and os.environ.get(key_env))
    return status


def available(job: str) -> list[str]:
    status = provider_status()
    return [p for p in load("providers")["jobs"][job] if status.get(p)]


def model_for(provider: str, job: str) -> str:
    models = load("providers")["providers"][provider]["models"]
    return models.get(job, models["default"])


def parse_json(content: str) -> dict:
    """Parse a model reply that should be one JSON object, tolerating code fences and chatter."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise LLMError("model reply is not JSON")
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError as e:
            raise LLMError(f"model reply is not valid JSON: {e}") from e


def _cache_path(key: str):
    return CACHE_DIR / "llm" / key[:2] / f"{key}.json"


def _post(provider: str, model: str, messages: list[dict], temperature: float, max_tokens: int) -> dict:
    spec = load("providers")["providers"][provider]
    url = spec["base_url"].rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if spec.get("key_env"):
        headers["Authorization"] = f"Bearer {os.environ[spec['key_env']]}"
    body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers)
    for attempt, pause in enumerate((*BACKOFF_SECONDS, None)):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as e:
            if e.code in RETRY_STATUS and pause is not None:
                time.sleep(pause)
                continue
            detail = e.read().decode("utf-8", "replace")[:300]
            raise LLMError(f"{provider} HTTP {e.code}: {detail}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            if pause is not None and attempt == 0:
                time.sleep(pause)
                continue
            raise LLMError(f"{provider} unreachable: {e}") from e
    raise LLMError(f"{provider}: retries exhausted")


def chat_json(
    messages: list[dict],
    job: str,
    providers: list[str] | None = None,
    temperature: float = 0.0,
    max_tokens: int = 1500,
) -> tuple[dict, CallMeta]:
    """Send `messages` to the first provider that answers; return (parsed JSON, metadata)."""
    chain = providers or available(job)
    if not chain:
        raise LLMError(f"no LLM provider available for '{job}' (set a key in .env, or start Ollama)")
    errors = []
    for provider in chain:
        model = model_for(provider, job)
        key = hashlib.sha256(
            json.dumps([provider, model, messages, temperature], ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        path = _cache_path(key)
        if path.exists():
            cached = json.loads(path.read_text(encoding="utf-8"))
            return parse_json(cached["content"]), CallMeta(provider, model, True, 0.0, *cached.get("usage", (None, None)))
        started = time.perf_counter()
        try:
            data = _post(provider, model, messages, temperature, max_tokens)
            content = data["choices"][0]["message"]["content"] or ""
            parsed = parse_json(content)
        except (LLMError, KeyError, IndexError) as e:
            errors.append(f"{provider}: {e}")
            continue
        usage = data.get("usage") or {}
        tokens = (usage.get("prompt_tokens"), usage.get("completion_tokens"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"content": content, "usage": tokens}, ensure_ascii=False), encoding="utf-8")
        return parsed, CallMeta(provider, model, False, (time.perf_counter() - started) * 1000, *tokens)
    raise LLMError("; ".join(errors))
