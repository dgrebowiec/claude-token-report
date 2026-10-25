"""Interactive configurator: table length (compact / long) and which elements the report contains.

In a terminal it is a full-screen editor driven by keys (arrows, space, enter). When stdin is
not a terminal (pipes, tests) it falls back to one text command per line.
"""
from __future__ import annotations

import copy
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Callable, List, Optional

from . import settings as settings_module
from .i18n import L
from .options import ELEMENT_INFO, uncompared, warnings_for
from .settings import DEFAULT_ELEMENTS, ELEMENTS, LEVELS, Settings, describe, describe_level

REVERSE = "\033[7m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
BOLD_CYAN = "\033[1;36m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
MAGENTA = "\033[35m"
RESET = "\033[0m"

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def key_help() -> str:
    return L(
        "↑↓ wybór   SPACJA włącz/wyłącz   ←→ długość tabel   a wszystko   n nic   r/d domyślne   "
        "s podsumowanie   ENTER zapisz (po podsumowaniu)   q wyjście",
        "↑↓ select   SPACE toggle   ←→ table length   a all   n none   r/d defaults   "
        "s summary   ENTER save (after the summary)   q quit"
    )


def line_help() -> str:
    return L("""polecenia:
  <n>     włącz lub wyłącz element n    l       zmień długość tabel (compact / long)
  a       wszystkie elementy            n       żaden (zostaje pierwszy)
  r / d   przywróć domyślne             s       podsumowanie (bez zapisu)
  w       podsumowanie, potem zapis po potwierdzeniu (t)                q   wyjdź bez zapisu""",
             """commands:
  <n>     toggle element n              l       switch table length (compact / long)
  a       all elements                  n       none (the first one stays)
  r / d   restore defaults              s       summary (nothing saved)
  w       summary, then save once confirmed (y)                         q   quit without saving""")


SUMMARY_KEYS_HELP = ("ENTER/w zapisz   inny klawisz: wróć do edycji",
                     "ENTER/w save   any other key: back to editing")
CONFIRM = ("t", "tak", "y", "yes", "w")  # answers that confirm saving in the line-based editor


def summary_lines(settings: Settings, color: bool = True) -> List[str]:
    """The summary screen: every element with its state, what long tables and --diff do for it,
    and the warnings (options.warnings_for) about settings that would have no effect."""
    b, d, g, y, bc, rst = ((BOLD, DIM, GREEN, YELLOW, BOLD_CYAN, RESET) if color
                           else ("", "", "", "", "", ""))
    yes, na = L("tak", "yes"), L("nie dotyczy", "n/a")
    compared, not_compared = L("porównanie", "compared"), L("bez porównania", "not compared")
    summary = L("podsumowanie", "summary")
    width = max(len(summary), *(len(e) for e in ELEMENTS)) + 2
    col = max(len(L("długie tabele", "long tables")), len(yes), len(na)) + 3

    def row(mark: str, name: str, tables: str, diff: str, note: str = "") -> str:
        return f"   {mark} {name:<{width}}{tables:<{col}}{diff}{note}"

    lines = [f" {bc}{L('PODSUMOWANIE USTAWIEŃ', 'SETTINGS SUMMARY')}{rst}", "",
             f" {b}{L('Długość tabel', 'Table length')}{rst}: {b}{settings.level}{rst}  {d}"
             + (L("rankingi po 10 wierszy (czynności po 16)", "rankings of 10 rows (activities 16)")
                if settings.level == "long" else
                L("rankingi po 5 wierszy (czynności po 8)", "rankings of 5 rows (activities 8)"))
             + rst, "",
             f"{b}" + row(" ", "element", L("długie tabele", "long tables"), "--diff") + rst,
             f"{g}" + row("✓", summary, na, compared, L("  (zawsze w raporcie)", "  (always in the report)")) + rst]
    chosen = settings.shown()
    for e in ELEMENTS:
        info = ELEMENT_INFO[e]
        line = row("✓" if e in chosen else "·", e, yes if info.has_tables else na,
                   not_compared if uncompared((e,)) else compared)
        lines.append(f"{g}{line}{rst}" if e in chosen else f"{d}{line}{rst}")
    lines += ["", f" {d}✓ {L('włączony', 'on')}   · {L('wyłączony', 'off')}   "
                  + L("długie tabele: czy long wydłuża tabele elementu",
                      "long tables: whether long makes the tables of the element longer") + rst,
              f" {d}--diff: " + L("czy porównanie z poprzednim okresem ma dla niego część",
                                  "whether the comparison with the previous window has a part for it")
              + rst, ""]
    warnings = warnings_for(settings)
    lines += [f" {y}⚠ {w}{rst}" for w in warnings] or [
        f" {g}✓ {L('każde ustawienie ma skutek', 'every setting has an effect')}{rst}"]
    return lines


