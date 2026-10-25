"""Interactive configurator: detail level and which elements the report contains.

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
from .settings import (DEFAULT_ELEMENTS, ELEMENTS, LEVELS, MINIMAL_ELEMENTS, Settings,
                        describe, describe_level)

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
        "↑↓ wybór   SPACJA włącz/wyłącz   ←→ poziom   a wszystko   n nic   r/d domyślne   ENTER zapisz   q wyjście",
        "↑↓ select   SPACE toggle   ←→ level   a all   n none   r/d defaults   ENTER save   q quit"
    )


def line_help() -> str:
    return L("""polecenia:
  <n>     włącz lub wyłącz element n    l       zmień poziom szczegółowości
  a       wszystkie elementy            n       żaden (zostaje pierwszy)
  r / d   przywróć domyślne             w       zapisz i wyjdź          q   wyjdź bez zapisu""",
             """commands:
  <n>     toggle element n              l       cycle detail level
  a       all elements                  n       none (the first one stays)
  r / d   restore defaults              w       save and exit           q   quit without saving""")


def section_preview(element: str, level: str, width: int = 86, color: bool = True) -> List[str]:
    """Generates a rich, realistic terminal preview of the given element taking language and level into account."""
    b = BOLD if color else ""
    d = DIM if color else ""
    c = CYAN if color else ""
    bc = BOLD_CYAN if color else ""
    y = YELLOW if color else ""
    g = GREEN if color else ""
    m = MAGENTA if color else ""
    rst = RESET if color else ""

    col_rule = f"{d}{'─' * min(width - 6, 76)}{rst}"

    if level == "minimal" and element not in MINIMAL_ELEMENTS:
        return [
            f" {bc}── {element.upper()} ──{rst}",
            f" {y}{L(' [!] Ta sekcja jest pomijana na poziomie minimal.', ' [!] This section is omitted at minimal level.')}{rst}",
            f" {d}{L('     (zmień poziom na normal lub detailed za pomocą ← →, aby ją włączyć)', '     (change level to normal or detailed using ← → to enable it)')}{rst}",
        ]

    if element == "activities":
        limit_note = (L("tryb skrócony: do 8 głównych czynności", "short mode: up to 8 top activities") if level == "minimal"
                      else L("domyślnie: do 8 wierszy + (pozostałe)", "default: up to 8 rows + (other)") if level == "normal"
                      else L("pełna lista: do 16 wierszy + podział narzędzi", "full list: up to 16 rows + tool split"))
        lines = [
            f" {bc}── {L('NA CO IDĄ TOKENY', 'WHERE THE TOKENS GO')} ──{rst}",
            f" {b}{L('czynność', 'activity'):<30}{L('surowe', 'raw'):>8}{L('ważone', 'weighted'):>9}{'%':>6}{L('użyć', 'uses'):>7}{L('śr./szt.', 'avg'):>9}{rst}",
            f" {col_rule}",
            f" Bash: searching (grep/find/ls)   82.7M   {b}10.4M{rst} 22.4%    903     12k  {c}████{d}············{rst}",
            f" Bash: scripts (python/node/own)  61.1M   {b} 6.3M{rst} 13.5%    459     14k  {c}███{d}·············{rst}",
            f" Edit/Write — changing files      29.9M   {b} 4.5M{rst}  9.8%    646      7k  {c}██{d}··············{rst}",
        ]
        if level == "detailed":
            lines.append(f" Read — reading files             39.2M   {b} 3.7M{rst}  8.0%    878      4k  {c}██{d}··············{rst}")
        lines.append(f" {d}│ {limit_note}{rst}")
        return lines

    if element == "models":
        limit_note = (L("do 5 modeli", "up to 5 models") if level in ("minimal", "normal")
                      else L("do 10 modeli w pełnym zestawieniu tokenów", "up to 10 models with full token breakdown"))
        lines = [
            f" {bc}── {L('MODELE', 'MODELS')} ──{rst}",
            f" {b}{'model':<22}{L('surowe', 'raw'):>8}{L('ważone', 'weighted'):>9}{'%':>6}{L('wywoł.', 'calls'):>7}{L('waga', 'weight'):>7}{rst}",
            f" {col_rule}",
            f" claude-opus-5-5       327.9M   {b}40.1M{rst} 86.3%   2501   x0.8  {c}███████████{d}··{rst}",
            f" claude-sonnet-5-5      78.7M   {b} 6.3M{rst} 13.5%    912   x0.4  {c}██{d}···········{rst}",
            f" claude-haiku-5-5       10.6M   {b} 126k{rst}  0.3%    109  x0.02  {d}·············{rst}",
        ]
        lines.append(f" {d}│ {limit_note}{rst}")
        return lines

    if element == "sessions":
        limit_note = (L("5 najcięższych sesji", "5 heaviest sessions") if level in ("minimal", "normal")
                      else L("10 najcięższych sesji z pełnym podziałem", "10 heaviest sessions in full detail"))
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
        extra = (L(" + trend 6 głównych czynności w czasie", " + trend of top 6 activities over time")
                 if level == "detailed" else "")
        return [
            f" {bc}── {L('RODZAJE TOKENÓW — surowe vs ważone', 'TOKEN TYPES — raw vs weighted')} ──{rst}",
            f" cache read             391.4M   {b}13.9M{rst} 29.9%  {c}████████{d}··················{rst}",
            f" cache write 5 min       16.6M   {b}13.8M{rst} 29.8%  {c}████████{d}··················{rst}",
            f" output (response)        3.0M   {b}10.3M{rst} 22.1%  {c}██████{d}····················{rst}",
            f" {d}│ {L('rozbicie kosztów cache vs wyjście oraz rozkład dzienny/tygodniowy', 'cache vs output breakdown and daily/weekly distribution')}{extra}{rst}",
        ]

    if element == "breakdown":
        extra = (L(" + tabela subagentów wg typu z rozmiarem kontekstu", " + subagents table by type with context size")
                 if level == "detailed" else "")
        return [
            f" {bc}── {L('SESJA GŁÓWNA vs SUBAGENCI & PROJEKTY', 'MAIN vs SUBAGENTS & PROJECTS')} ──{rst}",
            f" " + L("subagenci", "subagents") + f"             246.2M   {b}28.8M{rst} 61.9%    2086  {c}████████████{d}········{rst}",
            f" " + L("sesja główna", "main session") + f"          171.0M   {b}17.7M{rst} 38.1%    1436  {c}████████{d}············{rst}",
            f" AISudokuAndroid        201.3M   {b}24.4M{rst} 52.4%    1891  {c}██████████{d}··········{rst}",
            f" {d}│ {L('udział subagentów oraz podział zużycia wg projektów', 'subagents share and usage split across projects')}{extra}{rst}",
        ]

    if element == "cache":
        extra = (L(" + pojedyncze zdarzenia wygaśnięcia cache i sesje", " + single cache rewrite events and sessions")
                 if level == "detailed" else "")
        calls_word = L("wyw.", "calls")
        wt_word = L("ważonych", "weighted")
        extra_word = L("nadmiaru", "extra")
        gap_word = L("przerwa", "pause")
        return [
            f" {bc}── {L('DŁUGOŚĆ ROZMOWY & WYGASŁY CACHE', 'CONVERSATION LENGTH & EXPIRED CACHE')} ──{rst}",
            f" 100-200k               1546 {calls_word}  {b}23.4M{rst} {wt_word} (50.4%)  {c}█████████{d}·········{rst}",
            f" " + L("wygasły cache", "expired cache") + f"          104 {calls_word}   {b}11.2M{rst} {extra_word}  ({gap_word} > 60 min: 34×)",
            f" {d}│ {L('analiza kosztów długich rozmów, odbudowy cache i powtórnych odczytów', 'cost analysis of long context, cache rewrites and repeated reads')}{extra}{rst}",
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
        """One key of the full-screen editor. Returns 'save', 'quit' or None."""
        self.message = ""
        if key in ("q", "esc", "ctrl-c"):
            if self.dirty and not self._quit_armed and key != "ctrl-c":
                self._quit_armed = True
                self.message = L("niezapisane zmiany: q jeszcze raz = wyjście, enter = zapis",
                                 "unsaved changes: press q again to quit, enter to save")
                return None
            return "quit"
        self._quit_armed = False
        if key in ("enter", "w"):
            return "save"
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
        """One text command of the line-based editor. Returns 'save', 'quit' or None."""
        self.message = ""
        if command == "w":
            return "save"
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
        lines = ["  " + " · ".join(tags)]
        if self.settings.level == "minimal":
            hidden = [e for e in self.settings.elements if e not in MINIMAL_ELEMENTS]
            if hidden:
                lines.append("  " + DIM + L("pominięte na poziomie minimal: ", "left out at minimal level: ")
                             + ", ".join(hidden) + RESET)
        return lines

    def rows(self, width: int) -> List[str]:
        lines = []
        minimal = self.settings.level == "minimal"
        for index, name in enumerate(ELEMENTS):
            is_active = index == self.cursor
            is_on = name in self.settings.elements
            note = ""
            if minimal and name not in MINIMAL_ELEMENTS:
                note = f" {DIM}" + L("(brak w minimal)", "(omitted in minimal)") + RESET

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

    def screen(self, width: int, height: int = 34) -> List[str]:
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

        level_hdr = f" {BOLD}{L('Poziom szczegółowości', 'Detail level')}{RESET}:  {pills_str}   {DIM}(← →){RESET}"
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
    out(L("poziom: ", "level: ") + f"{editor.settings.level}  ({describe_level(editor.settings.level)})")
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
    while True:
        show(editor, out)
        try:
            command = ask("> ").strip()
        except EOFError:
            command = "q"
        result = editor.handle_line(command)
        if editor.message:
            out(editor.message)
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
