#!/usr/bin/env python3
"""Claude Token Viewer for Steam Deck.

A zero-dependency local dashboard that reads Claude Code's usage logs
(~/.claude/projects/**/*.jsonl) and serves a Deck-sized (1280x800) visual
summary of your token usage: today's spend, daily history, and a per-model
breakdown.

Run:  python3 token-viewer.py            (then open http://localhost:8484)
      python3 token-viewer.py --port 9000 --host 0.0.0.0

Only the Python standard library is used, so it runs on stock SteamOS.
"""

import argparse
import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# ---------------------------------------------------------------------------
# Pricing (USD per million tokens). Cache write bills at 1.25x the input
# rate, cache read at 0.1x. Matched by substring, first hit wins, so more
# specific ids must come before generic ones. Unknown models still have
# their tokens counted but contribute $0 and are flagged in the UI.
# ---------------------------------------------------------------------------
PRICING = [
    ("fable-5", (10.0, 50.0)),
    ("mythos", (10.0, 50.0)),
    ("opus-4-8", (5.0, 25.0)),
    ("opus-4-7", (5.0, 25.0)),
    ("opus-4-6", (5.0, 25.0)),
    ("opus-4-5", (5.0, 25.0)),
    ("opus-4-1", (15.0, 75.0)),
    ("opus-4", (15.0, 75.0)),
    ("opus", (15.0, 75.0)),
    ("sonnet-5", (3.0, 15.0)),
    ("sonnet-4", (3.0, 15.0)),
    ("sonnet", (3.0, 15.0)),
    ("haiku-4-5", (1.0, 5.0)),
    ("3-5-haiku", (0.8, 4.0)),
    ("haiku", (0.25, 1.25)),
]
CACHE_WRITE_MULT = 1.25
CACHE_READ_MULT = 0.10


def rates_for(model):
    m = (model or "").lower()
    for key, rates in PRICING:
        if key in m:
            return rates
    return None


def cost_of(model, tok):
    r = rates_for(model)
    if r is None:
        return 0.0
    inp, out = r
    return (
        tok["in"] * inp
        + tok["out"] * out
        + tok["cw"] * inp * CACHE_WRITE_MULT
        + tok["cr"] * inp * CACHE_READ_MULT
    ) / 1_000_000


# ---------------------------------------------------------------------------
# Log scanning. Claude Code writes one JSONL transcript per session under
# <claude dir>/projects/<project>/<session>.jsonl. Assistant entries carry
# message.usage with the four token counters. The same message id can appear
# on several lines (text block, tool_use block, retries), so records are
# deduplicated on message.id + requestId before aggregation.
# ---------------------------------------------------------------------------
class UsageScanner:
    def __init__(self, claude_dirs):
        self.claude_dirs = claude_dirs
        self._file_cache = {}  # path -> (mtime, size, [records])
        self._lock = threading.Lock()

    def _parse_file(self, path):
        records = []
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except ValueError:
                        continue
                    if entry.get("type") != "assistant":
                        continue
                    msg = entry.get("message") or {}
                    usage = msg.get("usage") or {}
                    if not usage:
                        continue
                    model = msg.get("model") or ""
                    if model == "<synthetic>":
                        continue
                    ts_raw = entry.get("timestamp")
                    if not ts_raw:
                        continue
                    try:
                        ts = datetime.fromisoformat(
                            ts_raw.replace("Z", "+00:00")
                        ).timestamp()
                    except ValueError:
                        continue
                    records.append({
                        "key": f"{msg.get('id', '')}:{entry.get('requestId', '')}",
                        "ts": ts,
                        "model": model,
                        "in": usage.get("input_tokens", 0) or 0,
                        "out": usage.get("output_tokens", 0) or 0,
                        "cw": usage.get("cache_creation_input_tokens", 0) or 0,
                        "cr": usage.get("cache_read_input_tokens", 0) or 0,
                    })
        except OSError:
            pass
        return records

    def records(self):
        with self._lock:
            seen_paths = set()
            for base in self.claude_dirs:
                projects = Path(base) / "projects"
                if not projects.is_dir():
                    continue
                for path in projects.rglob("*.jsonl"):
                    p = str(path)
                    seen_paths.add(p)
                    try:
                        st = path.stat()
                    except OSError:
                        continue
                    cached = self._file_cache.get(p)
                    if cached and cached[0] == st.st_mtime and cached[1] == st.st_size:
                        continue
                    self._file_cache[p] = (st.st_mtime, st.st_size, self._parse_file(p))
            for stale in set(self._file_cache) - seen_paths:
                del self._file_cache[stale]

            out, seen_keys = [], set()
            for _, _, recs in self._file_cache.values():
                for r in recs:
                    if r["key"] in seen_keys and r["key"] != ":":
                        continue
                    seen_keys.add(r["key"])
                    out.append(r)
            return out