def section_preview(element: str, level: str, width: int = 86, color: bool = True) -> List[str]:
    """A realistic terminal preview of the element for the table length (compact / long)."""
    lines = _preview(element, level, width, color)
    if level == "long" and not ELEMENT_INFO[element].has_tables:
        d, rst = (DIM, RESET) if color else ("", "")
        lines.append(f" {d}│ {L('długie tabele nie zmieniają tej sekcji (stała długość)', 'long tables do not change this section (fixed length)')}{rst}")
    return lines


def _preview(element: str, level: str, width: int, color: bool) -> List[str]:
    b = BOLD if color else ""
    d = DIM if color else ""
    c = CYAN if color else ""
    bc = BOLD_CYAN if color else ""
    y = YELLOW if color else ""
    g = GREEN if color else ""
    m = MAGENTA if color else ""
    rst = RESET if color else ""

    col_rule = f"{d}{'─' * min(width - 6, 76)}{rst}"

    if element == "activities":
        limit_note = (L("compact: do 8 wierszy + (pozostałe)", "compact: up to 8 rows + (other)") if level == "compact"
                      else L("long: do 16 wierszy (w HTML do 20)", "long: up to 16 rows (20 in HTML)"))
        lines = [
            f" {bc}── {L('NA CO IDĄ TOKENY', 'WHERE THE TOKENS GO')} ──{rst}",
            f" {b}{L('czynność', 'activity'):<30}{L('surowe', 'raw'):>8}{L('ważone', 'weighted'):>9}{'%':>6}{L('użyć', 'uses'):>7}{L('śr./szt.', 'avg'):>9}{rst}",
            f" {col_rule}",
            f" Bash: searching (grep/find/ls)   82.7M   {b}10.4M{rst} 22.4%    903     12k  {d}│{rst}{c}▮▮▮▮{d}▯▯▯▯▯▯▯▯▯▯▯▯{rst}",
            f" Bash: scripts (python/node/own)  61.1M   {b} 6.3M{rst} 13.5%    459     14k  {d}│{rst}{c}▮▮▮{d}▯▯▯▯▯▯▯▯▯▯▯▯▯{rst}",
            f" Edit/Write — changing files      29.9M   {b} 4.5M{rst}  9.8%    646      7k  {d}│{rst}{c}▮▮{d}▯▯▯▯▯▯▯▯▯▯▯▯▯▯{rst}",
        ]
        if level == "long":
            lines.append(f" Read — reading files             39.2M   {b} 3.7M{rst}  8.0%    878      4k  {d}│{rst}{c}▮▮{d}▯▯▯▯▯▯▯▯▯▯▯▯▯▯{rst}")
        lines.append(f" {d}│ {limit_note}{rst}")
        return lines

    if element == "models":
        limit_note = (L("compact: do 5 modeli", "compact: up to 5 models") if level == "compact"
                      else L("long: do 10 modeli", "long: up to 10 models"))
        lines = [
            f" {bc}── {L('MODELE', 'MODELS')} ──{rst}",
            f" {b}{'model':<22}{L('surowe', 'raw'):>8}{L('ważone', 'weighted'):>9}{'%':>6}{L('wywoł.', 'calls'):>7}{L('waga', 'weight'):>7}{rst}",
            f" {col_rule}",
            f" claude-opus-5-5       327.9M   {b}40.1M{rst} 86.3%   2501   x0.8  {d}│{rst}{c}▮▮▮▮▮▮▮▮▮▮▮{d}▯▯{rst}",
            f" claude-sonnet-5-5      78.7M   {b} 6.3M{rst} 13.5%    912   x0.4  {d}│{rst}{c}▮▮{d}▯▯▯▯▯▯▯▯▯▯▯{rst}",
            f" claude-haiku-5-5       10.6M   {b} 126k{rst}  0.3%    109  x0.02  {d}·············{rst}",
        ]
        lines.append(f" {d}│ {limit_note}{rst}")
        return lines

    if element == "sessions":
        limit_note = (L("compact: 5 najcięższych sesji", "compact: 5 heaviest sessions") if level == "compact"
                      else L("long: 10 najcięższych sesji (w HTML 15)", "long: 10 heaviest sessions (15 in HTML)"))
        topic_a = L("orkiestruj plan...", "orchestrate plan...")
        topic_b = L("napraw błąd logowania...", "fix login bug...")
        lines = [
            f" {bc}── {L('NAJCIĘŻSZE ROZMOWY', 'HEAVIEST CONVERSATIONS')} ──{rst}",
            f" {b}{L('sesja', 'session'):<10}{L('projekt', 'project'):<18}{L('ważone', 'weighted'):>9}{'%':>6}{L('maks.ctx', 'max ctx'):>9}  {L('temat', 'topic')}{rst}",
            f" {col_rule}",
            f" {c}c8af7b08{rst}   velo-ad-studio     {b}9.5M{rst} 20.5%     177k  {topic_a}",
            f" {c}a1eeab39{rst}   AISudokuAndroid    {b}4.1M{rst}  8.8%     135k  {topic_b}",
        ]
        lines.append(f" {d}│ {limit_note}{rst}")
        return lines

    if element == "tips":
        return [
            f" {bc}── {L('CO MOŻNA POPRAWIĆ', 'WHAT YOU COULD IMPROVE')} ──{rst}",
            f" {bc}•{rst} " + L("Wygasły cache: 104× rozmowa zapisana od nowa (24% zużycia). Rozważ /compact przed długą przerwą.",
                                 "Expired cache: 104 times conversation rewritten (24% of usage). Consider /compact before long pauses."),
            f" {bc}•{rst} " + L("Szukanie i czytanie kodu to 44% zużycia. Opisz strukturę w CLAUDE.md i zlecaj szukanie subagentom.",
                                 "Searching and reading code is 44% of usage. Describe layout in CLAUDE.md and delegate searches to subagents."),
            f" {d}│ " + L("rekomendacje posortowane według potencjalnych oszczędności", "recommendations ranked by potential savings") + f"{rst}",
        ]

    if element == "time":
        return [
            f" {bc}── {L('RODZAJE TOKENÓW — surowe vs ważone', 'TOKEN TYPES — raw vs weighted')} ──{rst}",
            f" cache read             391.4M   {b}13.9M{rst} 29.9%  {d}│{rst}{c}▮▮▮▮▮▮▮▮{d}▯▯▯▯▯▯▯▯▯▯▯▯▯▯▯▯▯▯{rst}",
            f" cache write 5 min       16.6M   {b}13.8M{rst} 29.8%  {d}│{rst}{c}▮▮▮▮▮▮▮▮{d}▯▯▯▯▯▯▯▯▯▯▯▯▯▯▯▯▯▯{rst}",
            f" output (response)        3.0M   {b}10.3M{rst} 22.1%  {d}│{rst}{c}▮▮▮▮▮▮{d}▯▯▯▯▯▯▯▯▯▯▯▯▯▯▯▯▯▯▯▯{rst}",
            f" {d}│ {L('rozbicie kosztów cache vs wyjście, rozkład dzienny/tygodniowy i trend głównych czynności', 'cache vs output breakdown, daily/weekly distribution and the trend of top activities')}{rst}",
        ]

    if element == "breakdown":
        return [
            f" {bc}── {L('SESJA GŁÓWNA vs SUBAGENCI & PROJEKTY', 'MAIN vs SUBAGENTS & PROJECTS')} ──{rst}",
            f" " + L("subagenci", "subagents") + f"             246.2M   {b}28.8M{rst} 61.9%    2086  {d}│{rst}{c}▮▮▮▮▮▮▮▮▮▮▮▮{d}▯▯▯▯▯▯▯▯{rst}",
            f" " + L("sesja główna", "main session") + f"          171.0M   {b}17.7M{rst} 38.1%    1436  {d}│{rst}{c}▮▮▮▮▮▮▮▮{d}▯▯▯▯▯▯▯▯▯▯▯▯{rst}",
            f" AISudokuAndroid        201.3M   {b}24.4M{rst} 52.4%    1891  {d}│{rst}{c}▮▮▮▮▮▮▮▮▮▮{d}▯▯▯▯▯▯▯▯▯▯{rst}",
            f" {d}│ {L('udział subagentów, subagenci wg typu i podział zużycia wg projektów', 'subagents share, subagents by type and usage split across projects')}{rst}",
        ]

    if element == "cache":
        calls_word = L("wyw.", "calls")
        wt_word = L("ważonych", "weighted")
        extra_word = L("nadmiaru", "extra")
        gap_word = L("przerwa", "pause")
        return [
            f" {bc}── {L('DŁUGOŚĆ ROZMOWY & WYGASŁY CACHE', 'CONVERSATION LENGTH & EXPIRED CACHE')} ──{rst}",
            f" 100-200k               1546 {calls_word}  {b}23.4M{rst} {wt_word} (50.4%)  {d}│{rst}{c}▮▮▮▮▮▮▮▮▮{d}▯▯▯▯▯▯▯▯▯{rst}",
            f" " + L("wygasły cache", "expired cache") + f"          104 {calls_word}   {b}11.2M{rst} {extra_word}  ({gap_word} > 60 min: 34×)",
            f" {d}│ {L('koszt długich rozmów, zapisów cache od nowa (sesje, zdarzenia) i powtórnych odczytów', 'cost of long context, cache rewrites (sessions, events) and repeated reads')}{rst}",
        ]

    if element == "bash":
        long_word = L("długich", "long")
        wt_word = L("ważonych", "weighted")
        advice_txt = L("narzędzie Read z offset/limit lub head zamiast całego pliku",
                       "the Read tool with offset/limit, or head, instead of the whole file")
        return [
            f" {bc}── {L('SZUM Z POLECEŃ BASH', 'BASH NOISE')} ──{rst}",
            f" {b}cat{rst}                       12 {long_word} / 54   {b}322k{rst} {wt_word}   max 5k",
            f"   {c}→ {advice_txt}{rst}",
            f" {d}│ {L('wykrywa komendy bez -q, | head lub filtra wrzucające >2000 tokenów', 'detects commands without -q, | head or filter dumping >2000 tokens')}{rst}",
        ]

    if element == "skills":
        convs_word = L("rozmów", "convs")
        tok_word = L("tokeny", "tokens")
        named_word = L("wspomniany 3×", "named in 3 convs")
        used_tag = L("używany", "used")
        unused_tag = L("nieużyty", "unused")
        return [
            f" {bc}── {L('SKILLE', 'SKILLS')} ──{rst}",
            f" {b}kotlin-android{rst}            11 {convs_word}     {d}({used_tag}){rst}",
            f" {b}run{rst}                       92 {tok_word}     {y}{named_word}{rst} {d}({unused_tag}){rst}",
            f" {d}│ {L('pokazuje, które skille są używane, a które tylko zajmują kontekst', 'shows which skills are used and which only take up context')}{rst}",
            f" {d}│ {L('compact: do 5 wierszy na listę', 'compact: up to 5 rows per list') if level == 'compact' else L('long: do 10 wierszy na listę', 'long: up to 10 rows per list')}{rst}",
        ]

    if element == "map":
        reads_word = L("odczytów", "reads")
        lines_word = L("linii", "lines")
        not_found_tag = L("✗ nie znaleziono", "✗ not found")
        large_tag = L("[duży]", "[large]")
        return [
            f" {bc}── {L('MAPA PROJEKTU', 'PROJECT MAP')} ──{rst}",
            f" {bc}▸{rst} ~/projects/velo-ad-studio",
            f" docs/agy-workflow.md        46 {reads_word}    221 {lines_word}   {y}{not_found_tag}{rst}",
            f" src/panel/server.ts         39 {reads_word}   1670 {lines_word}   {y}{not_found_tag}{rst}  {m}{large_tag}{rst}",
            f" {d}│ {L('pliki i symbole szukane w kółko vs CLAUDE.md + gotowy szkic mapy', 'repeatedly looked up files/symbols vs CLAUDE.md + draft map')}{rst}",
        ]

    return [f" {element}"]


