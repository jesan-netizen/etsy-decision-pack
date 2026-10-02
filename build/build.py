#!/usr/bin/env python3
"""Build the static Etsy decision-pack website into site/.

Reads every markdown report in /home/ubuntu/etsy_research (plus directions/,
case_files/ and charts/*.json) and emits a fully self-contained static site:
HTML pages, inline-SVG figures, a client-side search index and a link checker.

Usage:  /home/ubuntu/.hermes/hermes-agent/venv/bin/python build.py
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import svgcharts                                              # noqa: E402

import markdown                                                # noqa: E402
from markdown.extensions.toc import TocExtension               # noqa: E402
from markdown.extensions.tables import TableExtension           # noqa: E402

ROOT = Path("/home/ubuntu/etsy_research")
SITE = ROOT / "site"
BUILD = SITE / "build"

# --------------------------------------------------------------------- utils --
STOP = set("""the a an and or of to in for on by with from as is are was were be been
this that these those it its into than then so per vs not no all any each every per
page one two three four five six seven eight nine ten top low high new old
figure chart table source note data unit value values label labels share shares
""".split())

ACCENTS = ["#4c6350", "#a8543a", "#7c9880", "#b5822e", "#6b7f9e", "#8a6e9e"]


def slug(s: str) -> str:
    s = re.sub(r"[^\w\s-]", "", str(s).lower())
    s = re.sub(r"[\s_]+", "-", s.strip())
    return re.sub(r"-{2,}", "-", s).strip("-") or "x"


def toks(s: str):
    return {t for t in re.split(r"[^\w]+", str(s).lower()) if len(t) > 2 and t not in STOP}


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def strip_tags(h: str) -> str:
    h = re.sub(r"(?s)<(script|style).*?</\1>", " ", h)
    h = re.sub(r"<[^>]+>", " ", h)
    h = html.unescape(h)
    return re.sub(r"\s+", " ", h).strip()


# ------------------------------------------------------------------ markdown --
MD = markdown.Markdown(
    extensions=[
        "extra", "sane_lists", "admonition",
        TableExtension(),
        "fenced_code",
        TocExtension(
            slugify=lambda s, _s: slug(s), permalink=False, separator="-"),
        "attr_list",
    ],
    extension_configs={
        "codehilite": {"guess_lang": False, "noclasses": False},
    },
    output_format="html5",
)
MD.convert("warmup")


def fix_table_blanks(text: str) -> str:
    """python-markdown only starts a table on a blank-line boundary. These
    reports often run a **bold lead-in** straight into the header row, which
    leaves the raw pipes visible. Insert the missing blank line."""
    lines = text.split("\n")
    out, fence = [], False
    for i, ln in enumerate(lines):
        if ln.strip().startswith("```"):
            fence = not fence
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        is_tbl = re.match(r"^\s*\|", ln)
        nxt_is_sep = bool(re.match(r"^\s*\|[\s:|-]*-[\s:|-]*\|", nxt)) and nxt.count("|") >= 2
        if (not fence and is_tbl and nxt_is_sep and out
                and out[-1].strip() and not re.match(r"^\s*\|", out[-1])
                and out[-1].strip() != ""):
            out.append("")
        out.append(ln)
    return "\n".join(out)


def drop_leading_h1(text: str) -> str:
    """The page already prints the report title as <h1>; don't print it twice."""
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        if not ln.strip():
            continue
        if re.match(r"^#\s+", ln):
            lines[i] = ""          # leave the line, drop the heading
        break
    return "\n".join(lines)


def split_row(ln: str):
    """Split a pipe row on UNESCAPED pipes only. Cells may legitimately contain
    '\\|' (keyword alternations like `WC\\|LINEART`); splitting on those would
    make the row look wider than its header and truncate real data."""
    s = ln.strip()
    s = s[1:] if s.startswith("|") else s
    s = s[:-1] if s.endswith("|") and not s.endswith("\\|") else s
    cells, buf, i = [], [], 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            buf.append(s[i:i + 2])
            i += 2
            continue
        if c == "|":
            cells.append("".join(buf))
            buf = []
        else:
            buf.append(c)
        i += 1
    cells.append("".join(buf))
    return cells


def _ncells(ln: str) -> int:
    return len(split_row(ln))


def normalise_tables(text: str) -> str:
    """Repair pipe tables whose separator row disagrees with the header row
    on column count (python-markdown then refuses the entire block and the
    raw pipes leak into the page). Pad separators and ragged data rows."""
    lines = text.split("\n")
    out, fence, i = [], False, 0
    while i < len(lines):
        ln = lines[i]
        if ln.strip().startswith("```"):
            fence = not fence
        if (not fence and re.match(r"^\s*\|", ln) and i + 1 < len(lines)
                and re.match(r"^\s*\|[\s:|-]*-[\s:|-]*\|", lines[i + 1])
                and lines[i + 1].count("|") >= 2):
            nxt = lines[i + 1]
            want = _ncells(ln)
            if _ncells(nxt) != want:
                sep_cells = split_row(nxt)
                while len(sep_cells) < want:
                    sep_cells.append("---")
                sep_cells = sep_cells[:want]
                nxt = "| " + " | ".join(sep_cells) + " |"
            out.append(ln)
            out.append(nxt)
            i += 2
            # pad (never trim) the data rows of this block to the header width
            while i < len(lines) and re.match(r"^\s*\|", lines[i]) and lines[i].strip():
                cells = split_row(lines[i])
                if len(cells) < want:
                    lines[i] = "| " + " | ".join(cells + [""] * (want - len(cells))) + " |"
                out.append(lines[i])
                i += 1
            continue
        out.append(ln)
        i += 1
    return "\n".join(out)


def md_html(text: str, ids: dict) -> str:
    """Convert a markdown fragment, giving every heading a unique id."""
    text = normalise_tables(fix_table_blanks(text))
    out = MD.reset().convert(text)

    def fix(m):
        tag, attr, body = m.group(1), m.group(2) or "", m.group(3)
        cur = re.search(r'id="([^"]+)"', attr)
        base = cur.group(1) if cur else slug(body)
        key = base
        n = ids.get(key, 0) + 1
        ids[key] = n
        if n > 1:
            key = f"{base}-{n}"
        attr = re.sub(r'\s*id="[^"]*"', "", attr) + f' id="{key}"'
        return f"<{tag}{attr}>{body}</{tag}>"

    out = re.sub(r"<(h[1-6])((?:\s+[^>]*?)?)>(.*?)</\1>", fix, out, flags=re.S)
    # scrollable table wrappers
    out = re.sub(r"<table>", '<div class="tw"><table>', out)
    out = re.sub(r"</table>", "</table></div>", out)
    return out


def split_sections(md: str):
    """-> [(level, heading_text, body_md)] on h1..h3 boundaries."""
    lines = md.split("\n")
    secs, cur_h, cur_lvl, buf = [], "", 0, []
    fence = False
    for ln in lines:
        if ln.strip().startswith("```"):
            fence = not fence
        m = None if fence else re.match(r"^(#{1,4})\s+(.*?)\s*$", ln)
        if m:
            if buf:
                secs.append((cur_lvl, cur_h, "\n".join(buf)))
            cur_lvl, cur_h = len(m.group(1)), m.group(2)
            buf = [ln]
        else:
            buf.append(ln)
    if buf:
        secs.append((cur_lvl, cur_h, "\n".join(buf)))
    return secs