def zero():
    return {"in": 0, "out": 0, "cw": 0, "cr": 0, "cost": 0.0, "messages": 0}


def add(bucket, rec):
    for k in ("in", "out", "cw", "cr"):
        bucket[k] += rec[k]
    bucket["cost"] += cost_of(rec["model"], rec)
    bucket["messages"] += 1


def build_summary(scanner, days=30):
    records = scanner.records()
    today = datetime.now().date()
    start = today - timedelta(days=days - 1)
    day_buckets = {start + timedelta(days=i): zero() for i in range(days)}
    model_buckets = {}

    for rec in records:
        d = datetime.fromtimestamp(rec["ts"]).date()
        if d < start or d > today:
            continue
        add(day_buckets[d], rec)
        mb = model_buckets.setdefault(rec["model"], zero())
        add(mb, rec)

    def totals(since):
        t = zero()
        for d, b in day_buckets.items():
            if d >= since:
                for k in t:
                    t[k] += b[k]
        return t

    day_rows = []
    for d in sorted(day_buckets):
        b = day_buckets[d]
        day_rows.append({
            "date": d.isoformat(),
            "label": d.strftime("%b %-d") if os.name != "nt" else d.strftime("%b %d"),
            "total": b["in"] + b["out"] + b["cw"] + b["cr"],
            **b,
        })

    model_rows = []
    for model, b in sorted(model_buckets.items(), key=lambda kv: -kv[1]["cost"]):
        model_rows.append({
            "model": model,
            "total": b["in"] + b["out"] + b["cw"] + b["cr"],
            "known_pricing": rates_for(model) is not None,
            **b,
        })

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "days": day_rows,
        "models": model_rows,
        "totals": {
            "today": totals(today),
            "week": totals(today - timedelta(days=6)),
            "month": totals(start),
        },
        "sources": [str(d) for d in scanner.claude_dirs],
    }


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/usage"):
            data = build_summary(SCANNER)
            self._send(200, "application/json", json.dumps(data).encode())
        elif self.path == "/" or self.path.startswith("/index"):
            self._send(200, "text/html; charset=utf-8", PAGE.encode())
        else:
            self._send(404, "text/plain", b"not found")


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Claude Token Viewer</title>
<style>
  :root {
    --page: #0d0d0d; --surface: #1a1a19; --ink: #ffffff;
    --ink-2: #c3c2b7; --muted: #898781; --grid: #2c2c2a;
    --baseline: #383835; --border: rgba(255,255,255,0.10);
    --series: #3987e5; --series-dim: #1c5cab;
  }
  * { box-sizing: border-box; margin: 0; }
  html, body { background: var(--page); color: var(--ink);
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
  body { padding: 18px 22px 30px; max-width: 1280px; margin: 0 auto; }
  header { display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap;
    margin-bottom: 16px; }
  header h1 { font-size: 20px; font-weight: 650; }
  header .sub { color: var(--muted); font-size: 13px; }
  header .spacer { flex: 1; }
  .btn { background: var(--surface); border: 1px solid var(--border);
    color: var(--ink-2); border-radius: 10px; padding: 10px 18px;
    font-size: 15px; cursor: pointer; min-height: 44px; }
  .btn.active { color: var(--ink); border-color: var(--series);
    background: rgba(57,135,229,0.12); }
  .btn:focus-visible { outline: 2px solid var(--series); outline-offset: 2px; }
  .row { display: grid; gap: 12px; margin-bottom: 12px; }
  .kpis { grid-template-columns: 1.4fr 1fr 1fr 1fr 1fr; }
  .card { background: var(--surface); border: 1px solid var(--border);
    border-radius: 14px; padding: 14px 16px; }
  .kpi .label { color: var(--muted); font-size: 13px; margin-bottom: 6px; }
  .kpi .value { font-size: 26px; font-weight: 600; }
  .kpi.hero .value { font-size: 44px; }
  .kpi .hint { color: var(--muted); font-size: 12px; margin-top: 4px; }
  .charts { grid-template-columns: 3fr 2fr; }
  .card h2 { font-size: 14px; font-weight: 600; color: var(--ink-2);
    margin-bottom: 2px; }
  .card .subtitle { font-size: 12px; color: var(--muted); margin-bottom: 10px; }
  .toolbar { display: flex; gap: 8px; margin: 2px 0 10px; }
  svg text { font-family: inherit; }
  .axis { fill: var(--muted); font-size: 11px; }
  .dlabel { fill: var(--ink-2); font-size: 11px; }
  .bar-hit { fill: transparent; cursor: pointer; }
  #tooltip { position: fixed; pointer-events: none; background: #232322;
    border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px;
    font-size: 13px; color: var(--ink-2); display: none; z-index: 10;
    box-shadow: 0 6px 24px rgba(0,0,0,0.5); min-width: 170px; }
  #tooltip .t-date { color: var(--ink); font-weight: 600; margin-bottom: 6px; }
  #tooltip .t-row { display: flex; justify-content: space-between; gap: 16px; }
  #tooltip .t-row span:last-child { font-variant-numeric: tabular-nums; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: right; color: var(--muted); font-weight: 500;
    padding: 6px 10px; border-bottom: 1px solid var(--grid); }
  th:first-child, td:first-child { text-align: left; }
  td { text-align: right; padding: 6px 10px; color: var(--ink-2);
    border-bottom: 1px solid var(--grid);
    font-variant-numeric: tabular-nums; }
  tr:last-child td { border-bottom: none; }
  td.today, th.today { color: var(--ink); font-weight: 600; }
  .table-wrap { overflow-x: auto; }
  footer { color: var(--muted); font-size: 12px; margin-top: 14px;
    line-height: 1.5; }
  .warn { color: var(--ink-2); }
  @media (max-width: 900px) {
    .kpis { grid-template-columns: 1fr 1fr; }
    .charts { grid-template-columns: 1fr; }
  }
