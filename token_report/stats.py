"""Aggregating model calls into the numbers shown in the reports."""
from __future__ import annotations

import collections
import datetime
from dataclasses import dataclass, field
from typing import Counter, DefaultDict, Dict, List, Mapping, NamedTuple, Optional, Tuple

from .classify import call_activities
from .formatting import pct
from .i18n import L, weekday
from .naming import Namer
from .pricing import cache_rewrite_waste, context_size
from .transcripts import Call, FileKey, SessionKey, SessionMeta

# (from, to, label) — calls are grouped by how long the conversation was at that moment
CTX_BUCKETS = [(0, 50e3, "< 50k"), (50e3, 100e3, "50-100k"), (100e3, 200e3, "100-200k"),
               (200e3, 300e3, "200-300k"), (300e3, float("inf"), "300k+")]
LONG_CTX_BUCKETS = ("200-300k", "300k+")
MIN_REBUILD_CTX = 20000
FEW_CALLS = 30  # groups with fewer calls are marked as unreliable
TOP_REBUILDS = 5

_EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")


@dataclass
class Bucket:
    weighted: float = 0.0
    calls: int = 0

    def add(self, weighted: float) -> None:
        self.weighted += weighted
        self.calls += 1


@dataclass
class Period:
    """one day or week (also used for the --daily series)"""
    weighted: float = 0.0
    calls: int = 0
    date: Optional[datetime.date] = None
    weighted_by_type: Counter[str] = field(default_factory=collections.Counter)
    tokens: Counter[str] = field(default_factory=collections.Counter)
    activities: Counter[str] = field(default_factory=collections.Counter)

    def add(self, call: Call, activities: List[Tuple[str, float]]) -> None:
        self.weighted += call.weighted
        self.calls += 1
        self.weighted_by_type.update(call.weighted_by_type)
        self.tokens.update(call.tokens)
        for key, share in activities:
            self.activities[key] += call.weighted * share


@dataclass
class ContextBucket:
    weighted: float = 0.0
    calls: int = 0
    reading: float = 0.0  # weighted tokens spent just on reading the conversation


@dataclass
class SessionStats:
    weighted: float = 0.0
    calls: int = 0
    subagent_weighted: float = 0.0
    max_context: int = 0  # of the main conversation


class RebuildEvent(NamedTuple):
    waste: float
    time: datetime.datetime
    file_key: FileKey
    context: int
    gap_minutes: float


@dataclass
class Rebuilds:
    """calls where an expired cache made the whole conversation be written again"""
    count: int = 0
    waste: float = 0.0
    top: List[RebuildEvent] = field(default_factory=list)


@dataclass
class Rereads:
    """Read tool calls for a part of a file that was already in the conversation"""
    reads: int = 0
    repeats: int = 0
    files: Counter[str] = field(default_factory=collections.Counter)


def _bucket_map() -> DefaultDict[str, Bucket]:
    return collections.defaultdict(Bucket)


@dataclass
class Stats:
    n_calls: int = 0
    weighted: float = 0.0
    tokens: Counter[str] = field(default_factory=collections.Counter)
    weighted_by_type: Counter[str] = field(default_factory=collections.Counter)
    by_activity: DefaultDict[str, Bucket] = field(default_factory=_bucket_map)
    by_model: DefaultDict[str, Bucket] = field(default_factory=_bucket_map)
    by_project: DefaultDict[str, Bucket] = field(default_factory=_bucket_map)
    by_side: DefaultDict[str, Bucket] = field(default_factory=_bucket_map)  # "main" / "sub"
    by_agent_type: DefaultDict[str, Bucket] = field(default_factory=_bucket_map)
    by_day: DefaultDict[str, Period] = field(
        default_factory=lambda: collections.defaultdict(Period))
    by_week: DefaultDict[str, Period] = field(
        default_factory=lambda: collections.defaultdict(Period))
    by_context: Dict[str, ContextBucket] = field(
        default_factory=lambda: {name: ContextBucket() for _, _, name in CTX_BUCKETS})
    by_session: DefaultDict[SessionKey, SessionStats] = field(
        default_factory=lambda: collections.defaultdict(SessionStats))
    rebuilds: Rebuilds = field(default_factory=Rebuilds)
    rereads: Rereads = field(default_factory=Rereads)
    n_sessions: int = 0
    n_subagents: int = 0

    @property
    def raw(self) -> int:
        return sum(self.tokens.values())

    def periods(self, kind: str) -> List[Tuple[str, Period]]:
        """days or weeks in chronological order"""
        groups = self.by_week if kind == "week" else self.by_day
        return sorted(groups.items(), key=lambda kv: kv[1].date)

    def long_context_weighted(self) -> float:
        return sum(self.by_context[k].weighted for k in LONG_CTX_BUCKETS)


def week_key(loc: datetime.datetime) -> str:
    y, w, _ = loc.isocalendar()
    monday = loc.date() - datetime.timedelta(days=loc.weekday())
    return f"{y}-W{w:02d} ({monday:%m-%d}..{monday + datetime.timedelta(days=6):%m-%d})"


def cache_hit(tokens: Mapping[str, float]) -> Optional[float]:
    ctx = context_size(tokens)
    return pct(tokens["cache_read"], ctx) if ctx else None


