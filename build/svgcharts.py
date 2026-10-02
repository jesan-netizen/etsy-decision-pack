#!/usr/bin/env python3
"""Inline-SVG chart renderer for the Etsy decision pack.

Reads chart dicts (as found in charts/*.json) and returns self-contained SVG
markup -- no external JS libraries, no fonts, no network. Supports bar,
horizontal_bar, grouped_bar, line, pie, histogram, scatter, heatmap, table.

Chart dict shape (the corpus files):
    {id, title, type, labels: [...], values: [...], note: str}
trends files instead use:
    {id, title, type, unit, period?, source, verified, data: ...}

render(chart) -> ('svg', markup) | ('html', markup)
"""
from __future__ import annotations

import math
import re

# ---------------------------------------------------------------- palette ----
SERIES = ["#4c6350", "#a8543a", "#7c9880", "#c9a227", "#7c8b99", "#8a6e9e",
          "#5e8b7e", "#b5654a", "#6b7f9e", "#96794a"]
PIE = ["#3f5643", "#6b8a6f", "#95ab92", "#b9c9b0", "#d9c9a8", "#c9a227",
       "#a8543a", "#8a6e9e", "#5e8b7e", "#7c8b99", "#b5654a"]
INK = "#2f3d31"
MUTED = "#7b8478"
GRID = "#e2dccb"
AXIS = "#b9c1ae"

W, H = 920, 440
PAD_L, PAD_R, PAD_T, PAD_B = 74, 24, 26, 78


# ----------------------------------------------------------------- helpers ---
def esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(float(v)) else None
    if v is None:
        return None
    try:
        f = float(str(v).strip().replace(",", "").replace("$", "")
                  .replace("%", "").replace("x", "").strip())
        return f if math.isfinite(f) else None
    except (ValueError, TypeError):
        return None


def fmt(v, _=None) -> str:
    if v is None:
        return ""
    a = abs(v)
    if a >= 1_000_000:
        return f"{v/1_000_000:.2f}M".replace(".00M", "M")
    if a >= 10_000:
        return f"{v/1000:.1f}k".replace(".0k", "k")
    if a >= 100:
        return f"{v:,.0f}"
    if a >= 10:
        return f"{v:.1f}".replace(".0", "")
    if a >= 1:
        return f"{v:.2f}".rstrip("0").rstrip(".")
    if a == 0:
        return "0"
    return f"{v:.3f}".rstrip("0").rstrip(".")


def cut(s, n=34):
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "\u2026"


def txt(x, y, s, cls="ax", anchor="middle", extra=""):
    return (f'<text x="{x:.1f}" y="{y:.1f}" class="{cls}" '
            f'text-anchor="{anchor}"{extra}>{esc(s)}</text>')


def nice_ticks(lo, hi, n=5):
    if hi == lo:
        hi = lo + 1
    span = hi - lo
    raw = span / n
    mag = 10 ** math.floor(math.log10(abs(raw))) if raw else 1
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            step = m * mag
            break
    else:
        step = 10 * mag
    start = math.floor(lo / step) * step
    ticks = []
    v = start
    while v <= hi + step * 0.5:
        if v >= lo - step * 1e-9:
            ticks.append(round(v, 10))
        v += step
    return ticks


def svg_open(w, h, title):
    return (f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" '
            f'preserveAspectRatio="xMidYMid meet" '
            f'aria-label="{esc(cut(title, 160))}">'
            f'<title>{esc(title)}</title>')


