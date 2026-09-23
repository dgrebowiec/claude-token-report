"""Reading Claude Code transcripts (~/.claude/projects/**/*.jsonl) into model calls and sessions."""
from __future__ import annotations

import datetime
import glob
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Iterator, List, NamedTuple, Optional, Tuple

from .pricing import context_size, split_usage, weighted_by_type

SessionKey = Tuple[str, str]                  # (project dir, main session id)
FileKey = Tuple[str, str, Optional[str]]      # SessionKey + agent id / "sidechain" / None


class TranscriptFile(NamedTuple):
    path: str
    proj_dir: str
    session_id: str
    agent_id: Optional[str]  # None for the main conversation


class Prompt(NamedTuple):
    time: datetime.datetime
    kind: str  # "prompt" (typed by the user) or "notif" (background task notification)
    text: str


@dataclass
class SessionMeta:
    proj_dir: str
    cwd: Optional[str] = None
    topic: str = ""  # the first real request
    prompts: List[Prompt] = field(default_factory=list)
    compactions: List[Tuple[datetime.datetime, FileKey]] = field(default_factory=list)


@dataclass
class Call:
    """one API call (one model response), deduplicated by message id"""
    time: datetime.datetime
    model: str
    session_key: SessionKey
    file_key: FileKey
    agent_id: Optional[str]
    is_subagent: bool
    usage: Optional[Dict[str, Any]] = None
    tools: Dict[Any, Tuple[str, Dict[str, Any]]] = field(default_factory=dict)
    agent_type: Optional[str] = None
    # filled in by _finish() once the last usage record of the message is known
    tokens: Dict[str, int] = field(default_factory=dict)
    weighted_by_type: Dict[str, float] = field(default_factory=dict)
    weighted: float = 0.0
    context: int = 0

    def _finish(self) -> None:
        self.tokens = split_usage(self.usage or {})
        self.weighted_by_type = weighted_by_type(self.tokens, self.model)
        self.weighted = sum(self.weighted_by_type.values())
        self.context = context_size(self.tokens)

    @property
    def raw(self) -> int:
        return sum(self.tokens.values())


# --------------------------------------------------------------------------- files

def default_root() -> str:
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    return os.path.join(base, "projects")


def _agent_id(filename: str) -> str:
    stem = filename[:-len(".jsonl")]
    return stem[len("agent-"):] if stem.startswith("agent-") else stem


def transcript_files(root: str) -> Iterator[TranscriptFile]:
    """<root>/<project>/<session>.jsonl and <root>/<project>/<session>/subagents/<agent>.jsonl"""
    for path in glob.glob(os.path.join(root, "*", "**", "*.jsonl"), recursive=True):
        rel = os.path.relpath(path, root).split(os.sep)
        if len(rel) == 2:
            yield TranscriptFile(path, rel[0], rel[1][:-len(".jsonl")], None)
        elif len(rel) == 4 and rel[2] == "subagents":
            yield TranscriptFile(path, rel[0], rel[1], _agent_id(rel[3]))


def _main_transcripts(root: str) -> Iterator[Tuple[float, TranscriptFile]]:
    """(mtime, file) of every main conversation transcript"""
    for tf in transcript_files(root):
        if tf.agent_id:
            continue
        try:
            yield os.path.getmtime(tf.path), tf
        except OSError:
            continue


def find_session(root: str, ident: Optional[str]) -> Optional[Tuple[SessionKey, List[TranscriptFile]]]:
    """most recent main transcript whose id starts with / contains ident ('latest' = newest),
    together with the transcripts of its subagents"""
    ident = (ident or "latest").lower()
    best = None
    for mtime, tf in _main_transcripts(root):
        sid = tf.session_id.lower()
        if ident in ("latest", "last"):
            score = 1
        elif sid == ident:
            score = 3
        elif sid.startswith(ident):
            score = 2
        elif ident in sid:
            score = 1
        else:
            continue
        if best is None or (score, mtime) > best[0]:
            best = ((score, mtime), tf)
    if not best:
        return None
    main = best[1]
    files = [main]
    pattern = os.path.join(os.path.dirname(main.path), main.session_id, "subagents", "*.jsonl")
    for path in sorted(glob.glob(pattern)):
        files.append(TranscriptFile(path, main.proj_dir, main.session_id,
                                    _agent_id(os.path.basename(path))))
    return (main.proj_dir, main.session_id), files