def ctx_growth(stats: Stats) -> Optional[Tuple[float, float, str]]:
    """(avg weight per call in the largest reliable bucket, in 50-100k, label) or None"""
    base = stats.by_context["50-100k"]
    if base.calls < FEW_CALLS:
        return None
    for _, _, name in reversed(CTX_BUCKETS):
        b = stats.by_context[name]
        if b.calls >= FEW_CALLS and name != "50-100k":
            return b.weighted / b.calls, base.weighted / base.calls, name
    return None


# --------------------------------------------------------------------------- aggregation

def aggregate(calls: List[Call], sessions: Mapping[SessionKey, SessionMeta],
              namer: Namer) -> Stats:
    stats = Stats(n_calls=len(calls))
    by_file: DefaultDict[FileKey, List[Call]] = collections.defaultdict(list)
    for call in calls:
        _add_call(stats, call, sessions, namer)
        by_file[call.file_key].append(call)
    stats.rebuilds = _find_rebuilds(by_file)
    stats.rereads = _find_rereads(by_file, sessions, namer)
    stats.n_sessions = len(stats.by_session)
    stats.n_subagents = len({c.file_key for c in calls if c.is_subagent})
    return stats


def _add_call(stats: Stats, call: Call, sessions: Mapping[SessionKey, SessionMeta],
              namer: Namer) -> None:
    w = call.weighted
    stats.weighted += w
    stats.tokens.update(call.tokens)
    stats.weighted_by_type.update(call.weighted_by_type)

    activities = call_activities(call)
    for key, share in activities:
        stats.by_activity[key].add(w * share)
    stats.by_model[call.model].add(w)
    project = namer.project(sessions.get(call.session_key), call.session_key[0])
    stats.by_project[project].add(w)
    stats.by_side["sub" if call.is_subagent else "main"].add(w)
    if call.is_subagent:
        stats.by_agent_type[call.agent_type or L("(nieznany typ)", "(unknown type)")].add(w)

    loc = call.time.astimezone()
    day = stats.by_day[f"{loc:%Y-%m-%d} {weekday(loc.date())}"]
    day.date = loc.date()
    day.add(call, activities)
    week = stats.by_week[week_key(loc)]
    week.date = loc.date() - datetime.timedelta(days=loc.weekday())
    week.add(call, activities)

    for lo, hi, name in CTX_BUCKETS:
        if lo <= call.context < hi:
            b = stats.by_context[name]
            b.weighted += w
            b.calls += 1
            b.reading += call.weighted_by_type["cache_read"] + call.weighted_by_type["input"]
            break

    s = stats.by_session[call.session_key]
    s.weighted += w
    s.calls += 1
    if call.is_subagent:
        s.subagent_weighted += w
    else:
        s.max_context = max(s.max_context, call.context)


def _find_rebuilds(by_file: Mapping[FileKey, List[Call]]) -> Rebuilds:
    """expired cache: the context was mostly written again instead of read from the cache"""
    out = Rebuilds()
    for file_key, calls in by_file.items():
        for prev, call in zip(calls, calls[1:]):
            written = call.tokens["cache_write_5m"] + call.tokens["cache_write_1h"]
            if call.context < MIN_REBUILD_CTX or written < 0.5 * call.context:
                continue
            waste = cache_rewrite_waste(call.tokens, call.model)
            gap = (call.time - prev.time).total_seconds() / 60
            out.count += 1
            out.waste += waste
            out.top.append(RebuildEvent(waste, call.time, file_key, call.context, gap))
    out.top.sort(key=lambda e: -e.waste)
    out.top = out.top[:TOP_REBUILDS]
    return out


def _read_range(tool_input: Mapping) -> Tuple[float, float]:
    try:
        first = int(tool_input.get("offset") or 1)
        limit = tool_input.get("limit")
        return (first, first + int(limit) - 1) if limit else (first, float("inf"))
    except (TypeError, ValueError):
        return 1, float("inf")


def _find_rereads(by_file: Mapping[FileKey, List[Call]],
                  sessions: Mapping[SessionKey, SessionMeta], namer: Namer) -> Rereads:
    """re-reads: Read of a line range that is already in context (no edit / compaction since)"""
    events: DefaultDict[FileKey, list] = collections.defaultdict(list)
    for file_key, calls in by_file.items():
        for call in calls:
            for name, tool_input in call.tools.values():
                path = str(tool_input.get("file_path") or "")
                if not path:
                    continue
                if name in _EDIT_TOOLS:
                    events[file_key].append((call.time, "edit", path, None))
                elif name == "Read":
                    events[file_key].append((call.time, "read", path, _read_range(tool_input)))
    for meta in sessions.values():
        for t, file_key in meta.compactions:
            if file_key in events:
                events[file_key].append((t, "compact", None, None))

    out = Rereads()
    for evs in events.values():
        evs.sort(key=lambda e: e[0])
        in_context: DefaultDict[str, list] = collections.defaultdict(list)
        for _t, kind, path, rng in evs:
            if kind == "compact":
                in_context.clear()
            elif kind == "edit":
                in_context.pop(path, None)
            else:
                out.reads += 1
                if any(max(rng[0], r[0]) <= min(rng[1], r[1]) for r in in_context[path]):
                    out.repeats += 1
                    out.files[namer.file(path)] += 1
                in_context[path].append(rng)
    return out
