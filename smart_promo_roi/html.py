"""Self-contained HTML for the Smart Promotions ROI dashboard (black default, white toggle)."""
from __future__ import annotations

import html as _html
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


def _html_template(
    *,
    country: str,
    subtitle: str,
    data_json: str,
    build_banner: str,
    dashboard_version: str,
) -> str:
    esc = _html.escape
    title = f"Smart Promotions ROI — {country}"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)}</title>
  <meta name="dashboard-version" content="{esc(dashboard_version)}">
  {_chart_script_tag()}
  <style>
    /* ── Dark theme (default: black) ── */
    :root {{
      --bg:          #000000;
      --card:        #0d0d0d;
      --card-2:      #141414;
      --border:      #222222;
      --border-dim:  #1a1a1a;
      --green:       #34d88c;
      --green-dark:  #25a86a;
      --green-dim:   #0d2218;
      --green-glow:  rgba(52,216,140,.18);
      --text:        #e8e8e8;
      --text-muted:  #888888;
      --text-dim:    #444444;
      --blue:        #4a9eff;
      --blue-dim:    #0d1e30;
      --orange:      #f5a623;
      --purple:      #b39ddb;
      --yellow:      #ffd54f;
      --red:         #ef5350;
      --badge-bg:    #34d88c;
      --badge-text:  #000000;
      --shadow:      rgba(0,0,0,.6);
    }}

    /* ── Light theme ── */
    html.light {{
      --bg:          #ffffff;
      --card:        #f5f5f5;
      --card-2:      #eeeeee;
      --border:      #d9d9d9;
      --border-dim:  #e8e8e8;
      --green:       #1e8a50;
      --green-dark:  #166b3e;
      --green-dim:   #e6f5ed;
      --green-glow:  rgba(30,138,80,.1);
      --text:        #111111;
      --text-muted:  #555555;
      --text-dim:    #999999;
      --blue:        #1565c0;
      --blue-dim:    #e3eeff;
      --orange:      #e65c00;
      --purple:      #6a3fbf;
      --yellow:      #b8860b;
      --red:         #c62828;
      --badge-bg:    #1e8a50;
      --badge-text:  #ffffff;
      --shadow:      rgba(0,0,0,.12);
    }}
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html {{ scroll-behavior: smooth; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
    }}

    /* ── Header ── */
    .header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 1.1rem 1.8rem;
      background: var(--card);
      border-bottom: 1px solid var(--border);
    }}
    .header-left h1 {{
      font-size: 1.25rem;
      font-weight: 700;
      color: var(--text);
    }}
    .header-left .header-sub {{
      font-size: .78rem;
      color: var(--text-muted);
      margin-top: .2rem;
    }}
    .badge {{
      background: var(--badge-bg);
      color: var(--badge-text);
      font-size: .72rem;
      font-weight: 800;
      letter-spacing: .08em;
      padding: .35rem .75rem;
      border-radius: 6px;
      white-space: nowrap;
    }}

    /* ── Build banner ── */
    .build-banner {{
      font-size: .75rem;
      background: #1a2d1f;
      border-bottom: 1px solid var(--border-dim);
      color: var(--text-muted);
      padding: .38rem 1.8rem;
      text-align: center;
    }}

    /* ── View toggle (Provider / Brand) ── */
    .view-toggle {{
      display: inline-flex;
      background: var(--card-2);
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
    }}
    .vt-btn {{
      background: transparent;
      border: none;
      color: var(--text-muted);
      font-size: .78rem;
      font-weight: 700;
      letter-spacing: .04em;
      padding: .4rem .9rem;
      cursor: pointer;
      transition: background .15s, color .15s;
      white-space: nowrap;
    }}
    .vt-btn.active {{
      background: var(--green);
      color: var(--badge-text);
    }}
    .vt-btn:not(.active):hover {{
      background: var(--border);
      color: var(--text);
    }}

    /* ── Filter bar ── */
    .filter-bar {{
      background: var(--card);
      border-bottom: 1px solid var(--border);
      padding: .85rem 1.8rem;
      display: flex;
      align-items: center;
      gap: .75rem;
      flex-wrap: wrap;
    }}
    .filter-bar label {{
      font-size: .75rem;
      color: var(--text-muted);
      font-weight: 600;
      letter-spacing: .03em;
      text-transform: uppercase;
    }}
    .filter-bar select,
    .filter-bar input[type="date"] {{
      background: var(--card-2);
      border: 1px solid var(--border);
      color: var(--text);
      border-radius: 7px;
      padding: .45rem .75rem;
      font-size: .84rem;
      min-width: 220px;
      cursor: pointer;
      outline: none;
      appearance: none;
      -webkit-appearance: none;
    }}
    .filter-bar input[type="date"] {{
      min-width: 10rem;
    }}
    .filter-bar select:focus,
    .filter-bar input[type="date"]:focus {{
      border-color: var(--green);
    }}
    .filter-sep {{
      color: var(--border);
      font-size: 1.2rem;
    }}
    .filter-entity-wrap {{
      display: inline-flex;
      align-items: center;
      gap: .5rem;
      flex-wrap: wrap;
    }}
    .filter-entity-wrap label {{
      margin: 0;
    }}
    /* ── Provider combobox ── */
    .combo-wrap {{
      position: relative;
      display: inline-block;
    }}
    .combo-input {{
      background: var(--card-2);
      border: 1px solid var(--border);
      color: var(--text);
      border-radius: 7px;
      padding: .45rem 2rem .45rem .75rem;
      font-size: .84rem;
      min-width: 260px;
      outline: none;
      box-sizing: border-box;
    }}
    .combo-input:focus {{ border-color: var(--green); }}
    .combo-clear {{
      position: absolute; right: .45rem; top: 50%; transform: translateY(-50%);
      background: none; border: none; color: var(--text-muted); font-size: 1rem;
      cursor: pointer; padding: 0; line-height: 1; display: none;
    }}
    .combo-clear:hover {{ color: var(--text); }}
    .combo-list {{
      position: absolute; top: calc(100% + 4px); left: 0; min-width: 100%;
      max-height: 280px; overflow-y: auto;
      background: var(--card); border: 1px solid var(--border);
      border-radius: 8px; box-shadow: 0 6px 20px rgba(0,0,0,.35);
      z-index: 200; display: none;
    }}
    .combo-list.open {{ display: block; }}
    .combo-opt {{
      padding: .45rem .75rem; font-size: .82rem; cursor: pointer;
      color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }}
    .combo-opt:hover, .combo-opt.active {{ background: var(--green); color: #fff; }}
    .combo-none {{ padding: .45rem .75rem; font-size: .82rem; color: var(--text-muted); }}
    .btn-load {{
      background: var(--green);
      color: var(--badge-text);
      border: none;
      border-radius: 8px;
      padding: .5rem 1.4rem;
      font-size: .88rem;
      font-weight: 700;
      cursor: pointer;
      transition: background .15s;
      white-space: nowrap;
    }}
    .btn-load:hover {{ background: var(--green-dark); }}
    .btn-load:active {{ transform: scale(.97); }}

    /* ── Main wrap ── */
    .wrap {{ max-width: 1240px; margin: 0 auto; padding: 1.5rem 1.5rem 3rem; }}

    /* ── Provider card ── */
    .provider-card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1rem 1.4rem;
      margin-bottom: 1.25rem;
    }}
    .provider-card h2 {{
      font-size: 1.35rem;
      font-weight: 700;
      color: var(--text);
    }}
    .provider-card .provider-meta {{
      font-size: .8rem;
      color: var(--text-muted);
      margin-top: .3rem;
    }}

    /* ── Hero ROAS ── */
    .hero-roas {{
      background: var(--card);
      border: 1.5px solid var(--green-dark);
      border-radius: 14px;
      text-align: center;
      padding: 2rem 1.5rem 1.75rem;
      margin-bottom: 1.25rem;
      box-shadow: 0 0 32px var(--green-glow);
    }}
    .hero-roas .label {{
      font-size: .72rem;
      font-weight: 700;
      letter-spacing: .12em;
      text-transform: uppercase;
      color: var(--text-muted);
      margin-bottom: .65rem;
    }}
    .hero-roas .roas-number {{
      font-size: 4.5rem;
      font-weight: 800;
      color: var(--green);
      line-height: 1;
    }}
    .hero-roas .roas-sub {{
      font-size: .92rem;
      color: var(--text-muted);
      margin-top: .6rem;
    }}

    /* ── KPI cards ── */
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: .9rem;
      margin-bottom: 1.25rem;
    }}
    @media (max-width: 900px) {{ .kpi-grid {{ grid-template-columns: repeat(2, 1fr); }} }}
    @media (max-width: 500px) {{ .kpi-grid {{ grid-template-columns: 1fr; }} }}
    .kpi-card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1rem 1.1rem 1rem;
    }}
    .kpi-card .kpi-label {{
      font-size: .67rem;
      font-weight: 700;
      letter-spacing: .09em;
      text-transform: uppercase;
      color: var(--text-muted);
      margin-bottom: .55rem;
    }}
    .kpi-card .kpi-value {{
      font-size: 2rem;
      font-weight: 700;
      line-height: 1;
    }}
    .kpi-card .kpi-sub {{
      font-size: .73rem;
      color: var(--text-muted);
      margin-top: .45rem;
      line-height: 1.4;
    }}
    .kv-green  {{ color: var(--green); }}
    .kv-orange {{ color: var(--orange); }}
    .kv-purple {{ color: var(--purple); }}
    .kv-white  {{ color: var(--text); }}

    /* ── Charts ── */
    .charts-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 1rem;
      margin-bottom: 1.25rem;
    }}
    @media (max-width: 860px) {{ .charts-grid {{ grid-template-columns: 1fr; }} }}
    .chart-card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1.1rem 1.2rem 1rem;
    }}
    .chart-card h3 {{
      font-size: .66rem;
      font-weight: 700;
      letter-spacing: .09em;
      text-transform: uppercase;
      color: var(--text-muted);
      margin-bottom: 1rem;
    }}
    canvas {{ max-height: 280px; }}

    /* ── Promo type table ── */
    .table-card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1.1rem 1.2rem;
      margin-bottom: 1.25rem;
      overflow-x: auto;
    }}
    .table-card h3 {{
      font-size: .66rem;
      font-weight: 700;
      letter-spacing: .09em;
      text-transform: uppercase;
      color: var(--text-muted);
      margin-bottom: .9rem;
    }}
    table.promo-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: .82rem;
    }}
    table.promo-table th {{
      text-align: left;
      font-size: .67rem;
      font-weight: 700;
      letter-spacing: .06em;
      text-transform: uppercase;
      color: var(--text-dim);
      padding: .45rem .75rem;
      border-bottom: 1px solid var(--border);
      white-space: nowrap;
    }}
    table.promo-table th:not(:first-child) {{ text-align: right; }}
    table.promo-table td {{
      padding: .7rem .75rem;
      border-bottom: 1px solid var(--border-dim);
      text-align: right;
      color: var(--text);
    }}
    table.promo-table td:first-child {{ text-align: left; }}
    table.promo-table tbody tr:last-child td {{ border-bottom: none; }}
    .promo-badge {{
      display: inline-block;
      background: var(--green-dim);
      color: var(--green);
      border: 1px solid var(--green-dark);
      border-radius: 5px;
      padding: .22rem .65rem;
      font-size: .75rem;
      font-weight: 600;
    }}

    /* ── Summary & Recommendation ── */
    .summary-box {{
      background: var(--green-dim);
      border-left: 3px solid var(--green);
      border-radius: 0 10px 10px 0;
      padding: 1rem 1.3rem;
      margin-bottom: .9rem;
      font-size: .88rem;
      line-height: 1.65;
      color: var(--text);
    }}
    .recommendation-box {{
      background: var(--blue-dim);
      border-left: 3px solid var(--blue);
      border-radius: 0 10px 10px 0;
      padding: 1rem 1.3rem;
      margin-bottom: 1.5rem;
      font-size: .88rem;
      line-height: 1.65;
      color: var(--text);
    }}

    /* ── Footer ── */
    .footer {{
      text-align: center;
      font-size: .75rem;
      color: var(--text-dim);
      padding: 1.5rem 1rem;
      border-top: 1px solid var(--border-dim);
      margin-top: 1rem;
    }}

    /* ── Empty / hidden states ── */
    .hidden {{ display: none !important; }}
    .empty-state {{
      text-align: center;
      padding: 3rem 1rem;
      color: var(--text-muted);
      font-size: .9rem;
    }}
    .empty-state .empty-icon {{
      font-size: 2.5rem;
      margin-bottom: .75rem;
      opacity: .4;
    }}

    /* ── Theme toggle button ── */
    .theme-toggle {{
      display: flex;
      align-items: center;
      gap: .5rem;
    }}
    .theme-btn {{
      background: var(--card-2);
      border: 1px solid var(--border);
      color: var(--text-muted);
      border-radius: 20px;
      padding: .35rem .9rem;
      font-size: .78rem;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: .4rem;
      transition: background .15s, border-color .15s, color .15s;
      white-space: nowrap;
    }}
    .theme-btn:hover {{
      border-color: var(--green);
      color: var(--text);
    }}
    .theme-btn .theme-icon {{ font-size: .95rem; }}

    /* ── Scrollbar ── */
    ::-webkit-scrollbar {{ width: 6px; height: 6px; }}
    ::-webkit-scrollbar-track {{ background: var(--bg); }}
    ::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 3px; }}
  </style>
