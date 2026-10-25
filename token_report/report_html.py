"""The HTML report (--html): one self-contained page, no external resources."""
from __future__ import annotations

import datetime
import html
import os
from typing import Callable, Dict, List, Mapping, Optional, Tuple

from .classify import activity_name
from .context import ReportContext
from .daily import DayRow, daily_summary
from .explain import explain_text
from .formatting import (arrow, fmt_change, fmt_delta, fmt_int, fmt_tok, home_relative, pct,
                         side_name)
from .hotspots import LARGE_FILE, Item, ProjectHotspots, column_name, limits_note, status
from .i18n import L, get_lang, weekday
from .options import no_comparison_note
from .pricing import TOKEN_TYPES, TYPE_WEIGHTS, model_weight, type_name, unknown_models
from .report_text import diff_takeaways
from .session_detail import (SessionDetail, details_for, effort_name, fmt_duration,
                             ultracode_text)
from .stats import (CTX_BUCKETS, FEW_CALLS, GAP_BUCKETS, LONG_CONTEXT, TOP_REBUILDS, Bucket, Stats,
                    cache_hit, ctx_growth, timeline_kind)
from .tips import tips
from .tooltips import help_mark as qm
from .waste import advice, bash_note, skills_note

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
    """--diff: the same parts as report_text.text_diff — the summary numbers always, a table for
    each comparable element of the report, the takeaways, then the elements without a comparison"""
    if prev is None:
        return ""

    def row(name: str, a: float, b: float, fmt: Callable[[float], str]) -> str:
        cls = "up" if a > b else "down"
        return (f"<tr><td class=l>{E(name)}</td><td class=n>{fmt(a)}</td><td class=n>{fmt(b)}</td>"
                f"<td class='n {cls}'>{arrow(a, b)} {fmt_change(a, b)}</td></tr>")

    def table(rows: List[str]) -> str:
        return (f"<div class=wrap><table><tr><th></th><th class=n>{L('teraz', 'now')}</th>"
                f"<th class=n>{L('wcześniej', 'before')}</th><th class=n>{L('zmiana', 'change')}"
                f"</th></tr>{''.join(rows)}</table></div>")

    def groups(title: str, cur: Mapping[str, Bucket], old: Mapping[str, Bucket],
               names: Callable[[str], str] = str) -> str:
        def w(g: Mapping[str, Bucket], key: str) -> float:
            return g[key].weighted if key in g else 0.0
        keys = sorted(set(cur) | set(old), key=lambda k: -w(cur, k) - w(old, k))[:12]
        return f"<h3>{title}</h3>" + table([row(names(k), w(cur, k), w(old, k), fmt_tok)
                                            for k in keys])

    rows = [row(L("wywołania modelu", "model calls"), stats.n_calls, prev.n_calls, fmt_int),
            row(L("tokeny surowe", "raw tokens"), stats.raw or 1, prev.raw, fmt_tok),
            row(L("tokeny ważone", "weighted tokens"), stats.weighted, prev.weighted, fmt_tok)]
    if ctx.has("time"):  # the token types
        rows += [row("\u00a0\u00a0" + type_name(t), stats.weighted_by_type[t],
                     prev.weighted_by_type[t], fmt_tok)
                 for t in TOKEN_TYPES if stats.weighted_by_type[t] or prev.weighted_by_type[t]]
    rows.append(row(L("średnio na wywołanie", "average per call"),
                    stats.weighted / max(stats.n_calls, 1), prev.weighted / max(prev.n_calls, 1),
                    fmt_tok))
    hit_cur, hit_prev = cache_hit(stats.tokens) or 0, cache_hit(prev.tokens) or 0
    cls = "up" if hit_cur > hit_prev else "down"
    rows.append(f"<tr><td class=l>{L('trafienia w cache', 'cache hit rate')}</td>"
                f"<td class=n>{hit_cur:.1f}%</td><td class=n>{hit_prev:.1f}%</td>"
                f"<td class='n {cls}'>{arrow(hit_cur, hit_prev)} {hit_cur - hit_prev:+.1f}pp</td></tr>")
    parts = [f"<h2>{L('Porównanie', 'Comparison')}{qm('compare')}</h2><p class=sub>"
             f"{E(ctx.label)} vs {E(ctx.prev_label)}</p><div class=cmp>", table(rows)]
    if ctx.has("activities"):
        parts.append(groups(L("Na co idą tokeny (ważone)", "Where the tokens go (weighted)"),
                            stats.by_activity, prev.by_activity, activity_name))
    if ctx.has("models"):
        parts.append(groups(L("Modele (ważone)", "Models (weighted)"), stats.by_model,
                            prev.by_model))
    if ctx.has("breakdown"):
        parts.append(groups(L("Projekty (ważone)", "Projects (weighted)"), stats.by_project,
                            prev.by_project))
    takeaways = diff_takeaways(stats, prev, ctx)
    if takeaways:
        items = "".join(f"<li>{E(t)}</li>" for t in takeaways)
        parts.append(f"<h3>{L('Wnioski', 'Takeaways')}</h3><div class=card><ul>{items}</ul></div>")
    note = no_comparison_note(ctx.plan.elements)
    if note:
        parts.append(f"<p class=sub>{E(note)}</p>")
    return "".join(parts) + "</div>"


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


