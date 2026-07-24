#!/usr/bin/env python3
"""
Malta Account Performance Dashboard — live Databricks data + Salesforce account ownership.

Account owner: dim_provider_v2.sf_account_owner_name (Salesforce snapshot).
Account name: provider_account_recipient; brand = brand_name; provider = provider_name.

Comparison modes (client-side): WoW (weekly GMV), MoM and YoY (monthly GMV).
Fair partial-period slice when current week/month is still running (Europe/Malta).

Output default: ~/Desktop/Cursor projects/outputs/bolt-food/mt_account_performance.html

Usage:
  python3 build_mt_account_performance_dashboard.py
  python3 build_mt_account_performance_dashboard.py --end-month 2026-06 --history-months 24
"""

from __future__ import annotations

from cursor_output_paths import bolt_food_output_dir, bolt_food_output_path, bad_orders_output_dir
import argparse
import calendar
import datetime as dt
import html as html_lib
import json
import os
import sys
from typing import Any, Optional

import pandas as pd
from zoneinfo import ZoneInfo

_ROOT = os.path.dirname(os.path.abspath(__file__))
_MALTA_TZ = ZoneInfo("Europe/Malta")


def _ensure_dbx_on_path() -> None:
    dbx_dir = os.path.join(_ROOT, "databricks-setup")
    if dbx_dir not in sys.path:
        sys.path.insert(0, dbx_dir)


def _period_tuple(s: str) -> tuple[int, int]:
    p = s.strip().split("-")
    if len(p) != 2:
        raise ValueError(f"Bad month {s!r}, use YYYY-MM")
    y, m = int(p[0]), int(p[1])
    if m < 1 or m > 12:
        raise ValueError(f"Bad month {s!r}")
    return y, m


def _month_partition_str(y: int, m: int) -> str:
    return f"{y:04d}-{m:02d}-01"


def _shift_month(y: int, m: int, delta: int) -> tuple[int, int]:
    idx = y * 12 + (m - 1) + delta
    ny, nm0 = divmod(idx, 12)
    return ny, nm0 + 1


def month_series_ending(end_month: str, n_months: int) -> list[str]:
    y, m = _period_tuple(end_month)
    out: list[str] = []
    for k in range(n_months - 1, -1, -1):
        yy, mm = _shift_month(y, m, -k)
        out.append(f"{yy:04d}-{mm:02d}")
    return out


def _week_start(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())


def week_series_ending(end_date: dt.date, n_weeks: int) -> list[str]:
    """ISO week labels YYYY-Www from oldest → newest."""
    cur = _week_start(end_date)
    starts: list[dt.date] = []
    for _ in range(n_weeks):
        starts.append(cur)
        cur = cur - dt.timedelta(days=7)
    starts.reverse()
    out: list[str] = []
    for ws in starts:
        iso = ws.isocalendar()
        out.append(f"{iso.year:04d}-W{iso.week:02d}")
    return out


def _week_start_from_label(label: str) -> Optional[dt.date]:
    try:
        y_str, w_str = label.split("-W")
        y, w = int(y_str), int(w_str)
        return dt.date.fromisocalendar(y, w, 1)
    except (ValueError, AttributeError):
        return None


def _range_dates_months(month_keys: list[str]) -> tuple[str, str]:
    first_y, first_m = _period_tuple(month_keys[0])
    last_y, last_m = _period_tuple(month_keys[-1])
    start = _month_partition_str(first_y, first_m)
    ly, lm = _shift_month(last_y, last_m, 1)
    end_excl = _month_partition_str(ly, lm)
    return start, end_excl


def _range_dates_weeks(week_keys: list[str]) -> tuple[str, str]:
    first = _week_start_from_label(week_keys[0])
    last = _week_start_from_label(week_keys[-1])
    if not first or not last:
        raise ValueError("Invalid week keys")
    end_excl = last + dt.timedelta(days=7)
    return first.isoformat(), end_excl.isoformat()


def _normalize_month_key(raw: Optional[str]) -> str:
    if not raw:
        return ""
    s = str(raw).strip()
    if len(s) >= 7 and s[4] == "-":
        return s[:7]
    return s


def _normalize_week_key(raw: Optional[str]) -> str:
    if not raw:
        return ""
    s = str(raw).strip()[:10]
    try:
        d = dt.date.fromisoformat(s)
        iso = d.isocalendar()
        return f"{iso.year:04d}-W{iso.week:02d}"
    except ValueError:
        return ""


