"""The terminal report."""
from __future__ import annotations

import datetime
import textwrap
from typing import Callable, List, Mapping, Optional, Tuple

from .classify import activity_name
from .context import TOP_ROWS, ReportContext
from .daily import DayRow, daily_summary
from .formatting import (arrow, bar, fmt_change, fmt_delta, fmt_int, fmt_tok, pct, short,
                         side_name)
from .i18n import L, weekday
from .naming import Namer
from .pricing import TOKEN_TYPES, TYPE_WEIGHTS, model_weight, type_name, unknown_models
from .stats import CTX_BUCKETS, FEW_CALLS, Bucket, Stats, cache_hit, ctx_growth, timeline_kind
from .tips import tips
from .transcripts import TranscriptFile, load

WIDTH = 92


class _Lines:
    """collects report lines"""

    def __init__(self) -> None:
        self._lines: List[str] = []

    def add(self, text: str = "") -> None:
        self._lines.append(text)

    def rule(self) -> None:
        self.add("=" * WIDTH)

    def header(self, title: str) -> None:
        self.add()
        self.add(f"-- {title} " + "-" * max(0, WIDTH - len(title) - 4))

    def note(self, text: str, indent: int = 3) -> None:
        for line in textwrap.wrap(text, WIDTH - indent - 1):
            self.add(" " * indent + line)

    def bullet(self, text: str) -> None:
        lines = textwrap.wrap(text, WIDTH - 4)
        self.add(" * " + lines[0])
        for line in lines[1:]:
            self.add("   " + line)

    def render(self) -> str:
        return "\n".join(self._lines)


def _breakdown(out: _Lines, title: str, groups: Mapping[str, Bucket], total: float, top: int,
               label: str, names: Callable[[str], str] = str, desc: Optional[str] = None,
               left: bool = False, n_label: Optional[str] = None,
               extra: Optional[Tuple[str, Callable[[str], str]]] = None) -> None:
    """a table of groups sorted by weighted tokens, with a bar per row"""
    out.header(title)
    if desc:
        out.note(desc)
    total = total or 1e-9
    n_label = n_label or L("wywoł.", "calls")
    extra_head = f"{extra[0]:>7}" if extra else ""
    out.add(f" {label:<32}{L('surowe', 'raw'):>9}{L('ważone', 'weighted'):>10}{'%':>7}"
            f"{n_label:>8}{L('śr./szt.', 'avg'):>9}{extra_head}  ")
    items = sorted(groups.items(), key=lambda kv: -kv[1].weighted)
    for key, b in items[:top]:
        name = short(str(names(key)), 31) if left else str(names(key))[:31]
        extra_val = f"{extra[1](key):>7}" if extra else ""
        out.add(f" {name:<32}{fmt_tok(b.raw):>9}{fmt_tok(b.weighted):>10}"
                f"{pct(b.weighted, total):>6.1f}%{b.calls:>8}"
                f"{fmt_tok(b.weighted / b.calls if b.calls else 0):>9}{extra_val}  "
                f"{bar(b.weighted / total, 20)}")
    rest = items[top:]
    if rest:
        rest_w = sum(b.weighted for _, b in rest)
        rest_raw = sum(b.raw for _, b in rest)
        out.add(f" {L(f'(pozostałe: {len(rest)})', f'(other: {len(rest)})'):<32}"
                f"{fmt_tok(rest_raw):>9}{fmt_tok(rest_w):>10}{pct(rest_w, total):>6.1f}%")


# --------------------------------------------------------------------------- main report

