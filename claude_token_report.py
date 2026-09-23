#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
claude_token_report.py — where do your Claude Code tokens actually go?

Reads ONLY the local Claude Code transcripts (~/.claude/projects/**/*.jsonl).
Sends nothing anywhere, calls no API, uses 0 tokens. Python 3.8+, no dependencies.

  python3 claude_token_report.py               # last 7 days
  python3 claude_token_report.py --explain     # what raw and weighted tokens mean
  python3 claude_token_report.py --html r.html # HTML report
  python3 claude_token_report.py --help        # all options
"""
import argparse
import collections
import datetime
import glob
import html
import json
import os
import re
import shlex
import textwrap
import urllib.parse
import sys

# --------------------------------------------------------------------------- language

LANG = "en"


def L(pl, en):
    return pl if LANG == "pl" else en


def detect_lang(argv):
    """English by default; -l pl / --lang pl switches to Polish"""
    for i, a in enumerate(argv):
        if a in ("-l", "--lang") and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--lang="):
            return a.split("=", 1)[1]
        if a.startswith("-l") and not a.startswith("--") and len(a) > 2:
            return a[2:].lstrip("=")
    return "en"


WEEKDAYS_PL = ("pon", "wt", "śr", "czw", "pt", "sob", "nd")
WEEKDAYS_EN = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def wd(d):
    return (WEEKDAYS_PL if LANG == "pl" else WEEKDAYS_EN)[d.weekday()]


# --------------------------------------------------------------------------- weights

# How much each token counts, in "weighted tokens": one weighted token = one normal (uncached)
# input token of the reference model (Opus 5). Anthropic does not publish the formula behind
# subscription usage limits; relative API prices are the best public proxy — a pricier model
# or token type uses the limit faster. Only the ratios below matter, not the money.
W_INPUT, W_CACHE_READ, W_WRITE_5M, W_WRITE_1H, W_OUTPUT = 1.0, 0.1, 1.25, 2.0, 5.0

# Relative API prices per 1M tokens: (substring of model id, input, output, cache read).
# Checked in order — more specific names first. Override with --prices FILE.
PRICES = [
    ("fable-5-1", 10.0, 50.0, 0.25),
    ("mythos-5-1", 10.0, 50.0, 0.25),
    ("fable-5", 10.0, 50.0, 1.00),
    ("mythos-5", 10.0, 50.0, 1.00),
    ("opus-5-5", 4.0, 20.0, 0.20),
    ("opus-5", 5.0, 25.0, 0.50),
    ("opus-4-8", 5.0, 25.0, 0.50),
    ("opus-4-7", 5.0, 25.0, 0.50),
    ("opus-4-6", 5.0, 25.0, 0.50),
    ("opus-4-5", 5.0, 25.0, 0.50),
    ("opus-4", 15.0, 75.0, 1.50),      # Opus 4 / 4.1
    ("3-opus", 15.0, 75.0, 1.50),
    ("sonnet-5", 2.0, 10.0, 0.20),
    ("sonnet", 3.0, 15.0, 0.30),       # Sonnet 3.7 / 4 / 4.5 / 4.6
    ("haiku-4-5", 1.0, 5.0, 0.10),
    ("3-5-haiku", 0.8, 4.0, 0.08),
    ("3-haiku", 0.25, 1.25, 0.025),
    ("haiku", 1.0, 5.0, 0.10),
]
REF_PRICE = 5.0  # input price of the reference model (Opus 5) -> model weight 1.0
FALLBACK_PRICE = ("opus-5", 5.0, 25.0, 0.50)
UNKNOWN_MODELS = set()


def price_for(model):
    ml = (model or "").lower()
    for pat, pin, pout, pcr in PRICES:
        if pat in ml:
            return pin, pout, pcr
    UNKNOWN_MODELS.add(model or "?")
    return FALLBACK_PRICE[1:]


def model_weight(model):
    return price_for(model)[0] / REF_PRICE


def load_prices(path):
    """JSON: {"model-substring": [input, output, cache_read], ...} — prepended to the table."""
    with open(path) as f:
        data = json.load(f)
    extra = [(k.lower(), float(v[0]), float(v[1]), float(v[2])) for k, v in data.items()]
    PRICES[:0] = extra


# --------------------------------------------------------------------------- tokens

TYPES = ("input", "cache_read", "cache_write_5m", "cache_write_1h", "output")
WEIGHTS = {"input": W_INPUT, "cache_read": W_CACHE_READ, "cache_write_5m": W_WRITE_5M,
           "cache_write_1h": W_WRITE_1H, "output": W_OUTPUT}


def type_name(t):
    return {
        "input": L("wejście (nowy tekst)", "input (new text)"),
        "cache_read": L("odczyt z cache", "cache read"),
        "cache_write_5m": L("zapis do cache 5 min", "cache write 5 min"),
        "cache_write_1h": L("zapis do cache 1 h", "cache write 1 h"),
        "output": L("wyjście (odpowiedź)", "output (response)"),
    }[t]


def split_usage(u):
    cc = u.get("cache_creation") or {}
    c5 = cc.get("ephemeral_5m_input_tokens", 0) or 0
    c1 = cc.get("ephemeral_1h_input_tokens", 0) or 0
    cw = u.get("cache_creation_input_tokens", 0) or 0
    if not c5 and not c1:
        c5 = cw  # older records have no 5m/1h split
    return {"input": u.get("input_tokens", 0) or 0,
            "cache_read": u.get("cache_read_input_tokens", 0) or 0,
            "cache_write_5m": c5, "cache_write_1h": c1,
            "output": u.get("output_tokens", 0) or 0}


def weighted_by_type(tk, model):
    """weighted tokens per token type: token type weight × model weight"""
    pin, pout, pcr = price_for(model)
    return {"input": tk["input"] * pin / REF_PRICE,
            "cache_read": tk["cache_read"] * pcr / REF_PRICE,
            "cache_write_5m": tk["cache_write_5m"] * pin * W_WRITE_5M / REF_PRICE,
            "cache_write_1h": tk["cache_write_1h"] * pin * W_WRITE_1H / REF_PRICE,
            "output": tk["output"] * pout / REF_PRICE}


# --------------------------------------------------------------------------- classification

NO_TOOL = "no_tool"

_PREFIX = {"while", "until", "if", "elif", "then", "do", "else", "!", "time", "nohup",
           "exec", "sudo", "env", "{", "}", "for", "in", "done", "fi", "timeout", "xargs"}
_TRIVIAL = {"cd", "echo", "printf", "export", "source", ".", "set", "true", "false", ":",
            "pwd", "unset", "alias", "which", "command", "type", "test", "[", "[[", "date",
            "yes", "clear", "read", "let", "local", "declare", "shift", "exit", "return"}
_REDIR = re.compile(r"\d*>>?&?\s*[^\s;&|()]+|<\s*[^\s;&|()]+")

BASH_GROUPS = [
    ("bash_search", {"grep", "rg", "egrep", "fgrep", "ag", "ack", "find", "fd", "ls", "tree",
                     "locate", "du"}),
    ("bash_read", {"cat", "head", "tail", "sed", "awk", "wc", "less", "more", "nl", "bat",
                   "file", "stat", "diff", "cmp", "jq", "yq", "sort", "uniq", "cut", "strings",
                   "hexdump", "xxd", "od", "column"}),
    ("bash_git", {"git"}),
    ("bash_gh", {"gh", "glab"}),
    ("bash_pkg", {"pip", "pip3", "uv", "poetry", "pipx", "conda", "apt", "apt-get", "brew",
                  "dnf", "yum", "pacman", "snap", "gem", "composer"}),
    ("bash_build", {"make", "cmake", "ninja", "cargo", "go", "npm", "pnpm", "yarn", "bun",
                    "npx", "bunx", "deno", "tsc", "pytest", "jest", "vitest", "mocha", "tox",
                    "nox", "gradle", "gradlew", "mvn", "mvnw", "ant", "dotnet", "msbuild",
                    "swift", "xcodebuild", "flutter", "dart", "rake", "bundle", "mix",
                    "rustc", "gcc", "g++", "clang", "javac", "kotlinc", "eslint", "prettier",
                    "ruff", "black", "mypy", "pylint", "flake8", "phpunit", "ctest"}),
    ("bash_script", {"python", "python3", "node", "ruby", "perl", "php", "bash", "sh", "zsh",
                     "java", "lua", "Rscript", "julia"}),
    ("bash_container", {"docker", "podman", "docker-compose", "kubectl", "helm", "terraform",
                        "ansible", "vagrant"}),
    ("bash_net", {"curl", "wget", "ssh", "scp", "rsync", "http", "nc", "ping"}),
    ("bash_wait", {"sleep", "wait", "pgrep", "pidof", "ps", "top", "watch", "kill", "pkill",
                   "killall", "lsof"}),
    ("bash_device", {"adb", "emulator", "xcrun", "simctl", "fastlane", "ios-deploy",
                     "idevicesyslog", "scrcpy"}),
    ("bash_browser", {"agent-browser", "playwright", "puppeteer", "chromium", "chromium-browser",
                      "google-chrome", "firefox", "lighthouse", "selenium"}),
    ("bash_fileops", {"mkdir", "cp", "mv", "rm", "touch", "chmod", "chown", "ln", "tar",
                      "zip", "unzip", "gzip", "gunzip", "tee", "rmdir", "install"}),
]
BASH_LOOKUP = {cmd: grp for grp, cmds in BASH_GROUPS for cmd in cmds}


def activity_name(key):
    names = {
        NO_TOOL: L("(bez narzędzia) odpowiedź tekstowa", "(no tool) text reply"),
        "read": L("Read — czytanie plików", "Read — reading files"),
        "edit": L("Edit/Write — zmiany w plikach", "Edit/Write — changing files"),
        "search": L("Grep/Glob — szukanie", "Grep/Glob — searching"),
        "agent": L("Agent — uruchomienie subagenta", "Agent — launching a subagent"),
        "web": L("Web — wyszukiwanie/pobieranie", "Web — search/fetch"),
        "todo": L("lista zadań (Todo/Task)", "task list (Todo/Task)"),
        "skill": "Skill",
        "toolsearch": L("ToolSearch — ładowanie narzędzi", "ToolSearch — loading tools"),
        "ask": L("pytanie do użytkownika", "asking the user"),
        "bg": L("zadania w tle (odczyt/monitor)", "background tasks (poll/monitor)"),
        "plan": L("tryb planowania", "plan mode"),
        "bash_search": L("Bash: szukanie (grep/find/ls)", "Bash: searching (grep/find/ls)"),
        "bash_read": L("Bash: czytanie (cat/head/sed)", "Bash: reading (cat/head/sed)"),
        "bash_git": "Bash: git",
        "bash_gh": "Bash: gh (GitHub/GitLab CLI)",
        "bash_pkg": L("Bash: instalacja pakietów", "Bash: installing packages"),
        "bash_build": L("Bash: build/testy/lint", "Bash: build/test/lint"),
        "bash_script": L("Bash: skrypty (python/node/sh/własne)", "Bash: scripts (python/node/sh/own)"),
        "bash_container": "Bash: docker/k8s/infra",
        "bash_net": L("Bash: sieć (curl/ssh)", "Bash: network (curl/ssh)"),
        "bash_wait": L("Bash: procesy/czekanie (sleep/ps)", "Bash: processes/waiting (ps/sleep)"),
        "bash_device": L("Bash: urządzenia (adb/emulator/xcrun)", "Bash: devices (adb/emulator/xcrun)"),
        "bash_browser": L("Bash: automatyzacja przeglądarki", "Bash: browser automation"),
        "bash_fileops": L("Bash: operacje na plikach", "Bash: file operations"),
        "bash_other": L("Bash: inne", "Bash: other"),
    }
    if key in names:
        return names[key]
    if key.startswith("mcp:"):
        return "MCP: " + key[4:]
    return key


EXPLORE_KEYS = {"read", "search", "bash_search", "bash_read"}


def _tokens(command):
    text = command.replace("\n", " ; ")
    for candidate in (_REDIR.sub(" ", text), text):
        try:
            lex = shlex.shlex(candidate, posix=True, punctuation_chars=";&|()")
            lex.whitespace_split = True
            lex.commenters = ""
            return list(lex)
        except ValueError:
            continue
    return command.split()


def _simple_commands(command):
    """split a shell command on ; && || | and newlines, drop keywords and VAR=... prefixes"""
    cmds, cur = [], []
    for t in _tokens(command):
        if t and not t.strip(";&|()"):
            if cur:
                cmds.append(cur)
            cur = []
        else:
            cur.append(t)
    if cur:
        cmds.append(cur)
    out = []
    for c in cmds:
        c = [t for t in c if t.strip()]
        if not c or c[0] in ("for", "select", "case"):
            continue  # loop header: "for f in a b" — the body comes after "do"
        i = 0
        while i < len(c) and (c[i] in _PREFIX or re.match(r"[A-Za-z_]\w*=", c[i])
                              or (i > 0 and (c[i].startswith("-") or c[i].isdigit()))):
            i += 1
        if i < len(c):
            out.append(c[i:])
    return out


def classify_bash(command):
    for c in _simple_commands(str(command or "")):
        name = os.path.basename(c[0])
        if name in _TRIVIAL:
            continue
        if name in ("npm", "pnpm", "yarn", "bun") and len(c) > 1 and c[1] in (
                "i", "install", "add", "ci", "remove", "uninstall", "update", "upgrade"):
            return "bash_pkg"
        grp = BASH_LOOKUP.get(name)
        if grp:
            return grp
        if name.startswith("python") or "/" in c[0] or \
                re.search(r"\.(sh|py|js|mjs|ts|rb|pl|bash)$", name):
            return "bash_script"  # interpreters and project scripts called by path
        return "bash_other"
    return "bash_other"


def classify_tool(name, inp):
    if name == "Bash":
        return classify_bash((inp or {}).get("command", ""))
    if name == "Read":
        return "read"
    if name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        return "edit"
    if name in ("Grep", "Glob", "LS"):
        return "search"
    if name in ("Agent", "Task", "SendMessage"):
        return "agent"
    if name in ("WebSearch", "WebFetch"):
        return "web"
    if name in ("TodoWrite", "TodoRead", "TaskCreate", "TaskUpdate", "TaskList", "TaskGet"):
        return "todo"
    if name == "Skill":
        return "skill"
    if name == "ToolSearch":
        return "toolsearch"
    if name == "AskUserQuestion":
        return "ask"
    if name in ("BashOutput", "TaskOutput", "Monitor", "KillShell", "KillBash", "TaskStop"):
        return "bg"
    if name in ("EnterPlanMode", "ExitPlanMode"):
        return "plan"
    if name and name.startswith("mcp__"):
        parts = name.split("__")
        return "mcp:" + (parts[1] if len(parts) > 1 else name)
    return name or "?"


# --------------------------------------------------------------------------- loading

def default_root():
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    return os.path.join(base, "projects")


def transcript_files(root):
    """yields (path, proj_dir, main_session_id, agent_id_or_None)"""
    for p in glob.glob(os.path.join(root, "*", "**", "*.jsonl"), recursive=True):
        rel = os.path.relpath(p, root).split(os.sep)
        if len(rel) == 2:
            yield p, rel[0], rel[1][:-6], None
        elif len(rel) == 4 and rel[2] == "subagents":
            f = rel[3][:-6]
            yield p, rel[0], rel[1], (f[len("agent-"):] if f.startswith("agent-") else f)


_STRIP_BLOCKS = re.compile(
    r"<(system-reminder|local-command-stdout|local-command-stderr|local-command-caveat)>"
    r".*?</\1>", re.S)


def _user_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(x.get("text", "") for x in content
                        if isinstance(x, dict) and x.get("type") == "text")
    return ""


def _clean_prompt(txt):
    txt = _STRIP_BLOCKS.sub(" ", txt or "")
    m = re.search(r"<command-name>(.*?)</command-name>", txt, re.S)
    args = re.search(r"<command-args>(.*?)</command-args>", txt, re.S)
    if m:
        txt = m.group(1).strip() + " " + (args.group(1).strip() if args else "")
    txt = re.sub(r"<[^>]+>", " ", txt)
    return re.sub(r"\s+", " ", txt).strip()


def load(root, start, end, files=None):
    """Parses transcripts. Returns (calls, sessions).
    calls: one dict per API call (deduplicated by message id) inside [start, end].
    sessions: (proj_dir, session_id) -> metadata (cwd, topic, prompts, compactions)."""
    calls = {}
    sessions = {}
    tuid_type, tuid_agent, meta_type = {}, {}, {}
    for path, proj_dir, main_sess, agent_id in (files or transcript_files(root)):
        try:
            if start and files is None and datetime.datetime.fromtimestamp(
                    os.path.getmtime(path), datetime.timezone.utc) < start:
                continue  # file not touched inside the window
        except OSError:
            continue
        if agent_id:
            try:
                with open(path[:-6] + ".meta.json") as f:
                    mt = json.load(f)
                if mt.get("agentType"):
                    meta_type[agent_id] = mt["agentType"]
            except (OSError, ValueError):
                pass
        sess = sessions.setdefault((proj_dir, main_sess), {
            "cwd": None, "topic": "", "prompts": [], "compacts": [], "proj_dir": proj_dir})
        try:
            fh = open(path, errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                if '"timestamp"' not in line:
                    continue
                try:
                    d = json.loads(line)
                    t = datetime.datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00"))
                except (ValueError, KeyError, TypeError, AttributeError):
                    continue
                if not sess["cwd"] and d.get("cwd"):
                    sess["cwd"] = d["cwd"]
                typ = d.get("type")
                m = d.get("message") or {}
                if not isinstance(m, dict):
                    m = {}
                in_window = (start is None or t >= start) and (end is None or t <= end)
                side = bool(agent_id) or bool(d.get("isSidechain"))
                file_key = (proj_dir, main_sess,
                            agent_id or ("sidechain" if d.get("isSidechain") else None))

                if typ == "system" and d.get("subtype") == "compact_boundary":
                    sess["compacts"].append((t, file_key))
                elif typ == "assistant":
                    content = m.get("content") if isinstance(m.get("content"), list) else []
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "tool_use" and \
                                b.get("name") in ("Agent", "Task") and b.get("id"):
                            tuid_type[b["id"]] = (b.get("input") or {}).get(
                                "subagent_type") or "general-purpose"
                    model = m.get("model") or "?"
                    mid = m.get("id") or d.get("requestId") or d.get("uuid")
                    if not in_window or model == "<synthetic>" or not mid:
                        continue
                    c = calls.get(mid)
                    if c is None:
                        c = calls[mid] = {"t": t, "model": model, "u": None, "tools": {},
                                          "side": side, "file_key": file_key,
                                          "sess_key": (proj_dir, main_sess),
                                          "agent_id": agent_id}
                    if m.get("usage"):
                        c["u"] = m["usage"]  # the last record of a message wins
                    for i, b in enumerate(content):
                        if isinstance(b, dict) and b.get("type") == "tool_use":
                            c["tools"][b.get("id") or (len(c["tools"]), i)] = (
                                b.get("name"), b.get("input") or {})
                elif typ == "user":
                    cc = m.get("content")
                    if isinstance(cc, list):
                        for x in cc:
                            if isinstance(x, dict) and x.get("type") == "tool_result" \
                                    and x.get("tool_use_id") in tuid_type:
                                am = re.search(r"agentId:\s*([0-9a-zA-Z_-]{6,40})",
                                               _user_text(x.get("content")) if not isinstance(
                                                   x.get("content"), str) else x["content"])
                                if am:
                                    tuid_agent[x["tool_use_id"]] = am.group(1)
                    is_result = isinstance(cc, list) and any(
                        isinstance(x, dict) and x.get("type") == "tool_result" for x in cc)
                    if is_result or side or d.get("isMeta") or d.get("isCompactSummary"):
                        continue
                    raw = _user_text(cc)
                    if "<task-notification>" in raw:
                        s = re.search(r"<summary>(.*?)(</summary>|$)", raw, re.S)
                        txt, kind = _clean_prompt(s.group(1) if s else raw), "notif"
                    else:
                        txt, kind = _clean_prompt(raw), "prompt"
                    if not txt or txt.startswith(("Caveat:", "[Request interrupted")):
                        continue
                    bare_cmd = txt.startswith("/") and len(txt.split()) == 1
                    if kind == "prompt" and not sess["topic"] and not bare_cmd:
                        sess["topic"] = txt[:150]
                    if in_window:
                        sess["prompts"].append((t, kind, txt[:300]))

    aid_type = dict(meta_type)
    for tu, aid in tuid_agent.items():
        aid_type.setdefault(aid, tuid_type.get(tu))
    out = []
    for c in calls.values():
        if not c["u"]:
            continue
        c["agent_type"] = aid_type.get(c["agent_id"]) if c["side"] else None
        c["tk"] = split_usage(c["u"])
        c["w_t"] = weighted_by_type(c["tk"], c["model"])
        c["w"] = sum(c["w_t"].values())
        c["ctx"] = c["tk"]["input"] + c["tk"]["cache_read"] + \
            c["tk"]["cache_write_5m"] + c["tk"]["cache_write_1h"]
        out.append(c)
    out.sort(key=lambda c: c["t"])
    return out, sessions


# --------------------------------------------------------------------------- naming / privacy

class Namer:
    def __init__(self, private):
        self.private = private
        self.proj_map, self.file_map = {}, {}

    def project(self, sess_meta, proj_dir):
        cwd = (sess_meta or {}).get("cwd")
        if cwd:
            home = os.path.expanduser("~")
            wt = None
            m = re.search(r"^(.*?)[/\\]\.claude[/\\]worktrees[/\\]([^/\\]+)", cwd)
            if m:
                cwd, wt = m.group(1), m.group(2)
            if cwd == home:
                name = "~"
            elif cwd.startswith(home + os.sep):
                name = "~/" + cwd[len(home) + 1:]
            else:
                name = cwd
            if wt:
                name += " [worktree]" if self.private else f" [worktree {wt}]"
        else:
            name = proj_dir
        if self.private:
            base = name.replace(" [worktree]", "")
            if base not in self.proj_map:
                self.proj_map[base] = f"project-{len(self.proj_map) + 1}"
            return self.proj_map[base] + (" [worktree]" if base != name else "")
        return name

    def file(self, path):
        base = os.path.basename(path)
        if not self.private:
            return base
        if path not in self.file_map:
            ext = os.path.splitext(base)[1]
            self.file_map[path] = f"file-{len(self.file_map) + 1}{ext}"
        return self.file_map[path]

    def topic(self, txt):
        return "" if self.private else (txt or "")


# --------------------------------------------------------------------------- aggregation

CTX_BUCKETS = [(0, 50e3, "< 50k"), (50e3, 100e3, "50-100k"), (100e3, 200e3, "100-200k"),
               (200e3, 300e3, "200-300k"), (300e3, float("inf"), "300k+")]
MIN_REBUILD_CTX = 20000
FEW_CALLS = 30  # groups with fewer calls are marked as unreliable


def call_activities(c):
    """(activity, share of the call) — a call's weight is split evenly between its tools"""
    tools = list(c["tools"].values())
    if not tools:
        return [(NO_TOOL, 1.0)]
    return [(classify_tool(n, i), 1.0 / len(tools)) for n, i in tools]


