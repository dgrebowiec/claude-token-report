"""Avoidable noise: shell commands that dump long output into the conversation, and skills
that are listed in every conversation but never used (or named in a request and not invoked).

Sizes are estimated from the text of tool results (4 characters ≈ 1 token); a result then
stays in the conversation and is re-read on every following call, which the weight accounts for.
"""
from __future__ import annotations

import collections
import os
import re
from dataclasses import dataclass, field
from typing import (TYPE_CHECKING, DefaultDict, Dict, Iterable, List, Mapping, NamedTuple,
                    Set, Tuple)

from .classify import command_family, file_commands, limits_output
from .i18n import L
from .pricing import W_CACHE_READ, W_WRITE_5M, model_weight

if TYPE_CHECKING:
    from .transcripts import Call, SessionKey, SessionMeta

CHARS_PER_TOKEN = 4
NOISY_TOKENS = 2000  # a result this long (≈ 8000 characters) counts as noise ...
TOP_FAMILIES = 8
TOP_SKILLS = 10
MIN_NOISY_RUNS = 2  # ... and a command kind is reported after this many such results

# command family -> (pl, en) what to do instead
_ADVICE = {
    "git diff": ("najpierw `git diff --stat`, potem `git diff -- plik` tylko dla jednego pliku",
                 "start with `git diff --stat`, then `git diff -- file` for a single file"),
    "git log": ("`git log --oneline -n 20` zamiast pełnej historii",
                "`git log --oneline -n 20` instead of the full history"),
    "git show": ("`git show --stat <commit>` albo `git show <commit> -- plik`",
                 "`git show --stat <commit>` or `git show <commit> -- file`"),
    "cat": ("narzędzie Read z offset/limit albo `grep -n`/`head` zamiast całego pliku",
            "the Read tool with offset/limit, or `grep -n` / `head`, instead of the whole file"),
    "ls": ("zawęź ścieżkę albo użyj Glob; `| head` dla długich katalogów",
           "narrow the path or use Glob; `| head` for long directories"),
    "find": ("zawęź ścieżkę i `-maxdepth`, albo użyj Glob; `| head`",
             "narrow the path and `-maxdepth`, or use Glob; `| head`"),
    "tree": ("`tree -L 2` albo Glob zamiast pełnego drzewa",
             "`tree -L 2` or Glob instead of the full tree"),
    "grep": ("`-l` (tylko nazwy plików), `-m N` albo `| head`; przeszukuj konkretny katalog",
             "`-l` (file names only), `-m N` or `| head`; search a specific directory"),
    "rg": ("`-l`, `-m N` albo `| head`; przeszukuj konkretny katalog",
           "`-l`, `-m N` or `| head`; search a specific directory"),
    "curl": ("`-s` i `| jq '.pole'`, albo `-o plik` i czytaj fragmenty",
             "`-s` and `| jq '.field'`, or `-o file` and read parts"),
    "pip install": ("`-q`", "`-q`"),
    "npm install": ("`--silent --no-progress`", "`--silent --no-progress`"),
    "pytest": ("`-q -x` — tylko błędy, stop na pierwszym; przy niejasnej przyczynie uruchom "
               "ponownie bez filtra", "`-q -x` — failures only, stop at the first; if the cause "
               "is unclear, rerun without the filter"),
    "python -m pytest": ("`-q -x` — tylko błędy, stop na pierwszym",
                         "`-q -x` — failures only, stop at the first"),
    "npm test": ("`--silent` i `--bail`", "`--silent` and `--bail`"),
    "docker build": ("`--quiet` albo `--progress=plain 2>&1 | tail -n 30`",
                     "`--quiet` or `--progress=plain 2>&1 | tail -n 30`"),
    "docker logs": ("`--tail 100` i `| grep -E 'ERROR|WARN'`",
                    "`--tail 100` and `| grep -E 'ERROR|WARN'`"),
    "cargo build": ("`-q`", "`-q`"),
    "cargo test": ("`-q`", "`-q`"),
}
_DEFAULT_ADVICE = (
    "ogranicz wyjście: tryb cichy (`-q`/`--silent`), `| head`/`| tail` albo zapis do pliku "
    "i czytanie fragmentów (błędy zostaw w całości)",
    "cut the output: quiet mode (`-q`/`--silent`), `| head` / `| tail`, or write it to a file "
    "and read parts (keep errors whole)")