def _activities(stats: Stats, top: int) -> str:
    return (f"<h2>{L('Na co idą tokeny', 'Where the tokens go')}{qm('activity')}</h2>"
            + _breakdown_table(stats.by_activity, stats.weighted or 1e-9,
                               L('czynność', 'activity'), activity_name, top,
                               L('użyć', 'uses'), 'uses'))


def _models(stats: Stats, top: int = 12) -> str:
    model_weight_col = (f"{L('waga', 'weight')}{qm('mweight')}",
                        lambda k: "x" + format(model_weight(k), ".2g"))
    unknown = ""
    if unknown_models():
        unknown = (f"<p class=sub>{L('Nieznane modele liczone z wagą Opus 5', 'Unknown models weighted as Opus 5')}: "
                   f"{E(', '.join(unknown_models()))}</p>")
    return (f"<h2>{L('Modele', 'Models')}{qm('models')}</h2>"
            + _breakdown_table(stats.by_model, stats.weighted or 1e-9, 'model', top=top,
                               extra=model_weight_col) + unknown)


def _breakdowns(stats: Stats, ctx: ReportContext) -> str:
    total = stats.weighted or 1e-9
    agents = ""
    if stats.by_agent_type and not ctx.detail:
        agents = (f"<h2>{L('Subagenci wg typu', 'Subagents by type')}{qm('agents')}</h2>"
                  + _breakdown_table(stats.by_agent_type, total, L('typ', 'type')))
    projects = ""
    if not ctx.session:
        projects = (f"<h2>{L('Projekty', 'Projects')}{qm('projects')}</h2>"
                    + _breakdown_table(stats.by_project, total, L('projekt', 'project')))
    return "\n".join([
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
    top = sorted(stats.by_session.items(), key=lambda kv: -kv[1].weighted)[:ctx.rows + (5 if ctx.plan.long_tables else 0)]
    details = details_for(ctx.calls, ctx.sessions, [k for k, _ in top], ctx.namer)
    rows = ""
    for key, s in top:
        meta = ctx.sessions.get(key)
        topic = ctx.namer.topic(meta.topic if meta else None)
        detail = details.get(key)
        rows += (
            f"<tr class=sess><td class=m><button type=button class=sbtn aria-expanded=false "
            f"title='{L('pokaż szczegóły sesji', 'show session details')}'>"
            f"<i aria-hidden=true>▸</i>{E(key[1][:8])}</button></td>"
            f"<td>{E(ctx.namer.project(meta, key[0]))}"
            f"</td><td class=n>{fmt_tok(s.raw)}</td><td class=n>{fmt_tok(s.weighted)}</td>"
            f"<td class=n>{pct(s.weighted, total):.1f}%"
            f"</td><td class=n>{s.calls}</td><td class=n>{fmt_tok(s.max_context)}</td>"
            f"<td class=n>{pct(s.subagent_weighted, s.weighted):.0f}%</td>"
            f"<td class=t>{E(topic[:100])}</td></tr>")
        if detail:
            rows += (f"<tr class=sdet hidden><td colspan=9>{_session_detail(detail)}</td></tr>")
    return (f"<h2>{L('Najcięższe rozmowy', 'Heaviest conversations')}{qm('sessions')}</h2>"
            f"<p class=sub>{L('Kliknij sesję, żeby zobaczyć jej szczegóły.', 'Click a session to see its details.')}</p>"
            f"<div class=wrap><table class=sessions><tr><th>{L('sesja', 'session')}</th><th>"
            f"{L('projekt', 'project')}</th><th class=n>{_raw_h()}</th>"
            f"<th class=n>{_weighted_h()}{qm('weighted')}</th>"
            f"<th class=n>%</th><th class=n>{_calls_h()}</th><th class=n>"
            f"{L('maks. ctx', 'max ctx')}{qm('maxctx')}</th><th class=n>{L('subag.', 'sub')}"
            f"{qm('subshare')}</th><th>{L('temat', 'topic')}</th></tr>{rows}</table></div>")


# --------------------------------------------------------------------------- one session

def _kv(name: str, value: str) -> str:
    return f"<dt>{name}</dt><dd>{value}</dd>"


def _session_detail(d: SessionDetail) -> str:
    """everything about one session: used in --session and in the heaviest-conversation rows"""
    total = d.weighted or 1e-9
    start, end = d.start.astimezone(), d.end.astimezone()
    until = f"{end:%H:%M}" if end.date() == start.date() else f"{end:%Y-%m-%d %H:%M}"
    efforts = " ".join(
        f"<span class=chip>{E(effort_name(level))} <b>{pct(u.weighted, total):.0f}%</b> "
        f"<small>{u.calls} {L('wyw.', 'calls')}</small></span>" for level, u in d.efforts)
    fast = (L(f"{d.fast.calls} wywołań ({pct(d.fast.weighted, total):.0f}% zużycia)",
              f"{d.fast.calls} calls ({pct(d.fast.weighted, total):.0f}% of usage)")
            if d.fast.calls else L("nie", "no"))
    info = [
        _kv(L("sesja", "session"), f"<span class=m>{E(d.session_id)}</span>"),
        _kv(L("projekt", "project"), E(d.project) + (
            f" <span class=few>· {L('gałąź', 'branch')} {E(d.branch)}</span>" if d.branch else "")),
        _kv(L("czas", "time"), f"{start:%Y-%m-%d %H:%M} → {until} ({fmt_duration(d.duration)})"
            + (f" <span class=few>· Claude Code {E(d.version)}</span>" if d.version else "")),
        _kv(L("rozmowa", "conversation"),
            L(f"prośby: {d.requests}, powiadomienia: {d.notifications}, kompaktowania: "
              f"{d.compactions}, wywołania: {d.calls}, maks. kontekst {fmt_tok(d.max_context)}",
              f"{d.requests} requests, {d.notifications} notifications, {d.compactions} "
              f"compactions, {d.calls} calls, max context {fmt_tok(d.max_context)}")),
        _kv("cache", L(f"odbudowany od nowa <b>{d.rebuilds.count}×</b>"
                       + (f" (nadmiar {fmt_tok(d.rebuilds.waste)}, najdłuższa przerwa {d.rebuilds.longest_gap:.0f} min)" if d.rebuilds.count else ""),
                       f"rewritten <b>{d.rebuilds.count}×</b>"
                       + (f" (extra {fmt_tok(d.rebuilds.waste)}, longest pause {d.rebuilds.longest_gap:.0f} min)" if d.rebuilds.count else ""))),
        _kv(L("długi kontekst", "long context"),
            L(f"<b>{d.long_calls}</b> wywołań na kontekście ≥ {fmt_tok(LONG_CONTEXT)}, kompaktowań: {d.compactions}",
              f"<b>{d.long_calls}</b> calls at a context ≥ {fmt_tok(LONG_CONTEXT)}, compactions: {d.compactions}")
            + (L(f" ({fmt_tok(d.long_weighted)} ważonych)", f" ({fmt_tok(d.long_weighted)} weighted)") if d.long_calls else "")),
        _kv(L("zużycie", "usage"), L(f"<b>{fmt_tok(d.weighted)}</b> ważonych, {fmt_tok(d.raw)} surowych",
                                     f"<b>{fmt_tok(d.weighted)}</b> weighted, {fmt_tok(d.raw)} raw")),
        _kv(f"effort{qm('effort')}", efforts),
        _kv(f"ultracode{qm('ultracode')}", E(ultracode_text(d))),
        _kv(L("tryb fast", "fast mode"), fast),
    ]
    if d.skills:
        info.append(_kv(L("skille", "skills"), E(", ".join(f"{k} ×{n}"
                                                            for k, n in d.skills.most_common()))))
    parts = [f"<dl class=kv>{''.join(info)}</dl>"]

    rows = "".join(
        f"<tr><td class=m>{E(m.model)}</td><td class=n>{m.calls}</td><td class=n>{m.sub_calls}</td>"
        f"<td class=n>{fmt_tok(m.tokens['input'])}</td><td class=n>{fmt_tok(m.tokens['cache_read'])}</td>"
        f"<td class=n>{fmt_tok(m.tokens['cache_write_5m'] + m.tokens['cache_write_1h'])}</td>"
        f"<td class=n>{fmt_tok(m.tokens['output'])}</td><td class=n>{fmt_tok(m.raw)}</td>"
        f"<td class=n><b>{fmt_tok(m.weighted)}</b></td><td class=n>{pct(m.weighted, total):.0f}%</td></tr>"
        for m in d.models)
    parts.append(
        f"<h3>{L('Modele', 'Models')}</h3><div class=wrap><table><tr><th>model</th>"
        f"<th class=n>{_calls_h()}</th><th class=n>{L('w tym subag.', 'of it sub')}</th>"
        f"<th class=n>{L('wejście', 'input')}</th><th class=n>{L('odczyt cache', 'cache read')}</th>"
        f"<th class=n>{L('zapis cache', 'cache write')}</th><th class=n>{L('wyjście', 'output')}</th>"
        f"<th class=n>{L('surowe', 'raw')}</th><th class=n>{_weighted_h()}</th><th class=n>%</th>"
        f"</tr>{rows}</table></div>")

    if d.agents:
        rows = "".join(
            f"<tr><td class=m>{E(a.agent_id[:8])}</td><td>{E(a.agent_type)}</td>"
            f"<td class=m>{E(', '.join(a.models))}</td><td class=n>{a.calls}</td>"
            f"<td class=n>{fmt_tok(a.weighted)}</td><td class=n>{pct(a.weighted, total):.0f}%</td>"
            f"<td class=t title='{E(a.task)}'>{E(a.task)}</td></tr>"
            for a in d.agents)
        parts.append(
            f"<h3>{L('Subagenci', 'Subagents')} ({len(d.agents)})</h3><div class=wrap><table>"
            f"<tr><th>id</th><th>{L('typ', 'type')}</th><th>{L('modele', 'models')}</th>"
            f"<th class=n>{_calls_h()}</th><th class=n>{_weighted_h()}</th><th class=n>%</th>"
            f"<th>{L('zadanie', 'task')}</th></tr>{rows}</table></div>")

    if d.files:
        rows = "".join(
            f"<tr><td class=p>{E(f.name)}</td><td class=n>{f.reads}</td><td class=n>{f.edits}</td>"
            f"<td class=n>{fmt_tok(f.weighted)}</td><td class=n>{pct(f.weighted, total):.0f}%</td></tr>"
            for f in d.files)
        more = (f" <span class=few>· {L('pokazano', 'showing')} {len(d.files)} "
                f"{L('z', 'of')} {d.n_files}</span>" if d.n_files > len(d.files) else "")
        parts.append(
            f"<h3>{L('Pliki', 'Files')}{qm('files')}{more}</h3><div class=wrap><table><tr>"
            f"<th>{L('plik', 'file')}</th><th class=n>{L('odczyty', 'reads')}</th>"
            f"<th class=n>{L('zmiany', 'edits')}</th><th class=n>{_weighted_h()}</th>"
            f"<th class=n>%</th></tr>{rows}</table></div>")

    if d.searches:
        items = "".join(f"<li><code>{E(p)}</code> ×{n}</li>" for p, n in d.searches.most_common())
        parts.append(f"<h3>{L('Najczęstsze wyszukiwania (Grep/Glob)', 'Most frequent searches (Grep/Glob)')}"
                     f"</h3><ul class=srch>{items}</ul>")
    return f"<div class=sd>{''.join(parts)}</div>"


def _single_session(ctx: ReportContext) -> str:
    if not ctx.detail:
        return ""
    return (f"<h2>{L('Szczegóły sesji', 'Session details')}</h2>"
            f"<div class=card>{_session_detail(ctx.detail)}</div>")


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
        _rebuild_details(stats),
        _long_context(stats),
    ])