def new_bucket():
    return {"w": 0.0, "n": 0, "raw": 0}


def new_period():
    return {"w": 0.0, "n": 0, "date": None, "w_t": collections.Counter(),
            "tok": collections.Counter(), "act": collections.Counter()}


def agg_add(b, w, n=1, raw=0):
    b["w"] += w
    b["n"] += n
    b["raw"] += raw


def aggregate(calls, sessions, namer):
    R = {"n": len(calls), "tok": collections.Counter(), "w_t": collections.Counter(), "w": 0.0}
    for g in ("act", "model", "proj", "side", "agent"):
        R[g] = collections.defaultdict(new_bucket)
    R["day"] = collections.defaultdict(new_period)
    R["week"] = collections.defaultdict(new_period)
    R["ctxb"] = {nm: {"w": 0.0, "n": 0, "read": 0.0, "ctx": 0} for _, _, nm in CTX_BUCKETS}
    R["sess"] = collections.defaultdict(lambda: {"w": 0.0, "n": 0, "sub_w": 0.0, "max_ctx": 0})
    by_file = collections.defaultdict(list)

    for c in calls:
        w, raw = c["w"], sum(c["tk"].values())
        R["w"] += w
        R["tok"].update(c["tk"])
        R["w_t"].update(c["w_t"])
        acts = call_activities(c)
        for k, share in acts:
            agg_add(R["act"][k], w * share, 1, raw * share)
        agg_add(R["model"][c["model"]], w, 1, raw)
        agg_add(R["proj"][namer.project(sessions.get(c["sess_key"]), c["sess_key"][0])], w, 1, raw)
        agg_add(R["side"]["sub" if c["side"] else "main"], w, 1, raw)
        if c["side"]:
            agg_add(R["agent"][c["agent_type"] or L("(nieznany typ)", "(unknown type)")], w, 1, raw)

        loc = c["t"].astimezone()
        for key, bucket, date in (
                (f"{loc:%Y-%m-%d} {wd(loc.date())}", R["day"], loc.date()),
                (week_key(loc), R["week"], loc.date() - datetime.timedelta(days=loc.weekday()))):
            b = bucket[key]
            b["w"] += w
            b["n"] += 1
            b["date"] = date
            b["w_t"].update(c["w_t"])
            b["tok"].update(c["tk"])
            for k, share in acts:
                b["act"][k] += w * share

        for lo, hi, nm in CTX_BUCKETS:
            if lo <= c["ctx"] < hi:
                x = R["ctxb"][nm]
                x["w"] += w
                x["n"] += 1
                x["read"] += c["w_t"]["cache_read"] + c["w_t"]["input"]
                x["ctx"] += c["ctx"]
                break

        s = R["sess"][c["sess_key"]]
        s["w"] += w
        s["n"] += 1
        if c["side"]:
            s["sub_w"] += w
        else:
            s["max_ctx"] = max(s["max_ctx"], c["ctx"])
        by_file[c["file_key"]].append(c)

    # expired cache: the context was mostly written again instead of read from cache
    R["rebuild"] = {"n": 0, "w": 0.0, "waste": 0.0, "top": []}
    for fk, lst in by_file.items():
        prev = None
        for c in lst:
            cw = c["tk"]["cache_write_5m"] + c["tk"]["cache_write_1h"]
            if prev is not None and c["ctx"] >= MIN_REBUILD_CTX and cw >= 0.5 * c["ctx"]:
                pin, _pout, pcr = price_for(c["model"])
                waste = (c["tk"]["cache_write_5m"] * (pin * W_WRITE_5M - pcr)
                         + c["tk"]["cache_write_1h"] * (pin * W_WRITE_1H - pcr)) / REF_PRICE
                gap = (c["t"] - prev["t"]).total_seconds() / 60
                R["rebuild"]["n"] += 1
                R["rebuild"]["w"] += c["w"]
                R["rebuild"]["waste"] += waste
                R["rebuild"]["top"].append((waste, c["t"], fk, c["ctx"], gap))
            prev = c
    R["rebuild"]["top"].sort(key=lambda x: -x[0])
    R["rebuild"]["top"] = R["rebuild"]["top"][:5]

    # re-reads: Read of a line range that is already in context (no edit / compaction since)
    events = collections.defaultdict(list)
    for fk, lst in by_file.items():
        for c in lst:
            for name, inp in c["tools"].values():
                fp = str(inp.get("file_path") or "")
                if not fp:
                    continue
                if name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
                    events[fk].append((c["t"], "edit", fp, None))
                elif name == "Read":
                    try:
                        a = int(inp.get("offset") or 1)
                        lim = inp.get("limit")
                        rng = (a, a + int(lim) - 1) if lim else (a, float("inf"))
                    except (TypeError, ValueError):
                        rng = (1, float("inf"))
                    events[fk].append((c["t"], "read", fp, rng))
    for s in sessions.values():
        for t, fk in s["compacts"]:
            if fk in events:
                events[fk].append((t, "compact", None, None))
    R["reread"] = {"reads": 0, "repeat": 0, "files": collections.Counter()}
    for fk, evs in events.items():
        evs.sort(key=lambda x: x[0])
        seen = collections.defaultdict(list)
        for _t, kind, fp, rng in evs:
            if kind == "compact":
                seen.clear()
            elif kind == "edit":
                seen.pop(fp, None)
            else:
                R["reread"]["reads"] += 1
                if any(max(rng[0], r[0]) <= min(rng[1], r[1]) for r in seen[fp]):
                    R["reread"]["repeat"] += 1
                    R["reread"]["files"][namer.file(fp)] += 1
                seen[fp].append(rng)

    R["n_sessions"] = len(R["sess"])
    R["n_subagents"] = len({c["file_key"] for c in calls if c["side"]})
    return R


def week_key(loc):
    y, w, _ = loc.isocalendar()
    mon = loc.date() - datetime.timedelta(days=loc.weekday())
    return f"{y}-W{w:02d} ({mon:%m-%d}..{mon + datetime.timedelta(days=6):%m-%d})"


def cache_hit(tok):
    ctx = tok["input"] + tok["cache_read"] + tok["cache_write_5m"] + tok["cache_write_1h"]
    return pct(tok["cache_read"], ctx) if ctx else None


def ctx_growth(R):
    """(avg weight per call in the largest reliable bucket, in 50-100k, label) or None"""
    base = R["ctxb"]["50-100k"]
    if base["n"] < FEW_CALLS:
        return None
    for _, _, nm in reversed(CTX_BUCKETS):
        b = R["ctxb"][nm]
        if b["n"] >= FEW_CALLS and nm != "50-100k":
            return b["w"] / b["n"], base["w"] / base["n"], nm
    return None


# --------------------------------------------------------------------------- formatting

def fmt_tok(n):
    n = float(n)
    if abs(n) >= 1e9:
        return f"{n / 1e9:.2f}B"
    if abs(n) >= 1e6:
        return f"{n / 1e6:.1f}M"
    if abs(n) >= 1e3:
        return f"{n / 1e3:.0f}k"
    return f"{n:.0f}"


def pct(a, b):
    return 100.0 * a / b if b else 0.0


def short(name, width):
    """shortens a path-like name from the left, keeping the last component readable"""
    if len(name) <= width:
        return name
    return "…" + name[-(width - 1):]


def fmt_int(n):
    return f"{int(n):,}".replace(",", " ")


def bar(frac, width=24):
    full = int(round(max(0.0, min(1.0, frac)) * width))
    return "#" * full + "." * (width - full)


def fmt_change(cur, prev):
    if prev:
        return f"{pct(cur - prev, prev):+.0f}%"
    return L("nowe", "new") if cur else "0%"


def fmt_delta(d):
    return ("+" if d >= 0 else "-") + fmt_tok(abs(d))


def last_local_day(end):
    e = end.astimezone()
    return (e - datetime.timedelta(seconds=1)).date() if e.time() == datetime.time(0) else e.date()


