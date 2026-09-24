"""The HTML report (--html): one self-contained page, no external resources."""
from __future__ import annotations

import datetime
import html
import os
from typing import Callable, Dict, List, Mapping, Optional, Tuple

from .classify import activity_name
from .context import TOP_ROWS, ReportContext
from .daily import DayRow, daily_summary
from .explain import explain_text
from .formatting import arrow, fmt_change, fmt_delta, fmt_int, fmt_tok, pct, side_name
from .i18n import L, get_lang, weekday
from .pricing import TOKEN_TYPES, TYPE_WEIGHTS, model_weight, type_name, unknown_models
from .stats import CTX_BUCKETS, FEW_CALLS, Bucket, Stats, cache_hit, ctx_growth, timeline_kind
from .tips import tips
from .tooltips import help_mark as qm

E = html.escape

_ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

# token type -> CSS variable (validated categorical slots 1-4)
SERIES = {"input": "--s1", "cache_read": "--s2", "cache_write": "--s3", "output": "--s4"}


def _asset(name: str) -> str:
    with open(os.path.join(_ASSETS, name), encoding="utf-8") as f:
        return f.read()


def _merge_types(d: Mapping[str, float]) -> Dict[str, float]:
    """both cache write durations as one series"""
    return {"input": d["input"], "cache_read": d["cache_read"],
            "cache_write": d["cache_write_5m"] + d["cache_write_1h"], "output": d["output"]}


def _type_labels() -> Dict[str, str]:
    return {"input": type_name("input"), "cache_read": type_name("cache_read"),
            "cache_write": L("zapis do cache", "cache write"), "output": type_name("output")}


def _weighted_h() -> str:
    return L("ważone", "weighted")


def _raw_h() -> str:
    return f"{L('surowe', 'raw')}{qm('raw')}"


def _calls_h() -> str:
    return L("wywoł.", "calls")


def _card(value: str, label: str, cls: str = "card") -> str:
    return f"<div class={cls}><b>{value}</b><span>{label}</span></div>"


# --------------------------------------------------------------------------- sections

def _breakdown_table(groups: Mapping[str, Bucket], total: float, label: str,
                     names: Callable[[str], str] = str, top: int = 12,
                     n_label: Optional[str] = None, n_key: str = "calls",
                     extra: Optional[Tuple[str, Callable[[str], str]]] = None) -> str:
    items = sorted(groups.items(), key=lambda kv: -kv[1].weighted)[:top]
    peak = max((b.weighted for _, b in items), default=0) or 1e-9
    extra_head = f"<th class=n>{extra[0]}</th>" if extra else ""
    rows = "".join(
        f"<tr><td class=l>{E(str(names(k)))}</td>"
        + (f"<td class=n>{extra[1](k)}</td>" if extra else "")
        + f"<td class=n>{fmt_tok(b.raw)}</td><td class=n>{fmt_tok(b.weighted)}</td>"
        f"<td class=n>{pct(b.weighted, total):.1f}%</td>"
        f"<td class=n>{b.calls}</td><td class=n>{fmt_tok(b.weighted / b.calls if b.calls else 0)}"
        f"</td><td class=b><span style='width:{100 * b.weighted / peak:.1f}%'"
        f" title='{E(str(names(k)))}: {fmt_tok(b.weighted)}'></span></td></tr>"
        for k, b in items)
    return (f"<div class=wrap><table><tr><th>{E(label)}</th>{extra_head}<th class=n>{_raw_h()}</th>"
            f"<th class=n>{_weighted_h()}"
            f"{qm('weighted')}</th><th class=n>%</th><th class=n>{n_label or _calls_h()}"
            f"{qm(n_key)}</th><th class=n>{L('śr.', 'avg')}{qm('avg')}</th><th></th></tr>"
            f"{rows}</table></div>")