# ------------------------------------------------------------------- figures --
class FigBook:
    def __init__(self):
        self.items = []                     # (chart, id, title, note)

    def add(self, chart, extra_note=""):
        cid = slug(chart.get("id", chart.get("title", "fig")))
        while any(i[1] == cid for i in self.items):
            cid += "-x"
        self.items.append((chart, cid, chart.get("title", cid),
                           " ".join(x for x in (chart.get("note", ""),
                                                extra_note) if x)))
        return cid

    def html(self, chart, cid, title, note):
        kind, mark = svgcharts.render(chart)
        src = chart.get("source")
        second = chart.get("secondary_source") or chart.get("secondary_sources")
        bits = []
        if chart.get("unit"):
            bits.append("Unit: " + str(chart["unit"]))
        if chart.get("period"):
            bits.append("Period: " + str(chart["period"]))
        if src:
            bits.append('Source: <a href="%s" rel="noopener">%s</a>'
                        % (html.escape(str(src)), html.escape(str(src)[:78])))
        if second:
            s = second if isinstance(second, str) else second[0]
            bits.append('Cross-check: <a href="%s" rel="noopener">%s</a>'
                        % (html.escape(str(s)), html.escape(str(s)[:60])))
        if chart.get("verified"):
            bits.append("Source verified")
        if chart.get("caveat"):
            bits.append("Caveat: " + str(chart["caveat"])[:220])
        cap = f"<figcaption>{html.escape(str(note))}</figcaption>" if note else ""
        meta = ('<div class="src">' + " &middot; ".join(bits) + "</div>") if bits else ""
        tag = "Figure"
        return (f'<figure class="fig" id="fig-{cid}">'
                f'<figcaption class="fig-h"><span class="t">{tag} &middot; '
                f'{html.escape(str(title))}</span>'
                f'<span class="id">{html.escape(str(chart.get("id", cid)))}</span>'
                f'</figcaption>'
                f'<div class="fig-plot">{mark}</div>{cap}{meta}</figure>')


def render_sections(secs, fb: FigBook, charts, used):
    """Convert sections to HTML, dropping each chart at its best-matching
    heading. Unmatched charts are returned for a trailing gallery."""
    ids: dict = {}
    out = []
    for lvl, head, body in secs:
        out.append(md_html(body, ids))
        if not charts:
            continue
        # place the best keyword-matching chart at the end of its own section
        ht = toks(head)
        best, score = None, 0
        for ch in charts:
            if ch.get("id") in used:
                continue
            ct = toks(ch.get("title", "")) | toks(ch.get("id", ""))
            s = len(ht & ct)
            if s > score:
                best, score = ch, s
        if best is not None and score >= 1:
            used.add(best.get("id"))
            fb.add(best)
            chart, cid, title, note = fb.items[-1]
            out.append(fb.html(chart, cid, title, note))
    return "\n".join(out), ids


def gallery(charts, fb: FigBook, title="All figures"):
    if not charts:
        return ""
    parts = [f'<h2 id="{slug(title)}">{title}</h2>',
             '<ul class="fig-list">']
    made = []
    for ch in charts:
        cid = fb.add(ch)
        chart, cid2, t2, n2 = fb.items[-1]
        made.append(fb.html(chart, cid2, t2, n2))
        parts.append(f'<li><a href="#fig-{cid}">{html.escape(str(ch.get("title", cid)))}</a></li>')
    parts.append("</ul>")
    parts.append('<div class="fig-grid">' + "".join(made) + "</div>")
    return "\n".join(parts)


# -------------------------------------------------------------------- chrome --
NAV = [
    ("Overview", "index.html", "Overview"),
    ("The Corpus", "corpus/index.html", "corpus"),
    ("Directions", "directions/index.html", "directions"),
    ("Case Files", "shops/index.html", "shops"),
    ("Alfie's Doctrine", "doctrine.html", "doctrine"),
    ("External Trends", "trends.html", "trends"),
    ("Live Recon", "recon.html", "recon"),
    ("Debate", "debate.html", "debate"),
    ("The Brief", "method-plan.html", "brief"),
]
SUBNAV = {
    "corpus": [("Corpus home", "index.html"), ("Young Winners (56)", "yw.html"),
               ("17 Master Shops", "shops17.html"), ("Cross-Corpus Stats", "stats.html"),
               ("Vault Synthesis", "synthesis.html"), ("Lane Catalogue", "lanes.html"),
               ("Faith vs Vintage", "lane-faith-vintage.html"), ("Raw Tables", "tables.html")],
    "directions": None,
    "shops": None,
}


def rel(depth: int) -> str:
    return "../" * depth


def page(*, title, sub, section, depth=0, crumb=(), body, toc=None,
         pager="", lede="", extra_head="", pending=False) -> str:
    r = rel(depth)
    nav = "".join(
        f'<a href="{r}{href}" class="{"on" if section == sect else ""}">{html.escape(label)}</a>'
        for label, href, sect in NAV)
    sb = ""
    if toc:
        items = []
        cur2 = None
        for lvl, t, a in toc:
            if lvl <= 2 and cur2 is not None:
                items.append("</ul>")
                cur2 = None
            if lvl <= 2:
                items.append('<ul class="lvl2">')
                cur2 = lvl
            items.append(f'<a class="{"lvl3" if lvl >= 3 else ""}" href="#{a}">'
                         f'{html.escape(t)}</a>')
        if cur2 is not None:
            items.append("</ul>")
        sb = "".join(items)
    sb = (f'<div class="side" id="side" data-collapsed="0">'
          f'<button class="menu-btn" id="sideToggle" style="width:100%">Hide contents</button>'
          f'<div class="side-body" style="margin-top:12px">{sb}</div></div>') if toc else ""

    cr = ""
    if crumb:
        parts = []
        for i, (t, h) in enumerate(crumb):
            parts.append(f'<a href="{h}">{html.escape(t)}</a>' if h else html.escape(t))
            if i < len(crumb) - 1:
                parts.append('<span style="opacity:.45"> / </span>')
        cr = '<div class="crumb">' + "".join(parts) + "</div>"

    badge = ' <span class="pill pending">pending</span>' if pending else ""
    search = (f'<div class="searchwrap"><input id="q" data-search type="search" '
              f'placeholder="Search the whole pack…" autocomplete="off" spellcheck="false">'
              f'<span class="kbd">/</span><div id="qresults"></div></div>')

    return f"""<!DOCTYPE html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} — Etsy Decision Pack</title>
<meta name="description" content="Etsy decision pack: 73-shop corpus analysis, 14 direction research projects, 75 shop case files, trend research and live page-one recon.">
<link rel="stylesheet" href="{r}assets/site.css">{extra_head}
</head>
<body id="top">
<header class="topbar">
  <div class="topbar-in">
    <a class="brand" href="{r}index.html">
      <span class="brand-mark">E</span>
      <span class="brand-txt"><b>Etsy Decision Pack</b><span>Oct 2026 evidence base</span></span>
    </a>
    <nav class="topnav" id="topnav">{nav}</nav>
    {search}
    <button class="menu-btn" id="menu">Menu</button>
  </div>
</header>
<div class="shell">
  {cr}
  <div class="layout{'' if sb else ' layout-full'}">
    {sb}
    <main class="content">
      <h1>{title}{badge}</h1>
      {f'<p class="lede">{lede}</p>' if lede else ''}
      {body}
      {pager}
    </main>
  </div>
</div>
<footer><div class="foot-in">
  <p><b>Etsy Decision Pack</b> — the complete research base the decision is made from.
  Built from <code>/home/ubuntu/etsy_phase2/*.csv</code>: 73 shops, 40,275 listing rows.
  Evidence only: no listings created, no Kittl credits spent, the final call is the boss's.</p>
  <p>All figures render as inline SVG. No external requests — this site works offline.
  &middot; <a href="{r}search.html">Full-text search</a>
  &middot; <a href="#top">Back to top</a></p>
</div></footer>
<script>window.SP_BASE = "{r}";</script>
<script src="{r}assets/search_index.js"></script>
<script src="{r}assets/site.js"></script>
</body>
</html>"""