def period_label(start, end, last_n=None, rolling=None, session=None):
    if session:
        return L("sesja ", "session ") + session
    if start is None:
        return L("cała historia", "all history")
    if rolling:
        return (L(f"ostatnie {rolling:g} × 24 h", f"last {rolling:g} × 24 h")
                + f" ({start.astimezone():%m-%d %H:%M}..{end.astimezone():%m-%d %H:%M})")
    s, e = start.astimezone().date(), last_local_day(end)
    today = datetime.datetime.now().astimezone().date()
    if s == e:
        if s == today:
            return L("dzisiaj", "today") + f" ({s}, {wd(s)})"
        if s == today - datetime.timedelta(days=1):
            return L("wczoraj", "yesterday") + f" ({s}, {wd(s)})"
        return f"{s} ({wd(s)})"
    n = (e - s).days + 1
    if last_n and e == today:
        return L(f"ostatnie {n} dni", f"last {n} days") + f" ({s}..{e})"
    return f"{s}..{e} (" + L(f"{n} dni", f"{n} days") + ")"


def side_name(k):
    return L("sesja główna", "main session") if k == "main" else L("subagenci", "subagents")


# --------------------------------------------------------------------------- tips

def tips(R):
    out = []
    tot = R["w"] or 1e-9
    big = sum(R["ctxb"][k]["w"] for k in ("200-300k", "300k+"))
    g = ctx_growth(R)
    if pct(big, tot) > 20:
        ratio = f" (~{g[0] / g[1]:.1f}x)" if g else ""
        out.append(L(
            f"Długie rozmowy: wywołania przy kontekście powyżej 200k to {pct(big, tot):.0f}% "
            f"zużycia, a każde takie wywołanie obciąża limit mocniej niż przy krótkiej rozmowie"
            f"{ratio}. Nowe, niezwiązane zadanie zaczynaj od /clear, a długą pracę skracaj "
            f"przez /compact.",
            f"Long conversations: calls with more than 200k of context are {pct(big, tot):.0f}% "
            f"of usage, and each of them weighs more than a call in a short conversation"
            f"{ratio}. Start unrelated tasks with /clear and shorten long work with /compact."))
    rb = R["rebuild"]
    if rb["n"] and pct(rb["waste"], tot) > 3:
        out.append(L(
            f"Wygasły cache: {rb['n']} razy cała rozmowa była zapisywana od nowa (zwykle po "
            f"przerwie dłuższej niż 5 minut). To {pct(rb['waste'], tot):.0f}% zużycia, którego "
            f"dało się uniknąć. Przed dłuższą przerwą dokończ wątek, a po powrocie do starej "
            f"rozmowy rozważ /compact albo /clear.",
            f"Expired cache: {rb['n']} times the whole conversation was written again (usually "
            f"after a break of more than 5 minutes). That is {pct(rb['waste'], tot):.0f}% of "
            f"usage that could have been avoided. Finish the thread before a long break, and "
            f"consider /compact or /clear when you return to an old conversation."))
    explore = sum(R["act"][k]["w"] for k in EXPLORE_KEYS if k in R["act"])
    if pct(explore, tot) > 25:
        out.append(L(
            f"Szukanie i czytanie kodu to {pct(explore, tot):.0f}% zużycia. Wskazuj w prośbie "
            f"konkretne pliki lub funkcje, opisz strukturę projektu w CLAUDE.md, a szerokie "
            f"przeszukiwanie zlecaj subagentowi (np. „użyj subagenta, żeby znalazł…”). Jego "
            f"robocze odczyty nie trafiają do głównej rozmowy, wraca tylko wynik.",
            f"Searching and reading code is {pct(explore, tot):.0f}% of usage. Name concrete "
            f"files or functions in your request, describe the project layout in CLAUDE.md, "
            f"and hand broad searches to a subagent (e.g. \"use a subagent to find…\"). Its "
            f"working reads stay out of the main conversation; only the result comes back."))
    rr = R["reread"]
    if rr["reads"] >= 20 and pct(rr["repeat"], rr["reads"]) > 20:
        out.append(L(
            f"{pct(rr['repeat'], rr['reads']):.0f}% odczytów plików dotyczyło fragmentów, które "
            f"już były w rozmowie (bez zmian pomiędzy).",
            f"{pct(rr['repeat'], rr['reads']):.0f}% of file reads were for parts already in the "
            f"conversation (unchanged in between)."))
    out_share = pct(R["w_t"]["output"], tot)
    if out_share > 35:
        out.append(L(
            f"Odpowiedzi modelu (tekst, kod, myślenie) to {out_share:.0f}% zużycia. Niższy "
            f"poziom effort albo prośba o zwięzłe odpowiedzi to zmniejszy.",
            f"Model output (text, code, thinking) is {out_share:.0f}% of usage. A lower effort "
            f"level or asking for concise answers reduces it."))
    if R["model"]:
        top_model, tb = max(R["model"].items(), key=lambda kv: kv[1]["w"])
        if model_weight(top_model) >= 0.8 and pct(tb["w"], tot) > 80:
            out.append(L(
                f"{pct(tb['w'], tot):.0f}% zużycia to {top_model}. Tańszy model (np. Sonnet) "
                f"obciąża limit kilka razy słabiej, więc do prostych zadań warto go wybrać "
                f"przez /model.",
                f"{pct(tb['w'], tot):.0f}% of usage is {top_model}. A cheaper model (e.g. "
                f"Sonnet) uses the limit several times slower, so pick it via /model for simple "
                f"tasks."))
    if not out:
        out.append(L("Nic nie odstaje — rozkład zużycia wygląda zdrowo.",
                     "Nothing stands out — the usage distribution looks healthy."))
    return out


# --------------------------------------------------------------------------- text report

WIDTH = 92


def hdr(A, title):
    A("")
    A(f"-- {title} " + "-" * max(0, WIDTH - len(title) - 4))


def note(A, text, indent=3):
    for line in textwrap.wrap(text, WIDTH - indent - 1):
        A(" " * indent + line)


def breakdown(A, title, groups, R, top, label, names=lambda k: k, desc=None, left=False,
              n_label=None, extra=None):
    hdr(A, title)
    if desc:
        note(A, desc)
    tot = R["w"] or 1e-9
    n_label = n_label or L("wywoł.", "calls")
    xh = f"{extra[0]:>7}" if extra else ""
    A(f" {label:<38}{L('ważone', 'weighted'):>10}{'%':>7}{n_label:>8}{L('śr./szt.', 'avg'):>9}"
      f"{xh}  ")
    items = sorted(groups.items(), key=lambda kv: -kv[1]["w"])
    for k, b in items[:top]:
        nm = short(str(names(k)), 37) if left else str(names(k))[:37]
        xv = f"{extra[1](k):>7}" if extra else ""
        A(f" {nm:<38}{fmt_tok(b['w']):>10}{pct(b['w'], tot):>6.1f}%{b['n']:>8}"
          f"{fmt_tok(b['w'] / b['n'] if b['n'] else 0):>9}{xv}  {bar(b['w'] / tot)}")
    rest = items[top:]
    if rest:
        rw = sum(b["w"] for _, b in rest)
        A(f" {L(f'(pozostałe: {len(rest)})', f'(other: {len(rest)})'):<38}{fmt_tok(rw):>10}"
          f"{pct(rw, tot):>6.1f}%")


def summary(A, R):
    raw = sum(R["tok"].values())
    hit = cache_hit(R["tok"])

    def item(name, value, text):
        A(f" {name:<26}{value:>12}")
        note(A, text, 5)

    item(L("wywołania modelu", "model calls"), fmt_int(R["n"]), L(
        f"Tyle razy Claude Code wysłał zapytanie do modelu (w {R['n_sessions']} rozmowach, "
        f"z {R['n_subagents']} subagentami). Jedna Twoja wiadomość to zwykle od kilku do "
        f"kilkudziesięciu wywołań: każde użycie narzędzia (odczyt pliku, komenda, edycja) to "
        f"kolejne wywołanie.",
        f"How many times Claude Code sent a request to the model (in {R['n_sessions']} "
        f"conversations, with {R['n_subagents']} subagents). One message from you usually means "
        f"several to dozens of calls: every tool use (reading a file, a command, an edit) is "
        f"another call."))
    item(L("tokeny surowe", "raw tokens"), fmt_tok(raw), L(
        "Cały tekst, który model przeczytał i napisał, liczony po równo. Model nie pamięta "
        "rozmowy, więc przy każdym wywołaniu czyta ją od początku — stąd tak ogromna liczba. "
        "Sama w sobie niewiele mówi, bo większość to tani powtórny odczyt z cache.",
        "All the text the model read and wrote, every token counted the same. The model has "
        "no memory, so it re-reads the whole conversation on every call — hence the huge "
        "number. On its own it says little, because most of it is cheap re-reading from cache."))
    item(L("tokeny ważone", "weighted tokens"), fmt_tok(R["w"]), L(
        "GŁÓWNA MIARA RAPORTU. Te same tokeny, ale każdy liczony według tego, jak mocno "
        "obciąża limit: powtórny odczyt z cache x0.1, nowy tekst x1, zapis do cache x1.25, "
        "odpowiedź modelu x5, a do tego waga modelu (Opus 5 x1, Sonnet 5 x0.4). Wszystkie "
        "procenty niżej są liczone od tej wartości. Szczegóły: --explain",
        "THE MAIN MEASURE OF THIS REPORT. The same tokens, but each counted by how heavily it "
        "uses your limit: re-reading from cache x0.1, new text x1, cache write x1.25, model "
        "output x5, plus the model's weight (Opus 5 x1, Sonnet 5 x0.4). All percentages below "
        "are shares of this number. Details: --explain"))
    if hit is not None:
        item(L("trafienia w cache", "cache hit rate"), f"{hit:.1f}%", L(
            "Jaka część rozmowy była tanim powtórnym odczytem z cache. Powyżej ~90% to dobry "
            "wynik. Spadki oznaczają przerwy dłuższe niż 5 minut albo zmiany na początku "
            "rozmowy (np. zmianę modelu).",
            "How much of the conversation was cheap re-reading from cache. Above ~90% is good. "
            "Drops mean breaks longer than 5 minutes or changes at the start of the "
            "conversation (e.g. switching models)."))
    if R["n"]:
        ctx_t = raw - R["tok"]["output"]
        item(L("średnio na wywołanie", "average per call"), fmt_tok(R["w"] / R["n"]), L(
            f"tokenów ważonych; model czytał wtedy średnio {fmt_tok(ctx_t / R['n'])} tokenów "
            f"rozmowy.", f"weighted tokens; the model was reading {fmt_tok(ctx_t / R['n'])} "
            f"tokens of conversation on average."))


def token_table(A, R):
    tok, w_t = R["tok"], R["w_t"]
    raw = sum(tok.values()) or 1
    tw = R["w"] or 1e-9
    A(f" {L('rodzaj tokenu', 'token type'):<26}{L('surowe', 'raw'):>9}{'%':>7}"
      f"{L('waga', 'weight'):>8}{L('ważone', 'weighted'):>10}{'%':>7}")
    for t in TYPES:
        if t == "cache_write_1h" and not tok[t]:
            continue
        A(f" {type_name(t):<26}{fmt_tok(tok[t]):>9}{pct(tok[t], raw):>6.1f}%"
          f"{'x' + format(WEIGHTS[t], 'g'):>8}{fmt_tok(w_t[t]):>10}{pct(w_t[t], tw):>6.1f}%")
    A(f" {L('RAZEM', 'TOTAL'):<26}{fmt_tok(raw):>9}{'':>7}{'':>8}{fmt_tok(R['w']):>10}")
    note(A, L(
        "Surowe i ważone to te same tokeny policzone na dwa sposoby. Odczyt z cache to prawie "
        "wszystkie surowe tokeny, ale z wagą x0.1 jego udział w limicie jest dużo mniejszy. "
        "Ważone uwzględniają też wagę modelu (tabela MODELE), dlatego nie są dokładnie "
        "surowe × waga.",
        "Raw and weighted are the same tokens counted two ways. Cache reads are almost all raw "
        "tokens, but at x0.1 their share of the limit is much smaller. Weighted also includes "
        "the model's weight (see MODELS), so it is not exactly raw × weight."))


