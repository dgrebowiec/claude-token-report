"""Suggestions computed from the numbers ("what you could improve")."""
from __future__ import annotations

from typing import List

from .classify import EXPLORE_KEYS
from .formatting import pct
from .i18n import L
from .pricing import model_weight
from .stats import Stats, ctx_growth

# thresholds (percent of weighted tokens) above which a tip is shown
LONG_CTX_PCT = 20
REBUILD_WASTE_PCT = 3
EXPLORE_PCT = 25
REREAD_MIN_READS, REREAD_PCT = 20, 20
OUTPUT_PCT = 35
TOP_MODEL_PCT, EXPENSIVE_MODEL_WEIGHT = 80, 0.8


def tips(stats: Stats) -> List[str]:
    out = []
    total = stats.weighted or 1e-9

    long_ctx = pct(stats.long_context_weighted(), total)
    if long_ctx > LONG_CTX_PCT:
        growth = ctx_growth(stats)
        ratio = f" (~{growth[0] / growth[1]:.1f}x)" if growth else ""
        out.append(L(
            f"Długie rozmowy: wywołania przy kontekście powyżej 200k to {long_ctx:.0f}% "
            f"zużycia, a każde takie wywołanie obciąża limit mocniej niż przy krótkiej rozmowie"
            f"{ratio}. Nowe, niezwiązane zadanie zaczynaj od /clear, a długą pracę skracaj "
            f"przez /compact.",
            f"Long conversations: calls with more than 200k of context are {long_ctx:.0f}% "
            f"of usage, and each of them weighs more than a call in a short conversation"
            f"{ratio}. Start unrelated tasks with /clear and shorten long work with /compact."))

    rb = stats.rebuilds
    if rb.count and pct(rb.waste, total) > REBUILD_WASTE_PCT:
        out.append(L(
            f"Wygasły cache: {rb.count} razy cała rozmowa była zapisywana od nowa (zwykle po "
            f"przerwie dłuższej niż 5 minut). To {pct(rb.waste, total):.0f}% zużycia, którego "
            f"dało się uniknąć. Przed dłuższą przerwą dokończ wątek, a po powrocie do starej "
            f"rozmowy rozważ /compact albo /clear.",
            f"Expired cache: {rb.count} times the whole conversation was written again (usually "
            f"after a break of more than 5 minutes). That is {pct(rb.waste, total):.0f}% of "
            f"usage that could have been avoided. Finish the thread before a long break, and "
            f"consider /compact or /clear when you return to an old conversation."))

    explore = sum(stats.by_activity[k].weighted for k in EXPLORE_KEYS if k in stats.by_activity)
    if pct(explore, total) > EXPLORE_PCT:
        out.append(L(
            f"Szukanie i czytanie kodu to {pct(explore, total):.0f}% zużycia. Wskazuj w prośbie "
            f"konkretne pliki lub funkcje, opisz strukturę projektu w CLAUDE.md, a szerokie "
            f"przeszukiwanie zlecaj subagentowi (np. „użyj subagenta, żeby znalazł…”). Jego "
            f"robocze odczyty nie trafiają do głównej rozmowy, wraca tylko wynik.",
            f"Searching and reading code is {pct(explore, total):.0f}% of usage. Name concrete "
            f"files or functions in your request, describe the project layout in CLAUDE.md, "
            f"and hand broad searches to a subagent (e.g. \"use a subagent to find…\"). Its "
            f"working reads stay out of the main conversation; only the result comes back."))

    rr = stats.rereads
    if rr.reads >= REREAD_MIN_READS and pct(rr.repeats, rr.reads) > REREAD_PCT:
        out.append(L(
            f"{pct(rr.repeats, rr.reads):.0f}% odczytów plików dotyczyło fragmentów, które "
            f"już były w rozmowie (bez zmian pomiędzy).",
            f"{pct(rr.repeats, rr.reads):.0f}% of file reads were for parts already in the "
            f"conversation (unchanged in between)."))

    output_share = pct(stats.weighted_by_type["output"], total)
    if output_share > OUTPUT_PCT:
        out.append(L(
            f"Odpowiedzi modelu (tekst, kod, myślenie) to {output_share:.0f}% zużycia. Niższy "
            f"poziom effort albo prośba o zwięzłe odpowiedzi to zmniejszy.",
            f"Model output (text, code, thinking) is {output_share:.0f}% of usage. A lower effort "
            f"level or asking for concise answers reduces it."))

    if stats.by_model:
        top_model, top = max(stats.by_model.items(), key=lambda kv: kv[1].weighted)
        share = pct(top.weighted, total)
        if model_weight(top_model) >= EXPENSIVE_MODEL_WEIGHT and share > TOP_MODEL_PCT:
            out.append(L(
                f"{share:.0f}% zużycia to {top_model}. Tańszy model (np. Sonnet) "
                f"obciąża limit kilka razy słabiej, więc do prostych zadań warto go wybrać "
                f"przez /model.",
                f"{share:.0f}% of usage is {top_model}. A cheaper model (e.g. "
                f"Sonnet) uses the limit several times slower, so pick it via /model for simple "
                f"tasks."))

    if not out:
        out.append(L("Nic nie odstaje — rozkład zużycia wygląda zdrowo.",
                     "Nothing stands out — the usage distribution looks healthy."))
    return out