# ------------------------------------------------------------------- bars ----
def _vbar(labels, values, title):
    """Vertical bars; auto-flips to horizontal when there are many labels."""
    if len(labels) > 13:
        return _hbar(labels, values, title)
    vals = [num(v) for v in values]
    vals = [0.0 if v is None else v for v in vals]
    lo = min(0.0, min(vals)) if vals else 0.0
    hi = max(vals) if vals else 1.0
    ticks = nice_ticks(lo, hi, 5)
    lo, hi = min(lo, ticks[0]), max(hi, ticks[-1])
    iw, ih = W - PAD_L - PAD_R, H - PAD_T - PAD_B
    pw, ph = PAD_L, H - PAD_B

    def sy(v):
        return PAD_T + ih - (v - lo) / (hi - lo) * ih

    out = [svg_open(W, H, title)]
    for t in ticks:
        y = sy(t)
        out.append(f'<line x1="{pw}" y1="{y:.1f}" x2="{W-PAD_R}" y2="{y:.1f}" '
                   f'class="grid"/>')
        out.append(txt(pw - 10, y + 4, fmt(t), "ax tick", "end"))
    bw = iw / len(labels)
    bar = bw * 0.62
    show_vals = len(labels) <= 14
    for i, (lb, v) in enumerate(zip(labels, vals)):
        x = pw + i * bw + (bw - bar) / 2
        y0, y1 = sy(max(0.0, v)), sy(min(0.0, v))
        out.append(f'<rect x="{x:.1f}" y="{min(y0,y1):.1f}" width="{bar:.1f}" '
                   f'height="{max(abs(y1-y0),1.2):.1f}" rx="2.5" '
                   f'fill="{SERIES[i % len(SERIES)]}" class="bar">'
                   f'<title>{esc(lb)}: {esc(fmt(v))}</title></rect>')
        if show_vals:
            vy = y0 - 6 if v >= 0 else y1 + 13
            out.append(txt(x + bar / 2, vy, fmt(v), "val"))
        rot = ' transform="rotate(-32 {0:.1f} {1:.1f})"'.format(
            pw + i * bw + bw / 2, H - PAD_B + 20)
        out.append(txt(pw + i * bw + bw / 2, H - PAD_B + 18,
                       cut(lb, 18 if len(labels) > 8 else 26), "ax lab",
                       extra=rot if len(labels) > 5 or max(len(str(l)) for l in labels) > 9 else ""))
    out.append(f'<line x1="{pw}" y1="{sy(0):.1f}" x2="{W-PAD_R}" '
               f'y2="{sy(0):.1f}" class="axis"/>')
    out.append("</svg>")
    return "".join(out)


def _hbar(labels, values, title):
    vals = [num(v) for v in values]
    vals = [0.0 if v is None else v for v in vals]
    n = len(labels)
    lw = min(300, max(140, int(W * 0.3)))
    ih = H - 56
    row = ih / max(n, 1)
    bh = min(24, row * 0.68)
    show_vals = n <= 40
    m = max(vals) if vals else 1.0
    m = m if m > 0 else 1.0
    out = [svg_open(W, H, title)]
    pw = PAD_L + lw - 12
    iw = W - pw - 92
    for i, (lb, v) in enumerate(zip(labels, vals)):
        y = 34 + i * row
        out.append(txt(pw - 10, y + bh / 2 + 4, cut(lb, 30), "ax lab", "end"))
        w = max(abs(v) / m * iw, 1.5)
        out.append(f'<rect x="{pw}" y="{y:.1f}" width="{w:.1f}" '
                   f'height="{bh:.1f}" rx="2.5" '
                   f'fill="{SERIES[i % len(SERIES)]}" class="bar">'
                   f'<title>{esc(lb)}: {esc(fmt(v))}</title></rect>')
        if show_vals:
            out.append(txt(pw + w + 7, y + bh / 2 + 4, fmt(v), "val", "start"))
    out.append(f'<line x1="{pw}" y1="26" x2="{pw}" y2="{26+ih:.1f}" class="axis"/>')
    out.append("</svg>")
    return "".join(out)