def text_report(R, ctx):
    out = []
    A = out.append
    tot = R["w"] or 1e-9
    A("=" * WIDTH)
    A(" " + L("ZUŻYCIE TOKENÓW CLAUDE CODE", "CLAUDE CODE TOKEN USAGE") + " — " + ctx["label"])
    A(" " + L("źródło: lokalne transkrypty ", "source: local transcripts ") + ctx["root_disp"]
      + L("  (raport zużywa 0 tokenów)", "  (this report uses 0 tokens)"))
    A("=" * WIDTH)
    summary(A, R)

    hdr(A, L("RODZAJE TOKENÓW — surowe vs ważone", "TOKEN TYPES — raw vs weighted"))
    token_table(A, R)

    breakdown(A, L("NA CO IDĄ TOKENY", "WHERE THE TOKENS GO"), R["act"], R, ctx["top"] + 6,
              L("czynność", "activity"), activity_name, n_label=L("użyć", "uses"), desc=L(
                  "Każde wywołanie jest przypisane do narzędzia, którego model w nim użył (przy "
                  "kilku narzędziach naraz — po równo). „Bez narzędzia” = model odpowiedział Ci "
                  "tekstem. „śr./szt.” = ile średnio waży jedno użycie.",
                  "Each call is assigned to the tool the model used in it (split evenly if it "
                  "used several). 'No tool' = the model replied to you with text. 'avg' = the "
                  "average weight of one use."))
    breakdown(A, L("MODELE", "MODELS"), R["model"], R, ctx["top"], "model",
              extra=(L("waga", "weight"), lambda k: "x" + format(model_weight(k), ".2g")),
              desc=L("„waga” = jak mocno model obciąża limit względem Opus 5 (x1). Ta sama praca "
                     "na modelu z wagą x0.4 zużywa 2.5 raza mniej.",
                     "'weight' = how heavily the model uses the limit relative to Opus 5 (x1). "
                     "The same work on a x0.4 model uses 2.5 times less."))
    if UNKNOWN_MODELS:
        note(A, L("nieznane modele liczone z wagą Opus 5: ", "unknown models weighted as Opus 5: ")
             + ", ".join(sorted(UNKNOWN_MODELS)) + L(" (zmień przez --prices)", " (use --prices)"))
    breakdown(A, L("SESJA GŁÓWNA vs SUBAGENCI", "MAIN SESSION vs SUBAGENTS"), R["side"], R, 2,
              L("gdzie", "where"), side_name, desc=L(
                  "Subagenci to osobne instancje Claude uruchamiane narzędziem Agent. Mają "
                  "własny kontekst, więc ich praca nie wydłuża głównej rozmowy.",
                  "Subagents are separate Claude instances started with the Agent tool. They "
                  "have their own context, so their work doesn't grow the main conversation."))
    if R["agent"]:
        breakdown(A, L("SUBAGENCI WG TYPU", "SUBAGENTS BY TYPE"), R["agent"], R, ctx["top"],
                  L("typ subagenta", "subagent type"))
    if not ctx.get("session"):
        breakdown(A, L("PROJEKTY (katalog roboczy)", "PROJECTS (working directory)"),
                  R["proj"], R, ctx["top"], L("projekt", "project"), left=True)

    hdr(A, L("DŁUGOŚĆ ROZMOWY — ile waży wywołanie przy danym rozmiarze kontekstu",
             "CONVERSATION LENGTH — weight of a call by context size"))
    note(A, L(
        "Kontekst = cała rozmowa, którą model czyta przy danym wywołaniu. Rośnie z każdym "
        "krokiem, a model czyta ją za każdym razem od nowa, więc im dłuższa rozmowa, tym więcej "
        "waży każde kolejne wywołanie.",
        "Context = the whole conversation the model reads in a call. It grows with every step "
        "and the model re-reads it every time, so the longer the conversation, the more each "
        "further call weighs."))
    A(f" {L('kontekst', 'context'):<14}{L('wywoł.', 'calls'):>8}{L('ważone', 'weighted'):>10}"
      f"{'%':>7}{L('śr./wywoł.', 'avg/call'):>12}{L('w tym czytanie', 'of it reading'):>16}")
    for _, _, nm in CTX_BUCKETS:
        b = R["ctxb"][nm]
        if not b["n"]:
            continue
        few = L("  (mało danych)", "  (few calls)") if b["n"] < FEW_CALLS else ""
        A(f" {nm:<14}{b['n']:>8}{fmt_tok(b['w']):>10}{pct(b['w'], tot):>6.1f}%"
          f"{fmt_tok(b['w'] / b['n']):>12}{fmt_tok(b['read'] / b['n']):>16}{few}")
    g = ctx_growth(R)
    if g:
        note(A, L(f"Wywołanie przy kontekście {g[2]} waży średnio {g[0] / g[1]:.1f}x tyle co "
                  f"przy 50-100k. „w tym czytanie” = część, która idzie tylko na ponowne "
                  f"przeczytanie rozmowy. Grupa „< 50k” to często początki rozmów, które "
                  f"najpierw zapisują wszystko do cache.",
                  f"A call at {g[2]} context weighs {g[0] / g[1]:.1f}x as much as one at 50-100k "
                  f"on average. 'of it reading' = the part spent only on re-reading the "
                  f"conversation. The '< 50k' group is often conversation starts, which first "
                  f"write everything to the cache."))

    key = "week" if ctx["chart"] == "week" else "day"
    periods = sorted(R[key].items(), key=lambda kv: kv[1]["date"])
    if len(periods) > 1 or ctx["chart"]:
        hdr(A, L("W CZASIE — ", "OVER TIME — ") + (L("tygodnie", "weeks") if key == "week"
                                                     else L("dni", "days")))
        mx = max(b["w"] for _, b in periods) or 1e-9
        A(f" {L('okres', 'period'):<26}{L('ważone', 'weighted'):>10}{'%':>7}"
          f"{L('wywoł.', 'calls'):>8}  ")
        for k, b in periods:
            A(f" {k:<26}{fmt_tok(b['w']):>10}{pct(b['w'], tot):>6.1f}%{b['n']:>8}  "
              f"{bar(b['w'] / mx, 30)}")
        if ctx["chart"] and len(periods) > 1:
            cats = [k for k, _ in sorted(R["act"].items(), key=lambda kv: -kv[1]["w"])[:6]]
            view = periods[-8:]
            A("")
            A(" " + L("trend głównych czynności (tokeny ważone):",
                      "trend of top activities (weighted tokens):"))
            heads = [(k[5:10] if key == "day" else k[5:8]) for k, _ in view]
            A(f" {'':<40}" + "".join(f"{h:>8}" for h in heads))
            for cat in cats:
                A(f" {activity_name(cat)[:39]:<40}"
                  + "".join(f"{fmt_tok(b['act'][cat]):>8}" for _, b in view))

    if not ctx.get("session"):
        hdr(A, L("NAJCIĘŻSZE ROZMOWY", "HEAVIEST CONVERSATIONS"))
        A(f" {L('sesja', 'session'):<10}{L('projekt', 'project'):<22}{L('ważone', 'weighted'):>9}"
          f"{'%':>7}{L('wywoł.', 'calls'):>7}{L('maks.ctx', 'max ctx'):>9}"
          f"{L('subag.', 'sub'):>7}  {L('temat (pierwsza prośba)', 'topic (first request)')}")
        for sk, s in sorted(R["sess"].items(), key=lambda kv: -kv[1]["w"])[:ctx["top"]]:
            meta = ctx["sessions"].get(sk, {})
            pname = ctx["namer"].project(meta, sk[0])
            A(f" {sk[1][:8]:<10}{short(pname, 21):<22}{fmt_tok(s['w']):>9}"
              f"{pct(s['w'], tot):>6.1f}%{s['n']:>7}{fmt_tok(s['max_ctx']):>9}"
              f"{pct(s['sub_w'], s['w']):>6.0f}%  {ctx['namer'].topic(meta.get('topic'))[:38]}")
        note(A, L("„maks.ctx” = do jakiego rozmiaru urosła rozmowa; „subag.” = jaka część "
                  "zużycia tej sesji przypadła na subagentów. Szczegóły jednej sesji: "
                  "--session <id>",
                  "'max ctx' = how large the conversation grew; 'sub' = the share of this "
                  "session's usage spent by subagents. One session in detail: --session <id>"))

    if ctx.get("session"):
        meta = ctx["sessions"].get(ctx["session_key"], {})
        hdr(A, L("FAZY SESJI — zużycie między kolejnymi prośbami",
                 "SESSION PHASES — usage between requests"))
        evs = sorted(meta.get("prompts", []), key=lambda x: x[0])
        calls = ctx["calls"]
        for i, (t, kind, txt) in enumerate(evs):
            t2 = evs[i + 1][0] if i + 1 < len(evs) else None
            cs = [c for c in calls if c["t"] >= t and (t2 is None or c["t"] < t2)]
            w = sum(c["w"] for c in cs)
            mc = max((c["ctx"] for c in cs if not c["side"]), default=0)
            tag = L("powiad.", "notif.") if kind == "notif" else L("prośba", "request")
            A(f" {t.astimezone():%m-%d %H:%M}  {tag:<8}{len(cs):>5} {L('wyw.', 'calls')}"
              f"{fmt_tok(w):>8}  ctx {fmt_tok(mc):>5}  {ctx['namer'].topic(txt)[:44]}")

    rb = R["rebuild"]
    hdr(A, L("WYGASŁY CACHE — rozmowa zapisana od nowa",
             "EXPIRED CACHE — conversation written again"))
    note(A, L(
        "Cache trzyma rozmowę przez 5 minut (czasem godzinę) od ostatniego użycia. Po dłuższej "
        "przerwie model musi zapisać całą rozmowę od nowa (waga x1.25) zamiast ją tanio "
        "odczytać (x0.1).",
        "The cache keeps the conversation for 5 minutes (sometimes an hour) after its last use. "
        "After a longer break the model has to write the whole conversation again (weight "
        "x1.25) instead of reading it cheaply (x0.1)."))
    A(" " + L(f"takich wywołań: {rb['n']}   nadmiarowe zużycie: {fmt_tok(rb['waste'])} "
              f"({pct(rb['waste'], tot):.1f}% całości)",
              f"such calls: {rb['n']}   extra usage: {fmt_tok(rb['waste'])} "
              f"({pct(rb['waste'], tot):.1f}% of the total)"))
    for waste, t, fk, cx, gap in rb["top"]:
        A(f"    {t.astimezone():%Y-%m-%d %H:%M}  {fk[1][:8]}  ctx {fmt_tok(cx):>5}  "
          + L(f"przerwa {gap:>4.0f} min  nadmiar {fmt_tok(waste)}",
              f"gap {gap:>4.0f} min  extra {fmt_tok(waste)}"))

    rr = R["reread"]
    if rr["reads"]:
        hdr(A, L("POWTÓRNE ODCZYTY PLIKÓW (narzędzie Read)", "REPEATED FILE READS (Read tool)"))
        A(" " + L(f"odczytów: {rr['reads']}, z tego fragment już był w rozmowie: {rr['repeat']} "
                  f"({pct(rr['repeat'], rr['reads']):.0f}%)",
                  f"reads: {rr['reads']}, part already in the conversation: {rr['repeat']} "
                  f"({pct(rr['repeat'], rr['reads']):.0f}%)"))
        for f, n in rr["files"].most_common(6):
            A(f"    {f[:50]:<52}+{n}")

    hdr(A, L("CO MOŻNA POPRAWIĆ", "WHAT YOU COULD IMPROVE"))
    for tip in tips(R):
        lines = textwrap.wrap(tip, WIDTH - 4)
        A(" * " + lines[0])
        for line in lines[1:]:
            A("   " + line)
    A("")
    A(" " + L("Pełne wyjaśnienie tokenów surowych i ważonych: --explain",
              "Full explanation of raw and weighted tokens: --explain"))
    A("=" * WIDTH)
    return "\n".join(out)


def text_diff(Rc, Rp, ctx):
    out = []
    A = out.append
    A("=" * WIDTH)
    A(" " + L("PORÓWNANIE", "COMPARISON") + f": {ctx['label']}  vs  {ctx['prev_label']}")
    A("=" * WIDTH)
    A(f" {L('wskaźnik', 'metric'):<30}{L('teraz', 'now'):>12}{L('wcześniej', 'before'):>12}"
      f"{L('zmiana', 'change'):>10}")

    def row(name, a, b, f):
        A(f" {name:<30}{f(a):>12}{f(b):>12}{fmt_change(a, b):>10}")

    row(L("wywołania modelu", "model calls"), Rc["n"], Rp["n"], fmt_int)
    row(L("tokeny surowe", "raw tokens"), sum(Rc["tok"].values()), sum(Rp["tok"].values()), fmt_tok)
    row(L("tokeny ważone", "weighted tokens"), Rc["w"], Rp["w"], fmt_tok)
    for t in TYPES:
        if Rc["w_t"][t] or Rp["w_t"][t]:
            row("  " + type_name(t), Rc["w_t"][t], Rp["w_t"][t], fmt_tok)
    row(L("średnio na wywołanie", "average per call"), Rc["w"] / max(Rc["n"], 1),
        Rp["w"] / max(Rp["n"], 1), fmt_tok)
    hc, hp = cache_hit(Rc["tok"]) or 0, cache_hit(Rp["tok"]) or 0
    A(f" {L('trafienia w cache', 'cache hit rate'):<30}{hc:>11.1f}%{hp:>11.1f}%"
      f"{hc - hp:>+8.1f}pp")

    def cmp(title, gc, gp, names=lambda k: k, top=12):
        hdr(A, title)
        A(f" {'':<38}{L('teraz', 'now'):>10}{L('wcześniej', 'before'):>11}{L('różnica', 'diff'):>10}"
          f"{L('zmiana', 'change'):>9}")
        keys = sorted(set(gc) | set(gp), key=lambda k: -(gc[k]["w"] if k in gc else 0)
                      - (gp[k]["w"] if k in gp else 0))[:top]
        for k in keys:
            a = gc[k]["w"] if k in gc else 0.0
            b = gp[k]["w"] if k in gp else 0.0
            A(f" {str(names(k))[:37]:<38}{fmt_tok(a):>10}{fmt_tok(b):>11}{fmt_delta(a - b):>10}"
              f"{fmt_change(a, b):>9}")

    cmp(L("NA CO IDĄ TOKENY (ważone)", "WHERE THE TOKENS GO (weighted)"), Rc["act"], Rp["act"],
        activity_name)
    cmp(L("MODELE (ważone)", "MODELS (weighted)"), Rc["model"], Rp["model"])
    cmp(L("PROJEKTY (ważone)", "PROJECTS (weighted)"), Rc["proj"], Rp["proj"],
        lambda k: short(k, 37))
    bc = sum(Rc["ctxb"][k]["w"] for k in ("200-300k", "300k+"))
    bp = sum(Rp["ctxb"][k]["w"] for k in ("200-300k", "300k+"))
    hdr(A, L("WNIOSKI", "TAKEAWAYS"))
    A(" * " + L(f"długie rozmowy (kontekst > 200k): {pct(bc, Rc['w']):.0f}% zużycia "
                f"(wcześniej {pct(bp, Rp['w']):.0f}%)",
                f"long conversations (context > 200k): {pct(bc, Rc['w']):.0f}% of usage "
                f"(before {pct(bp, Rp['w']):.0f}%)"))
    A(" * " + L(f"nadmiar przez wygasły cache: {pct(Rc['rebuild']['waste'], Rc['w']):.1f}% "
                f"(wcześniej {pct(Rp['rebuild']['waste'], Rp['w']):.1f}%)",
                f"extra from expired cache: {pct(Rc['rebuild']['waste'], Rc['w']):.1f}% "
                f"(before {pct(Rp['rebuild']['waste'], Rp['w']):.1f}%)"))
    A("=" * WIDTH)
    return "\n".join(out)


# --------------------------------------------------------------------------- day by day

def daily_series(calls, first, last):
    """one bucket per calendar day from first to last (inclusive), empty days included"""
    days = collections.OrderedDict()
    d = first
    while d <= last:
        days[d] = {"w": 0.0, "n": 0, "tok": collections.Counter(), "act": collections.Counter()}
        d += datetime.timedelta(days=1)
    for c in calls:
        b = days.get(c["t"].astimezone().date())
        if b is None:
            continue
        b["w"] += c["w"]
        b["n"] += 1
        b["tok"].update(c["tk"])
        for k, share in call_activities(c):
            b["act"][k] += c["w"] * share
    return list(days.items())


def daily_rows(series, has_base):
    """adds the change vs the previous day and the activity that changed the most"""
    rows = []
    for i, (d, b) in enumerate(series):
        p = series[i - 1][1] if i else None
        r = {"date": d, "b": b, "p": p, "base": has_base and i == 0, "hit": cache_hit(b["tok"]),
             "per_call": b["w"] / b["n"] if b["n"] else None, "driver": None}
        if p is not None:
            acts = set(b["act"]) | set(p["act"])
            if acts:
                k = max(acts, key=lambda a: abs(b["act"][a] - p["act"][a]))
                r["driver"] = (k, b["act"][k] - p["act"][k])
        rows.append(r)
    return rows


def arrow(cur, prev):
    if prev is None:
        return " "
    if abs(cur - prev) <= 0.01 * max(abs(prev), 1e-9) or (not cur and not prev):
        return "="
    return "▲" if cur > prev else "▼"


def daily_summary(rows):
    days = [r for r in rows if not r["base"]]
    if not days:
        return None
    changed = [r for r in days if r["p"] is not None]
    return {"avg": sum(r["b"]["w"] for r in days) / len(days), "n": len(days),
            "hi": max(days, key=lambda r: r["b"]["w"]), "lo": min(days, key=lambda r: r["b"]["w"]),
            "up": sum(1 for r in changed if arrow(r["b"]["w"], r["p"]["w"]) == "▲"),
            "down": sum(1 for r in changed if arrow(r["b"]["w"], r["p"]["w"]) == "▼")}


def text_daily(rows):
    out = []
    A = out.append
    hdr(A, L("DZIEŃ PO DNIU — zmiana względem poprzedniego dnia",
             "DAY BY DAY — change vs the previous day"))
    A(f" {L('dzień', 'day'):<17}{L('ważone', 'weighted'):>9}{L('zmiana', 'change'):>10}{'%':>7}"
      f"{L('wywoł.', 'calls'):>8}{'cache':>7}{L('śr./wyw.', 'avg/call'):>10}  "
      f"{L('największa zmiana', 'biggest change')}")
    for r in rows:
        b, p, d = r["b"], r["p"], r["date"]
        name = f"{d:%m-%d} {wd(d)}" + (L(" (baza)", " (base)") if r["base"] else "")
        hit = f"{r['hit']:.0f}%" if r["hit"] is not None else "-"
        per = fmt_tok(r["per_call"]) if r["per_call"] is not None else "-"
        if p is None or r["base"]:
            A(f" {name:<17}{fmt_tok(b['w']):>9}{'':>10}{'':>7}{b['n']:>8}{hit:>7}{per:>10}")
            continue
        drv = ""
        if r["driver"] and abs(r["driver"][1]) >= 1:
            drv = f"{fmt_delta(r['driver'][1])} {activity_name(r['driver'][0])}"
        A(f" {name:<15}{arrow(b['w'], p['w']):>2}{fmt_tok(b['w']):>9}{fmt_delta(b['w'] - p['w']):>10}"
          f"{fmt_change(b['w'], p['w']):>7}{b['n']:>8}{hit:>7}{per:>10}  {drv[:44]}")
    sm = daily_summary(rows)
    if sm:
        A("")
        A(" " + L(f"średnio dziennie {fmt_tok(sm['avg'])}   najwięcej {sm['hi']['date']} "
                  f"({fmt_tok(sm['hi']['b']['w'])})   najmniej {sm['lo']['date']} "
                  f"({fmt_tok(sm['lo']['b']['w'])})   dni ▲ {sm['up']} / ▼ {sm['down']}",
                  f"daily average {fmt_tok(sm['avg'])}   highest {sm['hi']['date']} "
                  f"({fmt_tok(sm['hi']['b']['w'])})   lowest {sm['lo']['date']} "
                  f"({fmt_tok(sm['lo']['b']['w'])})   days ▲ {sm['up']} / ▼ {sm['down']}"))
        note(A, L("Wszystko w tokenach ważonych. ▲ = więcej niż dzień wcześniej, ▼ = mniej, "
                  "= bez zmian (±1%). „największa zmiana” = czynność, której zużycie zmieniło "
                  "się najbardziej.",
                  "All in weighted tokens. ▲ = more than the day before, ▼ = less, = unchanged "
                  "(±1%). 'biggest change' = the activity whose usage changed the most."))
    return "\n".join(out)


