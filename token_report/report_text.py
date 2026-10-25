"""The terminal report."""
from __future__ import annotations

import datetime
import textwrap
from typing import Callable, List, Mapping, Optional, Tuple

from .classify import activity_name
from .context import TOP_ROWS, ReportContext
from .daily import DayRow, daily_summary
from .formatting import (arrow, bar, fmt_change, fmt_delta, fmt_int, fmt_tok, home_relative,
                         pct, short, short_right, side_name)
from .hotspots import LARGE_FILE, LONG_INSTRUCTIONS, Item, column_name, limits_note, status
from .i18n import L, weekday
from .naming import Namer
from .options import no_comparison_note
from .pricing import TOKEN_TYPES, TYPE_WEIGHTS, model_weight, type_name, unknown_models
from .session_detail import SessionDetail, effort_name, fmt_duration, ultracode_text
from .stats import (CAUSE_COMPACT, CAUSE_EXPIRED, CAUSE_MODEL, CAUSE_OTHER, CAUSES, CTX_BUCKETS,
                    FEW_CALLS, GAP_BUCKETS, LONG_CONTEXT, TOP_REBUILDS, Bucket, Stats,
                    cache_hit, ctx_growth, timeline_kind)
from .tips import tips
from .transcripts import TranscriptFile, load
from .waste import advice, bash_note, skills_note

WIDTH = 104


class _Style:
    """ANSI terminal styling that preserves column alignment (pad first, wrap second)."""

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled and text else text

    def bold(self, text: str) -> str:
        return self._wrap("1", text)

    def dim(self, text: str) -> str:
        return self._wrap("2", text)

    def cyan(self, text: str) -> str:
        return self._wrap("36", text)

    def bold_cyan(self, text: str) -> str:
        return self._wrap("1;36", text)

    def green(self, text: str) -> str:
        return self._wrap("32", text)

    def yellow(self, text: str) -> str:
        return self._wrap("33", text)

    def red(self, text: str) -> str:
        return self._wrap("31", text)

    def magenta(self, text: str) -> str:
        return self._wrap("35", text)

    def bar(self, frac: float, width: int = 20) -> str:
        raw = bar(frac, width)
        if not self.enabled:
            return raw
        dots = raw.find("·")
        if dots == -1:
            return self.cyan(raw)
        if dots == 0:
            return self.dim(raw)
        return self.cyan(raw[:dots]) + self.dim(raw[dots:])

    def delta(self, text: str, diff: float) -> str:
        if not self.enabled or abs(diff) < 1e-9:
            return self.dim(text) if abs(diff) < 1e-9 else text
        return self.yellow(text) if diff > 0 else self.green(text)

    def arrow(self, cur: float, prev: Optional[float], padded: str) -> str:
        sym = arrow(cur, prev)
        if not self.enabled or sym == " ":
            return padded
        if sym == "=":
            return self.dim(padded)
        return self.yellow(padded) if sym == "▲" else self.green(padded)


class _Lines:
    """collects report lines"""

    def __init__(self, color: bool = False) -> None:
        self._lines: List[str] = []
        self.s = _Style(color)
        self._last_kind: str = "empty"

    def add(self, text: str = "", kind: str = "text") -> None:
        self._lines.append(text)
        self._last_kind = "empty" if not text.strip() else kind

    def ensure_blank(self) -> None:
        if self._lines and self._last_kind not in ("empty", "header", "rule"):
            self.add()

    def rule(self) -> None:
        self.add(self.s.cyan("═" * WIDTH), kind="rule")

    def header(self, title: str) -> None:
        self.add()
        dashes = "─" * max(0, WIDTH - len(title) - 4)
        self.add(f"{self.s.cyan('──')} {self.s.bold_cyan(title)} {self.s.dim(dashes)}",
                 kind="header")

    def subheader(self, title: str, indent: int = 1) -> None:
        self.ensure_blank()
        self.add(" " * indent + self.s.bold_cyan("▸ " + title), kind="subheader")

    def table_header(self, cols: str, indent: int = 1, rule_width: Optional[int] = None) -> None:
        if self._last_kind in ("note", "text", "row"):
            self.add()
        w = rule_width if rule_width is not None else max(len(cols.rstrip()), WIDTH - indent)
        self.add(" " * indent + self.s.bold(cols), kind="table_header")
        self.add(" " * indent + self.s.dim("─" * w), kind="table_rule")

    def note(self, text: str, indent: int = 2) -> None:
        if self._last_kind == "note":
            self.add(" " * indent + self.s.dim("│"), kind="note_sep")
        elif self._last_kind == "row":
            self.add()
        prefix = " " * indent + "│ "
        for line in textwrap.wrap(text, WIDTH - len(prefix) - 1):
            self.add(self.s.dim(prefix + line), kind="note")

    def prose(self, text: str, indent: int = 1) -> None:
        for line in textwrap.wrap(text, WIDTH - indent - 1):
            self.add(" " * indent + line, kind="text")

    def bullet(self, text: str) -> None:
        if self._last_kind == "bullet":
            self.add()
        lines = textwrap.wrap(text, WIDTH - 4)
        self.add(f" {self.s.bold_cyan('•')} " + lines[0], kind="bullet")
        for line in lines[1:]:
            self.add("   " + line, kind="bullet")

    def render(self) -> str:
        return "\n".join(self._lines)


def _breakdown(out: _Lines, title: str, groups: Mapping[str, Bucket], total: float, top: int,
               label: str, names: Callable[[str], str] = str, desc: Optional[str] = None,
               left: bool = False, n_label: Optional[str] = None,
               extra: Optional[Tuple[str, Callable[[str], str]]] = None) -> None:
    """a table of groups sorted by weighted tokens, with a bar per row"""
    s = out.s
    out.header(title)
    if desc:
        out.note(desc)
    total = total or 1e-9
    n_label = n_label or L("wywoł.", "calls")
    extra_head = f"{extra[0]:>7}" if extra else ""
    bar_w = 13 if extra else 20
    cols = (f"{label:<38}{L('surowe', 'raw'):>9}{L('ważone', 'weighted'):>10}{'%':>7}"
            f"{n_label:>8}{L('śr./szt.', 'avg'):>9}{extra_head}")
    out.table_header(cols, indent=1, rule_width=WIDTH - 1)
    items = sorted(groups.items(), key=lambda kv: -kv[1].weighted)
    for key, b in items[:top]:
        raw_name = str(names(key))
        name = short(raw_name, 37) if left else short_right(raw_name, 37)
        extra_val = f"{extra[1](key):>7}" if extra else ""
        out.add(f" {name:<38}{fmt_tok(b.raw):>9}{s.bold(f'{fmt_tok(b.weighted):>10}')}"
                f"{pct(b.weighted, total):>6.1f}%{b.calls:>8}"
                f"{fmt_tok(b.weighted / b.calls if b.calls else 0):>9}{extra_val}  "
                f"{s.bar(b.weighted / total, bar_w)}", kind="row")
    rest = items[top:]
    if rest:
        rest_w = sum(b.weighted for _, b in rest)
        rest_raw = sum(b.raw for _, b in rest)
        rest_lbl = L(f"(pozostałe: {len(rest)})", f"(other: {len(rest)})")
        out.add(s.dim(f" {rest_lbl:<38}{fmt_tok(rest_raw):>9}{fmt_tok(rest_w):>10}"
                      f"{pct(rest_w, total):>6.1f}%"), kind="row")


# --------------------------------------------------------------------------- main report