def _summary(out: _Lines, stats: Stats) -> None:
    raw = stats.raw
    hit = cache_hit(stats.tokens)

    def item(name: str, value: str, text: str) -> None:
        out.add(f" {name:<26}{value:>12}   {text}")

    item(L("wywołania modelu", "model calls"), fmt_int(stats.n_calls),
         L(f"{stats.n_sessions} rozmów, {stats.n_subagents} subagentów",
           f"{stats.n_sessions} conversations, {stats.n_subagents} subagents"))
    item(L("tokeny surowe", "raw tokens"), fmt_tok(raw),
         L("wszystkie tokeny liczone po równo", "all tokens counted equally"))
    item(L("tokeny ważone", "weighted tokens"), fmt_tok(stats.weighted),
         L("główna miara — obciążenie limitu (--explain)",
           "main measure — load on your limit (--explain)"))
    if hit is not None:
        item(L("trafienia w cache", "cache hit rate"), f"{hit:.1f}%",
             L("powyżej ~90% to dobry wynik", "above ~90% is good"))
    if stats.n_calls:
        ctx_tokens = raw - stats.tokens["output"]
        item(L("średnio na wywołanie", "average per call"), fmt_tok(stats.weighted / stats.n_calls),
             L(f"ważonych; śr. kontekst {fmt_tok(ctx_tokens / stats.n_calls)}",
               f"weighted; avg context {fmt_tok(ctx_tokens / stats.n_calls)}"))


def _token_types(out: _Lines, stats: Stats) -> None:
    out.header(L("RODZAJE TOKENÓW — surowe vs ważone", "TOKEN TYPES — raw vs weighted"))
    tok, w_t = stats.tokens, stats.weighted_by_type
    raw = stats.raw or 1
    total = stats.weighted or 1e-9
    out.add(f" {L('rodzaj tokenu', 'token type'):<26}{L('surowe', 'raw'):>9}{'%':>7}"
            f"{L('waga', 'weight'):>8}{L('ważone', 'weighted'):>10}{'%':>7}")
    for t in TOKEN_TYPES:
        if t == "cache_write_1h" and not tok[t]:
            continue
        out.add(f" {type_name(t):<26}{fmt_tok(tok[t]):>9}{pct(tok[t], raw):>6.1f}%"
                f"{'x' + format(TYPE_WEIGHTS[t], 'g'):>8}{fmt_tok(w_t[t]):>10}"
                f"{pct(w_t[t], total):>6.1f}%")
    out.add(f" {L('RAZEM', 'TOTAL'):<26}{fmt_tok(raw):>9}{'':>7}{'':>8}{fmt_tok(stats.weighted):>10}")
    out.note(L("Ważone uwzględniają też wagę modelu (tabela MODELE).",
               "Weighted also includes the model's weight (see MODELS)."))


def _groups(out: _Lines, stats: Stats, ctx: ReportContext) -> None:
    total = stats.weighted
    _breakdown(out, L("NA CO IDĄ TOKENY", "WHERE THE TOKENS GO"), stats.by_activity, total,
               TOP_ROWS + 6, L("czynność", "activity"), activity_name, n_label=L("użyć", "uses"),
               desc=L("Każde wywołanie jest przypisane do narzędzia, którego model w nim użył (przy "
                      "kilku narzędziach naraz — po równo). „Bez narzędzia” = model odpowiedział Ci "
                      "tekstem. „śr./szt.” = ile średnio waży jedno użycie.",
                      "Each call is assigned to the tool the model used in it (split evenly if it "
                      "used several). 'No tool' = the model replied to you with text. 'avg' = the "
                      "average weight of one use."))
    _breakdown(out, L("MODELE", "MODELS"), stats.by_model, total, TOP_ROWS, "model",
               extra=(L("waga", "weight"), lambda k: "x" + format(model_weight(k), ".2g")),
               desc=L("„waga” = jak mocno model obciąża limit względem Opus 5 (x1). Ta sama praca "
                      "na modelu z wagą x0.4 zużywa 2.5 raza mniej.",
                      "'weight' = how heavily the model uses the limit relative to Opus 5 (x1). "
                      "The same work on a x0.4 model uses 2.5 times less."))
    if unknown_models():
        out.note(L("nieznane modele liczone z wagą Opus 5: ", "unknown models weighted as Opus 5: ")
                 + ", ".join(unknown_models()))
    _breakdown(out, L("SESJA GŁÓWNA vs SUBAGENCI", "MAIN SESSION vs SUBAGENTS"), stats.by_side,
               total, 2, L("gdzie", "where"), side_name,
               desc=L("Subagenci to osobne instancje Claude uruchamiane narzędziem Agent. Mają "
                      "własny kontekst, więc ich praca nie wydłuża głównej rozmowy.",
                      "Subagents are separate Claude instances started with the Agent tool. They "
                      "have their own context, so their work doesn't grow the main conversation."))
    if stats.by_agent_type:
        _breakdown(out, L("SUBAGENCI WG TYPU", "SUBAGENTS BY TYPE"), stats.by_agent_type, total,
                   TOP_ROWS, L("typ subagenta", "subagent type"))
    if not ctx.session:
        _breakdown(out, L("PROJEKTY (katalog roboczy)", "PROJECTS (working directory)"),
                   stats.by_project, total, TOP_ROWS, L("projekt", "project"), left=True)