# --------------------------------------------------------------------------- explanation

EXPLAIN_PL = """\
CO ZNACZĄ LICZBY W TYM RAPORCIE
================================

1. JAK CLAUDE CODE ZUŻYWA TOKENY
   Token to kawałek tekstu (średnio 3-4 znaki). Model nie ma pamięci między
   zapytaniami, więc przy KAŻDYM wywołaniu Claude Code wysyła mu całą
   dotychczasową rozmowę: instrukcje systemowe, opisy narzędzi, CLAUDE.md,
   Twoje wiadomości, odpowiedzi modelu i wyniki narzędzi (treść plików,
   wyjście komend).
   Jedna Twoja prośba to zwykle od kilku do kilkudziesięciu wywołań: model
   czyta plik (wywołanie), szuka czegoś (wywołanie), edytuje (wywołanie)...
   i przy każdym z nich czyta CAŁĄ rozmowę od początku.

2. CZTERY RODZAJE TOKENÓW (tak zapisuje je Claude Code w transkryptach)
   wejście          nowy tekst, którego nie było w cache            waga x1
   odczyt z cache   część rozmowy wysłana już wcześniej, trzymana
                    w pamięci podręcznej (cache). Zwykle 90%+
                    wszystkich tokenów.                             waga x0.1
   zapis do cache   nowy fragment rozmowy (np. wynik narzędzia)
                    zapisany w cache, żeby następne wywołanie mogło
                    go tanio odczytać                   waga x1.25 (5 min) / x2 (1 h)
   wyjście          to, co model napisał: tekst, kod, wywołania
                    narzędzi, myślenie                              waga x5

3. SKĄD TE MNOŻNIKI?
   Z oficjalnego cennika API Anthropic. Dla każdego modelu obowiązują te
   same proporcje: odczyt z cache kosztuje 10% ceny zwykłego wejścia,
   zapis do cache 125% (cache 5-minutowy) lub 200% (1-godzinny), a wyjście
   5 razy tyle co wejście (np. Opus 5: 5 USD za 1M tokenów wejścia i 25 USD
   za 1M wyjścia). Wyjątki: Fable 5.1 ma odczyt z cache x0.025, Opus 5.5 x0.05.
   Na planie Pro/Max nie płacisz za tokeny, tylko masz limit użycia. Anthropic
   nie publikuje dokładnego wzoru tego limitu. Wiadomo, że droższe modele
   zużywają go szybciej. Raport ZAKŁADA, że limit liczy tokeny w tych samych
   proporcjach co cennik. To najlepsze dostępne przybliżenie, ale nie
   oficjalna liczba.

4. TOKENY SUROWE (NIEWAŻONE)
   Zwykła suma wszystkich czterech rodzajów, każdy token liczony tak samo.
   Wychodzą ogromne liczby (setki milionów), bo ta sama rozmowa jest
   czytana przy każdym wywołaniu. Surowe tokeny mówią, ILE TEKSTU przeszło
   przez model, ale nie, JAK MOCNO obciążyło to limit.

5. TOKENY WAŻONE (główna miara raportu)
   Każdy token mnożony przez wagę swojego rodzaju ORAZ wagę modelu:

     ważone = (wejście x1 + odczyt_cache x0.1 + zapis_cache x1.25 + wyjście x5)
              x waga modelu

   Przykład jednego wywołania przy rozmowie o długości ok. 100 tys. tokenów:
     odczyt z cache 100 000  x 0.1  = 10 000
     zapis do cache   2 000  x 1.25 =  2 500
     wyjście            500  x 5    =  2 500
     na Opus 5 (waga x1):   SUROWE 102 500   WAŻONE 15 000
     na Sonnet 5 (x0.4):    SUROWE 102 500   WAŻONE  6 000
   97% surowych tokenów to tani odczyt z cache, a obciążenie limitu rozkłada
   się prawie po równo na czytanie, zapis i odpowiedź.

6. WAGI MODELI (względem Opus 5)
   Fable 5 / 5.1         x2      Sonnet 4.x          x0.6
   Opus 5, Opus 4.5-4.8  x1      Sonnet 5            x0.4
   Opus 5.5              x0.8    Haiku 4.5           x0.2
   Ta sama praca na Sonnecie 5 obciąża limit 2.5 raza mniej niż na Opusie 5.

7. DLACZEGO DŁUGIE ROZMOWY ZUŻYWAJĄ WIĘCEJ
   Wywołanie przy rozmowie o długości 300 tys. tokenów musi ją całą
   przeczytać, więc samo czytanie to ok. 30 tys. tokenów ważonych, za każdym
   razem. Przy rozmowie o długości 50 tys. to tylko 5 tys. Dlatego:
     /clear    zaczyna od zera (najlepsze przy nowym, niezwiązanym zadaniu),
     /compact  zastępuje rozmowę krótkim podsumowaniem.

8. WYGASŁY CACHE
   Cache trzyma rozmowę przez 5 minut (czasem godzinę) od ostatniego użycia.
   Po dłuższej przerwie następne wywołanie musi zapisać CAŁĄ rozmowę od nowa
   (x1.25 zamiast x0.1, czyli 12.5 raza więcej za ten sam tekst).

9. JAK LICZONE SĄ CZYNNOŚCI („na co idą tokeny”)
   Każde wywołanie jest przypisane do narzędzia, którego model w nim użył
   (Read, Edit, Bash: git...). Gdy użył kilku naraz, dzielone jest po równo.
   Wywołanie bez narzędzia to odpowiedź tekstowa do Ciebie.
   Większość obciążenia to czytanie rozmowy, więc kategoria mówi, CO MODEL
   ROBIŁ w danym kroku, a nie co zajmuje w rozmowie najwięcej miejsca.

10. POZOSTAŁE POJĘCIA
   wywołanie      jedno zapytanie do modelu (jedna jego odpowiedź)
   kontekst/ctx   cała rozmowa, którą model czyta w danym wywołaniu
   subagent       osobna instancja Claude (narzędzie Agent) z własnym, czystym
                  kontekstem; jej praca nie wydłuża głównej rozmowy
   sesja          jedna rozmowa (plik transkryptu + jej subagenci)

Raport czyta wyłącznie lokalne pliki ~/.claude/projects/**/*.jsonl,
niczego nie wysyła i nie zużywa tokenów. Wagi: tabela PRICES w skrypcie
(stan 2026-09); zmienisz je opcją --prices plik.json.
"""

EXPLAIN_EN = """\
WHAT THE NUMBERS IN THIS REPORT MEAN
====================================

1. HOW CLAUDE CODE USES TOKENS
   A token is a chunk of text (3-4 characters on average). The model has no
   memory between requests, so on EVERY call Claude Code sends it the whole
   conversation so far: system instructions, tool descriptions, CLAUDE.md,
   your messages, the model's replies and tool results (file contents,
   command output).
   One request from you usually means several to dozens of calls: the model
   reads a file (a call), searches (a call), edits (a call)... and every one
   of them re-reads the WHOLE conversation from the start.

2. FOUR TOKEN TYPES (as Claude Code records them in its transcripts)
   input          new text that was not in the cache              weight x1
   cache read     part of the conversation sent before and kept
                  in the cache. Usually 90%+ of all tokens.       weight x0.1
   cache write    a new piece of conversation (e.g. a tool result)
                  stored in the cache so the next call can read
                  it cheaply                       weight x1.25 (5 min) / x2 (1 h)
   output         what the model wrote: text, code, tool calls,
                  thinking                                        weight x5

3. WHERE DO THESE MULTIPLIERS COME FROM?
   From Anthropic's official API pricing. Every model uses the same ratios:
   a cache read costs 10% of a normal input token, a cache write 125%
   (5-minute cache) or 200% (1-hour cache), and output 5 times the input
   price (e.g. Opus 5: $5 per 1M input tokens and $25 per 1M output tokens).
   Exceptions: Fable 5.1 cache reads are x0.025, Opus 5.5 x0.05.
   On a Pro/Max plan you don't pay per token, you have a usage limit.
   Anthropic does not publish the exact formula behind it. It is known that
   pricier models use it faster. This report ASSUMES the limit counts tokens
   in the same proportions as the pricing. That is the best available proxy,
   not an official number.

4. RAW (UNWEIGHTED) TOKENS
   The plain sum of all four types, every token counted the same. The
   numbers get huge (hundreds of millions) because the same conversation is
   re-read on every call. Raw tokens tell you HOW MUCH TEXT went through the
   model, not HOW HEAVILY it used your limit.

5. WEIGHTED TOKENS (the main measure of this report)
   Each token is multiplied by the weight of its type AND the model's weight:

     weighted = (input x1 + cache_read x0.1 + cache_write x1.25 + output x5)
                x model weight

   Example of one call in a conversation of about 100k tokens:
     cache read  100,000  x 0.1  = 10,000
     cache write   2,000  x 1.25 =  2,500
     output          500  x 5    =  2,500
     on Opus 5 (weight x1):    RAW 102,500   WEIGHTED 15,000
     on Sonnet 5 (x0.4):       RAW 102,500   WEIGHTED  6,000
   97% of the raw tokens are cheap cache reads, yet the load on the limit is
   split almost evenly between reading, writing and answering.

6. MODEL WEIGHTS (relative to Opus 5)
   Fable 5 / 5.1         x2      Sonnet 4.x          x0.6
   Opus 5, Opus 4.5-4.8  x1      Sonnet 5            x0.4
   Opus 5.5              x0.8    Haiku 4.5           x0.2
   The same work on Sonnet 5 uses the limit 2.5 times less than on Opus 5.

7. WHY LONG CONVERSATIONS USE MORE
   A call in a 300k-token conversation has to read all of it, so reading
   alone is about 30k weighted tokens, every single time. In a 50k-token
   conversation it is only 5k. That's why:
     /clear    starts from zero (best when switching to an unrelated task),
     /compact  replaces the conversation with a short summary.

8. EXPIRED CACHE
   The cache keeps the conversation for 5 minutes (sometimes an hour) after
   its last use. After a longer break the next call has to write the WHOLE
   conversation again (x1.25 instead of x0.1, i.e. 12.5x more for the same
   text).

9. HOW ACTIVITIES ARE COUNTED ("where the tokens go")
   Each call is assigned to the tool the model used in it (Read, Edit,
   Bash: git...). If it used several at once, it is split evenly. A call
   without a tool is a text reply to you.
   Most of the load is re-reading the conversation, so the category says
   WHAT THE MODEL WAS DOING in that step, not what takes the most space.

10. OTHER TERMS
   call           one request to the model (one model response)
   context/ctx    the whole conversation the model reads in a call
   subagent       a separate Claude instance (Agent tool) with its own clean
                  context; its work does not grow the main conversation
   session        one conversation (transcript file + its subagents)

The report reads only local files ~/.claude/projects/**/*.jsonl, sends
nothing and uses no tokens. Weights: the PRICES table in the script
(as of 2026-09); override with --prices file.json.
"""


def explain_text():
    return EXPLAIN_PL if LANG == "pl" else EXPLAIN_EN


# --------------------------------------------------------------------------- HTML report

SERIES = {  # token type -> CSS variable (validated categorical slots 1-4)
    "input": "--s1", "cache_read": "--s2", "cache_write": "--s3", "output": "--s4"}