def _summary_cards(stats: Stats) -> str:
    hit = cache_hit(stats.tokens) or 0
    return "\n".join([
        "<div class=grid>",
        _card(fmt_tok(stats.weighted), f"{L('tokenów ważonych — główna miara', 'weighted tokens — the main measure')}{qm('weighted')}", '"card main"'),
        _card(fmt_tok(stats.raw or 1), f"{L('tokenów surowych (nieważonych)', 'raw (unweighted) tokens')}{qm('raw')}"),
        _card(fmt_int(stats.n_calls), f"{L('wywołań modelu', 'model calls')} · {stats.n_sessions} {L('sesji', 'sessions')}{qm('calls')}"),
        _card(fmt_tok(stats.weighted / max(stats.n_calls, 1)), f"{L('ważonych na wywołanie', 'weighted per call')}{qm('avgcall')}"),
        _card(f"{hit:.0f}%", f"{L('rozmowy z cache', 'of conversation from cache')}{qm('hit')}"),
        "</div>",
    ])


def _explanation() -> str:
    return (f"<details><summary>{L('Co to są tokeny surowe i ważone? Skąd wagi? (pełne wyjaśnienie)', 'What are raw and weighted tokens? Where do the weights come from? (full explanation)')}</summary>\n"
            f"<div class=\"card explain\">{E(explain_text())}</div></details>")


def _comparison(stats: Stats, prev: Optional[Stats], ctx: ReportContext) -> str:
    if prev is None:
        return ""

    def row(name: str, a: float, b: float, fmt: Callable[[float], str]) -> str:
        cls = "up" if a > b else "down"
        return (f"<tr><td class=l>{E(name)}</td><td class=n>{fmt(a)}</td><td class=n>{fmt(b)}</td>"
                f"<td class='n {cls}'>{arrow(a, b)} {fmt_change(a, b)}</td></tr>")

    def activity_w(s: Stats, key: str) -> float:
        return s.by_activity[key].weighted if key in s.by_activity else 0

    rows = [row(L("wywołania modelu", "model calls"), stats.n_calls, prev.n_calls, fmt_int),
            row(L("tokeny surowe", "raw tokens"), stats.raw or 1, prev.raw, fmt_tok),
            row(L("tokeny ważone", "weighted tokens"), stats.weighted, prev.weighted, fmt_tok),
            row(L("średnio na wywołanie", "average per call"), stats.weighted / max(stats.n_calls, 1),
                prev.weighted / max(prev.n_calls, 1), fmt_tok)]
    keys = sorted(set(stats.by_activity) | set(prev.by_activity),
                  key=lambda k: -activity_w(stats, k))[:12]
    rows += [row(activity_name(k), activity_w(stats, k), activity_w(prev, k), fmt_tok) for k in keys]
    return (f"<h2>{L('Porównanie', 'Comparison')}{qm('compare')}</h2><p class=sub>"
            f"{E(ctx.label)} vs {E(ctx.prev_label)}</p><div class=wrap><table><tr><th>"
            f"</th><th class=n>{L('teraz', 'now')}</th><th class=n>{L('wcześniej', 'before')}"
            f"</th><th class=n>{L('zmiana', 'change')}</th></tr>{''.join(rows)}</table></div>")


