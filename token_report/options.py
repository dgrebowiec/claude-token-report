"""What a report shows, decided in one place.

``resolve`` turns the command line (and the settings saved by --configure) into a ``ReportPlan``:
which elements the report has, how long its tables are and which modifiers apply. Contradictory
flags raise ``OptionsError`` with a user-facing message instead of being silently ignored.

Precedence, strongest first:
1. contradictory flags in one command -> error;
2. a preset (--short / --full) or --only replaces the saved set of elements;
3. section flags (--bash, --cache ...) add sections to the base set (saved, preset or default);
   --long makes the tables long without changing the elements;
4. --no-config -> the base set is the default one;
5. a modifier (--diff, --daily) works on what the report has; it never turns hidden elements on.
"""
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .context import SECTIONS
from .i18n import L
from .periods import picked_options
from .settings import CORE, ELEMENTS, Settings

DEFAULT = CORE  # the default report: activities, models, sessions, tips
SHORT = ("activities", "models", "sessions")  # --short
# the attribute argparse stores each section flag in -> the flag as the user types it
SECTION_FLAGS = {"time": "--time", "breakdown": "--breakdown", "cache": "--cache",
                 "bash": "--bash", "skills": "--skills", "map": "--project-map"}
# separate commands: they print something else than a report
COMMANDS = (("explain", "--explain"), ("configure", "--configure"),
            ("reset_config", "--reset-config"), ("list", "--list"))


@dataclass(frozen=True)
class ElementInfo:
    has_tables: bool  # its table length depends on the long / compact setting
    comparable: bool  # --diff has a comparison for it


# has_tables read from the renderers (report_text, report_html): an element has tables when its
# number of rows follows ctx.rows / long tables; breakdown, cache and bash tables have a fixed length.
# comparable: --diff (report_text.text_diff, report_html._comparison) has a part for it — time: the
# token types, breakdown: the projects, cache: long conversations and expired cache, bash: the share
# of noisy Bash output. sessions, tips, skills and map have none (see report-options.md for why).
ELEMENT_INFO: Dict[str, ElementInfo] = {
    "activities": ElementInfo(has_tables=True, comparable=True),
    "models": ElementInfo(has_tables=True, comparable=True),
    "sessions": ElementInfo(has_tables=True, comparable=False),
    "tips": ElementInfo(has_tables=False, comparable=False),
    "time": ElementInfo(has_tables=False, comparable=True),
    "breakdown": ElementInfo(has_tables=False, comparable=True),
    "cache": ElementInfo(has_tables=False, comparable=True),
    "bash": ElementInfo(has_tables=False, comparable=True),
    "skills": ElementInfo(has_tables=True, comparable=False),
    "map": ElementInfo(has_tables=False, comparable=False),
}


def uncompared(elements: Tuple[str, ...]) -> Tuple[str, ...]:
    """the elements (of a report) that --diff has no comparison for"""
    return tuple(e for e in elements if not ELEMENT_INFO[e].comparable)


def no_comparison_note(elements: Tuple[str, ...]) -> str:
    """the line under the --diff comparison; '' when every element is compared"""
    missing = uncompared(elements)
    return L("Bez porównania: ", "Not compared: ") + ", ".join(missing) if missing else ""


def warnings_for(settings: Settings) -> List[str]:
    """the saved settings that would have no effect, with the reason (the configurator's summary
    screen); the same ELEMENT_INFO as the report footer and --dry-run"""
    chosen = tuple(settings.shown())
    out = []
    fixed = [e for e in chosen if not ELEMENT_INFO[e].has_tables]
    if settings.level == "long" and fixed:
        if len(fixed) == len(chosen):
            out.append(L("long nic nie zmienia: żaden włączony element nie ma tabel o zmiennej "
                         "długości (" + ", ".join(fixed) + ")",
                         "long changes nothing: no element that is on has tables of variable "
                         "length (" + ", ".join(fixed) + ")"))
        else:
            out.append(L("long nie zmienia: " + ", ".join(fixed) + " (stała długość, bez tabel)",
                         "long does not change: " + ", ".join(fixed)
                         + " (fixed length, no tables)"))
    missing = uncompared(chosen)
    if missing and len(missing) == len(chosen):
        out.append(L("wszystkie włączone elementy bez porównania — --diff pokaże tylko liczby ogólne",
                     "no element that is on has a comparison — --diff will show only the overall "
                     "numbers"))
    elif missing:
        out.append(L("--diff nie porówna: ", "--diff will not compare: ") + ", ".join(missing))
    return out


