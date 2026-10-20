"""How-to answers from the app manual (docs/app_manual/M-*.md).

The manual is small, so a plain BM25 keyword search is enough: no vector database. In rules mode
the best section's steps are wrapped in a dialect template. In LLM mode the top three sections go
to the model, which must answer only from them and cite the section it used. If the manual does
not cover the question, the ticket goes to a human as a "manual gap".
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache

from . import llm
from .config import MANUAL_DIR, load, prompt
from .schemas import Reply, Ticket, Understanding
from .textnorm import clean, fold

_STOP = {
    "من", "في", "على", "الى", "الي", "عن", "مع", "او", "و", "هل", "شلون", "كيف", "اريد", "اعرف", "شنو", "ممكن",
    "اكدر", "اقدر", "انا", "هاي", "هذا", "هذه", "مال", "مالي", "التطبيق", "تطبيق", "نخله", "حتى", "بعدين", "اذا",
    "how", "do", "i", "to", "my", "the", "a", "an", "can", "in", "of", "is", "what", "and", "for", "on", "with",
    "shlon", "arid", "il", "el", "asawi",
}
_PREFIXES = ("وال", "بال", "لل", "ال", "و")


def tokens(text: str) -> list[str]:
    out = []
    for word in re.findall(r"\w+", fold(clean(text))):
        for prefix in _PREFIXES:
            # a bare و ("and") is stripped only from longer words, so وكيل (agent) stays whole
            if word.startswith(prefix) and len(word) - len(prefix) >= (4 if prefix == "و" else 3):
                word = word[len(prefix):]
                break
        if word not in _STOP and not word.isdigit() and len(word) > 1:
            out.append(word)
    return out


@dataclass
class Section:
    id: str
    title_ar: str
    title_en: str
    keywords: str
    steps: list[str]
    raw: str

    @property
    def topic_terms(self) -> set[str]:
        """Words from the title and keywords: what the section is about."""
        return set(tokens(" ".join([self.title_ar, self.title_en, self.keywords])))

    @property
    def search_text(self) -> str:
        # titles and keywords count twice: they say what the section is about
        return " ".join([self.title_ar, self.title_ar, self.title_en, self.keywords, self.keywords, self.raw])


def _parse(path) -> Section:
    raw = path.read_text(encoding="utf-8")
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    head = lines[0].lstrip("# ").split("·", 1)
    meta = {l.split(":", 1)[0].strip(): l.split(":", 1)[1].strip() for l in lines[1:] if re.match(r"^(title_en|keywords)\s*:", l)}
    steps = [l for l in lines if re.match(r"^\d+\.", l)]
    return Section(head[0].strip(), head[1].strip() if len(head) > 1 else "", meta.get("title_en", ""),
                   meta.get("keywords", ""), steps, raw)


@lru_cache(maxsize=1)
def sections() -> list[Section]:
    return [_parse(p) for p in sorted(MANUAL_DIR.glob("M-*.md"))]


@lru_cache(maxsize=1)
def _index():
    docs = [Counter(tokens(s.search_text)) for s in sections()]
    lengths = [sum(d.values()) for d in docs]
    avg = sum(lengths) / max(1, len(lengths))
    df = Counter(term for d in docs for term in d)
    return docs, lengths, avg, df


def search(query: str, k: int = 3) -> list[dict]:
    """BM25 over the manual. Returns [{section, score, matched}] best first."""
    docs, lengths, avg, df = _index()
    n = len(docs)
    q = set(tokens(query))
    results = []
    for section, doc, length in zip(sections(), docs, lengths):
        score, matched = 0.0, []
        for term in q:
            tf = doc.get(term, 0)
            if not tf:
                continue
            matched.append(term)
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            score += idf * tf * 2.5 / (tf + 1.5 * (1 - 0.75 + 0.75 * length / avg))
        results.append({"section": section, "score": round(score, 2), "matched": matched})
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:k]


def covers(hit: dict) -> bool:
    """The best section counts only if it scores well AND the question hits its title or keywords."""
    cfg = load("policy")["manual"]
    on_topic = set(hit["matched"]) & hit["section"].topic_terms
    return hit["score"] >= cfg["min_score"] and len(hit["matched"]) >= cfg["min_matched_terms"] and bool(on_topic)


def answer(ticket: Ticket, u: Understanding, clean_text: str, mode: str, providers: list[str] | None = None) -> tuple[Reply, dict]:
    """Return (reply, trace detail). reply.kind == "none" means the manual does not cover it."""
    query = " ".join(filter(None, [u.facts.feature_asked, clean_text]))
    hits = search(query)
    detail = {"query_terms": sorted(set(tokens(query))),
              "top": [{"id": h["section"].id, "score": h["score"], "matched": h["matched"]} for h in hits]}

    if mode == "llm":
        try:
            context = "\n\n".join(h["section"].raw for h in hits)
            ids = [h["section"].id for h in hits]
            raw, meta = llm.chat_json(
                [{"role": "system", "content": prompt("manual_answer", SECTIONS=context)},
                 {"role": "user", "content": f"Customer question:\n<question>\n{clean_text}\n</question>"}],
                job="manual_answer", providers=providers,
            )
            cited = [c for c in raw.get("cited_sections") or [] if c in ids]
            if raw.get("not_in_manual") or not cited or not raw.get("answer"):
                return Reply(kind="none", source=f"llm:{meta.label}"), {**detail, "llm": "not in manual"}
            return Reply(kind="manual_answer", text=str(raw["answer"]), cited_sections=cited, source=f"llm:{meta.label}"), detail
        except llm.LLMError as e:
            detail["llm_error"] = str(e)  # fall back to the rules answer below

    best = hits[0] if hits else None
    if not best or not covers(best):
        return Reply(kind="none", source="bm25"), detail
    s = best["section"]
    text = load("templates")["how_to"].format(section_id=s.id, title=s.title_ar, steps="\n".join(s.steps))
    return Reply(kind="manual_answer", text=text, cited_sections=[s.id], source="bm25+template"), detail


def section_text(ids: list[str]) -> str:
    return "\n".join(s.raw for s in sections() if s.id in ids)