def frame_preview(lines: List[str], element: str, level: str, width: int = 86, color: bool = True) -> List[str]:
    """Wraps preview lines in a clean, unmistakable terminal box container."""
    c = CYAN if color else ""
    bc = BOLD_CYAN if color else ""
    d = DIM if color else ""
    rst = RESET if color else ""

    box_w = max(50, min(width - 2, 88))
    inner_w = box_w - 4

    header_txt = f" 👁  {L('PODGLĄD SEKCJI', 'SECTION PREVIEW')}: {element} ({level}) "
    dash_len = max(2, inner_w - len(header_txt))
    top = f" {c}╭─{bc}{header_txt}{c}{'─' * dash_len}╮{rst}"
    bottom = f" {c}╰{'─' * (inner_w + 2)}╯{rst}"

    out = [top]
    for line in lines:
        vis_len = len(strip_ansi(line))
        pad = max(0, inner_w - vis_len)
        out.append(f" {c}│{rst} {line}{' ' * pad} {c}│{rst}")
    out.append(bottom)
    return out


class Editor:
    """Editing state shared by the full-screen and the line-based front ends."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.cursor = 0
        self.dirty = False
        self.message = ""
        self._quit_armed = False
        self.summary_open = False  # the summary screen (s, or ENTER / w before saving)

    # --- operations ---

    def _changed(self) -> None:
        self.dirty = True

    def move_cursor(self, step: int) -> None:
        self.cursor = (self.cursor + step) % len(ELEMENTS)

    def toggle(self, index: Optional[int] = None) -> None:
        name = ELEMENTS[self.cursor if index is None else index]
        chosen = self.settings.elements
        if name in chosen:
            if len(chosen) == 1:
                self.message = L("co najmniej jeden element musi zostać", "at least one element must stay on")
                return
            chosen.remove(name)
        else:
            chosen.append(name)
        self.settings.elements = [e for e in ELEMENTS if e in chosen]
        self._changed()

    def cycle_level(self, step: int = 1) -> None:
        s = self.settings
        s.level = LEVELS[(LEVELS.index(s.level) + step) % len(LEVELS)]
        self._changed()

    def select_all(self) -> None:
        self.settings.elements = list(ELEMENTS)
        self._changed()

    def select_none(self) -> None:
        self.settings.elements = [ELEMENTS[0]]
        self._changed()

    def reset(self) -> None:
        self.settings.level = Settings().level
        self.settings.elements = list(DEFAULT_ELEMENTS)
        self.cursor = 0
        self.message = L("przywrócono ustawienia domyślne (enter aby zapisać)",
                         "restored default settings (press enter to save)")
        self._changed()

    # --- input ---

    def handle_key(self, key: str) -> Optional[str]:
        """One key of the full-screen editor. Returns 'save', 'quit' or None. ENTER / w open the
        summary first; ENTER / w there saves, any other key goes back to editing."""
        self.message = ""
        if self.summary_open:
            if key in ("enter", "w"):
                return "save"
            if key == "ctrl-c":
                return "quit"
            self.summary_open = False
            return None
        if key in ("q", "esc", "ctrl-c"):
            if self.dirty and not self._quit_armed and key != "ctrl-c":
                self._quit_armed = True
                self.message = L("niezapisane zmiany: q jeszcze raz = wyjście, enter = zapis",
                                 "unsaved changes: press q again to quit, enter to save")
                return None
            return "quit"
        self._quit_armed = False
        if key in ("enter", "w", "s"):
            self.summary_open = True
            return None
        actions = {
            "up": lambda: self.move_cursor(-1), "k": lambda: self.move_cursor(-1),
            "down": lambda: self.move_cursor(1), "j": lambda: self.move_cursor(1),
            "space": self.toggle, "x": self.toggle,
            "left": lambda: self.cycle_level(-1), "right": lambda: self.cycle_level(1),
            "l": lambda: self.cycle_level(1),
            "a": self.select_all, "n": self.select_none,
            "r": self.reset, "d": self.reset,
        }
        if key in actions:
            actions[key]()
        elif key.isdigit() and 1 <= int(key) <= min(9, len(ELEMENTS)):
            self.cursor = int(key) - 1
            self.toggle()
        elif key == "0":
            self.cursor = len(ELEMENTS) - 1
            self.toggle()
        return None

    def handle_line(self, command: str) -> Optional[str]:
        """One text command of the line-based editor. Returns 'confirm' (w: the summary, then
        save once confirmed), 'summary' (s), 'quit' or None."""
        self.message = ""
        if command == "w":
            return "confirm"
        if command == "s":
            return "summary"
        if command == "":
            return None  # just show the editor again
        if command == "q":
            return "quit"
        if command == "l":
            self.cycle_level(1)
        elif command == "a":
            self.select_all()
        elif command == "n":
            self.select_none()
        elif command in ("r", "d", "reset", "default"):
            self.reset()
        elif command.isdigit():
            index = int(command) - 1
            if 0 <= index < len(ELEMENTS):
                self.toggle(index)
            else:
                self.message = L(f"brak elementu {command}", f"no element {command}")
        else:
            self.message = L(f"nieznane polecenie: {command!r}", f"unknown command: {command!r}")
        return None

    # --- output ---

    def preview(self) -> List[str]:
        """What the report will contain, in report order."""
        shown = self.settings.shown()
        tags = [f"{CYAN}[{L('podsumowanie', 'summary')}]{RESET}"]
        for e in shown:
            tags.append(f"{BOLD}[{e}]{RESET}")
        return ["  " + " · ".join(tags)]

    def rows(self, width: int) -> List[str]:
        lines = []
        long_tables = self.settings.level == "long"
        for index, name in enumerate(ELEMENTS):
            is_active = index == self.cursor
            is_on = name in self.settings.elements
            note = ""
            if long_tables and is_on and not ELEMENT_INFO[name].has_tables:
                note = f" {DIM}" + L("(long nic tu nie zmienia)", "(long changes nothing here)") + RESET

            mark = f"{GREEN}[✓]{RESET}" if is_on else f"{DIM}[ ]{RESET}"
            num = f"{DIM}{index + 1:>2}.{RESET}"

            if is_active:
                name_str = f"{BOLD_CYAN}{name:<10}{RESET}"
                desc_str = f"{BOLD}{describe(name)}{RESET}"
                prefix = f"{BOLD_CYAN}▸{RESET} "
            else:
                name_str = f"{name:<10}"
                desc_str = f"{DIM}{describe(name)}{RESET}"
                prefix = "  "

            row = f"{prefix}{num} {mark} {name_str} {desc_str}{note}"
            lines.append(row)
        return lines

    def summary_screen(self) -> List[str]:
        title = f" {BOLD_CYAN}⚙  CLAUDE CODE TOKEN REPORT — {L('KONFIGURACJA', 'CONFIGURATION')}{RESET}"
        if self.dirty:
            title += f"  {YELLOW}({L('niezapisane zmiany', 'unsaved changes')}){RESET}"
        return [title, "", *summary_lines(self.settings), "", f" {DIM}{L(*SUMMARY_KEYS_HELP)}{RESET}"]

    def screen(self, width: int, height: int = 34) -> List[str]:
        if self.summary_open:
            return self.summary_screen()
        s = self.settings
        title = f" {BOLD_CYAN}⚙  CLAUDE CODE TOKEN REPORT — {L('KONFIGURACJA', 'CONFIGURATION')}{RESET}"
        if self.dirty:
            title += f"  {YELLOW}({L('niezapisane zmiany', 'unsaved changes')}){RESET}"

        elements_hdr = (f" {BOLD}{L('Elementy raportu', 'Report elements')}{RESET}   "
                        f"{DIM}{L('SPACJA włącz/wyłącz', 'SPACE toggle')} · "
                        f"{L('r/d domyślne', 'r/d defaults')}{RESET}")

        level_pills = []
        for lvl in LEVELS:
            if lvl == s.level:
                level_pills.append(f"{BOLD_CYAN}● [ {lvl.upper()} ]{RESET}")
            else:
                level_pills.append(f"{DIM}[ {lvl} ]{RESET}")
        pills_str = "   ".join(level_pills)

        level_hdr = f" {BOLD}{L('Długość tabel', 'Table length')}{RESET}:  {pills_str}   {DIM}(← →){RESET}"
        level_desc = f"    {DIM}{describe_level(s.level)}{RESET}"

        top_lines = [
            title,
            "",
            elements_hdr,
            *self.rows(width),
            "",
            level_hdr,
            level_desc,
            "",
        ]

        curr_elem = ELEMENTS[self.cursor]
        raw_preview = section_preview(curr_elem, s.level, width=width, color=True)

        bottom_lines = [
            "",
            f" {BOLD}{L('Raport będzie zawierał', 'The report will contain')}{RESET}:",
            *self.preview(),
            "",
            f" {DIM}{key_help()}{RESET}",
        ]
        if self.message:
            bottom_lines.append(f" {BOLD_CYAN}{self.message}{RESET}")

        # Allocate preview frame lines based on available terminal height
        overhead = len(top_lines) + len(bottom_lines) + 2  # borders of frame
        avail_preview_lines = max(2, height - overhead) if height else len(raw_preview)
        framed_preview = frame_preview(raw_preview[:avail_preview_lines], curr_elem, s.level,
                                       width=width, color=True)

        return top_lines + framed_preview + bottom_lines


# --- terminal handling ---

KEYS = {
    "\x1b[A": "up", "\x1b[B": "down", "\x1b[C": "right", "\x1b[D": "left",
    "\x1bOA": "up", "\x1bOB": "down", "\x1bOC": "right", "\x1bOD": "left",
    "\x1b": "esc", " ": "space", "\r": "enter", "\n": "enter", "\x03": "ctrl-c",
}
WINDOWS_ARROWS = {"H": "up", "P": "down", "K": "left", "M": "right"}


def decode_key(sequence: str) -> str:
    """Raw characters of one key press -> key name (or the character itself)."""
    if sequence in KEYS:
        return KEYS[sequence]
    return sequence if len(sequence) == 1 else ""


class Terminal:
    """Single-key input and full-screen drawing: termios on POSIX, msvcrt on Windows."""

    def __enter__(self) -> "Terminal":
        if os.name == "nt":
            os.system("")  # turns on ANSI escape handling in the Windows console
        else:
            import termios
            import tty
            self._fd = sys.stdin.fileno()
            self._saved = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)
        sys.stdout.write("\033[?1049h\033[?25l")  # alternate screen, hide cursor
        sys.stdout.flush()
        return self

    def __exit__(self, *exc) -> None:
        sys.stdout.write("\033[?25h\033[?1049l")
        sys.stdout.flush()
        if os.name != "nt":
            import termios
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved)

    def read_key(self) -> str:
        if os.name == "nt":
            import msvcrt
            char = msvcrt.getwch()
            if char in ("\x00", "\xe0"):
                return WINDOWS_ARROWS.get(msvcrt.getwch(), "")
            return decode_key(char)
        import select
        data = os.read(self._fd, 1)
        if data == b"\x1b":
            while len(data) < 8 and select.select([self._fd], [], [], 0.03)[0]:
                data += os.read(self._fd, 1)
        elif data and data[0] >= 0xC0:  # first byte of a multi-byte UTF-8 character
            while select.select([self._fd], [], [], 0)[0] and len(data) < 4:
                data += os.read(self._fd, 1)
        return decode_key(data.decode("utf-8", errors="ignore"))

    def draw(self, lines: List[str]) -> None:
        sys.stdout.write("\033[H\033[2J" + "\n".join(lines) + "\n")
        sys.stdout.flush()


def run_tui(path: Optional[Path] = None) -> Optional[Path]:
    """Full-screen editor. Returns the path it saved to, or None when the user quit."""
    path = path or settings_module.settings_path()
    editor = Editor(copy.deepcopy(settings_module.load(path) or Settings()))
    result = None
    with Terminal() as term:
        try:
            while result is None:
                sz = shutil.get_terminal_size()
                term.draw(editor.screen(sz.columns, sz.lines))
                result = editor.handle_key(term.read_key())
        except KeyboardInterrupt:
            result = "quit"
    if result == "save":
        saved = settings_module.save(editor.settings, path)
        print(L(f"zapisano {saved}", f"saved to {saved}"))
        return saved
    print(L("nie zapisano", "not saved"))
    return None


# --- line-based fallback ---

def show(editor: Editor, out: Callable[[str], None]) -> None:
    out("")
    out(L("długość tabel: ", "table length: ") + f"{editor.settings.level}  ({describe_level(editor.settings.level)})")
    out("")
    for row in editor.rows(78):
        out(strip_ansi(row).rstrip())
    out("")
    curr_elem = ELEMENTS[editor.cursor]
    out(L(f"podgląd sekcji [{curr_elem}] ({editor.settings.level}):",
          f"preview of section [{curr_elem}] ({editor.settings.level}):"))
    for pline in section_preview(curr_elem, editor.settings.level, width=78, color=False):
        out(" " + pline)
    out("")
    out(L("raport będzie zawierał:", "the report will contain:"))
    for line in editor.preview():
        out(strip_ansi(line))
    out("")
    out(line_help())


def run(path: Optional[Path] = None, ask: Callable[[str], str] = input,
        out: Callable[[str], None] = print) -> Optional[Path]:
    """Line-based editor. Returns the path it saved to, or None when the user quit."""
    path = path or settings_module.settings_path()
    editor = Editor(copy.deepcopy(settings_module.load(path) or Settings()))
    redraw = True
    while True:
        if redraw:
            show(editor, out)
        redraw = True
        try:
            command = ask("> ").strip()
        except EOFError:
            command = "q"
        result = editor.handle_line(command)
        if editor.message:
            out(editor.message)
        if result in ("summary", "confirm"):
            out("")
            for line in summary_lines(editor.settings, color=False):
                out(line.rstrip())
            out("")
        if result == "summary":
            out(L("w = zapisz, Enter = ekran edycji", "w = save, Enter = the editor"))
            redraw = False
            continue
        if result == "confirm":
            try:
                answer = ask(L("zapisać? t = tak, inne = wróć do edycji > ",
                               "save? y = yes, anything else = back to editing > ")).strip().lower()
            except EOFError:
                answer = ""
            if answer in CONFIRM:
                result = "save"
            else:
                out(L("nie zapisano — wracasz do edycji", "not saved — back to editing"))
        if result == "save":
            saved = settings_module.save(editor.settings, path)
            out(L(f"zapisano {saved}", f"saved to {saved}"))
            return saved
        if result == "quit":
            out(L("nie zapisano", "not saved"))
            return None


def main(path: Optional[Path] = None) -> Optional[Path]:
    """Full-screen editor in a terminal, line-based otherwise."""
    if sys.stdin.isatty() and sys.stdout.isatty():
        return run_tui(path)
    return run(path)