HELP = {  # tooltip texts for the "?" marks in the HTML report: key -> (pl, en)
    "calls": ("Wywołanie = jedno zapytanie do modelu (jedna jego odpowiedź). Jedna Twoja "
              "wiadomość to zwykle wiele wywołań — każde użycie narzędzia to kolejne.",
              "A call is one request to the model (one model response). One message from you "
              "usually triggers many calls — every tool use is another one."),
    "raw": ("Cały tekst, który model przeczytał i napisał, każdy token liczony tak samo. "
            "Model czyta rozmowę od nowa przy każdym wywołaniu, więc liczba jest ogromna i "
            "sama w sobie niewiele mówi.",
            "All text the model read and wrote, every token counted the same. The model "
            "re-reads the conversation on every call, so the number is huge and says little "
            "on its own."),
    "weighted": ("Główna miara. Tokeny liczone według tego, jak mocno obciążają limit: odczyt "
                 "z cache x0.1, nowy tekst x1, zapis do cache x1.25, odpowiedź x5, razy waga "
                 "modelu (Opus 5 x1, Sonnet 5 x0.4). Proporcje wzięte z cennika API Anthropic.",
                 "The main measure. Tokens counted by how heavily they use your limit: cache "
                 "read x0.1, new text x1, cache write x1.25, output x5, times the model weight "
                 "(Opus 5 x1, Sonnet 5 x0.4). Ratios taken from Anthropic's API pricing."),
    "hit": ("Jaka część rozmowy była tanim powtórnym odczytem z cache. Powyżej ~90% to dobry "
            "wynik; spadki = przerwy dłuższe niż 5 min albo zmiana modelu.",
            "How much of the conversation was cheap re-reading from cache. Above ~90% is good; "
            "drops = breaks over 5 minutes or a model switch."),
    "avgcall": ("Ile tokenów ważonych zużywa średnio jedno wywołanie modelu.",
                "How many weighted tokens one model call uses on average."),
    "weight": ("Mnożnik rodzaju tokenu z cennika API: odczyt z cache kosztuje 10% zwykłego "
               "wejścia, zapis 125% (5 min) lub 200% (1 h), wyjście 500%.",
               "Token type multiplier from the API pricing: a cache read costs 10% of normal "
               "input, a write 125% (5 min) or 200% (1 h), output 500%."),
    "mweight": ("Jak mocno model obciąża limit względem Opus 5 (x1), wg proporcji cen API. Ta "
                "sama praca na modelu x0.4 zużywa 2.5 raza mniej.",
                "How heavily the model uses the limit relative to Opus 5 (x1), based on API "
                "price ratios. The same work on a x0.4 model uses 2.5 times less."),
    "types": ("Te same tokeny policzone na dwa sposoby. Surowe: prawie wszystko to odczyt z "
              "cache. Ważone: widać, że odpowiedzi i zapisy do cache obciążają limit dużo "
              "bardziej, niż sugeruje ich liczba.",
              "The same tokens counted two ways. Raw: almost everything is cache reads. "
              "Weighted: output and cache writes load the limit far more than their count "
              "suggests."),
    "time": ("Tokeny ważone w kolejnych dniach (lub tygodniach), podzielone na rodzaje. Najedź "
             "na słupek, żeby zobaczyć dokładne wartości.",
             "Weighted tokens per day (or week), split by type. Hover a bar for exact values."),
    "daily": ("Każdy dzień porównany z poprzednim (w tokenach ważonych), z czynnością, która "
              "zmieniła się najbardziej. ▲ więcej, ▼ mniej, = bez zmian (±1%). Pierwszy "
              "wiersz (baza) to dzień przed okresem.",
              "Each day compared with the previous one (in weighted tokens), with the activity "
              "that changed the most. ▲ more, ▼ less, = unchanged (±1%). The first row (base) "
              "is the day before the period."),
    "driver": ("Czynność, której zużycie zmieniło się najbardziej względem poprzedniego dnia.",
               "The activity whose usage changed the most compared with the previous day."),
    "activity": ("Każde wywołanie przypisane do narzędzia, którego model w nim użył (przy kilku "
                 "narzędziach — po równo). „Bez narzędzia” = odpowiedź tekstowa do Ciebie.",
                 "Each call is assigned to the tool the model used in it (split evenly if "
                 "several). 'No tool' = a text reply to you."),
    "uses": ("Ile razy model użył tego narzędzia.", "How many times the model used this tool."),
    "avg": ("Ile tokenów ważonych średnio na jedno wywołanie lub użycie.",
            "Average weighted tokens per call or use."),
    "models": ("Zużycie wg modelu. Droższy model obciąża limit mocniej za tę samą pracę.",
               "Usage by model. A pricier model uses more of the limit for the same work."),
    "side": ("Sesja główna = Twoja rozmowa. Subagenci = osobne instancje Claude uruchomione "
             "narzędziem Agent; mają własny kontekst, więc nie wydłużają głównej rozmowy.",
             "Main session = your conversation. Subagents = separate Claude instances started "
             "with the Agent tool; they have their own context and don't grow the main one."),
    "agents": ("Zużycie subagentów wg typu (wbudowane albo Twoje własne).",
               "Subagent usage by type (built-in or your own)."),
    "projects": ("Zużycie wg katalogu, w którym uruchomiono sesję.",
                 "Usage by the working directory the session was started in."),
    "length": ("Kontekst = cała rozmowa czytana przy danym wywołaniu. Rośnie z każdym krokiem, "
               "więc im dłuższa rozmowa, tym więcej waży każde wywołanie. Nowe zadanie → "
               "/clear, długa praca → /compact.",
               "Context = the whole conversation read in a call. It grows with every step, so "
               "the longer the conversation, the more each call weighs. New task → /clear, "
               "long work → /compact."),
    "reading": ("Część wywołania, która idzie tylko na ponowne przeczytanie rozmowy. Rośnie "
                "razem z długością rozmowy.",
                "The part of a call spent only on re-reading the conversation. It grows with "
                "the conversation's length."),
    "sessions": ("Najcięższe rozmowy (razem z ich subagentami). Temat = Twoja pierwsza prośba. "
                 "Szczegóły: --session <id>.", "The heaviest conversations (including their "
                 "subagents). Topic = your first request. Details: --session <id>."),
    "maxctx": ("Do jakiego rozmiaru (w tokenach) urosła główna rozmowa.",
               "How large (in tokens) the main conversation grew."),
    "subshare": ("Jaka część zużycia tej sesji przypadła na subagentów.",
                 "The share of this session's usage spent by subagents."),
    "rebuild": ("Cache trzyma rozmowę 5 minut (lub godzinę). Po dłuższej przerwie model "
                "zapisuje całą rozmowę od nowa (x1.25) zamiast ją odczytać (x0.1). Liczone, gdy "
                "rozmowa ma ≥20k tokenów i ≥50% z niej zapisano.",
                "The cache keeps the conversation for 5 minutes (or an hour). After a longer "
                "break the model writes it all again (x1.25) instead of reading it (x0.1). "
                "Counted when the conversation is ≥20k tokens and ≥50% of it was written."),
    "waste": ("O ile więcej zużyły te odbudowy niż zwykły odczyt z cache.",
              "How much more those rebuilds used than a normal cache read."),
    "reread": ("Odczyty (narzędzie Read) fragmentu pliku, który już był w rozmowie — bez zmian "
               "ani kompakcji pomiędzy.", "Read tool calls for a part of a file already in the "
               "conversation — no edit or compaction in between."),
    "tips": ("Wskazówki wyliczone automatycznie z liczb powyżej.",
             "Suggestions computed automatically from the numbers above."),
    "compare": ("Te same miary dla poprzedniego okresu o tej samej długości.",
                "The same metrics for the previous period of the same length."),
}


def qm(key):
    """a focusable '?' that shows an explanation tooltip"""
    pl, en = HELP[key]
    return (f"<button type=button class=q aria-label='{html.escape(L('wyjaśnienie', 'explain'))}'"
            f" data-tip='{html.escape(L(pl, en), quote=True)}'>?</button>")


TOOLTIP_JS = """<div id=tip role=tooltip hidden></div>
<script>
(function(){
  var tip=document.getElementById('tip'),cur=null;
  function show(el){
    tip.textContent=el.getAttribute('data-tip');tip.hidden=false;cur=el;
    var r=el.getBoundingClientRect(),w=tip.offsetWidth,h=tip.offsetHeight;
    var x=Math.max(8,Math.min(r.left+r.width/2-w/2,innerWidth-w-8));
    var y=r.bottom+8;if(y+h>innerHeight-8)y=Math.max(8,r.top-h-8);
    tip.style.left=x+'px';tip.style.top=y+'px';
  }
  function hide(){tip.hidden=true;cur=null;}
  document.addEventListener('mouseover',function(e){var q=e.target.closest('.q');if(q)show(q);});
  document.addEventListener('mouseout',function(e){if(e.target.closest('.q'))hide();});
  document.addEventListener('focusin',function(e){var q=e.target.closest('.q');
    if(q&&q.matches(':focus-visible'))show(q);});
  document.addEventListener('focusout',hide);
  document.addEventListener('click',function(e){var q=e.target.closest('.q');if(q)show(q);else hide();});
  document.addEventListener('keydown',function(e){if(e.key==='Escape')hide();});
  addEventListener('scroll',function(){if(cur)hide();},{passive:true});
})();
</script>"""

CSS = """
:root{--bg:#f7f6f3;--card:#fcfcfb;--fg:#0b0b0b;--mut:#52514e;--line:#e3e1dc;--acc:#2a78d6;
--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--up:#b3261e;--down:#1c5cab;
--upbar:#e34948;--downbar:#2a78d6;--tipbg:#0b0b0b;--tipfg:#fff}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#121211;--card:#1a1a19;
--fg:#fff;--mut:#c3c2b7;--line:#34332f;--acc:#3987e5;--s1:#3987e5;--s2:#d95926;--s3:#199e70;
--s4:#c98500;--up:#f2857d;--down:#86b6ef;--upbar:#e66767;--downbar:#3987e5;--tipbg:#f3f2ee;
--tipfg:#0b0b0b}}
:root[data-theme="dark"]{--bg:#121211;--card:#1a1a19;--fg:#fff;--mut:#c3c2b7;--line:#34332f;
--acc:#3987e5;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--up:#f2857d;--down:#86b6ef;
--upbar:#e66767;--downbar:#3987e5;--tipbg:#f3f2ee;--tipfg:#0b0b0b}
*{box-sizing:border-box}
body{margin:0;padding:28px 16px;background:var(--bg);color:var(--fg);
font:14px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1040px;margin:0 auto}
h1{font-size:24px;margin:0 0 4px}
h2{font-size:15px;margin:32px 0 10px;letter-spacing:.02em;display:flex;align-items:center}
.sub{color:var(--mut);margin:0 0 14px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:18px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.card>b{display:block;font-size:24px;font-weight:650;font-variant-numeric:tabular-nums}
.card>span{color:var(--mut);font-size:12.5px}
.card.main{border-color:var(--acc);box-shadow:inset 0 0 0 1px var(--acc)}
.wrap{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%;min-width:560px}
table.daily{min-width:860px} table.daily td:first-child{white-space:nowrap}
td,th{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:middle}
th{color:var(--mut);font-weight:500;font-size:12.5px;white-space:nowrap}
tr:last-child td{border-bottom:0}
tr.base td{color:var(--mut)}
.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.m{font-family:ui-monospace,Menlo,monospace}
.t{color:var(--mut);font-size:12.5px;max-width:340px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.few{color:var(--mut);font-size:11.5px}
.b{width:28%;min-width:110px} .b span{display:block;height:8px;border-radius:0 4px 4px 0;background:var(--acc)}
.up{color:var(--up)} .down{color:var(--down)}
.dv{position:relative;width:130px;height:10px}
.dv::before{content:"";position:absolute;left:50%;top:-3px;bottom:-3px;border-left:1px solid var(--mut)}
.dv span{position:absolute;top:1px;height:8px}
.dvu{left:calc(50% + 1px);background:var(--upbar);border-radius:0 4px 4px 0}
.dvd{right:calc(50% + 1px);background:var(--downbar);border-radius:4px 0 0 4px}
.srow{display:flex;align-items:center;gap:12px;margin:8px 0}
.slab{width:150px;flex:none;color:var(--mut);font-size:12.5px;display:flex;align-items:center}
.stack{flex:1;display:flex;height:22px;gap:2px} .stack span{display:block;height:100%}
.stack span:first-child{border-radius:4px 0 0 4px} .stack span:last-child{border-radius:0 4px 4px 0}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:12.5px;color:var(--mut);margin-bottom:8px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}
svg{width:100%;height:auto;display:block} .gl{stroke:var(--line)}
.ax{fill:var(--mut);font-size:11px}
.q{display:inline-flex;align-items:center;justify-content:center;flex:none;width:17px;height:17px;
margin-left:6px;padding:0;border:1px solid var(--mut);border-radius:50%;background:transparent;
color:var(--mut);font:600 10.5px/1 ui-sans-serif,system-ui,sans-serif;cursor:help;vertical-align:1px;
position:relative}
.q::after{content:"";position:absolute;inset:-7px}
.q:hover,.q:focus-visible{color:var(--acc);border-color:var(--acc);outline:none}
#tip{position:fixed;z-index:20;max-width:min(320px,calc(100vw - 16px));padding:8px 11px;
border-radius:8px;background:var(--tipbg);color:var(--tipfg);font-size:12.5px;line-height:1.45;
box-shadow:0 4px 18px rgba(0,0,0,.18);pointer-events:none;font-weight:400;letter-spacing:0}
details{margin-top:12px} summary{cursor:pointer;color:var(--acc);font-weight:600}
.explain{white-space:pre-wrap;font:12.5px/1.55 ui-monospace,Menlo,monospace;overflow-x:auto}
ul{padding-left:20px} li{margin:6px 0}
footer{color:var(--mut);font-size:12px;margin-top:32px;border-top:1px solid var(--line);padding-top:12px}
@media (max-width:600px){.slab{width:105px} h1{font-size:20px}}
"""


def merge_types(d):
    return {"input": d["input"], "cache_read": d["cache_read"],
            "cache_write": d["cache_write_5m"] + d["cache_write_1h"], "output": d["output"]}


def type_labels():
    return {"input": type_name("input"), "cache_read": type_name("cache_read"),
            "cache_write": L("zapis do cache", "cache write"), "output": type_name("output")}


def html_daily(rows):
    E = html.escape
    changes = [abs(r["b"]["w"] - r["p"]["w"]) for r in rows if r["p"] is not None
               and not r["base"]]
    mx = max(changes, default=0) or 1e-9
    trs = []
    for r in rows:
        b, p, d = r["b"], r["p"], r["date"]
        name = f"{d:%m-%d} {wd(d)}"
        hit = f"{r['hit']:.0f}%" if r["hit"] is not None else "–"
        per = fmt_tok(r["per_call"]) if r["per_call"] is not None else "–"
        if p is None or r["base"]:
            tag = f" <small>({L('baza', 'base')})</small>" if r["base"] else ""
            trs.append(f"<tr class=base><td class=l>{name}{tag}</td><td class=n>"
                       f"{fmt_tok(b['w'])}</td><td></td><td></td><td></td>"
                       f"<td class=n>{b['n']}</td><td class=n>{hit}</td><td class=n>{per}</td>"
                       f"<td></td></tr>")
            continue
        dw = b["w"] - p["w"]
        ar = arrow(b["w"], p["w"])
        cls = "up" if ar == "▲" else "down" if ar == "▼" else ""
        dbar = (f"<div class=dv><span class={'dvu' if dw >= 0 else 'dvd'} "
                f"style='width:{50 * abs(dw) / mx:.1f}%' title='{fmt_delta(dw)}'></span></div>")
        drv = ""
        if r["driver"] and abs(r["driver"][1]) >= 1:
            dk, dv = r["driver"]
            drv = (f"<span class={'up' if dv > 0 else 'down'}>{fmt_delta(dv)}</span> "
                   f"{E(activity_name(dk))}")
        trs.append(f"<tr><td class=l>{name}</td><td class=n>{fmt_tok(b['w'])}</td>"
                   f"<td class='n {cls}'>{ar} {fmt_delta(dw)}</td>"
                   f"<td class='n {cls}'>{fmt_change(b['w'], p['w'])}</td><td>{dbar}</td>"
                   f"<td class=n>{b['n']}</td><td class=n>{hit}</td><td class=n>{per}</td>"
                   f"<td class=t>{drv}</td></tr>")
    sm = daily_summary(rows)
    cards = ""
    if sm:
        cards = (
            f"<div class=grid>"
            f"<div class=card><b>{fmt_tok(sm['avg'])}</b><span>"
            f"{L('średnio dziennie', 'daily average')} ({sm['n']} {L('dni', 'days')})</span></div>"
            f"<div class=card><b>{fmt_tok(sm['hi']['b']['w'])}</b><span>"
            f"{L('najwięcej', 'highest')}: {sm['hi']['date']}</span></div>"
            f"<div class=card><b>{fmt_tok(sm['lo']['b']['w'])}</b><span>"
            f"{L('najmniej', 'lowest')}: {sm['lo']['date']}</span></div>"
            f"<div class=card><b><span class=up>▲ {sm['up']}</span> · <span class=down>▼ "
            f"{sm['down']}</span></b><span>{L('dni wzrostu · spadku', 'days up · down')}"
            f"</span></div></div>")
    return (f"<h2>{L('Dzień po dniu', 'Day by day')}{qm('daily')}</h2>{cards}"
            f"<div class=wrap><table class=daily><tr><th>{L('dzień', 'day')}</th><th class=n>"
            f"{L('ważone', 'weighted')}{qm('weighted')}</th><th class=n>{L('zmiana', 'change')}"
            f"</th><th class=n>%</th><th>{L('wzrost / spadek', 'up / down')}</th><th class=n>"
            f"{L('wywoł.', 'calls')}{qm('calls')}</th><th class=n>cache{qm('hit')}</th>"
            f"<th class=n>{L('śr./wyw.', 'avg/call')}{qm('avgcall')}</th><th>"
            f"{L('największa zmiana', 'biggest change')}{qm('driver')}</th></tr>{''.join(trs)}"
            f"</table></div>")