def _context_length(out: _Lines, stats: Stats) -> None:
    total = stats.weighted or 1e-9
    out.header(L("DŁUGOŚĆ ROZMOWY — ile waży wywołanie przy danym rozmiarze kontekstu",
                 "CONVERSATION LENGTH — weight of a call by context size"))
    out.note(L(
        "Kontekst = cała rozmowa, którą model czyta przy danym wywołaniu. Rośnie z każdym "
        "krokiem, a model czyta ją za każdym razem od nowa, więc im dłuższa rozmowa, tym więcej "
        "waży każde kolejne wywołanie.",
        "Context = the whole conversation the model reads in a call. It grows with every step "
        "and the model re-reads it every time, so the longer the conversation, the more each "
        "further call weighs."))
    out.add(f" {L('kontekst', 'context'):<14}{L('wywoł.', 'calls'):>8}{L('surowe', 'raw'):>10}"
            f"{L('ważone', 'weighted'):>10}{'%':>7}{L('śr./wywoł.', 'avg/call'):>12}{L('w tym czytanie', 'of it reading'):>16}")
    for _, _, name in CTX_BUCKETS:
        b = stats.by_context[name]
        if not b.calls:
            continue
        few = L("  (mało danych)", "  (few calls)") if b.calls < FEW_CALLS else ""
        out.add(f" {name:<14}{b.calls:>8}{fmt_tok(b.raw):>10}{fmt_tok(b.weighted):>10}{pct(b.weighted, total):>6.1f}%"
                f"{fmt_tok(b.weighted / b.calls):>12}{fmt_tok(b.reading / b.calls):>16}{few}")
    growth = ctx_growth(stats)
    if growth:
        avg, base, name = growth
        out.note(L(f"Wywołanie przy kontekście {name} waży średnio {avg / base:.1f}x tyle co "
                   f"przy 50-100k. „w tym czytanie” = część, która idzie tylko na ponowne "
                   f"przeczytanie rozmowy. Grupa „< 50k” to często początki rozmów, które "
                   f"najpierw zapisują wszystko do cache.",
                   f"A call at {name} context weighs {avg / base:.1f}x as much as one at 50-100k "
                   f"on average. 'of it reading' = the part spent only on re-reading the "
                   f"conversation. The '< 50k' group is often conversation starts, which first "
                   f"write everything to the cache."))


