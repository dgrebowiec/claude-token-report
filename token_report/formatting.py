"""Small number/text formatters shared by the text and HTML reports."""
from __future__ import annotations

from typing import Optional

from .i18n import L


def fmt_tok(n: float) -> str:
    n = float(n)
    if abs(n) >= 1e9:
        return f"{n / 1e9:.2f}B"
    if abs(n) >= 1e6:
        return f"{n / 1e6:.1f}M"
    if abs(n) >= 1e3:
        return f"{n / 1e3:.0f}k"
    return f"{n:.0f}"


def fmt_int(n: float) -> str:
    return f"{int(n):,}".replace(",", " ")


def pct(a: float, b: float) -> float:
    return 100.0 * a / b if b else 0.0


def short(name: str, width: int) -> str:
    """shortens a path-like name from the left, keeping the last component readable"""
    if len(name) <= width:
        return name
    return "…" + name[-(width - 1):]


def bar(frac: float, width: int = 24) -> str:
    full = int(round(max(0.0, min(1.0, frac)) * width))
    return "#" * full + "." * (width - full)


def fmt_change(cur: float, prev: float) -> str:
    if prev:
        return f"{pct(cur - prev, prev):+.0f}%"
    return L("nowe", "new") if cur else "0%"


def fmt_delta(d: float) -> str:
    return ("+" if d >= 0 else "-") + fmt_tok(abs(d))


def arrow(cur: float, prev: Optional[float]) -> str:
    """▲ / ▼ / = (within ±1%) compared with the previous value"""
    if prev is None:
        return " "
    if abs(cur - prev) <= 0.01 * max(abs(prev), 1e-9) or (not cur and not prev):
        return "="
    return "▲" if cur > prev else "▼"


def side_name(key: str) -> str:
    return L("sesja główna", "main session") if key == "main" else L("subagenci", "subagents")
