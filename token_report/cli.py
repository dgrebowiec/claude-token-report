"""Command line interface."""
from __future__ import annotations

import argparse
import datetime
import os
import sys
import urllib.parse
from typing import List, Optional, Sequence

from . import __version__, configure, i18n, settings as settings_module
from .context import ReportContext
from .daily import DayRow, daily_rows, daily_series
from .explain import explain_text
from .formatting import fmt_tok
from .i18n import L
from .naming import Namer
from .options import OptionsError, parse_only, resolve
from .periods import (Window, midnight, parse_day, period_label, picked_options,
                      previous_window_start, resolve_window)
from .report_html import html_report
from .report_md import md_report
from .report_text import session_list, text_daily, text_diff, text_report
from .session_detail import session_detail
from .stats import aggregate
from .transcripts import Call, default_root, find_session, load, recent_sessions


def _prog_name() -> str:
    """how the user started us: claude_token_report.py, claude-token-report or python -m"""
    name = os.path.basename(sys.argv[0])
    return "python3 -m token_report" if name == "__main__.py" else name or "claude-token-report"


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog=_prog_name(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=L(
            "Raport dla subskrypcji Claude (Pro/Max): na co dokładnie idą tokeny w Claude Code.\n"
            "Czyta tylko lokalne transkrypty (~/.claude/projects), niczego nie wysyła, nie\n"
            "zużywa tokenów.\n\n"
            "Dwie miary:\n"
            "  tokeny surowe   cały tekst, który przeszedł przez model, każdy token po równo\n"
            "  tokeny ważone   te same tokeny liczone wg obciążenia limitu: odczyt z cache x0.1,\n"
            "                  zapis x1.25 (x2 przy cache 1 h), odpowiedź x5, razy waga modelu\n"
            "                  (Opus 5 x1, Sonnet 5 x0.4)\n"
            "Pełne wyjaśnienie i skąd wagi: --explain",
            "Report for Claude subscriptions (Pro/Max): where exactly your Claude Code tokens go.\n"
            "Reads only the local transcripts (~/.claude/projects), sends nothing, uses no\n"
            "tokens.\n\n"
            "Two measures:\n"
            "  raw tokens       all text that went through the model, every token counted the same\n"
            "  weighted tokens  the same tokens counted by load on your limit: cache read x0.1,\n"
            "                   write x1.25 (x2 at 1 h cache), output x5, times the model weight\n"
            "                   (Opus 5 x1, Sonnet 5 x0.4)\n"
            "Full explanation and where the weights come from: --explain"),
        epilog=L(
            "przykłady:\n"
            "  %(prog)s -l pl                         ostatnie 7 dni, po polsku\n"
            "  %(prog)s -l pl --explain               co znaczą tokeny surowe i ważone\n"
            "  %(prog)s -l pl --days 14 --daily       14 dni + wzrost/spadek każdego dnia\n"
            "  %(prog)s -l pl --date 2026-09-15       jeden konkretny dzień\n"
            "  %(prog)s -l pl --from 09-01 --to 09-15 --daily   zakres dat, dzień po dniu\n"
            "  %(prog)s -l pl --today --diff          dzisiaj vs wczoraj\n"
            "  %(prog)s -l pl --list                  ostatnie sesje\n"
            "  %(prog)s -l pl --short                 skrócony raport\n"
            "  %(prog)s -l pl --bash --skills         domyślny raport + szum z Bash i skille\n"
            "  %(prog)s -l pl --full                  wszystkie sekcje\n"
            "  %(prog)s -l pl --session 1a2b3c        szczegóły jednej sesji (id lub prefiks)\n"
            "  %(prog)s -l pl --html raport.html --daily --private   HTML do udostępnienia\n\n"
            "daty: RRRR-MM-DD, DD.MM.RRRR, MM-DD (bieżący rok), today, yesterday",
            "examples:\n"
            "  %(prog)s                               last 7 days\n"
            "  %(prog)s --explain                     what raw and weighted tokens mean\n"
            "  %(prog)s --days 14 --daily             14 days + each day's rise/fall\n"
            "  %(prog)s --date 2026-09-15             one specific day\n"
            "  %(prog)s --from 09-01 --to 09-15 --daily   a date range, day by day\n"
            "  %(prog)s --today --diff                today vs yesterday\n"
            "  %(prog)s --list                        recent sessions\n"
            "  %(prog)s --short                       short report\n"
            "  %(prog)s --bash --skills               default report + Bash noise and skills\n"
            "  %(prog)s --full                        every section\n"
            "  %(prog)s --session 1a2b3c              one session in detail (id or prefix)\n"
            "  %(prog)s --html report.html --daily --private   shareable HTML\n"
            "  %(prog)s -l pl                         Polish output\n\n"
            "dates: YYYY-MM-DD, DD.MM.YYYY, MM-DD (current year), today, yesterday"))
    g = ap.add_argument_group(L("okres (wybierz jeden sposób; domyślnie ostatnie 7 dni)",
                                "time window (pick one; default: last 7 days)"))
    g.add_argument("--days", "-d", type=float, default=None, metavar="N",
                   help=L("ostatnie N dni kalendarzowych, łącznie z dzisiaj; ułamek N daje okno N×24 h",
                          "last N calendar days, including today; a fraction N gives an N×24 h window"))
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
                   help=L("okno N×24h zamiast pełnych dni; bez --days domyślnie 7×24h",
                          "N×24h window instead of calendar days; without --days, 7×24h by default"))
    g = ap.add_argument_group(L("porównania", "comparisons"))
    g.add_argument("--daily", action="store_true",
                   help=L("dzień po dniu: wzrost/spadek każdego dnia względem poprzedniego",
                          "day by day: each day's rise/fall vs the previous day"))
    g.add_argument("--diff", action="store_true",
                   help=L("porównaj z poprzednim okresem tej samej długości",
                          "compare with the previous window of the same length"))
    g = ap.add_argument_group(L("zakres i widok", "scope and view"))
    g.add_argument("--session", "-s", metavar="ID", nargs="?", const="latest",
                   help=L("jedna sesja w szczegółach: modele, effort, ultracode, subagenci, "
                          "pliki (id/prefiks; bez wartości = najnowsza)",
                          "one session in detail: models, effort, ultracode, subagents, files "
                          "(id/prefix; no value = latest)"))
    g.add_argument("--short", action="store_true",
                   help=L("skrócony raport: główne liczby, czynności, modele i najcięższe rozmowy",
                          "short report: main numbers, activities, models and heaviest "
                          "conversations"))
    g.add_argument("--long", action="store_true",
                   help=L("długie tabele (10 wierszy zamiast 5) bez zmiany sekcji",
                          "long tables (10 rows instead of 5) without changing the sections"))
    g.add_argument("--list", metavar="N", nargs="?", type=int, const=15,
                   help=L("pokaż ostatnie sesje", "list recent sessions"))
    g = ap.add_argument_group(L("sekcje (domyślnie: podsumowanie, czynności, modele, najcięższe "
                                "rozmowy i wskazówki)",
                                "sections (default: summary, activities, models, heaviest "
                                "conversations and tips)"))
    g.add_argument("--bash", action="store_true",
                   help=L("szum z poleceń Bash: długie wyniki bez ograniczenia",
                          "Bash noise: long results with no limit"))
    g.add_argument("--skills", action="store_true",
                   help=L("skille: używane, nieużywane, ich koszt w kontekście",
                          "skills: used, unused, their cost in the context"))
    g.add_argument("--project-map", dest="map", action="store_true",
                   help=L("mapa projektu: czego Claude szuka w kółko vs. CLAUDE.md",
                          "project map: what Claude looks up again and again vs. CLAUDE.md"))
    g.add_argument("--cache", action="store_true",
                   help=L("cache i długość rozmowy: wygasły cache, powtórne odczyty, rozmiar kontekstu",
                          "cache and conversation length: expired cache, repeated reads, context size"))
    g.add_argument("--time", action="store_true",
                   help=L("rodzaje tokenów i zużycie w czasie", "token types and usage over time"))
    g.add_argument("--breakdown", action="store_true",
                   help=L("podział: sesja główna vs subagenci, typy subagentów, projekty",
                          "breakdown: main session vs subagents, subagent types, projects"))
    g.add_argument("--full", action="store_true",
                   help=L("wszystkie sekcje i dłuższe tabele", "every section and longer tables"))
    g.add_argument("--only", type=parse_only, metavar=L("LISTA", "LIST"),
                   help=L("tylko te elementy, po przecinku (zastępuje zapisane ustawienia): "
                          + ",".join(settings_module.ELEMENTS),
                          "only these elements, comma-separated (replaces the saved settings): "
                          + ",".join(settings_module.ELEMENTS)))
    g = ap.add_argument_group(L("wyjście", "output"))
    g.add_argument("--html", metavar=L("PLIK", "FILE"), help=L("zapisz raport HTML", "write an HTML report"))
    g.add_argument("--md", metavar=L("PLIK", "FILE"),
                   help=L("zapisz raport jako Markdown do analizy przez Claude'a (domyślnie z pełnym "
                          "szczegółem)",
                          "write the report as Markdown for Claude to analyze (full detail by default)"))
    g.add_argument("--private", action="store_true",
                   help=L("ukryj nazwy projektów, plików i treść próśb (do udostępniania)",
                          "hide project/file names and prompt text (for sharing)"))
    g.add_argument("--configure", action="store_true",
                   help=L("interaktywnie wybierz elementy raportu i długość tabel (compact / "
                          "long); flagi sekcji dopisują się do zapisanego zestawu",
                          "interactively pick the report elements and the table length (compact / "
                          "long); section flags add to the saved set"))
    g.add_argument("--reset-config", action="store_true",
                   help=L("przywróć domyślne ustawienia raportu (usuwa plik konfiguracji)",
                          "reset report configuration to defaults (removes configuration file)"))
    g.add_argument("--no-config", action="store_true",
                   help=L("zignoruj zapisane ustawienia (--configure) w tym uruchomieniu",
                          "ignore the saved settings (--configure) for this run"))
    g.add_argument("--explain", action="store_true",
                   help=L("wyjaśnij tokeny surowe i ważone", "explain raw and weighted tokens"))
    g.add_argument("--color", dest="color", action="store_true", default=None,
                   help=L("wymuś kolory w terminalu (np. dla less -R)",
                          "force terminal colors (e.g. for less -R)"))
    g.add_argument("--no-color", dest="color", action="store_false",
                   help=L("wyłącz kolory w terminalu", "disable terminal colors"))
    g.add_argument("--lang", "-l", choices=list(i18n.SUPPORTED), default="en",
                   help=L("język: en (domyślnie) lub pl", "language: en (default) or pl"))
    g.add_argument("--version", "-V", action="version", version=f"%(prog)s {__version__}")
    g.add_argument("--dir", metavar=L("KATALOG", "DIR"),
                   help=L("katalog transkryptów (domyślnie ~/.claude/projects)",
                          "transcripts dir (default ~/.claude/projects)"))
    return ap