</style>
</head>
<body>
<header>
  <h1>Claude token usage</h1>
  <div class="sub" id="updated">loading&hellip;</div>
  <div class="spacer"></div>
  <button class="btn" id="refreshBtn">Refresh (R)</button>
</header>

<div class="row kpis">
  <div class="card kpi hero">
    <div class="label">Est. cost today</div>
    <div class="value" id="k-cost-today">–</div>
    <div class="hint">API-equivalent pricing</div>
  </div>
  <div class="card kpi"><div class="label">Tokens today</div>
    <div class="value" id="k-tok-today">–</div>
    <div class="hint" id="k-msg-today"></div></div>
  <div class="card kpi"><div class="label">Output today</div>
    <div class="value" id="k-out-today">–</div>
    <div class="hint">generated tokens</div></div>
  <div class="card kpi"><div class="label">Est. cost, 7 days</div>
    <div class="value" id="k-cost-week">–</div></div>
  <div class="card kpi"><div class="label">Est. cost, 30 days</div>
    <div class="value" id="k-cost-month">–</div></div>
</div>

<div class="row charts">
  <div class="card">
    <h2>Daily estimated cost</h2>
    <div class="subtitle">tap a bar for the full token breakdown</div>
    <div class="toolbar" id="rangeBtns">
      <button class="btn" data-range="7">7 days</button>
      <button class="btn active" data-range="14">14 days</button>
      <button class="btn" data-range="30">30 days</button>
    </div>
    <svg id="dailyChart" width="100%" height="260" role="img"
         aria-label="Bar chart of estimated daily cost"></svg>
  </div>
  <div class="card">
    <h2>Cost by model</h2>
    <div class="subtitle">last 30 days</div>
    <svg id="modelChart" width="100%" height="316" role="img"
         aria-label="Bar chart of estimated cost per model"></svg>
  </div>
