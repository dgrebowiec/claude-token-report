"""Everything a report needs besides the aggregated numbers."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional

from .naming import Namer
from .session_detail import SessionDetail
from .transcripts import Call, SessionKey, SessionMeta

TOP_ROWS = 10  # rows in the ranking tables (--full)
CORE_ROWS = 5  # rows in the default report
SECTIONS = ("time", "breakdown", "cache", "bash", "skills", "map")  # the optional sections


@dataclass
class ReportContext:
    label: str  # the period, e.g. "last 7 days (...)"
    root_display: str  # transcripts directory as shown to the user
    sessions: Dict[SessionKey, SessionMeta]
    namer: Namer
    calls: List[Call] = field(default_factory=list)  # the calls inside the period
    session: Optional[str] = None  # --session argument (single-session report)
    session_key: Optional[SessionKey] = None
    prev_label: str = ""  # the period compared with (--diff)
    detail: Optional[SessionDetail] = None  # of the --session session
    short: bool = False  # --short: the main numbers and the heaviest conversations only
    sections: FrozenSet[str] = frozenset()  # optional sections asked for (--bash, --cache ...)
    full: bool = False  # --full: every section, long tables
    only_chosen: bool = False  # saved settings: long tables (full) but only the chosen sections
    core: Optional[FrozenSet[str]] = None  # saved settings: core elements to show; None = all

    def wants(self, section: str) -> bool:
        return (self.full and not self.only_chosen) or section in self.sections

    def shows(self, element: str) -> bool:
        """a core element (activities, models, sessions, tips) the report includes"""
        return self.core is None or element in self.core

    @property
    def rows(self) -> int:
        return TOP_ROWS if self.full else CORE_ROWS
