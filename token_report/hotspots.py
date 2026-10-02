"""What Claude looks up again and again in a project, and whether CLAUDE.md already says it.

A symbol or file looked up in several conversations is found from scratch in each of them;
a line in CLAUDE.md (or a path-scoped rule) would save that search.
"""
from __future__ import annotations

import collections
import glob
import os
import re
from dataclasses import dataclass, field
from typing import (TYPE_CHECKING, DefaultDict, Dict, Iterable, Iterator, List, Mapping,
                    Optional, Sequence, Set, Tuple)

from .classify import file_commands
from .naming import split_worktree

if TYPE_CHECKING:
    from .transcripts import Call, SessionKey, SessionMeta

MIN_USES = 5  # lookups of one symbol / file ...
MIN_SESSIONS = 2  # ... in at least this many conversations (1 when there is only one)
TOP_ITEMS = 8
TOP_PROJECTS = 3
LONG_INSTRUCTIONS = 200  # lines; the Claude Code docs advise keeping a CLAUDE.md under this
LARGE_FILE = 800  # lines; Claude reads such files in pieces
MAX_IMPORT_DEPTH = 4  # like Claude Code's @import

_INSTRUCTION_NAMES = ("CLAUDE.md", os.path.join(".claude", "CLAUDE.md"), "CLAUDE.local.md")
_SKIP_NAMES = {"CLAUDE.md", "CLAUDE.local.md", "AGENTS.md"}
_SKIP_DIRS = (".git", ".claude", "node_modules", "build", "dist", "__pycache__")
_READ_COMMANDS = {"cat", "head", "tail", "sed", "nl", "bat", "less", "more"}
_GREP_COMMANDS = {"grep", "egrep", "fgrep", "rg", "ag", "ack", "git"}  # git grep
_GREP_VALUE_OPTS = {"-A", "-B", "-C", "-m", "-g", "-t", "-T", "-f", "-j", "-d", "-D",
                    "--include", "--exclude", "--exclude-dir", "--glob", "--type",
                    "--type-not", "--max-count", "--context", "--after-context",
                    "--before-context", "--max-depth", "--threads"}
_FIND_PATTERN_OPTS = {"-name", "-iname", "-path", "-ipath", "-regex", "-iregex"}

_ESCAPE = re.compile(r"\\[A-Za-z]")  # \b \w \s ... in regexes, so "\bFoo" gives "Foo"
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SYMBOL = re.compile(r"[a-z0-9][A-Z]|[A-Za-z0-9]_[A-Za-z0-9]")  # camelCase or snake_case
_NOT_SYMBOLS = {"node_modules", "site_packages", "dist_packages"}
_CODE = re.compile(r"```.*?```|`[^`\n]*`", re.S)
_IMPORT = re.compile(r"(?<![\w`])@((?:[^\s`\\]|\\ )+)")
_MD_LINK = re.compile(r"\]\(([^)\s#]+\.md)\)|`([^`\s]+\.md)`")  # [map](docs/map.md) or `docs/map.md`


# --------------------------------------------------------------------------- results

@dataclass
class Item:
    """one row: a symbol or a file (path relative to the project)"""
    name: str
    uses: int
    sessions: int
    documented: Optional[bool]  # None: the project has no instruction files
    linked: bool = False  # not in the instructions, but in a .md file they link to (a map)
    lines: Optional[int] = None  # files: length on disk
    path: Optional[str] = None  # symbols: the file named after it, if Claude read one


@dataclass
class InstructionFile:
    name: str  # relative to the project, or ~-relative
    lines: int


@dataclass
class ProjectHotspots:
    root: str
    files: List[Item] = field(default_factory=list)
    symbols: List[Item] = field(default_factory=list)
    instructions: List[InstructionFile] = field(default_factory=list)

    @property
    def uses(self) -> int:
        return sum(i.uses for i in self.files + self.symbols)

    def long_instructions(self) -> List[InstructionFile]:
        return [f for f in self.instructions if f.lines > LONG_INSTRUCTIONS]

    def missing(self) -> List[Item]:
        return [i for i in self.files + self.symbols if not i.documented and not i.linked]

    def draft(self) -> List[str]:
        """lines to paste into CLAUDE.md: the undocumented files and symbols (a symbol together
        with the file named after it)"""
        missing = self.missing()
        with_symbol = {i.path for i in missing if i.path}
        lines = []
        for item in missing:
            if item.path:
                lines.append(f"- `{item.name}` — `{item.path}` — …")
            elif item.name not in with_symbol:
                lines.append(f"- `{item.name}` — …")
        return lines