class OptionsError(ValueError):
    """A combination of options that cannot work; the message is meant for the user."""


@dataclass(frozen=True)
class ReportPlan:
    elements: Tuple[str, ...]  # what the report shows besides the summary, in ELEMENTS order
    long_tables: bool = False  # 10 rows instead of 5 in the ranking tables
    diff: bool = False  # --diff: compare with the previous window
    daily: bool = False  # --daily: day by day
    session: bool = False  # --session: a single session
    origin: Dict[str, str] = field(default_factory=dict)  # element -> default|config|preset|flag
    base: str = "default"  # where the base set comes from: default|config|short|full|only|md
    only: Tuple[str, ...] = ()  # the elements named in --only (base "only")
    notes: Tuple[str, ...] = ()  # soft remarks for the report footer

    def has(self, element: str) -> bool:
        return element in self.elements


def parse_only(value: str) -> Tuple[str, ...]:
    """argparse type of --only: element names separated by commas"""
    names = [v.strip() for v in value.split(",") if v.strip()]
    unknown = [n for n in names if n not in ELEMENTS]
    if unknown or not names:
        raise argparse.ArgumentTypeError(
            L("nieznany element: ", "unknown element: ") + (", ".join(unknown) or "''")
            + L(" (dozwolone: ", " (allowed: ") + ", ".join(ELEMENTS) + ")")
    return tuple(e for e in ELEMENTS if e in names)


def report_options(args: argparse.Namespace) -> List[str]:
    """the report options given on the command line, as the user typed them"""
    got = list(picked_options(args))
    got += [n for n, v in (("--to", args.to), ("--rolling", args.rolling)) if v]
    got += [flag for key, flag in SECTION_FLAGS.items() if getattr(args, key)]
    got += [n for n, v in (("--short", args.short), ("--full", args.full), ("--long", args.long),
                           ("--only", args.only is not None), ("--diff", args.diff),
                           ("--daily", args.daily), ("--session", args.session is not None),
                           ("--html", args.html is not None), ("--md", args.md is not None),
                           ("--private", args.private), ("--no-config", args.no_config),
                           ("--dry-run", args.dry_run)) if v]
    return got


def _check_commands(args: argparse.Namespace) -> None:
    commands = [flag for key, flag in COMMANDS
                if (getattr(args, key) is not None if key == "list" else getattr(args, key))]
    if len(commands) > 1:
        raise OptionsError(L("podaj jedno polecenie naraz, a podano: ",
                             "give one command at a time, got: ") + " ".join(commands))
    extra = report_options(args)
    if commands and extra:
        raise OptionsError(L(f"{commands[0]} to osobne polecenie, nie przyjmuje opcji raportu: ",
                             f"{commands[0]} is a separate command, it takes no report options: ")
                           + " ".join(extra))


def _check_conflicts(args: argparse.Namespace) -> None:
    if args.short and args.full:
        raise OptionsError(L("--short i --full się wykluczają (krótki albo pełny raport) — "
                             "podaj jedno z nich",
                             "--short and --full exclude each other (a short or a full report) — "
                             "give one of them"))
    if args.only is not None and (args.short or args.full):
        preset = "--short" if args.short else "--full"
        raise OptionsError(L(f"--only i {preset} się wykluczają: oba wybierają zestaw sekcji — "
                             "podaj jedno z nich",
                             f"--only and {preset} exclude each other: both pick the set of "
                             "sections — give one of them"))
    if args.session is not None and args.diff:
        raise OptionsError(L("--diff nie działa z --session: pojedyncza sesja nie ma poprzedniego "
                             "okresu do porównania",
                             "--diff does not work with --session: a single session has no "
                             "previous window to compare with"))
    if args.all and args.diff:
        raise OptionsError(L("--diff nie działa z --all: cała historia nie ma poprzedniego okresu "
                             "do porównania",
                             "--diff does not work with --all: all history has no previous "
                             "window to compare with"))