def _json_for_script(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def query_provider_spine(dbx: Any, country_code: str) -> pd.DataFrame:
    cc = country_code.lower()
    return dbx.query(
        f"""
        SELECT
          CAST(p.provider_id AS BIGINT) AS provider_id,
          COALESCE(p.provider_name, '') AS provider_name,
          COALESCE(NULLIF(TRIM(p.brand_name), ''), '') AS brand_name,
          COALESCE(NULLIF(TRIM(p.provider_account_recipient), ''), '') AS account_name,
          COALESCE(p.sf_account_owner_name, '') AS sf_owner,
          COALESCE(p.account_manager_name, '') AS dbx_am,
          COALESCE(p.business_segment_v2, '') AS segment,
          COALESCE(p.provider_status, '') AS provider_status
        FROM ng_delivery_spark.dim_provider_v2 p
        WHERE LOWER(p.country_code) = '{cc}'
        """
    )


def query_gmv_by_month(dbx: Any, country_code: str, month_keys: list[str]) -> pd.DataFrame:
    parts_sql = ", ".join(
        f"DATE '{_period_tuple(k)[0]:04d}-{_period_tuple(k)[1]:02d}-01'" for k in month_keys
    )
    return dbx.query(
        f"""
        SELECT
          CAST(p.provider_id AS BIGINT) AS provider_id,
          CAST(m.metric_timestamp_partition AS STRING) AS month_key,
          CAST(COALESCE(m.total_gmv_before_discounts_eur, 0) AS DOUBLE) AS gmv
        FROM ng_delivery_spark.dim_provider_v2 p
        INNER JOIN ng_delivery_spark.fact_provider_monthly m
          ON m.provider_id = p.provider_id
        WHERE LOWER(p.country_code) = '{country_code.lower()}'
          AND m.metric_timestamp_partition IN ({parts_sql})
        """
    )


def query_gmv_by_week(
    dbx: Any, country_code: str, range_start: str, range_end_exclusive: str
) -> pd.DataFrame:
    cc = country_code.lower()
    return dbx.query(
        f"""
        SELECT
          CAST(provider_id AS BIGINT) AS provider_id,
          CAST(DATE_TRUNC('week', order_created_date) AS STRING) AS week_raw,
          CAST(SUM(COALESCE(gmv_eur, 0)) AS DOUBLE) AS gmv
        FROM ng_public_spark.etl_delivery_order_monetary_metrics
        WHERE LOWER(country) = '{cc}'
          AND order_created_date >= DATE '{range_start}'
          AND order_created_date < DATE '{range_end_exclusive}'
        GROUP BY provider_id, DATE_TRUNC('week', order_created_date)
        """
    )


def query_gmv_daily_incr(
    dbx: Any, country_code: str, range_start: str, range_end_exclusive: str
) -> pd.DataFrame:
    """Daily GMV by provider for fair partial-week/month proration."""
    cc = country_code.lower()
    return dbx.query(
        f"""
        SELECT
          CAST(provider_id AS BIGINT) AS provider_id,
          CAST(order_created_date AS STRING) AS order_date,
          CAST(SUM(COALESCE(gmv_eur, 0)) AS DOUBLE) AS gmv
        FROM ng_public_spark.etl_delivery_order_monetary_metrics
        WHERE LOWER(country) = '{cc}'
          AND order_created_date >= DATE '{range_start}'
          AND order_created_date < DATE '{range_end_exclusive}'
        GROUP BY provider_id, order_created_date
        """
    )


def query_sp_enrollment_summary(dbx: Any, country_code: str) -> pd.DataFrame:
    cc = country_code.lower()
    return dbx.query(
        f"""
        SELECT
          CAST(e.provider_id AS BIGINT) AS provider_id,
          CASE
            WHEN MAX(CASE WHEN LOWER(TRIM(COALESCE(e.smart_promo_enrollment_state, ''))) = 'active'
              THEN 1 ELSE 0 END) = 1 THEN 'Active'
            ELSE 'Inactive'
          END AS status,
          CAST(MIN(
            CASE WHEN LOWER(TRIM(COALESCE(e.smart_promo_enrollment_state, ''))) = 'active'
              THEN CAST(e.smart_promo_offer_provider_enrollment_start_date AS DATE)
            END
          ) AS STRING) AS opt_in_date,
          CAST(MAX(
            CASE WHEN LOWER(TRIM(COALESCE(e.smart_promo_enrollment_state, ''))) != 'active'
              THEN CAST(COALESCE(
                e.smart_promo_offer_provider_enrollment_end_ts,
                e.smart_promo_provider_enrollment_end_ts
              ) AS DATE)
            END
          ) AS STRING) AS opt_out_date
        FROM core_models_spark.fact_provider_smart_promo_offer_campaign_enrollment e
        INNER JOIN ng_delivery_spark.dim_provider_v2 p
          ON p.provider_id = e.provider_id AND LOWER(p.country_code) = '{cc}'
        WHERE LOWER(e.country_code) = '{cc}'
        GROUP BY e.provider_id
        """
    )


def query_sl_enrollment_summary(dbx: Any, country_code: str) -> pd.DataFrame:
    cc = country_code.lower()
    return dbx.query(
        f"""
        SELECT
          CAST(e.provider_id AS BIGINT) AS provider_id,
          CASE
            WHEN MAX(CASE WHEN LOWER(TRIM(COALESCE(e.sponsored_listing_state, ''))) = 'active'
              THEN 1 ELSE 0 END) = 1 THEN 'Active'
            ELSE 'Inactive'
          END AS status,
          CAST(MIN(
            CASE WHEN LOWER(TRIM(COALESCE(e.sponsored_listing_state, ''))) = 'active'
              THEN CAST(e.sponsored_listing_start_ts_local AS DATE)
            END
          ) AS STRING) AS opt_in_date,
          CAST(MAX(
            CASE WHEN LOWER(TRIM(COALESCE(e.sponsored_listing_state, ''))) != 'active'
              THEN CAST(COALESCE(
                e.sponsored_listing_actual_end_ts_local,
                e.sponsored_listing_default_end_ts_local
              ) AS DATE)
            END
          ) AS STRING) AS opt_out_date
        FROM core_models_spark.fact_provider_sponsored_listing_offer_enrollment e
        INNER JOIN ng_delivery_spark.dim_provider_v2 p
          ON p.provider_id = e.provider_id AND LOWER(p.country_code) = '{cc}'
        WHERE LOWER(e.country_code) = '{cc}'
        GROUP BY e.provider_id
        """
    )


def _empty_daily_month(month_keys: list[str]) -> list[list[float]]:
    return [[0.0] * calendar.monthrange(*_period_tuple(ym))[1] for ym in month_keys]


def _empty_daily_week(week_keys: list[str]) -> list[list[float]]:
    out: list[list[float]] = []
    for wk in week_keys:
        ws = _week_start_from_label(wk)
        if ws:
            out.append([0.0] * 7)
        else:
            out.append([0.0] * 7)
    return out


def build_payload(
    dbx: Any,
    country_code: str,
    month_keys: list[str],
    week_keys: list[str],
    as_of_malta: dt.date,
) -> dict[str, Any]:
    spine = query_provider_spine(dbx, country_code)
    m_start, m_end_excl = _range_dates_months(month_keys)
    w_start, w_end_excl = _range_dates_weeks(week_keys)
    daily_start = min(m_start, w_start)
    daily_end = max(m_end_excl, w_end_excl)

    gmv_m_df = query_gmv_by_month(dbx, country_code, month_keys)
    gmv_w_df = query_gmv_by_week(dbx, country_code, w_start, w_end_excl)
    daily_df = query_gmv_daily_incr(dbx, country_code, daily_start, daily_end)
    sp_df = query_sp_enrollment_summary(dbx, country_code)
    sl_df = query_sl_enrollment_summary(dbx, country_code)

    gmv_m_df = gmv_m_df.copy()
    gmv_m_df["month_key"] = gmv_m_df["month_key"].astype(str).str.slice(0, 7)

    gmv_w_df = gmv_w_df.copy()
    gmv_w_df["week_key"] = gmv_w_df["week_raw"].map(_normalize_week_key)

    mk_index = {k: i for i, k in enumerate(month_keys)}
    wk_index = {k: i for i, k in enumerate(week_keys)}

    sp_map: dict[int, dict[str, str]] = {}
    for _, r in sp_df.iterrows():
        sp_map[int(r["provider_id"])] = {
            "st": str(r["status"] or "Inactive"),
            "in": str(r["opt_in_date"] or "")[:10],
            "out": str(r["opt_out_date"] or "")[:10],
        }

    sl_map: dict[int, dict[str, str]] = {}
    for _, r in sl_df.iterrows():
        sl_map[int(r["provider_id"])] = {
            "st": str(r["status"] or "Inactive"),
            "in": str(r["opt_in_date"] or "")[:10],
            "out": str(r["opt_out_date"] or "")[:10],
        }

    n_m = len(month_keys)
    n_w = len(week_keys)
    zeros_m = [0.0] * n_m
    zeros_w = [0.0] * n_w

    per_pid_m: dict[int, list[float]] = {}
    per_pid_w: dict[int, list[float]] = {}
    per_pid_dm: dict[int, list[list[float]]] = {}
    per_pid_dw: dict[int, list[list[float]]] = {}

    for pid in spine["provider_id"].tolist():
        pid_i = int(pid)
        per_pid_m[pid_i] = zeros_m[:]
        per_pid_w[pid_i] = zeros_w[:]
        per_pid_dm[pid_i] = _empty_daily_month(month_keys)
        per_pid_dw[pid_i] = _empty_daily_week(week_keys)

    for _, r in gmv_m_df.iterrows():
        pid = int(r["provider_id"])
        mk = r["month_key"]
        if pid not in per_pid_m or mk not in mk_index:
            continue
        per_pid_m[pid][mk_index[mk]] = float(r["gmv"] or 0)

    for _, r in gmv_w_df.iterrows():
        pid = int(r["provider_id"])
        wk = r["week_key"]
        if pid not in per_pid_w or wk not in wk_index:
            continue
        per_pid_w[pid][wk_index[wk]] = float(r["gmv"] or 0)

    if daily_df is not None and not daily_df.empty:
        for _, r in daily_df.iterrows():
            pid = int(r["provider_id"])
            if pid not in per_pid_dm:
                continue
            g = float(r["gmv"] or 0)
            od_raw = str(r["order_date"] or "")[:10]
            try:
                od = dt.date.fromisoformat(od_raw)
            except ValueError:
                continue
            mk = f"{od.year:04d}-{od.month:02d}"
            if mk in mk_index:
                dom = od.day
                mi = mk_index[mk]
                if 1 <= dom <= len(per_pid_dm[pid][mi]):
                    per_pid_dm[pid][mi][dom - 1] += g
            ws = _week_start(od)
            wk = f"{ws.isocalendar().year:04d}-W{ws.isocalendar().week:02d}"
            if wk in wk_index:
                idx_d = od.weekday()
                if 0 <= idx_d < 7:
                    per_pid_dw[pid][wk_index[wk]][idx_d] += g

    rows: list[dict[str, Any]] = []
    for _, r in spine.iterrows():
        pid = int(r["provider_id"])
        sp = sp_map.get(pid, {"st": "Inactive", "in": "", "out": ""})
        sl = sl_map.get(pid, {"st": "Inactive", "in": "", "out": ""})
        rows.append(
            {
                "id": pid,
                "acct": str(r["account_name"] or ""),
                "n": str(r["provider_name"] or ""),
                "br": str(r["brand_name"] or ""),
                "sf": str(r["sf_owner"] or ""),
                "dam": str(r["dbx_am"] or ""),
                "sg": str(r["segment"] or ""),
                "st": str(r["provider_status"] or ""),
                "gm": per_pid_m.get(pid, zeros_m[:]),
                "gw": per_pid_w.get(pid, zeros_w[:]),
                "idm": per_pid_dm.get(pid, _empty_daily_month(month_keys)),
                "idw": per_pid_dw.get(pid, _empty_daily_week(week_keys)),
                "sp": sp,
                "sl": sl,
            }
        )

    owners = sorted({r["sf"] for r in rows if r["sf"]})

    return {
        "country": country_code.upper(),
        "month_keys": month_keys,
        "week_keys": week_keys,
        "as_of_malta": as_of_malta.isoformat(),
        "as_of_week": week_keys[-1] if week_keys else "",
        "as_of_month": month_keys[-1] if month_keys else "",
        "sf_owners": owners,
        "rows": rows,
    }


def _render_html(payload: dict[str, Any], generated: str) -> str:
    data_json = _json_for_script(payload)
    title = "Malta — Account Performance"
    esc_title = html_lib.escape(title)
    esc_gen = html_lib.escape(generated)
    esc_country = html_lib.escape(payload["country"])

    html_raw = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>__TITLE__</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
  <style>
    :root {
      --bg: #f4f6f9;
      --surface: #ffffff;
      --text: #1a2332;
      --muted: #64748b;
      --accent: #2563eb;
      --border: #e2e8f0;
      --up: #059669;
      --down: #dc2626;
      --up-bg: #ecfdf5;
      --down-bg: #fef2f2;
    }
    * { box-sizing: border-box; }
    body {
      font-family: "Inter", "Segoe UI", system-ui, sans-serif;
      background: var(--bg);
      color: var(--text);
      margin: 0;
      padding: 1.25rem 1.5rem 3rem;
      line-height: 1.5;
    }
    h1 { font-size: 1.5rem; font-weight: 700; margin: 0 0 0.25rem; letter-spacing: -0.02em; }
    .sub { color: var(--muted); font-size: 0.875rem; margin-bottom: 1.25rem; }
    .toolbar {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1rem 1.15rem;
      margin-bottom: 1rem;
      display: flex;
      flex-wrap: wrap;
      gap: 0.85rem 1rem;
      align-items: flex-end;
    }
    .toolbar label {
      display: flex;
      flex-direction: column;
      gap: 0.3rem;
      font-size: 0.72rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--muted);
    }
    select, input[type="text"], input[type="date"] {
      background: var(--bg);
      color: var(--text);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0.45rem 0.65rem;
      font-size: 0.875rem;
      min-width: 140px;
    }
    input[type="text"] { min-width: 180px; }
    .seg {
      display: flex;
      gap: 0;
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
    }
    .seg button {
      border: none;
      background: var(--bg);
      color: var(--muted);
      padding: 0.45rem 0.75rem;
      font-size: 0.8rem;
      font-weight: 600;
      cursor: pointer;
    }
    .seg button.active {
      background: var(--accent);
      color: #fff;
    }
    .cards {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 0.75rem;
      margin-bottom: 1rem;
    }
    .card-kpi {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 0.85rem 1rem;
    }
    .card-kpi .lbl { font-size: 0.72rem; color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.03em; }
    .card-kpi .val { font-size: 1.35rem; font-weight: 700; margin-top: 0.2rem; font-variant-numeric: tabular-nums; }
    .card-kpi .val.up { color: var(--up); }
    .card-kpi .val.down { color: var(--down); }
    .charts {
      display: grid;
      gap: 1rem;
      margin-bottom: 1rem;
    }
    @media (min-width: 1100px) {
      .charts { grid-template-columns: 2fr 1fr 1fr; }
    }
    .chart-box {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1rem;
    }
    .chart-box h3 { margin: 0 0 0.75rem; font-size: 0.9rem; font-weight: 600; }
    .chart-wrap { position: relative; height: 220px; }
    .table-wrap {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1rem;
      overflow-x: auto;
    }
    .table-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 0.75rem;
      flex-wrap: wrap;
      gap: 0.5rem;
    }
    .table-head h2 { margin: 0; font-size: 1rem; font-weight: 600; }
    .crumb { font-size: 0.8rem; color: var(--muted); }
    .crumb a { color: var(--accent); cursor: pointer; text-decoration: none; }
    .crumb a:hover { text-decoration: underline; }
    table.data {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.78rem;
    }
    table.data th, table.data td {
      border-bottom: 1px solid var(--border);
      padding: 0.5rem 0.55rem;
      text-align: left;
      vertical-align: middle;
    }
    table.data th {
      color: var(--muted);
      font-weight: 600;
      font-size: 0.7rem;
      text-transform: uppercase;
      letter-spacing: 0.03em;
      cursor: pointer;
      user-select: none;
      white-space: nowrap;
    }
    table.data th:hover { color: var(--accent); }
    table.data th.sorted { color: var(--accent); }
    table.data .num { text-align: right; font-variant-numeric: tabular-nums; }
    table.data tr.clickable { cursor: pointer; }
    table.data tr.clickable:hover { background: #f8fafc; }
    .delta-up { color: var(--up); font-weight: 600; }
    .delta-down { color: var(--down); font-weight: 600; }
    .badge {
      display: inline-block;
      padding: 0.15rem 0.45rem;
      border-radius: 999px;
      font-size: 0.68rem;
      font-weight: 600;
    }
    .badge.active { background: var(--up-bg); color: var(--up); }
    .badge.inactive { background: #f1f5f9; color: var(--muted); }
    .btn {
      background: var(--surface);
      color: var(--accent);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0.45rem 0.75rem;
      font-size: 0.8rem;
      font-weight: 600;
      cursor: pointer;
    }
    .btn:hover { border-color: var(--accent); }
    .modal-back {
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(15, 23, 42, 0.45);
      z-index: 100;
      align-items: center;
      justify-content: center;
      padding: 1rem;
    }
    .modal-back.open { display: flex; }
    .modal {
      background: var(--surface);
      border-radius: 14px;
      max-width: 720px;
      width: 100%;
      max-height: 90vh;
      overflow: auto;
      padding: 1.25rem;
      box-shadow: 0 20px 50px rgba(0,0,0,0.15);
    }
    .modal h2 { margin: 0 0 0.5rem; font-size: 1.1rem; }
    .modal .close { float: right; border: none; background: none; font-size: 1.25rem; cursor: pointer; color: var(--muted); }
    .note { font-size: 0.78rem; color: var(--muted); margin-top: 0.5rem; }
  </style>
</head>
<body>
  <h1>__TITLE__</h1>
  <p class="sub">Country: __COUNTRY__ · Generated __GEN__ · Owner from <strong>sf_account_owner_name</strong> · GMV from Databricks warehouse</p>

  <div class="toolbar">
    <label>View level
      <div class="seg" id="viewSeg">
        <button type="button" data-view="portfolio">Portfolio</button>
        <button type="button" data-view="provider" class="active">Provider</button>
        <button type="button" data-view="brand">Brand</button>
      </div>
    </label>
    <label>Comparison
      <div class="seg" id="cmpSeg">
        <button type="button" data-cmp="wow">WoW</button>
        <button type="button" data-cmp="mom" class="active">MoM</button>
        <button type="button" data-cmp="yoy">YoY</button>
      </div>
    </label>
    <label>Account manager (SF owner)
      <select id="fOwner"><option value="">All</option></select>
    </label>
    <label>Country
      <select id="fCountry"><option value="MT">Malta (MT)</option></select>
    </label>
    <label>Account / provider search
      <input type="text" id="fSearch" placeholder="Search name…" />
    </label>
    <label id="lblPeriod">Current period
      <select id="fPeriod"></select>
    </label>
    <button type="button" class="btn" id="reloadBtn" title="Reload page after re-running the Python builder">Reload data</button>
  </div>

  <p class="note" id="periodNote"></p>
  <div class="crumb" id="breadcrumb"></div>

  <div class="cards" id="kpiCards"></div>

  <div class="charts">
    <div class="chart-box">
      <h3>GMV trend</h3>
      <div class="chart-wrap"><canvas id="chartTrend"></canvas></div>
    </div>
    <div class="chart-box">
      <h3>Top growing</h3>
      <div class="chart-wrap"><canvas id="chartGrow"></canvas></div>
    </div>
    <div class="chart-box">
      <h3>Top declining</h3>
      <div class="chart-wrap"><canvas id="chartDecline"></canvas></div>
    </div>
  </div>

  <div class="table-wrap">
    <div class="table-head">
      <h2 id="tableTitle">Account performance</h2>
      <span class="note" id="rowCount"></span>
    </div>
    <table class="data" id="mainTable">
      <thead id="tableHead"></thead>
      <tbody id="tableBody"></tbody>
    </table>
  </div>

  <div class="modal-back" id="detailModal">
    <div class="modal">
      <button type="button" class="close" id="modalClose">&times;</button>
      <h2 id="modalTitle"></h2>
      <p class="note" id="modalSub"></p>
      <div class="chart-wrap" style="height:200px"><canvas id="chartDetail"></canvas></div>
      <div id="modalMeta" style="margin-top:1rem;font-size:0.85rem"></div>
    </div>
  </div>

  <script id="dash-data" type="application/json">__DATA__</script>
  <script>
const D = JSON.parse(document.getElementById('dash-data').textContent);
const MONTHS = D.month_keys;
const WEEKS = D.week_keys;
const ROWS = D.rows;
const AS_OF = D.as_of_malta || '';

const state = {
  view: 'provider',
  cmp: 'mom',
  owner: '',
  search: '',
  periodIdx: -1,
  sortKey: 'dltPct',
  sortDir: -1,
  drillOwner: '',
  drillBrand: '',
  drillProvider: null,
};

let chartTrend = null, chartGrow = null, chartDecline = null, chartDetail = null;

function esc(s) {
  const el = document.createElement('div');
  el.textContent = s == null ? '' : String(s);
  return el.innerHTML;
}

function euro(n, dec) {
  if (n == null || !isFinite(n)) return '—';
  return Number(n).toLocaleString(undefined, { maximumFractionDigits: dec == null ? 0 : dec });
}

function pct(n) {
  if (n == null || !isFinite(n)) return '—';
  const sign = n > 0 ? '+' : '';
  return sign + n.toFixed(1) + '%';
}

function daysInMonth(ym) {
  const [y, m] = ym.split('-').map(Number);
  return new Date(y, m, 0).getDate();
}

function asOfDay() {
  if (!AS_OF || AS_OF.length < 10) return 31;
  const d = parseInt(AS_OF.slice(8, 10), 10);
  return isFinite(d) ? d : 31;
}

function asOfDow() {
  if (!AS_OF) return 6;
  const p = AS_OF.split('-').map(Number);
  const dt = new Date(p[0], p[1]-1, p[2]);
  return (dt.getDay() + 6) % 7;
}

function sumArr(a, k) {
  if (!a) return 0;
  const lim = k == null ? a.length : Math.min(k, a.length);
  let s = 0;
  for (let i = 0; i < lim; i++) s += Number(a[i]) || 0;
  return s;
}

function gmvMonth(r, mi, fair) {
  const full = Number(r.gm[mi]) || 0;
  if (!fair || MONTHS[mi] !== D.as_of_month) return full;
  const inc = r.idm && r.idm[mi] ? r.idm[mi] : [];
  const k = Math.min(asOfDay(), inc.length || daysInMonth(MONTHS[mi]));
  const partial = sumArr(inc, k);
  return partial > 0 ? partial : full * k / daysInMonth(MONTHS[mi]);
}

function gmvWeek(r, wi, fair) {
  const full = Number(r.gw[wi]) || 0;
  if (!fair || WEEKS[wi] !== D.as_of_week) return full;
  const inc = r.idw && r.idw[wi] ? r.idw[wi] : [];
  const k = Math.min(asOfDow() + 1, 7);
  const partial = sumArr(inc, k);
  return partial > 0 ? partial : full * k / 7;
}

function periodIndices() {
  const cmp = state.cmp;
  let cur = state.periodIdx;
  if (cur < 0) {
    cur = cmp === 'wow' ? WEEKS.length - 1 : MONTHS.length - 1;
  }
  if (cmp === 'wow') {
    const prev = Math.max(0, cur - 1);
    return { cur, prev, fair: WEEKS[cur] === D.as_of_week, mode: 'week' };
  }
  if (cmp === 'mom') {
    const prev = Math.max(0, cur - 1);
    return { cur, prev, fair: MONTHS[cur] === D.as_of_month, mode: 'month' };
  }
  const prev = cur - 12;
  return { cur, prev, fair: MONTHS[cur] === D.as_of_month, mode: 'month' };
}

function entityGmv(entity, pi) {
  if (pi.mode === 'week') {
    return entity.rows.reduce((s, r) => s + gmvWeek(r, pi.cur, pi.fair), 0);
  }
  return entity.rows.reduce((s, r) => s + gmvMonth(r, pi.cur, pi.fair), 0);
}

function entityGmvPrev(entity, pi) {
  if (pi.prev < 0) return 0;
  if (pi.mode === 'week') {
    return entity.rows.reduce((s, r) => s + gmvWeek(r, pi.prev, pi.fair), 0);
  }
  return entity.rows.reduce((s, r) => s + gmvMonth(r, pi.prev, pi.fair), 0);
}

function filterRows() {
  let list = ROWS;
  const owner = state.drillOwner || state.owner;
  if (owner) list = list.filter(r => r.sf === owner);
  if (state.drillProvider != null) list = list.filter(r => r.id === state.drillProvider);
  if (state.drillBrand) {
    const b = state.drillBrand;
    list = list.filter(r => (r.br && r.br.trim()) ? r.br.trim() === b : '(no brand)' === b);
  }
  const q = (state.search || '').trim().toLowerCase();
  if (q) {
    list = list.filter(r =>
      (r.acct || '').toLowerCase().includes(q) ||
      (r.n || '').toLowerCase().includes(q) ||
      (r.br || '').toLowerCase().includes(q)
    );
  }
  return list;
}

function aggregateBrand(rows) {
  const by = {};
  for (const r of rows) {
    const k = (r.br && r.br.trim()) ? r.br.trim() : '(no brand)';
    if (!by[k]) by[k] = { key: k, label: k, rows: [], sf: new Set(), acct: new Set() };
    by[k].rows.push(r);
    if (r.sf) by[k].sf.add(r.sf);
    if (r.acct) by[k].acct.add(r.acct);
  }
  return Object.values(by).map(o => ({
    key: o.key,
    label: o.label,
    rows: o.rows,
    sf: [...o.sf].sort().join('; ') || '—',
    acct: [...o.acct].sort().join('; ') || '—',
    isGroup: true,
  }));
}

function aggregatePortfolio(rows) {
  const by = {};
  for (const r of rows) {
    const k = r.sf || '(unassigned)';
    if (!by[k]) by[k] = { key: k, label: k, rows: [] };
    by[k].rows.push(r);
  }
  return Object.values(by).sort((a, b) => a.label.localeCompare(b.label));
}

function aggregateProvider(rows) {
  return rows.map(r => ({
    key: String(r.id),
    label: r.n,
    rows: [r],
    sf: r.sf,
    acct: r.acct,
    isGroup: false,
    raw: r,
  }));
}

function metricsForEntity(entity) {
  const pi = periodIndices();
  const cur = entityGmv(entity, pi);
  const prev = entityGmvPrev(entity, pi);
  const dlt = cur - prev;
  const dltPct = prev ? (dlt / prev) * 100 : (cur ? 100 : 0);
  const n = entity.rows.length;
  let spA = 0, slA = 0;
  for (const r of entity.rows) {
    if (r.sp && r.sp.st === 'Active') spA++;
    if (r.sl && r.sl.st === 'Active') slA++;
  }
  return { cur, prev, dlt, dltPct, n, spA, slA, spPct: n ? (spA / n) * 100 : 0, slPct: n ? (slA / n) * 100 : 0, pi };
}

function getEntities() {
  const rows = filterRows();
  if (state.view === 'portfolio') return aggregatePortfolio(rows);
  if (state.view === 'brand') return aggregateBrand(rows);
  return aggregateProvider(rows);
}

function periodLabel(idx, mode) {
  if (mode === 'week') return WEEKS[idx] || '';
  const ym = MONTHS[idx];
  if (!ym) return '';
  const [y, m] = ym.split('-').map(Number);
  return new Date(y, m - 1, 1).toLocaleString(undefined, { month: 'short', year: 'numeric' });
}

function renderKpis(entities) {
  const pi = periodIndices();
  const providerRows = filterRows();
  let totalAccounts = providerRows.length, totalGmv = 0, totalPrev = 0, growing = 0, declining = 0, spN = 0, slN = 0;
  for (const r of providerRows) {
    const e = { rows: [r], label: r.n };
    const m = metricsForEntity(e);
    totalGmv += m.cur;
    totalPrev += m.prev;
    if (m.dlt > 0) growing++;
    if (m.dlt < 0) declining++;
    if (r.sp && r.sp.st === 'Active') spN++;
    if (r.sl && r.sl.st === 'Active') slN++;
  }
  const gPct = totalPrev ? ((totalGmv - totalPrev) / totalPrev) * 100 : 0;
  const gCls = gPct >= 0 ? 'up' : 'down';
  document.getElementById('kpiCards').innerHTML = [
    ['Total accounts', euro(totalAccounts), ''],
    ['Total GMV', '€' + euro(totalGmv), ''],
    ['GMV growth %', pct(gPct), gCls],
    ['Accounts growing', euro(growing), 'up'],
    ['Accounts declining', euro(declining), 'down'],
    ['Smart promotions', euro(spN), ''],
    ['Sponsored listings', euro(slN), ''],
  ].map(([lbl, val, cls]) =>
    `<div class="card-kpi"><div class="lbl">${esc(lbl)}</div><div class="val ${cls}">${esc(val)}</div></div>`
  ).join('');
}

function trendSeries(entities) {
  const pi = periodIndices();
  const isWeek = pi.mode === 'week';
  const keys = isWeek ? WEEKS : MONTHS;
  const tail = 12;
  const start = Math.max(0, keys.length - tail);
  const labels = [];
  const data = [];
  for (let i = start; i < keys.length; i++) {
    labels.push(isWeek ? keys[i] : periodLabel(i, 'month'));
    let s = 0;
    for (const e of entities) {
      for (const r of e.rows) {
        s += isWeek ? gmvWeek(r, i, false) : gmvMonth(r, i, false);
      }
    }
    data.push(s);
  }
  return { labels, data };
}

function topMovers(entities, n, positive) {
  const scored = entities.map(e => {
    const m = metricsForEntity(e);
    return { label: e.label, dlt: m.dlt, dltPct: m.dltPct };
  });
  scored.sort((a, b) => positive ? b.dlt - a.dlt : a.dlt - b.dlt);
  const filt = scored.filter(x => positive ? x.dlt > 0 : x.dlt < 0).slice(0, n);
  return filt;
}

function renderCharts(entities) {
  const ts = trendSeries(entities);
  const grow = topMovers(entities, 8, true);
  const dec = topMovers(entities, 8, false);

  const mk = (id, cfg) => {
    const ctx = document.getElementById(id);
    if (!ctx) return null;
    const old = id === 'chartTrend' ? chartTrend : id === 'chartGrow' ? chartGrow : chartDecline;
    if (old) old.destroy();
    return new Chart(ctx, cfg);
  };

  chartTrend = mk('chartTrend', {
    type: 'line',
    data: {
      labels: ts.labels,
      datasets: [{ label: 'GMV (€)', data: ts.data, borderColor: '#2563eb', backgroundColor: 'rgba(37,99,235,0.08)', fill: true, tension: 0.25, pointRadius: 2 }]
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { ticks: { callback: v => '€' + Number(v).toLocaleString() } } } }
  });

  chartGrow = mk('chartGrow', {
    type: 'bar',
    data: {
      labels: grow.map(x => x.label.slice(0, 22)),
      datasets: [{ label: 'Δ GMV €', data: grow.map(x => x.dlt), backgroundColor: '#059669' }]
    },
    options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } }
  });

  chartDecline = mk('chartDecline', {
    type: 'bar',
    data: {
      labels: dec.map(x => x.label.slice(0, 22)),
      datasets: [{ label: 'Δ GMV €', data: dec.map(x => x.dlt), backgroundColor: '#dc2626' }]
    },
    options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } }
  });
}

