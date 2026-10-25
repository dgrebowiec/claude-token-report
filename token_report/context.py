"""Everything a report needs besides the aggregated numbers."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional

from .naming import Namer
from .session_detail import SessionDetail
from .transcripts import Call, SessionKey, SessionMeta

if TYPE_CHECKING:
    from .options import ReportPlan

TOP_ROWS = 10  # rows in the ranking tables with long tables (--long, --full)
CORE_ROWS = 5  # rows in the ranking tables with compact tables (the default)
SECTIONS = ("time", "breakdown", "cache", "bash", "skills", "map")  # the optional sections


def _default_plan() -> "ReportPlan":
    """the default report: core elements, compact tables (options imports this module)"""
    from .options import DEFAULT, ReportPlan
    return ReportPlan(elements=DEFAULT, origin={e: "default" for e in DEFAULT})


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
    plan: "ReportPlan" = field(default_factory=_default_plan)  # options.resolve

    def has(self, element: str) -> bool:
        """the report includes this element (a core one or an optional section)"""
        return self.plan.has(element)

    @property
    def rows(self) -> int:
        return TOP_ROWS if self.plan.long_tables else CORE_ROWS
