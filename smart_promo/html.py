"""Self-contained HTML for the smart promotions dashboard."""
from __future__ import annotations

import html as html_lib
import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _chart_script_tag() -> str:
    vendor = os.path.join(str(_REPO_ROOT), "vendor", "chart.umd.min.js")
    if os.path.isfile(vendor):
        with open(vendor, "r", encoding="utf-8") as f:
            body = f.read().replace("</script>", "<\\/script>")
        return f"<script>\n{body}\n</script>"
    return '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>'


def _html_template(title: str, subtitle: str, data_json: str, build_banner: str, dashboard_version: str) -> str:
    esc = html_lib.escape
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)}</title>
  <meta name="smart-promo-dashboard" content="{esc(dashboard_version)}" />
  {_chart_script_tag()}
  <style>
    :root {{
      --bolt-green: #2A9C64; --bolt-green-dark: #1e7a4d; --bolt-bg: #f6f8f6;
      --bolt-card: #ffffff; --bolt-border: #e0e6e0; --bolt-muted: #607d6b;
      --bolt-text: #1a1a1a; --bolt-blue: #1565c0; --bolt-orange: #ef6c00;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bolt-bg); color: var(--bolt-text); }}
    .wrap {{ max-width: 1280px; margin: 0 auto; padding: 0 1rem 2rem; }}
    header {{ background: linear-gradient(135deg, #2A9C64 0%, #1e7a4d 100%); color: #fff;
      padding: 1.4rem 1.6rem; border-radius: 0 0 16px 16px; }}
    header h1 {{ font-size: 1.45rem; font-weight: 700; }}
    header .sub {{ margin-top: .35rem; opacity: .92; font-size: .82rem; line-height: 1.35; max-width: 900px; }}
    .filters {{ display: flex; gap: .65rem; align-items: center; margin: 1rem 0; flex-wrap: wrap; }}
    .filters label {{ font-size: .82rem; color: var(--bolt-muted); font-weight: 600; }}
    .filters select, .filters input[type="search"], .filters input[type="date"] {{
      padding: .4rem .65rem; border-radius: 8px; border: 1px solid var(--bolt-border);
      font-size: .82rem; margin-left: .35rem; min-width: 140px; }}
    .filters input[type="date"] {{ min-width: 11rem; }}
    .search-wrap {{ position: relative; display: inline-flex; align-items: center; }}
    .search-wrap input[type="search"] {{ padding-right: 1.6rem; min-width: 200px; }}
    .search-clear {{ position: absolute; right: .4rem; background: none; border: none;
      cursor: pointer; color: var(--bolt-muted); font-size: 1rem; line-height: 1;
      padding: 0; display: none; }}
    .search-clear:hover {{ color: var(--bolt-text); }}
    mark.hl {{ background: #fff176; border-radius: 2px; padding: 0 1px; }}
    .date-range-box {{
      display: flex; flex-wrap: wrap; align-items: center; gap: .45rem .75rem;
      border: 2px solid var(--bolt-green); border-radius: 10px; padding: .5rem .85rem;
      background: linear-gradient(180deg, #e8f5ec 0%, #fff 55%);
      width: 100%; box-sizing: border-box; margin-bottom: .35rem; }}
    .date-range-heading {{
      font-size: .82rem; font-weight: 800; color: var(--bolt-green-dark); letter-spacing: .02em;
      margin-right: .25rem; }}
    .date-presets {{ display: inline-flex; flex-wrap: wrap; gap: .35rem; align-items: center; margin-left: .25rem; }}
    .preset-btn {{
      font-size: .74rem; padding: .28rem .55rem; border-radius: 6px; border: 1px solid var(--bolt-border);
      background: #fff; color: var(--bolt-text); cursor: pointer; font-weight: 600; }}
    .preset-btn:hover {{ background: #eef7f1; border-color: var(--bolt-green); }}
    .tabs {{ display: flex; gap: .35rem; flex-wrap: wrap; margin-bottom: 1rem; }}
    .tab {{ padding: .45rem 1rem; border: none; background: #eef3ee; border-radius: 8px;
      cursor: pointer; font-size: .82rem; font-weight: 600; color: var(--bolt-muted); }}
    .tab.active {{ background: var(--bolt-green); color: #fff; }}
    .panel {{ background: var(--bolt-card); border: 1px solid var(--bolt-border);
      border-radius: 12px; padding: 1rem 1.2rem; margin-bottom: 1rem; }}
    .panel h2 {{ font-size: .95rem; font-weight: 700; margin-bottom: .65rem; color: var(--bolt-green-dark); }}
    .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
      gap: .75rem; margin-bottom: 1rem; }}
    .kpi {{ background: var(--bolt-card); border: 1px solid var(--bolt-border); border-radius: 10px;
      padding: .75rem 1rem; text-align: center; }}
    .kpi h3 {{ font-size: .68rem; text-transform: uppercase; color: var(--bolt-muted);
      letter-spacing: .4px; margin-bottom: .25rem; }}
    .kpi .val {{ font-size: 1.25rem; font-weight: 700; }}
    .kpi .val.bolt {{ color: var(--bolt-blue); }}
    .kpi .val.prov {{ color: var(--bolt-orange); }}
    .grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }}
    @media (max-width: 960px) {{ .grid2 {{ grid-template-columns: 1fr; }} }}
    canvas {{ max-height: 320px; }}
    table.data {{ width: 100%; border-collapse: collapse; font-size: .8rem; }}
    table.data th, table.data td {{
      border-bottom: 1px solid var(--bolt-border); padding: .4rem .55rem;
      text-align: right; vertical-align: top; }}
    table.data th:first-child, table.data td:first-child {{ text-align: left; max-width: 420px;
      white-space: normal; word-break: break-word; }}
    table.data th {{ background: #fafcfa; color: var(--bolt-muted); font-weight: 600; white-space: nowrap; }}
    table.data th.sortable {{ cursor: pointer; user-select: none; color: var(--bolt-green-dark); }}
    .section-hidden {{ display: none !important; }}
    .hint {{ font-size: .78rem; color: var(--bolt-muted); margin-bottom: .5rem; }}
    .build-banner {{
      font-size: .78rem; background: #fff8e1; border-bottom: 1px solid #ffe082; color: #5d4037;
      padding: .45rem 1rem; margin: 0; text-align: center; }}
    .filter-dock-wrap {{
      position: sticky; top: 0; z-index: 50;
      background: linear-gradient(180deg, #f6f8f6 0%, #eef3ee 100%);
      border-bottom: 2px solid var(--bolt-green);
      padding: .55rem 0 .65rem; margin: 0 0 .5rem 0;
      box-shadow: 0 2px 8px rgba(0,0,0,.07); }}
    .primary-filters {{
      display: flex; align-items: center; gap: .55rem; flex-wrap: wrap;
      padding: .35rem 0; }}
    .primary-filters .pf-group {{ display: flex; align-items: center; gap: .35rem; }}
    .primary-filters .pf-lbl {{
      font-size: .7rem; font-weight: 800; letter-spacing: .05em;
      color: var(--bolt-muted); text-transform: uppercase; }}
    .primary-filters .pf-ctrl {{
      padding: .5rem .7rem; border-radius: 8px; border: 1px solid var(--bolt-border);
      background: #fff; font-size: .85rem; min-width: 170px; color: var(--bolt-text);
      margin-left: 0; }}
    .primary-filters .pf-ctrl.pf-wide {{ min-width: 240px; }}
    .primary-filters .pf-sep {{
      width: 1px; align-self: stretch; background: var(--bolt-border); margin: 0 .1rem; }}
    .view-toggle {{ display: inline-flex; border: 1px solid var(--bolt-border);
      border-radius: 8px; overflow: hidden; background: #fff; }}
    .view-toggle .vt {{
      padding: .5rem .95rem; border: none; background: transparent;
      font-size: .82rem; font-weight: 700; color: var(--bolt-muted); cursor: pointer; }}
    .view-toggle .vt.active {{ background: var(--bolt-green); color: #fff; }}
    .hidden-filters {{ display: none !important; }}
    .combo-wrap {{ position: relative; display: inline-flex; align-items: center; }}
    .combo-input {{
      padding: .5rem .9rem .5rem .7rem; border-radius: 8px; border: 1px solid var(--bolt-border);
      background: #fff; font-size: .85rem; min-width: 260px; color: var(--bolt-text);
      outline: none; }}
    .combo-input:focus {{ border-color: var(--bolt-green); box-shadow: 0 0 0 2px #b7e3c7; }}
    .combo-clear {{ position: absolute; right: .45rem; background: none; border: none;
      color: var(--bolt-muted); cursor: pointer; font-size: 1rem; line-height: 1;
      padding: 0; display: none; }}
    .combo-clear:hover {{ color: var(--bolt-text); }}
    .combo-list {{
      position: absolute; top: calc(100% + 4px); left: 0; right: 0; z-index: 60;
      max-height: 280px; overflow-y: auto;
      background: #fff; border: 1px solid var(--bolt-border); border-radius: 8px;
      box-shadow: 0 8px 24px rgba(0,0,0,.10); display: none; }}
    .combo-list.open {{ display: block; }}
    .combo-opt {{ padding: .45rem .75rem; font-size: .82rem; cursor: pointer; }}
    .combo-opt:hover, .combo-opt.active {{ background: #eef7f1; color: var(--bolt-green-dark); }}
    .combo-none {{ padding: .45rem .75rem; font-size: .82rem; color: var(--bolt-muted); }}
    .combo-wrap {{ position: relative; display: inline-flex; align-items: center; }}
    .combo-input {{
      padding: .5rem 2rem .5rem .7rem; border-radius: 8px;
      border: 1px solid var(--bolt-border); background: #fff;
      font-size: .85rem; min-width: 240px; color: var(--bolt-text); }}
    .combo-input:focus {{ outline: none; border-color: var(--bolt-green);
      box-shadow: 0 0 0 3px rgba(42,156,100,.15); }}
    .combo-clear {{
      position: absolute; right: .35rem; background: none; border: none;
      cursor: pointer; color: var(--bolt-muted); font-size: 1.05rem;
      line-height: 1; padding: .15rem .3rem; display: none; border-radius: 4px; }}
    .combo-clear:hover {{ color: var(--bolt-text); background: #f0f4f0; }}
    .combo-list {{
      position: absolute; top: calc(100% + 4px); left: 0;
      min-width: 100%; max-height: 320px; overflow-y: auto;
      background: #fff; border: 1px solid var(--bolt-border);
      border-radius: 8px; box-shadow: 0 6px 18px rgba(0,0,0,.10);
      z-index: 60; display: none; }}
    .combo-list.open {{ display: block; }}
    .combo-opt {{
      padding: .45rem .75rem; font-size: .85rem; color: var(--bolt-text);
      cursor: pointer; white-space: nowrap; }}
    .combo-opt.active, .combo-opt:hover {{ background: #eef7f1; color: var(--bolt-green-dark); }}
    .combo-opt.all-opt {{ font-weight: 700; color: var(--bolt-green-dark);
      border-bottom: 1px solid var(--bolt-border); }}
    .combo-none {{ padding: .45rem .75rem; font-size: .85rem; color: var(--bolt-muted); }}
    .combo-meta {{ font-size: .72rem; color: var(--bolt-muted); margin-left: .4rem; }}
    .btn-load {{
      background: var(--bolt-green); color: #fff; border: none; border-radius: 8px;
      padding: .55rem 1.1rem; font-weight: 700; font-size: .85rem; cursor: pointer;
      margin-left: auto; }}
    .btn-load:hover {{ background: var(--bolt-green-dark); }}
  </style>
</head>
<body>
  <!-- Smart promotions dashboard -->
  <header>
    <h1>{esc(title)}</h1>
    <div class="sub">{esc(subtitle)}</div>
  </header>
  <p class="build-banner">{esc(build_banner)}</p>
  <div class="filter-dock-wrap">
    <div class="wrap">
      <div class="primary-filters">
        <div class="view-toggle" role="tablist" aria-label="Entity view">
          <button type="button" class="vt active" id="vtProvider" role="tab" aria-selected="true">Provider</button>
          <button type="button" class="vt" id="vtBrand" role="tab" aria-selected="false">Brand</button>
        </div>
        <div class="pf-group" id="pfProviderGroup">
          <span class="pf-lbl">Provider</span>
          <div class="combo-wrap" id="providerComboWrap">
            <input type="text" class="combo-input" id="providerComboInput" placeholder="Type to search…" autocomplete="off" spellcheck="false" aria-label="Provider" />
            <button type="button" class="combo-clear" id="providerComboClear" title="Clear" aria-label="Clear provider">×</button>
            <div class="combo-list" id="providerComboList" role="listbox"></div>
          </div>
          <input type="hidden" id="provSel" value="all" />
        </div>
        <div class="pf-group" id="pfBrandGroup" style="display:none">
          <span class="pf-lbl">Brand</span>
          <div class="combo-wrap" id="brandComboWrap">
            <input type="text" class="combo-input" id="brandComboInput" placeholder="Type to search brands…" autocomplete="off" spellcheck="false" aria-label="Brand" />
            <button type="button" class="combo-clear" id="brandComboClear" title="Clear" aria-label="Clear brand">×</button>
            <div class="combo-list" id="brandComboList" role="listbox"></div>
          </div>
          <input type="hidden" id="brandSel" value="all" />
        </div>
        <div class="pf-sep" aria-hidden="true"></div>
        <div class="pf-group">
          <span class="pf-lbl">From</span>
          <input type="date" id="dateFromIn" class="pf-ctrl" aria-label="Order date from" />
        </div>
        <div class="pf-group">
          <span class="pf-lbl">To</span>
          <input type="date" id="dateToIn" class="pf-ctrl" aria-label="Order date to" />
        </div>
        <button type="button" class="btn-load" id="loadReportBtn">Load Report</button>
      </div>
      <!-- Hidden filters kept for JS compatibility; always default to "all". -->
      <div class="hidden-filters" aria-hidden="true">
        <select id="audSel"><option value="all">All</option></select>
        <select id="lifeSel"><option value="all">All</option></select>
        <select id="lcsSel"><option value="all">All</option></select>
        <select id="enrCohortSel"><option value="all">All</option></select>
        <select id="reasonSel"><option value="all">All</option></select>
        <select id="amSel"><option value="all">All</option></select>
        <select id="segSel"><option value="all">All</option></select>
        <select id="objSel"><option value="all">All</option></select>
        <input type="search" id="searchIn" value="" />
        <button type="button" id="searchClear">×</button>
        <button type="button" class="preset-btn" data-preset="full"></button>
        <button type="button" class="preset-btn" data-preset="30"></button>
        <button type="button" class="preset-btn" data-preset="7"></button>
      </div>
    </div>
  </div>
  <div class="wrap">
    <p class="hint" style="margin:-0.15rem 0 0.75rem">Pick a <strong>Provider</strong> or <strong>Brand</strong> and a date range, then click <strong>Load Report</strong>. The <strong>Targeting cohorts</strong> tab uses the <strong>same filters</strong> (dates, provider/brand, advanced filters) as Spend analysis.</p>
    <div class="tabs" id="mainTabs">
      <button type="button" class="tab active" data-tab="tab-spend">Spend by report reason</button>
      <button type="button" class="tab" data-tab="tab-cohort">Targeting cohorts</button>
      <button type="button" class="tab" data-tab="tab-prov">Provider × reason</button>
      <button type="button" class="tab" data-tab="tab-enroll">Enrollments</button>
    </div>

    <div id="tab-spend" class="tab-panel">
      <div class="kpi-grid" id="kpiSpend"></div>
      <div class="grid2">
        <div class="panel">
          <h2>Bolt vs provider (filtered)</h2>
          <p class="hint">Stacked spend in local currency from order metrics.</p>
          <canvas id="chBoltProv"></canvas>
        </div>
        <div class="panel">
          <h2>By report reason (horizontal)</h2>
          <canvas id="chByReason"></canvas>
        </div>
      </div>
      <div class="panel">
        <h2>Report reason breakdown</h2>
        <p class="hint">Sort columns. Provider % = provider / (bolt + provider). Use lifecycle / LCS filters to narrow churn vs engaged vs new.</p>
        <table class="data" id="tblReason"><thead></thead><tbody></tbody></table>
      </div>
    </div>

    <div id="tab-cohort" class="tab-panel section-hidden">
      <div class="panel">
        <h2>Partner UI audiences (Bolt vs provider)</h2>
        <p class="hint">Same five cohorts as &quot;Create a smart promotion&quot; → Choose an audience (mapped from campaign name + LCS; see subtitle).</p>
        <canvas id="chAudience"></canvas>
      </div>
      <div class="panel">
        <h2>Spend by product audience</h2>
        <table class="data" id="tblAudience"><thead></thead><tbody></tbody></table>
      </div>
      <div class="panel">
        <h2>Lifecycle bucket (Bolt vs provider)</h2>
        <p class="hint">Derived from LCS cohort wording (e.g. churned, engaged). With no filters, matches the server rollup for the file window; otherwise sums the filtered detail rows (top spenders capped).</p>
        <canvas id="chLifecycle"></canvas>
      </div>
      <div class="grid2">
        <div class="panel">
          <h2>By lifecycle bucket</h2>
          <table class="data" id="tblLifecycle"><thead></thead><tbody></tbody></table>
        </div>
        <div class="panel">
          <h2>By enrollment cohort</h2>
          <p class="hint">Enrollment cohort label when present (capped).</p>
          <table class="data" id="tblEnrollCohort"><thead></thead><tbody></tbody></table>
        </div>
      </div>
      <div class="panel">
        <h2>By LCS cohort string (top)</h2>
        <p class="hint">Raw targeting segments from enrollments join (top by spend).</p>
        <table class="data" id="tblLcs"><thead></thead><tbody></tbody></table>
      </div>
    </div>

    <div id="tab-prov" class="tab-panel section-hidden">
      <div class="panel">
        <h2>Top provider × report reason (pre-aggregated)</h2>
          <p class="hint">Use filters above; with filters applied, cohorts are recomputed from the detail slice (LCS / enrollment lists still top-N by spend).</p>
        <table class="data" id="tblProv"><thead></thead><tbody></tbody></table>
      </div>
    </div>

    <div id="tab-enroll" class="tab-panel section-hidden">
      <div class="panel">
        <h2>Smart promo enrollments</h2>
        <p class="hint">From fact_provider_smart_promo_offer_campaign_enrollment.</p>
        <table class="data" id="tblEnroll"><thead></thead><tbody></tbody></table>
      </div>
    </div>
  </div>

  <script type="application/json" id="sp-data-json">{data_json}</script>
  <script>
  const DATA = JSON.parse(document.getElementById("sp-data-json").textContent);

  function fmtMoney(x) {{
    const n = Number(x);
    if (!isFinite(n)) return "—";
    return n.toLocaleString(undefined, {{ maximumFractionDigits: 2 }});
  }}
  function fmtInt(x) {{
    const n = Number(x);
    if (!isFinite(n)) return "—";
    return Math.round(n).toLocaleString();
  }}
  function pct(p, t) {{
    const a = Number(p), b = Number(t);
    if (!isFinite(a) || !isFinite(b) || b === 0) return "—";
    return (100 * a / b).toFixed(1) + "%";
  }}

  function uniq(vals) {{
    const s = new Set();
    vals.forEach(v => {{ if (v != null && String(v).trim() !== "") s.add(String(v)); }});
    return Array.from(s).sort((a,b) => a.localeCompare(b));
  }}

  function fillSelect(id, values, allLabel) {{
    const el = document.getElementById(id);
    const cur = el.value;
    el.innerHTML = '<option value="all">' + allLabel + "</option>" +
      values.map(v => '<option value="' + v.replace(/"/g, "&quot;") + '">' + v + "</option>").join("");
    if ([...el.options].some(o => o.value === cur)) el.value = cur;
  }}

  const rowsReason = DATA.by_report_reason || [];
  const rowsProv = DATA.by_provider_reason || [];
  const rowsEnroll = DATA.enrollments || [];

  function cohortLabel(v) {{
    const s = String(v || "").trim();
    return s === "" ? "(not mapped)" : s;
  }}

  const meta = DATA.meta || {{}};
  function parseISODate(s) {{
    const p = String(s || "").slice(0, 10).split("-");
    if (p.length !== 3) return new Date(NaN);
    return new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2]));
  }}
  function formatISODate(d) {{
    const y = d.getFullYear(), m = String(d.getMonth() + 1).padStart(2, "0"), day = String(d.getDate()).padStart(2, "0");
    return y + "-" + m + "-" + day;
  }}
  function clampOrderDates() {{
    const df = document.getElementById("dateFromIn");
    const dt = document.getElementById("dateToIn");
    const a = parseISODate(df.value);
    const b = parseISODate(dt.value);
    if (isNaN(a) || isNaN(b)) return;
    if (a > b) {{
      df.value = formatISODate(b);
      dt.value = formatISODate(a);
    }}
  }}
  (function initDateBounds() {{
    const s0 = String(meta.start || "").slice(0, 10);
    const s1 = String(meta.end || "").slice(0, 10);
    const df = document.getElementById("dateFromIn");
    const dt = document.getElementById("dateToIn");
    df.min = s0; df.max = s1; dt.min = s0; dt.max = s1;
    df.value = s0; dt.value = s1;
  }})();

  document.querySelectorAll(".preset-btn").forEach(btn => {{
    btn.addEventListener("click", () => {{
      const preset = btn.getAttribute("data-preset");
      const win0 = parseISODate(meta.start);
      const win1 = parseISODate(meta.end);
      const df = document.getElementById("dateFromIn");
      const dt = document.getElementById("dateToIn");
      if (preset === "full") {{
        df.value = formatISODate(win0);
        dt.value = formatISODate(win1);
      }} else {{
        const n = preset === "7" ? 7 : 30;
        let end = win1;
        let start = new Date(end.getFullYear(), end.getMonth(), end.getDate() - (n - 1));
        if (start < win0) start = win0;
        df.value = formatISODate(start);
        dt.value = formatISODate(end);
      }}
      clampOrderDates();
      refreshSpend();
    }});
  }});

  // Searchable combobox factory — hidden input holds the selected value ("all" = no filter).
  // Options: array of objects with value/label/hay (hay = lowercased haystack we match against).
  function makeCombo(opts) {{
    const inp    = document.getElementById(opts.inputId);
    const hidden = document.getElementById(opts.hiddenId);
    const list   = document.getElementById(opts.listId);
    const clr    = document.getElementById(opts.clearId);
    const allLbl = opts.allLabel || "All";
    const max    = opts.maxResults || 200;
    let items    = [];
    let activeIdx = -1;
    const esc = (t) => String(t).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

    function openList(filterText) {{
      const q = String(filterText || "").trim().toLowerCase();
      const terms = q ? q.split(/\s+/) : [];
      const matched = items.filter(it => !terms.length || terms.every(t => it.hay.includes(t)));
      const headRow =
        '<div class="combo-opt" data-value="all" data-label="' + esc(allLbl) + '" data-idx="-1" style="font-weight:700">' +
        esc(allLbl) + "</div>";
      const more = matched.length > max ? '<div class="combo-none">Showing top ' + max + " of " + matched.length + " matches — keep typing to narrow…</div>" : "";
      list.innerHTML = headRow +
        (matched.length
          ? matched.slice(0, max).map((it, i) =>
              '<div class="combo-opt" data-value="' + esc(it.value) + '" data-label="' + esc(it.label) + '" data-idx="' + i + '">' + esc(it.label) + "</div>"
            ).join("")
          : '<div class="combo-none">No matches</div>') + more;
      list.classList.add("open");
      activeIdx = -1;
    }}
    function closeList() {{ list.classList.remove("open"); }}
    function setVal(val, label) {{
      hidden.value = val || "all";
      inp.value    = (val && val !== "all") ? label : "";
      clr.style.display = inp.value ? "block" : "none";
      closeList();
      activeIdx = -1;
      if (typeof opts.onChange === "function") opts.onChange();
    }}
    function moveActive(dir) {{
      const nodes = list.querySelectorAll(".combo-opt");
      if (!nodes.length) return;
      nodes.forEach(n => n.classList.remove("active"));
      activeIdx = Math.max(0, Math.min(nodes.length - 1, activeIdx + dir));
      nodes[activeIdx].classList.add("active");
      nodes[activeIdx].scrollIntoView({{ block: "nearest" }});
    }}
    inp.addEventListener("input", () => {{
      clr.style.display = inp.value ? "block" : "none";
      hidden.value = "all";
      openList(inp.value);
    }});
    inp.addEventListener("focus", () => openList(inp.value));
    inp.addEventListener("keydown", e => {{
      if (e.key === "ArrowDown")      {{ e.preventDefault(); moveActive(1); }}
      else if (e.key === "ArrowUp")   {{ e.preventDefault(); moveActive(-1); }}
      else if (e.key === "Enter")     {{
        e.preventDefault();
        const a = list.querySelector(".combo-opt.active") || list.querySelector(".combo-opt");
        if (a) setVal(a.dataset.value, a.dataset.label);
      }}
      else if (e.key === "Escape")    {{ closeList(); inp.blur(); }}
    }});
    list.addEventListener("mousedown", e => {{
      const opt = e.target.closest(".combo-opt");
      if (opt) {{ e.preventDefault(); setVal(opt.dataset.value, opt.dataset.label); }}
    }});
    clr.addEventListener("click", () => {{
      setVal("all", "");
      inp.focus();
      openList("");
    }});
    document.addEventListener("click", e => {{
      if (!e.target.closest("#" + opts.wrapId)) closeList();
    }});
    return {{
      setItems(newItems) {{ items = newItems; }},
      setValue(val, label) {{ setVal(val, label); }},
      value() {{ return hidden.value; }},
    }};
  }}

  const escCombo = (t) => String(t).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");

  const providerCombo = makeCombo({{
    wrapId: "providerComboWrap", inputId: "providerComboInput",
    hiddenId: "provSel", listId: "providerComboList", clearId: "providerComboClear",
    allLabel: "All providers", onChange: () => refreshSpend(),
  }});
  const brandCombo = makeCombo({{
    wrapId: "brandComboWrap", inputId: "brandComboInput",
    hiddenId: "brandSel", listId: "brandComboList", clearId: "brandComboClear",
    allLabel: "All brands", onChange: () => refreshSpend(),
  }});

  (function populateProviderCombo() {{
    const byPid = new Map();
    rowsProv.forEach(r => {{
      const id = String(r.provider_id != null ? r.provider_id : "");
      if (id && !byPid.has(id)) {{
        byPid.set(id, {{
          name:    String(r.provider_name || ""),
          segment: String(r.segment || ""),
          am:      String(r.am || ""),
        }});
      }}
    }});
    const items = [...byPid.entries()]
      .map(([id, v]) => {{
        const parts = [v.name];
        if (v.segment) parts.push(v.segment);
        const label = parts.join(" · ") + " · " + id;
        const hay = (v.name + " " + v.segment + " " + v.am + " " + id).toLowerCase();
        return {{ value: id, label, hay }};
      }})
      .sort((a, b) => a.label.localeCompare(b.label));
    providerCombo.setItems(items);
  }})();

  (function populateBrandCombo() {{
    const brands = new Set();
    rowsProv.forEach(r => {{
      const b = String(r.brand_name || "").trim();
      if (b) brands.add(b);
    }});
    const items = [...brands]
      .sort((a, b) => a.localeCompare(b))
      .map(b => ({{ value: b, label: b, hay: b.toLowerCase() }}));
    brandCombo.setItems(items);
  }})();

  fillSelect("audSel", uniq(rowsProv.map(r => String(r.audience_cohort || ""))), "All");
  fillSelect("lifeSel", uniq(rowsProv.map(r => String(r.lifecycle_bucket || ""))), "All");
  fillSelect("lcsSel", uniq(rowsProv.map(r => cohortLabel(r.lcs_cohort))), "All");
  fillSelect("enrCohortSel", uniq(rowsProv.map(r => cohortLabel(r.enrollment_cohort))), "All");
  fillSelect("reasonSel", uniq(rowsProv.map(r => r.report_reason)), "All reasons");
  fillSelect("amSel", uniq(rowsProv.map(r => r.am)), "All AMs");
  fillSelect("segSel", uniq(rowsProv.map(r => r.segment)), "All segments");
  fillSelect("objSel", uniq(rowsProv.map(r => r.spend_objective)), "All objectives");

  function filterProvRows() {{
    const d0 = document.getElementById("dateFromIn").value;
    const d1 = document.getElementById("dateToIn").value;
    const pv = document.getElementById("provSel").value;
    const br = document.getElementById("brandSel").value;
    const aud = document.getElementById("audSel").value;
    const life = document.getElementById("lifeSel").value;
    const lcs = document.getElementById("lcsSel").value;
    const enr = document.getElementById("enrCohortSel").value;
    const rr = document.getElementById("reasonSel").value;
    const am = document.getElementById("amSel").value;
    const seg = document.getElementById("segSel").value;
    const obj = document.getElementById("objSel").value;
    const rawQ = document.getElementById("searchIn").value.trim().toLowerCase();
    const qTerms = rawQ ? rawQ.split(/\s+/).filter(Boolean) : [];
    return rowsProv.filter(r => {{
      const od = String(r.order_date || "").slice(0, 10);
      if (d0 && (!od || od < d0)) return false;
      if (d1 && (!od || od > d1)) return false;
      if (pv !== "all" && String(r.provider_id) !== pv) return false;
      if (br !== "all" && cohortLabel(r.brand_name) !== br) return false;
      if (aud !== "all" && String(r.audience_cohort || "") !== aud) return false;
      if (life !== "all" && String(r.lifecycle_bucket || "") !== life) return false;
      if (lcs !== "all" && cohortLabel(r.lcs_cohort) !== lcs) return false;
      if (enr !== "all" && cohortLabel(r.enrollment_cohort) !== enr) return false;
      if (rr !== "all" && String(r.report_reason) !== rr) return false;
      if (am !== "all" && String(r.am) !== am) return false;
      if (seg !== "all" && String(r.segment) !== seg) return false;
      if (obj !== "all" && String(r.spend_objective) !== obj) return false;
      if (qTerms.length > 0) {{
        const blob = [r.provider_name, r.brand_name, r.provider_id, r.report_reason, r.am,
          r.segment, r.lcs_cohort, r.enrollment_cohort, r.lifecycle_bucket, r.audience_cohort,
          r.spend_objective, r.target, r.treatment_type]
          .map(x => String(x || "").toLowerCase()).join(" ");
        if (!qTerms.every(t => blob.includes(t))) return false;
      }}
      return true;
    }});
  }}

  function aggregateFromProv(filtered) {{
    const byR = {{}};
    filtered.forEach(r => {{
      const k = String(r.report_reason || "");
      if (!byR[k]) byR[k] = {{ bolt: 0, prov: 0, orders: 0, providers: new Set() }};
      byR[k].bolt += Number(r.bolt_spend_local) || 0;
      byR[k].prov += Number(r.provider_spend_local) || 0;
      byR[k].orders += Number(r.orders) || 0;
      byR[k].providers.add(String(r.provider_id));
    }});
    return Object.entries(byR).map(([report_reason, v]) => ({{
      report_reason,
      bolt_spend_local: v.bolt,
      provider_spend_local: v.prov,
      total_spend_local: v.bolt + v.prov,
      orders: v.orders,
      providers: v.providers.size
    }})).sort((a,b) => b.total_spend_local - a.total_spend_local);
  }}

  /** Group filtered detail rows by one dimension (same money semantics as report-reason rollup). */
  function aggregateFromProvByField(filtered, field, keyFn) {{
    const byKey = {{}};
    filtered.forEach(r => {{
      const raw = r[field];
      const k = keyFn ? keyFn(raw) : (String(raw || "").trim() || "(not mapped)");
      if (!byKey[k]) byKey[k] = {{ bolt: 0, prov: 0, orders: 0, providers: new Set() }};
      byKey[k].bolt += Number(r.bolt_spend_local) || 0;
      byKey[k].prov += Number(r.provider_spend_local) || 0;
      byKey[k].orders += Number(r.orders) || 0;
      byKey[k].providers.add(String(r.provider_id));
    }});
    return Object.entries(byKey).map(([k, v]) => ({{
      [field]: k,
      bolt_spend_local: v.bolt,
      provider_spend_local: v.prov,
      total_spend_local: v.bolt + v.prov,
      orders: v.orders,
      providers: v.providers.size
    }})).sort((a, b) => (Number(b.total_spend_local) || 0) - (Number(a.total_spend_local) || 0));
  }}

  function hlText(raw, terms) {{
    if (!terms || terms.length === 0) return escCell(raw);
    let s = escCell(raw);
    terms.forEach(t => {{
      if (!t) return;
      const re = new RegExp("(" + t.replace(/[.*+?^${{}}()|[\\]\\\\]/g, "\\\\$&") + ")", "gi");
      s = s.replace(re, "<mark class='hl'>$1</mark>");
    }});
    return s;
  }}

  function anyDimensionFilter() {{
    const q = document.getElementById("searchIn").value.trim();
    const ms = String(meta.start || "").slice(0, 10);
    const me = String(meta.end || "").slice(0, 10);
    if (document.getElementById("dateFromIn").value !== ms
      || document.getElementById("dateToIn").value !== me) return true;
    if (document.getElementById("provSel").value !== "all") return true;
    if (document.getElementById("brandSel").value !== "all") return true;
    return document.getElementById("audSel").value !== "all"
      || document.getElementById("lifeSel").value !== "all"
      || document.getElementById("lcsSel").value !== "all"
      || document.getElementById("enrCohortSel").value !== "all"
      || document.getElementById("reasonSel").value !== "all"
      || document.getElementById("amSel").value !== "all"
      || document.getElementById("segSel").value !== "all"
      || document.getElementById("objSel").value !== "all"
      || q.length > 0;
  }}

  const COHORT_TOP_ENROLL = 120;
  const COHORT_TOP_LCS = 100;

  /** Pre-aggregated server rollups only when no slice filters; else recompute from filtered detail. */
  function cohortSlicesForCharts() {{
    if (!anyDimensionFilter()) {{
      return {{
        aud: DATA.by_audience_cohort || [],
        life: DATA.by_lifecycle_bucket || [],
        enroll: DATA.by_enrollment_cohort || [],
        lcs: DATA.by_lcs_cohort || [],
      }};
    }}
    const filtered = filterProvRows();
    return {{
      aud: aggregateFromProvByField(filtered, "audience_cohort", null),
      life: aggregateFromProvByField(filtered, "lifecycle_bucket", null),
      enroll: aggregateFromProvByField(filtered, "enrollment_cohort", cohortLabel).slice(0, COHORT_TOP_ENROLL),
      lcs: aggregateFromProvByField(filtered, "lcs_cohort", cohortLabel).slice(0, COHORT_TOP_LCS),
    }};
  }}

  function reasonAggForCharts() {{
    if (!anyDimensionFilter()) return (DATA.by_report_reason || []).map(r => ({{
      report_reason: r.report_reason,
      bolt_spend_local: Number(r.bolt_spend_local) || 0,
      provider_spend_local: Number(r.provider_spend_local) || 0,
      total_spend_local: Number(r.total_spend_local) != null
        ? Number(r.total_spend_local)
        : (Number(r.bolt_spend_local)||0) + (Number(r.provider_spend_local)||0),
      orders: Number(r.orders) || 0,
      providers: Number(r.providers) || 0
    }}));
    return aggregateFromProv(filterProvRows());
  }}

  function renderKpis(agg) {{
    let bolt = 0, prov = 0, ord = 0;
    agg.forEach(r => {{
      bolt += Number(r.bolt_spend_local) || 0;
      prov += Number(r.provider_spend_local) || 0;
      ord += Number(r.orders) || 0;
    }});
    const tot = bolt + prov;
    const el = document.getElementById("kpiSpend");
    el.innerHTML = [
      ["Orders (sum)", fmtInt(ord)],
      ["Bolt spend", fmtMoney(bolt)],
      ["Provider spend", fmtMoney(prov)],
      ["Total spend", fmtMoney(tot)],
      ["Provider % of spend", pct(prov, tot)]
    ].map(([h,v]) => '<div class="kpi"><h3>' + h + '</h3><div class="val">' + v + "</div></div>").join("");
  }}

  let chBoltProv = null;
  let chByReason = null;

  function renderCharts(agg) {{
    const labels = agg.map(r => r.report_reason.length > 48 ? r.report_reason.slice(0,46) + "…" : r.report_reason);
    const bolt = agg.map(r => Number(r.bolt_spend_local) || 0);
    const prov = agg.map(r => Number(r.provider_spend_local) || 0);

    const ctx1 = document.getElementById("chBoltProv");
    if (chBoltProv) chBoltProv.destroy();
    chBoltProv = new Chart(ctx1, {{
      type: "bar",
      data: {{
        labels,
        datasets: [
          {{ label: "Bolt", data: bolt, backgroundColor: "rgba(21,101,192,0.75)", stack: "s" }},
          {{ label: "Provider", data: prov, backgroundColor: "rgba(239,108,0,0.8)", stack: "s" }}
        ]
      }},
      options: {{
        responsive: true,
        plugins: {{ legend: {{ position: "bottom" }} }},
        scales: {{
          x: {{ stacked: true, ticks: {{ maxRotation: 60, minRotation: 25, autoSkip: true, maxTicksLimit: 14 }} }},
          y: {{ stacked: true, beginAtZero: true }}
        }}
      }}
    }});

    const ctx2 = document.getElementById("chByReason");
    if (chByReason) chByReason.destroy();
    const tot = agg.map(r => (Number(r.bolt_spend_local)||0) + (Number(r.provider_spend_local)||0));
    chByReason = new Chart(ctx2, {{
      type: "bar",
      data: {{
        labels,
        datasets: [
          {{ label: "Bolt", data: bolt.map((b,i) => tot[i] ? b/tot[i] : 0), backgroundColor: "rgba(21,101,192,0.85)", stack: "p" }},
          {{ label: "Provider", data: prov.map((p,i) => tot[i] ? p/tot[i] : 0), backgroundColor: "rgba(239,108,0,0.85)", stack: "p" }}
        ]
      }},
      options: {{
        indexAxis: "y",
        responsive: true,
        plugins: {{
          legend: {{ position: "bottom" }},
          tooltip: {{
            callbacks: {{
              label: function(c) {{
                const i = c.dataIndex;
                const t = tot[i];
                const side = c.dataset.label === "Bolt" ? bolt[i] : prov[i];
                return c.dataset.label + ": " + fmtMoney(side) + " (" + (t ? (100*side/t).toFixed(1) : "0") + "%)";
              }}
            }}
          }}
        }},
        scales: {{
          x: {{ stacked: true, max: 1, ticks: {{ callback: v => (v*100).toFixed(0) + "%" }} }},
          y: {{ stacked: true }}
        }}
      }}
    }});
  }}

  let sortReason = {{ key: "total_spend_local", dir: "desc" }};
  function renderReasonTable(agg) {{
    const keys = ["report_reason","bolt_spend_local","provider_spend_local","total_spend_local","provider_pct","orders","providers"];
    const head = "<tr>"
      + ["Report reason","Bolt","Provider","Total","Prov %","Orders","Providers"]
          .map((h,i) => '<th class="sortable" data-k="' + keys[i] + '">' + h + "</th>").join("")
      + "</tr>";
    const sorted = [...agg].sort((a,b) => {{
      const ka = sortReason.key, d = sortReason.dir === "asc" ? 1 : -1;
      let va = a[ka], vb = b[ka];
      if (ka === "provider_pct") {{
        va = (Number(a.provider_spend_local)||0) / ((Number(a.bolt_spend_local)||0)+(Number(a.provider_spend_local)||0) || 1);
        vb = (Number(b.provider_spend_local)||0) / ((Number(b.bolt_spend_local)||0)+(Number(b.provider_spend_local)||0) || 1);
      }}
      if (typeof va === "string") return d * String(va).localeCompare(String(vb));
      return d * ((Number(va)||0) - (Number(vb)||0));
    }});
    const body = sorted.map(r => {{
      const t = (Number(r.bolt_spend_local)||0) + (Number(r.provider_spend_local)||0);
      const pp = t ? (100*(Number(r.provider_spend_local)||0)/t).toFixed(1) + "%" : "—";
      return "<tr><td>" + (r.report_reason || "").replace(/</g,"&lt;") + "</td>"
        + "<td>" + fmtMoney(r.bolt_spend_local) + "</td>"
        + "<td>" + fmtMoney(r.provider_spend_local) + "</td>"
        + "<td>" + fmtMoney(r.total_spend_local != null ? r.total_spend_local : t) + "</td>"
        + "<td>" + pp + "</td>"
        + "<td>" + fmtInt(r.orders) + "</td>"
        + "<td>" + fmtInt(r.providers) + "</td></tr>";
    }}).join("");
    const tbl = document.getElementById("tblReason");
    tbl.querySelector("thead").innerHTML = head;
    tbl.querySelector("tbody").innerHTML = body || "<tr><td colspan='7'>No rows</td></tr>";
    tbl.querySelectorAll("th.sortable").forEach(th => {{
      th.onclick = () => {{
        const k = th.getAttribute("data-k");
        if (sortReason.key === k) sortReason.dir = sortReason.dir === "desc" ? "asc" : "desc";
        else {{ sortReason.key = k; sortReason.dir = "desc"; }}
        refreshSpend();
      }};
    }});
  }}

  function escCell(s) {{
    return String(s || "").replace(/</g, "&lt;");
  }}

  function renderProvTable(rows) {{
    const rawQ = document.getElementById("searchIn").value.trim().toLowerCase();
    const terms = rawQ ? rawQ.split(/\s+/).filter(Boolean) : [];
    const head = "<tr><th>Order date</th><th>Provider</th><th>ID</th><th>Brand</th><th>AM</th><th>Segment</th><th>Product audience</th><th>Lifecycle</th><th>LCS cohort</th>"
      + "<th>Enr. cohort</th><th>Report reason</th><th>Objective</th>"
      + "<th>Bolt</th><th>Provider</th><th>Total</th><th>Orders</th></tr>";
    const lcs72 = s => {{ const t = String(s||""); return t.length > 72 ? t.slice(0,72) + "…" : t; }};
    const ec48 = s => {{ const t = String(s||""); return t.length > 48 ? t.slice(0,48) + "…" : t; }};
    const body = rows.slice(0, 500).map(r => "<tr>"
      + "<td>" + escCell(String(r.order_date || "").slice(0, 10)) + "</td>"
      + "<td>" + hlText(r.provider_name, terms) + "</td>"
      + "<td>" + hlText(String(r.provider_id||""), terms) + "</td>"
      + "<td>" + hlText(r.brand_name, terms) + "</td>"
      + "<td>" + hlText(r.am, terms) + "</td>"
      + "<td>" + hlText(r.segment, terms) + "</td>"
      + "<td>" + hlText(r.audience_cohort, terms) + "</td>"
      + "<td>" + hlText(r.lifecycle_bucket, terms) + "</td>"
      + "<td>" + hlText(lcs72(r.lcs_cohort), terms) + "</td>"
      + "<td>" + hlText(ec48(r.enrollment_cohort), terms) + "</td>"
      + "<td>" + hlText(r.report_reason, terms) + "</td>"
      + "<td>" + hlText(r.spend_objective, terms) + "</td>"
      + "<td>" + fmtMoney(r.bolt_spend_local) + "</td>"
      + "<td>" + fmtMoney(r.provider_spend_local) + "</td>"
      + "<td>" + fmtMoney(r.total_spend_local) + "</td>"
      + "<td>" + fmtInt(r.orders) + "</td>"
      + "</tr>").join("");
    const tbl = document.getElementById("tblProv");
    tbl.querySelector("thead").innerHTML = head;
    tbl.querySelector("tbody").innerHTML = body || "<tr><td colspan='16'>No rows</td></tr>";
  }}

  let chLifecycle = null;
  let chAudience = null;
  function renderCohortStatic() {{
    const sl = cohortSlicesForCharts();
    const aud = sl.aud;
    const labelsA = aud.map(r => String(r.audience_cohort || ""));
    const boltA = aud.map(r => Number(r.bolt_spend_local) || 0);
    const provA = aud.map(r => Number(r.provider_spend_local) || 0);
    const ctxA = document.getElementById("chAudience");
    if (chAudience) chAudience.destroy();
    chAudience = new Chart(ctxA, {{
      type: "bar",
      data: {{
        labels: labelsA,
        datasets: [
          {{ label: "Bolt", data: boltA, backgroundColor: "rgba(21,101,192,0.75)", stack: "aud" }},
          {{ label: "Provider", data: provA, backgroundColor: "rgba(239,108,0,0.8)", stack: "aud" }}
        ]
      }},
      options: {{
        indexAxis: "y",
        responsive: true,
        plugins: {{ legend: {{ position: "bottom" }} }},
        scales: {{
          x: {{ stacked: true, beginAtZero: true }},
          y: {{ stacked: true }}
        }}
      }}
    }});

    const headA = "<tr><th>Product audience</th><th>Bolt</th><th>Provider</th><th>Total</th><th>Prov %</th><th>Orders</th><th>Providers</th></tr>";
    document.getElementById("tblAudience").querySelector("thead").innerHTML = headA;
    document.getElementById("tblAudience").querySelector("tbody").innerHTML =
      (aud.map(r => {{
        const t = (Number(r.bolt_spend_local)||0) + (Number(r.provider_spend_local)||0);
        const pp = t ? (100*(Number(r.provider_spend_local)||0)/t).toFixed(1) + "%" : "—";
        return "<tr><td>" + escCell(r.audience_cohort) + "</td>"
          + "<td>" + fmtMoney(r.bolt_spend_local) + "</td>"
          + "<td>" + fmtMoney(r.provider_spend_local) + "</td>"
          + "<td>" + fmtMoney(r.total_spend_local != null ? r.total_spend_local : t) + "</td>"
          + "<td>" + pp + "</td>"
          + "<td>" + fmtInt(r.orders) + "</td>"
          + "<td>" + fmtInt(r.providers) + "</td></tr>";
      }}).join("")) || "<tr><td colspan='7'>No rows</td></tr>";

    const life = sl.life;
    const labels = life.map(r => String(r.lifecycle_bucket || ""));
    const bolt = life.map(r => Number(r.bolt_spend_local) || 0);
    const prov = life.map(r => Number(r.provider_spend_local) || 0);
    const ctx = document.getElementById("chLifecycle");
    if (chLifecycle) chLifecycle.destroy();
    chLifecycle = new Chart(ctx, {{
      type: "bar",
      data: {{
        labels,
        datasets: [
          {{ label: "Bolt", data: bolt, backgroundColor: "rgba(21,101,192,0.75)", stack: "lc" }},
          {{ label: "Provider", data: prov, backgroundColor: "rgba(239,108,0,0.8)", stack: "lc" }}
        ]
      }},
      options: {{
        indexAxis: "y",
        responsive: true,
        plugins: {{ legend: {{ position: "bottom" }} }},
        scales: {{
          x: {{ stacked: true, beginAtZero: true }},
          y: {{ stacked: true }}
        }}
      }}
    }});

    function spendTableBody(rows, nameField) {{
      return (rows || []).map(r => {{
        const name = String(r[nameField] || "");
        const t = (Number(r.bolt_spend_local)||0) + (Number(r.provider_spend_local)||0);
        const pp = t ? (100*(Number(r.provider_spend_local)||0)/t).toFixed(1) + "%" : "—";
        return "<tr><td>" + escCell(name) + "</td>"
          + "<td>" + fmtMoney(r.bolt_spend_local) + "</td>"
          + "<td>" + fmtMoney(r.provider_spend_local) + "</td>"
          + "<td>" + fmtMoney(r.total_spend_local != null ? r.total_spend_local : t) + "</td>"
          + "<td>" + pp + "</td>"
          + "<td>" + fmtInt(r.orders) + "</td>"
          + "<td>" + fmtInt(r.providers) + "</td></tr>";
      }}).join("");
    }}
    const head = "<tr><th>Cohort</th><th>Bolt</th><th>Provider</th><th>Total</th><th>Prov %</th><th>Orders</th><th>Providers</th></tr>";
    document.getElementById("tblLifecycle").querySelector("thead").innerHTML = head;
    document.getElementById("tblLifecycle").querySelector("tbody").innerHTML =
      spendTableBody(life, "lifecycle_bucket") || "<tr><td colspan='7'>No rows</td></tr>";
    document.getElementById("tblEnrollCohort").querySelector("thead").innerHTML = head.replace("Cohort", "Enrollment cohort");
    document.getElementById("tblEnrollCohort").querySelector("tbody").innerHTML =
      spendTableBody(sl.enroll, "enrollment_cohort") || "<tr><td colspan='7'>No rows</td></tr>";
    document.getElementById("tblLcs").querySelector("thead").innerHTML = head.replace("Cohort", "LCS cohort");
    document.getElementById("tblLcs").querySelector("tbody").innerHTML =
      spendTableBody(sl.lcs, "lcs_cohort") || "<tr><td colspan='7'>No rows</td></tr>";
  }}

  function filterEnrollRows() {{
    const d0 = document.getElementById("dateFromIn").value;
    const d1 = document.getElementById("dateToIn").value;
    const pv = document.getElementById("provSel").value;
    const br = document.getElementById("brandSel").value;
    return rowsEnroll.filter(r => {{
      const sd = String(r.enrollment_start_date || "").slice(0, 10);
      if (d0 && (!sd || sd < d0)) return false;
      if (d1 && (!sd || sd > d1)) return false;
      if (pv !== "all" && String(r.provider_id) !== pv) return false;
      if (br !== "all" && cohortLabel(r.brand_name) !== br) return false;
      return true;
    }});
  }}

  function renderEnroll() {{
    const rows = filterEnrollRows();
    const head = "<tr><th>Start</th><th>Provider</th><th>Brand</th><th>AM</th><th>State</th><th>Offer type</th><th>SP type</th>"
      + "<th>Mode</th><th>Campaign obj</th><th>Campaign id</th></tr>";
    const body = rows.map(r => "<tr>"
      + "<td>" + String(r.enrollment_start_date||"") + "</td>"
      + "<td>" + escCell(r.provider_name) + "</td>"
      + "<td>" + escCell(r.brand_name) + "</td>"
      + "<td>" + escCell(r.am) + "</td>"
      + "<td>" + String(r.enrollment_state||"") + "</td>"
      + "<td>" + String(r.smart_promo_offer_type||"") + "</td>"
      + "<td>" + String(r.smart_promo_type||"") + "</td>"
      + "<td>" + String(r.smart_promo_offer_mode||"") + "</td>"
      + "<td>" + String(r.campaign_spend_objective||"") + "</td>"
      + "<td>" + String(r.campaign_id||"") + "</td>"
      + "</tr>").join("");
    const tbl = document.getElementById("tblEnroll");
    tbl.querySelector("thead").innerHTML = head;
    tbl.querySelector("tbody").innerHTML = body || "<tr><td colspan='10'>No rows</td></tr>";
  }}

  function refreshSpend() {{
    clampOrderDates();
    const filtered = filterProvRows();
    const agg = reasonAggForCharts();
    agg.forEach(r => {{
      r.total_spend_local = (Number(r.bolt_spend_local)||0) + (Number(r.provider_spend_local)||0);
    }});
    renderKpis(agg);
    renderCharts(agg);
    renderReasonTable(agg);
    renderProvTable(filtered);
    renderEnroll();
    renderCohortStatic();
  }}

  document.querySelectorAll("#mainTabs .tab").forEach(btn => {{
    btn.addEventListener("click", () => {{
      document.querySelectorAll("#mainTabs .tab").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      document.querySelectorAll(".tab-panel").forEach(p => p.classList.add("section-hidden"));
      document.getElementById(btn.getAttribute("data-tab")).classList.remove("section-hidden");
    }});
  }});

  // provSel/brandSel are hidden inputs driven by their comboboxes (which call refreshSpend themselves).
  ["dateFromIn","dateToIn","audSel","lifeSel","lcsSel","enrCohortSel","reasonSel","amSel","segSel","objSel"].forEach(id => {{
    const el = document.getElementById(id);
    el.addEventListener("change", refreshSpend);
    if (id === "dateFromIn" || id === "dateToIn") el.addEventListener("input", refreshSpend);
  }});
  (function initSearch() {{
    const inp = document.getElementById("searchIn");
    const clr = document.getElementById("searchClear");
    function updateClear() {{
      clr.style.display = inp.value.trim() ? "block" : "none";
    }}
    inp.addEventListener("input", () => {{ updateClear(); refreshSpend(); }});
    clr.addEventListener("click", () => {{
      inp.value = "";
      updateClear();
      inp.focus();
      refreshSpend();
    }});
    updateClear();
  }})();

  document.getElementById("loadReportBtn").addEventListener("click", refreshSpend);

  (function initViewToggle() {{
    const vtP = document.getElementById("vtProvider");
    const vtB = document.getElementById("vtBrand");
    const gP  = document.getElementById("pfProviderGroup");
    const gB  = document.getElementById("pfBrandGroup");
    function setMode(mode) {{
      const isProv = mode === "provider";
      vtP.classList.toggle("active", isProv);
      vtB.classList.toggle("active", !isProv);
      vtP.setAttribute("aria-selected", isProv ? "true" : "false");
      vtB.setAttribute("aria-selected", isProv ? "false" : "true");
      gP.style.display = isProv ? "" : "none";
      gB.style.display = isProv ? "none" : "";
      // Reset the inactive dimension so filters don't stack unexpectedly.
      if (isProv) {{
        document.getElementById("brandSel").value = "all";
        document.getElementById("brandComboInput").value = "";
        document.getElementById("brandComboClear").style.display = "none";
      }} else {{
        document.getElementById("provSel").value = "all";
        document.getElementById("providerComboInput").value = "";
        document.getElementById("providerComboClear").style.display = "none";
      }}
      refreshSpend();
    }}
    vtP.addEventListener("click", () => setMode("provider"));
    vtB.addEventListener("click", () => setMode("brand"));
  }})();

  refreshSpend();
  </script>
</body>
</html>
"""
