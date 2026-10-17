"""Everything about one session: models, effort, modes, subagents, skills, files and searches."""
from __future__ import annotations

import collections
import datetime
import os
import re
from dataclasses import dataclass, field
from typing import Counter, DefaultDict, Dict, List, Optional, Tuple

from .formatting import home_relative
from .hotspots import bash_read_files
from .i18n import L
from .naming import Namer
from .stats import LONG_CONTEXT, SessionRebuilds, iter_rebuilds
from .transcripts import Call, SessionKey, SessionMeta

TOP_FILES = 15
TOP_SEARCHES = 8
EFFORT_ORDER = ("low", "medium", "high", "xhigh", "max")

_EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
_ULTRACODE_WORD = re.compile(r"\bultracode\b", re.I)


@dataclass
class ModelUse:
    model: str
    calls: int = 0
    sub_calls: int = 0  # of them made by subagents
    weighted: float = 0.0
    tokens: Counter[str] = field(default_factory=collections.Counter)

    @property
    def raw(self) -> int:
        return sum(self.tokens.values())


@dataclass
class Usage:
    calls: int = 0
    weighted: float = 0.0


@dataclass
class AgentUse:
    agent_id: str
    agent_type: str
    task: str
    start: datetime.datetime
    models: Counter[str] = field(default_factory=collections.Counter)
    calls: int = 0
    weighted: float = 0.0


@dataclass
class FileUse:
    name: str
    reads: int = 0
    edits: int = 0
    weighted: float = 0.0  # share of the calls that read or changed the file


@dataclass
class SessionDetail:
    session_id: str
    project: str
    branch: Optional[str]
    version: Optional[str]
    start: datetime.datetime
    end: datetime.datetime
    calls: int
    weighted: float
    raw: int
    max_context: int
    requests: int
    notifications: int
    compactions: int
    rebuilds: SessionRebuilds  # expired cache
    long_calls: int  # main-conversation calls with context >= LONG_CONTEXT
    long_weighted: float
    models: List[ModelUse]
    efforts: List[Tuple[str, Usage]]
    fast: Usage
    ultracode_on: List[datetime.datetime]
    ultracode_requests: int  # requests with the "ultracode" keyword
    workflows: int  # Workflow tool calls
    agents: List[AgentUse]
    skills: Counter[str]
    files: List[FileUse]
    n_files: int
    searches: Counter[str]

    @property
    def duration(self) -> datetime.timedelta:
        return self.end - self.start


def fmt_duration(d: datetime.timedelta) -> str:
    minutes = int(d.total_seconds() // 60)
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60:02d} min"


def effort_name(level: str) -> str:
    return level if level != "?" else L("(nie zapisano)", "(not recorded)")


def _display_path(path: str, cwd: Optional[str], namer: Namer) -> str:
    if namer.private:
        return namer.file(path)
    if cwd:
        full = os.path.normpath(os.path.join(cwd, os.path.expanduser(path)))
        if full.startswith(cwd.rstrip(os.sep) + os.sep):
            return os.path.relpath(full, cwd)
        return home_relative(full)
    return home_relative(path)


def _call_files(call: Call) -> List[Tuple[str, str, float]]:
    """(path, "read"/"edit", share of the call's weight) for every file the call touched"""
    tools = list(call.tools.values())
    out = []
    for name, tool_input in tools:
        share = 1.0 / len(tools)
        if name == "Read" and tool_input.get("file_path"):
            out.append((str(tool_input["file_path"]), "read", share))
        elif name in _EDIT_TOOLS:
            path = tool_input.get("file_path") or tool_input.get("notebook_path")
            if path:
                out.append((str(path), "edit", share))
        elif name == "Bash":
            paths = [p for p in bash_read_files(str(tool_input.get("command") or ""))
                     if not any(c in p for c in "$*?{")]  # variables and globs aren't files
            out.extend((p, "read", share / len(paths)) for p in paths)
    return out