def _rebuild_details(stats: Stats) -> str:
    rb = stats.rebuilds
    if not rb.count:
        return ""
    gaps = ", ".join(f"{label} min: <b>{rb.by_gap[label]}</b>" for _, label in GAP_BUCKETS)
    rows = (f"<tr><th>{L('sesja', 'session')}</th><th class=n>{L('odbudowy', 'rewrites')}</th>"
            f"<th class=n>{L('nadmiar', 'extra')}</th>"
            f"<th class=n>{L('najdłuższa przerwa', 'longest pause')}</th></tr>")
    for key, sr in sorted(rb.by_session.items(), key=lambda kv: -kv[1].waste)[:TOP_REBUILDS]:
        rows += (f"<tr><td class=m>{E(key[1][:8])}</td><td class=n>{sr.count}</td>"
                 f"<td class=n>{fmt_tok(sr.waste)}</td><td class=n>{sr.longest_gap:.0f} min</td></tr>")
    return (f"<p class=sub>{L('Przerwa przed odbudową', 'Pause before the rewrite')}: {gaps}. "
            f"{L('Cache trwa 5 min albo 1 h. Przerwa krótsza niż jego czas życia („< 5 min”, a przy cache 1 h także „5-60 min”) to odbudowa bez wygaśnięcia z upływu czasu (np. zmiana modelu lub wcześniejszej części rozmowy).', 'The cache lasts 5 minutes or 1 hour. A pause shorter than its lifetime (“< 5 min”, and with the 1-hour cache also “5-60 min”) is a rewrite that time did not cause (e.g. a model switch or a change in an earlier part of the conversation).')}</p>"
            f"<div class=wrap><table>{rows}</table></div>")