def _use_color(flag: Optional[bool]) -> bool:
    if flag is not None:
        return flag
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return sys.stdout.isatty() and os.environ.get("TERM") != "dumb"


def _load_from(window: Window, args: argparse.Namespace,
               prev_start: Optional[datetime.datetime]) -> Optional[datetime.datetime]:
    """the earliest moment any part of the report needs: the window, its --daily baseline day
    and the --diff window before it"""
    load_from = window.start
    if args.daily and window.has_base_day:
        load_from = midnight(window.first - datetime.timedelta(days=1))
    if prev_start is not None:
        load_from = min(load_from, prev_start)
    return load_from


def _daily_rows(window: Window, calls: List[Call], current: List[Call]) -> List[DayRow]:
    first = window.first or current[0].time.astimezone().date()
    last = window.last if window.start is not None else current[-1].time.astimezone().date()
    has_base = window.has_base_day
    series_from = first - datetime.timedelta(days=1) if has_base else first
    return daily_rows(daily_series(calls, series_from, last), has_base)


def _write_file(path: str, page: str, n_calls: int, weighted: float) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)
    print(L(f"zapisano {path}  ({n_calls} wywołań, {fmt_tok(weighted)} tokenów ważonych)",
            f"saved {path}  ({n_calls} calls, {fmt_tok(weighted)} weighted tokens)"))
    uri = "file://" + urllib.parse.quote(os.path.abspath(path))
    # OSC 8 hyperlink when on a terminal; the bare file:// URL is auto-linked by most terminals too
    link = f"\033]8;;{uri}\033\\{uri}\033]8;;\033\\" if sys.stdout.isatty() else uri
    print(L("otwórz: ", "open: ") + link)


