"""Saved report settings: detail level and which elements the report contains."""
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
LEVELS = ("minimal", "normal", "detailed")
DEFAULT_ELEMENTS = list(CORE)
# elements the minimal level (the short report) has no room for
MINIMAL_ELEMENTS = ("activities", "models", "sessions")


def describe(element: str) -> str:
    return {
        "activities": L("czynności: na co idą tokeny", "activities: what the tokens go to"),
        "models": L("modele i ich waga", "models and their weight"),
        "sessions": L("najcięższe rozmowy", "heaviest conversations"),
        "tips": L("wskazówki: co można poprawić", "tips: what you could improve"),
        "time": L("rodzaje tokenów i zużycie w czasie", "token types and usage over time"),
        "breakdown": L("sesja główna vs subagenci, projekty", "main session vs subagents, projects"),
        "cache": L("cache i długość rozmowy", "cache and conversation length"),
        "bash": L("szum z poleceń Bash", "Bash noise"),
        "skills": L("skille: używane i nieużywane", "skills: used and unused"),
        "map": L("mapa projektu vs. CLAUDE.md", "project map vs. CLAUDE.md"),
    }[element]


def describe_level(level: str) -> str:
    return {
        "minimal": L("skrócony raport, krótkie tabele", "short report, short tables"),
        "normal": L("domyślny raport", "the default report"),
        "detailed": L("długie tabele (10 wierszy zamiast 5)", "long tables (10 rows instead of 5)"),
    }[level]


@dataclass
class Settings:
    level: str = "normal"
    elements: List[str] = field(default_factory=lambda: list(DEFAULT_ELEMENTS))

    def to_dict(self) -> Dict[str, Any]:
        return {"level": self.level, "elements": list(self.elements)}

    def shown(self) -> List[str]:
        """Elements that end up in the report, in report order."""
        allowed = MINIMAL_ELEMENTS if self.level == "minimal" else ELEMENTS
        return [e for e in ELEMENTS if e in self.elements and e in allowed]


def settings_path() -> Path:
    override = os.environ.get("CLAUDE_TOKEN_REPORT_CONFIG")
    if override:
        return Path(override)
    return Path.home() / ".claude" / "claude-token-report.json"


def from_dict(data: Any) -> Settings:
    """Tolerant parsing: anything wrong falls back to the default for that key."""
    if not isinstance(data, dict):
        return Settings()
    level = data.get("level")
    elements: List[str] = []
    for name in data.get("elements") or []:
        if name in ELEMENTS and name not in elements:
            elements.append(name)
    return Settings(level=level if level in LEVELS else "normal",
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