def build_toc(body: str):
    """[(level, text, anchor)] from rendered HTML headings."""
    out = []
    for m in re.finditer(r"<(h[1-4])[^>]*id=\"([^\"]+)\"[^>]*>(.*?)</\1>", body, re.S):
        txt = strip_tags(re.sub(r"<a class=\"anchor\".*?</a>", "", m.group(3), flags=re.S))
        lvl = int(m.group(1)[1])
        out.append((lvl, txt, m.group(2)))
    return out


def add_anchors(body: str):
    return re.sub(
        r"<(h[2-4])([^>]*id=\"([^\"]+)\"[^>]*)>(.*?)</\1>",
        r'<\1\2>\4<a class="anchor" href="#\3">#</a></\1>', body, flags=re.S)


def pager_html(prev_p, next_p):
    if not (prev_p or next_p):
        return ""
    out = ['<nav class="pager">']
    if prev_p:
        t, h = prev_p
        out.append(f'<a href="{h}"><div class="d">Previous</div><div class="t">{html.escape(t)}</div></a>')
    else:
        out.append("<span style='flex:1'></span>")
    if next_p:
        t, h = next_p
        out.append(f'<a class="next" href="{h}"><div class="d">Next</div><div class="t">{html.escape(t)}</div></a>')
    out.append("</nav>")
    return "".join(out)


# ------------------------------------------------------------------ chart io --
def charts_of(name):
    p = ROOT / "charts" / name
    d = json.loads(read(p))
    if isinstance(d, dict):
        return d.get("charts", [])
    return d


# ------------------------------------------------------------------ search ix --
SEARCH_DOCS = []
PAGES = []          # (title, url, section, blurb) for the home page cards


def add_docs(url, page_title, body_html, intro=600, section_chars=900):
    """Split a rendered page into one search document per heading section."""
    heads = [(m.start(), m.group(2), strip_tags(re.sub(r"<a class=\"anchor\".*?</a>", "",
                                                       m.group(3), flags=re.S)))
             for m in re.finditer(r"<(h[1-4])[^>]*id=\"([^\"]+)\"[^>]*>(.*?)</\1>",
                                  body_html, re.S)]
    if not heads:
        flat = strip_tags(body_html)[:intro]
        if flat:
            SEARCH_DOCS.append(dict(u=url, t=page_title, pt=page_title, sec=page_title,
                                    a="", b=flat, ht=norm(page_title), h=norm(flat)))
        return
    lead = strip_tags(body_html[:heads[0][0]])[:intro]
    if lead:
        SEARCH_DOCS.append(dict(u=url, t=page_title, pt=page_title,
                                sec=page_title + " — overview", a="",
                                b=lead, ht=norm(page_title),
                                h=norm(page_title + " " + lead)))
    for i, (start, anchor, title) in enumerate(heads):
        end = heads[i + 1][0] if i + 1 < len(heads) else len(body_html)
        text = strip_tags(body_html[start:end])[:section_chars]
        SEARCH_DOCS.append(dict(u=url, t=title or page_title, pt=page_title,
                                sec=title or page_title, a=anchor, b=text,
                                ht=norm(title),
                                h=norm(page_title + " " + title + " " + text)))


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s.$-]", " ", str(s).lower())).strip()


def write(rel_path: str, content: str):
    p = SITE / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def emit(rel_path, **kw):
    body = add_anchors(kw.pop("body"))
    toc = kw.pop("toc", None)
    if toc is None:
        toc = [t for t in build_toc(body) if t[0] <= 3]
    kw["toc"] = toc
    url = rel_path
    out = page(body=body, **kw)
    write(rel_path, out)
    add_docs(url, kw["title"], body)
    PAGES.append((kw["title"], rel_path, kw.get("section", ""), kw.get("blurb", "")))
    return out

# ------------------------------------------------------------------ mapping ---
OUTMAP = {}          # absolute .md path -> site-relative html path
SHOP_SLUG = {}       # shop name -> slug


def register_map():
    """Pre-compute the md -> html map so cross-links resolve."""
    OUTMAP[str(ROOT / "directions_from_data.md").replace("\\", "/")] = "corpus/lanes.html"
    for src, dst in [("yw_analysis.md", "corpus/yw.html"),
                     ("shops17_analysis.md", "corpus/shops17.html"),
                     ("stats_analysis.md", "corpus/stats.html"),
                     ("vault_synthesis.md", "corpus/synthesis.html"),
                     ("lane_faith_vintage.md", "corpus/lane-faith-vintage.html"),
                     ("live_recon.md", "recon.html"),
                     ("alfie_deep.md", "doctrine.html"),
                     ("external_trends.md", "trends.html"),
                     ("everbee_keywords.md", "corpus/keywords.html"),
                     ("wave2_brief.md", "corpus/method.html"),
                     ("_tables.md", "corpus/tables.html"),
                     ("PLAN.md", "method-plan.html"),
                     ("debate_ranking_v2.md", "debate.html"),
                     ("debate_ranking.md", "debate-ranking-v1.html")]:
        OUTMAP[f"{ROOT}/{src}"] = dst
    for f in sorted((ROOT / "directions").glob("*.md")):
        n = f.name[:2]
        OUTMAP[str(f)] = f"directions/d{n}-{slug(f.stem[3:])}.html"
    for f in sorted((ROOT / "case_files").glob("*.md")):
        if f.name == "_INDEX.md":
            OUTMAP[str(f)] = "shops/index.html"
            continue
        OUTMAP[str(f)] = f"shops/{slug(f.stem)}.html"
        SHOP_SLUG[f.stem] = slug(f.stem)


def fix_links(body_html: str, page_rel: str) -> str:
    """Rewrite in-document .md hrefs to their generated .html equivalents."""
    here = os.path.dirname(page_rel)

    def repl(m):
        href = m.group(1)
        if href.startswith(("http://", "https://", "#", "mailto:")):
            return m.group(0)
        key = href.split("#")[0]
        if not key.endswith(".md"):
            return m.group(0)
        target = None
        bases = [ROOT / (here or "."), ROOT / "case_files", ROOT / "directions", ROOT]
        for base in bases:
            cand = os.path.normpath(os.path.join(str(base), key))
            if cand in OUTMAP:
                target = OUTMAP[cand]
                break
        if not target:
            # last resort: match on bare filename (shops/, directions/)
            base_name = os.path.basename(key)
            for cand, out in OUTMAP.items():
                if os.path.basename(cand) == base_name:
                    target = out
                    break
        if not target:
            return m.group(0)
        newp = os.path.relpath(target, here or ".")
        return 'href="%s"' % newp

    return re.sub(r'href="([^"]+)"', repl, body_html)


# --------------------------------------------------------------- report page --
def report_page(*, out, title, section, depth, crumb, md_path, charts=(),
                lede="", pager=("" ), intro_note="", gallery_title="All figures"):
    """Convert one markdown report into one HTML page with its figures."""
    fb = FigBook()
    md = drop_leading_h1(read(md_path))
    secs = split_sections(md)
    used = set()
    body, ids = render_sections(secs, fb, list(charts), used)
    left = [c for c in charts if c.get("id") not in used]
    if left:
        body += "\n" + gallery(left, fb, gallery_title)
    body = fix_links(body, out)
    emit(out, title=title, sub=slug(title), section=section, depth=depth,
         crumb=crumb, body=body, lede=lede, pager=pager)
    return len(fb.items)


# ------------------------------------------------------------------ 1. home ---
def total_figures():
    n = 0
    for f in ("yw_charts.json", "shops17_charts.json", "stats_charts.json",
              "trends_charts.json"):
        n += len(charts_of(f))
    p = ROOT / "charts" / "debate_charts.json"
    if p.exists():
        d = json.loads(read(p))
        ch = d.get("charts", {})
        n += len(ch.values()) if isinstance(ch, dict) else len(ch)
    return n