def _daily(rows: Optional[List[DayRow]]) -> str:
    if not rows:
        return ""
    changes = [abs(r.day.weighted - r.prev.weighted) for r in rows
               if r.prev is not None and not r.is_base]
    peak = max(changes, default=0) or 1e-9
    trs = []
    for r in rows:
        day, prev = r.day, r.prev
        name = f"{r.date:%m-%d} {weekday(r.date)}"
        hit = f"{r.cache_hit:.0f}%" if r.cache_hit is not None else "–"
        per_call = fmt_tok(r.per_call) if r.per_call is not None else "–"
        if prev is None or r.is_base:
            tag = f" <small>({L('baza', 'base')})</small>" if r.is_base else ""
            trs.append(f"<tr class=base><td class=l>{name}{tag}</td><td class=n>"
                       f"{fmt_tok(day.raw)}</td><td class=n>{fmt_tok(day.weighted)}</td><td></td><td></td><td></td>"
                       f"<td class=n>{day.calls}</td><td class=n>{hit}</td>"
                       f"<td class=n>{per_call}</td><td></td></tr>")
            continue
        delta = day.weighted - prev.weighted
        ar = arrow(day.weighted, prev.weighted)
        cls = "up" if ar == "▲" else "down" if ar == "▼" else ""
        delta_bar = (f"<div class=dv><span class={'dvu' if delta >= 0 else 'dvd'} "
                     f"style='width:{50 * abs(delta) / peak:.1f}%' title='{fmt_delta(delta)}'>"
                     f"</span></div>")
        driver = ""
        if r.driver and abs(r.driver[1]) >= 1:
            key, change = r.driver
            driver = (f"<span class={'up' if change > 0 else 'down'}>{fmt_delta(change)}</span> "
                      f"{E(activity_name(key))}")
        trs.append(f"<tr><td class=l>{name}</td><td class=n>{fmt_tok(day.raw)}</td>"
                   f"<td class=n>{fmt_tok(day.weighted)}</td>"
                   f"<td class='n {cls}'>{ar} {fmt_delta(delta)}</td>"
                   f"<td class='n {cls}'>{fmt_change(day.weighted, prev.weighted)}</td>"
                   f"<td>{delta_bar}</td><td class=n>{day.calls}</td><td class=n>{hit}</td>"
                   f"<td class=n>{per_call}</td><td class=t>{driver}</td></tr>")
    summary = daily_summary(rows)
    cards = ""
    if summary:
        cards = (
            f"<div class=grid>"
            f"<div class=card><b>{fmt_tok(summary.average)}</b><span>"
            f"{L('średnio dziennie', 'daily average')} ({summary.days} {L('dni', 'days')})</span></div>"
            f"<div class=card><b>{fmt_tok(summary.highest.day.weighted)}</b><span>"
            f"{L('najwięcej', 'highest')}: {summary.highest.date}</span></div>"
            f"<div class=card><b>{fmt_tok(summary.lowest.day.weighted)}</b><span>"
            f"{L('najmniej', 'lowest')}: {summary.lowest.date}</span></div>"
            f"<div class=card><b><span class=up>▲ {summary.up}</span> · <span class=down>▼ "
            f"{summary.down}</span></b><span>{L('dni wzrostu · spadku', 'days up · down')}"
            f"</span></div></div>")
    return (f"<h2>{L('Dzień po dniu', 'Day by day')}{qm('daily')}</h2>{cards}"
            f"<div class=wrap><table class=daily><tr><th>{L('dzień', 'day')}</th>"
            f"<th class=n>{_raw_h()}</th><th class=n>"
            f"{_weighted_h()}{qm('weighted')}</th><th class=n>{L('zmiana', 'change')}"
            f"</th><th class=n>%</th><th>{L('wzrost / spadek', 'up / down')}</th><th class=n>"
            f"{_calls_h()}{qm('calls')}</th><th class=n>cache{qm('hit')}</th>"
            f"<th class=n>{L('śr./wyw.', 'avg/call')}{qm('avgcall')}</th><th>"
            f"{L('największa zmiana', 'biggest change')}{qm('driver')}</th></tr>{''.join(trs)}"
            f"</table></div>")


def _token_types(stats: Stats) -> str:
    total = stats.weighted or 1e-9
    raw = stats.raw or 1
    labels = _type_labels()
    stacks = []
    for label, values, help_key in (
            (L("tokeny surowe", "raw tokens"), _merge_types(stats.tokens), "raw"),
            (L("tokeny ważone", "weighted tokens"), _merge_types(stats.weighted_by_type), "weighted")):
        s = sum(values.values()) or 1e-9
        segments = "".join(
            f"<span style='width:{100 * v / s:.2f}%;background:var({SERIES[k]})' "
            f"title='{E(labels[k])}: {100 * v / s:.1f}%'></span>"
            for k, v in values.items() if v > 0)
        stacks.append(f"<div class=srow><div class=slab>{E(label)}{qm(help_key)}</div>"
                      f"<div class=stack>{segments}</div></div>")
    rows = "".join(
        f"<tr><td class=l>{E(type_name(t))}</td><td class=n>{fmt_tok(stats.tokens[t])}</td>"
        f"<td class=n>{pct(stats.tokens[t], raw):.1f}%</td><td class=n>x{TYPE_WEIGHTS[t]:g}</td>"
        f"<td class=n>{fmt_tok(stats.weighted_by_type[t])}</td>"
        f"<td class=n>{pct(stats.weighted_by_type[t], total):.1f}%</td></tr>"
        for t in TOKEN_TYPES if not (t == "cache_write_1h" and not stats.tokens[t]))
    return "\n".join([
        f"<h2>{L('Rodzaje tokenów: surowe vs ważone', 'Token types: raw vs weighted')}{qm('types')}</h2>",
        f"<div class=card><div class=legend>{_legend()}</div>{''.join(stacks)}</div>",
        f"<div class=wrap style=\"margin-top:12px\"><table><tr><th>{L('rodzaj', 'type')}</th>"
        f"<th class=n>{L('surowe', 'raw')}{qm('raw')}</th><th class=n>%</th>"
        f"<th class=n>{L('waga', 'weight')}{qm('weight')}</th>"
        f"<th class=n>{_weighted_h()}{qm('weighted')}</th><th class=n>%</th></tr>{rows}</table></div>",
    ])


