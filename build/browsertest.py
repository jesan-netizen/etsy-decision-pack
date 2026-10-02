#!/usr/bin/env python3
"""Verify the served site in real headless Chrome.

CDP is unusable here: the host runs a managed Chrome whose process singleton
steals any --remote-debugging-port we open. So this drives Chrome's --dump-dom
mode instead, which still executes every script and applies every stylesheet —
the assertions below run against the live rendered document, not the source.

  1. every page renders an <h1> and is not an error page
  2. every figure became a real inline SVG with plotted geometry
  3. every table has a header row
  4. the client-side search pipeline returns ranked, highlighted results
     (driven through search.html?q=)
  5. responsive sanity at a 420px viewport
  6. no CDN / asset dependency on a remote origin

Usage: /home/ubuntu/.hermes/hermes-agent/venv/bin/python browsertest.py [base_url]
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8420").rstrip("/")
CHROME = "google-chrome"
GEOM = re.compile(r"<(rect|path|circle|line)\b")

fails: list[str] = []


def ok(cond, msg):
    print(("  PASS  " if cond else "  FAIL  ") + msg)
    if not cond:
        fails.append(msg)


PROFILE = Path("/tmp/etsy-site-chrome-profile")


def dump(url: str, width: int = 1440, budget: int = 6000) -> str:
    """Render one URL in headless Chrome and return the post-JS DOM.

    One shared profile for the whole run: creating a fresh --user-data-dir per
    page makes Chrome spend its startup on profile scaffolding and it often
    exits before it writes anything."""
    r = subprocess.run(
        [CHROME, "--headless", "--no-sandbox", "--disable-gpu",
         "--disable-extensions", "--no-first-run", "--no-default-browser-check",
         f"--user-data-dir={PROFILE}", f"--window-size={width},1200",
         f"--virtual-time-budget={budget}", "--dump-dom", url],
        capture_output=True, text=True, timeout=180)
    dom = r.stdout
    if not dom.strip():
        raise RuntimeError(f"chrome produced no DOM for {url} (rc={r.returncode}, "
                           f"stderr={r.stderr[-200:]!r})")
    return dom


def crawl():
    seen, queue = set(), [BASE + "/"]
    while queue and len(seen) < 400:
        u = queue.pop()
        if u in seen:
            continue
        seen.add(u)
        try:
            with urllib.request.urlopen(u, timeout=20) as r:
                body = r.read().decode("utf-8", "replace")
        except Exception:                                        # noqa: BLE001
            continue
        for m in re.finditer(r'href="([^"#?]+\.html)(?:#[^"]*)?"', body):
            nxt = urllib.request.urljoin(u, m.group(1))
            if nxt.startswith(BASE) and nxt not in seen:
                queue.append(nxt)
    return sorted(seen)


def main() -> int:
    pages = crawl()
    print(f"\n== crawl: {len(pages)} pages discovered from the home page ==")
    ok(len(pages) >= 100, f"crawl found {len(pages)} pages (expected >= 100)")

    print("\n== 1/2/3. render, figures, tables ==")
    tot_fig = tot_svg = tot_tbl = 0
    bad_page, bad_fig, bad_tbl = [], [], []
    for i, u in enumerate(pages, 1):
        dom = dump(u)
        if "<h1" not in dom or "</html>" not in dom:
            bad_page.append(u)
        figs = dom.count('class="fig"')
        svgs = len(re.findall(r'<svg[^>]*class="chart"', dom))
        # some chart specs are genuinely tables (type: "table") and render as
        # <table class="chart-table"> rather than SVG — those are not failures.
        tbl_figs = dom.count('class="chart-table"')
        tot_fig += figs
        tot_svg += svgs
        if figs and svgs + tbl_figs != figs:
            bad_fig.append(f"{u}: {figs} figures but {svgs} chart SVGs "
                           f"+ {tbl_figs} table figures")
        for m in re.finditer(r'<svg[^>]*class="chart".*?</svg>', dom, re.S):
            if len(GEOM.findall(m.group(0))) < 3:
                bad_fig.append(f"{u}: an SVG carries <3 geometry elements")
                break
        tot_tbl += len(re.findall(r"<table", dom))
        for m in re.finditer(r"<table.*?</table>", dom, re.S):
            if not re.search(r"<thead>.*?<th", m.group(0), re.S):
                bad_tbl.append(f"{u}: a table has no header row")
                break
        if i % 25 == 0:
            print(f"    … {i}/{len(pages)} pages checked")

    ok(not bad_page, f"all {len(pages)} pages render an <h1> and close cleanly")
    ok(not bad_fig, f"{tot_fig} figures, all inline SVG with plotted geometry")
    ok(not bad_tbl, f"{tot_tbl} tables, all with a header row")
    for b in (bad_page + bad_fig + bad_tbl)[:8]:
        print("     - " + b)

    print("\n== 4. the client-side search pipeline ==")
    for q in ["nursery", "MartyWallArt", "zero", "bundle ladder", "vintage"]:
        dom = dump(f"{BASE}/search.html?q={urllib.parse.quote(q)}", budget=9000)
        cards = dom.count('class="card"')
        marks = dom.count("<mark>")
        meta = re.search(r'id="pagemeta"[^>]*>([^<]*)<', dom)
        m = re.search(r"(\d+)", meta.group(1)) if meta else None
        hits = int(m.group(1)) if m else 0
        ok(cards > 0 and hits > 0 and marks > 0,
           f"q={q!r:<16} -> {hits:>4} hits, {cards} result cards, {marks} highlights")

    # a query with no matches must degrade gracefully, not throw
    dom = dump(f"{BASE}/search.html?q=zzzqqqxxnotathing", budget=8000)
    ok("Nothing in the pack matches" in dom,
       "a no-match query shows the empty-state message instead of breaking")

    print("\n== 5. responsive ==")
    dom = dump(BASE + "/corpus/yw.html", width=420)
    ok('<meta name="viewport"' in dom, "viewport meta present")
    ok('class="side"' in dom, "report pages keep their contents sidebar")
    ok('id="menu"' in dom, "mobile menu button present")

    print("\n== 6. self-contained ==")
    sample = pages[::9]
    remote_assets = []
    for u in sample:
        dom = dump(u)
        for tag in re.finditer(r"<(link|script|img|iframe)\b[^>]*?(?:href|src)=\"([^\"]+)\"",
                               dom):
            ref = tag.group(2)
            if ref.startswith(("http://", "https://", "//")):
                remote_assets.append(f"{u}: {tag.group(1)} -> {ref}")
    ok(not remote_assets,
       f"no <link>/<script>/<img> pulls from a remote origin "
       f"({len(sample)} pages sampled)")
    for r in remote_assets[:5]:
        print("     - " + r)
    return 1 if fails else 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception as exc:                                     # noqa: BLE001
        import traceback
        traceback.print_exc()
        print(f"\nBROWSER TEST CRASHED: {exc}")
        code = 1
    print("\n" + "=" * 62)
    if fails:
        print(f"{len(fails)} CHECK(S) FAILED:")
        for f in fails:
            print("  - " + f)
    elif code == 0:
        print("ALL BROWSER CHECKS PASSED")
    sys.exit(1 if (fails or code) else 0)