function badge(st) {
  const cls = st === 'Active' ? 'active' : 'inactive';
  return `<span class="badge ${cls}">${esc(st || 'Inactive')}</span>`;
}

function sortEntities(entities) {
  const key = state.sortKey;
  const dir = state.sortDir;
  return [...entities].sort((a, b) => {
    const ma = metricsForEntity(a);
    const mb = metricsForEntity(b);
    let va, vb;
    if (key === 'cur') { va = ma.cur; vb = mb.cur; }
    else if (key === 'dlt') { va = ma.dlt; vb = mb.dlt; }
    else if (key === 'dltPct') { va = ma.dltPct; vb = mb.dltPct; }
    else if (key === 'sp') { va = ma.spA; vb = mb.spA; }
    else if (key === 'sl') { va = ma.slA; vb = mb.slA; }
    else if (key === 'sf') { va = a.sf || a.label; vb = b.sf || b.label; return dir * String(va).localeCompare(String(vb)); }
    else if (key === 'label') { va = a.label; vb = b.label; return dir * String(va).localeCompare(String(vb)); }
    else { va = ma.dltPct; vb = mb.dltPct; }
    return dir * (va - vb);
  });
}

function renderTable(entities) {
  const sorted = sortEntities(entities);
  const pi = periodIndices();
  const isPortfolio = state.view === 'portfolio';

  let head = '';
  if (isPortfolio) {
    head = `<tr>
      <th data-k="sf">Account manager</th>
      <th class="num" data-k="n">Accounts</th>
      <th class="num" data-k="cur">Total GMV</th>
      <th class="num" data-k="dlt">GMV change €</th>
      <th class="num" data-k="dltPct">GMV change %</th>
      <th class="num" data-k="sp">SP adoption</th>
      <th class="num" data-k="sl">SL adoption</th>
      <th class="num">Growing</th>
      <th class="num">Declining</th>
    </tr>`;
  } else {
    head = `<tr>
      <th data-k="label">Account name</th>
      <th>Provider</th>
      <th>Brand</th>
      <th data-k="sf">SF owner</th>
      <th class="num" data-k="cur">Current GMV</th>
      <th class="num">Previous GMV</th>
      <th class="num" data-k="dlt">GMV change €</th>
      <th class="num" data-k="dltPct">GMV change %</th>
      <th data-k="sp">Smart promo</th>
      <th>SP opt-in</th>
      <th>SP opt-out</th>
      <th data-k="sl">Sponsored listings</th>
      <th>SL opt-in</th>
      <th>SL opt-out</th>
    </tr>`;
  }
  document.getElementById('tableHead').innerHTML = head;
  document.querySelectorAll('#tableHead th[data-k]').forEach(th => {
    if (th.dataset.k === state.sortKey) th.classList.add('sorted');
    th.addEventListener('click', () => {
      const k = th.dataset.k;
      if (state.sortKey === k) state.sortDir *= -1;
      else { state.sortKey = k; state.sortDir = -1; }
      refresh();
    });
  });

  const body = sorted.map(e => {
    const m = metricsForEntity(e);
    const dCls = m.dlt >= 0 ? 'delta-up' : 'delta-down';
    if (isPortfolio) {
      let grow = 0, dec = 0;
      for (const r of e.rows) {
        const sub = metricsForEntity({ rows: [r], label: r.n });
        if (sub.dlt > 0) grow++;
        if (sub.dlt < 0) dec++;
      }
      return `<tr class="clickable" data-owner="${esc(e.key)}">
        <td><strong>${esc(e.label)}</strong></td>
        <td class="num">${m.n}</td>
        <td class="num">€${euro(m.cur)}</td>
        <td class="num ${dCls}">€${euro(m.dlt)}</td>
        <td class="num ${dCls}">${pct(m.dltPct)}</td>
        <td class="num">${m.spA} (${pct(m.spPct).replace('+','')})</td>
        <td class="num">${m.slA} (${pct(m.slPct).replace('+','')})</td>
        <td class="num delta-up">${grow}</td>
        <td class="num delta-down">${dec}</td>
      </tr>`;
    }
    const r = e.raw || e.rows[0];
    const isBrand = state.view === 'brand';
    let spSt = r.sp ? r.sp.st : 'Inactive';
    let slSt = r.sl ? r.sl.st : 'Inactive';
    let spIn = (r.sp && r.sp.in) || '—';
    let slIn = (r.sl && r.sl.in) || '—';
    let spOut = (r.sp && r.sp.out) || '—';
    let slOut = (r.sl && r.sl.out) || '—';
    if (isBrand && e.rows.length > 1) {
      spSt = m.spA > 0 ? 'Active (' + m.spA + '/' + m.n + ')' : 'Inactive';
      slSt = m.slA > 0 ? 'Active (' + m.slA + '/' + m.n + ')' : 'Inactive';
      spIn = m.spA + ' active';
      slIn = m.slA + ' active';
      spOut = '—';
      slOut = '—';
    }
    return `<tr class="clickable" data-id="${isBrand ? '' : r.id}" data-brand="${esc(e.key)}" data-acct="${esc(r.acct || e.acct)}">
      <td>${esc(isBrand ? e.label : (r.acct || e.acct || '—'))}</td>
      <td>${esc(isBrand ? (m.n + ' providers') : r.n)}</td>
      <td>${esc(isBrand ? e.label : (r.br || '—'))}</td>
      <td>${esc(r.sf || e.sf || '—')}</td>
      <td class="num">€${euro(m.cur)}</td>
      <td class="num">€${euro(m.prev)}</td>
      <td class="num ${dCls}">€${euro(m.dlt)}</td>
      <td class="num ${dCls}">${pct(m.dltPct)}</td>
      <td>${isBrand ? esc(spSt) : badge(spSt)}</td>
      <td>${esc(spIn)}</td>
      <td>${esc(spOut)}</td>
      <td>${isBrand ? esc(slSt) : badge(slSt)}</td>
      <td>${esc(slIn)}</td>
      <td>${esc(slOut)}</td>
    </tr>`;
  }).join('');

  document.getElementById('tableBody').innerHTML = body || '<tr><td colspan="15">No rows match filters</td></tr>';
  document.getElementById('rowCount').textContent = sorted.length + ' rows';

  document.querySelectorAll('#tableBody tr.clickable').forEach(tr => {
    tr.addEventListener('click', () => {
      if (state.view === 'portfolio' && tr.dataset.owner) {
        state.drillOwner = tr.dataset.owner;
        state.view = 'provider';
        document.querySelectorAll('#viewSeg button').forEach(b => b.classList.toggle('active', b.dataset.view === 'provider'));
        refresh();
        return;
      }
      if (state.view === 'provider' && tr.dataset.brand) {
        state.drillBrand = tr.dataset.brand;
        state.view = 'brand';
        document.querySelectorAll('#viewSeg button').forEach(b => b.classList.toggle('active', b.dataset.view === 'brand'));
        refresh();
        return;
      }
      openDetail(tr.dataset.acct || tr.dataset.brand || '', tr.dataset.id);
    });
  });
}

