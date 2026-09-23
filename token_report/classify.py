"""Which activity a model call belongs to: the tool it used, and for Bash the kind of command."""
from __future__ import annotations

import os
import re
import shlex
from typing import TYPE_CHECKING, Any, List, Mapping, Tuple

from .i18n import L

if TYPE_CHECKING:
    from .transcripts import Call

NO_TOOL = "no_tool"
EXPLORE_KEYS = {"read", "search", "bash_search", "bash_read"}

_PREFIX = {"while", "until", "if", "elif", "then", "do", "else", "!", "time", "nohup",
           "exec", "sudo", "env", "{", "}", "for", "in", "done", "fi", "timeout", "xargs"}
_TRIVIAL = {"cd", "echo", "printf", "export", "source", ".", "set", "true", "false", ":",
            "pwd", "unset", "alias", "which", "command", "type", "test", "[", "[[", "date",
            "yes", "clear", "read", "let", "local", "declare", "shift", "exit", "return"}
_REDIR = re.compile(r"\d*>>?&?\s*[^\s;&|()]+|<\s*[^\s;&|()]+")
_ASSIGNMENT = re.compile(r"[A-Za-z_]\w*=")
_SCRIPT_FILE = re.compile(r"\.(sh|py|js|mjs|ts|rb|pl|bash)$")
_JS_PACKAGE_MANAGERS = ("npm", "pnpm", "yarn", "bun")
_JS_INSTALL_VERBS = ("i", "install", "add", "ci", "remove", "uninstall", "update", "upgrade")

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
BASH_LOOKUP = {cmd: group for group, cmds in BASH_GROUPS for cmd in cmds}

# Claude Code tool name -> activity key (Bash and MCP tools are handled separately)
_TOOL_ACTIVITY = {
    "Read": "read",
    **dict.fromkeys(("Edit", "Write", "MultiEdit", "NotebookEdit"), "edit"),
    **dict.fromkeys(("Grep", "Glob", "LS"), "search"),
    **dict.fromkeys(("Agent", "Task", "SendMessage"), "agent"),
    **dict.fromkeys(("WebSearch", "WebFetch"), "web"),
    **dict.fromkeys(("TodoWrite", "TodoRead", "TaskCreate", "TaskUpdate", "TaskList",
                     "TaskGet"), "todo"),
    "Skill": "skill",
    "ToolSearch": "toolsearch",
    "AskUserQuestion": "ask",
    **dict.fromkeys(("BashOutput", "TaskOutput", "Monitor", "KillShell", "KillBash",
                     "TaskStop"), "bg"),
    **dict.fromkeys(("EnterPlanMode", "ExitPlanMode"), "plan"),
}


def activity_name(key: str) -> str:
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


def _shell_tokens(command: str) -> List[str]:
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


def _simple_commands(command: str) -> List[List[str]]:
    """split a shell command on ; && || | and newlines, drop keywords and VAR=... prefixes"""
    commands, current = [], []
    for token in _shell_tokens(command):
        if token and not token.strip(";&|()"):
            if current:
                commands.append(current)
            current = []
        else:
            current.append(token)
    if current:
        commands.append(current)

    out = []
    for words in commands:
        words = [w for w in words if w.strip()]
        if not words or words[0] in ("for", "select", "case"):
            continue  # loop header: "for f in a b" — the body comes after "do"
        i = 0
        while i < len(words) and (words[i] in _PREFIX or _ASSIGNMENT.match(words[i])
                                  or (i > 0 and (words[i].startswith("-") or words[i].isdigit()))):
            i += 1
        if i < len(words):
            out.append(words[i:])
    return out


def classify_bash(command: Any) -> str:
    """activity key of the first non-trivial command in a shell line"""
    for words in _simple_commands(str(command or "")):
        name = os.path.basename(words[0])
        if name in _TRIVIAL:
            continue
        if name in _JS_PACKAGE_MANAGERS and len(words) > 1 and words[1] in _JS_INSTALL_VERBS:
            return "bash_pkg"
        group = BASH_LOOKUP.get(name)
        if group:
            return group
        if name.startswith("python") or "/" in words[0] or _SCRIPT_FILE.search(name):
            return "bash_script"  # interpreters and project scripts called by path
        return "bash_other"
    return "bash_other"


def classify_tool(name: str, tool_input: Mapping) -> str:
    if name == "Bash":
        return classify_bash((tool_input or {}).get("command", ""))
    if isinstance(name, str) and name in _TOOL_ACTIVITY:
        return _TOOL_ACTIVITY[name]
    if name and name.startswith("mcp__"):
        parts = name.split("__")
        return "mcp:" + (parts[1] if len(parts) > 1 else name)
    return name or "?"


def call_activities(call: Call) -> List[Tuple[str, float]]:
    """(activity, share of the call) — a call's weight is split evenly between its tools"""
    tools = list(call.tools.values())
    if not tools:
        return [(NO_TOOL, 1.0)]
    return [(classify_tool(name, tool_input), 1.0 / len(tools)) for name, tool_input in tools]