def total_pages(include_home=True):
    """Pages on disk. Called while building the home page, which has not been
    written yet, so count itself."""
    n = len(list(SITE.rglob("*.html")))
    return n + (1 if include_home else 0)


def build_home(stats):
    cards = []
    card_data = [
        ("The Corpus", "corpus/index.html", "01", ACCENTS[0],
         "73 shops, 40,275 listing rows, merged from the 56 young winners and the "
         "17 master shops. Lane maps, price bands, survival curves, tag discipline.",
         ["Young Winners", "17 Master Shops", "Cross-Corpus Stats", "Vault Synthesis"]),
        ("Directions", "directions/index.html", "02", ACCENTS[1],
         "14 full research projects — market case, competition reality, first 16 "
         "listings, pricing, copy, risks and the case against, each from the corpus.",
         ["14 direction docs", "Prev/next navigation", "Arguments both ways"]),
        ("Shop Case Files", "shops/index.html", "03", ACCENTS[2],
         "One profile per shop: scorecard, three axes, price distribution, bundle "
         "share, tag strategy, trajectory, what to copy, what to avoid, verdict.",
         ["75 shop profiles", "Ranked tables", "Engine classification"]),
        ("Alfie's Doctrine", "doctrine.html", "04", ACCENTS[3],
         "Deep read of the Push to 1K and interview transcripts: ad numbers, the Q4 "
         "doctrine, pricing, cadence, mockups, bundles — and where it contradicts us.",
         ["8 doctrine sections", "Contradictions called out"]),
        ("External Trends", "trends.html", "05", ACCENTS[4],
         "Pinterest Predicts, Etsy's own Seller Trend Report, colour authorities, "
         "eRank keyword ranks and Meta creative benchmarks — every row source-linked.",
         ["131 figures", "Source + caveat per figure"]),
        ("Live Etsy Recon", "recon.html", "06", ACCENTS[5],
         "Page-one captures across six head terms: physical vs digital slots, "
         "buy-box pressure, ad positions, and what a zero-review shop faces.",
         ["6 SERPs captured", "112 page-one listings"]),
        ("Debate Ranking", "debate.html", "07", "#a8543a",
         "One agent argues each direction, a reconciliation agent ranks them. "
         "Pending — the Wave 3 debate output is not written yet.",
         ["Pending", "Placeholder"]),
    ]
    for t, href, n, acc, blurb, meta in card_data:
        pills = "".join(f'<span class="pill plain">{html.escape(x)}</span>' for x in meta)
        cards.append(f'''<a class="card" href="{href}" style="--accent:{acc}">
  <div class="kick">Section {n}</div>
  <h3>{html.escape(t)}</h3>
  <p>{html.escape(blurb)}</p>
  <div class="meta">{pills}</div>
</a>''')

    method = read(ROOT / "PLAN.md")
    ids = {}
    plan_html = md_html(method, ids)
    plan_html = fix_links(plan_html, "index.html")

    s = "".join(f'<div class="stat"><b>{v}</b><span>{html.escape(l)}</span></div>'
                for v, l in stats)
    body = f'''
<div class="hero">
  <h1>Every shop analysed, every lane priced, every argument on the table.</h1>
  <p class="lede">The complete evidence base for one decision: which lane a new Etsy
  shop should enter. Built from the listing CSVs and the page-one captures, with
  nothing rounded in the boss's favour. The final call is his — this is only the evidence.</p>
  <div class="searchwrap hero">
    <input id="q" data-search type="search" placeholder="Search all 100+ pages — a lane, a shop, a figure id, a number…"
           autocomplete="off" spellcheck="false"><span class="kbd">/</span>
    <div id="qresults"></div>
  </div>
</div>

<div class="stats">{s}</div>

<div class="sec-title">The pack <span class="n">seven sections · {total_pages()} pages</span></div>
<div class="grid">{''.join(cards)}</div>

<div class="sec-title">How to read it <span class="n">the brief this pack answers</span></div>
<div class="content">{plan_html}</div>

<div class="note"><b>Units basis is mixed and the pack says so everywhere.</b>
The 56 Young Winners shops are counted on a real 6-month window
(<code>Est. Sales Last 6 Mo</code>). The 17 starred shops only carry
<code>Est. Total Sales</code> — lifetime. Totals are therefore valid for
<i>ranking lanes against each other</i> and are <b>not</b> a market size.
Revenue everywhere is <code>units × listed price</code>: a gross sticker proxy,
before Etsy fees, before the standing sale discount, before COGS.</div>
'''
    body = add_anchors(body)
    write("index.html", page(title="Overview", sub="overview", section="index",
                             depth=0, crumb=(), body=body, toc=None))
    add_docs("index.html", "Overview", body)
    PAGES.append(("Overview", "index.html", "index", ""))


def build_search_page():
    body = '''
<div class="searchwrap hero" style="margin-bottom:22px">
  <input id="pagequery" type="search" placeholder="Search the whole pack…"
         autocomplete="off" spellcheck="false">
  <div id="qresults"></div>
</div>
<p id="pagemeta" class="pill plain">Type a lane, a shop, a figure id or a number.</p>
<div id="pageresults"></div>
<div class="note">The index covers every paragraph of every report in the pack —
the three corpus analyses, all 14 direction projects, all 75 shop case files,
Alfie's doctrine, the external trend research and the live recon. Press
<code>/</code> anywhere to jump back to the search box.</div>
'''
    body = add_anchors(body)
    write("search.html", page(title="Search", sub="search", section="",
                              depth=0, crumb=(("Overview", "index.html"),),
                              body=body, toc=None))
    add_docs("search.html", "Search", body)
    PAGES.append(("Search", "search.html", "", ""))


# --------------------------------------------------------------- 2. corpus ----
def corpus_cards():
    """Card grid for the corpus hub, with per-file chart counts."""
    counts = {"yw": len(charts_of("yw_charts.json")),
              "shops17": len(charts_of("shops17_charts.json")),
              "stats": len(charts_of("stats_charts.json"))}
    items = [
        ("Young Winners Corpus", "yw.html", ACCENTS[0], "56 shops · 26,429 rows · 6-month window",
         "The young-winners deep read: lane map and sub-lane split, per-lane yield, "
         "single vs set vs bundle shapes, 50 leading tags, price bands, age decay "
         "and the survival curve.", counts["yw"], "Deep read"),
        ("17 Master Shops", "shops17.html", ACCENTS[1], "17 shops · 13,846 rows · lifetime units",
         "The mature-shop deep read and the merge into one 73-shop corpus: per-shop "
         "profiles, the lane map by source, price-band yield with the rookie-bias "
         "control, tag leaders and the merged tables.", counts["shops17"], "Deep read"),
        ("Cross-Corpus Statistics", "stats.html", ACCENTS[2], "73 shops · 40,275 rows · both bases",
         "The master yield table (shape × price band × corpus), survival analysis, "
         "elasticity, lane-level yield, the bundle engine and the deliberate "
         "maturity confound.", counts["stats"], "Statistics"),
        ("Vault Synthesis", "synthesis.html", ACCENTS[3], "4 engines · universals · contradictions",
         "The prior vault notes distilled: the four engines with numbers, the "
         "universals, the faith lane both ways, Alfie's teaching by source, and the "
         "contradictions the pack refuses to paper over.", 0, "Synthesis"),
        ("Lane Catalogue", "lanes.html", ACCENTS[4], "22 lanes · 14 aesthetics · 120 directions",
         "What the corpus actually contains, lane by lane: 22 qualified lanes, 14 "
         "aesthetics, 120 qualified directions with units, revenue proxy, yield per "
         "listing and price bands.", 0, "Catalogue"),
        ("Faith vs Vintage", "lane-faith-vintage.html", ACCENTS[5], "2 lanes side by side · live prices",
         "The one contested lane pair, measured live: page one, buy-box price and "
         "discount depth, cart pressure, digital download competition and the vintage "
         "physical-stock lane.", 0, "Lane brief"),
        ("Raw Tables", "tables.html", "#6b7f9e", "every table from the pipeline",
         "The full table set the pipeline emits, unedited — the layer between the "
         "CSVs and the reports.", 0, "Data"),
        ("Keyword Pulls", "keywords.html", "#8a6e9e", "Everbee · 6 head terms",
         "Everbee volume against competition for the six head terms, and why the "
         "faith heads are the only ones with a workable ratio.", 0, "Keywords"),
        ("Method & Waves", "method.html", "#7b8478", "the brief, wave by wave",
         "The brief this pack answers, the wave plan that produced it, and the hard "
         "rules it was built under.", 0, "Method"),
    ]
    out = []
    for t, href, acc, meta, blurb, nf, kick in items:
        badge = (f'<span class="pill">{nf} figures</span>' if nf else
                 '<span class="pill plain">no charts</span>')
        out.append(f'''<a class="card" href="{href}" style="--accent:{acc}">
  <div class="kick">{html.escape(kick)}</div>
  <h3>{html.escape(t)}</h3>
  <p>{html.escape(blurb)}</p>
  <div class="meta"><span class="pill plain">{html.escape(meta)}</span>{badge}</div>
</a>''')
    return "".join(out)


