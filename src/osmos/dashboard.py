"""A single self-contained HTML report: category breakdown + sortable, filterable table.

No server, no build step, no CDN — opens directly from disk, works offline.
Rendering follows the dataviz skill's method: this is a magnitude/ranking job
(count per category), so the chart gets one hue, not a color per category —
categorical color would misrepresent what the chart is actually showing. The
bar layout, spacing and colors come from the skill's validated reference
palette (`references/palette.md`), not invented here.
"""

from __future__ import annotations

import json
from string import Template

_CSS = """
:root {
  --page: #f9f9f7; --surface: #fcfcfb; --text-primary: #0b0b0b;
  --text-secondary: #52514e; --muted: #898781; --border: rgba(11,11,11,0.10);
  --gridline: #e1e0d9; --series-1: #2a78d6;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    --page: #0d0d0d; --surface: #1a1a19; --text-primary: #ffffff;
    --text-secondary: #c3c2b7; --muted: #898781; --border: rgba(255,255,255,0.10);
    --gridline: #2c2c2a; --series-1: #3987e5;
  }
}
:root[data-theme="dark"] {
  --page: #0d0d0d; --surface: #1a1a19; --text-primary: #ffffff;
  --text-secondary: #c3c2b7; --muted: #898781; --border: rgba(255,255,255,0.10);
  --gridline: #2c2c2a; --series-1: #3987e5;
}
* { box-sizing: border-box; }
body {
  background: var(--page); color: var(--text-primary); margin: 0;
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
}
.wrap { max-width: 1000px; margin: 0 auto; padding: 28px 16px 60px; }
.head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 20px; }
.head h1 { font-size: 20px; margin: 0; }
.head .sub { color: var(--text-secondary); font-size: 13px; margin-top: 2px; }
#theme-toggle {
  border: 1px solid var(--border); background: var(--surface); color: var(--text-secondary);
  border-radius: 8px; padding: 6px 12px; font-size: 13px; cursor: pointer;
}
.kpis { display: flex; gap: 14px; flex-wrap: wrap; margin-bottom: 22px; }
.kpi { background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  padding: 14px 18px; flex: 1; min-width: 150px; }
.kpi .label { font-size: 12px; color: var(--text-secondary); }
.kpi .value { font-size: 26px; font-weight: 600; margin-top: 4px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  padding: 18px 20px; margin-bottom: 22px; }
.card h2 { font-size: 14px; color: var(--text-secondary); font-weight: 600;
  margin: 0 0 14px; text-transform: uppercase; letter-spacing: 0.02em; }
.bar-row { display: flex; align-items: center; gap: 10px; padding: 4px 0; cursor: pointer; }
.bar-label { width: 190px; flex-shrink: 0; font-size: 13px; color: var(--text-secondary);
  text-align: right; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bar-track { flex: 1; height: 18px; }
.bar-fill { height: 18px; background: var(--series-1); border-radius: 0 4px 4px 0;
  min-width: 2px; filter: brightness(1); transition: filter 0.15s; }
.bar-row:hover .bar-fill, .bar-row.active .bar-fill { filter: brightness(1.12); }
.bar-row.active .bar-label { color: var(--text-primary); font-weight: 600; }
.bar-value { font-size: 12px; color: var(--text-secondary); min-width: 30px;
  font-variant-numeric: tabular-nums; }
.controls { display: flex; gap: 10px; margin-bottom: 14px; flex-wrap: wrap; }
#search { flex: 1; min-width: 200px; padding: 8px 10px; border: 1px solid var(--border);
  border-radius: 8px; background: var(--page); color: var(--text-primary); font-size: 13px; }
#clear-filter { border: 1px solid var(--border); background: var(--page);
  color: var(--text-secondary); border-radius: 8px; padding: 8px 12px; font-size: 13px;
  cursor: pointer; display: none; }
#clear-filter.visible { display: inline-block; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { text-align: left; padding: 8px 10px; color: var(--muted); font-weight: 600;
  border-bottom: 1px solid var(--gridline); cursor: pointer; white-space: nowrap; }
th .arrow { color: var(--text-secondary); margin-left: 4px; }
td { padding: 8px 10px; border-bottom: 1px solid var(--gridline); vertical-align: top; }
.truncate { display: block; max-width: 320px; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; cursor: pointer; }
.truncate.expanded { max-width: none; white-space: normal; overflow: visible; text-overflow: clip; }
td.num { font-variant-numeric: tabular-nums; text-align: right; }
#row-count { color: var(--muted); font-size: 12px; margin-top: 10px; }
#tooltip { position: fixed; background: var(--text-primary); color: var(--page);
  font-size: 12px; padding: 5px 9px; border-radius: 6px; pointer-events: none; z-index: 10; }
#tooltip[hidden] { display: none; }
"""

