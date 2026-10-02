/* Etsy Decision Pack — client-side search over the JSON index + small UI glue.
   No external libraries. Fails silently to a plain <form> if the index
   cannot be fetched (e.g. opened over file://).                       */
(function () {
  "use strict";

  var IDX = null;          // {docs:[...], pages:[...]}
  var sel = -1, rows = [], active = null;

  /* ---------------------------------------------------------- utilities --- */
  function $(s, r) { return (r || document).querySelector(s); }
  function el(tag, cls, txt) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (txt != null) n.textContent = txt;
    return n;
  }
  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  function norm(s) {
    return String(s).toLowerCase()
      .replace(/[^\w\s.$-]+/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }
  /* snippet around the first hit, with <mark> */
  function snip(body, terms) {
    var b = body || "", low = norm(b), at = -1, t;
    for (var i = 0; i < terms.length; i++) {
      var p = low.indexOf(terms[i]);
      if (p >= 0 && (at < 0 || p < at)) { at = p; t = terms[i]; }
    }
    if (at < 0) { at = 0; t = terms[0]; }
    var start = Math.max(0, at - 70);
    var frag = b.slice(start, start + 210);
    var out = esc((start > 0 ? "…" : "") + frag + (start + 210 < b.length ? "…" : ""));
    terms.forEach(function (term) {
      if (!term) return;
      var re = new RegExp("(" + term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "gi");
      out = out.replace(re, "<mark>$1</mark>");
    });
    return out;
  }
  function hl(text, terms) {
    var out = esc(text);
    terms.forEach(function (term) {
      if (!term) return;
      var re = new RegExp("(" + term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "gi");
      out = out.replace(re, "<mark>$1</mark>");
    });
    return out;
  }

  /* ------------------------------------------------------------ loading --- */
  function load(cb) {
    if (IDX) return cb();
    var s = document.createElement("script");
    s.src = "assets/search_index.js";
    s.onload = function () { IDX = window.SEARCH_INDEX; cb(); };
    s.onerror = function () { console.warn("[search] index unavailable"); };
    document.head.appendChild(s);
  }

  /* ------------------------------------------------------------ ranking --- */
  function search(q) {
    if (!IDX) return [];
    var terms = norm(q).split(" ").filter(function (t) { return t.length > 1; });
    if (!terms.length) return [];
    var out = [];
    for (var i = 0; i < IDX.docs.length; i++) {
      var d = IDX.docs[i];
      var hay = d.h;                       // pre-normalised haystack
      var score = 0, ok = true;
      for (var j = 0; j < terms.length; j++) {
        var t = terms[j], from = 0, n = 0, pos;
        while ((pos = hay.indexOf(t, from)) >= 0 && n < 30) { n++; from = pos + t.length; }
        if (!n) { ok = false; break; }
        score += n;
        if (d.t && d.t.indexOf(t) >= 0) score += 12;      // title boost
        if (d.ht && d.ht.indexOf(t) >= 0) score += 5;     // heading boost
      }
      if (!ok) continue;
      score += (d.w || 0);
      out.push({ d: d, s: score, terms: terms });
    }
    out.sort(function (a, b) { return b.s - a.s; });
    return out.slice(0, 40);
  }

  /* -------------------------------------------------------------- render --- */
  function render(hits, panel, box) {
    panel.innerHTML = "";
    rows = [];
    if (!box.value.trim()) { panel.classList.remove("show"); sel = -1; return; }
    panel.classList.add("show");
    if (!hits.length) {
      panel.appendChild(el("div", "empty", "No match for “" + box.value.trim() + "”."));
      return;
    }
    var head = el("div", "rhead", hits.length + (hits.length === 40 ? "+ matches" : " matches"));
    panel.appendChild(head);
    hits.forEach(function (h, i) {
      var a = el("a", "row");
      a.href = h.d.u + (h.d.a ? "#" + h.d.a : "");
      var t = el("div", "rt");
      t.innerHTML = hl(h.d.t, h.terms);
      var sec = el("div", "rh", h.d.sec || h.d.u);
      var x = el("div", "rx", "");
      x.innerHTML = snip(h.d.b, h.terms);
      a.appendChild(t); a.appendChild(sec); a.appendChild(x);
      panel.appendChild(a);
      rows.push(a);
    });
    sel = -1;
  }

  function highlight(i) {
    if (!rows.length) return;
    rows.forEach(function (r, j) { r.classList.toggle("sel", j === i); });
    sel = i;
    if (rows[i]) rows[i].scrollIntoView({ block: "nearest" });
  }

  function wire(box) {
    if (!box) return;
    var panel = $("#" + box.id + "results");
    if (!panel) return;

    var t = null;
    box.addEventListener("input", function () {
      clearTimeout(t);
      var v = box.value;
      t = setTimeout(function () { load(function () { render(search(v), panel, box); }); }, 110);
    });
    box.addEventListener("focus", function () {
      load(function () { if (box.value.trim()) render(search(box.value), panel, box); });
    });
    box.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown") { e.preventDefault(); highlight(Math.min(sel + 1, rows.length - 1)); }
      else if (e.key === "ArrowUp") { e.preventDefault(); highlight(Math.max(sel - 1, 0)); }
      else if (e.key === "Enter") {
        if (sel >= 0 && rows[sel]) { location.href = rows[sel].href; }
        else if (rows.length) { location.href = rows[0].href; }
        else if (box.value.trim() && IDX) {
          var q = box.value.trim();
          location.href = "search.html" + (window.SP_BASE || "") + "?q=" + encodeURIComponent(q);
        }
      } else if (e.key === "Escape") { panel.classList.remove("show"); box.blur(); }
    });
    document.addEventListener("click", function (e) {
      if (!panel.contains(e.target) && e.target !== box) panel.classList.remove("show");
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-search]").forEach(wire);
    var q = new URLSearchParams(location.search).get("q");
    var page = $("#pagequery");
    if (q && page) { page.value = q; load(function () { runPage(q); }); }
    else if (page) { load(function () { if (page.value) runPage(page.value); }); }

    document.addEventListener("keydown", function (e) {
      if ((e.key === "/" || (e.key === "k" && (e.metaKey || e.ctrlKey))) &&
          !/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) {
        var b = document.querySelector("[data-search]");
        if (b) { e.preventDefault(); b.focus(); b.select(); }
      }
    });

    var mb = $("#menu");
    if (mb) mb.addEventListener("click", function () {
      var n = $("#topnav");
      n.classList.toggle("open");
      mb.textContent = n.classList.contains("open") ? "Close" : "Menu";
    });
    var sc = $("#sideToggle");
    if (sc) sc.addEventListener("click", function () {
      var s = $("#side");
      var c = s.getAttribute("data-collapsed") === "1";
      s.setAttribute("data-collapsed", c ? "0" : "1");
      sc.textContent = c ? "Hide contents" : "Show contents";
    });
  });

  /* --------------------------------------------------- dedicated results --- */
  function runPage(q) {
    var box = $("#pagequery"), out = $("#pageresults"), meta = $("#pagemeta");
    if (!out) return;
    var hits = search(q);
    out.innerHTML = "";
    if (!hits.length) {
      out.innerHTML = '<p class="note pending">Nothing in the pack matches that. Try a lane name, a shop name, a price band, or a figure id.</p>';
      if (meta) meta.textContent = "";
      return;
    }
    if (meta) meta.textContent = hits.length + " matching passages across the pack";
    var byPage = {};
    hits.forEach(function (h) { (byPage[h.d.u] = byPage[h.d.u] || []).push(h); });
    Object.keys(byPage).forEach(function (u) {
      var card = el("div", "card");
      card.style.marginBottom = "14px";
      var h3 = el("h3", null, byPage[u][0].d.pt || byPage[u][0].d.t);
      h3.style.marginTop = "0";
      card.appendChild(h3);
      var n = Math.min(byPage[u].length, 4);
      for (var i = 0; i < n; i++) {
        var p = el("p");
        p.style.margin = "0 0 10px";
        var a = el("a", null, hl(byPage[u][i].d.sec, byPage[u][i].terms));
        a.href = byPage[u][i].d.u + (byPage[u][i].d.a ? "#" + byPage[u][i].d.a : "");
        a.style.fontFamily = "var(--sans)";
        a.style.fontSize = "11px";
        a.style.textTransform = "uppercase";
        a.style.letterSpacing = ".06em";
        p.appendChild(a);
        var sp = el("span");
        sp.innerHTML = " " + snip(byPage[u][i].d.b, byPage[u][i].terms);
        p.appendChild(sp);
        card.appendChild(p);
      }
      if (byPage[u].length > n) {
        var m = el("p", "meta", (byPage[u].length - n) + " more in this page");
        m.style.margin = "0";
        card.appendChild(m);
      }
      out.appendChild(card);
    });
  }
})();