def build_corpus():
    yw = charts_of("yw_charts.json")
    s17 = charts_of("shops17_charts.json")
    st = charts_of("stats_charts.json")
    cr = [("Overview", "index.html"), ("The Corpus", "index.html")]

    report_page(out="corpus/yw.html", title="Young Winners Corpus — Deep Analysis",
                section="corpus", depth=1, crumb=cr,
                md_path=ROOT / "yw_analysis.md", charts=yw,
                lede="56 young winners, 26,429 listing rows, counted on a real "
                     "6-month sales window. The lane map, what each lane actually "
                     "yields, and the shape decision that drives everything.",
                pager=pager_html(("Cross-Corpus Statistics", "stats.html"),
                                 ("17 Master Shops", "shops17.html")))
    report_page(out="corpus/shops17.html", title="17 Master Shops & the Merged 73-Shop Corpus",
                section="corpus", depth=1, crumb=cr,
                md_path=ROOT / "shops17_analysis.md", charts=s17,
                lede="The 17 starred shops on lifetime units, merged with the 56 "
                     "young winners into one corpus — with the maturity confound "
                     "stated rather than hidden.",
                pager=pager_html(("Young Winners Corpus", "yw.html"),
                                 ("Cross-Corpus Statistics", "stats.html")))
    report_page(out="corpus/stats.html", title="Cross-Corpus Statistical Analysis",
                section="corpus", depth=1, crumb=cr,
                md_path=ROOT / "stats_analysis.md", charts=st,
                lede="The master yield table by shape, price band and corpus; what "
                     "sells nothing; where elasticity actually shows up; and the "
                     "two samples the pack refuses to pretend are the same.",
                pager=pager_html(("17 Master Shops", "shops17.html"),
                                 ("Vault Synthesis", "synthesis.html")))
    for src, out, t, lede, pv, nx in [
        ("vault_synthesis.md", "corpus/synthesis.html", "Master Vault Synthesis",
         "The prior vault notes distilled into four engines, the universals that hold "
         "across all of them, and the contradictions left standing.",
         ("Cross-Corpus Statistics", "stats.html"), ("Lane Catalogue", "lanes.html")),
        ("directions_from_data.md", "corpus/lanes.html", "What the 73-Shop Corpus Contains",
         "22 qualified lanes, 14 aesthetics, 120 qualified directions — every one "
         "with the count that sizes it and the yield that decides it.",
         ("Vault Synthesis", "synthesis.html"), ("Faith vs Vintage", "lane-faith-vintage.html")),
        ("lane_faith_vintage.md", "corpus/lane-faith-vintage.html",
         "Faith vs Vintage — the contested lane pair, measured live",
         "The one pair the pack argues about, priced from live page one: buy-box "
         "depth, cart pressure and what each lane's page one actually holds.",
         ("Lane Catalogue", "lanes.html"), ("Alfie's Doctrine", "../doctrine.html")),
        ("_tables.md", "corpus/tables.html", "Raw Pipeline Tables",
         "Every table the pipeline emits, unedited — the layer between the CSVs and "
         "the reports.",
         ("Faith vs Vintage", "lane-faith-vintage.html"), ("Keyword Pulls", "keywords.html")),
        ("everbee_keywords.md", "corpus/keywords.html", "Everbee Keyword Pulls",
         "Volume against competition for the six head terms, and the ratio that "
         "rules the generic ones out.",
         ("Raw Pipeline Tables", "tables.html"), ("Method & Waves", "method.html")),
        ("wave2_brief.md", "corpus/method.html", "Method & Waves",
         "The brief this pack answers, the wave plan that produced it, and the hard "
         "rules it was built under.",
         ("Keyword Pulls", "keywords.html"), ("Directions", "../directions/index.html")),
    ]:
        report_page(out=out, title=t, section="corpus", depth=1, crumb=cr,
                    md_path=ROOT / src, lede=lede, pager=pager_html(pv, nx))

    nf = {p.stem: read(p) for p in (ROOT / "case_files").glob("*.md")}
    body = f'''<p class="lede">One corpus, three reads. The 56 young winners are
counted on a 6-month window; the 17 master shops only carry lifetime units. Both are
real, they are not comparable, and every page below says which basis it uses.</p>
<div class="note"><b>Read the young-winners file first.</b> It holds the lane map and
the sub-lane split that the other two reports then test against a mature sample and
then re-test statistically.</div>
<div class="stats">
  <div class="stat"><b>73</b><span>shops in corpus</span></div>
  <div class="stat"><b>40,275</b><span>listing rows</span></div>
  <div class="stat"><b>56</b><span>young winners, 6mo</span></div>
  <div class="stat"><b>17</b><span>starred, lifetime</span></div>
  <div class="stat"><b>{len(yw) + len(s17) + len(st)}</b><span>figures</span></div>
</div>
<div class="sec-title">The reports <span class="n">three deep reads, four supporting</span></div>
<div class="grid">{corpus_cards()}</div>'''
    body = add_anchors(body)
    write("corpus/index.html", page(title="The Corpus", sub="corpus", section="corpus",
                                    depth=1, crumb=cr, body=body, toc=None))
    add_docs("corpus/index.html", "The Corpus", body)
    PAGES.append(("The Corpus", "corpus/index.html", "corpus", ""))


# ----------------------------------------------------------- 3. directions ----
DIR_ACC = ["#4c6350", "#a8543a", "#7c9880", "#b5822e", "#6b7f9e", "#8a6e9e",
           "#5e8b7e", "#b5654a", "#7c8b99", "#96794a", "#4c6350", "#a8543a",
           "#7c9880", "#b5822e"]


def dir_summary(md: str, limit=240):
    """First real sentence(s) of section 1, markdown-stripped."""
    m = re.search(r"^##\s*1\..*$", md, re.M)
    if not m:
        return ""
    tail = md[m.end():]
    tail = re.split(r"^##\s", tail, maxsplit=1, flags=re.M)[0]
    lines = [l for l in tail.split("\n") if l.strip() and not l.startswith("|")]
    txt = " ".join(lines)
    txt = re.sub(r"[*_`>#]", "", txt)
    txt = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    if len(txt) > limit:
        cut = txt[:limit]
        dot = cut.rfind(". ")
        txt = (cut[: dot + 1] if dot > limit * 0.55 else cut.rsplit(" ", 1)[0] + "…")
    return txt