function openDetail(label, id) {
  let rows = filterRows();
  if (id) rows = rows.filter(r => String(r.id) === String(id));
  else if (label) rows = rows.filter(r => (r.acct || r.br || r.n) === label || (r.br && r.br.trim() === label));
  if (!rows.length && state.drillBrand) rows = filterRows().filter(r => (r.br && r.br.trim()) ? r.br.trim() === state.drillBrand : state.drillBrand === '(no brand)');
  if (!rows.length) return;
  const entity = { rows, label: label || rows[0].n };
  const m = metricsForEntity(entity);
  const pi = periodIndices();
  document.getElementById('modalTitle').textContent = label || rows[0].n;
  document.getElementById('modalSub').textContent =
    `${rows.length} provider(s) · GMV ${periodLabel(pi.cur, pi.mode)}: €${euro(m.cur)} (${pct(m.dltPct)})`;
  const ts = trendSeries([entity]);
  if (chartDetail) chartDetail.destroy();
  chartDetail = new Chart(document.getElementById('chartDetail'), {
    type: 'line',
    data: { labels: ts.labels, datasets: [{ label: 'GMV', data: ts.data, borderColor: '#2563eb', tension: 0.2 }] },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } }
  });
  const r0 = rows[0];
  document.getElementById('modalMeta').innerHTML = `
    <div><strong>SF owner:</strong> ${esc(r0.sf || '—')}</div>
    <div><strong>Smart promotions:</strong> ${badge(r0.sp.st)} ${esc(r0.sp.in || '')}</div>
    <div><strong>Sponsored listings:</strong> ${badge(r0.sl.st)} ${esc(r0.sl.in || '')}</div>`;
  document.getElementById('detailModal').classList.add('open');
}