def main(argv: Optional[Sequence[str]] = None) -> None:
    argv = sys.argv[1:] if argv is None else list(argv)
    i18n.set_lang(i18n.detect_lang(argv))  # an invalid value is reported by argparse below
    ap = build_parser()
    args = ap.parse_args(argv)
    saved = None if args.no_config else settings_module.load()
    try:
        plan = resolve(args, saved)  # before the separate commands: they take no report options
    except OptionsError as e:
        ap.error(str(e))

    color = _use_color(args.color)
    if args.explain:
        print(explain_text(color=color))
        return
    if args.configure:
        configure.main()
        return
    if args.reset_config:
        cfg = settings_module.settings_path()
        if cfg.is_file():
            cfg.unlink()
            print(L(f"przywrócono ustawienia domyślne (usunięto {cfg})",
                    f"restored default settings (removed {cfg})"))
        else:
            print(L("ustawienia są już domyślne (brak zapisanego pliku konfiguracji)",
                    "settings are already default (no saved configuration file)"))
        return
    root = args.dir or default_root()
    if not os.path.isdir(root):
        sys.exit(L(f"brak katalogu {root} — czy Claude Code był tu używany? (--dir)",
                   f"no directory {root} — has Claude Code been used here? (--dir)"))
    namer = Namer(args.private)

    if args.list:
        print(session_list(root, recent_sessions(root, args.list), namer, color=color))
        return

    files, session_key, session_label = None, None, None
    if args.session:
        found = find_session(root, args.session)
        if not found:
            sys.exit(L(f"nie znaleziono sesji '{args.session}'. Lista: --list",
                       f"no session matching '{args.session}'. See --list"))
        session_key, files = found
        session_label = session_key[1][:8]

    try:
        window = resolve_window(args)
    except ValueError as e:
        ap.error(str(e))
    if args.session and not picked_options(args):
        window.start, window.first = None, None  # a session report covers the whole session
    start, end = window.start, window.end

    prev_start = previous_window_start(window) if args.diff else None
    calls, sessions = load(root, _load_from(window, args, prev_start), end, files=files)
    current = [c for c in calls if start is None or c.time >= start]
    if not current:
        sys.exit(L("brak danych w tym okresie", "no data in this time window"))

    label = period_label(start, end, window.last_n, window.rolling, session_label)
    if session_key:
        label += "  (" + namer.project(sessions.get(session_key), session_key[0]) + ")"
    ctx = ReportContext(label=label, root_display=root.replace(os.path.expanduser("~"), "~", 1),
                        sessions=sessions, namer=namer,
                        calls=current, session=args.session, session_key=session_key, plan=plan)
    if session_key:
        ctx.detail = session_detail(session_key, current, sessions.get(session_key), namer)
    stats = aggregate(current, sessions, namer)
    prev_stats = None
    if prev_start is not None:
        prev_stats = aggregate([c for c in calls if prev_start <= c.time < start], sessions, namer,
                               hotspots=False)
        ctx.prev_label = period_label(prev_start, start)
    daily = _daily_rows(window, calls, current) if args.daily else None

    if args.html:
        _write_file(args.html, html_report(stats, ctx, prev_stats, daily),
                    stats.n_calls, stats.weighted)
    if args.md:
        _write_file(args.md, md_report(stats, ctx, prev_stats, daily),
                    stats.n_calls, stats.weighted)
    if args.html or args.md:
        return
    if prev_stats is not None:
        print(text_diff(stats, prev_stats, ctx, color=color))
        print()
    if daily:
        print(text_daily(daily, color=color))
        print()
    print(text_report(stats, ctx, color=color))


def run() -> None:
    # e.g. a Windows console or a redirected stdout that can't encode ▲ ▼ … — don't crash
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    try:
        main()
        sys.stdout.flush()
    except BrokenPipeError:
        # output piped into e.g. `head` that exited early: silence the error at interpreter exit
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