</div>

<div class="row">
  <div class="card">
    <h2>Daily breakdown</h2>
    <div class="subtitle">last 14 days</div>
    <div class="table-wrap"><table id="dayTable"></table></div>
  </div>
</div>

<footer id="foot"></footer>
<div id="tooltip"></div>

<script>
"use strict";
let DATA = null, RANGE = 14;
const $ = (id) => document.getElementById(id);
const NS = "http://www.w3.org/2000/svg";

const fmtMoney = (v) => "$" + (v >= 100 ? v.toFixed(0) : v >= 10 ? v.toFixed(1) : v.toFixed(2));
const fmtTok = (v) => {
  if (v >= 1e9) return (v / 1e9).toFixed(2) + "B";
  if (v >= 1e6) return (v / 1e6).toFixed(1) + "M";
  if (v >= 1e3) return (v / 1e3).toFixed(1) + "K";
  return String(v);
};
const fmtInt = (v) => v.toLocaleString("en-US");

function el(name, attrs, text) {
  const e = document.createElementNS(NS, name);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (text !== undefined) e.textContent = text;
  return e;
}

function niceMax(v) {
  if (v <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 2, 2.5, 5, 10]) if (v <= m * p) return m * p;
  return 10 * p;
}

const tooltip = $("tooltip");
function showTip(evt, day) {
  tooltip.innerHTML =
    '<div class="t-date">' + day.label + "</div>" +
    tipRow("Est. cost", fmtMoney(day.cost)) +
    tipRow("Input", fmtTok(day["in"])) +
    tipRow("Output", fmtTok(day.out)) +
    tipRow("Cache write", fmtTok(day.cw)) +
    tipRow("Cache read", fmtTok(day.cr)) +
    tipRow("Messages", fmtInt(day.messages));
  tooltip.style.display = "block";
  const w = tooltip.offsetWidth, h = tooltip.offsetHeight;
  let x = evt.clientX + 14, y = evt.clientY - h - 10;
  if (x + w > window.innerWidth - 8) x = evt.clientX - w - 14;
  if (y < 8) y = evt.clientY + 14;
  tooltip.style.left = x + "px"; tooltip.style.top = y + "px";
}
const tipRow = (k, v) => '<div class="t-row"><span>' + k + "</span><span>" + v + "</span></div>";
const hideTip = () => { tooltip.style.display = "none"; };