def _summary(out: _Lines, stats: Stats) -> None:
    s = out.s
    raw = stats.raw
    hit = cache_hit(stats.tokens)

    def item(name: str, value: str, text: str, highlight: bool = False) -> None:
        lbl = s.bold(f"{name:<26}") if highlight else f"{name:<26}"
        val = s.bold_cyan(f"{value:>12}") if highlight else s.bold(f"{value:>12}")
        out.add(f" {lbl}{val}   {s.dim(text)}", kind="row")

    item(L("wywołania modelu", "model calls"), fmt_int(stats.n_calls),
         L(f"{stats.n_sessions} rozmów, {stats.n_subagents} subagentów",
           f"{stats.n_sessions} conversations, {stats.n_subagents} subagents"))
    item(L("tokeny surowe", "raw tokens"), fmt_tok(raw),
         L("wszystkie tokeny liczone po równo", "all tokens counted equally"))
    item(L("tokeny ważone", "weighted tokens"), fmt_tok(stats.weighted),
         L("główna miara — obciążenie limitu (--explain)",
           "main measure — load on your limit (--explain)"),
         highlight=True)
    if hit is not None:
        item(L("trafienia w cache", "cache hit rate"), f"{hit:.1f}%",
             L("powyżej ~90% to dobry wynik", "above ~90% is good"))
    if stats.n_calls:
        ctx_tokens = raw - stats.tokens["output"]
        item(L("średnio na wywołanie", "average per call"), fmt_tok(stats.weighted / stats.n_calls),
             L(f"ważonych; śr. kontekst {fmt_tok(ctx_tokens / stats.n_calls)}",
               f"weighted; avg context {fmt_tok(ctx_tokens / stats.n_calls)}"))
    if stats.turns:
        item(L("prośby użytkownika", "user requests"), fmt_int(stats.turns),
             L(f"ważonych na prośbę średnio {fmt_tok(stats.weighted / stats.turns)} "
               f"(cała praca, włącznie z subagentami)",
               f"weighted per request on average {fmt_tok(stats.weighted / stats.turns)} "
               f"(all work, subagents included)"))


def _token_types(out: _Lines, stats: Stats) -> None:
    s = out.s
    out.header(L("RODZAJE TOKENÓW — surowe vs ważone", "TOKEN TYPES — raw vs weighted"))
    tok, w_t = stats.tokens, stats.weighted_by_type
    raw = stats.raw or 1
    total = stats.weighted or 1e-9
    cols = (f"{L('rodzaj tokenu', 'token type'):<28}{L('surowe', 'raw'):>10}{'%':>7}"
            f"{L('waga', 'weight'):>8}{L('ważone', 'weighted'):>10}{'%':>7}")
    out.table_header(cols, indent=1, rule_width=WIDTH - 1)
    for t in TOKEN_TYPES:
        if t == "cache_write_1h" and not tok[t]:
            continue
        out.add(f" {type_name(t):<28}{fmt_tok(tok[t]):>10}{pct(tok[t], raw):>6.1f}%"
                f"{'x' + format(TYPE_WEIGHTS[t], 'g'):>8}{s.bold(f'{fmt_tok(w_t[t]):>10}')}"
                f"{pct(w_t[t], total):>6.1f}%  {s.bar(w_t[t] / total, 27)}", kind="row")
    out.add(" " + s.dim("─" * 70), kind="table_rule")
    out.add(s.bold(f" {L('RAZEM', 'TOTAL'):<28}{fmt_tok(raw):>10}{'':>7}{'':>8}{fmt_tok(stats.weighted):>10}"),
            kind="row")
    out.note(L("Ważone uwzględniają też wagę modelu (tabela MODELE).",
               "Weighted also includes the model's weight (see MODELS)."))


def _models(out: _Lines, stats: Stats, top: int = TOP_ROWS) -> None:
    _breakdown(out, L("MODELE", "MODELS"), stats.by_model, stats.weighted, top, "model",
               extra=(L("waga", "weight"), lambda k: "x" + format(model_weight(k), ".2g")),
               desc=L("„waga” = jak mocno model obciąża limit względem Opus 5 (x1). Ta sama praca "
                      "na modelu z wagą x0.4 zużywa 2.5 raza mniej.",
                      "'weight' = how heavily the model uses the limit relative to Opus 5 (x1). "
                      "The same work on a x0.4 model uses 2.5 times less."))
    if unknown_models():
        out.note(L("nieznane modele liczone z wagą Opus 5: ", "unknown models weighted as Opus 5: ")
                 + ", ".join(unknown_models()))


def _activities(out: _Lines, stats: Stats, top: int) -> None:
    _breakdown(out, L("NA CO IDĄ TOKENY", "WHERE THE TOKENS GO"), stats.by_activity,
               stats.weighted, top, L("czynność", "activity"), activity_name, n_label=L("użyć", "uses"),
               desc=L("Każde wywołanie jest przypisane do narzędzia, którego model w nim użył (przy "
                      "kilku narzędziach naraz — po równo). „Bez narzędzia” = model odpowiedział Ci "
                      "tekstem. „śr./szt.” = ile średnio waży jedno użycie.",
                      "Each call is assigned to the tool the model used in it (split evenly if it "
                      "used several). 'No tool' = the model replied to you with text. 'avg' = the "
                      "average weight of one use."))


def _breakdowns(out: _Lines, stats: Stats, ctx: ReportContext) -> None:
    total = stats.weighted
    _breakdown(out, L("SESJA GŁÓWNA vs SUBAGENCI", "MAIN SESSION vs SUBAGENTS"), stats.by_side,
               total, 2, L("gdzie", "where"), side_name,
               desc=L("Subagenci to osobne instancje Claude uruchamiane narzędziem Agent. Mają "
                      "własny kontekst, więc ich praca nie wydłuża głównej rozmowy.",
                      "Subagents are separate Claude instances started with the Agent tool. They "
                      "have their own context, so their work doesn't grow the main conversation."))
    if stats.by_agent_type and not ctx.detail:
        _breakdown(out, L("SUBAGENCI WG TYPU", "SUBAGENTS BY TYPE"), stats.by_agent_type, total,
                   TOP_ROWS, L("typ subagenta", "subagent type"),
                   extra=(L("kont.", "ctx"),
                          lambda key: fmt_tok(stats.by_agent_type[key].avg_context)),
                   desc=L("„kontekst” = średni rozmiar rozmowy, jaką subagent czytał przy "
                          "wywołaniu. Duży kontekst przy małej pracy to sygnał, że subagent "
                          "dostał za dużo.",
                          "'context' = average size of the conversation the subagent read per "
                          "call. A large context for little work is a sign it was given too much."))
    if not ctx.session:
        _breakdown(out, L("PROJEKTY (katalog roboczy)", "PROJECTS (working directory)"),
                   stats.by_project, total, TOP_ROWS, L("projekt", "project"), left=True)


def _context_length(out: _Lines, stats: Stats) -> None:
    s = out.s
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
    cols = (f"{L('kontekst', 'context'):<14}{L('wywoł.', 'calls'):>8}{L('surowe', 'raw'):>10}"
            f"{L('ważone', 'weighted'):>10}{'%':>7}{L('śr./wywoł.', 'avg/call'):>12}"
            f"{L('w tym czytanie', 'of it reading'):>16}")
    out.table_header(cols, indent=1, rule_width=WIDTH - 1)
    for _, _, name in CTX_BUCKETS:
        b = stats.by_context[name]
        if not b.calls:
            continue
        extra = (s.dim(L("  (mało danych)", "  (few calls)")) if b.calls < FEW_CALLS
                 else "  " + s.bar(b.weighted / total, 18))
        out.add(f" {name:<14}{b.calls:>8}{fmt_tok(b.raw):>10}{s.bold(f'{fmt_tok(b.weighted):>10}')}"
                f"{pct(b.weighted, total):>6.1f}%"
                f"{fmt_tok(b.weighted / b.calls):>12}{fmt_tok(b.reading / b.calls):>16}{extra}",
                kind="row")
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
    _overhead(out, stats)