def recent_sessions(root: str, n: int) -> List[Tuple[float, TranscriptFile]]:
    """the n most recently used main transcripts, newest first"""
    return sorted(_main_transcripts(root), reverse=True)[:n]


# --------------------------------------------------------------------------- prompts

_STRIP_BLOCKS = re.compile(
    r"<(system-reminder|local-command-stdout|local-command-stderr|local-command-caveat)>"
    r".*?</\1>", re.S)
_AGENT_ID = re.compile(r"agentId:\s*([0-9a-zA-Z_-]{6,40})")


def _user_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(x.get("text", "") for x in content
                        if isinstance(x, dict) and x.get("type") == "text")
    return ""


def _clean_prompt(txt: str) -> str:
    txt = _STRIP_BLOCKS.sub(" ", txt or "")
    command = re.search(r"<command-name>(.*?)</command-name>", txt, re.S)
    args = re.search(r"<command-args>(.*?)</command-args>", txt, re.S)
    if command:
        txt = command.group(1).strip() + " " + (args.group(1).strip() if args else "")
    txt = re.sub(r"<[^>]+>", " ", txt)
    return re.sub(r"\s+", " ", txt).strip()


def _is_tool_result(x: Any) -> bool:
    return isinstance(x, dict) and x.get("type") == "tool_result"


# --------------------------------------------------------------------------- parsing

def _parse_time(value: Any) -> datetime.datetime:
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