def _over_time(out: _Lines, stats: Stats) -> None:
    kind = timeline_kind(stats)
    periods = stats.periods(kind)
    if not periods:
        return
    total = stats.weighted or 1e-9
    out.header(L("W CZASIE — ", "OVER TIME — ")
               + (L("tygodnie", "weeks") if kind == "week" else L("dni", "days")))
    peak = max(p.weighted for _, p in periods) or 1e-9
    out.add(f" {L('okres', 'period'):<26}{L('surowe', 'raw'):>9}{L('ważone', 'weighted'):>10}"
            f"{'%':>7}{L('wywoł.', 'calls'):>8}  ")
    for key, p in periods:
        out.add(f" {key:<26}{fmt_tok(p.raw):>9}{fmt_tok(p.weighted):>10}"
                f"{pct(p.weighted, total):>6.1f}%{p.calls:>8}  {bar(p.weighted / peak, 26)}")
    if len(periods) <= 1:
        return
    top_activities = [k for k, _ in sorted(stats.by_activity.items(),
                                           key=lambda kv: -kv[1].weighted)[:6]]
    view = periods[-8:]
    out.add()
    out.add(" " + L("trend głównych czynności (tokeny ważone):",
                    "trend of top activities (weighted tokens):"))
    heads = [(key[5:10] if kind == "day" else key[5:8]) for key, _ in view]
    out.add(f" {'':<40}" + "".join(f"{h:>8}" for h in heads))
    for activity in top_activities:
        out.add(f" {activity_name(activity)[:39]:<40}"
                + "".join(f"{fmt_tok(p.activities[activity]):>8}" for _, p in view))


def _heaviest_sessions(out: _Lines, stats: Stats, ctx: ReportContext) -> None:
    total = stats.weighted or 1e-9
    out.header(L("NAJCIĘŻSZE ROZMOWY", "HEAVIEST CONVERSATIONS"))
    out.add(f" {L('sesja', 'session'):<10}{L('projekt', 'project'):<22}{L('surowe', 'raw'):>8}"
            f"{L('ważone', 'weighted'):>10}"
            f"{'%':>7}{L('wywoł.', 'calls'):>7}{L('maks.ctx', 'max ctx'):>9}"
            f"{L('subag.', 'sub'):>7}  {L('temat', 'topic')}")
    for key, s in sorted(stats.by_session.items(), key=lambda kv: -kv[1].weighted)[:TOP_ROWS]:
        meta = ctx.sessions.get(key)
        project = ctx.namer.project(meta, key[0])
        topic = ctx.namer.topic(meta.topic if meta else None)
        out.add(f" {key[1][:8]:<10}{short(project, 21):<22}{fmt_tok(s.raw):>8}{fmt_tok(s.weighted):>10}"
                f"{pct(s.weighted, total):>6.1f}%{s.calls:>7}{fmt_tok(s.max_context):>9}"
                f"{pct(s.subagent_weighted, s.weighted):>6.0f}%  {topic[:30]}")
    out.note(L("„maks.ctx” = do jakiego rozmiaru urosła rozmowa; „subag.” = jaka część "
               "zużycia tej sesji przypadła na subagentów. Szczegóły jednej sesji: "
               "--session <id>",
               "'max ctx' = how large the conversation grew; 'sub' = the share of this "
               "session's usage spent by subagents. One session in detail: --session <id>"))


def _session_phases(out: _Lines, ctx: ReportContext) -> None:
    meta = ctx.sessions.get(ctx.session_key)
    out.header(L("FAZY SESJI — zużycie między kolejnymi prośbami",
                 "SESSION PHASES — usage between requests"))
    prompts = sorted(meta.prompts if meta else [], key=lambda p: p.time)
    for i, prompt in enumerate(prompts):
        until = prompts[i + 1].time if i + 1 < len(prompts) else None
        calls = [c for c in ctx.calls if c.time >= prompt.time and (until is None or c.time < until)]
        weighted = sum(c.weighted for c in calls)
        raw = sum(c.raw for c in calls)
        max_ctx = max((c.context for c in calls if not c.is_subagent), default=0)
        tag = L("powiad.", "notif.") if prompt.kind == "notif" else L("prośba", "request")
        out.add(f" {prompt.time.astimezone():%m-%d %H:%M}  {tag:<8}{len(calls):>5} "
                f"{L('wyw.', 'calls')}{fmt_tok(raw):>8} {L('sur.', 'raw')}{fmt_tok(weighted):>7} "
                f"{L('waż.', 'wt.')}  ctx {fmt_tok(max_ctx):>5}  {ctx.namer.topic(prompt.text)[:30]}")


