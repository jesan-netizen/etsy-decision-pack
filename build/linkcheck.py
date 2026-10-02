#!/usr/bin/env python3
"""Verify the generated site: links resolve, anchors exist, figures render,
assets exist, search index is well-formed.

Usage:  /home/ubuntu/.hermes/hermes-agent/venv/bin/python linkcheck.py
Exit code 0 = clean, 1 = problems found.
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent
EXTERNAL = re.compile(r"^(https?:|mailto:|tel:|data:|javascript:|#)")


def hrefs(html: str):
    for m in re.finditer(r'(?:href|src)="([^"]+)"', html):
        yield m.group(1)


def anchors(html: str):
    return set(re.findall(r'id="([^"]+)"', html))


def main() -> int:
    pages = sorted(p for p in SITE.rglob("*.html"))
    if not pages:
        print("FAIL: no HTML pages found")
        return 1
    cache = {}
    for p in pages:
        t = p.read_text(encoding="utf-8")
        cache[p] = (t, anchors(t))

    errs = Counter()
    details = []
    total_links = total_anchor = 0

    for p, (t, anch) in cache.items():
        rel = p.relative_to(SITE)
        for h in hrefs(t):
            if EXTERNAL.match(h):
                continue
            total_links += 1
            target, _, frag = h.partition("#")
            if not target:
                if frag and frag not in anch:
                    errs["local-anchor"] += 1
                    details.append(f"{rel}: local anchor #{frag} not on page")
                continue
            # normpath, not resolve: resolve() follows symlinks and would
            # compare a resolved child against an unresolved site root.
            tp = Path(os.path.normpath(p.parent / target))
            if SITE.resolve() not in tp.resolve().parents and tp.resolve() != SITE.resolve():
                errs["escape"] += 1
                details.append(f"{rel}: {h} escapes the site root")
                continue
            if not tp.exists():
                if tp.name in ("", "index") or target.endswith("/"):
                    idx = tp / "index.html"
                    if idx.exists():
                        continue
                errs["missing-file"] += 1
                details.append(f"{rel}: -> {h} (no such file)")
                continue
            if frag and tp.suffix == ".html":
                tt, ta = cache.get(tp, ("", None))
                if ta is None:
                    tt = tp.read_text(encoding="utf-8")
                    ta = anchors(tt)
                if frag not in ta:
                    errs["dead-anchor"] += 1
                    total_anchor += 1
                    details.append(f"{rel}: -> {h} (anchor #{frag} missing in target)")

    # ---- structural checks ------------------------------------------------
    figs = svg = tables = 0
    empty_svg = []
    for p, (t, _) in cache.items():
        figs += t.count('class="fig"')
        svg += t.count("<svg")
        tables += t.count("<table")
        for m in re.finditer(r"<svg\b.*?</svg>", t, re.S):
            if len(m.group(0)) < 300 or "chart" not in m.group(0)[:200]:
                empty_svg.append(f"{p.relative_to(SITE)}")
        if "<!DOCTYPE html>" not in t:
            errs["no-doctype"] += 1
        if 'assets/site.css' not in t:
            errs["no-css"] += 1
        if "</html>" not in t:
            errs["truncated"] += 1

    # ---- markdown that escaped conversion --------------------------------
    raw_tables = []
    for p, (t, _) in cache.items():
        body = re.sub(r"(?s)<(figure|div class=\"tw\"|pre|code)\b.*?</\1>", " ", t)
        for m in re.finditer(r"<p>\s*\|[^<]{6,}\|", body):
            raw_tables.append(f"{p.relative_to(SITE)}: unconverted table "
                              f"{m.group(0)[:44]!r}")
        if re.search(r"<p>\s*#{1,6}\s", body):
            errs["raw-heading"] += 1
    if raw_tables:
        errs["raw-table"] += len(raw_tables)
        details += raw_tables[:10]

    # ---- asset + search index --------------------------------------------
    for a in ("assets/site.css", "assets/site.js", "assets/search_index.js",
              "search_index.json"):
        if not (SITE / a).exists():
            errs["missing-asset"] += 1
            details.append(f"missing asset: {a}")

    ix = SITE / "assets" / "search_index.js"
    docs = 0
    if ix.exists():
        raw = ix.read_text(encoding="utf-8")
        payload = raw.split("=", 1)[1].strip().rstrip(";")
        try:
            obj = json.loads(payload)
            docs = len(obj["docs"])
            urls = {d["u"] for d in obj["docs"]}
            for u in urls:
                if not (SITE / u).exists():
                    errs["search-dead-page"] += 1
                    details.append(f"search index points at missing page: {u}")
            for d in obj["docs"][:4000]:
                for k in ("u", "t", "b", "h", "sec"):
                    if k not in d or not isinstance(d[k], str):
                        errs["search-schema"] += 1
                        break
        except Exception as e:                                  # noqa: BLE001
            errs["search-json"] += 1
            details.append(f"search index JSON invalid: {e}")
    if docs < 100:
        errs["search-thin"] += 1

    # ---- report -----------------------------------------------------------
    size = sum(p.stat().st_size for p in SITE.rglob("*") if p.is_file())
    print(f"pages      : {len(pages)}")
    print(f"figures    : {figs}  (inline SVGs: {svg})")
    print(f"tables     : {tables}")
    print(f"links      : {total_links} internal, all targets checked")
    print(f"search docs: {docs}")
    print(f"site size  : {size/1e6:.1f} MB across "
          f"{sum(1 for p in SITE.rglob('*') if p.is_file())} files")
    if empty_svg:
        errs["empty-svg"] += len(empty_svg)
        details += [f"suspiciously small svg: {x}" for x in empty_svg[:5]]

    if not errs:
        print("\nOK — every link resolves, every anchor exists, "
              "every figure has markup, assets present.")
        return 0
    print("\nPROBLEMS:")
    for k, v in errs.most_common():
        print(f"  {k:22s} {v}")
    for d in details[:40]:
        print(f"   - {d}")
    if len(details) > 40:
        print(f"   … and {len(details)-40} more")
    return 1


if __name__ == "__main__":
    sys.exit(main())