def html_report(R, ctx, Rp=None, daily=None):
    E = html.escape
    tot = R["w"] or 1e-9
    raw = sum(R["tok"].values()) or 1
    hit = cache_hit(R["tok"]) or 0
    w_h, calls_h = L("ważone", "weighted"), L("wywoł.", "calls")

    def btable(groups, label, names=lambda k: k, top=12, n_label=None, n_key="calls",
               extra=None):
        items = sorted(groups.items(), key=lambda kv: -kv[1]["w"])[:top]
        mx = max((b["w"] for _, b in items), default=0) or 1e-9
        xh = f"<th class=n>{extra[0]}</th>" if extra else ""
        rows = "".join(
            f"<tr><td class=l>{E(str(names(k)))}</td>"
            + (f"<td class=n>{extra[1](k)}</td>" if extra else "")
            + f"<td class=n>{fmt_tok(b['w'])}</td><td class=n>{pct(b['w'], tot):.1f}%</td>"
            f"<td class=n>{b['n']}</td><td class=n>{fmt_tok(b['w'] / b['n'] if b['n'] else 0)}"
            f"</td><td class=b><span style='width:{100 * b['w'] / mx:.1f}%'"
            f" title='{E(str(names(k)))}: {fmt_tok(b['w'])}'></span></td></tr>"
            for k, b in items)
        return (f"<div class=wrap><table><tr><th>{E(label)}</th>{xh}<th class=n>{w_h}"
                f"{qm('weighted')}</th><th class=n>%</th><th class=n>{n_label or calls_h}"
                f"{qm(n_key)}</th><th class=n>{L('śr.', 'avg')}{qm('avg')}</th><th></th></tr>"
                f"{rows}</table></div>")

    trows = "".join(
        f"<tr><td class=l>{E(type_name(t))}</td><td class=n>{fmt_tok(R['tok'][t])}</td>"
        f"<td class=n>{pct(R['tok'][t], raw):.1f}%</td><td class=n>x{WEIGHTS[t]:g}</td>"
        f"<td class=n>{fmt_tok(R['w_t'][t])}</td><td class=n>{pct(R['w_t'][t], tot):.1f}%</td></tr>"
        for t in TYPES if not (t == "cache_write_1h" and not R["tok"][t]))

    tnames = type_labels()
    stacks = []
    for lab, d, hk in ((L("tokeny surowe", "raw tokens"), merge_types(R["tok"]), "raw"),
                       (L("tokeny ważone", "weighted tokens"), merge_types(R["w_t"]), "weighted")):
        s = sum(d.values()) or 1e-9
        segs = "".join(
            f"<span style='width:{100 * v / s:.2f}%;background:var({SERIES[k]})' "
            f"title='{E(tnames[k])}: {100 * v / s:.1f}%'></span>"
            for k, v in d.items() if v > 0)
        stacks.append(f"<div class=srow><div class=slab>{E(lab)}{qm(hk)}</div><div class=stack>"
                      f"{segs}</div></div>")
    legend = "".join(f"<span><i style='background:var({SERIES[k]})'></i>{E(v)}</span>"
                     for k, v in tnames.items())

    # time chart: weighted tokens per period, stacked by token type
    key = "week" if ctx["chart"] == "week" else "day"
    periods = sorted(R[key].items(), key=lambda kv: kv[1]["date"])
    chart = ""
    if len(periods) > 1:
        mx = max(b["w"] for _, b in periods) or 1e-9
        n = len(periods)
        W, H, pad_l, pad_b, pad_t = 720, 230, 52, 34, 12
        ph = H - pad_b - pad_t
        bw = (W - pad_l) / n
        parts = []
        for g in range(5):
            y = pad_t + ph * (1 - g / 4)
            parts.append(f"<line x1={pad_l} x2={W} y1={y:.1f} y2={y:.1f} class=gl />"
                         f"<text x={pad_l - 6} y={y + 4:.1f} class=ax text-anchor=end>"
                         f"{fmt_tok(mx * g / 4)}</text>")
        for i, (k, b) in enumerate(periods):
            x = pad_l + i * bw + bw * 0.15
            y0 = H - pad_b
            m = merge_types(b["w_t"])
            for t in ("cache_read", "cache_write", "input", "output"):
                h = ph * m[t] / mx
                if h <= 0:
                    continue
                parts.append(f"<rect x={x:.1f} y={y0 - h:.1f} width={bw * 0.7:.1f} "
                             f"height={max(h - 1, 0.5):.1f} fill='var({SERIES[t]})'><title>"
                             f"{E(k)} — {E(tnames[t])}: {fmt_tok(m[t])}</title></rect>")
                y0 -= h
            parts.append(f"<rect x={pad_l + i * bw:.1f} y=0 width={bw:.1f} height={H - pad_b} "
                         f"fill=transparent><title>{E(k)}: {fmt_tok(b['w'])} "
                         f"{L('ważonych', 'weighted')}, {b['n']} {L('wywołań', 'calls')}"
                         f"</title></rect>")
            if n <= 16 or i % max(1, n // 12) == 0:
                lab = k[5:10] if key == "day" else k[5:8]
                parts.append(f"<text x={pad_l + i * bw + bw / 2:.1f} y={H - pad_b + 16} "
                             f"class=ax text-anchor=middle>{E(lab)}</text>")
        chart = (f"<h2>{L('Zużycie w czasie', 'Usage over time')}{qm('time')}</h2><div class=card>"
                 f"<div class=legend>{legend}</div><svg viewBox='0 0 {W} {H}' role=img "
                 f"aria-label='{L('zużycie w czasie', 'usage over time')}'>{''.join(parts)}</svg>"
                 f"</div>")

    ctx_rows = ""
    for _, _, nm in CTX_BUCKETS:
        b = R["ctxb"][nm]
        if not b["n"]:
            continue
        few = f" <span class=few>({L('mało danych', 'few calls')})</span>" \
            if b["n"] < FEW_CALLS else ""
        ctx_rows += (f"<tr><td class=l>{nm}{few}</td><td class=n>{b['n']}</td>"
                     f"<td class=n>{fmt_tok(b['w'])}</td><td class=n>{pct(b['w'], tot):.1f}%</td>"
                     f"<td class=n>{fmt_tok(b['w'] / b['n'])}</td>"
                     f"<td class=n>{fmt_tok(b['read'] / b['n'])}</td></tr>")
    g = ctx_growth(R)
    growth = ""
    if g:
        growth = (f"<p class=sub style='margin-top:10px'>" + E(L(
            f"Wywołanie przy kontekście {g[2]} waży średnio {g[0] / g[1]:.1f}x tyle co przy "
            f"50-100k. Grupa „< 50k” to często początki rozmów, które najpierw zapisują "
            f"wszystko do cache.",
            f"A call at {g[2]} context weighs {g[0] / g[1]:.1f}x as much as one at 50-100k on "
            f"average. The '< 50k' group is often conversation starts, which first write "
            f"everything to the cache.")) + "</p>")

    sessions_sec = ""
    if not ctx.get("session"):
        ses_rows = ""
        for sk, s in sorted(R["sess"].items(), key=lambda kv: -kv[1]["w"])[:ctx["top"] + 5]:
            meta = ctx["sessions"].get(sk, {})
            ses_rows += (
                f"<tr><td class=m>{E(sk[1][:8])}</td><td>{E(ctx['namer'].project(meta, sk[0]))}"
                f"</td><td class=n>{fmt_tok(s['w'])}</td><td class=n>{pct(s['w'], tot):.1f}%"
                f"</td><td class=n>{s['n']}</td><td class=n>{fmt_tok(s['max_ctx'])}</td>"
                f"<td class=n>{pct(s['sub_w'], s['w']):.0f}%</td>"
                f"<td class=t>{E(ctx['namer'].topic(meta.get('topic'))[:100])}</td></tr>")
        sessions_sec = (
            f"<h2>{L('Najcięższe rozmowy', 'Heaviest conversations')}{qm('sessions')}</h2>"
            f"<div class=wrap><table><tr><th>{L('sesja', 'session')}</th><th>"
            f"{L('projekt', 'project')}</th><th class=n>{w_h}{qm('weighted')}</th><th class=n>%"
            f"</th><th class=n>{calls_h}</th><th class=n>{L('maks. ctx', 'max ctx')}"
            f"{qm('maxctx')}</th><th class=n>{L('subag.', 'sub')}{qm('subshare')}</th><th>"
            f"{L('temat', 'topic')}</th></tr>{ses_rows}</table></div>")

    diff = ""
    if Rp is not None:
        def drow(name, a, b, f):
            cls = "up" if a > b else "down"
            return (f"<tr><td class=l>{E(name)}</td><td class=n>{f(a)}</td><td class=n>{f(b)}</td>"
                    f"<td class='n {cls}'>{arrow(a, b)} {fmt_change(a, b)}</td></tr>")
        rows = [drow(L("wywołania modelu", "model calls"), R["n"], Rp["n"], fmt_int),
                drow(L("tokeny surowe", "raw tokens"), raw, sum(Rp["tok"].values()), fmt_tok),
                drow(L("tokeny ważone", "weighted tokens"), R["w"], Rp["w"], fmt_tok),
                drow(L("średnio na wywołanie", "average per call"), R["w"] / max(R["n"], 1),
                     Rp["w"] / max(Rp["n"], 1), fmt_tok)]
        keys = sorted(set(R["act"]) | set(Rp["act"]),
                      key=lambda k: -(R["act"][k]["w"] if k in R["act"] else 0))[:12]
        rows += [drow(activity_name(k), R["act"][k]["w"] if k in R["act"] else 0,
                      Rp["act"][k]["w"] if k in Rp["act"] else 0, fmt_tok) for k in keys]
        diff = (f"<h2>{L('Porównanie', 'Comparison')}{qm('compare')}</h2><p class=sub>"
                f"{E(ctx['label'])} vs {E(ctx['prev_label'])}</p><div class=wrap><table><tr><th>"
                f"</th><th class=n>{L('teraz', 'now')}</th><th class=n>{L('wcześniej', 'before')}"
                f"</th><th class=n>{L('zmiana', 'change')}</th></tr>{''.join(rows)}</table></div>")

    rb, rr = R["rebuild"], R["reread"]
    tips_html = "".join(f"<li>{E(t)}</li>" for t in tips(R))
    title = L("Zużycie tokenów", "Token usage")
    unknown = ""
    if UNKNOWN_MODELS:
        unknown = (f"<p class=sub>{L('Nieznane modele liczone z wagą Opus 5', 'Unknown models weighted as Opus 5')}: "
                   f"{E(', '.join(sorted(UNKNOWN_MODELS)))}</p>")
    agents_sec = (f"<h2>{L('Subagenci wg typu', 'Subagents by type')}{qm('agents')}</h2>"
                  + btable(R['agent'], L('typ', 'type'))) if R['agent'] else ''
    proj_sec = (f"<h2>{L('Projekty', 'Projects')}{qm('projects')}</h2>"
                + btable(R['proj'], L('projekt', 'project'))) if not ctx.get('session') else ''
    mw = (f"{L('waga', 'weight')}{qm('mweight')}", lambda k: "x" + format(model_weight(k), ".2g"))

    return f"""<!doctype html>
<html lang={LANG}><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>{title} — Claude Code</title>
<style>{CSS}</style></head><body><main>
<h1>{title} — {E(ctx['label'])}</h1>
<p class=sub>{L('Źródło: lokalne transkrypty Claude Code. Raport nie zużywa tokenów. Najedź lub kliknij „?”, żeby zobaczyć wyjaśnienie.',
                'Source: local Claude Code transcripts. This report uses no tokens. Hover or tap “?” for an explanation.')}</p>
<div class=grid>
<div class="card main"><b>{fmt_tok(R['w'])}</b><span>{L('tokenów ważonych — główna miara', 'weighted tokens — the main measure')}{qm('weighted')}</span></div>
<div class=card><b>{fmt_tok(raw)}</b><span>{L('tokenów surowych (nieważonych)', 'raw (unweighted) tokens')}{qm('raw')}</span></div>
<div class=card><b>{fmt_int(R['n'])}</b><span>{L('wywołań modelu', 'model calls')} · {R['n_sessions']} {L('sesji', 'sessions')}{qm('calls')}</span></div>
<div class=card><b>{fmt_tok(R['w'] / max(R['n'], 1))}</b><span>{L('ważonych na wywołanie', 'weighted per call')}{qm('avgcall')}</span></div>
<div class=card><b>{hit:.0f}%</b><span>{L('rozmowy z cache', 'of conversation from cache')}{qm('hit')}</span></div>
</div>
<details><summary>{L('Co to są tokeny surowe i ważone? Skąd wagi? (pełne wyjaśnienie)', 'What are raw and weighted tokens? Where do the weights come from? (full explanation)')}</summary>
<div class="card explain">{E(explain_text())}</div></details>
{diff}
{html_daily(daily) if daily else ''}
<h2>{L('Rodzaje tokenów: surowe vs ważone', 'Token types: raw vs weighted')}{qm('types')}</h2>
<div class=card><div class=legend>{legend}</div>{''.join(stacks)}</div>
<div class=wrap style="margin-top:12px"><table><tr><th>{L('rodzaj', 'type')}</th><th class=n>{L('surowe', 'raw')}{qm('raw')}</th><th class=n>%</th><th class=n>{L('waga', 'weight')}{qm('weight')}</th><th class=n>{w_h}{qm('weighted')}</th><th class=n>%</th></tr>{trows}</table></div>
{chart}
<h2>{L('Na co idą tokeny', 'Where the tokens go')}{qm('activity')}</h2>
{btable(R['act'], L('czynność', 'activity'), activity_name, 20, L('użyć', 'uses'), 'uses')}
<h2>{L('Modele', 'Models')}{qm('models')}</h2>{btable(R['model'], 'model', extra=mw)}{unknown}
<h2>{L('Sesja główna vs subagenci', 'Main session vs subagents')}{qm('side')}</h2>
{btable(R['side'], L('gdzie', 'where'), side_name)}
{agents_sec}
{proj_sec}
<h2>{L('Długość rozmowy', 'Conversation length')}{qm('length')}</h2>
<div class=wrap><table><tr><th>{L('kontekst', 'context')}</th><th class=n>{calls_h}</th><th class=n>{w_h}{qm('weighted')}</th><th class=n>%</th><th class=n>{L('śr./wywoł.', 'avg/call')}{qm('avgcall')}</th><th class=n>{L('w tym czytanie', 'of it reading')}{qm('reading')}</th></tr>{ctx_rows}</table></div>
{growth}
{sessions_sec}
<h2>{L('Cache i powtórki', 'Cache and repeats')}</h2>
<div class=grid>
<div class=card><b>{rb['n']}</b><span>{L('razy rozmowa zapisana od nowa', 'times the conversation was rewritten')}{qm('rebuild')}</span></div>
<div class=card><b>{pct(rb['waste'], tot):.1f}%</b><span>{L('zużycia to nadmiar przez wygasły cache', 'of usage was extra from expired cache')} ({fmt_tok(rb['waste'])}){qm('waste')}</span></div>
<div class=card><b>{pct(rr['repeat'], rr['reads']):.0f}%</b><span>{L('odczytów plików to powtórki', 'of file reads were repeats')} ({rr['repeat']}/{rr['reads']}){qm('reread')}</span></div>
</div>
<h2>{L('Co można poprawić', 'What you could improve')}{qm('tips')}</h2><div class=card><ul>{tips_html}</ul></div>
<footer>{L('Wagi rodzajów: wejście x1, odczyt cache x0.1, zapis cache x1.25 (5 min) / x2 (1 h), wyjście x5; wagi modeli względem Opus 5. Proporcje z cennika API Anthropic (stan 2026-09). Anthropic nie publikuje wzoru limitów subskrypcji — to przybliżenie.', 'Type weights: input x1, cache read x0.1, cache write x1.25 (5 min) / x2 (1 h), output x5; model weights relative to Opus 5. Ratios from Anthropic API pricing (as of 2026-09). Anthropic does not publish the subscription limit formula — this is an approximation.')}
{L('Wygenerowano', 'Generated')} {datetime.datetime.now():%Y-%m-%d %H:%M}.</footer>
</main>
{TOOLTIP_JS}
</body></html>"""


# --------------------------------------------------------------------------- windows & sessions

def midnight(d):
    """local midnight at the start of calendar day d"""
    return datetime.datetime.combine(d, datetime.time(0)).astimezone()


def parse_day(s):
    """YYYY-MM-DD, DD.MM.YYYY, MM-DD (this year), today/yesterday"""
    v = s.strip().lower()
    today = datetime.date.today()
    if v in ("today", "dzis", "dziś", "dzisiaj"):
        return today
    if v in ("yesterday", "wczoraj"):
        return today - datetime.timedelta(days=1)
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            return datetime.datetime.strptime(v, fmt).date()
        except ValueError:
            pass
    try:
        return datetime.datetime.strptime(f"{today.year}-{v}", "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(
            L(f"zła data '{s}' (użyj RRRR-MM-DD)", f"invalid date '{s}' (use YYYY-MM-DD)"))


def resolve_window(a):
    """-> dict(start, end, first, last, last_n, rolling); start None = all history"""
    now = datetime.datetime.now().astimezone()
    today = now.date()
    W = {"start": None, "end": now, "first": None, "last": today, "last_n": None, "rolling": None}
    picked = [n for n, v in (("--days", a.days is not None), ("--date", a.date),
                             ("--from", a.from_), ("--today", a.today),
                             ("--yesterday", a.yesterday), ("--all", a.all)) if v]
    if len(picked) > 1:
        raise ValueError(L("podaj okres tylko jednym sposobem, a podano: ",
                           "set the period one way only, got: ") + " ".join(picked))
    if a.to and not a.from_:
        raise ValueError(L("--to wymaga --from", "--to requires --from"))
    if a.all:
        return W
    if a.date:
        d1 = d2 = a.date
    elif a.from_:
        d1, d2 = a.from_, (a.to or today)
    elif a.today:
        d1 = d2 = today
    elif a.yesterday:
        d1 = d2 = today - datetime.timedelta(days=1)
    else:
        days = 7 if a.days is None else a.days
        if days <= 0:
            raise ValueError(L("--days musi być > 0", "--days must be > 0"))
        if a.rolling or days != int(days):
            W.update(start=now - datetime.timedelta(days=days), rolling=days)
            W["first"] = W["start"].date()
            return W
        d1, d2 = today - datetime.timedelta(days=int(days) - 1), today
        W["last_n"] = int(days)
    if d1 > d2:
        raise ValueError(L(f"początek {d1} jest po końcu {d2}", f"start {d1} is after end {d2}"))
    if d1 > today:
        raise ValueError(L(f"{d1} jest w przyszłości", f"{d1} is in the future"))
    d2 = min(d2, today)
    W.update(start=midnight(d1), end=min(midnight(d2 + datetime.timedelta(days=1)), now),
             first=d1, last=d2)
    return W


def find_session(root, ident):
    """most recent main transcript whose id starts with / contains ident ('latest' = newest)"""
    best = None
    ident = (ident or "latest").lower()
    for path, proj, sess, agent in transcript_files(root):
        if agent:
            continue
        s = sess.lower()
        if ident in ("latest", "last"):
            score = 1
        elif s == ident:
            score = 3
        elif s.startswith(ident):
            score = 2
        elif ident in s:
            score = 1
        else:
            continue
        try:
            mt = os.path.getmtime(path)
        except OSError:
            continue
        if best is None or (score, mt) > best[0]:
            best = ((score, mt), path, proj, sess)
    if not best:
        return None
    _, path, proj, sess = best
    files = [(path, proj, sess, None)]
    for p in sorted(glob.glob(os.path.join(os.path.dirname(path), sess, "subagents", "*.jsonl"))):
        f = os.path.basename(p)[:-6]
        files.append((p, proj, sess, f[len("agent-"):] if f.startswith("agent-") else f))
    return proj, sess, files


def list_sessions(root, n, namer):
    rows = []
    for path, proj, sess, agent in transcript_files(root):
        if agent:
            continue
        try:
            rows.append((os.path.getmtime(path), path, proj, sess))
        except OSError:
            pass
    rows.sort(reverse=True)
    out = [f" {L('sesja', 'session'):<10}{L('ostatnio', 'last used'):<18}{L('projekt', 'project'):<28}"
           f"{L('pierwsza prośba', 'first request')}"]
    for mt, path, proj, sess in rows[:n]:
        _, sessions = load(root, None, None, files=[(path, proj, sess, None)])
        meta = sessions.get((proj, sess), {})
        out.append(f" {sess[:8]:<10}{datetime.datetime.fromtimestamp(mt):%Y-%m-%d %H:%M}  "
                   f"{short(namer.project(meta, proj), 27):<28}{namer.topic(meta.get('topic'))[:50]}")
    return "\n".join(out)


# --------------------------------------------------------------------------- main

def build_parser():
    ap = argparse.ArgumentParser(
        prog="claude_token_report.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=L(
            "Raport dla subskrypcji Claude (Pro/Max): na co dokładnie idą tokeny w Claude Code.\n"
            "Czyta tylko lokalne transkrypty (~/.claude/projects), niczego nie wysyła, nie\n"
            "zużywa tokenów.\n\n"
            "Dwie miary:\n"
            "  tokeny surowe   cały tekst, który przeszedł przez model, każdy token po równo\n"
            "  tokeny ważone   te same tokeny liczone wg obciążenia limitu: odczyt z cache x0.1,\n"
            "                  zapis x1.25, odpowiedź x5, razy waga modelu (Opus 5 x1, Sonnet 5 x0.4)\n"
            "Pełne wyjaśnienie i skąd wagi: --explain",
            "Report for Claude subscriptions (Pro/Max): where exactly your Claude Code tokens go.\n"
            "Reads only the local transcripts (~/.claude/projects), sends nothing, uses no\n"
            "tokens.\n\n"
            "Two measures:\n"
            "  raw tokens       all text that went through the model, every token counted the same\n"
            "  weighted tokens  the same tokens counted by load on your limit: cache read x0.1,\n"
            "                   write x1.25, output x5, times the model weight (Opus 5 x1, Sonnet 5 x0.4)\n"
            "Full explanation and where the weights come from: --explain"),
        epilog=L(
            "przykłady:\n"
            "  %(prog)s -l pl                         ostatnie 7 dni, po polsku\n"
            "  %(prog)s -l pl --explain               co znaczą tokeny surowe i ważone\n"
            "  %(prog)s -l pl --days 14 --daily       14 dni + wzrost/spadek każdego dnia\n"
            "  %(prog)s -l pl --date 2026-09-15       jeden konkretny dzień\n"
            "  %(prog)s -l pl --from 09-01 --to 09-15 --daily   zakres dat, dzień po dniu\n"
            "  %(prog)s -l pl --today --diff          dzisiaj vs wczoraj\n"
            "  %(prog)s -l pl --days 30 --chart week  30 dni, oś czasu tygodniami\n"
            "  %(prog)s -l pl --list                  ostatnie sesje\n"
            "  %(prog)s -l pl --session 1a2b3c        jedna sesja z fazami (id lub prefiks)\n"
            "  %(prog)s -l pl --html raport.html --daily --private   HTML do udostępnienia\n\n"
            "daty: RRRR-MM-DD, DD.MM.RRRR, MM-DD (bieżący rok), today, yesterday",
            "examples:\n"
            "  %(prog)s                               last 7 days\n"
            "  %(prog)s --explain                     what raw and weighted tokens mean\n"
            "  %(prog)s --days 14 --daily             14 days + each day's rise/fall\n"
            "  %(prog)s --date 2026-09-15             one specific day\n"
            "  %(prog)s --from 09-01 --to 09-15 --daily   a date range, day by day\n"
            "  %(prog)s --today --diff                today vs yesterday\n"
            "  %(prog)s --days 30 --chart week        30 days, timeline by week\n"
            "  %(prog)s --list                        recent sessions\n"
            "  %(prog)s --session 1a2b3c              one session with its phases (id or prefix)\n"
            "  %(prog)s --html report.html --daily --private   shareable HTML\n"
            "  %(prog)s -l pl                         Polish output\n\n"
            "dates: YYYY-MM-DD, DD.MM.YYYY, MM-DD (current year), today, yesterday"))
    g = ap.add_argument_group(L("okres (wybierz jeden sposób; domyślnie ostatnie 7 dni)",
                                "time window (pick one; default: last 7 days)"))
    g.add_argument("--days", "-d", type=float, default=None, metavar="N",
                   help=L("ostatnie N dni kalendarzowych, łącznie z dzisiaj",
                          "last N calendar days, including today"))
    g.add_argument("--date", type=parse_day, metavar=L("DZIEŃ", "DAY"),
                   help=L("jeden konkretny dzień", "one specific day"))
    g.add_argument("--from", dest="from_", type=parse_day, metavar=L("DZIEŃ", "DAY"),
                   help=L("początek zakresu (włącznie)", "start of a range (inclusive)"))
    g.add_argument("--to", type=parse_day, metavar=L("DZIEŃ", "DAY"),
                   help=L("koniec zakresu (włącznie; domyślnie dzisiaj)",
                          "end of the range (inclusive; default today)"))
    g.add_argument("--today", "-t", action="store_true", help=L("tylko dzisiaj", "today only"))
    g.add_argument("--yesterday", "-y", action="store_true", help=L("tylko wczoraj", "yesterday only"))
    g.add_argument("--all", action="store_true", help=L("cała historia", "all history"))
    g.add_argument("--rolling", action="store_true",
                   help=L("z --days: okno N×24h zamiast pełnych dni",
                          "with --days: N×24h window instead of calendar days"))
    g = ap.add_argument_group(L("porównania", "comparisons"))
    g.add_argument("--daily", action="store_true",
                   help=L("dzień po dniu: wzrost/spadek każdego dnia względem poprzedniego",
                          "day by day: each day's rise/fall vs the previous day"))
    g.add_argument("--diff", action="store_true",
                   help=L("porównaj z poprzednim okresem tej samej długości",
                          "compare with the previous window of the same length"))
    g = ap.add_argument_group(L("zakres i widok", "scope and view"))
    g.add_argument("--session", "-s", metavar="ID", nargs="?", const="latest",
                   help=L("jedna sesja (id/prefiks; bez wartości = najnowsza)",
                          "one session (id/prefix; no value = latest)"))
    g.add_argument("--list", metavar="N", nargs="?", type=int, const=15,
                   help=L("pokaż ostatnie sesje", "list recent sessions"))
    g.add_argument("--chart", nargs="?", const="day", choices=["day", "week"],
                   help=L("oś czasu wg dni/tygodni z trendem czynności",
                          "timeline by day/week with activity trend"))
    g.add_argument("--top", type=int, default=10, help=L("wierszy w tabelach (10)", "rows per table (10)"))
    g = ap.add_argument_group(L("wyjście", "output"))
    g.add_argument("--html", metavar=L("PLIK", "FILE"), help=L("zapisz raport HTML", "write an HTML report"))
    g.add_argument("--private", action="store_true",
                   help=L("ukryj nazwy projektów, plików i treść próśb (do udostępniania)",
                          "hide project/file names and prompt text (for sharing)"))
    g.add_argument("--explain", action="store_true",
                   help=L("wyjaśnij tokeny surowe i ważone", "explain raw and weighted tokens"))
    g.add_argument("--lang", "-l", choices=["en", "pl"], default="en",
                   help=L("język: en (domyślnie) lub pl", "language: en (default) or pl"))
    g.add_argument("--dir", metavar=L("KATALOG", "DIR"),
                   help=L("katalog transkryptów (domyślnie ~/.claude/projects)",
                          "transcripts dir (default ~/.claude/projects)"))
    g.add_argument("--prices", metavar="JSON",
                   help=L('własne wagi modeli jako ceny API: {"nazwa-modelu": [wejście, wyjście, odczyt_cache]}',
                          'custom model weights as API prices: {"model-substring": [input, output, cache_read]}'))
    return ap