</head>
<body>

  <!-- Header -->
  <div class="header">
    <div class="header-left">
      <h1>Smart Promotions ROI <span style="font-weight:400;color:var(--text-muted);font-size:.95rem;">· Provider Performance Report</span></h1>
      <div class="header-sub">{esc(subtitle)}</div>
    </div>
    <div class="theme-toggle">
      <button class="theme-btn" id="themeToggleBtn" title="Switch theme">
        <span class="theme-icon" id="themeIcon">☀️</span>
        <span id="themeLabel">Light</span>
      </button>
      <div class="badge">BOLT FOOD {esc(country)}</div>
    </div>
  </div>

  <!-- Build banner -->
  <div class="build-banner">{esc(build_banner)}</div>

  <!-- Filter bar -->
  <div class="filter-bar">
    <div class="view-toggle" role="group" aria-label="View by">
      <button class="vt-btn active" id="vtProvider">Provider</button>
      <button class="vt-btn"        id="vtBrand">Brand</button>
    </div>
    <span id="filterProviderWrap" class="filter-entity-wrap">
      <label>PROVIDER</label>
      <span class="combo-wrap" id="providerComboWrap">
        <input type="text" class="combo-input" id="providerComboInput"
               placeholder="Type to search…" autocomplete="off" aria-label="Select provider" />
        <button type="button" class="combo-clear" id="providerComboClear" tabindex="-1">×</button>
        <div class="combo-list" id="providerComboList" role="listbox"></div>
        <!-- hidden value carrier read by load logic -->
        <input type="hidden" id="providerSel" />
      </span>
    </span>
    <span id="filterBrandWrap" class="filter-entity-wrap hidden" title="A brand is a group of provider locations sharing the same brand name">
      <label>BRAND</label>
      <select id="brandSel" aria-label="Select brand (group of providers)"></select>
      <span class="filter-sep">|</span>
      <label>PROVIDER <span style="font-weight:400;text-transform:none;letter-spacing:0">in brand</span></label>
      <select id="brandProviderSel" aria-label="All locations or one provider in this brand">
        <option value="all">All locations</option>
      </select>
    </span>
    <span class="filter-sep">|</span>
    <label>FROM</label>
    <input type="date" id="dateFrom" aria-label="From date">
    <label>TO</label>
    <input type="date" id="dateTo" aria-label="To date">
    <button class="btn-load" id="loadReportBtn">Load Report</button>
  </div>

  <!-- Main content -->
  <div class="wrap">

    <!-- Empty state (before any provider is loaded) -->
    <div id="emptyState" class="empty-state">
      <div class="empty-icon">📊</div>
      <div id="emptyStateMsg">Choose <strong>Provider</strong> or <strong>Brand</strong> (a group of locations), set dates, then click <strong>Load Report</strong>.</div>
    </div>

    <!-- Provider card -->
    <div id="providerCard" class="provider-card hidden">
      <h2 id="pcName">—</h2>
      <div class="provider-meta" id="pcMeta">—</div>
    </div>

    <!-- Hero ROAS -->
    <div id="heroRoas" class="hero-roas hidden">
      <div class="label">Return on Promotional Investment</div>
      <div class="roas-number" id="roasNumber">—</div>
      <div class="roas-sub" id="roasSub">—</div>
    </div>

    <!-- 4 KPI cards -->
    <div id="kpiGrid" class="kpi-grid hidden">
      <div class="kpi-card">
        <div class="kpi-label">Your Investment</div>
        <div class="kpi-value kv-white" id="kpiInvest">—</div>
        <div class="kpi-sub" id="kpiInvestSub">—</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Sales Generated</div>
        <div class="kpi-value kv-green" id="kpiSales">—</div>
        <div class="kpi-sub" id="kpiSalesSub">—</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Promoted Orders</div>
        <div class="kpi-value kv-orange" id="kpiOrders">—</div>
        <div class="kpi-sub" id="kpiOrdersSub">—</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Customers Reached</div>
        <div class="kpi-value kv-purple" id="kpiCustomers">—</div>
        <div class="kpi-sub" id="kpiCustomersSub">—</div>
      </div>
    </div>

    <!-- Charts -->
    <div id="chartsGrid" class="charts-grid hidden">
      <div class="chart-card">
        <h3>Weekly: Your Investment vs Sales Generated</h3>
        <canvas id="investSalesChart"></canvas>
      </div>
      <div class="chart-card">
        <h3>Weekly: ROAS Trend</h3>
        <canvas id="roasTrendChart"></canvas>
      </div>
    </div>

    <!-- Performance by promotion type -->
    <div id="promoTypeCard" class="table-card hidden">
      <h3>Performance by Promotion Type</h3>
      <table class="promo-table" id="promoTypeTable">
        <thead>
          <tr>
            <th>Promotion Type</th>
            <th>Your Investment</th>
            <th>Bolt Co-Investment</th>
            <th>Orders</th>
            <th>Sales (GMV)</th>
            <th>Avg Discount / Order</th>
            <th>ROAS</th>
          </tr>
        </thead>
        <tbody id="promoTypeTbody"></tbody>
      </table>
    </div>

    <!-- SP Audience Cohort breakdown -->
    <div id="cohortCard" class="table-card hidden">
      <h3>Performance by SP Audience Cohort</h3>
      <p style="font-size:.75rem;color:var(--text-muted);margin-bottom:.9rem;">
        The 5 Smart Promotion audience types from the partner portal.
        Discount % varies per provider — figures show actual spend and sales generated.
      </p>
      <div class="charts-grid" style="margin-bottom:1rem;">
        <div class="chart-card">
          <h3>Investment by Audience (Your spend)</h3>
          <canvas id="cohortInvestChart"></canvas>
        </div>
        <div class="chart-card">
          <h3>ROAS by Audience</h3>
          <canvas id="cohortRoasChart"></canvas>
        </div>
      </div>
      <table class="promo-table" id="cohortTable">
        <thead>
          <tr>
            <th>Audience Cohort</th>
            <th>Your Investment</th>
            <th>Bolt Co-Investment</th>
            <th>Orders</th>
            <th>Sales (GMV)</th>
            <th>Avg Discount / Order</th>
            <th>ROAS</th>
          </tr>
        </thead>
        <tbody id="cohortTbody"></tbody>
      </table>
    </div>

    <!-- Brand view: per-location breakdown (only in Brand mode) -->
    <div id="brandProvidersCard" class="table-card hidden">
      <h3>Providers in this brand</h3>
      <p style="font-size:.75rem;color:var(--text-muted);margin-bottom:.9rem;">
        A <strong>brand</strong> is a group of provider locations (same brand name). This table always lists
        <em>every</em> location in the selected brand for the date range. Charts and KPIs above follow
        <strong>Provider in brand</strong> (All locations = whole group, or pick one location).
      </p>
      <table class="promo-table" id="brandProvidersTable">
        <thead>
          <tr>
            <th>Provider</th>
            <th>ID</th>
            <th>Segment</th>
            <th>Your Investment</th>
            <th>Bolt Co-Investment</th>
            <th>Orders</th>
            <th>Sales (GMV)</th>
            <th>Avg Discount / Order</th>
            <th>ROAS</th>
          </tr>
        </thead>
        <tbody id="brandProvidersTbody"></tbody>
      </table>
    </div>

    <!-- AI Summary -->
    <div id="summaryBox" class="summary-box hidden"></div>

    <!-- Recommendation -->
    <div id="recommendationBox" class="recommendation-box hidden"></div>

  </div><!-- /.wrap -->

  <!-- Footer -->
  <div class="footer">
    Smart Promotions ROI Dashboard &middot; Bolt Food {esc(country)} &middot;
    Data: <span id="footerRange">—</span> &middot; v{esc(dashboard_version)}
  </div>

  <!-- Embedded data -->
  <script type="application/json" id="roi-data-json">{data_json}</script>

  <script>
  // ─────────────────────────────────────────────────────────────────────────
  // Data
  // ─────────────────────────────────────────────────────────────────────────
  const DATA = JSON.parse(document.getElementById("roi-data-json").textContent);
  const meta = DATA.meta || {{}};
  const providers    = DATA.providers     || [];
  const weekly       = DATA.weekly        || [];
  const byPromoType  = DATA.by_promo_type || [];
  const bySpCohort   = DATA.by_sp_cohort  || [];
  const totalOrders  = DATA.total_orders  || [];
  const customers    = DATA.customers     || [];

  // ─────────────────────────────────────────────────────────────────────────
  // Brand maps (built once)
  // ─────────────────────────────────────────────────────────────────────────
  // brand_name → Set of provider_ids
  const brandToPids = new Map();
  // provider_id → brand_name
  const pidToBrand  = new Map();
  providers.forEach(p => {{
    const pid   = Number(p.provider_id);
    const brand = String(p.brand_name || p.provider_name || "").trim() || String(pid);
    pidToBrand.set(pid, brand);
    if (!brandToPids.has(brand)) brandToPids.set(brand, new Set());
    brandToPids.get(brand).add(pid);
  }});

  // current view mode
  let viewMode = "provider"; // "provider" | "brand"

  // ─────────────────────────────────────────────────────────────────────────
  // Formatters
  // ─────────────────────────────────────────────────────────────────────────
  function fmtEur(v) {{
    const n = Number(v);
    if (!isFinite(n)) return "—";
    return "€" + n.toLocaleString(undefined, {{minimumFractionDigits: 0, maximumFractionDigits: 0}});
  }}
  function fmtEurDec(v) {{
    const n = Number(v);
    if (!isFinite(n)) return "—";
    return "€" + n.toLocaleString(undefined, {{minimumFractionDigits: 2, maximumFractionDigits: 2}});
  }}
  function fmtInt(v) {{
    const n = Number(v);
    if (!isFinite(n)) return "—";
    return Math.round(n).toLocaleString();
  }}
  function fmtRoas(v) {{
    const n = Number(v);
    if (!isFinite(n) || n <= 0) return "—";
    return n.toFixed(1) + "×";
  }}
  function fmtPct(part, total) {{
    const p = Number(part), t = Number(total);
    if (!isFinite(p) || !isFinite(t) || t === 0) return "—";
    return (100 * p / t).toFixed(1) + "%";
  }}

  // ─────────────────────────────────────────────────────────────────────────
  // Lookup helpers
  // ─────────────────────────────────────────────────────────────────────────
  function byPid(arr, pid) {{
    return arr.filter(r => Number(r.provider_id) === pid);
  }}
  function onePid(arr, pid) {{
    return arr.find(r => Number(r.provider_id) === pid) || null;
  }}

  // ─────────────────────────────────────────────────────────────────────────
  // Date helpers
  // ─────────────────────────────────────────────────────────────────────────
  function parseDate(s) {{
    const p = String(s || "").slice(0, 10).split("-");
    if (p.length !== 3) return new Date(NaN);
    return new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2]));
  }}
  function fmtDateDisplay(s) {{
    const d = parseDate(s);
    if (isNaN(d)) return s || "—";
    return d.toLocaleDateString(undefined, {{day:"2-digit", month:"2-digit", year:"numeric"}});
  }}

  // ─────────────────────────────────────────────────────────────────────────
  // Init filter bar
  // ─────────────────────────────────────────────────────────────────────────
  function escOpt(s) {{
    return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/"/g,"&quot;");
  }}

  /* ── Provider combobox ── */
  (function initProviderCombo() {{
    const inp   = document.getElementById("providerComboInput");
    const list  = document.getElementById("providerComboList");
    const clr   = document.getElementById("providerComboClear");
    const hidden = document.getElementById("providerSel");
    let sortedProviders = [];
    let activeIdx = -1;

    function setVal(pid, label) {{
      hidden.value = pid;
      inp.value = label;
      clr.style.display = label ? "block" : "none";
      closeList();
      activeIdx = -1;
    }}

    function openList(filterText) {{
      const q = (filterText || "").trim().toLowerCase();
      const terms = q ? q.split(/\s+/) : [];
      const matched = sortedProviders.filter(p => {{
        if (!terms.length) return true;
        const hay = (String(p.provider_name||"") + " " + String(p.provider_id||"") + " " + String(p.segment||"")).toLowerCase();
        return terms.every(t => hay.includes(t));
      }});
      list.innerHTML = matched.length
        ? matched.slice(0, 120).map((p, i) => {{
            const lbl = String(p.provider_name||p.provider_id) + (p.segment ? " (" + p.segment + ")" : "");
            return '<div class="combo-opt" data-pid="' + escOpt(String(p.provider_id)) + '" data-label="' + escOpt(lbl) + '" data-idx="' + i + '">' + escOpt(lbl) + "</div>";
          }}).join("")
        : '<div class="combo-none">No matches</div>';
      list.classList.add("open");
      activeIdx = -1;
    }}

    function closeList() {{
      list.classList.remove("open");
    }}

    function moveActive(dir) {{
      const opts = list.querySelectorAll(".combo-opt");
      if (!opts.length) return;
      opts.forEach(o => o.classList.remove("active"));
      activeIdx = Math.max(0, Math.min(opts.length - 1, activeIdx + dir));
      opts[activeIdx].classList.add("active");
      opts[activeIdx].scrollIntoView({{ block: "nearest" }});
    }}

    inp.addEventListener("input", () => {{
      clr.style.display = inp.value ? "block" : "none";
      hidden.value = "";
      openList(inp.value);
    }});
    inp.addEventListener("focus", () => openList(inp.value));
    inp.addEventListener("keydown", e => {{
      if (e.key === "ArrowDown") {{ e.preventDefault(); moveActive(1); }}
      else if (e.key === "ArrowUp") {{ e.preventDefault(); moveActive(-1); }}
      else if (e.key === "Enter") {{
        e.preventDefault();
        const active = list.querySelector(".combo-opt.active");
        if (active) setVal(active.dataset.pid, active.dataset.label);
        else {{
          const first = list.querySelector(".combo-opt");
          if (first) setVal(first.dataset.pid, first.dataset.label);
        }}
      }}
      else if (e.key === "Escape") {{ closeList(); inp.blur(); }}
    }});
    list.addEventListener("mousedown", e => {{
      const opt = e.target.closest(".combo-opt");
      if (opt) {{ e.preventDefault(); setVal(opt.dataset.pid, opt.dataset.label); }}
    }});
    clr.addEventListener("click", () => {{
      setVal("", "");
      inp.focus();
      openList("");
    }});
    document.addEventListener("click", e => {{
      if (!e.target.closest("#providerComboWrap")) closeList();
    }});

    window.populateProviderDropdown = function() {{
      sortedProviders = [...providers].sort((a, b) =>
        String(a.provider_name||"").localeCompare(String(b.provider_name||"")));
      if (!hidden.value && sortedProviders.length) {{
        const p = sortedProviders[0];
        const lbl = String(p.provider_name||p.provider_id) + (p.segment ? " (" + p.segment + ")" : "");
        setVal(String(p.provider_id), lbl);
      }}
    }};
  }})();

  function populateBrandDropdown() {{
    const sel = document.getElementById("brandSel");
    const brands = [...brandToPids.keys()].sort((a, b) => a.localeCompare(b));
    sel.innerHTML = brands.map(b =>
      '<option value="' + escOpt(b) + '">' + escOpt(b) +
      ' (' + brandToPids.get(b).size + " location" + (brandToPids.get(b).size > 1 ? "s" : "") + ")</option>"
    ).join("");
    if (brands.length) populateBrandProviderSel(brands[0]);
  }}

  function populateBrandProviderSel(brandName) {{
    const sel = document.getElementById("brandProviderSel");
    const cur = sel.value;
    const pids = brandToPids.get(brandName);
    let html = '<option value="all">All locations in brand</option>';
    if (pids && pids.size) {{
      const sorted = [...pids].sort((a, b) => {{
        const pa = providers.find(p => Number(p.provider_id) === a);
        const pb = providers.find(p => Number(p.provider_id) === b);
        return String((pa && pa.provider_name) || a).localeCompare(String((pb && pb.provider_name) || b));
      }});
      sorted.forEach(pid => {{
        const p = providers.find(x => Number(x.provider_id) === Number(pid));
        const name = p ? String(p.provider_name || pid) : String(pid);
        html += '<option value="' + escOpt(String(pid)) + '">' + escOpt(name) + "</option>";
      }});
    }}
    sel.innerHTML = html;
    if ([...sel.options].some(o => o.value === cur)) sel.value = cur;
    else sel.value = "all";
  }}

  function firstDayOfMonthIso(iso10) {{
    const p = String(iso10 || "").slice(0, 10).split("-");
    if (p.length !== 3) return iso10;
    return p[0] + "-" + p[1] + "-01";
  }}

  (function initFilters() {{
    const s0 = String(meta.start || "").slice(0, 10);
    const s1 = String(meta.end   || "").slice(0, 10);
    const df = document.getElementById("dateFrom");
    const dt = document.getElementById("dateTo");
    // Default FROM = first day of the month containing the build end date,
    // but not before the available data window.
    let defaultFrom = firstDayOfMonthIso(s1);
    if (defaultFrom < s0) defaultFrom = s0;
    df.min = s0; df.max = s1; df.value = defaultFrom;
    dt.min = s0; dt.max = s1; dt.value = s1;
    document.getElementById("footerRange").textContent =
      (s0 && s1) ? fmtDateDisplay(s0) + " – " + fmtDateDisplay(s1) : "—";
    document.getElementById("filterProviderWrap").classList.remove("hidden");
    document.getElementById("filterBrandWrap").classList.add("hidden");
    populateProviderDropdown();
  }})();

  document.getElementById("brandSel").addEventListener("change", function() {{
    populateBrandProviderSel(this.value);
  }});

  // ─────────────────────────────────────────────────────────────────────────
  // Chart instances
  // ─────────────────────────────────────────────────────────────────────────
  let investSalesChart  = null;
  let roasTrendChart    = null;
  let cohortInvestChart = null;
  let cohortRoasChart   = null;

  Chart.defaults.color = "#7aaa90";
  Chart.defaults.borderColor = "#283d33";

  function cssVar(name) {{
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }}
  function gridColor() {{
    return document.documentElement.classList.contains("light")
      ? "rgba(0,0,0,.08)" : "rgba(255,255,255,.06)";
  }}

  function renderInvestSalesChart(weekRows, d0, d1) {{
    const filtered = weekRows.filter(r => {{
      const w = String(r.week_start || "").slice(0, 10);
      return (!d0 || w >= d0) && (!d1 || w <= d1);
    }});
    filtered.sort((a, b) => String(a.week_start).localeCompare(String(b.week_start)));

    const labels  = filtered.map(r => String(r.week_start || "").slice(0, 10));
    const invest  = filtered.map(r => Number(r.provider_invest) || 0);
    const sales   = filtered.map(r => Number(r.sales_gmv) || 0);
    const gc      = gridColor();
    const green   = cssVar("--green");
    const blue    = cssVar("--blue");

    const ctx = document.getElementById("investSalesChart");
    if (investSalesChart) investSalesChart.destroy();
    investSalesChart = new Chart(ctx, {{
      type: "line",
      data: {{
        labels,
        datasets: [
          {{
            label: "Your Investment (€)",
            data: invest,
            borderColor: green,
            backgroundColor: green + "14",
            borderWidth: 2,
            pointRadius: 4,
            pointBackgroundColor: green,
            tension: .3,
            fill: true,
          }},
          {{
            label: "Sales Generated (€)",
            data: sales,
            borderColor: blue,
            backgroundColor: blue + "14",
            borderWidth: 2,
            pointRadius: 4,
            pointBackgroundColor: blue,
            tension: .3,
            fill: true,
          }},
        ],
      }},
      options: {{
        responsive: true,
        plugins: {{
          legend: {{
            position: "top",
            labels: {{ boxWidth: 14, font: {{ size: 11 }}, color: cssVar("--text-muted") }},
          }},
        }},
        scales: {{
          x: {{
            ticks: {{
              maxRotation: 45, minRotation: 25,
              autoSkip: true, maxTicksLimit: 12,
              font: {{ size: 10 }}, color: cssVar("--text-muted"),
            }},
            grid: {{ color: gc }},
          }},
          y: {{
            beginAtZero: true,
            ticks: {{ callback: v => "€" + v.toLocaleString(), color: cssVar("--text-muted") }},
            grid: {{ color: gc }},
          }},
        }},
      }},
    }});
  }}

  function renderRoasTrendChart(weekRows, d0, d1) {{
    const filtered = weekRows.filter(r => {{
      const w = String(r.week_start || "").slice(0, 10);
      return (!d0 || w >= d0) && (!d1 || w <= d1);
    }});
    filtered.sort((a, b) => String(a.week_start).localeCompare(String(b.week_start)));

    const labels = filtered.map(r => String(r.week_start || "").slice(0, 10));
    const roas   = filtered.map(r => {{
      const inv = Number(r.provider_invest) || 0;
      const gmv = Number(r.sales_gmv) || 0;
      return inv > 0 ? gmv / inv : 0;
    }});
    const gc    = gridColor();
    const green = cssVar("--green");

    const ctx = document.getElementById("roasTrendChart");
    if (roasTrendChart) roasTrendChart.destroy();
    roasTrendChart = new Chart(ctx, {{
      type: "line",
      data: {{
        labels,
        datasets: [{{
          label: "ROAS (×)",
          data: roas,
          borderColor: green,
          backgroundColor: green + "1a",
          borderWidth: 2.5,
          pointRadius: 5,
          pointBackgroundColor: green,
          tension: .35,
          fill: true,
        }}],
      }},
      options: {{
        responsive: true,
        plugins: {{
          legend: {{
            position: "top",
            labels: {{ boxWidth: 14, font: {{ size: 11 }}, color: cssVar("--text-muted") }},
          }},
        }},
        scales: {{
          x: {{
            ticks: {{
              maxRotation: 45, minRotation: 25,
              autoSkip: true, maxTicksLimit: 12,
              font: {{ size: 10 }}, color: cssVar("--text-muted"),
            }},
            grid: {{ color: gc }},
          }},
          y: {{
            beginAtZero: true,
            ticks: {{ callback: v => v.toFixed(1) + "×", color: cssVar("--text-muted") }},
            grid: {{ color: gc }},
          }},
        }},
      }},
    }});
  }}

  // ─────────────────────────────────────────────────────────────────────────
  // Cohort charts + table
  // ─────────────────────────────────────────────────────────────────────────
  function renderCohortSection(cohortRows) {{
    if (!cohortRows.length) {{
      document.getElementById("cohortCard").classList.add("hidden");
      return;
    }}
    document.getElementById("cohortCard").classList.remove("hidden");
    const gc     = gridColor();
    const labels = cohortRows.map(r => r.audience_cohort);
    const colours = labels.map(l => {{
      const i = COHORT_ORDER.indexOf(l);
      return i !== -1 ? COHORT_COLOURS[i] : "#888888";
    }});

    // Investment bar chart
    const invest = cohortRows.map(r => r.provider_invest);
    const ctx1   = document.getElementById("cohortInvestChart");
    if (cohortInvestChart) cohortInvestChart.destroy();
    cohortInvestChart = new Chart(ctx1, {{
      type: "bar",
      data: {{
        labels,
        datasets: [{{
          label: "Your Investment (€)",
          data: invest,
          backgroundColor: colours.map(c => c + "cc"),
          borderColor:     colours,
          borderWidth: 1.5,
        }}],
      }},
      options: {{
        indexAxis: "y",
        responsive: true,
        plugins: {{ legend: {{ display: false }} }},
        scales: {{
          x: {{ beginAtZero: true, ticks: {{ callback: v => "€" + v.toLocaleString(), color: cssVar("--text-muted") }}, grid: {{ color: gc }} }},
          y: {{ ticks: {{ color: cssVar("--text-muted"), font: {{ size: 11 }} }}, grid: {{ color: gc }} }},
        }},
      }},
    }});

    // ROAS bar chart
    const roasVals = cohortRows.map(r => r.provider_invest > 0 ? r.sales_gmv / r.provider_invest : 0);
    const ctx2     = document.getElementById("cohortRoasChart");
    if (cohortRoasChart) cohortRoasChart.destroy();
    cohortRoasChart = new Chart(ctx2, {{
      type: "bar",
      data: {{
        labels,
        datasets: [{{
          label: "ROAS (×)",
          data: roasVals,
          backgroundColor: colours.map(c => c + "cc"),
          borderColor:     colours,
          borderWidth: 1.5,
        }}],
      }},
      options: {{
        indexAxis: "y",
        responsive: true,
        plugins: {{ legend: {{ display: false }} }},
        scales: {{
          x: {{ beginAtZero: true, ticks: {{ callback: v => v.toFixed(1) + "×", color: cssVar("--text-muted") }}, grid: {{ color: gc }} }},
          y: {{ ticks: {{ color: cssVar("--text-muted"), font: {{ size: 11 }} }}, grid: {{ color: gc }} }},
        }},
      }},
    }});

    // Table
    document.getElementById("cohortTbody").innerHTML = cohortRows.map((r, i) => {{
      const pi   = r.provider_invest;
      const bi   = r.bolt_invest;
      const gmv  = r.sales_gmv;
      const ord  = r.promoted_orders;
      const rr   = pi > 0 ? gmv / pi : 0;
      const avgD = ord > 0 ? pi / ord : 0;
      const col  = colours[i] || "#888888";
      return "<tr>"
        + "<td><span class='promo-badge' style='background:transparent;border-color:" + col + ";color:" + col + "'>"
        + escHTML(r.audience_cohort) + "</span></td>"
        + "<td>" + fmtEur(pi)      + "</td>"
        + "<td>" + fmtEur(bi)      + "</td>"
        + "<td>" + fmtInt(ord)     + "</td>"
        + "<td>" + fmtEur(gmv)     + "</td>"
        + "<td>" + fmtEurDec(avgD) + "</td>"
        + "<td>" + fmtRoas(rr)     + "</td>"
        + "</tr>";
    }}).join("") || "<tr><td colspan='7' style='text-align:center;color:var(--text-muted)'>No cohort data</td></tr>";
  }}

  // ─────────────────────────────────────────────────────────────────────────
  // Summary text generator
  // ─────────────────────────────────────────────────────────────────────────
  function buildSummary(provName, provInvest, boltInvest, salesGmv, promotedOrders, roas, ftCustomers, customersReached) {{
    const net = salesGmv - provInvest;
    const salesPerEur = provInvest > 0 ? Math.round(salesGmv / provInvest) : 0;
    let html = "";

    html += "<strong style='color:var(--text)'>" + escHTML(provName) + "</strong> invested ";
    html += "<strong style='color:var(--green)'>€" + fmtInt(provInvest) + "</strong>";
    html += " in promotions on Bolt Food. ";
    html += "These promotions were applied on ";
    html += "<strong style='color:var(--orange)'>" + fmtInt(promotedOrders) + " orders</strong>";
    html += ", generating <strong style='color:var(--green)'>€" + fmtInt(salesGmv) + " in sales</strong>.";

    if (roas > 0) {{
      html += "<br><br>For every <strong>€1 invested</strong>, ";
      html += "<strong style='color:var(--green)'>€" + salesPerEur + " in sales</strong>";
      html += " were generated (ROAS: <strong>" + fmtRoas(roas) + "</strong>).";
    }}

    if (ftCustomers > 0) {{
      html += " Among those orders, ";
      html += "<strong style='color:var(--purple)'>" + fmtInt(ftCustomers) + " came from first-time customers</strong>";
      html += " — new business driven by your promotions.";
    }}

    return html;
  }}

  function buildRecommendation(roas, provInvest) {{
    if (roas <= 0 || provInvest <= 0) {{
      return "<strong>No data available</strong> for this provider and date range. Try broadening the window.";
    }}
    if (roas >= 20) {{
      return "<strong>Strong performance.</strong> A ROAS of " + fmtRoas(roas) +
             " means promotions are working exceptionally well. Consider increasing investment to capture more volume.";
    }}
    if (roas >= 10) {{
      return "<strong>Good performance.</strong> Your promotions are delivering solid returns at " + fmtRoas(roas) +
             ". Consider testing higher-value discounts to attract premium customers.";
    }}
    if (roas >= 5) {{
      return "<strong>Moderate performance.</strong> ROAS of " + fmtRoas(roas) +
             " leaves room to improve. Try adjusting discount levels or testing different promotion types.";
    }}
    return "<strong>Below target.</strong> ROAS of " + fmtRoas(roas) +
           " suggests promotions need review. Consider pausing or restructuring underperforming campaigns.";
  }}

  function escHTML(s) {{
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }}

  // ─────────────────────────────────────────────────────────────────────────
  // Aggregation helpers (brand mode sums across multiple provider_ids)
  // ─────────────────────────────────────────────────────────────────────────
  function aggregateWeekly(pidSet, d0, d1) {{
    const byWeek = {{}};
    weekly.forEach(r => {{
      if (!pidSet.has(Number(r.provider_id))) return;
      const w = String(r.week_start || "").slice(0, 10);
      if (d0 && w < d0) return;
      if (d1 && w > d1) return;
      if (!byWeek[w]) byWeek[w] = {{ week_start: w, provider_invest: 0, bolt_invest: 0, sales_gmv: 0, promoted_orders: 0 }};
      byWeek[w].provider_invest += Number(r.provider_invest) || 0;
      byWeek[w].bolt_invest     += Number(r.bolt_invest)     || 0;
      byWeek[w].sales_gmv       += Number(r.sales_gmv)       || 0;
      byWeek[w].promoted_orders += Number(r.promoted_orders) || 0;
    }});
    return Object.values(byWeek).sort((a, b) => a.week_start.localeCompare(b.week_start));
  }}

  function aggregatePromoType(pidSet) {{
    const byType = {{}};
    byPromoType.forEach(r => {{
      if (!pidSet.has(Number(r.provider_id))) return;
      const t = String(r.promotion_type || "Other");
      if (!byType[t]) byType[t] = {{ promotion_type: t, provider_invest: 0, bolt_invest: 0, sales_gmv: 0, promoted_orders: 0 }};
      byType[t].provider_invest += Number(r.provider_invest) || 0;
      byType[t].bolt_invest     += Number(r.bolt_invest)     || 0;
      byType[t].sales_gmv       += Number(r.sales_gmv)       || 0;
      byType[t].promoted_orders += Number(r.promoted_orders) || 0;
    }});
    return Object.values(byType).sort((a, b) => b.provider_invest - a.provider_invest);
  }}

  // Cohort order mirrors the partner portal UI
  const COHORT_ORDER = [
    "New Bolt Food customers",
    "Promising returning customers",
    "High-spending customers",
    "Most active customers",
    "Loyal high frequency customers",
    "Other / unclassified",
  ];
  const COHORT_COLOURS = [
    "#4a9eff", // blue  — New
    "#34d88c", // green — Promising returning
    "#f5a623", // orange — High-spending
    "#b39ddb", // purple — Most active
    "#ffd54f", // yellow — Loyal high frequency
    "#888888", // grey  — Other
  ];

  function aggregateSpCohort(pidSet) {{
    const byCohort = {{}};
    bySpCohort.forEach(r => {{
      if (!pidSet.has(Number(r.provider_id))) return;
      const k = String(r.audience_cohort || "Other / unclassified");
      if (!byCohort[k]) byCohort[k] = {{ audience_cohort: k, provider_invest: 0, bolt_invest: 0, sales_gmv: 0, promoted_orders: 0 }};
      byCohort[k].provider_invest += Number(r.provider_invest) || 0;
      byCohort[k].bolt_invest     += Number(r.bolt_invest)     || 0;
      byCohort[k].sales_gmv       += Number(r.sales_gmv)       || 0;
      byCohort[k].promoted_orders += Number(r.promoted_orders) || 0;
    }});
    // Sort by the canonical cohort order, then by spend for any unlisted keys
    return Object.values(byCohort).sort((a, b) => {{
      const ia = COHORT_ORDER.indexOf(a.audience_cohort);
      const ib = COHORT_ORDER.indexOf(b.audience_cohort);
      if (ia !== -1 && ib !== -1) return ia - ib;
      if (ia !== -1) return -1;
      if (ib !== -1) return 1;
      return b.provider_invest - a.provider_invest;
    }});
  }}

  function aggregateTotals(pidSet) {{
    let invest = 0, bolt = 0, gmv = 0, promoted = 0, allOrders = 0, reached = 0, firstTime = 0;
    totalOrders.forEach(r => {{
      if (pidSet.has(Number(r.provider_id))) allOrders += Number(r.total_orders) || 0;
    }});
    customers.forEach(r => {{
      if (pidSet.has(Number(r.provider_id))) {{
        reached   += Number(r.customers_reached)    || 0;
        firstTime += Number(r.first_time_customers) || 0;
      }}
    }});
    return {{ allOrders, reached, firstTime }};
  }}

  /** Per-provider metrics inside a date window (for brand drill-down). */
  function aggregatePerProviderBreakdown(pidSet, d0, d1) {{
    const out = [];
    pidSet.forEach(pid => {{
      let invest = 0, bolt = 0, gmv = 0, ord = 0;
      weekly.forEach(r => {{
        if (Number(r.provider_id) !== pid) return;
        const w = String(r.week_start || "").slice(0, 10);
        if (d0 && w < d0) return;
        if (d1 && w > d1) return;
        invest += Number(r.provider_invest) || 0;
        bolt   += Number(r.bolt_invest)     || 0;
        gmv    += Number(r.sales_gmv)       || 0;
        ord    += Number(r.promoted_orders) || 0;
      }});
      const prov = providers.find(p => Number(p.provider_id) === pid);
      out.push({{
        provider_id:     pid,
        provider_name:   prov ? String(prov.provider_name || "") : "—",
        segment:         prov ? String(prov.segment || "") : "",
        provider_invest: invest,
        bolt_invest:     bolt,
        sales_gmv:       gmv,
        promoted_orders: ord,
      }});
    }});
    out.sort((a, b) =>
      (b.provider_invest - a.provider_invest) || (b.promoted_orders - a.promoted_orders)
    );
    return out;
  }}

  function renderBrandProviderTable(rows) {{
    const card = document.getElementById("brandProvidersCard");
    const tbody = document.getElementById("brandProvidersTbody");
    if (!rows.length) {{
      card.classList.add("hidden");
      return;
    }}
    card.classList.remove("hidden");
    tbody.innerHTML = rows.map(r => {{
      const pi   = r.provider_invest;
      const bi   = r.bolt_invest;
      const gmv  = r.sales_gmv;
      const ord  = r.promoted_orders;
      const rr   = pi > 0 ? gmv / pi : 0;
      const avgD = ord > 0 ? pi / ord : 0;
      return "<tr>"
        + "<td>" + escHTML(r.provider_name) + "</td>"
        + "<td>" + String(r.provider_id) + "</td>"
        + "<td>" + escHTML(r.segment) + "</td>"
        + "<td>" + fmtEur(pi) + "</td>"
        + "<td>" + fmtEur(bi) + "</td>"
        + "<td>" + fmtInt(ord) + "</td>"
        + "<td>" + fmtEur(gmv) + "</td>"
        + "<td>" + fmtEurDec(avgD) + "</td>"
        + "<td>" + fmtRoas(rr) + "</td>"
        + "</tr>";
    }}).join("") || "<tr><td colspan='9' style='text-align:center;color:var(--text-muted)'>No rows</td></tr>";
  }}

  // ─────────────────────────────────────────────────────────────────────────
  // Load Report
  // ─────────────────────────────────────────────────────────────────────────
  function loadReport() {{
    const d0 = document.getElementById("dateFrom").value;
    const d1 = document.getElementById("dateTo").value;

    // Metrics scope (pidSet) vs full brand group (for location table in brand mode)
    let pidSet = new Set();
    /** All provider_ids in the selected brand — always used for the breakdown table. */
    let brandGroupPidSet = new Set();
    let displayName = "";
    let metaLine    = "";

    if (viewMode === "brand") {{
      const brandName = document.getElementById("brandSel").value;
      if (!brandName) return;
      const pidsInBrand = brandToPids.get(brandName);
      if (pidsInBrand) pidsInBrand.forEach(id => brandGroupPidSet.add(Number(id)));

      const sub = document.getElementById("brandProviderSel").value;
      if (sub === "all") {{
        brandGroupPidSet.forEach(id => pidSet.add(id));
        displayName = brandName;
        const locCount = pidSet.size;
        metaLine = "Brand group · " + locCount + " provider location" + (locCount !== 1 ? "s" : "") + " · " + d0 + " → " + d1;
      }} else {{
        const pid = Number(sub);
        pidSet.add(pid);
        const prov = providers.find(p => Number(p.provider_id) === pid);
        displayName = prov ? String(prov.provider_name || "Provider " + pid) : "Provider " + pid;
        metaLine = "Under brand: " + brandName + " · " + d0 + " → " + d1;
      }}
    }} else {{
      const selVal = document.getElementById("providerSel").value;
      if (!selVal) return;
      const pid  = Number(selVal);
      pidSet.add(pid);
      const prov = providers.find(p => Number(p.provider_id) === pid);
      displayName = prov ? String(prov.provider_name || "Provider " + pid) : "Provider " + pid;
      const seg   = prov && prov.segment ? String(prov.segment) : "";
      const brand = prov && prov.brand_name && prov.brand_name !== prov.provider_name
                    ? " · Brand: " + prov.brand_name : "";
      metaLine = [seg, d0 + " → " + d1].filter(Boolean).join(" · ") + brand;
    }}

    // Aggregate data
    const weekRows  = aggregateWeekly(pidSet, d0, d1);
    const promoRows = aggregatePromoType(pidSet);
    const {{ allOrders, reached: custReached, firstTime: firstTimeCust }} = aggregateTotals(pidSet);

    let totalInvest = 0, totalBolt = 0, totalGmv = 0, totalPromoted = 0;
    weekRows.forEach(r => {{
      totalInvest   += r.provider_invest;
      totalBolt     += r.bolt_invest;
      totalGmv      += r.sales_gmv;
      totalPromoted += r.promoted_orders;
    }});

    const roas     = totalInvest > 0 ? totalGmv / totalInvest : 0;
    const netSales = totalGmv - totalInvest;

    // ── Provider / Brand card ──
    document.getElementById("emptyState").classList.add("hidden");
    document.getElementById("providerCard").classList.remove("hidden");
    document.getElementById("pcName").textContent = displayName;
    document.getElementById("pcMeta").textContent = metaLine;

    // ── Hero ROAS ──
    document.getElementById("heroRoas").classList.remove("hidden");
    document.getElementById("roasNumber").textContent = fmtRoas(roas);
    document.getElementById("roasSub").textContent =
      roas > 0
        ? "For every €1 invested in promotions, €" + Math.round(roas) + " in sales were generated."
        : "No promoted orders found in this date range.";

    // ── KPI cards ──
    document.getElementById("kpiGrid").classList.remove("hidden");

    document.getElementById("kpiInvest").textContent = fmtEur(totalInvest);
    document.getElementById("kpiInvestSub").innerHTML =
      "Bolt co-invested " + fmtEur(totalBolt) +
      " &middot; Total discount value " + fmtEur(totalInvest + totalBolt);

    document.getElementById("kpiSales").textContent = fmtEur(totalGmv);
    document.getElementById("kpiSalesSub").textContent =
      netSales >= 0 ? "Net after your investment: " + fmtEur(netSales) : "Net: " + fmtEur(netSales);

    document.getElementById("kpiOrders").textContent = fmtInt(totalPromoted);
    document.getElementById("kpiOrdersSub").textContent =
      allOrders > 0
        ? fmtPct(totalPromoted, allOrders) + " of your total " + fmtInt(allOrders) + " orders"
        : "Promoted orders";

    document.getElementById("kpiCustomers").textContent =
      custReached > 0 ? fmtInt(custReached) : "N/A";
    document.getElementById("kpiCustomersSub").textContent =
      firstTimeCust > 0 ? firstTimeCust + " were first-time customers" : "";

    // ── Charts ──
    document.getElementById("chartsGrid").classList.remove("hidden");
    renderInvestSalesChart(weekRows, null, null); // already filtered above
    renderRoasTrendChart(weekRows, null, null);

    // ── SP Cohort section ──
    renderCohortSection(aggregateSpCohort(pidSet));

    // ── Promo type table ──
    document.getElementById("promoTypeCard").classList.remove("hidden");
    document.getElementById("promoTypeTbody").innerHTML = promoRows.map(r => {{
      const pi   = r.provider_invest;
      const bi   = r.bolt_invest;
      const gmv  = r.sales_gmv;
      const ord  = r.promoted_orders;
      const rr   = pi > 0 ? gmv / pi : 0;
      const avgD = ord > 0 ? pi / ord : 0;
      return "<tr>"
        + "<td><span class='promo-badge'>" + escHTML(r.promotion_type) + "</span></td>"
        + "<td>" + fmtEur(pi) + "</td>"
        + "<td>" + fmtEur(bi) + "</td>"
        + "<td>" + fmtInt(ord) + "</td>"
        + "<td>" + fmtEur(gmv) + "</td>"
        + "<td>" + fmtEurDec(avgD) + "</td>"
        + "<td>" + fmtRoas(rr) + "</td>"
        + "</tr>";
    }}).join("") || "<tr><td colspan='7' style='text-align:center;color:var(--text-muted)'>No promotion data</td></tr>";

    // ── Brand: full provider list for the brand (always the whole group) ──
    if (viewMode === "brand" && brandGroupPidSet.size) {{
      renderBrandProviderTable(aggregatePerProviderBreakdown(brandGroupPidSet, d0, d1));
    }} else {{
      document.getElementById("brandProvidersCard").classList.add("hidden");
    }}

    // ── Summary & Recommendation ──
    const sumEl = document.getElementById("summaryBox");
    sumEl.classList.remove("hidden");
    sumEl.innerHTML = buildSummary(displayName, totalInvest, totalBolt, totalGmv,
                                   totalPromoted, roas, firstTimeCust, custReached);

    const recEl = document.getElementById("recommendationBox");
    recEl.classList.remove("hidden");
    recEl.innerHTML = buildRecommendation(roas, totalInvest);
  }}

  // ─────────────────────────────────────────────────────────────────────────
  // Theme toggle (black ↔ white)
  // ─────────────────────────────────────────────────────────────────────────
  (function initTheme() {{
    const saved = localStorage.getItem("sp-roi-theme");
    if (saved === "light") applyTheme("light");
  }})();

  function applyTheme(mode) {{
    const html  = document.documentElement;
    const btn   = document.getElementById("themeToggleBtn");
    const icon  = document.getElementById("themeIcon");
    const label = document.getElementById("themeLabel");
    if (mode === "light") {{
      html.classList.add("light");
      icon.textContent  = "🌙";
      label.textContent = "Dark";
      Chart.defaults.color       = "#555555";
      Chart.defaults.borderColor = "#d9d9d9";
    }} else {{
      html.classList.remove("light");
      icon.textContent  = "☀️";
      label.textContent = "Light";
      Chart.defaults.color       = "#888888";
      Chart.defaults.borderColor = "#222222";
    }}
    localStorage.setItem("sp-roi-theme", mode);
    // Redraw charts with new grid colours if a report is loaded
    if (investSalesChart) loadReport();
  }}

  document.getElementById("themeToggleBtn").addEventListener("click", function() {{
    const isLight = document.documentElement.classList.contains("light");
    applyTheme(isLight ? "dark" : "light");
  }});

  // ─────────────────────────────────────────────────────────────────────────
  // View toggle wiring
  // ─────────────────────────────────────────────────────────────────────────
  function switchView(mode) {{
    viewMode = mode;
    document.getElementById("vtProvider").classList.toggle("active", mode === "provider");
    document.getElementById("vtBrand").classList.toggle("active", mode === "brand");
    const pw = document.getElementById("filterProviderWrap");
    const bw = document.getElementById("filterBrandWrap");
    if (mode === "provider") {{
      pw.classList.remove("hidden");
      bw.classList.add("hidden");
      populateProviderDropdown();
    }} else {{
      pw.classList.add("hidden");
      bw.classList.remove("hidden");
      populateBrandDropdown();
    }}
    // Reset report area
    document.getElementById("emptyState").classList.remove("hidden");
    ["providerCard","heroRoas","kpiGrid","chartsGrid","cohortCard","promoTypeCard","brandProvidersCard","summaryBox","recommendationBox"]
      .forEach(id => document.getElementById(id).classList.add("hidden"));
  }}
  document.getElementById("vtProvider").addEventListener("click", () => switchView("provider"));
  document.getElementById("vtBrand").addEventListener("click",    () => switchView("brand"));

  // ─────────────────────────────────────────────────────────────────────────
  // Event wiring
  // ─────────────────────────────────────────────────────────────────────────
  document.getElementById("loadReportBtn").addEventListener("click", loadReport);

  // Auto-load first provider on page open
  if (providers.length > 0) {{
    loadReport();
  }}
  </script>
</body>
</html>
"""