@dataclass
class _Lookup:
    uses: int = 0
    sessions: Set["SessionKey"] = field(default_factory=set)

    def add(self, session: "SessionKey") -> None:
        self.uses += 1
        self.sessions.add(session)


# --------------------------------------------------------------------------- lookups

def symbols_in(pattern: str) -> Set[str]:
    """camelCase / snake_case identifiers in a search pattern (regex or glob)"""
    text = _ESCAPE.sub(" ", str(pattern or ""))
    return {w for w in _WORD.findall(text)
            if len(w) >= 4 and _SYMBOL.search(w) and w.lower() not in _NOT_SYMBOLS}


def _grep_args(words: Sequence[str]) -> Tuple[List[str], List[str]]:
    """(patterns, paths searched) of a grep / rg / git grep command"""
    args = list(words[1:])
    if os.path.basename(words[0]) == "git":
        if not args or args[0] != "grep":
            return [], []
        args = args[1:]
    patterns, positional, i = [], [], 0
    while i < len(args):
        arg = args[i]
        if arg in ("-e", "--regexp") and i + 1 < len(args):
            patterns.append(args[i + 1])
            i += 2
        elif arg.startswith("--regexp="):
            patterns.append(arg.split("=", 1)[1])
            i += 1
        elif arg in _GREP_VALUE_OPTS:
            i += 2
        elif arg == "--":
            positional.extend(args[i + 1:])
            break
        elif arg.startswith("-") and len(arg) > 1:
            i += 1
        else:
            positional.append(arg)
            i += 1
    if patterns:
        return patterns, positional
    return positional[:1], positional[1:]


def _symbols(patterns: Iterable[str], paths: List[str]) -> Iterator[Tuple[str, str, List[str]]]:
    for pattern in patterns:
        for symbol in symbols_in(pattern):
            yield "symbol", symbol, paths


_Lookups = Iterator[Tuple[str, str, List[str]]]


def _bash_lookups(command: str) -> _Lookups:
    for words, base in _with_cd(file_commands(command)):
        for kind, value, paths in _command_lookups(words):
            if base is None:
                yield kind, value, paths
            elif kind == "symbol":
                yield kind, value, [os.path.join(base, p) for p in paths] or [base]
            else:
                yield kind, os.path.join(base, value), paths


def _with_cd(commands: List[Sequence[str]]) -> Iterator[Tuple[Sequence[str], Optional[str]]]:
    """each command with the directory a preceding `cd` moved to (None: the session's cwd)"""
    base: Optional[str] = None
    for words in commands:
        if words[0] in ("cd", "pushd"):
            target = words[1] if len(words) > 1 else "~"
            base = os.path.join(base, target) if base else target
        else:
            yield words, base


def _command_lookups(words: Sequence[str]) -> _Lookups:
    name = os.path.basename(words[0])
    if name in _GREP_COMMANDS:
        yield from _symbols(*_grep_args(words))
    elif name == "find":
        paths = []
        for word in words[1:]:
            if word.startswith(("-", "(", "!")):
                break
            paths.append(word)
        yield from _symbols([v for o, v in zip(words, words[1:]) if o in _FIND_PATTERN_OPTS],
                            paths)
    elif name == "fd":
        positional = [w for w in words[1:] if not w.startswith("-")]
        yield from _symbols(positional[:1], positional[1:])
    elif name in _READ_COMMANDS and "-i" not in words:
        for arg in words[1:]:
            if not arg.startswith("-") and ("." in arg or "/" in arg):
                yield "bash_file", arg, []


def _lookups(name: str, tool_input: Mapping) -> _Lookups:
    """(kind, value, paths searched): ("symbol", name, paths), ("file", path, []) or
    ("bash_file", path that may not be a file, [])"""
    if name == "Read":
        path = tool_input.get("file_path")
        if path:
            yield "file", str(path), []
    elif name in ("Grep", "Glob"):
        path = tool_input.get("path")
        yield from _symbols([tool_input.get("pattern", "")], [str(path)] if path else [])
    elif name == "Bash":
        yield from _bash_lookups(tool_input.get("command", ""))


def _inside(path: str, cwd: str, root: str) -> bool:
    path = os.path.normpath(os.path.join(cwd, os.path.expanduser(path)))
    return any(path == base or path.startswith(base.rstrip(os.sep) + os.sep)
               for base in (cwd, root))