_GROUP_ADVICE = {  # fallback by first word, e.g. every "npm install ..."
    "npm": _ADVICE["npm install"], "pnpm": _ADVICE["npm install"], "yarn": _ADVICE["npm install"],
    "pip3": _ADVICE["pip install"], "uv": _ADVICE["pip install"],
}


def advice(family: str) -> str:
    pl_en = _ADVICE.get(family) or _GROUP_ADVICE.get(family.split()[0]) or _DEFAULT_ADVICE
    return L(*pl_en)


# --------------------------------------------------------------------------- results

@dataclass
class Family:
    """one kind of shell command (git diff, npm test ...)"""
    name: str
    runs: int = 0  # with a known result
    noisy: int = 0  # results of NOISY_TOKENS or more
    unlimited: int = 0  # noisy and the command did nothing to cut its output
    tokens: int = 0  # estimated tokens of the unlimited noisy results
    weighted: float = 0.0  # what they cost, counting the re-reads on later calls
    biggest: int = 0  # largest unlimited result, tokens
    example: str = ""  # the largest unlimited command (not shown with --private)


class SkillRow(NamedTuple):
    name: str
    tokens: int  # its listing line, loaded into every conversation
    uses: int
    named_in: int  # conversations whose request / commands / files named it, without invoking it


@dataclass
class Skills:
    conversations: int = 0  # conversations with a skill listing in the period
    available: Dict[str, int] = field(default_factory=dict)  # skill -> listing tokens
    used: DefaultDict[str, int] = field(default_factory=lambda: collections.defaultdict(int))
    named: DefaultDict[str, int] = field(default_factory=lambda: collections.defaultdict(int))

    def unused(self) -> List[SkillRow]:
        rows = [SkillRow(n, t, 0, self.named.get(n, 0)) for n, t in self.available.items()
                if not self.used.get(n)]
        return sorted(rows, key=lambda r: (-r.named_in, -r.tokens, r.name))

    def used_rows(self) -> List[SkillRow]:
        rows = [SkillRow(n, self.available.get(n, 0), u, self.named.get(n, 0))
                for n, u in self.used.items()]
        return sorted(rows, key=lambda r: (-r.uses, r.name))

    def listing_tokens(self) -> int:
        return sum(self.available.values())

    def unused_tokens(self) -> int:
        return sum(t for n, t in self.available.items() if not self.used.get(n))


@dataclass
class Waste:
    bash_results: int = 0  # Bash calls whose result size is known
    bash_tokens: int = 0  # estimated tokens of all of them
    noisy_tokens: int = 0  # of the unlimited noisy ones
    noisy_weighted: float = 0.0
    families: List[Family] = field(default_factory=list)
    skills: Skills = field(default_factory=Skills)

    @property
    def has_data(self) -> bool:
        return bool(self.bash_results or self.skills.conversations or self.skills.used)


# --------------------------------------------------------------------------- bash noise

def _bash_noise(calls: Iterable["Call"], out: Waste) -> None:
    by_file: DefaultDict[Tuple, List["Call"]] = collections.defaultdict(list)
    for call in calls:
        by_file[call.file_key].append(call)
    families: Dict[str, Family] = {}
    for file_calls in by_file.values():
        file_calls.sort(key=lambda c: c.time)
        for index, call in enumerate(file_calls):
            later = len(file_calls) - index - 1
            for tool_id, (name, tool_input) in call.tools.items():
                if name != "Bash" or tool_id not in call.result_chars:
                    continue
                command = str((tool_input or {}).get("command") or "")
                tokens = call.result_chars[tool_id] // CHARS_PER_TOKEN
                out.bash_results += 1
                out.bash_tokens += tokens
                fam = families.setdefault(command_family(command), Family(""))
                fam.runs += 1
                if tokens < NOISY_TOKENS:
                    continue
                fam.noisy += 1
                if limits_output(command):
                    continue
                weighted = tokens * model_weight(call.model) * (W_WRITE_5M + W_CACHE_READ * later)
                fam.unlimited += 1
                fam.tokens += tokens
                fam.weighted += weighted
                if tokens > fam.biggest:
                    fam.biggest, fam.example = tokens, command
    for name, fam in families.items():
        fam.name = name
    reported = [f for f in families.values() if f.unlimited >= MIN_NOISY_RUNS]
    reported.sort(key=lambda f: -f.weighted)
    out.families = reported[:TOP_FAMILIES]
    out.noisy_tokens = sum(f.tokens for f in families.values())
    out.noisy_weighted = sum(f.weighted for f in families.values())


# --------------------------------------------------------------------------- skills