def _overhead(out: _Lines, stats: Stats) -> None:
    if not stats.overhead_tokens:
        return
    total = stats.weighted or 1e-9
    out.add()
    out.prose(L(f"stały narzut: ok. {fmt_tok(stats.overhead_tokens)} na początku każdej "
                f"rozmowy (mediana pierwszego wywołania), ponowne czytanie go: "
                f"{fmt_tok(stats.overhead_weighted)} ({pct(stats.overhead_weighted, total):.1f}% "
                f"całości)",
                f"fixed overhead: about {fmt_tok(stats.overhead_tokens)} at the start of every "
                f"conversation (median of the first call), re-reading it: "
                f"{fmt_tok(stats.overhead_weighted)} ({pct(stats.overhead_weighted, total):.1f}% "
                f"of the total)"))
    out.add()
    out.note(L("To system prompt, narzędzia, CLAUDE.md i lista skilli. Szacunek: część każdego "
               "wywołania, którą model czyta z cache. Zmiana CLAUDE.md, skilli albo MCP "
               "przebudowuje ją od nowa.",
               "System prompt, tools, CLAUDE.md and the skill list. An estimate: the share of each "
               "call read from the cache. Changing CLAUDE.md, skills or MCP rebuilds it."))


def _over_time(out: _Lines, stats: Stats) -> None:
    s = out.s
    kind = timeline_kind(stats)
    periods = stats.periods(kind)
    if not periods:
        return
    total = stats.weighted or 1e-9
    out.header(L("W CZASIE — ", "OVER TIME — ")
               + (L("tygodnie", "weeks") if kind == "week" else L("dni", "days")))
    peak = max(p.weighted for _, p in periods) or 1e-9
    cols = (f"{L('okres', 'period'):<26}{L('surowe', 'raw'):>10}{L('ważone', 'weighted'):>10}"
            f"{'%':>7}{L('wywoł.', 'calls'):>8}")
    out.table_header(cols, indent=1, rule_width=WIDTH - 1)
    for key, p in periods:
        out.add(f" {key:<26}{fmt_tok(p.raw):>10}{s.bold(f'{fmt_tok(p.weighted):>10}')}"
                f"{pct(p.weighted, total):>6.1f}%{p.calls:>8}  {s.bar(p.weighted / peak, 36)}",
                kind="row")
    if len(periods) <= 1:
        return
    top_activities = [k for k, _ in sorted(stats.by_activity.items(),
                                           key=lambda kv: -kv[1].weighted)[:6]]
    view = periods[-8:]
    out.subheader(L("trend głównych czynności (tokeny ważone):",
                    "trend of top activities (weighted tokens):"))
    heads = [(key[5:10] if kind == "day" else key[5:8]) for key, _ in view]
    t_cols = f"{L('czynność', 'activity'):<35}" + "".join(f"{h:>8}" for h in heads)
    out.table_header(t_cols, indent=1, rule_width=len(t_cols))
    for activity in top_activities:
        out.add(f" {short_right(activity_name(activity), 34):<35}"
                + "".join(f"{fmt_tok(p.activities[activity]):>8}" for _, p in view), kind="row")


def _heaviest_sessions(out: _Lines, stats: Stats, ctx: ReportContext, top: int = TOP_ROWS) -> None:
    s = out.s
    total = stats.weighted or 1e-9
    out.header(L("NAJCIĘŻSZE ROZMOWY", "HEAVIEST CONVERSATIONS"))
    cols = (f"{L('sesja', 'session'):<10}{L('projekt', 'project'):<22}{L('surowe', 'raw'):>8}"
            f"{L('ważone', 'weighted'):>10}{'%':>7}{L('wywoł.', 'calls'):>7}"
            f"{L('maks.ctx', 'max ctx'):>9}{L('subag.', 'sub'):>7}  {L('temat', 'topic')}")
    out.table_header(cols, indent=1, rule_width=WIDTH - 1)
    for key, sess in sorted(stats.by_session.items(), key=lambda kv: -kv[1].weighted)[:top]:
        meta = ctx.sessions.get(key)
        project = ctx.namer.project(meta, key[0])
        topic = ctx.namer.topic(meta.topic if meta else None)
        out.add(f" {s.cyan(f'{key[1][:8]:<10}')}{short(project, 21):<22}{fmt_tok(sess.raw):>8}"
                f"{s.bold(f'{fmt_tok(sess.weighted):>10}')}"
                f"{pct(sess.weighted, total):>6.1f}%{sess.calls:>7}{fmt_tok(sess.max_context):>9}"
                f"{pct(sess.subagent_weighted, sess.weighted):>6.0f}%  {short_right(topic, 21)}",
                kind="row")
    out.note(L("„maks.ctx” = do jakiego rozmiaru urosła rozmowa; „subag.” = jaka część "
               "zużycia tej sesji przypadła na subagentów. Szczegóły jednej sesji: "
               "--session <id>",
               "'max ctx' = how large the conversation grew; 'sub' = the share of this "
               "session's usage spent by subagents. One session in detail: --session <id>"))


def _short_model(model: str) -> str:
    return model[len("claude-"):] if model.startswith("claude-") else model


def _session_info(out: _Lines, d: SessionDetail) -> None:
    s = out.s
    out.header(L("SZCZEGÓŁY SESJI", "SESSION DETAILS"))

    def item(name: str, value: str) -> None:
        lines = textwrap.wrap(value, WIDTH - 18) or [""]
        out.add(f" {s.bold(f'{name:<16}')} {lines[0]}", kind="row")
        for line in lines[1:]:
            out.add(" " * 18 + line, kind="row")

    start, end = d.start.astimezone(), d.end.astimezone()
    until = f"{end:%H:%M}" if end.date() == start.date() else f"{end:%Y-%m-%d %H:%M}"
    item(L("sesja", "session"), d.session_id)
    item(L("projekt", "project"),
         d.project + (L(f"  (gałąź {d.branch})", f"  (branch {d.branch})") if d.branch else ""))
    item(L("czas", "time"), f"{start:%Y-%m-%d %H:%M} → {until}  ({fmt_duration(d.duration)})"
         + (f"   Claude Code {d.version}" if d.version else ""))
    item(L("rozmowa", "conversation"),
         L(f"prośby: {d.requests}, powiadomienia: {d.notifications}, kompaktowania: "
           f"{d.compactions}, wywołania: {d.calls}, maks. kontekst {fmt_tok(d.max_context)}",
           f"{d.requests} requests, {d.notifications} notifications, {d.compactions} "
           f"compactions, {d.calls} calls, max context {fmt_tok(d.max_context)}"))
    item(L("zużycie", "usage"), L(f"{fmt_tok(d.weighted)} ważonych, {fmt_tok(d.raw)} surowych",
                                  f"{fmt_tok(d.weighted)} weighted, {fmt_tok(d.raw)} raw"))
    item("cache", L(f"odbudowany od nowa {d.rebuilds.count}×"
                    + (f" (nadmiar {fmt_tok(d.rebuilds.waste)}, najdłuższa przerwa "
                       f"{d.rebuilds.longest_gap:.0f} min)" if d.rebuilds.count else ""),
                    f"rewritten {d.rebuilds.count}×"
                    + (f" (extra {fmt_tok(d.rebuilds.waste)}, longest pause "
                       f"{d.rebuilds.longest_gap:.0f} min)" if d.rebuilds.count else "")))
    item(L("długi kontekst", "long context"),
         L(f"{d.long_calls} wywołań na kontekście ≥ {fmt_tok(LONG_CONTEXT)}, kompaktowań: "
           f"{d.compactions}", f"{d.long_calls} calls at a context ≥ {fmt_tok(LONG_CONTEXT)}, "
           f"compactions: {d.compactions}")
         + (L(f" ({fmt_tok(d.long_weighted)} ważonych)", f" ({fmt_tok(d.long_weighted)} weighted)")
            if d.long_calls else ""))
    item("effort", ", ".join(
        f"{effort_name(level)} {pct(u.weighted, d.weighted):.0f}% ({u.calls} {L('wyw.', 'calls')})"
        for level, u in d.efforts))
    item("ultracode", ultracode_text(d))
    item(L("tryb fast", "fast mode"),
         L(f"{d.fast.calls} wywołań ({pct(d.fast.weighted, d.weighted):.0f}% zużycia)",
           f"{d.fast.calls} calls ({pct(d.fast.weighted, d.weighted):.0f}% of usage)")
         if d.fast.calls else L("nie", "no"))
    if d.skills:
        item(L("skille", "skills"), ", ".join(f"{k} ×{n}" for k, n in d.skills.most_common()))