def resolve(args: argparse.Namespace, saved: Optional[Settings]) -> ReportPlan:
    """the plan of the report asked for by ``args`` (from cli.build_parser) and the saved
    settings (None: nothing saved or --no-config); raises OptionsError"""
    _check_commands(args)
    _check_conflicts(args)
    if args.no_config:
        saved = None
    flags = [k for k in SECTIONS if getattr(args, k)]
    long_tables = False
    if args.short:
        base, chosen, how = "short", SHORT, "preset"
    elif args.full:
        base, chosen, how, long_tables = "full", ELEMENTS, "preset", True
    elif args.only is not None:
        base, chosen, how = "only", tuple(args.only), "flag"
    elif saved is not None:
        base, chosen, how = "config", tuple(saved.shown()), "config"
        long_tables = saved.level == "long"
    elif args.md is not None and not flags:
        base, chosen, how, long_tables = "md", ELEMENTS, "preset", True  # an analysis wants all
    else:
        base, chosen, how = "default", DEFAULT, "default"
    long_tables = long_tables or args.long  # --long: long tables, the same elements
    origin = {e: how for e in chosen}
    for k in flags:
        origin.setdefault(k, "flag")
    elements = tuple(e for e in ELEMENTS if e in origin)
    note = no_comparison_note(elements) if args.diff else ""
    return ReportPlan(elements=elements, long_tables=long_tables, diff=args.diff,
                      daily=args.daily, session=args.session is not None, origin=origin,
                      base=base, only=tuple(args.only or ()), notes=(note,) if note else ())


def _config_display(path: Optional[str]) -> str:
    if path is None:
        from .settings import settings_path  # read when the footer is made (tests set the env)
        path = str(settings_path())
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if home and path.startswith(home + os.sep) else path


def describe_plan(plan: ReportPlan, prev_label: str = "",
                  config_path: Optional[str] = None) -> List[str]:
    """the footer "Settings of this report": where the set of elements comes from, the table
    length, the modifiers; the sections left out; how to change it. 2-3 short lines."""
    bases = {
        "default": L("zestaw domyślny", "the default set"),
        "config": L("sekcje z konfiguracji (", "sections from the configuration (")
                  + _config_display(config_path) + ")",
        "short": "--short",
        "full": "--full",
        "only": "--only " + ",".join(plan.only),
        "md": L("wszystkie elementy (domyślnie dla --md)", "every element (the --md default)"),
    }
    base = bases.get(plan.base, plan.base)
    added = [SECTION_FLAGS[e] for e in plan.elements
             if e in SECTION_FLAGS and plan.origin.get(e) == "flag" and e not in plan.only]
    if added:
        base += " + " + " ".join(added)
    parts = [base, L("tabele długie (10 wierszy)", "long tables (10 rows)") if plan.long_tables
             else L("tabele krótkie (5 wierszy)", "compact tables (5 rows)")]
    if plan.diff:
        diff = (L("porównanie z ", "compared with ") + prev_label if prev_label
                else L("porównanie z poprzednim okresem", "compared with the previous window"))
        missing = uncompared(plan.elements)
        if missing:  # the line under the comparison names them too; here only in brief
            diff += L(", bez porównania: ", ", not compared: ") + ", ".join(missing)
        parts.append(diff)
    if plan.daily:
        parts.append(L("dzień po dniu", "day by day"))
    lines = [L("Ustawienia: ", "Settings: ") + " · ".join(parts)]
    left_out = [flag for key, flag in SECTION_FLAGS.items() if not plan.has(key)]
    if left_out:
        lines.append(L("Więcej szczegółów: ", "More detail: ") + " ".join(left_out)
                     + L("  albo --full (wszystko)", "  or --full (everything)"))
    change = (L("bez konfiguracji: --no-config · zmiana: --configure",
                "without the configuration: --no-config · change it: --configure")
              if plan.base == "config"
              else L("własny zestaw na stałe: --configure", "your own saved set: --configure"))
    lines.append(change[0].upper() + change[1:] + " · "
                 + L("tokeny surowe i ważone: --explain", "raw and weighted tokens: --explain"))
    shown = no_comparison_note(plan.elements)  # already under the comparison block
    lines += [n for n in plan.notes if n != shown]
    return lines


