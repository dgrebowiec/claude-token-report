"""Everything a report needs besides the aggregated numbers."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .naming import Namer
from .transcripts import Call, SessionKey, SessionMeta

TOP_ROWS = 10  # rows in the ranking tables


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
