"""--daily: every day compared with the day before it."""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .classify import call_activities
from .formatting import arrow
from .stats import Period, cache_hit
from .transcripts import Call


@dataclass
class DayRow:
    date: datetime.date
    day: Period
    prev: Optional[Period]  # the day before (None for the first row)
    is_base: bool  # the extra day before the period, shown only as a baseline
    cache_hit: Optional[float]
    per_call: Optional[float]
    driver: Optional[Tuple[str, float]] = None  # the activity that changed the most, and by how much


@dataclass
class DailySummary:
    average: float
    days: int
    highest: DayRow
    lowest: DayRow
    up: int
    down: int


def daily_series(calls: List[Call], first: datetime.date,
                 last: datetime.date) -> List[Tuple[datetime.date, Period]]:
    """one bucket per calendar day from first to last (inclusive), empty days included"""
    days = {}
    d = first
    while d <= last:
        days[d] = Period(date=d)
        d += datetime.timedelta(days=1)
    for call in calls:
        bucket = days.get(call.time.astimezone().date())
        if bucket is not None:
            bucket.add(call, call_activities(call))
    return list(days.items())


def daily_rows(series: List[Tuple[datetime.date, Period]], has_base: bool) -> List[DayRow]:
    """adds the change vs the previous day and the activity that changed the most"""
    rows = []
    for i, (d, day) in enumerate(series):
        prev = series[i - 1][1] if i else None
        row = DayRow(date=d, day=day, prev=prev, is_base=has_base and i == 0,
                     cache_hit=cache_hit(day.tokens),
                     per_call=day.weighted / day.calls if day.calls else None)
        if prev is not None:
            acts = set(day.activities) | set(prev.activities)
            if acts:
                key = max(acts, key=lambda a: abs(day.activities[a] - prev.activities[a]))
                row.driver = (key, day.activities[key] - prev.activities[key])
        rows.append(row)
    return rows


def daily_summary(rows: List[DayRow]) -> Optional[DailySummary]:
    days = [r for r in rows if not r.is_base]
    if not days:
        return None
    arrows = [arrow(r.day.weighted, r.prev.weighted) for r in days if r.prev is not None]
    return DailySummary(average=sum(r.day.weighted for r in days) / len(days), days=len(days),
                        highest=max(days, key=lambda r: r.day.weighted),
                        lowest=min(days, key=lambda r: r.day.weighted),
                        up=arrows.count("▲"), down=arrows.count("▼"))