def _grouped_explicit(cats, series):
    """Chart shape {categories:[...], series:[{label, values:[...]}]}."""
    flat = [v for s in series for v in s["values"] if v is not None]
    lo, hi = (min(0, min(flat)), max(flat)) if flat else (0, 1)
    ticks = nice_ticks(lo, hi, 5)
    lo, hi = min(lo, ticks[0]), max(hi, ticks[-1])
    iw, ih = W - PAD_L - PAD_R, H - PAD_T - PAD_B
    pw, ph = PAD_L, H - PAD_B

    def sy(v):
        return PAD_T + ih - (v - lo) / (hi - lo) * ih

    k = len(series)
    out = [svg_open(W, H, "")]
    for t in ticks:
        y = sy(t)
        out.append(f'<line x1="{pw}" y1="{y:.1f}" x2="{W-PAD_R}" y2="{y:.1f}" class="grid"/>')
        out.append(txt(pw - 10, y + 4, fmt(t), "ax tick", "end"))
    cw = iw / len(cats)
    bw = cw * 0.74 / k
    for ci, cat in enumerate(cats):
        x0 = pw + ci * cw + cw * 0.13
        for si, s in enumerate(series):
            v = s["values"][ci] if ci < len(s["values"]) else None
            if v is None:
                continue
            x = x0 + si * bw
            y0, y1 = sy(max(0.0, v)), sy(min(0.0, v))
            out.append(f'<rect x="{x:.1f}" y="{min(y0,y1):.1f}" width="{max(bw-1.5,1.5):.1f}" '
                       f'height="{max(abs(y1-y0),1.2):.1f}" rx="2" '
                       f'fill="{SERIES[si % len(SERIES)]}" class="bar">'
                       f'<title>{esc(cat)} / {esc(s.get("label",""))}: {esc(fmt(v))}</title></rect>')
            if len(cats) <= 8 and k <= 7:
                out.append(txt(x + bw / 2, y0 - 5, fmt(v), "val"))
        lbl = cut(str(cat), max(9, int(58 / max(len(cats) * 1.0, 1)) + 8))
        out.append(txt(pw + ci * cw + cw / 2, ph + 20, lbl, "ax lab",
                       extra=f' transform="rotate(-34 {pw + ci*cw + cw/2:.1f} {ph+20})"'))
    # legend, wrapped onto two rows when long
    items = [cut(str(s.get("label", "")), 30) for s in series]
    lx, ly, per_row = pw, H - 30, max(1, len(items) // 2)
    for si, nm in enumerate(items):
        if si and si % per_row == 0:
            lx, ly = pw, ly + 15
        out.append(f'<rect x="{lx}" y="{ly-9}" width="10" height="10" rx="2" '
                   f'fill="{SERIES[si % len(SERIES)]}"/>')
        out.append(txt(lx + 15, ly, nm, "ax lab", "start"))
        lx += 25 + 6.6 * len(nm)
    out.append(f'<line x1="{pw}" y1="{sy(0):.1f}" x2="{W-PAD_R}" y2="{sy(0):.1f}" class="axis"/>')
    out.append("</svg>")
    return "".join(out)


def _heatmap_rows(chart):
    """{rows:[{weighting, ranks:{D9:1,...}}]} -> ranked matrix, best on top."""
    rows = chart.get("rows") or []
    if not rows:
        return ""
    rlab = chart.get("row_label", "weighting")
    clab = chart.get("col_label", "direction")
    ids = []
    for r in rows:
        for k in r["ranks"]:
            if k not in ids:
                ids.append(k)
    n, m = len(ids), len(rows)
    lw = 210
    iw = W - lw - PAD_R - 8
    cw = iw / n
    rh = min(30, (H - 70) / m)
    top = 46
    def shade(rank):
        # rank 1 = strongest: darker green
        return 0.12 + 0.86 * (1 - (rank - 1) / max(n - 1, 1)) ** 1.5
    out = [svg_open(W, H, chart.get("title", ""))]
    for j, k in enumerate(ids):
        out.append(txt(lw + j * cw + cw / 2, top - 9, k, "ax lab",
                       extra=f' transform="rotate(-40 {lw + j*cw + cw/2:.1f} {top-9})"'))
    out.append(txt(6, 14, clab.upper(), "ax lab", "start"))
    out.append(txt(lw - 8, 14, rlab.upper(), "ax lab", "end"))
    for i, r in enumerate(rows):
        y = top + i * rh
        out.append(txt(lw - 8, y + rh / 2 + 4, cut(str(r[rlab]), 26), "ax lab", "end"))
        for j, k in enumerate(ids):
            rk = r["ranks"].get(k)
            if rk is None:
                continue
            op = shade(rk)
            out.append(f'<rect x="{lw + j*cw + 1:.1f}" y="{y+1:.1f}" '
                       f'width="{max(cw-2,1):.1f}" height="{max(rh-2,1):.1f}" rx="2" '
                       f'fill="#3f5643" fill-opacity="{op:.3f}" class="cell">'
                       f'<title>{esc(str(r[rlab]))} / {esc(k)}: rank {rk}</title></rect>')
            out.append(txt(lw + j * cw + cw / 2, y + rh / 2 + 4, str(rk),
                           "cell-lab"))
    out.append(txt(lw, top + m * rh + 18, "darker = better rank", "ax lab", "start"))
    out.append("</svg>")
    return "".join(out)


def _grouped(chart):
    if chart.get("categories") and isinstance(chart.get("series"), list):
        return _grouped_explicit(chart["categories"], chart["series"])
    labels = [str(l) for l in chart.get("labels", [])]
    raw = chart.get("values", [])
    sep = labels.index("--") if "--" in labels else None

    if sep is not None:
        g1 = list(zip(labels[:sep], raw[:sep]))
        g2 = list(zip(labels[sep + 1:], raw[sep + 1:]))
        cats = [a for a, _ in g1] if len(g1) == len(g2) and g1 else \
               [a for a, _ in (g1 or g2)]
        series = [[num(b) for _, b in g1], [num(b) for _, b in g2]]
        names = ["Series A", "Series B"]
        if g1 and g2:
            s1 = {b for _, b in g1} - {a for a, _ in g1}
            s2 = {b for _, b in g2} - {a for a, _ in g2}
            names = [cut(next(iter(s1), "Series A"), 26),
                     cut(next(iter(s2), "Series B"), 26)]
    else:
        pairs = []
        for lb, v in zip(labels, raw):
            m = re.split(r"\s+[\u2013\u2014-]\s+", lb, maxsplit=1)
            pairs.append((m[0].strip(), m[1].strip() if len(m) > 1 else "Value"))
        cats, names = [], []
        for base, suf in pairs:
            if base not in cats:
                cats.append(base)
            if suf not in names:
                names.append(suf)
        k = len(names)
        grid = [[None] * k for _ in cats]
        ci = {c: i for i, c in enumerate(cats)}
        ni = {s: i for i, s in enumerate(names)}
        for base, suf, v in [(p[0], p[1], r) for p, r in zip(pairs, raw)]:
            grid[ci[base]][ni[suf]] = num(v)
        series = [[g[j] for g in grid] for j in range(k)]

    flat = [v for s in series for v in s if v is not None]
    if not flat:
        flat = [0, 1]
    lo, hi = min(0.0, min(flat)), max(flat)
    ticks = nice_ticks(lo, hi, 5)
    lo, hi = min(lo, ticks[0]), max(hi, ticks[-1])
    iw, ih = W - PAD_L - PAD_R, H - PAD_T - PAD_B
    pw, ph = PAD_L, H - PAD_B

    def sy(v):
        return PAD_T + ih - (v - lo) / (hi - lo) * ih

    k = len(series)
    out = [svg_open(W, H, chart.get("title", "grouped bar"))]
    for t in ticks:
        y = sy(t)
        out.append(f'<line x1="{pw}" y1="{y:.1f}" x2="{W-PAD_R}" y2="{y:.1f}" class="grid"/>')
        out.append(txt(pw - 10, y + 4, fmt(t), "ax tick", "end"))
    cw = iw / len(cats)
    bw = cw * 0.72 / k
    for ci_, cat in enumerate(cats):
        x0 = pw + ci_ * cw + cw * 0.14
        for si, s in enumerate(series):
            v = s[ci_]
            if v is None:
                continue
            x = x0 + si * bw
            y0, y1 = sy(max(0.0, v)), sy(min(0.0, v))
            out.append(f'<rect x="{x:.1f}" y="{min(y0,y1):.1f}" width="{max(bw-2,1.5):.1f}" '
                       f'height="{max(abs(y1-y0),1.2):.1f}" rx="2" '
                       f'fill="{SERIES[si % len(SERIES)]}" class="bar">'
                       f'<title>{esc(cat)} / {esc(names[si])}: {esc(fmt(v))}</title></rect>')
            if len(cats) <= 10:
                out.append(txt(x + bw / 2, y0 - 5, fmt(v), "val"))
        out.append(txt(pw + ci_ * cw + cw / 2, ph + 20, cut(cat, 14), "ax lab",
                       extra=f' transform="rotate(-28 {pw + ci_*cw + cw/2:.1f} {ph+20})"'))
    # legend
    lx = pw
    for si, nm in enumerate(names):
        out.append(f'<rect x="{lx}" y="{H-16}" width="11" height="11" rx="2" '
                   f'fill="{SERIES[si % len(SERIES)]}"/>')
        out.append(txt(lx + 16, H - 6, cut(nm, 34), "ax lab", "start"))
        lx += 26 + 7.2 * len(cut(nm, 34))
    out.append(f'<line x1="{pw}" y1="{sy(0):.1f}" x2="{W-PAD_R}" y2="{sy(0):.1f}" class="axis"/>')
    out.append("</svg>")
    return "".join(out)


# ------------------------------------------------------------------- line ----
def _line(chart):
    data = chart.get("data")
    labels = chart.get("labels")
    values = [num(v) for v in chart.get("values", [])]
    if isinstance(data, dict):                       # multi-series
        order, seen = [], set()
        for s in data.values():
            for k in s:
                if k not in seen:
                    seen.add(k)
                    order.append(k)
        order.sort()
        xs = order
        series = [([num(data[s].get(k)) for k in xs], s) for s in data]
    else:
        xs = [str(l) for l in (labels or [])]
        series = [(values, chart.get("id", "value"))]

    flat = [v for vs, _ in series for v in vs if v is not None]
    lo, hi = (min(flat), max(flat)) if flat else (0, 1)
    if lo == hi:
        lo, hi = lo - 1, hi + 1
    span = hi - lo
    ticks = nice_ticks(lo - span * 0.08, hi + span * 0.08, 5)
    lo, hi = min(lo, ticks[0]), max(hi, ticks[-1])
    iw, ih = W - PAD_L - PAD_R, H - PAD_T - PAD_B - 16
    pw, ph = PAD_L, H - PAD_B

    def sy(v):
        return PAD_T + ih - (v - lo) / (hi - lo) * ih

    n = len(xs)
    out = [svg_open(W, H, chart.get("title", "line"))]

    def sx(i):
        return pw + (iw / (n - 1) * i if n > 1 else iw / 2)

    for t in ticks:
        y = sy(t)
        out.append(f'<line x1="{pw}" y1="{y:.1f}" x2="{W-PAD_R}" y2="{y:.1f}" class="grid"/>')
        out.append(txt(pw - 10, y + 4, fmt(t), "ax tick", "end"))
    for si, (vs, nm) in enumerate(series):
        col = SERIES[si % len(SERIES)]
        run, d = [], []
        for i, v in enumerate(vs):
            if v is None:
                if len(run) > 1:
                    d.append(" ".join(run))
                run = []
                continue
            run.append(f"{'M' if not run else 'L'}{sx(i):.1f},{sy(v):.1f}")
        if len(run) > 1:
            d.append(" ".join(run))
        for path in d:
            out.append(f'<path d="{path}" fill="none" stroke="{col}" stroke-width="2.4" '
                       f'stroke-linejoin="round" stroke-linecap="round"/>')
        for i, v in enumerate(vs):
            if v is None:
                continue
            out.append(f'<circle cx="{sx(i):.1f}" cy="{sy(v):.1f}" r="3.6" fill="{col}" '
                       f'stroke="#fbf7ee" stroke-width="1.6"><title>{esc(nm)} {esc(xs[i])}: '
                       f'{esc(fmt(v))}</title></circle>')
            if n <= 8:
                out.append(txt(sx(i), sy(v) - 11, fmt(v), "val"))
    for i, x in enumerate(xs):
        out.append(txt(sx(i), ph + 20, cut(x, 12), "ax lab",
                       extra=f' transform="rotate(-30 {sx(i):.1f} {ph+20})"'))
    if len(series) > 1:
        lx = pw
        for si, (_, nm) in enumerate(series):
            out.append(f'<rect x="{lx}" y="{H-16}" width="11" height="11" rx="2" '
                       f'fill="{SERIES[si % len(SERIES)]}"/>')
            out.append(txt(lx + 16, H - 6, cut(nm, 30), "ax lab", "start"))
            lx += 26 + 7.2 * len(cut(nm, 30))
    out.append(f'<line x1="{pw}" y1="{PAD_T}" x2="{pw}" y2="{PAD_T+ih:.1f}" class="axis"/>')
    out.append("</svg>")
    return "".join(out)


# -------------------------------------------------------------------- pie ----
def _pie(chart):
    labels = [str(l) for l in chart.get("labels", [])]
    vals = [num(v) or 0.0 for v in chart.get("values", [])]
    tot = sum(vals) or 1.0
    R, cx, cy = 148.0, 190.0, H / 2 - 6
    out = [svg_open(W, H, chart.get("title", "pie"))]
    out.append(f'<circle cx="{cx}" cy="{cy}" r="{R+7}" class="pie-halo"/>')
    ang = -math.pi / 2
    for i, (lb, v) in enumerate(zip(labels, vals)):
        sweep = (v / tot) * 2 * math.pi
        if sweep <= 0:
            continue
        x1, y1 = cx + R * math.cos(ang), cy + R * math.sin(ang)
        ang2 = ang + sweep
        x2, y2 = cx + R * math.cos(ang2), cy + R * math.sin(ang2)
        large = 1 if sweep > math.pi else 0
        col = PIE[i % len(PIE)]
        out.append(
            f'<path d="M{cx:.1f},{cy:.1f} L{x1:.1f},{y1:.1f} '
            f'A{R:.1f},{R:.1f} 0 {large} 1 {x2:.1f},{y2:.1f} Z" fill="{col}" '
            f'class="slice"><title>{esc(lb)}: {esc(fmt(v))} ({v/tot*100:.1f}%)</title></path>')
        if sweep > 0.18:
            mr = R * 0.66
            mx, my = cx + mr * math.cos(ang + sweep / 2), cy + mr * math.sin(ang + sweep / 2)
            out.append(txt(mx, my + 4, f"{v/tot*100:.0f}%", "slice-lab"))
        ang = ang2
    lx = 372
    for i, (lb, v) in enumerate(zip(labels, vals)):
        y = 40 + i * 22
        if y > H - 30:
            break
        out.append(f'<rect x="{lx}" y="{y-10}" width="12" height="12" rx="3" '
                   f'fill="{PIE[i % len(PIE)]}"/>')
        out.append(txt(lx + 19, y, cut(lb, 30), "ax lab", "start"))
        out.append(txt(W - 26, y, f"{fmt(v)}  ({v/tot*100:.1f}%)", "val", "end"))
    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------- scatter ----
def _scatter(chart):
    labels = [str(l) for l in chart.get("labels", [])]
    vals = [num(v) for v in chart.get("values", [])]
    note = str(chart.get("note", ""))
    xs_numeric = all(num(l) is not None for l in labels)
    xs = [num(l) if xs_numeric else float(i) for i, l in enumerate(labels)]
    xs = [v if v is not None else float(i) for i, v in enumerate(xs)]
    ys = [0.0 if v is None else v for v in vals]
    xlo, xhi = min(xs), max(xs)
    ylo, yhi = min(ys), max(ys)
    if xhi == xlo:
        xhi = xlo + 1
    if yhi == ylo:
        yhi = ylo + 1
    ylo = min(0, ylo)
    yt = nice_ticks(ylo, yhi, 5)
    ylo, yhi = min(ylo, yt[0]), max(yhi, yt[-1])
    iw, ih = W - PAD_L - PAD_R - 20, H - PAD_T - PAD_B - 10
    pw, ph = PAD_L, H - PAD_B

    def sx(v):
        return pw + (v - xlo) / (xhi - xlo) * iw

    def sy(v):
        return PAD_T + ih - (v - ylo) / (yhi - ylo) * ih

    out = [svg_open(W, H, chart.get("title", "scatter"))]
    for t in yt:
        y = sy(t)
        out.append(f'<line x1="{pw}" y1="{y:.1f}" x2="{W-PAD_R-20}" y2="{y:.1f}" class="grid"/>')
        out.append(txt(pw - 10, y + 4, fmt(t), "ax tick", "end"))
    for t in nice_ticks(xlo, xhi, 6):
        if t < xlo:
            continue
        out.append(txt(sx(t), PAD_T + ih + 20, fmt(t), "ax tick"))
    for i, (x, y, lb) in enumerate(zip(xs, ys, labels)):
        out.append(f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="5" '
                   f'fill="{SERIES[i % len(SERIES)]}" fill-opacity="0.82" '
                   f'class="dot"><title>{esc(lb)}: x {esc(lb if xs_numeric else i)}, '
                   f'y {esc(fmt(y))}</title></circle>')
        if not xs_numeric and len(labels) <= 60:
            out.append(txt(sx(x) + 7, sy(y) + 3, cut(lb, 16), "pt-lab", "start"))
    mx, my = (xs_numeric and (sum(xs) / len(xs)), sum(ys) / len(ys))
    out.append(f'<line x1="{pw}" y1="{sy(my):.1f}" x2="{W-PAD_R-20}" y2="{sy(my):.1f}" '
               f'class="mean"/>')
    out.append(txt(pw, H - 12, "x = " + ("listing count" if xs_numeric else "shop (ordered)"),
                   "ax lab", "start"))
    out.append(f'<text x="{pw-56}" y="{PAD_T-10}" class="ax lab" text-anchor="start">'
               f'y = revenue per listing</text>')
    out.append(f'<line x1="{pw}" y1="{PAD_T}" x2="{pw}" y2="{PAD_T+ih:.1f}" class="axis"/>')
    out.append(f'<line x1="{pw}" y1="{PAD_T+ih:.1f}" x2="{W-PAD_R-20}" y2="{PAD_T+ih:.1f}" class="axis"/>')
    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------- heatmap ----
def _heatmap(chart):
    labels = [str(l) for l in chart.get("labels", [])]
    vals = [num(v) or 0.0 for v in chart.get("values", [])]
    if not any("::" in l for l in labels):
        return _hbar(labels, vals, chart.get("title", ""))
    rows, cols = [], []
    cells = {}
    for lb, v in zip(labels, vals):
        r, c = [x.strip() for x in lb.split("::", 1)]
        if r not in rows:
            rows.append(r)
        if c not in cols:
            cols.append(c)
        cells[(r, c)] = v
    lw = 150
    iw = W - lw - PAD_R - 8
    cw = iw / len(cols)
    rh = min(26, (H - 78) / len(rows))
    top = 52
    mx = max(cells.values()) or 1.0
    out = [svg_open(W, H, chart.get("title", "heatmap"))]
    for j, c in enumerate(cols):
        out.append(txt(lw + j * cw + cw / 2, top - 8, cut(c.replace("_", " "), 13),
                       "ax lab", extra=f' transform="rotate(-38 {lw + j*cw + cw/2:.1f} {top-8})"'))
    for i, r in enumerate(rows):
        y = top + i * rh
        out.append(txt(lw - 8, y + rh / 2 + 4, cut(r, 20), "ax lab", "end"))
        for j, c in enumerate(cols):
            v = cells.get((r, c), 0.0)
            t = v / mx if mx else 0
            op = 0.10 + 0.88 * (t ** 0.55)
            out.append(f'<rect x="{lw + j*cw + 1:.1f}" y="{y+1:.1f}" '
                       f'width="{max(cw-2,1):.1f}" height="{max(rh-2,1):.1f}" rx="2" '
                       f'fill="#3f5643" fill-opacity="{op:.3f}" class="cell">'
                       f'<title>{esc(r)} / {esc(c)}: {esc(fmt(v))}</title></rect>')
            if cw > 34 and rh > 13:
                out.append(txt(lw + j * cw + cw / 2, y + rh / 2 + 4, fmt(v),
                               "cell-lab"))
    # colour scale
    sy_ = top + len(rows) * rh + 16
    out.append(f'<defs><linearGradient id="hm{abs(hash(chart.get("id","x")))%99999}" '
               f'x1="0" x2="1"><stop offset="0" stop-color="#3f5643" stop-opacity="0.12"/>'
               f'<stop offset="1" stop-color="#3f5643" stop-opacity="1"/></linearGradient></defs>')
    out.append(f'<rect x="{lw}" y="{sy_}" width="180" height="10" rx="5" '
               f'fill="url(#hm{abs(hash(chart.get("id","x")))%99999})"/>')
    out.append(txt(lw - 8, sy_ + 9, "0", "ax tick", "end"))
    out.append(txt(lw + 188, sy_ + 9, fmt(mx), "ax tick", "start"))
    out.append("</svg>")
    return "".join(out)


# ------------------------------------------------------------------ table ----
def _table(chart):
    data = chart.get("data")
    if not isinstance(data, list) or not data:
        return _vbar([str(l) for l in chart.get("labels", [])],
                     chart.get("values", []), chart.get("title", ""))
    keys = []
    for row in data:
        for k in row:
            if k not in keys:
                keys.append(k)
    bad = {"n", "year", "rank", "id"}
    head = [k for k in keys if not (k in bad and len(keys) > 2)]
    head = head[:9]
    out = ['<div class="chart-table-wrap"><table class="chart-table"><thead><tr>']
    for h in head:
        out.append(f"<th>{esc(str(h).replace('_', ' '))}</th>")
    out.append("</tr></thead><tbody>")
    for row in data:
        out.append("<tr>")
        for h in head:
            v = row.get(h, "")
            if isinstance(v, (dict, list)):
                v = json_dumps(v)
            out.append(f"<td>{esc(str(v)[:300])}</td>")
        out.append("</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


def json_dumps(o):
    import json
    try:
        return json.dumps(o, ensure_ascii=False)[:200]
    except (TypeError, ValueError):
        return str(o)[:200]


# ------------------------------------------------------------------- api -----
def _labels_values(chart):
    """Most chart files use labels[]/values[]. The trends file instead stores
    `data: [{label, value, ...}]` with no labels/values keys — without this the
    bar/pie renderers silently draw an empty axis."""
    labels, values = chart.get("labels"), chart.get("values")
    if labels and values:
        return [str(x) for x in labels], list(values)
    data = chart.get("data")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        lab, val = [], []
        for row in data:
            if "label" not in row or "value" not in row:
                return None, None
            lab.append(str(row["label"]))
            val.append(row["value"])
        return lab, val
    return ([str(x) for x in (labels or [])], list(values or []))


def render(chart) -> tuple[str, str]:
    t = str(chart.get("type", "bar")).lower()
    title = str(chart.get("title", chart.get("id", "chart")))
    if t in ("table",):
        return "html", _table(chart)
    if t in ("grouped_bar", "grouped", "multibar"):
        return "svg", _grouped(chart)
    if t in ("line", "line_chart"):
        return "svg", _line(chart)
    if t in ("pie", "donut", "pie_chart"):
        lab, val = _labels_values(chart)
        return "svg", _pie(dict(chart, labels=lab, values=val))
    if t in ("scatter",):
        return "svg", _scatter(chart)
    if t in ("heatmap", "matrix"):
        lab, val = _labels_values(chart)
        if not lab:
            return "svg", _hbar([], [], chart.get("title", ""))
        return "svg", _heatmap(dict(chart, labels=lab, values=val))
    if t in ("heatmap_rows", "rank_matrix"):
        return "svg", _heatmap_rows(chart)
    if t in ("horizontal_bar", "hbar"):
        lab, val = _labels_values(chart)
        return "svg", _hbar(lab, val, title)
    if t in ("pie", "donut", "pie_chart"):
        lab, val = _labels_values(chart)
        return "svg", _pie(dict(chart, labels=lab, values=val))
    labels, values = _labels_values(chart)
    if t == "bar":
        return "svg", _vbar(labels, values, title)
    return "svg", _vbar(labels, values, title)          # bar / histogram default