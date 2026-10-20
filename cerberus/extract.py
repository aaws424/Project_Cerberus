"""Deterministic pre-extraction: phone numbers, transaction references, amounts, dates, agents.

Runs before any LLM call. In rules mode these are the extracted facts; in LLM mode they are a
cross-check (a disagreement escalates the ticket) and a fallback for fields the model missed.
All regexes run on folded text (see textnorm), so every span maps straight back to the clean
text, and quotes shown to the agent are exact substrings of the ticket.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .textnorm import fold


@dataclass
class Found:
    value: object
    start: int
    end: int
    quote: str
    currency: str | None = None


@dataclass
class Extracted:
    phones: list[Found] = field(default_factory=list)
    refs: list[Found] = field(default_factory=list)
    amounts: list[Found] = field(default_factory=list)
    dates: list[Found] = field(default_factory=list)
    agents: list[Found] = field(default_factory=list)

    def first(self, kind: str) -> Found | None:
        items = getattr(self, kind)
        return items[0] if items else None

    def summary(self) -> dict:
        return {
            kind: [str(f.value) + (f" {f.currency}" if f.currency else "") for f in getattr(self, kind)]
            for kind in ("amounts", "refs", "phones", "dates", "agents")
        }


def _free(taken: list[Found], start: int, end: int) -> bool:
    return all(end <= t.start or start >= t.end for t in taken)


# --- phones: Iraqi mobiles 07[5789]X XXX XXXX, optionally +964 ------------------------------
_PHONE = re.compile(r"(?<!\d)(?:\+?964[\s-]?|00964[\s-]?|0)(7[5789]\d)[\s-]?(\d{3})[\s-]?(\d{4})(?!\d)")


def _phones(f: str, c: str) -> list[Found]:
    return [Found("0" + "".join(m.groups()), m.start(), m.end(), c[m.start():m.end()]) for m in _PHONE.finditer(f)]


# --- transaction references ----------------------------------------------------------------
_REF_KEY = (
    r"(?:رقم\s*(?:ال)?(?:عمليه|حواله|معامله|مرجع|وصل|طلب|حركه)|(?:ال)?(?:عمليه|حواله)\s*رقم"
    r"|رقمها|ref(?:erence)?(?:\s*(?:no|number))?|transaction(?:\s*(?:id|no|number|ref))?)"
)
_REF = re.compile(_REF_KEY + r"\s*[:#.\-]?\s*(?:هو\s+|is\s+)?((?:[a-z]{2,4}-?)?\d{5,14})(?!\d)")
_TXN = re.compile(r"(?<![a-z0-9])((?:txn|trx)-?\d{5,14})(?!\d)")


def _refs(f: str, c: str, taken: list[Found]) -> list[Found]:
    found: list[Found] = []
    for rx in (_TXN, _REF):
        for m in rx.finditer(f):
            s, e = m.start(1), m.end(1)
            if _free(taken + found, s, e):
                found.append(Found(c[s:e].upper(), s, e, c[m.start():m.end()]))
    found.sort(key=lambda x: x.start)
    return found


# --- amounts ---------------------------------------------------------------------------------
_NUM = r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
_LB = r"(?<![\d.,])"
_THOUSAND = r"(?:الف|الاف|تالاف|ثلاف|alf|elf|thousand|k)(?![a-z])"
_MILLION = r"(?:مليون|ملايين|ملاين|million|milyon|malyon)(?![a-z])"
_USD_AFTER = r"(?:\$|دولار|usd|dollars?)"
_IQD_AFTER = r"(?:دينار|iqd|د\.ع)"

_WORD_MILLION = [  # longest first
    (r"مليونين\s*و\s*نص", 2_500_000),
    (r"مليون\s*و\s*نص", 1_500_000),
    (r"مليون\s*و\s*ربع", 1_250_000),
    (r"مليونين", 2_000_000),
    (r"نص\s*مليون", 500_000),
    (r"ربع\s*مليون", 250_000),
    (r"مليون", 1_000_000),
]
_WORD_NUMBERS = {
    "خمس": 5, "خمسه": 5, "عشر": 10, "عشره": 10, "عشرين": 20, "ثلاثين": 30, "تلاثين": 30,
    "اربعين": 40, "خمسين": 50, "ستين": 60, "سبعين": 70, "ثمانين": 80, "ثمنين": 80, "تسعين": 90,
    "ميه": 100, "مئه": 100, "ميتين": 200, "ثلاثميه": 300, "تلثميه": 300, "اربعميه": 400,
    "خمسميه": 500, "ستميه": 600, "سبعميه": 700, "ثمنميه": 800, "تسعميه": 900,
}
_WORDNUM = re.compile(
    r"(?<!\w)(" + "|".join(sorted(_WORD_NUMBERS, key=len, reverse=True)) + r")\s*(?:الف|الاف|تالاف)(?!\w)"
)
_MONEY_VERB = r"(?:حولت|حولتله|حولتلها|دزيت|دفعت|سحبت|انسحب|انسحبت|انخصم|انخصمت|بمبلغ|مبلغ|sent|paid|transferred|withdrew)"
_BARE = re.compile(_MONEY_VERB + r"[^\d]{0,15}?" + _LB + _NUM + r"(?![\d,])")


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def _amounts(f: str, c: str, taken: list[Found]) -> list[Found]:
    found: list[Found] = []

    def add(value: float, s: int, e: int, currency: str | None = None) -> None:
        if not _free(taken + found, s, e):
            return
        if currency is None:
            currency = "USD" if re.match(r"\s*" + _USD_AFTER, f[e:e + 12]) else "IQD"
        value = int(value) if float(value).is_integer() else round(value, 2)
        found.append(Found(value, s, e, c[s:e], currency))

    for m in re.finditer(r"\$\s*" + _NUM, f):
        add(_num(m.group(1)), m.start(), m.end(), "USD")
    for m in re.finditer(_LB + _NUM + r"\s*" + _USD_AFTER, f):
        add(_num(m.group(1)), m.start(), m.end(), "USD")
    for m in re.finditer(_LB + _NUM + r"\s*" + _MILLION, f):
        add(_num(m.group(1)) * 1_000_000, m.start(), m.end())
    for pattern, value in _WORD_MILLION:
        for m in re.finditer(pattern, f):
            add(value, m.start(), m.end())
    for m in re.finditer(_LB + _NUM + r"\s*" + _THOUSAND, f):
        add(_num(m.group(1)) * 1000, m.start(), m.end())
    for m in _WORDNUM.finditer(f):
        add(_WORD_NUMBERS[m.group(1)] * 1000, m.start(), m.end())
    for m in re.finditer(_LB + _NUM + r"\s*" + _IQD_AFTER, f):
        add(_num(m.group(1)), m.start(), m.end(), "IQD")
    for m in _BARE.finditer(f):
        value = _num(m.group(1))
        if value >= 1000:
            add(value, m.start(1), m.end(1))
    found.sort(key=lambda x: x.start)
    return found


# --- dates (resolved against the ticket's created_at) -----------------------------------------
_WEEKDAYS = {
    "اثنين": 0, "ثلاثاء": 1, "ثلاثا": 1, "اربعاء": 2, "اربعا": 2, "خميس": 3, "جمعه": 4, "سبت": 5, "احد": 6,
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
}
_DAY_WORDS = {"ثلاث": 3, "تلاث": 3, "اربع": 4, "خمس": 5, "ست": 6, "سبع": 7,
              "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
_DAY_NUM = r"(\d+|ثلاث|تلاث|اربع|خمس|ست|سبع|two|three|four|five|six)"
_SINCE = r"(?:قبل|من|صار(?:لي|له|لها|لهم)?|sar|since|for)"

_DATE_RULES = [  # (pattern, kind) in order of precedence, not position
    (r"(?<![\d.,])(\d{1,2})[/\-](\d{1,2})(?:[/\-](\d{2,4}))?(?![\d])", "explicit"),
    (r"(?:يوم\s*(?:ال)?|(?:on|last)\s+)(" + "|".join(_WEEKDAYS) + r")(?!\w)", "weekday"),
    (r"اول\s*امس|" + _SINCE + r"\s*يومين", "two_days"),
    (_SINCE + r"\s*" + _DAY_NUM + r"\s*(?:ايام|يوم|days?|ayam|eyam)(?!\w)", "n_days"),
    (_DAY_NUM + r"\s*(?:days?|ayam)\s+ago", "n_days"),
    (_SINCE + r"\s*(?:اسبوع|سبوع)|a\s+week\s+ago|last\s+week", "week"),
    (r"(?<!\w)(?:امس|البارحه|بارحه|yesterday|ams|mbareh|embareh)(?!\w)", "yesterday"),
    (r"(?<!\w)(?:اليوم|الصبح|الصباح|today|this\s+morning)(?!\w)|قبل\s*ساع(?:ه|تين)|(?:an?|one|two)\s+hours?\s+ago", "today"),
]


def _dates(f: str, c: str, created: datetime) -> list[Found]:
    today = created.date()
    found: list[Found] = []
    for pattern, kind in _DATE_RULES:
        for m in re.finditer(pattern, f):
            d: date | None = None
            if kind == "explicit":
                day, month = int(m.group(1)), int(m.group(2))
                year = int(m.group(3)) if m.group(3) else today.year
                year = year + 2000 if year < 100 else year
                try:
                    d = date(year, month, day)
                except ValueError:
                    continue
                if not m.group(3) and d > today:
                    d = d.replace(year=d.year - 1)
            elif kind == "weekday":
                d = today - timedelta(days=(today.weekday() - _WEEKDAYS[m.group(1)]) % 7)
            elif kind == "two_days":
                d = today - timedelta(days=2)
            elif kind == "n_days":
                raw = m.group(1)
                n = int(raw) if raw.isdigit() else _DAY_WORDS.get(raw, 0)
                d = today - timedelta(days=n) if 0 < n < 60 else None
            elif kind == "week":
                d = today - timedelta(days=7)
            elif kind == "yesterday":
                d = today - timedelta(days=1)
            elif kind == "today":
                d = today
            if d and d <= today:
                found.append(Found(d, m.start(), m.end(), c[m.start():m.end()]))
    return found  # already in precedence order


# --- agent location / name ---------------------------------------------------------------------
_AGENT = re.compile(r"(?:الوكيل|وكيل|agent)\s+(?:ب(?=ال)|في\s+|(?:in|at|from)\s+)?(ال[^\s,.?!،]+|[a-z][^\s,.?!]*)")
_AGENT_STOP = {"اللي", "الي", "the", "a", "an", "took", "said", "is", "was"}


def _agents(f: str, c: str) -> list[Found]:
    out = []
    for m in _AGENT.finditer(f):
        s, e = m.start(1), m.end(1)
        if f[s:e] in _AGENT_STOP:
            continue
        out.append(Found(c[s:e], s, e, c[m.start():m.end()]))
    return out


def extract_all(clean_text: str, created_at: datetime) -> Extracted:
    f = fold(clean_text)
    phones = _phones(f, clean_text)
    refs = _refs(f, clean_text, phones)
    amounts = _amounts(f, clean_text, phones + refs)
    return Extracted(
        phones=phones,
        refs=refs,
        amounts=amounts,
        dates=_dates(f, clean_text, created_at),
        agents=_agents(f, clean_text),
    )