def _expired_cache(out: _Lines, stats: Stats) -> None:
    total = stats.weighted or 1e-9
    rb = stats.rebuilds
    out.header(L("WYGASŁY CACHE — rozmowa zapisana od nowa",
                 "EXPIRED CACHE — conversation written again"))
    out.note(L(
        "Cache trzyma rozmowę przez 5 minut (czasem godzinę) od ostatniego użycia. Po dłuższej "
        "przerwie model musi zapisać całą rozmowę od nowa (waga x1.25) zamiast ją tanio "
        "odczytać (x0.1).",
        "The cache keeps the conversation for 5 minutes (sometimes an hour) after its last use. "
        "After a longer break the model has to write the whole conversation again (weight "
        "x1.25) instead of reading it cheaply (x0.1)."))
    out.add(" " + L(f"takich wywołań: {rb.count}   nadmiarowe zużycie: {fmt_tok(rb.waste)} "
                    f"({pct(rb.waste, total):.1f}% całości)",
                    f"such calls: {rb.count}   extra usage: {fmt_tok(rb.waste)} "
                    f"({pct(rb.waste, total):.1f}% of the total)"))
    for e in rb.top:
        out.add(f"    {e.time.astimezone():%Y-%m-%d %H:%M}  {e.file_key[1][:8]}  "
                f"ctx {fmt_tok(e.context):>5}  "
                + L(f"przerwa {e.gap_minutes:>4.0f} min  nadmiar {fmt_tok(e.waste)}",
                    f"gap {e.gap_minutes:>4.0f} min  extra {fmt_tok(e.waste)}"))


def _rereads(out: _Lines, stats: Stats) -> None:
    rr = stats.rereads
    if not rr.reads:
        return
    out.header(L("POWTÓRNE ODCZYTY PLIKÓW (narzędzie Read)", "REPEATED FILE READS (Read tool)"))
    out.add(" " + L(f"odczytów: {rr.reads}, z tego fragment już był w rozmowie: {rr.repeats} "
                    f"({pct(rr.repeats, rr.reads):.0f}%)",
                    f"reads: {rr.reads}, part already in the conversation: {rr.repeats} "
                    f"({pct(rr.repeats, rr.reads):.0f}%)"))
    for name, n in rr.files.most_common(6):
        out.add(f"    {name[:50]:<52}+{n}")


def text_report(stats: Stats, ctx: ReportContext) -> str:
    out = _Lines()
    out.rule()
    out.add(" " + L("ZUŻYCIE TOKENÓW CLAUDE CODE", "CLAUDE CODE TOKEN USAGE") + " — " + ctx.label)
    out.add(" " + L("źródło: lokalne transkrypty ", "source: local transcripts ") + ctx.root_display
            + L("  (raport zużywa 0 tokenów)", "  (this report uses 0 tokens)"))
    out.rule()
    _summary(out, stats)
    _token_types(out, stats)
    _groups(out, stats, ctx)
    _context_length(out, stats)
    _over_time(out, stats)
    if ctx.session:
        _session_phases(out, ctx)
    else:
        _heaviest_sessions(out, stats, ctx)
    _expired_cache(out, stats)
    _rereads(out, stats)
    out.header(L("CO MOŻNA POPRAWIĆ", "WHAT YOU COULD IMPROVE"))
    for tip in tips(stats):
        out.bullet(tip)
    out.add()
    out.add(" " + L("Pełne wyjaśnienie tokenów surowych i ważonych: --explain",
                    "Full explanation of raw and weighted tokens: --explain"))
    out.rule()
    return out.render()


# --------------------------------------------------------------------------- --diff

def _weighted(groups: Mapping[str, Bucket], key: str) -> float:
    return groups[key].weighted if key in groups else 0.0