def _session_models(out: _Lines, d: SessionDetail) -> None:
    s = out.s
    out.header(L("MODELE W TEJ SESJI", "MODELS IN THIS SESSION"))
    total = d.weighted or 1e-9
    cols = (f"{'model':<26}{L('wywoł.', 'calls'):>7}{L('subag.', 'sub'):>7}"
            f"{L('wejście', 'input'):>8}{L('odczyt', 'c.read'):>9}{L('zapis', 'c.write'):>9}"
            f"{L('wyjście', 'output'):>8}{L('ważone', 'weighted'):>9}{'%':>6}")
    out.table_header(cols, indent=1, rule_width=WIDTH - 1)
    for m in d.models:
        t = m.tokens
        out.add(f" {m.model[:25]:<26}{m.calls:>7}{m.sub_calls:>7}{fmt_tok(t['input']):>8}"
                f"{fmt_tok(t['cache_read']):>9}"
                f"{fmt_tok(t['cache_write_5m'] + t['cache_write_1h']):>9}"
                f"{fmt_tok(t['output']):>8}{s.bold(f'{fmt_tok(m.weighted):>9}')}"
                f"{pct(m.weighted, total):>5.0f}%", kind="row")
    out.note(L("„subag.” = ile z tych wywołań zrobili subagenci; odczyt/zapis = cache.",
               "'sub' = how many of these calls subagents made; c.read/c.write = cache."))
    if d.agents:
        out.header(L(f"SUBAGENCI W TEJ SESJI ({len(d.agents)})",
                     f"SUBAGENTS IN THIS SESSION ({len(d.agents)})"))
        a_cols = (f"{'id':<9}{L('typ', 'type'):<19}{'model':<15}{L('wywoł.', 'calls'):>6}"
                  f"{L('ważone', 'weighted'):>10}{'%':>6}  {L('zadanie', 'task')}")
        out.table_header(a_cols, indent=1, rule_width=WIDTH - 1)
        for a in d.agents[:TOP_ROWS + 5]:
            model = _short_model(a.models.most_common(1)[0][0])
            if len(a.models) > 1:
                model += f" +{len(a.models) - 1}"
            out.add(f" {s.cyan(f'{a.agent_id[:8]:<9}')}{a.agent_type[:18]:<19}{model[:14]:<15}"
                    f"{a.calls:>6}{s.bold(f'{fmt_tok(a.weighted):>10}')}"
                    f"{pct(a.weighted, total):>5.0f}%  {short_right(a.task, 30)}", kind="row")
        if len(d.agents) > TOP_ROWS + 5:
            out.add(" " + s.dim(L(f"(pozostałe: {len(d.agents) - TOP_ROWS - 5})",
                                  f"(other: {len(d.agents) - TOP_ROWS - 5})")), kind="row")


def _session_files(out: _Lines, d: SessionDetail) -> None:
    s = out.s
    if d.files:
        out.header(L(f"PLIKI — przeczytane i zmienione ({d.n_files})",
                     f"FILES — read and changed ({d.n_files})"))
        cols = (f"{L('plik', 'file'):<54}{L('odczyty', 'reads'):>8}{L('zmiany', 'edits'):>8}"
                f"{L('ważone', 'weighted'):>10}{'%':>6}")
        out.table_header(cols, indent=1, rule_width=WIDTH - 1)
        for f in d.files:
            out.add(f" {short(f.name, 53):<54}{f.reads:>8}{f.edits:>8}"
                    f"{s.bold(f'{fmt_tok(f.weighted):>10}')}"
                    f"{pct(f.weighted, d.weighted):>5.0f}%", kind="row")
        out.note(L("Odczyty narzędziem Read i przez cat/head/sed, zmiany przez Edit/Write. "
                   "„ważone” = część wywołań, w których model sięgnął po ten plik.",
                   "Reads with the Read tool and cat/head/sed, changes with Edit/Write. "
                   "'weighted' = the share of the calls in which the model used this file."))
    if d.searches:
        out.subheader(L("najczęstsze wyszukiwania (Grep/Glob):",
                        "most frequent searches (Grep/Glob):"))
        for pattern, n in d.searches.most_common():
            out.add(f"   {short_right(pattern, 70):<72}{n:>4}×", kind="row")


def _session_phases(out: _Lines, ctx: ReportContext) -> None:
    s = out.s
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
        out.add(f" {s.dim(f'{prompt.time.astimezone():%m-%d %H:%M}')}  {tag:<8}{len(calls):>5} "
                f"{L('wyw.', 'calls')}{fmt_tok(raw):>8} {L('sur.', 'raw')}"
                f"{s.bold(f'{fmt_tok(weighted):>7}')} "
                f"{L('waż.', 'wt.')}  ctx {fmt_tok(max_ctx):>5}  "
                f"{short_right(ctx.namer.topic(prompt.text), 34)}", kind="row")


def cause_name(cause: str) -> str:
    return {CAUSE_MODEL: L("zmiana modelu", "model changed"),
            CAUSE_COMPACT: L("po kompakcji", "after compaction"),
            CAUSE_EXPIRED: L("przerwa dłuższa niż cache", "pause longer than the cache"),
            CAUSE_OTHER: L("inne", "other")}[cause]