def _long_context(stats: Stats) -> str:
    lc = stats.long_context
    head = f"<h3>{L('Długie rozmowy', 'Long conversations')} — {L('kontekst', 'context')} ≥ {fmt_tok(LONG_CONTEXT)}</h3>"
    if not lc.calls:
        return head + f"<p class=sub>{L('Żadna rozmowa nie urosła do tego rozmiaru.', 'No conversation grew to this size.')}</p>"
    total = stats.weighted or 1e-9
    return "\n".join([
        head, "<div class=grid>",
        _card(str(lc.sessions), L("rozmów z takim kontekstem", "conversations that large")),
        _card(str(lc.uncompacted_sessions), L("z nich nigdy nie kompaktowanych", "of them never compacted")),
        _card(f"{pct(lc.weighted, total):.1f}%", f"{L('zużycia to wywołania na dużym kontekście', 'of usage was calls at a large context')} ({lc.calls} {L('wyw.', 'calls')}, {fmt_tok(lc.weighted)})"),
        "</div>",
        f"<p class=sub>{L('To zużycie wywołań na dużym kontekście, nie oszczędność z /compact — jej nie da się policzyć, bo nie wiadomo, jak mały byłby kontekst po kompaktowaniu.', 'This is what the calls at a large context used, not a saving from /compact — that cannot be calculated, as the context after compaction is unknown.')}</p>"])