class _Loader:
    def __init__(self, start: Optional[datetime.datetime], end: Optional[datetime.datetime]):
        self.start, self.end = start, end
        self.calls: Dict[str, Call] = {}
        self.sessions: Dict[SessionKey, SessionMeta] = {}
        # subagent type: from <agent>.meta.json, or matched Agent tool_use -> its result's agentId
        self.type_by_agent_meta: Dict[str, str] = {}
        self.type_by_tool_use: Dict[str, str] = {}
        self.agent_by_tool_use: Dict[str, str] = {}

    def in_window(self, t: datetime.datetime) -> bool:
        return (self.start is None or t >= self.start) and (self.end is None or t <= self.end)

    def read_file(self, tf: TranscriptFile, skip_old: bool) -> None:
        try:
            if skip_old and self.start and datetime.datetime.fromtimestamp(
                    os.path.getmtime(tf.path), datetime.timezone.utc) < self.start:
                return  # file not touched inside the window
        except OSError:
            return
        if tf.agent_id:
            self._read_agent_meta(tf)
        sess = self.sessions.setdefault((tf.proj_dir, tf.session_id), SessionMeta(tf.proj_dir))
        try:
            fh = open(tf.path, encoding="utf-8", errors="replace")
        except OSError:
            return
        with fh:
            for line in fh:
                if '"timestamp"' not in line:
                    continue
                try:
                    record = json.loads(line)
                    t = _parse_time(record["timestamp"])
                except (ValueError, KeyError, TypeError, AttributeError):
                    continue
                self._record(record, t, tf, sess)

    def _read_agent_meta(self, tf: TranscriptFile) -> None:
        try:
            with open(tf.path[:-len(".jsonl")] + ".meta.json", encoding="utf-8") as f:
                meta = json.load(f)
            if meta.get("agentType"):
                self.type_by_agent_meta[tf.agent_id] = meta["agentType"]
        except (OSError, ValueError):
            pass

    def _record(self, record: Dict[str, Any], t: datetime.datetime, tf: TranscriptFile,
                sess: SessionMeta) -> None:
        if not sess.cwd and record.get("cwd"):
            sess.cwd = record["cwd"]
        message = record.get("message") or {}
        if not isinstance(message, dict):
            message = {}
        sidechain = bool(record.get("isSidechain"))
        file_key = (tf.proj_dir, tf.session_id, tf.agent_id or ("sidechain" if sidechain else None))
        kind = record.get("type")
        if kind == "system" and record.get("subtype") == "compact_boundary":
            sess.compactions.append((t, file_key))
        elif kind == "assistant":
            self._assistant(message, record, t, tf, file_key, bool(tf.agent_id) or sidechain)
        elif kind == "user":
            self._user(message, record, t, sess, bool(tf.agent_id) or sidechain)

    def _assistant(self, message: Dict[str, Any], record: Dict[str, Any], t: datetime.datetime,
                   tf: TranscriptFile, file_key: FileKey, is_subagent: bool) -> None:
        content = message.get("content") if isinstance(message.get("content"), list) else []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use" and \
                    block.get("name") in ("Agent", "Task") and block.get("id"):
                self.type_by_tool_use[block["id"]] = (block.get("input") or {}).get(
                    "subagent_type") or "general-purpose"
        model = message.get("model") or "?"
        msg_id = message.get("id") or record.get("requestId") or record.get("uuid")
        if not self.in_window(t) or model == "<synthetic>" or not msg_id:
            return
        call = self.calls.get(msg_id)
        if call is None:
            call = self.calls[msg_id] = Call(
                time=t, model=model, session_key=(tf.proj_dir, tf.session_id),
                file_key=file_key, agent_id=tf.agent_id, is_subagent=is_subagent)
        if message.get("usage"):
            call.usage = message["usage"]  # a message is logged in parts; the last usage wins
        for i, block in enumerate(content):
            if isinstance(block, dict) and block.get("type") == "tool_use":
                call.tools[block.get("id") or (len(call.tools), i)] = (
                    block.get("name"), block.get("input") or {})

    def _user(self, message: Dict[str, Any], record: Dict[str, Any], t: datetime.datetime,
              sess: SessionMeta, is_subagent: bool) -> None:
        content = message.get("content")
        is_result = isinstance(content, list) and any(_is_tool_result(x) for x in content)
        if is_result:
            self._remember_agent_ids(content)
        if is_result or is_subagent or record.get("isMeta") or record.get("isCompactSummary"):
            return
        raw = _user_text(content)
        if "<task-notification>" in raw:
            summary = re.search(r"<summary>(.*?)(</summary>|$)", raw, re.S)
            text, kind = _clean_prompt(summary.group(1) if summary else raw), "notif"
        else:
            text, kind = _clean_prompt(raw), "prompt"
        if not text or text.startswith(("Caveat:", "[Request interrupted")):
            return
        bare_command = text.startswith("/") and len(text.split()) == 1
        if kind == "prompt" and not sess.topic and not bare_command:
            sess.topic = text[:150]
        if self.in_window(t):
            sess.prompts.append(Prompt(t, kind, text[:300]))

    def _remember_agent_ids(self, content: List[Any]) -> None:
        """an Agent tool result says which subagent transcript (agentId) it came from"""
        for x in content:
            if _is_tool_result(x) and x.get("tool_use_id") in self.type_by_tool_use:
                match = _AGENT_ID.search(_user_text(x.get("content")))
                if match:
                    self.agent_by_tool_use[x["tool_use_id"]] = match.group(1)

    def result(self) -> Tuple[List[Call], Dict[SessionKey, SessionMeta]]:
        type_by_agent = dict(self.type_by_agent_meta)
        for tool_use_id, agent_id in self.agent_by_tool_use.items():
            type_by_agent.setdefault(agent_id, self.type_by_tool_use.get(tool_use_id))
        out = []
        for call in self.calls.values():
            if not call.usage:
                continue
            call.agent_type = type_by_agent.get(call.agent_id) if call.is_subagent else None
            call._finish()
            out.append(call)
        out.sort(key=lambda c: c.time)
        return out, self.sessions


def load(root: str, start: Optional[datetime.datetime], end: Optional[datetime.datetime],
         files: Optional[Iterable[TranscriptFile]] = None
         ) -> Tuple[List[Call], Dict[SessionKey, SessionMeta]]:
    """Parses transcripts (all under root, or just `files`).
    Returns the calls inside [start, end] sorted by time, and metadata of every session read."""
    loader = _Loader(start, end)
    for tf in (files if files is not None else transcript_files(root)):
        loader.read_file(tf, skip_old=files is None)
    return loader.result()