def _expired_cache(out: _Lines, stats: Stats) -> None:
    s = out.s
    total = stats.weighted or 1e-9
    rb = stats.rebuilds
    out.header(L("WYGASŁY CACHE — rozmowa zapisana od nowa",
                 "EXPIRED CACHE — conversation written again"))
    out.add(" " + s.bold(L(f"takich wywołań: {rb.count}   nadmiarowe zużycie: {fmt_tok(rb.waste)} "
                           f"({pct(rb.waste, total):.1f}% całości)",
                           f"such calls: {rb.count}   extra usage: {fmt_tok(rb.waste)} "
                           f"({pct(rb.waste, total):.1f}% of the total)")), kind="text")
    out.add()
    out.note(L(
        "Cache trzyma rozmowę 5 minut albo 1 godzinę od ostatniego użycia (transkrypt "
        "zapisuje, które). Po dłuższej przerwie model zapisuje całą rozmowę od nowa zamiast "
        "ją odczytać: zapis 5 min = x1.25, zapis 1 h = x2, odczyt (oba) = x0.1 (w nowszych "
        "modelach x0.05 lub mniej).",
        "The cache keeps the conversation for 5 minutes or 1 hour after its last use (the "
        "transcript records which). After a longer break the model writes the whole "
        "conversation again instead of reading it: 5 min write = x1.25, 1 h write = x2, "
        "read (both) = x0.1 (x0.05 or less in newer models)."))
    if rb.count:
        out.subheader(L("przerwa przed odbudową:", "pause before the rewrite:"))
        for _, label in GAP_BUCKETS:
            out.add(f"   {label + ' min':<12}{s.bold(f'{rb.by_gap[label]:>5}')}", kind="row")
        out.note(L(
            "Czy przerwa wyjaśnia odbudowę, zależy od czasu życia cache w tej rozmowie: przy "
            "cache 5 min przerwa „5-60 min” to wygaśnięcie, przy cache 1 h już nie. "
            "„< 5 min” nigdy nie jest wygaśnięciem. Cache 5 min mają m.in. subagenci. "
            "Podział na przyczyny poniżej uwzględnia to osobno dla każdego pliku rozmowy. "
            "Przerwę liczymy od poprzedniego wywołania tego samego pliku.",
            "Whether the pause explains the rewrite depends on the cache lifetime in that "
            "conversation: with a 5 min cache a '5-60 min' pause is an expiry, with a 1 h cache "
            "it is not. '< 5 min' is never an expiry. Subagents, among others, use the 5 min "
            "cache. The causes below take this into account per conversation file. The pause "
            "is counted from the previous call of the same file."))
        out.subheader(L("przyczyna odbudowy:", "cause of the rewrite:"))
        for cause in CAUSES:
            if rb.by_cause[cause]:
                out.add(f"   {cause_name(cause):<38}{rb.by_cause[cause]:>5}×  "
                        f"{L('nadmiar', 'extra')} {s.bold(f'{fmt_tok(rb.waste_by_cause[cause]):>7}')}",
                        kind="row")
        out.note(L("„inne” = odbudowa bez widocznej w transkrypcie przyczyny (model bez zmian, "
                   "brak kompakcji, przerwa krótsza niż cache). Transkrypt nie zapisuje "
                   "początku rozmowy, więc nie wiadomo, co ją wywołało.",
                   "'other' = a rewrite with no cause visible in the transcript (same model, no "
                   "compaction, pause shorter than the cache). The transcript does not record "
                   "the start of the conversation, so the cause is unknown."))
    if stats.ttl_sessions:
        out.subheader(L("czas życia cache wg sesji (z zapisów w transkrypcie):",
                        "cache lifetime by session (from the writes in the transcript):"))
        for kind, label in (("5m", L("5 minut", "5 minutes")), ("1h", L("1 godzina", "1 hour")),
                            ("mixed", L("mieszany", "mixed"))):
            if stats.ttl_sessions[kind]:
                out.add(f"   {label:<14}{s.bold(f'{stats.ttl_sessions[kind]:>5}')}", kind="row")
    if rb.count:
        out.subheader(L("sesje z największą liczbą odbudów:", "sessions with the most rewrites:"))
        for key, sr in sorted(rb.by_session.items(), key=lambda kv: -kv[1].waste)[:TOP_REBUILDS]:
            out.add(f"   {s.cyan(key[1][:8])}  "
                    + L(f"{sr.count:>3}×  nadmiar {s.bold(f'{fmt_tok(sr.waste):>6}')}  "
                        f"najdłuższa przerwa {sr.longest_gap:>5.0f} min",
                        f"{sr.count:>3}×  extra {s.bold(f'{fmt_tok(sr.waste):>6}')}  "
                        f"longest pause {sr.longest_gap:>5.0f} min"), kind="row")
        out.subheader(L("największe pojedyncze zdarzenia:", "largest single events:"))
    for e in rb.top:
        out.add(f"   {s.dim(f'{e.time.astimezone():%Y-%m-%d %H:%M}')}  {s.cyan(e.file_key[1][:8])}  "
                f"ctx {fmt_tok(e.context):>5}  "
                + L(f"przerwa {e.gap_minutes:>4.0f} min  nadmiar {s.bold(f'{fmt_tok(e.waste):>5}')}  "
                    f"{s.dim(cause_name(e.cause))}",
                    f"gap {e.gap_minutes:>4.0f} min  extra {s.bold(f'{fmt_tok(e.waste):>5}')}  "
                    f"{s.dim(cause_name(e.cause))}"), kind="row")
    _long_context(out, stats)


def _long_context(out: _Lines, stats: Stats) -> None:
    s = out.s
    lc = stats.long_context
    out.header(L(f"DŁUGIE ROZMOWY — kontekst ≥ {fmt_tok(LONG_CONTEXT)}",
                 f"LONG CONVERSATIONS — context ≥ {fmt_tok(LONG_CONTEXT)}"))
    if not lc.calls:
        out.add(" " + L("żadna rozmowa nie urosła do tego rozmiaru.",
                        "no conversation grew to this size."))
        return
    out.add(" " + L(f"rozmów: {s.bold(str(lc.sessions))}, z tego nigdy nie kompaktowanych: "
                    f"{s.bold(str(lc.uncompacted_sessions))}",
                    f"conversations: {s.bold(str(lc.sessions))}, never compacted: "
                    f"{s.bold(str(lc.uncompacted_sessions))}"), kind="row")
    out.add(" " + L(f"wywołań na takim kontekście: {s.bold(str(lc.calls))}, ważone zużycie: "
                    f"{s.bold(fmt_tok(lc.weighted))} ({pct(lc.weighted, stats.weighted or 1e-9):.1f}% "
                    f"całości)",
                    f"calls at such a context: {s.bold(str(lc.calls))}, weighted usage: "
                    f"{s.bold(fmt_tok(lc.weighted))} ({pct(lc.weighted, stats.weighted or 1e-9):.1f}% "
                    f"of the total)"), kind="row")
    out.note(L("To zużycie wywołań na dużym kontekście, nie oszczędność z /compact — jej nie da "
               "się policzyć, bo nie wiadomo, jak mały byłby kontekst po kompaktowaniu.",
               "This is what the calls at a large context used, not a saving from /compact — "
               "that cannot be calculated, as the context after compaction is unknown."))


def _rereads(out: _Lines, stats: Stats) -> None:
    s = out.s
    rr = stats.rereads
    if not rr.reads:
        return
    out.header(L("POWTÓRNE ODCZYTY PLIKÓW (narzędzie Read)", "REPEATED FILE READS (Read tool)"))
    out.add(" " + L(f"odczytów: {s.bold(str(rr.reads))}, z tego fragment już był w rozmowie: "
                    f"{s.bold(str(rr.repeats))} ({pct(rr.repeats, rr.reads):.0f}%)",
                    f"reads: {s.bold(str(rr.reads))}, part already in the conversation: "
                    f"{s.bold(str(rr.repeats))} ({pct(rr.repeats, rr.reads):.0f}%)"), kind="text")
    out.add()
    for name, n in rr.files.most_common(6):
        out.add(f"   {short(name, 54):<56}{s.yellow(f'+{n}')}", kind="row")


def _fmt_status(s: _Style, item: Item) -> str:
    text = status(item)
    if item.linked:
        return s.cyan(f"→ {text}")
    if item.documented is None:
        return s.dim(text)
    if item.documented:
        return s.green(f"✓ {text}")
    return s.yellow(f"✗ {text}")