def _bash_noise(stats: Stats) -> str:
    w = stats.waste
    if not w.bash_results:
        return ""
    total = stats.weighted or 1e-9
    parts = [f"<h2>{L('Szum z poleceń Bash — długie wyniki bez ograniczenia', 'Bash noise — long results with no limit')}{qm('bashnoise')}</h2>",
             "<div class=grid>",
             _card(fmt_int(w.bash_results), L("wyników poleceń Bash", "Bash results")),
             _card(f"~{fmt_tok(w.noisy_tokens)}", L("tokenów w długich wynikach bez ograniczenia", "tokens in long unlimited results")),
             _card(f"{pct(w.noisy_weighted, total):.1f}%", f"{L('zużycia po uwzględnieniu ponownych odczytów', 'of usage counting the re-reads')} ({fmt_tok(w.noisy_weighted)})"),
             "</div>",
             f"<p class=sub>{E(bash_note())}</p>"]
    if not w.families:
        parts.append(f"<p class=sub>{L('Żaden rodzaj polecenia nie powtarza się z długim wynikiem.', 'No kind of command repeats with a long result.')}</p>")
        return "\n".join(parts)
    rows = (f"<tr><th>{L('polecenie', 'command')}</th><th class=n>{L('długich', 'long')}</th>"
            f"<th class=n>{L('z', 'of')}</th><th class=n>{L('tokeny', 'tokens')}</th>"
            f"<th class=n>{L('ważone', 'weighted')}</th><th class=n>max</th>"
            f"<th>{L('zamiast tego', 'instead')}</th></tr>")
    for f in w.families:
        example = "" if stats.hotspots_hidden else \
            f"<br><span class=few>{L('największe', 'largest')}: {E(f.example.replace(chr(10), ' ')[:90])}</span>"
        rows += (f"<tr><td class=p>{E(f.name)}</td><td class=n>{f.unlimited}</td><td class=n>{f.runs}</td>"
                 f"<td class=n>{fmt_tok(f.tokens)}</td><td class=n>{fmt_tok(f.weighted)}</td>"
                 f"<td class=n>{fmt_tok(f.biggest)}</td><td>{E(advice(f.name))}{example}</td></tr>")
    parts.append(f"<div class=wrap><table>{rows}</table></div>")
    return "\n".join(parts)