def build_directions():
    files = sorted((ROOT / "directions").glob("*.md"))
    entries = []
    for i, f in enumerate(files, start=1):
        md = read(f)
        title = re.search(r"^#\s+(.*?)\s*$", md, re.M).group(1)
        title = re.sub(r"^DIRECTION\s+\d+\s*[—–-]\s*", "", title, flags=re.I).strip()
        out = f"directions/d{i:02d}-{slug(f.stem[3:])}.html"
        entries.append(dict(n=i, f=f, out=out, title=title, md=md,
                            blurb=dir_summary(md),
                            tables=md.count("\n|"),
                            words=len(md.split())))

    for i, e in enumerate(entries):
        prev_ = entries[i - 1] if i else None
        next_ = entries[i + 1] if i + 1 < len(entries) else None
        pv = pager_html((f"{prev_['n']}. {prev_['title']}", prev_["out"].split("/")[-1])
                        if prev_ else ("The Corpus", "../corpus/index.html"),
                        (f"{next_['n']}. {next_['title']}", next_["out"].split("/")[-1])
                        if next_ else ("Shop Case Files", "../shops/index.html"))
        report_page(out=e["out"], title=f"{e['n']}. {e['title']}",
                    section="directions", depth=1,
                    crumb=(("Overview", "../index.html"), ("Directions", "index.html")),
                    md_path=e["f"], lede=e["blurb"], pager=pv)

    cards = []
    for i, e in enumerate(entries):
        acc = DIR_ACC[i % len(DIR_ACC)]
        cards.append(f'''<a class="card" href="{e['out'].split("/")[-1]}" style="--accent:{acc}">
  <div class="kick">Direction {e['n']:02d}</div>
  <h3>{html.escape(e['title'])}</h3>
  <p>{html.escape(e['blurb'])}</p>
  <div class="meta"><span class="pill plain">{e['words']:,} words</span>
  <span class="pill plain">{e['tables']} table rows</span></div>
</a>''')
    body = f'''<p class="lede">Fourteen full research projects, one per direction.
Each is written from the corpus numbers, not from taste: the market case, who owns it
and what they earn, what a zero-review shop actually faces on page one, the first 16
listings, the copy, the production plan, a launch simulation, the risks, and the case
against — including what would kill it.</p>
<div class="stats">
  <div class="stat"><b>14</b><span>direction projects</span></div>
  <div class="stat"><b>{sum(e['words'] for e in entries):,}</b><span>words</span></div>
  <div class="stat"><b>{sum(e['tables'] for e in entries):,}</b><span>table rows</span></div>
  <div class="stat"><b>73</b><span>shops of evidence</span></div>
</div>
<div class="note"><b>Read them in order, then read the debate.</b> Directions 1–12 are
candidate lanes. Direction 13 is the endgame — the physical tier a digital shop adds
later, not a launch state. Direction 14 is the small room-specific humour lane, held
as the low-cost control. The ranking that compares them is
<a href="../debate.html">pending Wave 3</a>.</div>
<div class="grid">{''.join(cards)}</div>'''
    body = add_anchors(body)
    write("directions/index.html", page(title="Directions", sub="directions",
                                        section="directions", depth=1,
                                        crumb=(("Overview", "../index.html"),),
                                        body=body, toc=None))
    add_docs("directions/index.html", "Directions", body)
    PAGES.append(("Directions", "directions/index.html", "directions", ""))
    return entries


# ------------------------------------------------------------ 4. case files ---
def parse_shop_index(md: str):
    """Pull shop rows out of the _INDEX.md ranking tables."""
    rows = {}
    for line in md.split("\n"):
        if not line.startswith("| [") or line.count("|") < 4:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        m = re.match(r"\[([^\]]+)\]\(([^)]+)\)", cells[0])
        if not m:
            continue
        name, f = m.group(1), m.group(2)
        rec = dict(name=name, file=f, cells=cells[1:])
        rows[f[:-3] if f.endswith(".md") else f] = rec
    return rows


def shop_card(rec, acc):
    cells = rec["cells"]
    # normalise: the 9-col revenue table is the richest common shape
    meta = " · ".join(c for c in cells[:5] if c)
    if len(cells) >= 9:
        lane, bundle, dead = cells[6], cells[7], cells[8]
    elif len(cells) >= 5:
        lane, bundle, dead = cells[3], "", ""
    else:
        lane, bundle, dead = (cells[-1] if cells else ""), "", ""
    pills = []
    if cells and re.match(r"^[\d,]+$", cells[0] or ""):
        pills.append(cells[0] + " listings")
    if len(cells) > 1 and re.match(r"^[\d,]+$", cells[1] or ""):
        pills.append(cells[1] + " sales")
    if len(cells) > 3 and cells[3].startswith(("$", "GBP", "INR", "EUR")):
        pills.append(cells[3] + "/mo")
    return f'''<a class="card" href="{slug(rec['name'])}.html" style="--accent:{acc}">
  <div class="kick">{html.escape(lane[:44] or 'shop')}</div>
  <h3>{html.escape(rec['name'])}</h3>
  <div class="meta">{''.join(f'<span class="pill plain">{html.escape(p)}</span>' for p in pills)}
  {'<span class="pill plain">bundle ' + html.escape(bundle) + '</span>' if bundle else ''}
  {'<span class="pill plain">dead ' + html.escape(dead) + '</span>' if dead else ''}</div>
</a>''', meta


def build_shops():
    idx_md = read(ROOT / "case_files" / "_INDEX.md")
    rows = parse_shop_index(idx_md)
    files = sorted(f for f in (ROOT / "case_files").glob("*.md") if f.name != "_INDEX.md")
    slugs = [slug(f.stem) for f in files]

    for i, f in enumerate(files):
        md = read(f)
        pv = pager_html(("Shop index", "index.html"),
                        (files[i + 1].stem, slugs[i + 1] + ".html") if i + 1 < len(files)
                        else ("Directions", "../directions/index.html"))
        report_page(out=f"shops/{slug(f.stem)}.html", title=f"{f.stem} — full shop profile",
                    section="shops", depth=1,
                    crumb=(("Overview", "../index.html"), ("Case Files", "index.html")),
                    md_path=f, pager=pv)

    cards = []
    for i, f in enumerate(files):
        rec = rows.get(f.stem, dict(name=f.stem, cells=[]))
        rec["name"] = rec.get("name") or f.stem
        card, _ = shop_card(rec, DIR_ACC[i % len(DIR_ACC)])
        cards.append(card)

    idx_body = add_anchors(md_html(idx_md, {}))
    idx_body = fix_links(idx_body, "shops/index.html")
    idx_body = re.sub(r"\[([^\]]+)\]\(([^)]+)\.md\)",
                      lambda m: f'<a href="{slug(m.group(1))}.html">{m.group(1)}</a>',
                      idx_body)

    body = f'''<p class="lede">75 shop profiles, one per shop, every figure read from
the listing CSVs or computed from their columns by a rule stated in the file that uses
it. Nothing hand-estimated. Each file gives the scorecard, the three axes, the price
distribution, the top listings, bundle share, tag strategy, trajectory, what to copy,
what to avoid, and the verdict.</p>
<div class="stats">
  <div class="stat"><b>75</b><span>shop profiles</span></div>
  <div class="stat"><b>73</b><span>with listing rows</span></div>
  <div class="stat"><b>4</b><span>engines + 5 other shapes</span></div>
  <div class="stat"><b>13</b><span>sections per file</span></div>
</div>
<div class="note"><b>Two units bases, and every file says which it uses.</b>
Young Winners listings count <code>Est. Sales Last 6 Mo</code> — a real 6-month window.
The 17 starred shops carry only <code>Est. Total Sales</code>, so every listing-level
share in those files is a <b>lifetime</b> share, not a recent-velocity one.</div>
<div class="sec-title">All shops <span class="n">{len(files)} profiles, alphabetical</span></div>
<div class="grid">{''.join(cards)}</div>
<div class="sec-title">Index &amp; rankings <span class="n">as compiled</span></div>
<div class="content">{idx_body}</div>'''
    body = add_anchors(body)
    write("shops/index.html", page(title="Shop Case Files", sub="case-files",
                                   section="shops", depth=1,
                                   crumb=(("Overview", "../index.html"),),
                                   body=body, toc=None))
    add_docs("shops/index.html", "Shop Case Files", body)
    PAGES.append(("Shop Case Files", "shops/index.html", "shops", ""))
    return len(files)