def _compare_groups(out: _Lines, title: str, cur: Mapping[str, Bucket],
                    prev: Mapping[str, Bucket], names: Callable[[str], str] = str,
                    top: int = 12) -> None:
    out.header(title)
    out.add(f" {'':<38}{L('teraz', 'now'):>10}{L('wcześniej', 'before'):>11}"
            f"{L('różnica', 'diff'):>10}{L('zmiana', 'change'):>9}")
    keys = sorted(set(cur) | set(prev), key=lambda k: -_weighted(cur, k) - _weighted(prev, k))
    for key in keys[:top]:
        a, b = _weighted(cur, key), _weighted(prev, key)
        out.add(f" {str(names(key))[:37]:<38}{fmt_tok(a):>10}{fmt_tok(b):>11}"
                f"{fmt_delta(a - b):>10}{fmt_change(a, b):>9}")


def text_diff(cur: Stats, prev: Stats, ctx: ReportContext) -> str:
    out = _Lines()
    out.rule()
    out.add(" " + L("PORÓWNANIE", "COMPARISON") + f": {ctx.label}  vs  {ctx.prev_label}")
    out.rule()
    out.add(f" {L('wskaźnik', 'metric'):<30}{L('teraz', 'now'):>12}{L('wcześniej', 'before'):>12}"
            f"{L('zmiana', 'change'):>10}")

    def row(name: str, a: float, b: float, fmt: Callable[[float], str]) -> None:
        out.add(f" {name:<30}{fmt(a):>12}{fmt(b):>12}{fmt_change(a, b):>10}")

    row(L("wywołania modelu", "model calls"), cur.n_calls, prev.n_calls, fmt_int)
    row(L("tokeny surowe", "raw tokens"), cur.raw, prev.raw, fmt_tok)
    row(L("tokeny ważone", "weighted tokens"), cur.weighted, prev.weighted, fmt_tok)
    for t in TOKEN_TYPES:
        if cur.weighted_by_type[t] or prev.weighted_by_type[t]:
            row("  " + type_name(t), cur.weighted_by_type[t], prev.weighted_by_type[t], fmt_tok)
    row(L("średnio na wywołanie", "average per call"), cur.weighted / max(cur.n_calls, 1),
        prev.weighted / max(prev.n_calls, 1), fmt_tok)
    hit_cur, hit_prev = cache_hit(cur.tokens) or 0, cache_hit(prev.tokens) or 0
    out.add(f" {L('trafienia w cache', 'cache hit rate'):<30}{hit_cur:>11.1f}%{hit_prev:>11.1f}%"
            f"{hit_cur - hit_prev:>+8.1f}pp")

    _compare_groups(out, L("NA CO IDĄ TOKENY (ważone)", "WHERE THE TOKENS GO (weighted)"),
                    cur.by_activity, prev.by_activity, activity_name)
    _compare_groups(out, L("MODELE (ważone)", "MODELS (weighted)"), cur.by_model, prev.by_model)
    _compare_groups(out, L("PROJEKTY (ważone)", "PROJECTS (weighted)"), cur.by_project,
                    prev.by_project, lambda k: short(k, 37))
    long_cur, long_prev = cur.long_context_weighted(), prev.long_context_weighted()
    waste_cur, waste_prev = cur.rebuilds.waste, prev.rebuilds.waste
    out.header(L("WNIOSKI", "TAKEAWAYS"))
    out.add(" * " + L(f"długie rozmowy (kontekst > 200k): {pct(long_cur, cur.weighted):.0f}% zużycia "
                      f"(wcześniej {pct(long_prev, prev.weighted):.0f}%)",
                      f"long conversations (context > 200k): {pct(long_cur, cur.weighted):.0f}% "
                      f"of usage (before {pct(long_prev, prev.weighted):.0f}%)"))
    out.add(" * " + L(f"nadmiar przez wygasły cache: {pct(waste_cur, cur.weighted):.1f}% "
                      f"(wcześniej {pct(waste_prev, prev.weighted):.1f}%)",
                      f"extra from expired cache: {pct(waste_cur, cur.weighted):.1f}% "
                      f"(before {pct(waste_prev, prev.weighted):.1f}%)"))
    out.rule()
    return out.render()