def _skills(stats: Stats, ctx: ReportContext) -> str:
    sk = stats.waste.skills
    if not (sk.conversations or sk.used):
        return ""
    name = ctx.namer.skill
    parts = [f"<h2>{L('Skille — które się przydają, a które tylko zajmują kontekst', 'Skills — which ones earn their place and which only take up context')}{qm('skills')}</h2>"]
    if sk.conversations:
        parts += ["<div class=grid>",
                  _card(str(len(sk.available)), L("skilli na liście", "skills listed")),
                  _card(f"~{fmt_tok(sk.listing_tokens())}", L("tokenów opisów w każdej rozmowie", "tokens of descriptions in every conversation")),
                  _card(str(len(sk.unused())), f"{L('nieużywanych', 'unused')} (~{fmt_tok(sk.unused_tokens())} {L('tokenów', 'tokens')})"),
                  "</div>"]
    parts.append(f"<p class=sub>{E(skills_note())}</p>")
    rows = ""
    used = sk.used_rows()
    if used:
        rows += f"<tr><th>{L('używane', 'used')}</th><th class=n>{L('rozmowy', 'convs')}</th><th class=n>{L('tokeny opisu', 'description tokens')}</th></tr>"
        rows += "".join(f"<tr><td class=p>{E(name(r.name))}</td><td class=n>{r.uses}</td>"
                        f"<td class=n>{r.tokens or '–'}</td></tr>" for r in used[:ctx.rows])
    unused = sk.unused()
    if unused:
        rows += (f"<tr><th>{L('nieużywane', 'unused')}</th><th class=n>{L('wspomniany', 'named')}</th>"
                 f"<th class=n>{L('tokeny opisu', 'description tokens')}</th></tr>")
        rows += "".join(f"<tr><td class=p>{E(name(r.name))}</td><td class=n>{r.named_in or '–'}</td>"
                        f"<td class=n>{r.tokens}</td></tr>" for r in unused[:ctx.rows * 2])
        if len(unused) > ctx.rows * 2:
            rows += f"<tr><td colspan=3 class=few>{L('… i ' + str(len(unused) - ctx.rows * 2) + ' kolejnych', '… and ' + str(len(unused) - ctx.rows * 2) + ' more')}</td></tr>"
    if rows:
        parts.append(f"<div class=wrap><table>{rows}</table></div>")
    return "\n".join(parts)


