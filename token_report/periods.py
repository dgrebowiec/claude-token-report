"""Time windows: parsing dates from the command line and naming the chosen period."""
from __future__ import annotations

import argparse
import datetime
from dataclasses import dataclass
from typing import Optional

from .i18n import L, weekday


@dataclass
class Window:
    start: Optional[datetime.datetime]  # None = all history
    end: datetime.datetime
    first: Optional[datetime.date]  # first calendar day
    last: datetime.date  # last calendar day
    last_n: Optional[int] = None  # "last N days"
    rolling: Optional[float] = None  # N × 24 h instead of calendar days

    @property
    def has_base_day(self) -> bool:
        """--daily can show the day before the window as a baseline"""
        return self.start is not None and not self.rolling


def midnight(d: datetime.date) -> datetime.datetime:
    """local midnight at the start of calendar day d"""
    return datetime.datetime.combine(d, datetime.time(0)).astimezone()


def parse_day(s: str) -> datetime.date:
    """YYYY-MM-DD, DD.MM.YYYY, MM-DD (this year), today/yesterday — an argparse type"""
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


def picked_options(args: argparse.Namespace) -> list:
    """the time-window options given on the command line"""
    return [n for n, v in (("--days", args.days is not None), ("--date", args.date),
                           ("--from", args.from_), ("--today", args.today),
                           ("--yesterday", args.yesterday), ("--all", args.all)) if v]


def resolve_window(args: argparse.Namespace) -> Window:
    """the window chosen by --days/--date/--from/--to/--today/--yesterday/--all;
    raises ValueError with a user-facing message for invalid combinations"""
    now = datetime.datetime.now().astimezone()
    today = now.date()
    picked = picked_options(args)
    if len(picked) > 1:
        raise ValueError(L("podaj okres tylko jednym sposobem, a podano: ",
                           "set the period one way only, got: ") + " ".join(picked))
    if args.to and not args.from_:
        raise ValueError(L("--to wymaga --from", "--to requires --from"))
    if args.all:
        return Window(start=None, end=now, first=None, last=today)

    if args.date:
        d1 = d2 = args.date
    elif args.from_:
        d1, d2 = args.from_, (args.to or today)
    elif args.today:
        d1 = d2 = today
    elif args.yesterday:
        d1 = d2 = today - datetime.timedelta(days=1)
    else:
        days = 7 if args.days is None else args.days
        if days <= 0:
            raise ValueError(L("--days musi być > 0", "--days must be > 0"))
        if args.rolling or days != int(days):
            start = now - datetime.timedelta(days=days)
            return Window(start=start, end=now, first=start.date(), last=today, rolling=days)
        return _calendar_window(today - datetime.timedelta(days=int(days) - 1), today, now,
                                last_n=int(days))
    return _calendar_window(d1, d2, now)


def _calendar_window(d1: datetime.date, d2: datetime.date, now: datetime.datetime,
                     last_n: Optional[int] = None) -> Window:
    today = now.date()
    if d1 > d2:
        raise ValueError(L(f"początek {d1} jest po końcu {d2}", f"start {d1} is after end {d2}"))
    if d1 > today:
        raise ValueError(L(f"{d1} jest w przyszłości", f"{d1} is in the future"))
    d2 = min(d2, today)
    return Window(start=midnight(d1), end=min(midnight(d2 + datetime.timedelta(days=1)), now),
                  first=d1, last=d2, last_n=last_n)


def previous_window_start(window: Window) -> Optional[datetime.datetime]:
    """start of the window of the same length right before this one (for --diff)"""
    if window.start is None:
        return None
    if window.rolling:
        return window.start - (window.end - window.start)
    n = (window.last - window.first).days + 1
    return midnight(window.first - datetime.timedelta(days=n))


def last_local_day(end: datetime.datetime) -> datetime.date:
    e = end.astimezone()
    return (e - datetime.timedelta(seconds=1)).date() if e.time() == datetime.time(0) else e.date()


def period_label(start: Optional[datetime.datetime], end: datetime.datetime,
                 last_n: Optional[int] = None, rolling: Optional[float] = None,
                 session: Optional[str] = None) -> str:
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
            return L("dzisiaj", "today") + f" ({s}, {weekday(s)})"
        if s == today - datetime.timedelta(days=1):
            return L("wczoraj", "yesterday") + f" ({s}, {weekday(s)})"
        return f"{s} ({weekday(s)})"
    n = (e - s).days + 1
    if last_n and e == today:
        return L(f"ostatnie {n} dni", f"last {n} days") + f" ({s}..{e})"
    return f"{s}..{e} (" + L(f"{n} dni", f"{n} days") + ")"