# ------------------------------------------------- 5. doctrine / trends / recon --
def build_single_reports():
    cr = [("Overview", "index.html")]
    report_page(out="doctrine.html", title="Alfie's Doctrine",
                section="doctrine", depth=0, crumb=cr,
                md_path=ROOT / "alfie_deep.md",
                lede="A deep read of the Push to 1K course, the interviews and the "
                     "Jul–Sep 2026 calls: the ad numbers, the Q4 doctrine, pricing, "
                     "cadence, mockup rules, bundles — and the places where it "
                     "contradicts what this pack wants to do.",
                pager=pager_html(("Live Etsy Recon", "recon.html"),
                                 ("External Trends", "trends.html")))
    tr = charts_of("trends_charts.json")
    report_page(out="trends.html", title="External Trends — Digital Wall Art",
                section="trends", depth=0, crumb=cr,
                md_path=ROOT / "external_trends.md", charts=tr,
                lede="Pinterest Predicts, Etsy's own Seller Trend Report, the colour "
                     "authorities, eRank's quarterly keyword ranks and Meta's creative "
                     "benchmarks. Every row carries its source URL and its caveat.",
                pager=pager_html(("Alfie's Doctrine", "doctrine.html"),
                                 ("Live Etsy Recon", "recon.html")),
                gallery_title="Trend figures")
    report_page(out="recon.html", title="Live Etsy Recon — Page One, 2 Oct 2026",
                section="recon", depth=0, crumb=cr,
                md_path=ROOT / "live_recon.md",
                lede="What is actually ranking today, across six head terms: physical "
                     "against digital slots, buy-box price and discount depth, ad "
                     "positions, and what a zero-review shop faces on page one.",
                pager=pager_html(("External Trends", "trends.html"),
                                 ("Debate Ranking", "debate.html")))


# ------------------------------------------------------------- 6. debate page --
def debate_chart_set():
    """charts/debate_charts.json uses {meta, directions, charts:{id:chart}}."""
    p = ROOT / "charts" / "debate_charts.json"
    if not p.exists():
        return [], None
    d = json.loads(read(p))
    ch = d.get("charts", {})
    out = list(ch.values()) if isinstance(ch, dict) else list(ch)
    return out, d.get("meta")


def build_debate():
    # v2 supersedes v1; v1 (debate_ranking.md) is kept unaltered for the record
    # and linked in the note below rather than being the source of the page.
    md = ROOT / "debate_ranking_v2.md"
    charts, meta = debate_chart_set()
    exists = md.exists()
    if exists:
        # ranked leaderboard, built from the chart JSON rather than scraped
        lead = ""
        p = ROOT / "charts" / "debate_charts.json"
        if p.exists():
            d = json.loads(read(p))
            dirs = sorted(d.get("directions", []), key=lambda x: x.get("rank", 99))
            crit = list((dirs[0].get("scores", {}) or {}).keys()) if dirs else []
            head = "".join(f"<th>{html.escape(c)}</th>" for c in crit)
            rws = []
            for dd in dirs:
                doc = dd.get("doc", "")
                href = ""
                if doc:
                    key = os.path.normpath(os.path.join(str(ROOT / "directions"), doc))
                    if key in OUTMAP:
                        href = os.path.relpath(OUTMAP[key], ".")
                name = (f'<a href="{href}">{html.escape(dd["name"])}</a>'
                        if href else html.escape(dd["name"]))
                sc = dd.get("scores", {})
                cells = "".join(
                    f'<td style="text-align:center">{sc.get(c, "—")}</td>'
                    for c in crit)
                rws.append(
                    f'<tr><td style="text-align:center"><b>{dd.get("rank","")}</b></td>'
                    f'<td>{name}</td>{cells}'
                    f'<td style="text-align:right"><b>{dd.get("weighted_total","")}</b></td></tr>')
            lead = f'''<h2 id="the-ranking">The ranking</h2>
<p>The reconciliation agent scored all 14 directions on seven criteria, each 0–10,
and weighted them: launch-tenure yield 0.20, market depth 0.15, competition openness
0.15, production cost 0.10, IP risk 0.10, doctrine fit 0.15, risk profile 0.15.
<b>Launch-tenure yield carries the heaviest weight</b> because it is the only criterion
measured on the population a launch shop is actually in.</p>
<div class="tw"><table><thead><tr><th style="text-align:center">#</th><th>Direction</th>
{head}<th style="text-align:right">Weighted</th></tr></thead>
<tbody>{''.join(rws)}</tbody></table></div>
<p class="tbl-note">Scores 0–10. Higher is better on every criterion, including
production cost and IP risk. Click a direction for its full research project.</p>
<div class="note"><b>Version.</b> This is the <b>v2</b> ranking — the repaired scoring,
re-derived on a single declared basis after four independent reviews. It supersedes
<b>v1</b>, which is retained unaltered for the record as
<a href="debate-ranking-v1.html">debate_ranking.md (v1)</a>.</div>'''

        report_page(out="debate.html", title="Debate Ranking — all 14 directions scored",
                    section="debate", depth=0, crumb=[("Overview", "index.html")],
                    md_path=md, charts=charts,
                    lede="One arguing agent per direction, then a reconciliation agent "
                         "that scores all 14 against each other on seven criteria. "
                         "The final call is the boss's.",
                    pager=pager_html(("Live Etsy Recon", "recon.html"),
                                     ("Overview", "index.html")),
                    gallery_title="Debate figures")
        if lead:
            # insert the leaderboard just after the page's opening block
            out = SITE / "debate.html"
            t = out.read_text(encoding="utf-8")
            anchor = '<h2 id="1-what-the-arguments'
            i = t.find(anchor)
            if i < 0:
                i = t.find('<h2 id="')
            if i > 0:
                t = t[:i] + lead + "\n" + t[i:]
            else:
                t = t.replace("</main>", lead + "</main>")
            out.write_text(t, encoding="utf-8")

        # v1, kept for the record: rendered without the v2 charts so its
        # figures cannot be mistaken for the current ranking.
        v1 = ROOT / "debate_ranking.md"
        if v1.exists():
            report_page(out="debate-ranking-v1.html",
                        title="Debate Ranking v1 (superseded — for the record)",
                        section="debate", depth=0,
                        crumb=[("Overview", "index.html"),
                               ("Debate Ranking", "debate.html")],
                        md_path=v1,
                        lede="<b>Superseded.</b> This is the original v1 debate ranking, "
                             "retained unaltered for the record after four independent "
                             "reviews found three decision-blocking defects. The current "
                             "ranking is <a href=\"debate.html\">v2</a>.",
                        pager=pager_html(("Debate Ranking (v2)", "debate.html"),
                                         ("Overview", "index.html")))
        return True

    dirs = sorted((ROOT / "directions").glob("*.md"))
    rows = []
    for i, f in enumerate(dirs, start=1):
        md_ = read(f)
        t = re.sub(r"^DIRECTION\s+\d+\s*[—–-]\s*", "",
                   re.search(r"^#\s+(.*?)\s*$", md_, re.M).group(1), flags=re.I).strip()
        verdicts = re.findall(r"^##+\s*(.*?(?:verdict|recommendation|recommend).*)$",
                              md_, re.M | re.I)
        v = verdicts[0].strip() if verdicts else "— section not present in this file"
        rows.append(f"""<tr><td><a href="directions/d{i:02d}-{slug(f.stem[3:])}.html">
  <b>{i:02d}</b></a></td><td><a href="directions/d{i:02d}-{slug(f.stem[3:])}.html">
  {html.escape(t)}</a></td><td>{html.escape(v[:90])}</td><td class="pill plain">not yet argued</td></tr>""")

    body = f'''<div class="note pending"><b>This page is a placeholder.</b>
The Wave 3 route debate — one arguing agent per direction, then a reconciliation agent
that ranks them — has not produced <code>debate_ranking.md</code> yet. The page is
built, linked and ready; the ranking is what is missing. Nothing here is a substitute
for it, and the boss's decision is explicitly reserved for him.</div>

<h2 id="what-this-page-will-hold">What this page will hold</h2>
<ul>
  <li><b>The argument per direction.</b> Each of the 14 agents argues its own
  direction from the Wave 1 numbers and its own Wave 2 research project — the upside
  first, then the case against, then what would kill it.</li>
  <li><b>The reconciliation.</b> A ranking agent reads all 14 arguments and ranks them
  on the pack's own criteria: cell size, yield per listing, revenue per listing, the
  live competition a zero-review shop faces, price-band reality and execution risk.</li>
  <li><b>The unresolved rows.</b> Where two arguments cannot both be true, the debate
  says so rather than splitting the difference silently.</li>
</ul>

<h2 id="the-14-candidates">The 14 candidates awaiting an argument</h2>
<p>Every direction below already has its full research project — market case,
competition, first 16 listings, pricing, copy, production, launch simulation, risks.
Click through for the evidence; the <em>argument</em> and the <em>rank</em> are the
two columns still empty.</p>
<div class="tw"><table><thead><tr><th>#</th><th>Direction</th>
<th>Verdict section in its own doc</th><th>Debate status</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>

<h2 id="what-already-decides">What the evidence already decides, before the debate</h2>
<p>These are the pack's settled findings. They are not re-opened by the debate; they are
its inputs.</p>
<ul>
  <li><b>Units basis is mixed.</b> 56 young winners on a 6-month window, 17 starred
  shops on lifetime. Totals rank lanes against each other; they are not a market size.</li>
  <li><b>The dead tail is universal.</b> Zero-sale share runs from a few per cent of a
  catalogue to over 95%. A shop reporting 90% dead listings is describing the model,
  not confessing.</li>
  <li><b>Shape pays more than price.</b> Bundle-shaped listings carry the yield in both
  corpora, and the mega-bundle band is the top of the ladder in both.</li>
  <li><b>The generic head terms are volume traps.</b> <code>printable wall art</code> at
  3,435 volume carries 2.93M competing listings; the faith heads carry 134K–543K against
  comparable volume.</li>
  <li><b>Page one is not available to a new shop on the generic terms.</b> The live
  recon shows who holds those slots and what they hold them with.</li>
</ul>

<div class="note"><b>Reserved for the boss.</b> The pack presents evidence and ranked
arguments. It does not choose a lane, create a listing, or spend a credit — and the
agent's own recommendation is not the decision.</div>'''
    body = add_anchors(body)
    write("debate.html", page(title="Debate Ranking", sub="debate", section="debate",
                              depth=0, crumb=[("Overview", "index.html")],
                              body=body, toc=None, pending=True))
    add_docs("debate.html", "Debate Ranking", body)
    PAGES.append(("Debate Ranking", "debate.html", "debate", ""))
    return False


