"""Arabic text clean-up and folding.

clean()  drops characters that carry no meaning for us (diacritics, tatweel, invisible
         direction marks) and collapses whitespace. Evidence quotes shown to the agent
         are cut from this text.
fold()   maps each character of clean() output to exactly one character
         (أ→ا, ة→ه, گ→ك, Arabic-Indic digits → 0-9, lower case ...). Because the mapping is
         one-to-one, a match found in the folded text has the same span in the clean text.
"""

from __future__ import annotations

import re

_INVISIBLE = re.compile("[​-‏‪-‮⁠-⁩﻿­ـ]")
_DIACRITICS = re.compile("[ؐ-ًؚ-ٰٟۖ-ۜ۟-۪ۨ-ۭ]")
_SPACES = re.compile(r"\s+")

_FOLD_MAP = {
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",
    "ى": "ي", "ئ": "ي", "ی": "ي", "ة": "ه", "ؤ": "و",
    "گ": "ك", "ک": "ك", "چ": "ج", "پ": "ب", "ڤ": "ف",
    "،": ",", "؛": ";", "؟": "?", "٬": ",", "٫": ".",
}
_FOLD_MAP.update({chr(0x0660 + i): str(i) for i in range(10)})  # ٠-٩
_FOLD_MAP.update({chr(0x06F0 + i): str(i) for i in range(10)})  # ۰-۹
_FOLD = str.maketrans(_FOLD_MAP)


def clean(text: str) -> str:
    text = _INVISIBLE.sub("", text)
    text = _DIACRITICS.sub("", text)
    return _SPACES.sub(" ", text).strip()


def fold(text: str) -> str:
    out = []
    for ch in text.translate(_FOLD):
        low = ch.lower()
        out.append(low if len(low) == 1 else ch)
    return "".join(out)


def norm(text: str) -> str:
    return fold(clean(text))


def digits_only(text: str) -> str:
    """'TXN-55120934' -> '55120934', '١٬٥٠٠' -> '1500'."""
    return re.sub(r"\D", "", fold(text))