_HTML = Template("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>osmos — influencer dashboard</title>
<style>$css</style>
</head>
<body>
<div class="wrap">
  <div class="head">
    <div>
      <h1>osmos</h1>
      <div class="sub">Instagram influencer classification — generated locally, no network calls on load</div>
    </div>
    <button id="theme-toggle" type="button">Dark mode</button>
  </div>

  <div class="kpis">
    <div class="kpi"><div class="label">Profiles collected</div><div class="value">$total</div></div>
    <div class="kpi"><div class="label">Classified</div><div class="value">$classified</div></div>
    <div class="kpi"><div class="label">Avg. confidence</div><div class="value">$avg_confidence</div></div>
  </div>

  <div class="card">
    <h2>By category</h2>
    <div id="chart">$bars_html</div>
  </div>

  <div class="card">
    <div class="controls">
      <input id="search" type="search" placeholder="Filter by username, bio or reasoning…">
      <button id="clear-filter" type="button">Clear category filter</button>
    </div>
    <table>
      <thead>
        <tr>
          <th data-key="username">Username<span class="arrow"></span></th>
          <th data-key="category">Category<span class="arrow"></span></th>
          <th data-key="confidence">Confidence<span class="arrow"></span></th>
          <th data-key="follower_count">Followers<span class="arrow"></span></th>
          <th data-key="reasoning">Reasoning <span style="font-weight:400;color:var(--muted);font-size:11px">(click to expand)</span><span class="arrow"></span></th>
        </tr>
      </thead>
      <tbody id="table-body"></tbody>
    </table>
    <div id="row-count"></div>
  </div>
</div>

<div id="tooltip" hidden></div>

<script>
const ROWS = $rows_json;
let sortKey = "follower_count";
let sortDir = -1;
let categoryFilter = null;
let searchText = "";

function categoryOf(row) { return row.category || "(unclassified)"; }

function getFiltered() {
  return ROWS.filter(function (r) {
    if (categoryFilter !== null && categoryOf(r) !== categoryFilter) return false;
    if (searchText) {
      const hay = [r.username, r.biography, r.reasoning].filter(Boolean).join(" ").toLowerCase();
      if (hay.indexOf(searchText.toLowerCase()) === -1) return false;
    }
    return true;
  });
}

function cell(text, opts) {
  const td = document.createElement("td");
  if (opts && opts.expandable) {
    // Truncating/ellipsis on a <td> itself is unreliable in auto-layout
    // tables — different rows can render inconsistently. An inner span
    // with its own max-width is the robust version of the same thing.
    const span = document.createElement("span");
    span.className = "truncate";
    span.textContent = text;
    span.addEventListener("click", function () { span.classList.toggle("expanded"); });
    td.appendChild(span);
  } else {
    td.textContent = text;
    if (opts && opts.className) td.className = opts.className;
  }
  return td;
}

function render() {
  const rows = getFiltered();
  rows.sort(function (a, b) {
    let av = a[sortKey], bv = b[sortKey];
    if (av === null || av === undefined) av = sortDir === 1 ? Infinity : -Infinity;
    if (bv === null || bv === undefined) bv = sortDir === 1 ? Infinity : -Infinity;
    if (typeof av === "string" || typeof bv === "string") {
      return sortDir * String(av).localeCompare(String(bv));
    }
    return sortDir * (av - bv);
  });

  const tbody = document.getElementById("table-body");
  tbody.innerHTML = "";
  for (const r of rows) {
    const tr = document.createElement("tr");
    tr.appendChild(cell("@" + r.username));
    tr.appendChild(cell(categoryOf(r)));
    tr.appendChild(cell(r.confidence != null ? Math.round(r.confidence * 100) + "%" : "—", {className: "num"}));
    tr.appendChild(cell(r.follower_count != null ? r.follower_count.toLocaleString() : "—", {className: "num"}));
    tr.appendChild(cell(r.reasoning || "—", {expandable: true}));
    tbody.appendChild(tr);
  }
  document.getElementById("row-count").textContent = "Showing " + rows.length + " of " + ROWS.length;

  document.querySelectorAll("th[data-key]").forEach(function (th) {
    const arrow = th.querySelector(".arrow");
    arrow.textContent = th.dataset.key === sortKey ? (sortDir === 1 ? "▲" : "▼") : "";
  });
}

document.querySelectorAll("th[data-key]").forEach(function (th) {
  th.addEventListener("click", function () {
    const key = th.dataset.key;
    if (sortKey === key) { sortDir *= -1; } else { sortKey = key; sortDir = 1; }
    render();
  });
});

document.getElementById("search").addEventListener("input", function (e) {
  searchText = e.target.value;
  render();
});

const clearBtn = document.getElementById("clear-filter");
function setCategoryFilter(cat) {
  categoryFilter = cat;
  document.querySelectorAll(".bar-row").forEach(function (el) {
    el.classList.toggle("active", el.dataset.category === cat);
  });
  clearBtn.classList.toggle("visible", cat !== null);
  render();
}
clearBtn.addEventListener("click", function () { setCategoryFilter(null); });

const tooltip = document.getElementById("tooltip");
document.querySelectorAll(".bar-row").forEach(function (el) {
  el.addEventListener("click", function () {
    setCategoryFilter(categoryFilter === el.dataset.category ? null : el.dataset.category);
  });
  el.addEventListener("mousemove", function (e) {
    tooltip.hidden = false;
    tooltip.textContent = el.dataset.category + ": " + el.querySelector(".bar-value").textContent;
    tooltip.style.left = (e.clientX + 14) + "px";
    tooltip.style.top = (e.clientY + 14) + "px";
  });
  el.addEventListener("mouseleave", function () { tooltip.hidden = true; });
});

const themeToggle = document.getElementById("theme-toggle");
function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  themeToggle.textContent = theme === "dark" ? "Light mode" : "Dark mode";
}
let savedTheme = null;
try { savedTheme = localStorage.getItem("osmos-theme"); } catch (e) { /* private window etc. */ }
applyTheme(savedTheme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
themeToggle.addEventListener("click", function () {
  const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
  applyTheme(next);
  try { localStorage.setItem("osmos-theme", next); } catch (e) { /* private window etc. */ }
});

render();
</script>
</body>
</html>
""")


def _bar_row_html(category: str, count: int, max_count: int) -> str:
    pct = max(round(count / max_count * 100, 1), 1.5) if max_count else 1.5
    label = category.replace("&", "&amp;").replace("<", "&lt;")
    return (
        f'<div class="bar-row" data-category="{label}">'
        f'<div class="bar-label">{label}</div>'
        f'<div class="bar-track"><div class="bar-fill" style="width:{pct}%"></div></div>'
        f'<div class="bar-value">{count}</div>'
        "</div>"
    )


def compute_stats(rows: list[dict]) -> dict:
    """Total/classified/avg-confidence/category-counts — shared by the static export and the live API.

    Kept separate from rendering so `web.py`'s `/api/profiles` can return the
    same numbers as JSON without recomputing them in JS.
    """
    classified = [r for r in rows if r.get("category")]
    confidences = [r["confidence"] for r in classified if r.get("confidence") is not None]
    avg_confidence_pct = round(sum(confidences) / len(confidences) * 100) if confidences else None

    counts: dict[str, int] = {}
    for row in rows:
        key = row.get("category") or "(unclassified)"
        counts[key] = counts.get(key, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])

    return {
        "total": len(rows),
        "classified": len(classified),
        "avg_confidence_pct": avg_confidence_pct,
        "categories": ranked,
    }


def render_dashboard(rows: list[dict]) -> str:
    """Render the full self-contained dashboard HTML for a set of influencer rows.

    Pure function — no filesystem, no sqlite — so it's testable with plain
    fixture dicts shaped like the ``influencers`` table.
    """
    stats = compute_stats(rows)
    avg_confidence = f"{stats['avg_confidence_pct']}%" if stats["avg_confidence_pct"] is not None else "—"

    ranked = stats["categories"]
    max_count = ranked[0][1] if ranked else 0
    bars_html = "\n".join(_bar_row_html(category, count, max_count) for category, count in ranked) or (
        '<p style="color:var(--muted);font-size:13px;">No profiles collected yet.</p>'
    )

    rows_json = json.dumps(rows, default=str).replace("<", "\\u003c")

    return _HTML.substitute(
        css=_CSS,
        total=stats["total"],
        classified=stats["classified"],
        avg_confidence=avg_confidence,
        bars_html=bars_html,
        rows_json=rows_json,
    )