function renderBreadcrumb() {
  const parts = [];
  parts.push(`<a data-crumb="root">Portfolio overview</a>`);
  if (state.drillOwner) parts.push(`<span> → </span><a data-crumb="owner">${esc(state.drillOwner)}</a>`);
  if (state.drillBrand) parts.push(`<span> → </span><span>${esc(state.drillBrand)}</span>`);
  document.getElementById('breadcrumb').innerHTML = parts.join('');
  document.querySelectorAll('[data-crumb]').forEach(a => {
    a.addEventListener('click', () => {
      if (a.dataset.crumb === 'root') {
        state.drillOwner = '';
        state.drillBrand = '';
        state.drillProvider = null;
        state.view = 'portfolio';
        document.querySelectorAll('#viewSeg button').forEach(b => b.classList.toggle('active', b.dataset.view === 'portfolio'));
      } else if (a.dataset.crumb === 'owner') {
        state.drillBrand = '';
        state.drillProvider = null;
        state.view = 'provider';
        document.querySelectorAll('#viewSeg button').forEach(b => b.classList.toggle('active', b.dataset.view === 'provider'));
      }
      refresh();
    });
  });
}

function fillPeriodSelect() {
  const sel = document.getElementById('fPeriod');
  const cmp = state.cmp;
  const isWeek = cmp === 'wow';
  const keys = isWeek ? WEEKS : MONTHS;
  document.getElementById('lblPeriod').firstChild.textContent = isWeek ? 'Current week ' : 'Current month ';
  sel.innerHTML = keys.map((k, i) => {
    const lab = isWeek ? k : periodLabel(i, 'month') + ' (' + k + ')';
    return `<option value="${i}">${esc(lab)}</option>`;
  }).join('');
  sel.value = String(state.periodIdx >= 0 ? state.periodIdx : keys.length - 1);
}