# -------------------------------------------------------------------- 7. main --
def build_search_index():
    docs = []
    for d in SEARCH_DOCS:
        if not d["b"].strip():
            continue
        docs.append(d)
    js = ("/* generated by build/build.py — do not edit */\n"
          "window.SEARCH_INDEX = " +
          json.dumps({"built": "2026-10-02", "docs": docs, "pages": len(set(d["u"] for d in docs))},
                     ensure_ascii=False, separators=(",", ":")) + ";\n")
    p = SITE / "assets" / "search_index.js"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(js, encoding="utf-8")
    (SITE / "search_index.json").write_text(
        json.dumps({"built": "2026-10-02", "docs": docs}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    return len(docs)


def main():
    register_map()
    # Never touch the repo's own metadata: build.py has silently deleted
    # .git on every run, forcing a re-init before each push.
    KEEP_DIRS = ("assets", "build", ".git", ".github")
    for p in SITE.iterdir():
        if p.is_dir() and p.name not in KEEP_DIRS:
            shutil.rmtree(p)
    for p in SITE.glob("*.html"):
        p.unlink()

    # Home and search pages are built last: their headline counts (pages,
    # figures) are measured from everything the other pages produced.
    entries = build_directions()
    build_search_page()
    build_corpus()
    build_shops()
    build_single_reports()
    debate_real = build_debate()

    # method/plan page (PLAN.md rendered standalone)
    ids = {}
    plan = fix_links(md_html(read(ROOT / "PLAN.md"), ids), "method-plan.html")
    emit("method-plan.html", title="The Brief this Pack Answers",
         sub="brief", section="brief", depth=0,
         crumb=(("Overview", "index.html"),), body=plan,
         pager=pager_html(("Overview", "index.html"),
                          ("The Corpus", "corpus/index.html")))

    # the home page goes last so its page/figure counts are measured, not guessed
    build_home([("73", "shops in corpus"), ("40,275", "listing rows"),
                ("14", "direction projects"), ("75", "shop case files"),
                (f"{total_figures()}", "figures rendered"),
                (f"{total_pages()}", "pages")])

    n = build_search_index()
    leaks = token_regression_check()
    print(f"pages written : {len(list(SITE.rglob('*.html')))}")
    print(f"search docs   : {n}")
    print(f"debate real   : {debate_real}")
    print(f"directions    : {len(entries)}")
    figs = 0
    for p in SITE.rglob("*.html"):
        figs += p.read_text(encoding="utf-8").count('class="fig"')
    print(f"figures       : {figs}")
    if leaks:
        raise SystemExit(
            f"build FAILED: {len(leaks)} template-token leak(s) in the built "
            f"site or the search index:\n  " + "\n  ".join(leaks[:20]))


# --------------------------------------------------------- token regression --
# Unfilled authoring placeholders (`@@T_LANE73@@`) and doubled percent signs
# (`%%`, left over from a %-format pass) have both shipped to the live site
# before. They are invisible to a link check and to a visual review of the
# pages that do not quote the affected figure, so they get their own gate:
# the build refuses to finish while any survive in a generated page or in
# either search index file.
TOKEN_PATTERNS = (
    ("unfilled-token", re.compile(r"@@[A-Za-z0-9_.:-]{2,}@@")),
    ("format-escape", re.compile(r"%%(?=[0-9%])")),
)


def token_regression_check():
    """Return a list of "page: kind: snippet" for every token that leaked.

    Scans the generated HTML and both search index artefacts, so a leak
    introduced in the markdown sources cannot reach either output silently.
    """
    targets = sorted(SITE.rglob("*.html"))
    targets += [SITE / "search_index.json", SITE / "assets" / "search_index.js"]
    found = []
    for p in targets:
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        for kind, rx in TOKEN_PATTERNS:
            for m in rx.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                found.append(f"{p.relative_to(SITE)}:{line}: {kind}: "
                             f"{m.group(0)!r}")
    return found


if __name__ == "__main__":
    main()