def _documented(item: Item) -> str:
    text = E(status(item))
    return f"<b>{text}</b>" if item.documented is False and not item.linked else text


def _hotspot_table(project: ProjectHotspots) -> str:
    in_claude = f"<th>{column_name()}</th>"
    rows = ""
    if project.files:
        rows += (f"<tr><th>{L('plik', 'file')}</th><th class=n>{L('odczyty', 'reads')}</th>"
                 f"<th class=n>{L('rozmowy', 'convs')}</th><th class=n>{L('linie', 'lines')}"
                 f"</th>{in_claude}</tr>")
        for i in project.files:
            large = f" <span class=few>{L('duży', 'large')}</span>" \
                if (i.lines or 0) >= LARGE_FILE else ""
            rows += (f"<tr><td class=p>{E(i.name)}</td><td class=n>{i.uses}</td>"
                     f"<td class=n>{i.sessions}</td><td class=n>"
                     f"{i.lines if i.lines is not None else '–'}{large}</td>"
                     f"<td>{_documented(i)}</td></tr>")
    if project.symbols:
        rows += (f"<tr><th>{L('symbol', 'symbol')}</th><th class=n>{L('szukania', 'lookups')}"
                 f"</th><th class=n>{L('rozmowy', 'convs')}</th><th></th>{in_claude}</tr>")
        for i in project.symbols:
            rows += (f"<tr><td class=p>{E(i.name)}</td><td class=n>{i.uses}</td>"
                     f"<td class=n>{i.sessions}</td><td></td><td>{_documented(i)}</td></tr>")
    return f"<div class=wrap><table>{rows}</table></div>"


def _project_map(stats: Stats) -> str:
    if not stats.hotspots and not stats.hotspots_hidden:
        return ""
    parts = [f"<h2>{L('Mapa projektu — czego Claude szuka w kółko', 'Project map — what Claude looks up again and again')}{qm('projectmap')}</h2>"]
    if stats.hotspots_hidden:
        parts.append(f"<p class=sub>{L('Ukryte z --private (nazwy plików i klas zdradzają projekt).', 'Hidden with --private (file and class names reveal the project).')}</p>")
        return "\n".join(parts)
    parts.append(f"<p class=sub>{E(limits_note())}</p>")
    for project in stats.hotspots:
        if project.instructions:
            loaded = ", ".join(L(f"{f.name} ({f.lines} linii)", f"{f.name} ({f.lines} lines)")
                               for f in project.instructions[:4])
            info = L("instrukcje: ", "instructions: ") + E(loaded)
        else:
            info = L("brak CLAUDE.md — uruchom /init w tym projekcie",
                     "no CLAUDE.md — run /init in this project")
        parts.append(f"<p><b>{E(home_relative(project.root))}</b> <span class=few>· {info}"
                     f"</span></p>")
        parts.append(_hotspot_table(project))
        files_draft, symbols_draft = project.draft_groups()
        if files_draft or symbols_draft:
            text = L("## Mapa projektu", "## Project map")
            for title, lines in ((L("### Pliki", "### Files"), files_draft),
                                 (L("### Symbole", "### Symbols"), symbols_draft)):
                if lines:
                    text += "\n\n" + "\n".join([title] + lines)
            hint = L("Zamień każde „…” jednym zdaniem: po co jest plik lub co robi symbol, np. „układ szablonów reklam; tu resolveLayout”.",
                     "Replace each “…” with one sentence: what the file is for or what the symbol does, e.g. “ad template layout; resolveLayout lives here”.")
            parts.append(f"<details><summary>{L('Szkic do CLAUDE.md dla pozycji „nie znaleziono”', 'Draft for CLAUDE.md for the items marked “not found”')}"
                         f"</summary><p class=sub>{hint}</p><div class=\"card explain\">{E(text)}</div></details>")
    return "\n".join(parts)


