"""--md: a Markdown file to hand to Claude for analysis."""
from __future__ import annotations

from typing import List, Optional

from .context import ReportContext
from .daily import DayRow
from .explain import explain_text
from .i18n import L
from .report_text import text_daily, text_diff, text_report
from .stats import Stats


def _block(text: str) -> str:
    return "```text\n" + text.rstrip() + "\n```"


def md_report(stats: Stats, ctx: ReportContext, prev_stats: Optional[Stats],
              daily: Optional[List[DayRow]]) -> str:
    parts = [
        "# " + L("Zużycie tokenów Claude Code — materiał do analizy",
                 "Claude Code token usage — material for analysis"),
        L(f"Okres: **{ctx.label}**. Źródło: lokalne transkrypty Claude Code.",
          f"Period: **{ctx.label}**. Source: local Claude Code transcripts."),
        "## " + L("Zadanie", "Task"),
        L("Przeanalizuj raport poniżej. Wskaż, na co idzie najwięcej tokenów, co jest "
          "marnowane (np. wygasły cache, długie rozmowy bez kompakcji, powtarzane odczyty, "
          "zaszumione wyjście Basha, nieużywane skille) i zaproponuj konkretne, uporządkowane "
          "według oszczędności zmiany w sposobie pracy lub w CLAUDE.md. Opieraj się na liczbach "
          "z raportu; jeśli czegoś w nim brakuje, powiedz czego.",
          "Analyze the report below. Point out what uses the most tokens, what is wasted "
          "(e.g. expired cache, long conversations without compaction, repeated reads, noisy "
          "Bash output, unused skills) and propose concrete changes to the way of working or to "
          "CLAUDE.md, ordered by how much they would save. Base it on the numbers in the report; "
          "if something is missing, say what."),
    ]
    if prev_stats is not None:
        parts += ["## " + L("Porównanie z poprzednim okresem", "Comparison with the previous period"),
                  _block(text_diff(stats, prev_stats, ctx))]
    if daily:
        parts += ["## " + L("Dzień po dniu", "Day by day"), _block(text_daily(daily))]
    parts += ["## " + L("Raport", "Report"), _block(text_report(stats, ctx)),
              "## " + L("Jak czytać liczby", "How to read the numbers"),
              _block(explain_text())]
    return "\n\n".join(parts) + "\n"