def _session_mentions(skill_names: Iterable[str], prompts: str, tools: List[Tuple[str, dict]]
                      ) -> Set[str]:
    """skills named in the user's requests, as a command, or by a file extension (pdf, docx);
    a plain word as a name (run, plan) is too common in requests, so only names with - _ :"""
    text = " " + prompts.lower() + " "
    commands: Set[str] = set()
    extensions: Set[str] = set()
    for name, tool_input in tools:
        tool_input = tool_input or {}
        if name == "Bash":
            commands.update(os.path.basename(cmd[0])
                            for cmd in file_commands(tool_input.get("command", "")))
        path = str(tool_input.get("file_path") or "")
        if path:
            extensions.add(os.path.splitext(path)[1].lstrip(".").lower())
    found = set()
    for skill in skill_names:
        short = skill.split(":")[-1].lower()
        full = re.compile(r"(?<![\w:-])" + re.escape(skill.lower()) + r"(?![\w:-])")
        distinctive = any(c in skill for c in "-_:")
        if (distinctive and full.search(text)) or short in commands or short in extensions:
            found.add(skill)
    return found


def _skill_usage(calls: Iterable["Call"], sessions: Mapping["SessionKey", "SessionMeta"],
                 out: Waste) -> None:
    tools_by_session: DefaultDict[Tuple, List[Tuple[str, dict]]] = collections.defaultdict(list)
    for call in calls:
        tools_by_session[call.session_key].extend(call.tools.values())

    skills = out.skills
    for key, meta in sessions.items():
        used = {str((i or {}).get("skill") or "") for n, i in tools_by_session.get(key, [])
                if n == "Skill"}
        used.update(p.text.split()[0].lstrip("/") for p in meta.prompts  # typed /skill-name
                    if p.kind == "prompt" and p.text.startswith("/")
                    and p.text.split()[0].lstrip("/") in meta.skills)
        used.discard("")
        for skill in used:
            skills.used[skill] += 1
        if not meta.skills:
            continue
        skills.conversations += 1
        for skill, chars in meta.skills.items():
            skills.available[skill] = max(skills.available.get(skill, 0), chars // CHARS_PER_TOKEN)
        prompts = " ".join(p.text for p in meta.prompts if p.kind == "prompt")
        for skill in _session_mentions(meta.skills, prompts, tools_by_session.get(key, [])):
            if skill not in used:
                skills.named[skill] += 1


def find_waste(calls: List["Call"], sessions: Mapping["SessionKey", "SessionMeta"]) -> Waste:
    out = Waste()
    _bash_noise(calls, out)
    _skill_usage(calls, sessions, out)
    return out


def bash_note() -> str:
    return L(
        "Rozmiary to szacunek z długości wyników narzędzi (4 znaki ≈ 1 token); wynik zostaje w "
        "rozmowie i jest czytany ponownie przy kolejnych wywołaniach (do /compact), stąd kolumna "
        "„ważone”. „Szum” = wynik ≥ " + str(NOISY_TOKENS) + " tokenów z polecenia bez flagi "
        "ciszy, filtra w potoku ani przekierowania; nie każdy taki wynik jest zbędny — czasem "
        "potrzebujesz całości. W łańcuchu poleceń (a && b) liczone jest ostatnie.",
        "Sizes are estimated from the length of tool results (4 characters ≈ 1 token); a result "
        "stays in the conversation and is re-read on later calls (until /compact), hence the "
        "'weighted' column. 'Noise' = a result of ≥ " + str(NOISY_TOKENS) + " tokens from a "
        "command with no quiet flag, pipe filter or redirect; not every such result is "
        "unnecessary — sometimes you need all of it. In a chain (a && b) the last command counts.")


def skills_note() -> str:
    return L(
        "Raport widzi skille, które Claude Code wpisał do transkryptu rozmowy; opis każdego "
        "trafia do kontekstu każdej rozmowy. „wspomniany” = nazwa skilla pada w prośbie (dla "
        "nazw z „-”, „_” lub „:”), w poleceniu lub jako rozszerzenie pliku, a skill nie został "
        "wywołany — to wskazówka, nie dowód, że pasował. Zwykłe słowa (run, plan) są pomijane.",
        "The report sees the skills Claude Code wrote into the conversation transcript; each "
        "one's description goes into the context of every conversation. 'named' = the skill's "
        "name appears in a request (for names with '-', '_' or ':'), in a command or as a file "
        "extension while the skill was not invoked — a hint, not proof that it fitted. Plain "
        "words (run, plan) are skipped.")