def _project_map(out: _Lines, stats: Stats) -> None:
    s = out.s
    if not stats.hotspots and not stats.hotspots_hidden:
        return
    out.header(L("MAPA PROJEKTU — czego Claude szuka w kółko",
                 "PROJECT MAP — what Claude looks up again and again"))
    if stats.hotspots_hidden:
        out.note(L("Ukryte z --private (nazwy plików i klas zdradzają projekt).",
                   "Hidden with --private (file and class names reveal the project)."))
        return
    out.note(L(
        "Pliki i symbole, których Claude szukał w kilku rozmowach. Każda nowa rozmowa odkrywa je "
        "od zera; jedna linia w CLAUDE.md oszczędza to szukanie.",
        "Files and symbols Claude looked up in several conversations. Each new conversation "
        "finds them from scratch; one line in CLAUDE.md saves that search."))
    out.note(limits_note())
    in_claude = column_name()
    for project in stats.hotspots:
        out.subheader(home_relative(project.root), indent=1)
        if project.instructions:
            out.add("   " + s.dim(L("instrukcje: ", "instructions: ")) + ", ".join(
                L(f"{f.name} ({f.lines} linii)", f"{f.name} ({f.lines} lines)")
                for f in project.instructions[:4]), kind="text")
        else:
            out.note(L("Brak CLAUDE.md — uruchom /init w tym projekcie, a potem dopisz mapę "
                       "z poniższego szkicu.",
                       "No CLAUDE.md — run /init in this project, then add the map from the "
                       "draft below."), indent=3)
        for f in project.long_instructions():
            out.note(L(f"{f.name} ma {f.lines} linii i ładuje się w każdej rozmowie (zalecane "
                       f"< {LONG_INSTRUCTIONS}). Wskazówki dla jednej części kodu przenieś do "
                       f".claude/rules/ z polem paths:, a procedury do skilli.",
                       f"{f.name} has {f.lines} lines and loads in every conversation "
                       f"(advised < {LONG_INSTRUCTIONS}). Move guidance for one part of the "
                       f"code to .claude/rules/ with a paths: field, and procedures to skills."),
                     indent=3)
        if project.files:
            f_cols = (f"{L('plik', 'file'):<46}{L('odczyty', 'reads'):>8}{L('rozm.', 'convs'):>7}"
                      f"{L('linie', 'lines'):>7}  {in_claude}")
            out.table_header(f_cols, indent=3, rule_width=86)
            for item in project.files:
                lines = str(item.lines) if item.lines is not None else "-"
                large = ("  " + s.magenta(L("[duży]", "[large]"))
                         if (item.lines or 0) >= LARGE_FILE else "")
                out.add(f"   {short(item.name, 45):<46}{s.bold(f'{item.uses:>8}')}"
                        f"{item.sessions:>7}{lines:>7}  {_fmt_status(s, item)}{large}",
                        kind="row")
        if project.symbols:
            s_cols = (f"{L('symbol', 'symbol'):<46}{L('szukania', 'lookups'):>8}"
                      f"{L('rozm.', 'convs'):>7}{'':>7}  {in_claude}")
            out.table_header(s_cols, indent=3, rule_width=86)
            for item in project.symbols:
                out.add(f"   {short(item.name, 45):<46}{s.bold(f'{item.uses:>8}')}"
                        f"{item.sessions:>7}{'':>7}  {_fmt_status(s, item)}", kind="row")
        if any((i.lines or 0) >= LARGE_FILE for i in project.files):
            out.note(L(f"„duży” = ponad {LARGE_FILE} linii, więc Claude czyta go kawałkami w "
                       f"każdej rozmowie. Opisz w CLAUDE.md, co jest w której części pliku, "
                       f"albo go podziel.",
                       f"'large' = over {LARGE_FILE} lines, so Claude reads it in pieces in "
                       f"every conversation. Describe in CLAUDE.md what is in which part of the "
                       f"file, or split it."), indent=3)
        files_draft, symbols_draft = project.draft_groups()
        if files_draft or symbols_draft:
            out.add()
            out.add("   " + s.bold(L("Do CLAUDE.md — szkic dla pozycji oznaczonych „nie znaleziono”:",
                                     "For CLAUDE.md — a draft for the items marked 'not found':")),
                    kind="text")
            out.note(L("Zamień każde „…” jednym zdaniem: po co jest plik lub co robi symbol, "
                       "np. „układ szablonów reklam; tu resolveLayout”.",
                       "Replace each '…' with one sentence: what the file is for or what "
                       "the symbol does, e.g. 'ad template layout; resolveLayout lives here'."),
                     indent=3)
            out.add()
            out.add("     " + s.bold_cyan(L("## Mapa projektu", "## Project map")), kind="text")
            for title, lines in ((L("### Pliki", "### Files"), files_draft),
                                 (L("### Symbole", "### Symbols"), symbols_draft)):
                if lines:
                    out.add("     " + s.bold(title), kind="text")
                    for line in lines:
                        out.add("     " + line, kind="text")


def _bash_noise(out: _Lines, stats: Stats) -> None:
    s = out.s
    w = stats.waste
    if not w.bash_results:
        return
    out.header(L("SZUM Z POLECEŃ BASH — długie wyniki bez ograniczenia",
                 "BASH NOISE — long results with no limit"))
    total = stats.weighted or 1e-9
    out.prose(L(f"wyników poleceń: {fmt_int(w.bash_results)}, ok. {fmt_tok(w.bash_tokens)} tokenów; "
                f"długich bez ograniczenia: ok. {fmt_tok(w.noisy_tokens)} tokenów, "
                f"po uwzględnieniu ponownych odczytów {fmt_tok(w.noisy_weighted)} ważonych "
                f"({pct(w.noisy_weighted, total):.1f}% zużycia)",
                f"command results: {fmt_int(w.bash_results)}, about {fmt_tok(w.bash_tokens)} "
                f"tokens; long and unlimited: about {fmt_tok(w.noisy_tokens)} tokens, "
                f"{fmt_tok(w.noisy_weighted)} weighted with the re-reads "
                f"({pct(w.noisy_weighted, total):.1f}% of usage)"))
    out.add()
    out.note(bash_note())
    if not w.families:
        out.add()
        out.add(" " + L("Żaden rodzaj polecenia nie powtarza się z długim wynikiem.",
                        "No kind of command repeats with a long result."))
        return
    cols = (f"{L('polecenie', 'command'):<28}{L('długich', 'long'):>9}{L('z', 'of'):>7}"
            f"{L('tokeny', 'tokens'):>10}{L('ważone', 'weighted'):>10}{L('max', 'max'):>9}")
    out.table_header(cols, indent=1, rule_width=len(cols))
    for idx, f in enumerate(w.families):
        if idx > 0:
            out.add()
        out.add(f" {s.bold(f'{short(f.name, 27):<28}')}{f.unlimited:>9}{f.runs:>7}"
                f"{fmt_tok(f.tokens):>10}{s.bold(f'{fmt_tok(f.weighted):>10}')}"
                f"{fmt_tok(f.biggest):>9}", kind="row")
        out.add(f"   {s.cyan('→ ' + advice(f.name))}", kind="row")
        if f.example and not stats.hotspots_hidden:
            ex = short(f.example.replace(chr(10), " "), 78)
            out.add("   " + s.dim(f"{L('największe', 'largest')}: {ex}"), kind="row")


