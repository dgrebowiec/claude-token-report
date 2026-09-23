"""Output language: English by default, Polish with -l pl.

Every user-visible string is written as ``L("polski", "english")`` and resolved at call time,
so the language must be set (``set_lang``) before any report text is built.
"""
from __future__ import annotations

import datetime
from typing import Sequence

SUPPORTED = ("en", "pl")

_lang = "en"


def set_lang(lang: str) -> None:
    global _lang
    _lang = lang if lang in SUPPORTED else "en"


def get_lang() -> str:
    return _lang


def L(pl: str, en: str) -> str:  # noqa: N802 — short on purpose, it wraps every string
    return pl if _lang == "pl" else en


def detect_lang(argv: Sequence[str]) -> str:
    """Finds -l/--lang before argparse runs, because the --help texts are already translated."""
    for i, arg in enumerate(argv):
        if arg in ("-l", "--lang") and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--lang="):
            return arg.split("=", 1)[1]
        if arg.startswith("-l") and not arg.startswith("--") and len(arg) > 2:
            return arg[2:].lstrip("=")
    return "en"


_WEEKDAYS_PL = ("pon", "wt", "śr", "czw", "pt", "sob", "nd")
_WEEKDAYS_EN = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def weekday(d: datetime.date) -> str:
    return (_WEEKDAYS_PL if _lang == "pl" else _WEEKDAYS_EN)[d.weekday()]