_FLAGS = [("time", "--time"), ("breakdown", "--breakdown"), ("cache", "--cache"),
          ("bash", "--bash"), ("skills", "--skills"), ("map", "--project-map")]


def _more(ctx: ReportContext) -> str:
    missing = [f for key, f in _FLAGS if not ctx.has(key)]
    if not missing:
        return ""
    flags = " ".join(f"<code>{f}</code>" for f in missing)
    return (f"<p class=sub>{L('Więcej szczegółów (wygeneruj raport z flagami): ', 'More detail (generate the report with the flags): ')}"
            f"{flags} {L('albo', 'or')} <code>--full</code> {L('(wszystko).', '(everything).')}</p>")


def _tips(stats: Stats, ctx: ReportContext) -> str:
    items = "".join(f"<li>{E(t)}</li>" for t in tips(stats, ctx))
    return (f"<h2>{L('Co można poprawić', 'What you could improve')}{qm('tips')}</h2>"
            f"<div class=card><ul>{items}</ul></div>")


def _footer() -> str:
    return (f"<footer>{L('Wagi rodzajów: wejście x1, odczyt cache x0.1, zapis cache x1.25 (5 min) / x2 (1 h), wyjście x5; wagi modeli względem Opus 5. Proporcje z cennika API Anthropic (stan 2026-10). Anthropic nie publikuje wzoru limitów subskrypcji — to przybliżenie.', 'Type weights: input x1, cache read x0.1, cache write x1.25 (5 min) / x2 (1 h), output x5; model weights relative to Opus 5. Ratios from Anthropic API pricing (as of 2026-10). Anthropic does not publish the subscription limit formula — this is an approximation.')}\n"
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
    tooltip = (f"<div id=tip role=tooltip hidden></div>\n<script>\n{_asset('tooltip.js')}"
               f"{_asset('sessions.js')}</script>")
    optional = [
        _token_types(stats) + _time_chart(stats) if ctx.has("time") else "",
        _breakdowns(stats, ctx) if ctx.has("breakdown") else "",
        _context_length(stats) + _cache_and_repeats(stats) if ctx.has("cache") else "",
        _bash_noise(stats) if ctx.has("bash") else "",
        _skills(stats, ctx) if ctx.has("skills") else "",
        _project_map(stats) if ctx.has("map") else "",
    ]
    return "\n".join([
        head,
        _summary_cards(stats),
        _single_session(ctx),
        _explanation(),
        _comparison(stats, prev, ctx),
        _daily(daily),
        _activities(stats, 20 if ctx.plan.long_tables else 8) if ctx.has("activities") else "",
        _models(stats, ctx.rows) if ctx.has("models") and not ctx.detail else "",
        _heaviest_sessions(stats, ctx) if ctx.has("sessions") else "",
        *optional,
        _tips(stats, ctx) if ctx.has("tips") else "",
        _more(ctx),
        _footer(),
        "</main>",
        tooltip,
        "</body></html>",
    ])