def session_detail(key: SessionKey, calls: List[Call], meta: Optional[SessionMeta],
                   namer: Namer) -> SessionDetail:
    """the calls must be the session's (main conversation and subagents), sorted by time"""
    cwd = meta.cwd if meta else None
    models: Dict[str, ModelUse] = {}
    efforts: DefaultDict[str, Usage] = collections.defaultdict(Usage)
    fast = Usage()
    agents: Dict[str, AgentUse] = {}
    files: Dict[str, FileUse] = {}
    skills: Counter[str] = collections.Counter()
    searches: Counter[str] = collections.Counter()
    workflows = 0
    for call in calls:
        m = models.setdefault(call.model, ModelUse(call.model))
        m.calls += 1
        m.sub_calls += call.is_subagent
        m.weighted += call.weighted
        m.tokens.update(call.tokens)
        e = efforts[call.effort or "?"]
        e.calls += 1
        e.weighted += call.weighted
        if call.speed == "fast":
            fast.calls += 1
            fast.weighted += call.weighted
        if call.is_subagent:
            agent_id = call.agent_id or "sidechain"
            a = agents.get(agent_id)
            if a is None:
                a = agents[agent_id] = AgentUse(
                    agent_id, namer.agent_type(call.agent_type) if call.agent_type
                    else L("(nieznany typ)", "(unknown type)"),
                    namer.topic(call.agent_task), call.time)
            a.models[call.model] += 1
            a.calls += 1
            a.weighted += call.weighted
        for name, tool_input in call.tools.values():
            if name == "Skill" and tool_input.get("skill"):
                skills[str(tool_input["skill"])] += 1
            elif name == "Workflow":
                workflows += 1
            elif name in ("Grep", "Glob") and tool_input.get("pattern") and not namer.private:
                searches[str(tool_input["pattern"])[:60]] += 1
        for path, kind, share in _call_files(call):
            name = _display_path(path, cwd, namer)
            f = files.setdefault(name, FileUse(name))
            if kind == "read":
                f.reads += 1
            else:
                f.edits += 1
            f.weighted += call.weighted * share

    rebuilds = SessionRebuilds()
    for _call, gap, waste in iter_rebuilds(calls):
        rebuilds.count += 1
        rebuilds.waste += waste
        rebuilds.longest_gap = max(rebuilds.longest_gap, gap)
    long_calls = [c for c in calls if not c.is_subagent and c.context >= LONG_CONTEXT]

    prompts = meta.prompts if meta else []
    requests = [p for p in prompts if p.kind == "prompt"]
    effort_rank = {level: i for i, level in enumerate(EFFORT_ORDER)}
    return SessionDetail(
        session_id=key[1],
        project=namer.project(meta, key[0]),
        branch=None if namer.private or not meta else meta.git_branch,
        version=meta.version if meta else None,
        start=calls[0].time,
        end=calls[-1].time,
        calls=len(calls),
        weighted=sum(c.weighted for c in calls),
        raw=sum(c.raw for c in calls),
        max_context=max((c.context for c in calls if not c.is_subagent), default=0),
        requests=len(requests),
        notifications=len(prompts) - len(requests),
        compactions=len(meta.compactions) if meta else 0,
        rebuilds=rebuilds,
        long_calls=len(long_calls),
        long_weighted=sum(c.weighted for c in long_calls),
        models=sorted(models.values(), key=lambda m: -m.weighted),
        efforts=sorted(efforts.items(), key=lambda kv: effort_rank.get(kv[0], 99)),
        fast=fast,
        ultracode_on=list(meta.ultracode) if meta else [],
        ultracode_requests=sum(1 for p in requests if _ULTRACODE_WORD.search(p.text)),
        workflows=workflows,
        agents=sorted(agents.values(), key=lambda a: -a.weighted),
        skills=skills,
        files=sorted(files.values(), key=lambda f: -f.weighted)[:TOP_FILES],
        n_files=len(files),
        searches=collections.Counter(dict(searches.most_common(TOP_SEARCHES))),
    )


def details_for(calls: List[Call], sessions: Dict[SessionKey, SessionMeta], keys: List[SessionKey],
                namer: Namer) -> Dict[SessionKey, SessionDetail]:
    """details of several sessions from one list of calls"""
    by_session: DefaultDict[SessionKey, List[Call]] = collections.defaultdict(list)
    wanted = set(keys)
    for call in calls:
        if call.session_key in wanted:
            by_session[call.session_key].append(call)
    return {k: session_detail(k, by_session[k], sessions.get(k), namer)
            for k in keys if by_session[k]}


def ultracode_text(d: SessionDetail) -> str:
    """one line: was ultracode on, and how it showed"""
    parts = []
    if d.ultracode_on:
        times = ", ".join(f"{t.astimezone():%m-%d %H:%M}" for t in d.ultracode_on[:3])
        parts.append(L(f"włączony ({times})", f"on ({times})"))
    if d.ultracode_requests:
        parts.append(L(f"słowo „ultracode” w {d.ultracode_requests} prośbach",
                       f"the 'ultracode' keyword in {d.ultracode_requests} requests"))
    if d.workflows:
        parts.append(L(f"narzędzie Workflow: {d.workflows}×", f"Workflow tool: {d.workflows}×"))
    return "; ".join(parts) if parts else L("nie", "no")