function renderDaily() {
  const svg = $("dailyChart");
  svg.textContent = "";
  const days = DATA.days.slice(-RANGE);
  const W = svg.clientWidth || 700, H = 260;
  svg.setAttribute("viewBox", "0 0 " + W + " " + H);
  const m = { top: 18, right: 10, bottom: 26, left: 44 };
  const iw = W - m.left - m.right, ih = H - m.top - m.bottom;
  const max = niceMax(Math.max(...days.map((d) => d.cost), 0.01));
  const y = (v) => m.top + ih - (v / max) * ih;

  for (let i = 0; i <= 4; i++) {
    const v = (max / 4) * i, yy = y(v);
    svg.appendChild(el("line", { x1: m.left, x2: W - m.right, y1: yy, y2: yy,
      stroke: i === 0 ? "var(--baseline)" : "var(--grid)", "stroke-width": 1 }));
    svg.appendChild(el("text", { x: m.left - 8, y: yy + 4,
      "text-anchor": "end", class: "axis" }, "$" + (v >= 10 ? v.toFixed(0) : v.toFixed(1))));
  }

  const slot = iw / days.length;
  const bw = Math.min(24, slot * 0.62);
  const maxIdx = days.reduce((a, d, i) => (d.cost > days[a].cost ? i : a), 0);
  const todayIdx = days.length - 1;

  days.forEach((d, i) => {
    const cx = m.left + slot * i + slot / 2;
    const bh = Math.max(0, (d.cost / max) * ih);
    if (bh > 0) {
      const r = Math.min(4, bh);
      const x0 = cx - bw / 2, y0 = y(d.cost);
      svg.appendChild(el("path", {
        d: "M" + x0 + "," + (y0 + r) +
           " a" + r + "," + r + " 0 0 1 " + r + ",-" + r +
           " h" + (bw - 2 * r) +
           " a" + r + "," + r + " 0 0 1 " + r + "," + r +
           " v" + (bh - r) + " h-" + bw + " Z",
        fill: "var(--series)",
      }));
    }
    if ((i === maxIdx && d.cost > 0) || (i === todayIdx && d.cost > 0 && RANGE <= 14)) {
      svg.appendChild(el("text", { x: cx, y: y(d.cost) - 5,
        "text-anchor": "middle", class: "dlabel" }, fmtMoney(d.cost)));
    }
    const every = RANGE > 14 ? 5 : RANGE > 7 ? 2 : 1;
    if (i % every === 0 || i === todayIdx) {
      svg.appendChild(el("text", { x: cx, y: H - 8, "text-anchor": "middle",
        class: "axis" }, d.label));
    }
    const hit = el("rect", { x: m.left + slot * i, y: m.top, width: slot,
      height: ih, class: "bar-hit" });
    hit.addEventListener("mousemove", (e) => showTip(e, d));
    hit.addEventListener("mouseleave", hideTip);
    hit.addEventListener("click", (e) => showTip(e, d));
    svg.appendChild(hit);
  });
}

function renderModels() {
  const svg = $("modelChart");
  svg.textContent = "";
  const models = DATA.models.slice(0, 6);
  const W = svg.clientWidth || 420, H = 316;
  svg.setAttribute("viewBox", "0 0 " + W + " " + H);
  if (!models.length) {
    svg.appendChild(el("text", { x: W / 2, y: H / 2, "text-anchor": "middle",
      class: "axis" }, "no usage in the last 30 days"));
    return;
  }
  const m = { top: 8, right: 64, bottom: 8, left: 10 };
  const iw = W - m.left - m.right;
  const rowH = Math.min(52, (H - m.top - m.bottom) / models.length);
  const max = Math.max(...models.map((d) => d.cost), 0.001);

  models.forEach((d, i) => {
    const y0 = m.top + rowH * i;
    const name = d.model.replace(/^claude-/, "") + (d.known_pricing ? "" : " *");
    svg.appendChild(el("text", { x: m.left, y: y0 + 14, class: "axis",
      fill: "var(--ink-2)" }, name));
    const bw = Math.max(2, (d.cost / max) * iw);
    svg.appendChild(el("rect", { x: m.left, y: y0 + 20, width: bw, height: 16,
      rx: 4, fill: "var(--series)" }));
    svg.appendChild(el("text", { x: m.left + bw + 8, y: y0 + 33,
      class: "dlabel" }, d.known_pricing ? fmtMoney(d.cost) : fmtTok(d.total) + " tok"));
    const hit = el("rect", { x: 0, y: y0, width: W, height: rowH, class: "bar-hit" });
    hit.addEventListener("mousemove", (e) => showTip(e, { label: d.model, ...d }));
    hit.addEventListener("mouseleave", hideTip);
    hit.addEventListener("click", (e) => showTip(e, { label: d.model, ...d }));
    svg.appendChild(hit);
  });
}

function renderTable() {
  const days = DATA.days.slice(-14).slice().reverse();
  const head = "<tr><th>Date</th><th>Input</th><th>Output</th>" +
    "<th>Cache write</th><th>Cache read</th><th>Total</th><th>Est. cost</th></tr>";
  const rows = days.map((d, i) => {
    const c = i === 0 ? ' class="today"' : "";
    return "<tr>" +
      "<td" + c + ">" + d.label + (i === 0 ? " (today)" : "") + "</td>" +
      "<td" + c + ">" + fmtInt(d["in"]) + "</td>" +
      "<td" + c + ">" + fmtInt(d.out) + "</td>" +
      "<td" + c + ">" + fmtInt(d.cw) + "</td>" +
      "<td" + c + ">" + fmtInt(d.cr) + "</td>" +
      "<td" + c + ">" + fmtInt(d.total) + "</td>" +
      "<td" + c + ">" + fmtMoney(d.cost) + "</td></tr>";
  }).join("");
  $("dayTable").innerHTML = head + rows;
}