def _relative(path: str, cwd: str, root: str) -> Optional[str]:
    """path relative to the project, or None when it lies outside it or is not interesting"""
    path = os.path.normpath(os.path.join(cwd, os.path.expanduser(path)))
    for base in (cwd, root):
        if path.startswith(base.rstrip(os.sep) + os.sep):
            rel = os.path.relpath(path, base)
            parts = rel.split(os.sep)
            if parts[0] in _SKIP_DIRS or os.path.basename(rel) in _SKIP_NAMES:
                return None
            return rel
    return None


# --------------------------------------------------------------------------- instruction files

def _read(path: str) -> Optional[str]:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def _display(path: str, root: str, home: str) -> str:
    if path.startswith(root.rstrip(os.sep) + os.sep):
        return os.path.relpath(path, root)
    if path.startswith(home + os.sep):
        return "~/" + os.path.relpath(path, home)
    return path


def instruction_files(root: str, home: str) -> List[Tuple[str, str]]:
    """(path, text) of what Claude Code loads as instructions in this project: CLAUDE.md files
    here and above (or AGENTS.md when there is none), their @imports, .claude/rules, and the
    user-level ones"""
    found: List[Tuple[str, str]] = []
    seen: Set[str] = set()

    def add(path: str, depth: int = 0) -> None:
        real = os.path.realpath(path)
        if real in seen or not os.path.isfile(path):
            return
        text = _read(path)
        if text is None:
            return
        seen.add(real)
        found.append((path, text))
        if depth >= MAX_IMPORT_DEPTH:
            return
        for match in _IMPORT.finditer(_CODE.sub(" ", text)):
            target = os.path.expanduser(match.group(1).replace("\\ ", " "))
            add(os.path.join(os.path.dirname(path), target), depth + 1)

    user_dir = os.path.join(home, ".claude")
    directory = root
    while True:
        for name in _INSTRUCTION_NAMES:
            if directory != home or name == "CLAUDE.md":  # ~/.claude/CLAUDE.md is user-level
                add(os.path.join(directory, name))
        parent = os.path.dirname(directory)
        if parent == directory:
            break
        directory = parent
    if not found:
        add(os.path.join(root, "AGENTS.md"))
        add(os.path.join(root, ".claude", "AGENTS.md"))
    add(os.path.join(user_dir, "CLAUDE.md"))
    for rules in (os.path.join(root, ".claude", "rules"), os.path.join(user_dir, "rules")):
        for path in sorted(glob.glob(os.path.join(rules, "**", "*.md"), recursive=True)):
            add(path)
    return found