# --------------------------------------------------------------------------- --daily

def text_daily(rows: List[DayRow]) -> str:
    out = _Lines()
    out.header(L("DZIEŃ PO DNIU — zmiana względem poprzedniego dnia",
                 "DAY BY DAY — change vs the previous day"))
    out.add(f" {L('dzień', 'day'):<17}{L('surowe', 'raw'):>9}{L('ważone', 'weighted'):>11}"
            f"{L('zmiana', 'change'):>10}{'%':>7}"
            f"{L('wywoł.', 'calls'):>8}{'cache':>7}{L('śr./wyw.', 'avg/call'):>10}  "
            f"{L('największa zmiana', 'biggest change')}")
    for r in rows:
        day, prev = r.day, r.prev
        name = f"{r.date:%m-%d} {weekday(r.date)}" + (L(" (baza)", " (base)") if r.is_base else "")
        hit = f"{r.cache_hit:.0f}%" if r.cache_hit is not None else "-"
        per_call = fmt_tok(r.per_call) if r.per_call is not None else "-"
        if prev is None or r.is_base:
            out.add(f" {name:<17}{fmt_tok(day.raw):>9}{fmt_tok(day.weighted):>11}{'':>10}{'':>7}{day.calls:>8}"
                    f"{hit:>7}{per_call:>10}")
            continue
        driver = ""
        if r.driver and abs(r.driver[1]) >= 1:
            driver = f"{fmt_delta(r.driver[1])} {activity_name(r.driver[0])}"
        out.add(f" {name:<17}{fmt_tok(day.raw):>9}{arrow(day.weighted, prev.weighted):>2}"
                f"{fmt_tok(day.weighted):>9}"
                f"{fmt_delta(day.weighted - prev.weighted):>10}"
                f"{fmt_change(day.weighted, prev.weighted):>7}{day.calls:>8}{hit:>7}"
                f"{per_call:>10}  {driver[:40]}")
    summary = daily_summary(rows)
    if summary:
        hi, lo = summary.highest, summary.lowest
        out.add()
        out.add(" " + L(f"średnio dziennie {fmt_tok(summary.average)}   najwięcej {hi.date} "
                        f"({fmt_tok(hi.day.weighted)})   najmniej {lo.date} "
                        f"({fmt_tok(lo.day.weighted)})   dni ▲ {summary.up} / ▼ {summary.down}",
                        f"daily average {fmt_tok(summary.average)}   highest {hi.date} "
                        f"({fmt_tok(hi.day.weighted)})   lowest {lo.date} "
                        f"({fmt_tok(lo.day.weighted)})   days ▲ {summary.up} / ▼ {summary.down}"))
        out.note(L("Zmiany w tokenach ważonych. ▲ = więcej niż dzień wcześniej, ▼ = mniej, "
                   "= bez zmian (±1%). „największa zmiana” = czynność, której zużycie zmieniło "
                   "się najbardziej.",
                   "Changes in weighted tokens. ▲ = more than the day before, ▼ = less, = unchanged "
                   "(±1%). 'biggest change' = the activity whose usage changed the most."))
    return out.render()


# --------------------------------------------------------------------------- --list

def session_list(root: str, recent: List[Tuple[float, TranscriptFile]], namer: Namer) -> str:
    lines = [f" {L('sesja', 'session'):<10}{L('ostatnio', 'last used'):<18}"
             f"{L('projekt', 'project'):<28}{L('pierwsza prośba', 'first request')}"]
    for mtime, tf in recent:
        _, sessions = load(root, None, None, files=[tf])
        meta = sessions.get((tf.proj_dir, tf.session_id))
        lines.append(f" {tf.session_id[:8]:<10}{datetime.datetime.fromtimestamp(mtime):%Y-%m-%d %H:%M}  "
                     f"{short(namer.project(meta, tf.proj_dir), 27):<28}"
                     f"{namer.topic(meta.topic if meta else None)[:50]}")
    return "\n".join(lines)