function render() {
  if (!DATA) return;
  const t = DATA.totals;
  $("k-cost-today").textContent = fmtMoney(t.today.cost);
  $("k-tok-today").textContent =
    fmtTok(t.today["in"] + t.today.out + t.today.cw + t.today.cr);
  $("k-msg-today").textContent = fmtInt(t.today.messages) + " messages";
  $("k-out-today").textContent = fmtTok(t.today.out);
  $("k-cost-week").textContent = fmtMoney(t.week.cost);
  $("k-cost-month").textContent = fmtMoney(t.month.cost);
  $("updated").textContent = "updated " + new Date().toLocaleTimeString();
  const unknown = DATA.models.some((d) => !d.known_pricing);
  $("foot").innerHTML =
    "Costs are the API-equivalent list price of the tokens used (input / output / " +
    "cache-write at 1.25&times; / cache-read at 0.1&times;) &mdash; on a subscription plan this is " +
    "an indicator of usage, not a bill." +
    (unknown ? ' <span class="warn">* model without a pricing entry: tokens counted, cost excluded.</span>' : "") +
    "<br>Reading: " + DATA.sources.join(", ") +
    " &middot; auto-refreshes every 60s &middot; keys: R refresh, &larr;/&rarr; change range";
  renderDaily(); renderModels(); renderTable();
}

async function load() {
  try {
    const res = await fetch("/api/usage");
    DATA = await res.json();
    render();
  } catch (e) {
    $("updated").textContent = "failed to load - is the server running?";
  }
}

$("rangeBtns").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-range]");
  if (!b) return;
  RANGE = +b.dataset.range;
  document.querySelectorAll("#rangeBtns .btn").forEach((x) =>
    x.classList.toggle("active", x === b));
  renderDaily();
});
$("refreshBtn").addEventListener("click", load);

document.addEventListener("keydown", (e) => {
  const ranges = [7, 14, 30];
  if (e.key === "r" || e.key === "R") load();
  if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
    let i = ranges.indexOf(RANGE) + (e.key === "ArrowRight" ? 1 : -1);
    i = Math.max(0, Math.min(ranges.length - 1, i));
    RANGE = ranges[i];
    document.querySelectorAll("#rangeBtns .btn").forEach((x) =>
      x.classList.toggle("active", +x.dataset.range === RANGE));
    renderDaily();
  }
});
window.addEventListener("resize", () => { renderDaily(); renderModels(); });

load();
setInterval(load, 60000);
</script>
</body>
</html>
"""


def default_claude_dirs():
    dirs = []
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    if env:
        dirs.append(Path(env))
    dirs.append(Path.home() / ".claude")
    dirs.append(Path.home() / ".config" / "claude")
    return [d for d in dirs if (d / "projects").is_dir()] or [Path.home() / ".claude"]


SCANNER = None


def main():
    global SCANNER
    ap = argparse.ArgumentParser(description="Claude token usage dashboard")
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind address (0.0.0.0 to view from other devices)")
    ap.add_argument("--port", type=int, default=8484)
    ap.add_argument("--claude-dir", action="append", default=None,
                    help="Claude data dir containing projects/ (repeatable)")
    args = ap.parse_args()

    dirs = [Path(d).expanduser() for d in args.claude_dir] if args.claude_dir \
        else default_claude_dirs()
    SCANNER = UsageScanner(dirs)

    found = sum(1 for d in dirs if (d / "projects").is_dir())
    if not found:
        print(f"warning: no projects/ folder under {', '.join(map(str, dirs))} - "
              "the dashboard will be empty until Claude Code writes usage logs there",
              file=sys.stderr)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Claude Token Viewer at http://{args.host}:{args.port}  "
          f"(reading: {', '.join(map(str, dirs))})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