def _skills(out: _Lines, stats: Stats, namer: Namer, rows: int = TOP_ROWS) -> None:
    s = out.s
    sk = stats.waste.skills
    if not (sk.conversations or sk.used):
        return
    out.header(L("SKILLE — które się przydają, a które tylko zajmują kontekst",
                 "SKILLS — which ones earn their place and which only take up context"))
    if sk.conversations:
        out.prose(L(f"skilli na liście: {len(sk.available)} (ok. {fmt_tok(sk.listing_tokens())} "
                    f"tokenów opisów w każdej rozmowie, rozmów z listą: {sk.conversations}); "
                    f"nieużywanych: {len(sk.unused())} (ok. {fmt_tok(sk.unused_tokens())} "
                    f"tokenów)",
                    f"skills listed: {len(sk.available)} (about {fmt_tok(sk.listing_tokens())} "
                    f"tokens of descriptions in every conversation, conversations with the "
                    f"list: {sk.conversations}); unused: {len(sk.unused())} (about "
                    f"{fmt_tok(sk.unused_tokens())} tokens)"))
        out.add()
    out.note(skills_note())
    used = sk.used_rows()
    if used:
        u_cols = f"{L('używane', 'used'):<46}{L('rozmowy', 'convs'):>8}"
        out.table_header(u_cols, indent=1, rule_width=len(u_cols))
        for r in used[:rows]:
            out.add(f" {short(namer.skill(r.name), 45):<46}{s.bold(f'{r.uses:>8}')}", kind="row")
    unused = sk.unused()
    if unused:
        un_cols = f"{L('nieużywane', 'unused'):<46}{L('tokeny', 'tokens'):>8}{L('wspomniany', 'named'):>12}"
        out.table_header(un_cols, indent=1, rule_width=len(un_cols))
        for r in unused[:rows]:
            named_str = s.yellow(f"{r.named_in:>12}") if r.named_in else f"{r.named_in:>12}"
            out.add(f" {short(namer.skill(r.name), 45):<46}{r.tokens:>8}{named_str}", kind="row")
        if len(unused) > rows:
            out.add(" " + s.dim(L(f"… i {len(unused) - rows} kolejnych",
                                  f"… and {len(unused) - rows} more")), kind="row")


_FLAGS = [("time", "--time"), ("breakdown", "--breakdown"), ("cache", "--cache"),
          ("bash", "--bash"), ("skills", "--skills"), ("map", "--project-map")]


def text_report(stats: Stats, ctx: ReportContext, color: bool = False) -> str:
    out = _Lines(color=color)
    s = out.s
    out.rule()
    title = L("ZUŻYCIE TOKENÓW CLAUDE CODE", "CLAUDE CODE TOKEN USAGE") + " — " + ctx.label
    out.add(" " + s.bold_cyan(title))
    src = (L("źródło: lokalne transkrypty ", "source: local transcripts ") + ctx.root_display
           + L("  (raport zużywa 0 tokenów)", "  (this report uses 0 tokens)"))
    out.add(" " + s.dim(src))
    out.rule()
    _summary(out, stats)
    if ctx.detail:
        _session_info(out, ctx.detail)
        _session_models(out, ctx.detail)
        _session_files(out, ctx.detail)
    if ctx.has("activities"):  # 8 rows compact, 16 long
        _activities(out, stats, ctx.rows + (6 if ctx.plan.long_tables else 3))
    if not ctx.detail and ctx.has("models"):  # a single session lists its models in SESSION DETAILS
        _models(out, stats, ctx.rows)
    if ctx.session:
        _session_phases(out, ctx)
    elif ctx.has("sessions"):
        _heaviest_sessions(out, stats, ctx, ctx.rows)
    if ctx.has("time"):
        _token_types(out, stats)
        _over_time(out, stats)
    if ctx.has("breakdown"):
        _breakdowns(out, stats, ctx)
    if ctx.has("cache"):
        _context_length(out, stats)
        _expired_cache(out, stats)
        _rereads(out, stats)
    if ctx.has("bash"):
        _bash_noise(out, stats)
    if ctx.has("skills"):
        _skills(out, stats, ctx.namer, ctx.rows)
    if ctx.has("map"):
        _project_map(out, stats)
    if ctx.has("tips"):
        out.header(L("CO MOŻNA POPRAWIĆ", "WHAT YOU COULD IMPROVE"))
        for tip in tips(stats, ctx):
            out.bullet(tip)
    out.add()
    missing = [f for key, f in _FLAGS if not ctx.has(key)]
    if missing:
        out.add(" " + s.dim(L("Więcej szczegółów: ", "More detail: ") + " ".join(missing)
                            + L("  albo --full (wszystko)", "  or --full (everything)")))
    out.add(" " + s.dim(L("Pełne wyjaśnienie tokenów surowych i ważonych: --explain",
                          "Full explanation of raw and weighted tokens: --explain")))
    out.rule()
    return out.render()


# --------------------------------------------------------------------------- --diff

def _weighted(groups: Mapping[str, Bucket], key: str) -> float:
    return groups[key].weighted if key in groups else 0.0


def _compare_groups(out: _Lines, title: str, cur: Mapping[str, Bucket],
                    prev: Mapping[str, Bucket], names: Callable[[str], str] = str,
                    top: int = 12) -> None:
    s = out.s
    out.header(title)
    cols = (f"{'':<38}{L('teraz', 'now'):>10}{L('wcześniej', 'before'):>11}"
            f"{L('różnica', 'diff'):>10}{L('zmiana', 'change'):>9}")
    out.table_header(cols, indent=1, rule_width=len(cols))
    keys = sorted(set(cur) | set(prev), key=lambda k: -_weighted(cur, k) - _weighted(prev, k))
    for key in keys[:top]:
        a, b = _weighted(cur, key), _weighted(prev, key)
        diff = a - b
        out.add(f" {short_right(str(names(key)), 37):<38}{s.bold(f'{fmt_tok(a):>10}')}"
                f"{fmt_tok(b):>11}{s.delta(f'{fmt_delta(diff):>10}', diff)}"
                f"{s.delta(f'{fmt_change(a, b):>9}', diff)}", kind="row")


def text_diff(cur: Stats, prev: Stats, ctx: ReportContext, color: bool = False) -> str:
    """the --diff block: the summary numbers always, then a part for each comparable element
    of the report (options.ELEMENT_INFO), then the elements left without a comparison"""
    out = _Lines(color=color)
    s = out.s
    out.rule()
    out.add(" " + s.bold_cyan(L("PORÓWNANIE", "COMPARISON") + f": {ctx.label}  vs  {ctx.prev_label}"))
    out.rule()
    cols = (f"{L('wskaźnik', 'metric'):<30}{L('teraz', 'now'):>12}{L('wcześniej', 'before'):>12}"
            f"{L('zmiana', 'change'):>10}")
    out.table_header(cols, indent=1, rule_width=len(cols))

    def row(name: str, a: float, b: float, fmt: Callable[[float], str]) -> None:
        out.add(f" {name:<30}{s.bold(f'{fmt(a):>12}')}{fmt(b):>12}"
                f"{s.delta(f'{fmt_change(a, b):>10}', a - b)}", kind="row")

    row(L("wywołania modelu", "model calls"), cur.n_calls, prev.n_calls, fmt_int)
    row(L("tokeny surowe", "raw tokens"), cur.raw, prev.raw, fmt_tok)
    row(L("tokeny ważone", "weighted tokens"), cur.weighted, prev.weighted, fmt_tok)
    if ctx.has("time"):  # the token types
        for t in TOKEN_TYPES:
            if cur.weighted_by_type[t] or prev.weighted_by_type[t]:
                row("  " + type_name(t), cur.weighted_by_type[t], prev.weighted_by_type[t], fmt_tok)
    row(L("średnio na wywołanie", "average per call"), cur.weighted / max(cur.n_calls, 1),
        prev.weighted / max(prev.n_calls, 1), fmt_tok)
    hit_cur, hit_prev = cache_hit(cur.tokens) or 0, cache_hit(prev.tokens) or 0
    out.add(f" {L('trafienia w cache', 'cache hit rate'):<30}{s.bold(f'{hit_cur:>11.1f}%')}"
            f"{hit_prev:>11.1f}%{hit_cur - hit_prev:>+8.1f}pp", kind="row")

    if ctx.has("activities"):
        _compare_groups(out, L("NA CO IDĄ TOKENY (ważone)", "WHERE THE TOKENS GO (weighted)"),
                        cur.by_activity, prev.by_activity, activity_name)
    if ctx.has("models"):
        _compare_groups(out, L("MODELE (ważone)", "MODELS (weighted)"), cur.by_model, prev.by_model)
    if ctx.has("breakdown"):
        _compare_groups(out, L("PROJEKTY (ważone)", "PROJECTS (weighted)"), cur.by_project,
                        prev.by_project, lambda k: short(k, 37))
    takeaways = diff_takeaways(cur, prev, ctx)
    if takeaways:
        out.header(L("WNIOSKI", "TAKEAWAYS"))
        for line in takeaways:
            out.bullet(line)
    note = no_comparison_note(ctx.plan.elements)
    if note:
        out.add()
        out.add(" " + s.dim(note))
    out.rule()
    return out.render()