def _legend() -> str:
    return "".join(f"<span><i style='background:var({SERIES[k]})'></i>{E(v)}</span>"
                   for k, v in _type_labels().items())


def _time_chart(stats: Stats) -> str:
    """SVG bars: weighted tokens per day/week, stacked by token type"""
    kind = timeline_kind(stats)
    periods = stats.periods(kind)
    if not periods:
        return ""
    labels = _type_labels()
    peak = max(p.weighted for _, p in periods) or 1e-9
    n = len(periods)
    width, height, pad_left, pad_bottom, pad_top = 720, 230, 52, 34, 12
    plot_h = height - pad_bottom - pad_top
    bar_w = (width - pad_left) / n
    parts = []
    for g in range(5):
        y = pad_top + plot_h * (1 - g / 4)
        parts.append(f"<line x1={pad_left} x2={width} y1={y:.1f} y2={y:.1f} class=gl />"
                     f"<text x={pad_left - 6} y={y + 4:.1f} class=ax text-anchor=end>"
                     f"{fmt_tok(peak * g / 4)}</text>")
    for i, (key, p) in enumerate(periods):
        x = pad_left + i * bar_w + bar_w * 0.15
        y0 = height - pad_bottom
        merged = _merge_types(p.weighted_by_type)
        for t in ("cache_read", "cache_write", "input", "output"):
            h = plot_h * merged[t] / peak
            if h <= 0:
                continue
            parts.append(f"<rect x={x:.1f} y={y0 - h:.1f} width={bar_w * 0.7:.1f} "
                         f"height={max(h - 1, 0.5):.1f} fill='var({SERIES[t]})'><title>"
                         f"{E(key)} — {E(labels[t])}: {fmt_tok(merged[t])}</title></rect>")
            y0 -= h
        parts.append(f"<rect x={pad_left + i * bar_w:.1f} y=0 width={bar_w:.1f} "
                     f"height={height - pad_bottom} fill=transparent><title>{E(key)}: "
                     f"{fmt_tok(p.weighted)} {L('ważonych', 'weighted')}, {fmt_tok(p.raw)} "
                     f"{L('surowych', 'raw')}, {p.calls} "
                     f"{L('wywołań', 'calls')}</title></rect>")
        if n <= 16 or i % max(1, n // 12) == 0:
            label = key[5:10] if kind == "day" else key[5:8]
            parts.append(f"<text x={pad_left + i * bar_w + bar_w / 2:.1f} y={height - pad_bottom + 16} "
                         f"class=ax text-anchor=middle>{E(label)}</text>")
    return (f"<h2>{L('Zużycie w czasie', 'Usage over time')}{qm('time')}</h2><div class=card>"
            f"<div class=legend>{_legend()}</div><svg viewBox='0 0 {width} {height}' role=img "
            f"aria-label='{L('zużycie w czasie', 'usage over time')}'>{''.join(parts)}</svg>"
            f"</div>")


def _groups(stats: Stats, ctx: ReportContext) -> str:
    total = stats.weighted or 1e-9
    model_weight_col = (f"{L('waga', 'weight')}{qm('mweight')}",
                        lambda k: "x" + format(model_weight(k), ".2g"))
    unknown = ""
    if unknown_models():
        unknown = (f"<p class=sub>{L('Nieznane modele liczone z wagą Opus 5', 'Unknown models weighted as Opus 5')}: "
                   f"{E(', '.join(unknown_models()))}</p>")
    agents = ""
    if stats.by_agent_type:
        agents = (f"<h2>{L('Subagenci wg typu', 'Subagents by type')}{qm('agents')}</h2>"
                  + _breakdown_table(stats.by_agent_type, total, L('typ', 'type')))
    projects = ""
    if not ctx.session:
        projects = (f"<h2>{L('Projekty', 'Projects')}{qm('projects')}</h2>"
                    + _breakdown_table(stats.by_project, total, L('projekt', 'project')))
    return "\n".join([
        f"<h2>{L('Na co idą tokeny', 'Where the tokens go')}{qm('activity')}</h2>",
        _breakdown_table(stats.by_activity, total, L('czynność', 'activity'), activity_name, 20,
                         L('użyć', 'uses'), 'uses'),
        f"<h2>{L('Modele', 'Models')}{qm('models')}</h2>"
        + _breakdown_table(stats.by_model, total, 'model', extra=model_weight_col) + unknown,
        f"<h2>{L('Sesja główna vs subagenci', 'Main session vs subagents')}{qm('side')}</h2>",
        _breakdown_table(stats.by_side, total, L('gdzie', 'where'), side_name),
        agents,
        projects,
    ])


def _context_length(stats: Stats) -> str:
    total = stats.weighted or 1e-9
    rows = ""
    for _, _, name in CTX_BUCKETS:
        b = stats.by_context[name]
        if not b.calls:
            continue
        few = f" <span class=few>({L('mało danych', 'few calls')})</span>" \
            if b.calls < FEW_CALLS else ""
        rows += (f"<tr><td class=l>{name}{few}</td><td class=n>{b.calls}</td>"
                 f"<td class=n>{fmt_tok(b.raw)}</td>"
                 f"<td class=n>{fmt_tok(b.weighted)}</td><td class=n>{pct(b.weighted, total):.1f}%</td>"
                 f"<td class=n>{fmt_tok(b.weighted / b.calls)}</td>"
                 f"<td class=n>{fmt_tok(b.reading / b.calls)}</td></tr>")
    growth = ctx_growth(stats)
    growth_note = ""
    if growth:
        avg, base, name = growth
        growth_note = ("<p class=sub style='margin-top:10px'>" + E(L(
            f"Wywołanie przy kontekście {name} waży średnio {avg / base:.1f}x tyle co przy "
            f"50-100k. Grupa „< 50k” to często początki rozmów, które najpierw zapisują "
            f"wszystko do cache.",
            f"A call at {name} context weighs {avg / base:.1f}x as much as one at 50-100k on "
            f"average. The '< 50k' group is often conversation starts, which first write "
            f"everything to the cache.")) + "</p>")
    return "\n".join([
        f"<h2>{L('Długość rozmowy', 'Conversation length')}{qm('length')}</h2>",
        f"<div class=wrap><table><tr><th>{L('kontekst', 'context')}</th><th class=n>{_calls_h()}"
        f"</th><th class=n>{_raw_h()}</th><th class=n>{_weighted_h()}{qm('weighted')}</th>"
        f"<th class=n>%</th><th class=n>{L('śr./wywoł.', 'avg/call')}{qm('avgcall')}</th>"
        f"<th class=n>{L('w tym czytanie', 'of it reading')}{qm('reading')}</th></tr>{rows}"
        f"</table></div>",
        growth_note,
    ])


def _heaviest_sessions(stats: Stats, ctx: ReportContext) -> str:
    if ctx.session:
        return ""
    total = stats.weighted or 1e-9
    rows = ""
    for key, s in sorted(stats.by_session.items(), key=lambda kv: -kv[1].weighted)[:TOP_ROWS + 5]:
        meta = ctx.sessions.get(key)
        topic = ctx.namer.topic(meta.topic if meta else None)
        rows += (
            f"<tr><td class=m>{E(key[1][:8])}</td><td>{E(ctx.namer.project(meta, key[0]))}"
            f"</td><td class=n>{fmt_tok(s.raw)}</td><td class=n>{fmt_tok(s.weighted)}</td>"
            f"<td class=n>{pct(s.weighted, total):.1f}%"
            f"</td><td class=n>{s.calls}</td><td class=n>{fmt_tok(s.max_context)}</td>"
            f"<td class=n>{pct(s.subagent_weighted, s.weighted):.0f}%</td>"
            f"<td class=t>{E(topic[:100])}</td></tr>")
    return (f"<h2>{L('Najcięższe rozmowy', 'Heaviest conversations')}{qm('sessions')}</h2>"
            f"<div class=wrap><table><tr><th>{L('sesja', 'session')}</th><th>"
            f"{L('projekt', 'project')}</th><th class=n>{_raw_h()}</th>"
            f"<th class=n>{_weighted_h()}{qm('weighted')}</th>"
            f"<th class=n>%</th><th class=n>{_calls_h()}</th><th class=n>"
            f"{L('maks. ctx', 'max ctx')}{qm('maxctx')}</th><th class=n>{L('subag.', 'sub')}"
            f"{qm('subshare')}</th><th>{L('temat', 'topic')}</th></tr>{rows}</table></div>")


def _cache_and_repeats(stats: Stats) -> str:
    total = stats.weighted or 1e-9
    rb, rr = stats.rebuilds, stats.rereads
    return "\n".join([
        f"<h2>{L('Cache i powtórki', 'Cache and repeats')}</h2>",
        "<div class=grid>",
        _card(str(rb.count), f"{L('razy rozmowa zapisana od nowa', 'times the conversation was rewritten')}{qm('rebuild')}"),
        _card(f"{pct(rb.waste, total):.1f}%", f"{L('zużycia to nadmiar przez wygasły cache', 'of usage was extra from expired cache')} ({fmt_tok(rb.waste)}){qm('waste')}"),
        _card(f"{pct(rr.repeats, rr.reads):.0f}%", f"{L('odczytów plików to powtórki', 'of file reads were repeats')} ({rr.repeats}/{rr.reads}){qm('reread')}"),
        "</div>",
    ])


def _tips(stats: Stats) -> str:
    items = "".join(f"<li>{E(t)}</li>" for t in tips(stats))
    return (f"<h2>{L('Co można poprawić', 'What you could improve')}{qm('tips')}</h2>"
            f"<div class=card><ul>{items}</ul></div>")


def _footer() -> str:
    return (f"<footer>{L('Wagi rodzajów: wejście x1, odczyt cache x0.1, zapis cache x1.25 (5 min) / x2 (1 h), wyjście x5; wagi modeli względem Opus 5. Proporcje z cennika API Anthropic (stan 2026-09). Anthropic nie publikuje wzoru limitów subskrypcji — to przybliżenie.', 'Type weights: input x1, cache read x0.1, cache write x1.25 (5 min) / x2 (1 h), output x5; model weights relative to Opus 5. Ratios from Anthropic API pricing (as of 2026-09). Anthropic does not publish the subscription limit formula — this is an approximation.')}\n"
            f"{L('Wygenerowano', 'Generated')} {datetime.datetime.now():%Y-%m-%d %H:%M}.</footer>")


# --------------------------------------------------------------------------- page

def html_report(stats: Stats, ctx: ReportContext, prev: Optional[Stats] = None,
                daily: Optional[List[DayRow]] = None) -> str:
    title = L("Zużycie tokenów", "Token usage")
    head = "\n".join([
        "<!doctype html>",
        f"<html lang={get_lang()}><head><meta charset=utf-8>",
        '<meta name=viewport content="width=device-width,initial-scale=1">',
        f"<title>{title} — Claude Code</title>",
        f"<style>\n{_asset('report.css')}</style></head><body><main>",
        f"<h1>{title} — {E(ctx.label)}</h1>",
        f"<p class=sub>{L('Źródło: lokalne transkrypty Claude Code. Raport nie zużywa tokenów. Najedź lub kliknij „?”, żeby zobaczyć wyjaśnienie.', 'Source: local Claude Code transcripts. This report uses no tokens. Hover or tap “?” for an explanation.')}</p>",
    ])
    tooltip = f"<div id=tip role=tooltip hidden></div>\n<script>\n{_asset('tooltip.js')}</script>"
    return "\n".join([
        head,
        _summary_cards(stats),
        _explanation(),
        _comparison(stats, prev, ctx),
        _daily(daily),
        _token_types(stats),
        _time_chart(stats),
        _groups(stats, ctx),
        _context_length(stats),
        _heaviest_sessions(stats, ctx),
        _cache_and_repeats(stats),
        _tips(stats),
        _footer(),
        "</main>",
        tooltip,
        "</body></html>",
    ])
