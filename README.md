# Etsy Decision Pack — static site

Self-contained research website built from the markdown reports and chart JSON in
`/home/ubuntu/etsy_research/`. No CDN, no external requests, no build step at serve
time — open it and it works, including offline.

## Serve

```bash
./start_site.sh              # foreground, http://0.0.0.0:8420
./start_site.sh --daemon     # background, pid in build/server.pid, log in build/server.log
```

Under the hood: `python3 -m http.server 8420 --bind 0.0.0.0` from this directory.

## Layout

```
index.html              Overview — hero, headline stats, section cards, site search
search.html             Full-text results page (?q=…)
method-plan.html        PLAN.md, the brief this pack answers
doctrine.html           Alfie's Doctrine        (alfie_deep.md)
trends.html             External Trends         (external_trends.md + trends_charts.json)
recon.html              Live Etsy Recon         (live_recon.md)
debate.html             Debate Ranking (v2)     (debate_ranking_v2.md + debate_charts.json)
debate-ranking-v1.html  Debate Ranking v1      (debate_ranking.md, superseded, for the record)
corpus/                 The Corpus hub + 9 report pages (yw, shops17, stats,
                        synthesis, lanes, lane-faith-vintage, tables, keywords, method)
directions/             Hub + 14 direction research projects, each with prev/next nav
shops/                  Hub + 75 shop case files
assets/site.css         All styling (sage green / cream)
assets/site.js          Search UI, nav, TOC toggle — vanilla JS, no libraries
assets/search_index.js  window.SEARCH_INDEX — 1,977 section-level search documents
search_index.json       The same index as plain JSON
build/                  Build + verification scripts (not part of the served site)
start_site.sh
```

## Rebuild

```bash
/home/ubuntu/.hermes/hermes-agent/venv/bin/python build/build.py
```

Reads every `*.md` report, `directions/*.md`, `case_files/*.md` and `charts/*.json`
under `/home/ubuntu/etsy_research/`, and rewrites the whole `site/` tree. New
reports are picked up automatically; new chart JSON files need their renderer wired
into `build/svgcharts.py`.

Chart types supported: `bar`, `horizontal_bar`, `grouped_bar` (both the
`labels`/`values` form and the `categories`/`series` form), `line`, `pie`,
`histogram`, `scatter`, `heatmap`, `heatmap_rows`, `table`.

## Verify

```bash
/home/ubuntu/.hermes/hermes-agent/venv/bin/python build/linkcheck.py    # static: links, anchors, figures, assets
/home/ubuntu/.hermes/hermes-agent/venv/bin/python build/browsertest.py  # real headless Chrome, needs the server up
```

`linkcheck.py` walks every internal href, resolves each anchor against its target
document, asserts no figure is an empty SVG, no table lost its header, no markdown
escaped conversion, and that every search-index URL points at a real page.

`browsertest.py` crawls the served site, then renders all 108 pages in headless
Chrome and asserts: each renders an `<h1>`, each figure is an inline SVG with
plotted geometry, each table has a header, the search pipeline returns ranked and
highlighted hits (and degrades gracefully on a no-match query), the layout reflows
at 420px, and no `<link>`/`<script>`/`<img>` pulls from a remote origin.

## Notes on the content

- Every revenue figure is `units × listed price` — a gross sticker-price proxy,
  before Etsy fees, before the standing sale discount, before COGS.
- Units are a **mixed basis**: the 56 Young Winners shops are counted on a real
  6-month window; the 17 starred shops only carry lifetime totals. Totals rank
  lanes against each other; they are not a market size.
- Evidence only. No listings were created, no credits spent, no lane chosen.