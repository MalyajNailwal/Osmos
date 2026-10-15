"""The local web app: Setup, Run, and Dashboard in one page — `osmos serve`.

No login flow, no account system — this runs on your own machine for your own
use, same trust boundary as the CLI. One thing this page deliberately does
NOT do: take an Instagram username/password through the browser. The Setup
tab's "Instagram cookies" field is the weaker, cookie-paste auth path
(same mechanism `COOKIES_PATH` uses from the CLI); the stronger, real-login
path (`INSTAGRAM_USERNAME`/`PASSWORD`, see README's "Auth" section) is
`.env`-only by design — a credential that strong doesn't belong typed into a
web form, even a local one.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import pipeline, storage
from .config import settings, update_settings
from .dashboard import _CSS, compute_stats

app = FastAPI(title="osmos")

_COOKIES_FILE = Path("cookies.json")

# Loggers worth surfacing to the Run tab's live log panel — the ones that
# actually narrate what's happening (tier escalation, retries, login steps),
# not the whole Python logging tree.
_STREAM_LOGGER_LEVELS = {
    "osmos_core": logging.DEBUG,
    "aiograpi": logging.INFO,
    "private_request": logging.INFO,
    "httpx": logging.INFO,
}


class _QueueLogHandler(logging.Handler):
    """Pushes formatted log records into an asyncio.Queue instead of stderr.

    ponytail: one handler set is shared by every concurrent /api/run/stream
    call (these loggers are process-wide), so two simultaneous runs would see
    each other's lines. Fine for a single-user localhost tool; add per-run
    logger names if this ever needs to support concurrent users.
    """

    def __init__(self, queue: asyncio.Queue[dict]) -> None:
        super().__init__()
        self.queue = queue

    def emit(self, record: logging.LogRecord) -> None:
        self.queue.put_nowait({"level": record.levelname, "message": self.format(record)})


def _db() -> sqlite3.Connection:
    return storage.connect(settings.db_path)


# --------------------------------------------------------------------- API


class SettingsUpdate(BaseModel):
    openrouter_api_key: str | None = None
    classifier_model: str | None = None
    proxy_url: str | None = None
    cookies_text: str | None = None


class RunRequest(BaseModel):
    usernames: list[str]
    posts: int = Field(default=12, ge=1, le=50)


@app.get("/api/status")
def status() -> dict:
    has_instagram_login = bool(settings.instagram_username and settings.instagram_password)
    has_cookies = bool(settings.cookies_path) and Path(settings.cookies_path).exists()
    has_api_key = bool(settings.openrouter_api_key)
    return {
        "has_api_key": has_api_key,
        "classifier_model": settings.classifier_model,
        "has_cookies": has_cookies,
        "has_instagram_login": has_instagram_login,
        "has_instagram_session": settings.ig_session_path.exists(),
        "has_proxy": bool(settings.proxy_url),
        "posts_per_profile": settings.posts_per_profile,
        "ready": has_api_key and (has_cookies or has_instagram_login),
    }


@app.post("/api/settings")
def save_settings(body: SettingsUpdate) -> dict:
    if body.cookies_text:
        _COOKIES_FILE.write_text(body.cookies_text)
        _COOKIES_FILE.chmod(0o600)  # a session cookie is full account access
        update_settings(cookies_path=str(_COOKIES_FILE))

    update_settings(
        openrouter_api_key=body.openrouter_api_key,
        classifier_model=body.classifier_model,
        proxy_url=body.proxy_url,
    )
    return status()


@app.get("/api/profiles")
def profiles() -> dict:
    conn = _db()
    rows = [dict(row) for row in storage.fetch_all(conn)]
    return {"rows": rows, **compute_stats(rows)}


@app.post("/api/collect")
async def collect(body: RunRequest) -> dict:
    if not body.usernames:
        raise HTTPException(400, "no usernames given")
    conn = _db()
    collected = await pipeline.run_collect(conn, body.usernames, posts_limit=body.posts)
    return {"collected": collected, "total": len(body.usernames)}


@app.post("/api/classify")
async def classify() -> dict:
    conn = _db()
    classified = await pipeline.run_classify(conn)
    return {"classified": classified}


@app.post("/api/run")
async def run(body: RunRequest) -> dict:
    if not body.usernames:
        raise HTTPException(400, "no usernames given")
    conn = _db()
    collected = await pipeline.run_collect(conn, body.usernames, posts_limit=body.posts)
    classified = await pipeline.run_classify(conn)
    return {"collected": collected, "total": len(body.usernames), "classified": classified}


@app.post("/api/run/stream")
async def run_stream(body: RunRequest) -> StreamingResponse:
    """Same as /api/run, but narrates every request as it happens.

    Server-Sent Events over a POST body (native EventSource is GET-only) —
    the browser reads this with fetch() + a manual stream reader instead.
    """
    if not body.usernames:
        raise HTTPException(400, "no usernames given")

    async def events() -> AsyncIterator[str]:
        queue: asyncio.Queue[dict] = asyncio.Queue()
        handler = _QueueLogHandler(queue)
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter("%(message)s"))
        loggers = [logging.getLogger(name) for name in _STREAM_LOGGER_LEVELS]
        previous_levels = [lg.level for lg in loggers]
        for lg, level in zip(loggers, _STREAM_LOGGER_LEVELS.values(), strict=True):
            lg.addHandler(handler)
            lg.setLevel(level)

        async def run_pipeline() -> None:
            try:
                conn = _db()
                collected = await pipeline.run_collect(conn, body.usernames, posts_limit=body.posts)
                classified = await pipeline.run_classify(conn)
                await queue.put(
                    {
                        "type": "done",
                        "collected": collected,
                        "total": len(body.usernames),
                        "classified": classified,
                    }
                )
            except Exception as exc:  # surfaced to the browser, not swallowed
                await queue.put({"type": "error", "message": str(exc)})

        task = asyncio.create_task(run_pipeline())
        try:
            while True:
                item = await queue.get()
                yield f"data: {json.dumps(item)}\n\n"
                if item.get("type") in ("done", "error"):
                    break
        finally:
            for lg, level in zip(loggers, previous_levels, strict=True):
                lg.removeHandler(handler)
                lg.setLevel(level)
            if not task.done():
                task.cancel()

    return StreamingResponse(events(), media_type="text/event-stream")


@app.get("/api/discover")
def discover(min_mentions: int = 2, limit: int = 30) -> dict:
    conn = _db()
    return {"candidates": storage.top_mentions(conn, min_count=min_mentions, limit=limit)}


# -------------------------------------------------------------------- page

_PAGE_CSS = (
    _CSS
    + """
.topbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 22px; }
.topbar h1 { font-size: 20px; margin: 0; }
.tabs { display: flex; gap: 4px; margin-bottom: 20px; border-bottom: 1px solid var(--gridline); }
.tab-btn { background: none; border: none; padding: 10px 16px; font-size: 14px; color: var(--text-secondary);
  cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -1px; }
.tab-btn.active { color: var(--text-primary); border-bottom-color: var(--series-1); font-weight: 600; }
.tab-panel { display: none; }
.tab-panel.active { display: block; }
label { display: block; font-size: 13px; color: var(--text-secondary); margin: 14px 0 6px; }
label:first-child { margin-top: 0; }
input[type=text], input[type=password], input[type=number], textarea {
  width: 100%; padding: 9px 11px; border: 1px solid var(--border); border-radius: 8px;
  background: var(--page); color: var(--text-primary); font-size: 13px; font-family: inherit;
}
textarea { resize: vertical; min-height: 90px; }
.hint { font-size: 12px; color: var(--muted); margin-top: 4px; }
button[type=submit], .btn-secondary {
  margin-top: 16px; padding: 9px 18px; border-radius: 8px; border: 1px solid var(--border);
  background: var(--series-1); color: #fff; font-size: 13px; font-weight: 600; cursor: pointer;
}
.btn-secondary { background: var(--page); color: var(--text-secondary); margin-left: 8px; }
button:disabled { opacity: 0.6; cursor: default; }
.badge { display: inline-block; padding: 3px 9px; border-radius: 999px; font-size: 12px; margin-left: 8px; }
.badge.good { background: rgba(12,163,12,0.15); color: #0ca30c; }
.badge.missing { background: rgba(227,73,72,0.15); color: #e34948; }
.badge.neutral { background: var(--border); color: var(--text-secondary); }
#run-output { margin-top: 14px; font-size: 13px; color: var(--text-secondary); white-space: pre-wrap; }
.field-row { display: flex; gap: 14px; }
.field-row > div { flex: 1; }

.run-status { display: flex; align-items: center; gap: 10px; margin-top: 14px; font-size: 13px; color: var(--text-secondary); }
.spinner { width: 15px; height: 15px; border-radius: 50%; border: 2px solid var(--border);
  border-top-color: var(--series-1); animation: spin 0.7s linear infinite; flex-shrink: 0; }
@keyframes spin { to { transform: rotate(360deg); } }

.skeleton { position: relative; overflow: hidden; background: var(--border); border-radius: 6px; }
.skeleton::after { content: ""; position: absolute; inset: 0; transform: translateX(-100%);
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.25), transparent);
  animation: shimmer 1.3s infinite; }
