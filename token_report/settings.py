"""Saved report settings: table length (compact / long) and which elements the report contains."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .context import SECTIONS
from .i18n import L

CORE = ("activities", "models", "sessions", "tips")  # shown in the default report
ELEMENTS = CORE + SECTIONS
LEVELS = ("compact", "long")  # table length: 5 or 10 rows in the ranking tables
DEFAULT_ELEMENTS = list(CORE)
# the levels of older versions -> (level, elements to keep or None for all of them)
OLD_LEVELS = {"minimal": ("compact", ("activities", "models", "sessions")),
              "normal": ("compact", None), "detailed": ("long", None)}


def describe(element: str) -> str:
    return {
        "activities": L("czynności: na co idą tokeny (czytanie kodu, edycje, polecenia...)",
                        "activities: what the tokens go to (reading code, edits, commands...)"),
        "models": L("modele i ich waga: ile zużył każdy model",
                    "models and their weight: what each model used"),
        "sessions": L("najcięższe rozmowy: ranking sesji według zużycia",
                      "heaviest conversations: sessions ranked by usage"),
        "tips": L("wskazówki: co można poprawić, na podstawie tego raportu",
                  "tips: what you could improve, from this report"),
        "time": L("rodzaje tokenów (surowe vs ważone) i zużycie dzień po dniu",
                  "token types (raw vs weighted) and usage day by day"),
        "breakdown": L("sesja główna vs subagenci, typy subagentów, projekty",
                       "main session vs subagents, subagent types, projects"),
        "cache": L("długość rozmowy, wygasły cache, długie rozmowy, powtórne odczyty",
                   "conversation length, expired cache, long conversations, re-reads"),
        "bash": L("szum z poleceń Bash: długie wyniki, których nikt nie ograniczył",
                  "Bash noise: long results nobody limited"),
        "skills": L("skille: używane i nieużywane (nieużywane zajmują miejsce w każdej rozmowie)",
                    "skills: used and unused (unused ones take room in every conversation)"),
        "map": L("mapa projektu: pliki i symbole, których Claude szuka w kółko, vs. CLAUDE.md",
                 "project map: files and symbols Claude keeps looking up, vs. CLAUDE.md"),
    }[element]


def describe_level(level: str) -> str:
    if level == "compact":
        return L("krótkie tabele: rankingi po 5 wierszy (czynności po 8)",
                 "short tables: rankings of 5 rows (activities 8)")
    from .options import ELEMENT_INFO  # options imports this module
    fixed = ", ".join(e for e in ELEMENTS if not ELEMENT_INFO[e].has_tables)
    return L("długie tabele: rankingi po 10 wierszy (czynności po 16); nie zmienia sekcji bez "
             "tabel: " + fixed,
             "long tables: rankings of 10 rows (activities 16); does not change the sections "
             "without tables: " + fixed)


@dataclass
class Settings:
    level: str = "compact"
    elements: List[str] = field(default_factory=lambda: list(DEFAULT_ELEMENTS))

    def to_dict(self) -> Dict[str, Any]:
        return {"level": self.level, "elements": list(self.elements)}

    def shown(self) -> List[str]:
        """Elements that end up in the report, in report order."""
        return [e for e in ELEMENTS if e in self.elements]


def settings_path() -> Path:
    override = os.environ.get("CLAUDE_TOKEN_REPORT_CONFIG")
    if override:
        return Path(override)
    return Path.home() / ".claude" / "claude-token-report.json"


def from_dict(data: Any) -> Settings:
    """Tolerant parsing: anything wrong falls back to the default for that key. The levels of
    older versions (minimal / normal / detailed) are migrated to compact / long."""
    if not isinstance(data, dict):
        return Settings()
    level = data.get("level")
    elements = [e for e in ELEMENTS if e in (data.get("elements") or [])]
    if level in OLD_LEVELS:
        level, keep = OLD_LEVELS[level]
        if keep is not None:  # minimal was the short report: only these three fitted in
            elements = [e for e in elements if e in keep] or list(keep)
    return Settings(level=level if level in LEVELS else "compact",
                    elements=elements or list(DEFAULT_ELEMENTS))


def load(path: Optional[Path] = None) -> Optional[Settings]:
    """None when nothing was saved: the report then behaves as before."""
    path = path or settings_path()
    try:
        return from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


def save(settings: Settings, path: Optional[Path] = None) -> Path:
    path = path or settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path
