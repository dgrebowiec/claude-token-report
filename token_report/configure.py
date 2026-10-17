"""Interactive configurator: detail level and which elements the report contains.

In a terminal it is a full-screen editor driven by keys (arrows, space, enter). When stdin is
not a terminal (pipes, tests) it falls back to one text command per line.
"""
from __future__ import annotations

import copy
import os
import shutil
import sys
from pathlib import Path
from typing import Callable, List, Optional

from . import settings as settings_module
from .i18n import L
from .settings import ELEMENTS, LEVELS, MINIMAL_ELEMENTS, Settings, describe, describe_level

REVERSE = "\033[7m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def key_help() -> str:
    return L("↑↓ wybór   spacja pokaż/ukryj   ←→ poziom   a wszystko   n nic   r reset   "
             "enter zapisz   q wyjście",
             "↑↓ select   space show/hide   ←→ level   a all   n none   r reset   "
             "enter save   q quit")


def line_help() -> str:
    return L("""polecenia:
  <n>   pokaż lub ukryj element n     l   zmień poziom szczegółowości
  a     wszystkie elementy            n   żaden (zostaje pierwszy)
  r     domyślne                      w   zapisz i wyjdź          q   wyjdź bez zapisu""",
             """commands:
  <n>   show or hide element n        l   cycle detail level
  a     all elements                  n   none (the first one stays)
  r     defaults                      w   save and exit           q   quit without saving""")


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
        self.settings.elements = Settings().elements
        self.cursor = 0
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
            "a": self.select_all, "n": self.select_none, "r": self.reset,
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
        elif command == "r":
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
        lines = ["  " + L("podsumowanie", "summary") + " · " + " · ".join(shown)]
        if self.settings.level == "minimal":
            hidden = [e for e in self.settings.elements if e not in MINIMAL_ELEMENTS]
            if hidden:
                lines.append("  " + L("pominięte na poziomie minimal: ", "left out at the minimal level: ")
                             + ", ".join(hidden))
        return lines

    def rows(self, width: int) -> List[str]:
        lines = []
        minimal = self.settings.level == "minimal"
        for index, name in enumerate(ELEMENTS):
            mark = "x" if name in self.settings.elements else " "
            note = ""
            if minimal and name not in MINIMAL_ELEMENTS:
                note = "  " + L("(nie na poziomie minimal)", "(not at the minimal level)")
            row = f" {index + 1:>2}. [{mark}] {name:<10} {describe(name)}{note}"
            row = row.ljust(min(max(width - 2, 40), 78))
            lines.append(row)
        return lines

    def screen(self, width: int) -> List[str]:
        s = self.settings
        title = f"{BOLD}claude-token-report --configure{RESET}"
        if self.dirty:
            title += f"  {DIM}({L('niezapisane zmiany', 'unsaved changes')}){RESET}"
        lines = [title, "", f"{BOLD}{L('Elementy raportu', 'Report elements')}{RESET}  "
                            f"{DIM}{L('spacja: pokaż/ukryj', 'space: show/hide')}{RESET}"]
        for index, row in enumerate(self.rows(width)):
            lines.append(f" {REVERSE}{row}{RESET}" if index == self.cursor else f" {row}")
        lines += [
            "",
            f"{BOLD}{L('Poziom', 'Level')}{RESET}  ◀ {s.level} ▶   {DIM}{' / '.join(LEVELS)}{RESET}",
            f"         {DIM}{describe_level(s.level)}{RESET}",
            "",
            f"{BOLD}{L('Raport będzie zawierał', 'The report will contain')}{RESET}",
            *self.preview(),
            "",
            f"{DIM}{key_help()}{RESET}",
        ]
        if self.message:
            lines.append(f"{BOLD}{self.message}{RESET}")
        return lines


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
                term.draw(editor.screen(shutil.get_terminal_size().columns))
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
        out(row.rstrip())
    out("")
    out(L("raport będzie zawierał:", "the report will contain:"))
    for line in editor.preview():
        out(line)
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