function refresh() {
  fillPeriodSelect();
  state.periodIdx = parseInt(document.getElementById('fPeriod').value, 10);
  state.owner = document.getElementById('fOwner').value;
  state.search = document.getElementById('fSearch').value;

  const pi = periodIndices();
  const prevOk = pi.prev >= 0;
  let note = `Comparing ${periodLabel(pi.cur, pi.mode)} vs ${prevOk ? periodLabel(pi.prev, pi.mode) : '—'} (${state.cmp.toUpperCase()})`;
  if (pi.fair) note += ' · Partial current period adjusted to elapsed days';
  document.getElementById('periodNote').textContent = note;

  const titles = { portfolio: 'Portfolio performance', provider: 'Provider performance', brand: 'Brand performance' };
  document.getElementById('tableTitle').textContent = titles[state.view] || 'Performance';

  const entities = getEntities();
  renderBreadcrumb();
  renderKpis(entities);
  renderCharts(entities);
  renderTable(entities);
}

(function init() {
  const ownerSel = document.getElementById('fOwner');
  (D.sf_owners || []).forEach(o => {
    const opt = document.createElement('option');
    opt.value = o;
    opt.textContent = o;
    ownerSel.appendChild(opt);
  });

  document.querySelectorAll('#viewSeg button').forEach(btn => {
    btn.addEventListener('click', () => {
      state.view = btn.dataset.view;
      document.querySelectorAll('#viewSeg button').forEach(b => b.classList.toggle('active', b === btn));
      if (state.view === 'portfolio') {
        state.drillOwner = '';
        state.drillBrand = '';
      }
      refresh();
    });
  });

  document.querySelectorAll('#cmpSeg button').forEach(btn => {
    btn.addEventListener('click', () => {
      state.cmp = btn.dataset.cmp;
      state.periodIdx = -1;
      document.querySelectorAll('#cmpSeg button').forEach(b => b.classList.toggle('active', b === btn));
      refresh();
    });
  });

  ['fOwner', 'fPeriod'].forEach(id => document.getElementById(id).addEventListener('change', refresh));
  document.getElementById('fSearch').addEventListener('input', refresh);
  document.getElementById('reloadBtn').addEventListener('click', () => window.location.reload());
  document.getElementById('modalClose').addEventListener('click', () => document.getElementById('detailModal').classList.remove('open'));
  document.getElementById('detailModal').addEventListener('click', e => {
    if (e.target.id === 'detailModal') document.getElementById('detailModal').classList.remove('open');
  });

  refresh();
})();
  </script>