@keyframes shimmer { 100% { transform: translateX(100%); } }
.skeleton-row td { padding: 10px 8px; }
.skeleton-bar { height: 13px; border-radius: 4px; }
.kpi .value.skeleton { height: 26px; width: 48px; display: inline-block; }

#run-log { margin-top: 12px; max-height: 260px; overflow-y: auto; background: #1c1c1a;
  border-radius: 8px; padding: 10px 12px; font-family: ui-monospace, "SF Mono", Menlo, monospace;
  font-size: 12px; line-height: 1.6; }
#run-log[hidden] { display: none; }
.log-line { white-space: pre-wrap; word-break: break-all; color: #d4d3cb; }
.log-line.log-debug { color: #7d7c74; }
.log-line.log-warning { color: #e8b339; }
.log-line.log-error { color: #e85d4f; }
"""
)

_PAGE_HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>osmos</title>
<style>{_PAGE_CSS}</style>
</head>
<body>
<div class="wrap">
  <div class="topbar">
    <h1>osmos</h1>
    <button id="theme-toggle" type="button">Dark mode</button>
  </div>

  <div class="tabs">
    <button class="tab-btn active" data-tab="setup" type="button">Setup</button>
    <button class="tab-btn" data-tab="run" type="button">Run</button>
    <button class="tab-btn" data-tab="dashboard" type="button">Dashboard</button>
  </div>

  <div id="tab-setup" class="tab-panel active">
    <div class="card">
      <h2>Classification</h2>
      <form id="settings-form">
        <label>OpenRouter API key <span id="status-key" class="badge"></span></label>
        <input type="password" id="key-input" placeholder="Leave blank to keep the current key">
        <div class="hint">Never shown back once saved. Get one free at openrouter.ai/keys.</div>

        <label>Model</label>
        <input type="text" id="model-input">
        <div class="hint">Free slugs end in ":free" and rotate — see openrouter.ai/models?max_price=0 if this one stops working.</div>

        <label>Instagram cookies <span id="status-cookies" class="badge"></span></label>
        <textarea id="cookies-input" placeholder="Paste exported cookies here (cookies.txt or JSON) — only needed if the anonymous tier gets IP-blocked. Never paste a password here."></textarea>
        <div class="hint">Export from a logged-in browser session with a "cookies.txt" extension. Written locally with owner-only file permissions, never sent anywhere but Instagram.</div>

        <label>Instagram login (stronger, recommended) <span id="status-login" class="badge"></span></label>
        <div class="hint" style="margin-top:0">Set <code>INSTAGRAM_USERNAME</code> / <code>INSTAGRAM_PASSWORD</code> in <code>.env</code> directly — never typed into this page. Use a disposable account. See the README's "Auth" section.</div>

        <label>Proxy URL <span id="status-proxy" class="badge"></span></label>
        <input type="text" id="proxy-input" placeholder="http://user:pass@host:8080 — only if you have a paid, non-shared proxy">

        <button type="submit">Save settings</button>
      </form>
    </div>
  </div>

  <div id="tab-run" class="tab-panel">
    <div class="card">
      <h2>Collect &amp; classify</h2>
      <form id="run-form">
        <label>Usernames (one per line, or comma-separated, @ optional)</label>
        <textarea id="usernames-input" placeholder="nike&#10;gordonramsay&#10;dogsofinstagram"></textarea>
        <div class="field-row">
          <div>
            <label>Posts per profile</label>
            <input type="number" id="posts-input" value="12" min="1" max="50">
          </div>
        </div>
        <button type="submit">Collect + classify</button>
        <button type="button" class="btn-secondary" id="classify-only-btn">Classify pending only</button>
      </form>
      <div id="run-output"></div>
      <pre id="run-log" hidden></pre>
    </div>
    <div class="card">
      <h2>Discover more usernames</h2>
      <p class="hint" style="margin-top:0">Accounts @mentioned across posts you've already collected — osmos_core has no search endpoint, so this is the way to find more.</p>
      <button type="button" class="btn-secondary" id="discover-btn" style="margin-left:0">Find candidates</button>
      <div id="discover-output"></div>
    </div>
  </div>

  <div id="tab-dashboard" class="tab-panel">
    <div class="kpis">
      <div class="kpi"><div class="label">Profiles collected</div><div class="value" id="kpi-total">—</div></div>
      <div class="kpi"><div class="label">Classified</div><div class="value" id="kpi-classified">—</div></div>
      <div class="kpi"><div class="label">Avg. confidence</div><div class="value" id="kpi-confidence">—</div></div>
    </div>
    <div class="card">
      <h2>By category</h2>
      <div id="chart"></div>
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
</div>
<div id="tooltip" hidden></div>

<script>
// ---------- tabs ----------
document.querySelectorAll(".tab-btn").forEach(function (btn) {{
  btn.addEventListener("click", function () {{
    document.querySelectorAll(".tab-btn").forEach(function (b) {{ b.classList.toggle("active", b === btn); }});
    document.querySelectorAll(".tab-panel").forEach(function (p) {{ p.classList.toggle("active", p.id === "tab-" + btn.dataset.tab); }});
    if (btn.dataset.tab === "dashboard") loadDashboard();
    if (btn.dataset.tab === "setup") loadStatus();
  }});
}});

// ---------- theme ----------
const themeToggle = document.getElementById("theme-toggle");
function applyTheme(theme) {{
  document.documentElement.setAttribute("data-theme", theme);
  themeToggle.textContent = theme === "dark" ? "Light mode" : "Dark mode";
}}
let savedTheme = null;
try {{ savedTheme = localStorage.getItem("osmos-theme"); }} catch (e) {{}}
applyTheme(savedTheme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
themeToggle.addEventListener("click", function () {{
  const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
  applyTheme(next);
  try {{ localStorage.setItem("osmos-theme", next); }} catch (e) {{}}
}});

// ---------- setup ----------
function badge(el, ok, onText, offText) {{
  el.textContent = ok ? onText : offText;
  el.className = "badge " + (ok ? "good" : "neutral");
}}
let _defaultTabChosen = false;
async function loadStatus() {{
  const s = await (await fetch("/api/status")).json();
  badge(document.getElementById("status-key"), s.has_api_key, "Configured", "Required — not set");
  if (!s.has_api_key) document.getElementById("status-key").className = "badge missing";
  document.getElementById("model-input").value = s.classifier_model;
  badge(document.getElementById("status-cookies"), s.has_cookies, "Configured", "Not set — public profiles only");
  badge(document.getElementById("status-login"), s.has_instagram_login,
    s.has_instagram_session ? "Configured, session active" : "Configured", "Not set — see .env");
  badge(document.getElementById("status-proxy"), s.has_proxy, "Configured", "Not set");
  document.getElementById("posts-input").value = s.posts_per_profile;

  // First load only: jump straight to Run when nothing's left to configure —
  // most sessions start with .env already set up, so Setup is a dead end.
  if (!_defaultTabChosen) {{
    _defaultTabChosen = true;
    if (s.ready) document.querySelector('.tab-btn[data-tab="run"]').click();
  }}
  return s;
}}
document.getElementById("settings-form").addEventListener("submit", async function (e) {{
  e.preventDefault();
  const btn = e.target.querySelector("button[type=submit]");
  btn.disabled = true; btn.textContent = "Saving…";
  await fetch("/api/settings", {{
    method: "POST", headers: {{"Content-Type": "application/json"}},
    body: JSON.stringify({{
      openrouter_api_key: document.getElementById("key-input").value || null,
      classifier_model: document.getElementById("model-input").value || null,
      proxy_url: document.getElementById("proxy-input").value || null,
      cookies_text: document.getElementById("cookies-input").value || null,
    }}),
  }});
  document.getElementById("key-input").value = "";
  document.getElementById("cookies-input").value = "";
  btn.disabled = false; btn.textContent = "Save settings";
  loadStatus();
}});

// ---------- run ----------
function parseUsernames(text) {{
  const seen = [];
  text.split(/[\\n,]/).forEach(function (line) {{
    const name = line.trim().replace(/^@/, "");
    if (name && !name.startsWith("#") && seen.indexOf(name) === -1) seen.push(name);
  }});
  return seen;
}}
function setRunStatus(out, text, spinning) {{
  out.innerHTML = "";
  if (spinning) {{
    const wrap = document.createElement("div");
    wrap.className = "run-status";
    const spin = document.createElement("div");
    spin.className = "spinner";
    const label = document.createElement("span");
    label.textContent = text;
    wrap.appendChild(spin); wrap.appendChild(label);
    out.appendChild(wrap);
  }} else {{
    out.textContent = text;
  }}
}}

function appendLogLine(logEl, item) {{
  const line = document.createElement("div");
  line.className = "log-line log-" + item.level.toLowerCase();
  line.textContent = item.message;
  logEl.appendChild(line);
  logEl.scrollTop = logEl.scrollHeight;
}}

async function runWithLogStream(usernames, posts, logEl) {{
  logEl.hidden = false;
  logEl.innerHTML = "";
  const response = await fetch("/api/run/stream", {{
    method: "POST", headers: {{"Content-Type": "application/json"}},
    body: JSON.stringify({{usernames: usernames, posts: posts}}),
  }});
  if (!response.ok) {{
    const data = await response.json().catch(function () {{ return {{}}; }});
    throw new Error(data.detail || "request failed");
  }}
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result = null;
  while (true) {{
    const chunk = await reader.read();
    if (chunk.done) break;
    buffer += decoder.decode(chunk.value, {{stream: true}});
    const parts = buffer.split("\\n\\n");
    buffer = parts.pop();
    for (const part of parts) {{
      if (!part.startsWith("data: ")) continue;
      const item = JSON.parse(part.slice(6));
      if (item.type === "done" || item.type === "error") {{ result = item; }}
      else {{ appendLogLine(logEl, item); }}
    }}
  }}
  if (!result) throw new Error("stream ended without a result");
  if (result.type === "error") throw new Error(result.message);
  return result;
}}

document.getElementById("run-form").addEventListener("submit", async function (e) {{
  e.preventDefault();
  const usernames = parseUsernames(document.getElementById("usernames-input").value);
  const posts = parseInt(document.getElementById("posts-input").value, 10) || 12;
  const out = document.getElementById("run-output");
  const logEl = document.getElementById("run-log");
  const btn = e.target.querySelector("button[type=submit]");
  if (!usernames.length) {{ setRunStatus(out, "Enter at least one username first.", false); return; }}
  btn.disabled = true; btn.textContent = "Running…";
  setRunStatus(out, "Collecting " + usernames.length + " profile(s) — this talks to Instagram, can take a while…", true);
  try {{
    const data = await runWithLogStream(usernames, posts, logEl);
    setRunStatus(out, "Collected " + data.collected + "/" + data.total + ". Classified " + data.classified + ".", false);
  }} catch (err) {{
    setRunStatus(out, "Error: " + err.message, false);
  }}
  btn.disabled = false; btn.textContent = "Collect + classify";
}});
document.getElementById("classify-only-btn").addEventListener("click", async function (e) {{
  const out = document.getElementById("run-output");
  const btn = e.target;
  btn.disabled = true;
  setRunStatus(out, "Classifying pending profiles…", true);
  const data = await (await fetch("/api/classify", {{method: "POST"}})).json();
  setRunStatus(out, "Classified " + data.classified + ".", false);
  btn.disabled = false;
}});
document.getElementById("discover-btn").addEventListener("click", async function (e) {{
  const out = document.getElementById("discover-output");
  const btn = e.target;
  btn.disabled = true;
  setRunStatus(out, "Looking for mentioned usernames…", true);
  const data = await (await fetch("/api/discover")).json();
  out.innerHTML = "";
  btn.disabled = false;
  if (!data.candidates.length) {{ out.textContent = "No new candidates yet — collect more profiles first."; return; }}
  const list = document.createElement("div");
  data.candidates.forEach(function (c) {{
    const row = document.createElement("div");
    row.style.fontSize = "13px"; row.style.padding = "3px 0"; row.style.color = "var(--text-secondary)";
    row.textContent = "@" + c[0] + " — mentioned " + c[1] + "× ";
    list.appendChild(row);
  }});
  out.appendChild(list);
}});

// ---------- dashboard ----------
let DASH_ROWS = [];
let sortKey = "follower_count", sortDir = -1, categoryFilter = null, searchText = "";

function categoryOf(row) {{ return row.category || "(unclassified)"; }}

function showDashboardSkeleton() {{
  ["kpi-total", "kpi-classified", "kpi-confidence"].forEach(function (id) {{
    const el = document.getElementById(id);
    el.textContent = "";
    el.classList.add("skeleton");
  }});
  const chart = document.getElementById("chart");
  chart.innerHTML = "";
  for (let i = 0; i < 4; i++) {{
    const row = document.createElement("div");
    row.className = "bar-row";
    row.innerHTML = '<div class="bar-label skeleton skeleton-bar" style="width:70px"></div>' +
      '<div class="bar-track"><div class="skeleton skeleton-bar" style="width:100%;height:100%"></div></div>' +
      '<div class="bar-value skeleton skeleton-bar" style="width:24px"></div>';
    chart.appendChild(row);
  }}
  const tbody = document.getElementById("table-body");
  tbody.innerHTML = "";
  for (let i = 0; i < 6; i++) {{
    const tr = document.createElement("tr");
    tr.className = "skeleton-row";
    for (let c = 0; c < 5; c++) {{
      const td = document.createElement("td");
      td.innerHTML = '<div class="skeleton skeleton-bar" style="width:' + (40 + Math.random() * 50) + '%"></div>';
      tr.appendChild(td);
    }}
    tbody.appendChild(tr);
  }}
}}

async function loadDashboard() {{
  showDashboardSkeleton();
  const data = await (await fetch("/api/profiles")).json();
  ["kpi-total", "kpi-classified", "kpi-confidence"].forEach(function (id) {{
    document.getElementById(id).classList.remove("skeleton");
  }});
  DASH_ROWS = data.rows;
  document.getElementById("kpi-total").textContent = data.total;
  document.getElementById("kpi-classified").textContent = data.classified;
  document.getElementById("kpi-confidence").textContent = data.avg_confidence_pct != null ? data.avg_confidence_pct + "%" : "—";

  const maxCount = data.categories.length ? data.categories[0][1] : 0;
  const chart = document.getElementById("chart");
  chart.innerHTML = "";
  if (!data.categories.length) {{
    chart.innerHTML = '<p style="color:var(--muted);font-size:13px;">No profiles collected yet.</p>';
  }}
  data.categories.forEach(function (pair) {{
    const category = pair[0], count = pair[1];
    const pct = maxCount ? Math.max(count / maxCount * 100, 1.5) : 1.5;
    const row = document.createElement("div");
    row.className = "bar-row"; row.dataset.category = category;
    row.innerHTML = '<div class="bar-label">' + category + '</div>' +
      '<div class="bar-track"><div class="bar-fill" style="width:' + pct + '%"></div></div>' +
      '<div class="bar-value">' + count + "</div>";
    row.addEventListener("click", function () {{ setCategoryFilter(categoryFilter === category ? null : category); }});
    row.addEventListener("mousemove", function (e) {{
      tooltip.hidden = false;
      tooltip.textContent = category + ": " + count;
      tooltip.style.left = (e.clientX + 14) + "px"; tooltip.style.top = (e.clientY + 14) + "px";
    }});
    row.addEventListener("mouseleave", function () {{ tooltip.hidden = true; }});
    chart.appendChild(row);
  }});
  renderTable();
}}

function cell(text, opts) {{
  const td = document.createElement("td");
  if (opts && opts.expandable) {{
    // Truncating/ellipsis on a <td> itself is unreliable in auto-layout
    // tables — different rows can render inconsistently. An inner span
    // with its own max-width is the robust version of the same thing.
    const span = document.createElement("span");
    span.className = "truncate";
    span.textContent = text;
    span.addEventListener("click", function () {{ span.classList.toggle("expanded"); }});
    td.appendChild(span);
  }} else {{
    td.textContent = text;
    if (opts && opts.className) td.className = opts.className;
  }}
  return td;
}}

function renderTable() {{
  const rows = DASH_ROWS.filter(function (r) {{
    if (categoryFilter !== null && categoryOf(r) !== categoryFilter) return false;
    if (searchText) {{
      const hay = [r.username, r.biography, r.reasoning].filter(Boolean).join(" ").toLowerCase();
      if (hay.indexOf(searchText.toLowerCase()) === -1) return false;
    }}
    return true;
  }});
  rows.sort(function (a, b) {{
    let av = a[sortKey], bv = b[sortKey];
    if (av === null || av === undefined) av = sortDir === 1 ? Infinity : -Infinity;
    if (bv === null || bv === undefined) bv = sortDir === 1 ? Infinity : -Infinity;
    if (typeof av === "string" || typeof bv === "string") return sortDir * String(av).localeCompare(String(bv));
    return sortDir * (av - bv);
  }});
  const tbody = document.getElementById("table-body");
  tbody.innerHTML = "";
  rows.forEach(function (r) {{
    const tr = document.createElement("tr");
    tr.appendChild(cell("@" + r.username));
    tr.appendChild(cell(categoryOf(r)));
    tr.appendChild(cell(r.confidence != null ? Math.round(r.confidence * 100) + "%" : "—", {{className: "num"}}));
    tr.appendChild(cell(r.follower_count != null ? r.follower_count.toLocaleString() : "—", {{className: "num"}}));
    tr.appendChild(cell(r.reasoning || "—", {{expandable: true}}));
    tbody.appendChild(tr);
  }});
  document.getElementById("row-count").textContent = "Showing " + rows.length + " of " + DASH_ROWS.length;
  document.querySelectorAll("th[data-key]").forEach(function (th) {{
    th.querySelector(".arrow").textContent = th.dataset.key === sortKey ? (sortDir === 1 ? "▲" : "▼") : "";
  }});
}}

document.querySelectorAll("th[data-key]").forEach(function (th) {{
  th.addEventListener("click", function () {{
    if (sortKey === th.dataset.key) {{ sortDir *= -1; }} else {{ sortKey = th.dataset.key; sortDir = 1; }}
    renderTable();
  }});
}});
document.getElementById("search").addEventListener("input", function (e) {{ searchText = e.target.value; renderTable(); }});
const clearBtn = document.getElementById("clear-filter");
function setCategoryFilter(cat) {{
  categoryFilter = cat;
  document.querySelectorAll(".bar-row").forEach(function (el) {{ el.classList.toggle("active", el.dataset.category === cat); }});
  clearBtn.classList.toggle("visible", cat !== null);
  renderTable();
}}
clearBtn.addEventListener("click", function () {{ setCategoryFilter(null); }});
const tooltip = document.getElementById("tooltip");

loadStatus();
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _PAGE_HTML


@app.exception_handler(Exception)
async def _unhandled(request, exc: Exception) -> JSONResponse:  # noqa: ARG001
    return JSONResponse(status_code=500, content={"detail": str(exc)})
