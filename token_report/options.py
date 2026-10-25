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


# read from the renderers (report_text, report_html): an element has tables when its number of
# rows follows ctx.rows / long tables; breakdown, cache and bash tables have a fixed length
ELEMENT_INFO: Dict[str, ElementInfo] = {
    "activities": ElementInfo(has_tables=True, comparable=True),
    "models": ElementInfo(has_tables=True, comparable=True),
    "sessions": ElementInfo(has_tables=True, comparable=False),
    "tips": ElementInfo(has_tables=False, comparable=False),
    "time": ElementInfo(has_tables=False, comparable=False),
    "breakdown": ElementInfo(has_tables=False, comparable=False),
    "cache": ElementInfo(has_tables=False, comparable=False),
    "bash": ElementInfo(has_tables=False, comparable=False),
    "skills": ElementInfo(has_tables=True, comparable=False),
    "map": ElementInfo(has_tables=False, comparable=False),
}


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
                           ("--private", args.private), ("--no-config", args.no_config)) if v]
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
    return ReportPlan(elements=tuple(e for e in ELEMENTS if e in origin),
                      long_tables=long_tables, diff=args.diff, daily=args.daily,
                      session=args.session is not None, origin=origin, base=base)