def main():
    global LANG
    LANG = detect_lang(sys.argv[1:])
    if LANG not in ("pl", "en"):
        LANG = "en"  # argparse reports the invalid value below
    ap = build_parser()
    a = ap.parse_args()

    if a.explain:
        print(explain_text())
        return
    root = a.dir or default_root()
    root_disp = root.replace(os.path.expanduser("~"), "~", 1)
    if not os.path.isdir(root):
        sys.exit(L(f"brak katalogu {root} — czy Claude Code był tu używany? (--dir)",
                   f"no directory {root} — has Claude Code been used here? (--dir)"))
    if a.prices:
        load_prices(a.prices)
    namer = Namer(a.private)

    if a.list:
        print(list_sessions(root, a.list, namer))
        return

    files, session_key, sess_label = None, None, None
    if a.session:
        found = find_session(root, a.session)
        if not found:
            sys.exit(L(f"nie znaleziono sesji '{a.session}'. Lista: --list",
                       f"no session matching '{a.session}'. See --list"))
        proj, sess, files = found
        session_key, sess_label = (proj, sess), sess[:8]

    try:
        W = resolve_window(a)
    except ValueError as e:
        ap.error(str(e))
    explicit = any((a.days is not None, a.date, a.from_, a.today, a.yesterday, a.all))
    if a.session and not explicit:
        W.update(start=None, first=None)
    start, end = W["start"], W["end"]

    prev_start = None
    if a.diff and start is not None:
        if W["rolling"]:
            prev_start = start - (end - start)
        else:
            n = (W["last"] - W["first"]).days + 1
            prev_start = midnight(W["first"] - datetime.timedelta(days=n))
    load_from = start
    if a.daily and start is not None and not W["rolling"]:
        load_from = midnight(W["first"] - datetime.timedelta(days=1))  # baseline day
    if prev_start is not None:
        load_from = min(load_from, prev_start)

    calls, sessions = load(root, load_from, end, files=files)
    cur = [c for c in calls if start is None or c["t"] >= start]
    if not cur:
        sys.exit(L("brak danych w tym okresie", "no data in this time window"))

    label = period_label(start, end, W["last_n"], W["rolling"], sess_label)
    if a.session:
        meta = sessions.get(session_key, {})
        label += "  (" + namer.project(meta, session_key[0]) + ")"
    ctx = {"label": label, "root_disp": root_disp, "top": a.top, "chart": a.chart,
           "sessions": sessions, "namer": namer, "session": a.session,
           "session_key": session_key, "calls": cur}
    R = aggregate(cur, sessions, namer)
    Rp = None
    if prev_start is not None:
        prev = [c for c in calls if prev_start <= c["t"] < start]
        Rp = aggregate(prev, sessions, namer)
        ctx["prev_label"] = period_label(prev_start, start)

    daily = None
    if a.daily:
        first = W["first"] or cur[0]["t"].astimezone().date()
        last = W["last"] if start is not None else cur[-1]["t"].astimezone().date()
        has_base = start is not None and not W["rolling"]
        first_in_series = first - datetime.timedelta(days=1) if has_base else first
        daily = daily_rows(daily_series(calls, first_in_series, last), has_base)

    if a.html:
        with open(a.html, "w", encoding="utf-8") as f:
            f.write(html_report(R, ctx, Rp, daily))
        print(L(f"zapisano {a.html}  ({R['n']} wywołań, {fmt_tok(R['w'])} tokenów ważonych)",
                f"saved {a.html}  ({R['n']} calls, {fmt_tok(R['w'])} weighted tokens)"))
        uri = "file://" + urllib.parse.quote(os.path.abspath(a.html))
        # OSC 8 hyperlink when on a terminal; the bare file:// URL is auto-linked by most terminals too
        link = f"\033]8;;{uri}\033\\{uri}\033]8;;\033\\" if sys.stdout.isatty() else uri
        print(L("otwórz: ", "open: ") + link)
        return
    if Rp is not None:
        print(text_diff(R, Rp, ctx))
        print()
    if daily:
        print(text_daily(daily))
        print()
    print(text_report(R, ctx))


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        pass