def linked_docs(root: str, loaded: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    """(path, text) of project .md files the instructions link to, e.g. a project map that
    CLAUDE.md tells Claude to read first; they load only when Claude reads them"""
    seen = {os.path.realpath(p) for p, _ in loaded}
    found = []
    for path, text in loaded:
        for match in _MD_LINK.finditer(text):
            target = os.path.expanduser(match.group(1) or match.group(2))
            for base in (os.path.dirname(path), root):
                full = os.path.normpath(os.path.join(base, target))
                real = os.path.realpath(full)
                if not full.startswith(root.rstrip(os.sep) + os.sep) or real in seen \
                        or not os.path.isfile(full):
                    continue
                linked = _read(full)
                if linked is not None:
                    seen.add(real)
                    found.append((full, linked))
                break
    return found


def _mentions(text: str, word: str) -> bool:
    return re.search(r"(?<![\w])" + re.escape(word) + r"(?![\w])", text) is not None


def _file_documented(text: str, rel: str) -> bool:
    base = os.path.basename(rel)
    stem = os.path.splitext(base)[0]
    return rel in text or base in text or (len(stem) >= 6 and _mentions(text, stem))


def _line_count(path: str) -> Optional[int]:
    try:
        if os.path.getsize(path) > 5_000_000:
            return None
        with open(path, "rb") as f:
            return sum(1 for _ in f)
    except OSError:
        return None


# --------------------------------------------------------------------------- aggregation

def find_hotspots(calls: List["Call"], sessions: Mapping["SessionKey", "SessionMeta"],
                  home: Optional[str] = None) -> List[ProjectHotspots]:
    """projects with symbols / files looked up in several conversations, most first"""
    home = os.path.normpath(home or os.path.expanduser("~"))
    files: DefaultDict[str, DefaultDict[str, _Lookup]] = collections.defaultdict(
        lambda: collections.defaultdict(_Lookup))
    symbols: DefaultDict[str, DefaultDict[str, _Lookup]] = collections.defaultdict(
        lambda: collections.defaultdict(_Lookup))
    exists: Dict[str, bool] = {}
    for call in calls:
        meta = sessions.get(call.session_key)
        cwd = os.path.normpath(meta.cwd) if meta and meta.cwd else None
        if not cwd:
            continue
        root = split_worktree(cwd)[0]
        if root in (home, os.sep):
            continue  # not a project
        for name, tool_input in call.tools.values():
            for kind, value, searched in _lookups(name, tool_input or {}):
                if kind == "symbol":
                    if all(_inside(p, cwd, root) for p in searched):  # not another project
                        symbols[root][value].add(call.session_key)
                    continue
                rel = _relative(value, cwd, root)
                if rel is None:
                    continue
                if kind == "bash_file":  # an argument of cat/sed/...: count it only if a file
                    full = os.path.join(root, rel)
                    if full not in exists:
                        exists[full] = os.path.isfile(full)
                    if not exists[full]:
                        continue
                files[root][rel].add(call.session_key)

    min_sessions = MIN_SESSIONS if len({c.session_key for c in calls}) > 1 else 1
    out = []
    for root in set(files) | set(symbols):
        project = _project_hotspots(root, home, files[root], symbols[root], min_sessions)
        if project.files or project.symbols:
            out.append(project)
    out.sort(key=lambda p: -p.uses)
    return out[:TOP_PROJECTS]


def _merge_case(lookups: Mapping[str, _Lookup]) -> Dict[str, _Lookup]:
    """UserManager and userManager are one thing to look up; keep the most used spelling"""
    groups: DefaultDict[str, List[Tuple[str, _Lookup]]] = collections.defaultdict(list)
    for name, lookup in lookups.items():
        groups[name.lower()].append((name, lookup))
    out = {}
    for variants in groups.values():
        name = max(variants, key=lambda v: (v[1].uses, v[0][0].isupper(), v[0]))[0]
        merged = _Lookup()
        for _, lookup in variants:
            merged.uses += lookup.uses
            merged.sessions |= lookup.sessions
        out[name] = merged
    return out


def _hot(lookups: Mapping[str, _Lookup], min_sessions: int) -> List[Tuple[str, _Lookup]]:
    items = [(k, v) for k, v in lookups.items()
             if v.uses >= MIN_USES and len(v.sessions) >= min_sessions]
    items.sort(key=lambda kv: (-kv[1].uses, -len(kv[1].sessions), kv[0]))
    return items[:TOP_ITEMS]


def _project_hotspots(root: str, home: str, files: Mapping[str, _Lookup],
                      symbols: Mapping[str, _Lookup], min_sessions: int) -> ProjectHotspots:
    loaded = instruction_files(root, home)
    text = "\n".join(t for _, t in loaded)
    linked = "\n".join(t for _, t in linked_docs(root, loaded))
    project = ProjectHotspots(root, instructions=[
        InstructionFile(_display(p, root, home), t.count("\n") + (not t.endswith("\n")))
        for p, t in loaded])

    def documented(check) -> Optional[bool]:
        return check() if loaded else None

    for rel, lookup in _hot(files, min_sessions):
        item = Item(rel, lookup.uses, len(lookup.sessions),
                    documented(lambda: _file_documented(text, rel)),
                    lines=_line_count(os.path.join(root, rel)))
        item.linked = not item.documented and _file_documented(linked, rel)
        project.files.append(item)
    # a symbol named like a file Claude read (UserManager -> .../UserManager.kt) is defined there
    by_stem: Dict[str, Tuple[int, str]] = {}
    for rel, lookup in files.items():
        stem = os.path.splitext(os.path.basename(rel))[0].lower()
        if lookup.uses > by_stem.get(stem, (0, ""))[0]:
            by_stem[stem] = (lookup.uses, rel)
    for symbol, lookup in _hot(_merge_case(symbols), min_sessions):
        item = Item(symbol, lookup.uses, len(lookup.sessions),
                    documented(lambda: _mentions(text, symbol)),
                    path=by_stem.get(symbol.lower(), (0, None))[1])
        item.linked = not item.documented and _mentions(linked, symbol)
        project.symbols.append(item)
    return project