def diff_takeaways(cur: Stats, prev: Stats, ctx: ReportContext) -> List[str]:
    """the shares compared by --diff for cache (long conversations, expired cache) and bash"""
    lines = []
    if ctx.has("cache"):
        long_cur, long_prev = cur.long_context_weighted(), prev.long_context_weighted()
        waste_cur, waste_prev = cur.rebuilds.waste, prev.rebuilds.waste
        lines.append(L(f"długie rozmowy (kontekst > 200k): {pct(long_cur, cur.weighted):.0f}% zużycia "
                       f"(wcześniej {pct(long_prev, prev.weighted):.0f}%)",
                       f"long conversations (context > 200k): {pct(long_cur, cur.weighted):.0f}% "
                       f"of usage (before {pct(long_prev, prev.weighted):.0f}%)"))
        lines.append(L(f"nadmiar przez wygasły cache: {pct(waste_cur, cur.weighted):.1f}% "
                       f"(wcześniej {pct(waste_prev, prev.weighted):.1f}%)",
                       f"extra from expired cache: {pct(waste_cur, cur.weighted):.1f}% "
                       f"(before {pct(waste_prev, prev.weighted):.1f}%)"))
    if ctx.has("bash"):
        noise_cur, noise_prev = cur.waste.noisy_weighted, prev.waste.noisy_weighted
        lines.append(L(f"szum z poleceń Bash (długie wyniki bez ograniczenia): "
                       f"{pct(noise_cur, cur.weighted):.1f}% zużycia "
                       f"(wcześniej {pct(noise_prev, prev.weighted):.1f}%)",
                       f"Bash noise (long results with no limit): "
                       f"{pct(noise_cur, cur.weighted):.1f}% of usage "
                       f"(before {pct(noise_prev, prev.weighted):.1f}%)"))
    return lines


# --------------------------------------------------------------------------- --daily

def text_daily(rows: List[DayRow], color: bool = False) -> str:
    out = _Lines(color=color)
    s = out.s
    out.header(L("DZIEŃ PO DNIU — zmiana względem poprzedniego dnia",
                 "DAY BY DAY — change vs the previous day"))
    cols = (f"{L('dzień', 'day'):<17}{L('surowe', 'raw'):>9}{L('ważone', 'weighted'):>11}"
            f"{L('zmiana', 'change'):>10}{'%':>7}"
            f"{L('wywoł.', 'calls'):>8}{'cache':>7}{L('śr./wyw.', 'avg/call'):>10}  "
            f"{L('największa zmiana', 'biggest change')}")
    out.table_header(cols, indent=1, rule_width=WIDTH - 1)
    for r in rows:
        day, prev = r.day, r.prev
        name = f"{r.date:%m-%d} {weekday(r.date)}" + (L(" (baza)", " (base)") if r.is_base else "")
        hit = f"{r.cache_hit:.0f}%" if r.cache_hit is not None else "-"
        per_call = fmt_tok(r.per_call) if r.per_call is not None else "-"
        if prev is None or r.is_base:
            out.add(f" {name:<17}{fmt_tok(day.raw):>9}{s.bold(f'{fmt_tok(day.weighted):>11}')}"
                    f"{'':>10}{'':>7}{day.calls:>8}{hit:>7}{per_call:>10}", kind="row")
            continue
        driver = ""
        if r.driver and abs(r.driver[1]) >= 1:
            driver = f"{fmt_delta(r.driver[1])} {activity_name(r.driver[0])}"
        diff = day.weighted - prev.weighted
        arr = s.arrow(day.weighted, prev.weighted, f"{arrow(day.weighted, prev.weighted):>2}")
        out.add(f" {name:<17}{fmt_tok(day.raw):>9}{arr}"
                f"{s.bold(f'{fmt_tok(day.weighted):>9}')}"
                f"{s.delta(f'{fmt_delta(diff):>10}', diff)}"
                f"{s.delta(f'{fmt_change(day.weighted, prev.weighted):>7}', diff)}"
                f"{day.calls:>8}{hit:>7}"
                f"{per_call:>10}  {short_right(driver, 28)}", kind="row")
    summary = daily_summary(rows)
    if summary:
        hi, lo = summary.highest, summary.lowest
        out.add()
        out.add(" " + L(f"średnio dziennie {s.bold(fmt_tok(summary.average))}   "
                        f"najwięcej {hi.date} ({s.bold(fmt_tok(hi.day.weighted))})   "
                        f"najmniej {lo.date} ({s.bold(fmt_tok(lo.day.weighted))})   "
                        f"dni ▲ {summary.up} / ▼ {summary.down}",
                        f"daily average {s.bold(fmt_tok(summary.average))}   "
                        f"highest {hi.date} ({s.bold(fmt_tok(hi.day.weighted))})   "
                        f"lowest {lo.date} ({s.bold(fmt_tok(lo.day.weighted))})   "
                        f"days ▲ {summary.up} / ▼ {summary.down}"), kind="text")
        out.add()
        out.note(L("Zmiany w tokenach ważonych. ▲ = więcej niż dzień wcześniej, ▼ = mniej, "
                   "= bez zmian (±1%). „największa zmiana” = czynność, której zużycie zmieniło "
                   "się najbardziej.",
                   "Changes in weighted tokens. ▲ = more than the day before, ▼ = less, = unchanged "
                   "(±1%). 'biggest change' = the activity whose usage changed the most."))
    return out.render()


# --------------------------------------------------------------------------- --list

def session_list(root: str, recent: List[Tuple[float, TranscriptFile]], namer: Namer,
                 color: bool = False) -> str:
    out = _Lines(color=color)
    s = out.s
    cols = (f"{L('sesja', 'session'):<10}{L('ostatnio', 'last used'):<18}"
            f"{L('projekt', 'project'):<28}{L('pierwsza prośba', 'first request')}")
    out.table_header(cols, indent=1, rule_width=WIDTH - 1)
    for mtime, tf in recent:
        _, sessions = load(root, None, None, files=[tf])
        meta = sessions.get((tf.proj_dir, tf.session_id))
        ts = f"{datetime.datetime.fromtimestamp(mtime):%Y-%m-%d %H:%M}"
        out.add(f" {s.cyan(f'{tf.session_id[:8]:<10}')}{s.dim(ts)}  "
                f"{short(namer.project(meta, tf.proj_dir), 27):<28}"
                f"{short_right(namer.topic(meta.topic if meta else None), 42)}", kind="row")
    return out.render()