def _origin_label(plan: ReportPlan, element: str) -> str:
    """where an element of the plan comes from, as the user would set it"""
    how = plan.origin.get(element, "")
    if element in plan.only:
        return "--only"
    if how == "flag":
        return SECTION_FLAGS.get(element, "--only")
    if how == "preset":
        return {"short": "--short", "full": "--full",
                "md": L("--md (domyślnie wszystko)", "--md (everything by default)")}[plan.base]
    if how == "config":
        return L("konfiguracja", "the configuration")
    return L("zestaw domyślny", "the default set")


def describe_dry_run(plan: ReportPlan, period: str, prev_label: str = "",
                     session: Optional[str] = None, html: Optional[str] = None,
                     md: Optional[str] = None, private: bool = False, root: str = "",
                     config_path: Optional[str] = None) -> List[str]:
    """--dry-run: what the report would show, without reading the transcripts. The closing
    lines are the report footer itself (describe_plan), so the two cannot disagree."""
    def row(name: str, value: str) -> str:
        return f" {name:<14}{value}"

    pad = " " * 15
    lines = [L("--dry-run: co pokaże raport — nic nie policzono, transkrypty nie zostały przeczytane",
               "--dry-run: what the report would show — nothing counted, no transcripts read")]
    lines.append(row(L("Okres:", "Period:"), period))
    if session is None:
        scope = L("cała historia z okresu", "all history in the period")
    else:
        which = (L("najnowsza", "the latest") if session == "latest" else session)
        scope = (L("jedna sesja: ", "one session: ") + which
                 + L(" (szukana dopiero przy raporcie)", " (looked up when the report runs)"))
    lines.append(row(L("Zakres:", "Scope:"), scope))
    width = max(len(e) for e in ELEMENTS)
    entries = [(L("podsumowanie", "summary"), L("zawsze", "always"))]
    entries += [(e, _origin_label(plan, e)) for e in plan.elements]
    width = max(width, len(entries[0][0]))
    for i, (name, origin) in enumerate(entries):
        lines.append((row(L("Elementy:", "Elements:"), "") if i == 0 else pad)
                     + f"{name:<{width}}  {origin}")
    tables = (L("długie (10 wierszy)", "long (10 rows)") if plan.long_tables
              else L("krótkie (5 wierszy)", "compact (5 rows)"))
    fixed = [e for e in plan.elements if not ELEMENT_INFO[e].has_tables]
    if plan.long_tables and fixed:
        tables += L("; bez zmian (bez tabel): ", "; no change (no tables): ") + ", ".join(fixed)
    lines.append(row(L("Tabele:", "Tables:"), tables))
    mods = []
    if plan.diff:
        diff = "--diff: " + (L("porównanie z ", "compared with ") + prev_label if prev_label
                             else L("porównanie z poprzednim okresem",
                                    "compared with the previous window"))
        missing = uncompared(plan.elements)
        if missing:
            diff += L("; bez porównania: ", "; not compared: ") + ", ".join(missing)
        mods.append(diff)
    if plan.daily:
        mods.append("--daily: " + L("dzień po dniu", "day by day"))
    for i, m in enumerate(mods or [L("brak", "none")]):
        lines.append((row(L("Modyfikatory:", "Modifiers:"), "") if i == 0 else pad) + m)
    outputs = [kind + path for kind, path in (("HTML: ", html), ("Markdown: ", md))
               if path is not None]
    output = (", ".join(outputs) + L(" (nie zapisano)", " (not written)") if outputs
              else L("terminal", "the terminal"))
    if private:
        output += L(" · ukryte nazwy projektów i plików (--private)",
                    " · project and file names hidden (--private)")
    lines.append(row(L("Wyjście:", "Output:"), output))
    if root:
        lines.append(row(L("Transkrypty:", "Transcripts:"),
                         root + L(" (nie sprawdzano)", " (not checked)")))
    lines.append(L(" Stopka raportu:", " Report footer:"))
    lines += ["   " + line for line in describe_plan(plan, prev_label, config_path)]
    return lines