</body>
</html>
"""
    return (
        html_raw.replace("__TITLE__", esc_title)
        .replace("__COUNTRY__", esc_country)
        .replace("__GEN__", esc_gen)
        .replace("__DATA__", data_json)
    )


def default_output_path() -> str:
    return bolt_food_output_path("mt_account_performance.html")


def main() -> int:
    ap = argparse.ArgumentParser(description="Malta Account Performance Dashboard (Databricks → HTML)")
    ap.add_argument("--country", default="mt", help="Country code (default: mt)")
    ap.add_argument(
        "--end-month",
        default=dt.datetime.now(_MALTA_TZ).strftime("%Y-%m"),
        metavar="YYYY-MM",
        help="Newest month in payload (default: current Malta month)",
    )
    ap.add_argument("--history-months", type=int, default=24, help="Months of GMV history (default: 24)")
    ap.add_argument("--history-weeks", type=int, default=52, help="Weeks of GMV history (default: 52)")
    ap.add_argument("-o", "--output", default="", help="Output HTML path")
    args = ap.parse_args()

    if args.history_months < 2:
        print("--history-months must be >= 2", file=sys.stderr)
        return 1
    if args.history_weeks < 2:
        print("--history-weeks must be >= 2", file=sys.stderr)
        return 1

    try:
        month_keys = month_series_ending(args.end_month.strip(), args.history_months)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1

    as_of_mt = dt.datetime.now(_MALTA_TZ).date()
    week_keys = week_series_ending(as_of_mt, args.history_weeks)

    _ensure_dbx_on_path()
    from dbx import DBX  # noqa: E402

    gen = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    cc = args.country.lower().strip()

    print("Querying Databricks…", file=sys.stderr)
    with DBX() as dbx:
        payload = build_payload(dbx, cc, month_keys, week_keys, as_of_mt)

    out = args.output.strip() or default_output_path()
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(_render_html(payload, gen))
    print(out)
    print(f"Providers: {len(payload['rows'])} · Owners: {len(payload['sf_owners'])}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
