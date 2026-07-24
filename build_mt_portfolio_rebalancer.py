#!/usr/bin/env python3
"""
Malta AM portfolio rebalancer — drag brands between account managers and see totals update live.

Brand-level moves only (all providers under a brand move together).
Moved brands are highlighted; reset and export supported.

Data: ng_delivery_spark.dim_provider_v2 (Malta, TEAM_AMS).

Output default: ~/Documents/Bolt food/mt_portfolio_rebalancer.html
Boltable: pushes to https://mt-portfolio-rebalancer.boltable.eu after each build (use --no-deploy to skip).

Usage:
  python3 build_mt_portfolio_rebalancer.py
  python3 build_mt_portfolio_rebalancer.py -o ~/Documents/Bolt\\ food/mt_portfolio_rebalancer.html
  python3 build_mt_portfolio_rebalancer.py --no-deploy
"""

from __future__ import annotations

import argparse
import calendar
import datetime as dt
import html as html_lib
import json
import os
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

_MALTA_TZ = ZoneInfo("Europe/Malta")
GMV_MONTHS = 6

_ROOT = os.path.dirname(os.path.abspath(__file__))

TEAM_AMS = [
    "Alena Tokareva",
    "Gulcin Erguven",
    "Mariem Slimen",
    "Rico Spagnol",
    "Fiona Borg",
    "Yousef Moungad",
]

AM_META: dict[str, dict[str, str]] = {
    "Alena Tokareva": {"slug": "alena", "role_segment": "ENT"},
    "Gulcin Erguven": {"slug": "gulcin", "role_segment": "MM"},
    "Mariem Slimen": {"slug": "mariem", "role_segment": "MM"},
    "Rico Spagnol": {"slug": "rico", "role_segment": "MM"},
    "Fiona Borg": {"slug": "fiona", "role_segment": "MM / Retail"},
    "Yousef Moungad": {"slug": "yousef", "role_segment": "MM"},
}

# Extra board columns (not in Databricks AM list); start empty until brands are moved in.
EXTRA_AM_COLUMNS: list[dict[str, str]] = [
    {"name": "Cognisant", "slug": "cognisant", "role_segment": "Outsourced AM"},
]

# Dashboard + preset treat these brand_keys as MM (align with Salesforce target segment).
# SF field: Account.Account_Management_Segment__c = 'Mid-market (AM Segment)'
# Extra lists loaded from Context/malta/smb_above_median_mm_overrides.json (Jun 2026).
_MM_OVERRIDE_BASE_BRAND_KEYS = frozenset(
    {
        "MCSIMS PASTIZZERIA",
        "KOZA DUMPLINGS",
        "HUNGRY JAKE",
        "JEFF'S PASTIZZERIA",
        "MCSIMS",
        "SPHINX",
        "SPHINX PASTIZZERIA",
        "RUNWAYS EDGE",
        "SMASH DADDY",
    }
)

_MM_OVERRIDE_BASE_PROVIDER_IDS = frozenset(
    {
        12947,  # Hungry Jake
        99850,  # Jeff's Pastizzeria Imsida
        146977,  # Jeff's Pastizzeria Zabbar
        163581,  # Koza Dumplings Marsascala
        139922,  # McSims San Pawl il-Bahar
        163236,  # McSims Pastizzeria Fgura
        133853,  # McSims Santa Hamrun
        129136,  # Runways Edge
        121069,  # Smash Daddy
        142501,  # Sphinx Mellieha
        123751,  # Sphinx Pastizzeria Birkirkara
    }
)


def _mm_override_manifest_path() -> str:
    return os.path.join(_ROOT, "Context", "malta", "smb_above_median_mm_overrides.json")


def _load_mm_override_sets() -> tuple[frozenset[str], frozenset[int]]:
    brand_keys = set(_MM_OVERRIDE_BASE_BRAND_KEYS)
    provider_ids = set(_MM_OVERRIDE_BASE_PROVIDER_IDS)
    path = _mm_override_manifest_path()
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for key in data.get("brand_keys") or []:
            if key:
                brand_keys.add(str(key).upper())
        for pid in data.get("provider_ids") or []:
            try:
                provider_ids.add(int(pid))
            except (TypeError, ValueError):
                pass
    sf_csv = os.path.expanduser("~/Documents/Bolt food/sf_smb_to_mm_changes.csv")
    if os.path.isfile(sf_csv):
        import csv

        with open(sf_csv, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("brand_key"):
                    brand_keys.add(str(row["brand_key"]).upper())
    return frozenset(brand_keys), frozenset(provider_ids)


MM_BRAND_KEYS, MM_PROVIDER_IDS = _load_mm_override_sets()

SEGMENT_SHORT = {
    "Enterprise (AM Segment)": "ENT",
    "Mid-market (AM Segment)": "MM",
    "SMB (AM Segment)": "SMB",
    "Missing": "—",
}

# dim_provider_v2 statuses excluded from portfolio (deleted = archived in CRM)
EXCLUDED_PROVIDER_STATUSES = ("deleted",)


def _status_filter_sql(alias: str = "p") -> str:
    excluded = ", ".join(f"'{s}'" for s in EXCLUDED_PROVIDER_STATUSES)
    return f"LOWER(COALESCE({alias}.provider_status, '')) NOT IN ({excluded})"


def _ensure_dbx_on_path() -> None:
    dbx_dir = os.path.join(_ROOT, "databricks-setup")
    if dbx_dir not in sys.path:
        sys.path.insert(0, dbx_dir)


def _sql_in_str(names: list[str]) -> str:
    return ", ".join(f"'{n}'" for n in names)


def _json_for_script(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def _default_output() -> str:
    out_dir = os.path.expanduser("~/Documents/Bolt food")
    os.makedirs(out_dir, exist_ok=True)
    return os.path.join(out_dir, "mt_portfolio_rebalancer.html")


def _data_js_path(html_path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(html_path)) or ".", "data.js")


def _data_json_path(html_path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(html_path)) or ".", "data.json")


def _write_data_js(payload: dict[str, Any], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write("window.__MT_PORTFOLIO_DATA__ = ")
        f.write(_json_for_script(payload))
        f.write(";\n")


def _write_data_json(payload: dict[str, Any], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")


def _dashboard_css_path(html_path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(html_path)) or ".", "dashboard.css")


def _dashboard_js_path(html_path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(html_path)) or ".", "dashboard.js")


def _split_html_bundle(html: str) -> tuple[str, str, str]:
    import re

    css_m = re.search(r"<style>\s*(.*?)\s*</style>", html, re.S)
    if not css_m:
        raise ValueError("dashboard HTML missing <style> block")
    css = css_m.group(1).strip() + "\n"
    html = (
        html[: css_m.start()]
        + '  <link rel="stylesheet" href="dashboard.css" />\n'
        + html[css_m.end() :]
    )

    js_m = re.search(
        r'<script src="chart\.umd\.min\.js" defer></script>\s*<script>\s*(.*?)\s*</script>',
        html,
        re.S,
    )
    if not js_m:
        raise ValueError("dashboard HTML missing inline app script")
    js = js_m.group(1).strip() + "\n"
    html = (
        html[: js_m.start()]
        + '  <script src="chart.umd.min.js" defer></script>\n'
        + '  <script src="dashboard.js" defer></script>\n'
        + html[js_m.end() :]
    )

    html = html.replace(
        "<body>",
        "<body>",
        1,
    )
    html = html.replace(
        '<div id="pageLoader">Loading portfolio data…</div>',
        '<noscript><p style="color:#fca5a5">JavaScript is required for this dashboard.</p></noscript>\n'
        '  <div id="pageLoader">Loading portfolio data…</div>\n'
        '  <p id="bootStatus">Initialising…</p>',
        1,
    )
    return html, css, js


def _resolve_gh_state_token() -> str:
    """Fine-grained PAT with contents:write on boltable/mt-portfolio-rebalancer only.

    Set MT_PORTFOLIO_GH_TOKEN before rebuild — never falls back to gh auth token
    (that would embed a personal session token in public dashboard.js).
    """
    return os.environ.get("MT_PORTFOLIO_GH_TOKEN", "").strip()


def _patch_dashboard_js(js: str, gh_token: str = "") -> str:
    status_hook = (
        "function setBootStatus(msg) {\n"
        "  const el = document.getElementById('bootStatus');\n"
        "  if (el) el.textContent = msg;\n"
        "}\n\n"
    )
    if "function setBootStatus" not in js:
        js = status_hook + js

    js = js.replace(
        "async function loadPortfolioData() {\n"
        "  const res = await fetch('data.json', { cache: 'no-store' });\n"
        "  if (!res.ok) throw new Error('data.json HTTP ' + res.status);\n"
        "  return res.json();\n"
        "}",
        "async function loadPortfolioData() {\n"
        "  setBootStatus('Loading portfolio data…');\n"
        "  const embedded = document.getElementById('portfolio-data');\n"
        "  if (embedded && embedded.textContent.trim()) {\n"
        "    try {\n"
        "      return JSON.parse(embedded.textContent);\n"
        "    } catch (err) {\n"
        "      console.warn('embedded portfolio-data parse failed', err);\n"
        "    }\n"
        "  }\n"
        "  try {\n"
        "    const res = await fetch('data.json', { cache: 'no-store' });\n"
        "    if (res.ok) return res.json();\n"
        "  } catch (err) {\n"
        "    console.warn('fetch data.json failed', err);\n"
        "  }\n"
        "  if (window.__MT_PORTFOLIO_DATA__ && window.__MT_PORTFOLIO_DATA__.brands) {\n"
        "    return window.__MT_PORTFOLIO_DATA__;\n"
        "  }\n"
        "  await new Promise((resolve, reject) => {\n"
        "    const s = document.createElement('script');\n"
        "    s.src = 'data.js';\n"
        "    s.onload = () => resolve();\n"
        "    s.onerror = () => reject(new Error('data.js failed to load'));\n"
        "    document.head.appendChild(s);\n"
        "  });\n"
        "  if (!window.__MT_PORTFOLIO_DATA__) throw new Error('Portfolio data missing');\n"
        "  return window.__MT_PORTFOLIO_DATA__;\n"
        "}",
    )

    js = js.replace(
        "function showBootError(msg) {\n"
        "  const bootErr = document.getElementById('bootError');\n"
        "  if (bootErr) {\n"
        "    bootErr.style.display = 'block';\n"
        "    bootErr.textContent = msg;\n"
        "  }\n"
        "  hidePageLoader();\n"
        "}",
        "function showBootError(msg) {\n"
        "  setBootStatus(msg);\n"
        "  const bootErr = document.getElementById('bootError');\n"
        "  if (bootErr) {\n"
        "    bootErr.style.display = 'block';\n"
        "    bootErr.textContent = msg;\n"
        "  }\n"
        "  hidePageLoader();\n"
        "}",
    )

    js = js.replace(
        "function hidePageLoader() {\n"
        "  if (pageReady) return;\n"
        "  pageReady = true;\n"
        "  const loader = document.getElementById('pageLoader');\n"
        "  if (loader) loader.classList.add('hidden');\n"
        "}",
        "function hidePageLoader() {\n"
        "  if (pageReady) return;\n"
        "  pageReady = true;\n"
        "  const loader = document.getElementById('pageLoader');\n"
        "  if (loader) loader.classList.add('hidden');\n"
        "  const status = document.getElementById('bootStatus');\n"
        "  if (status) status.style.display = 'none';\n"
        "}",
    )

    js = js.replace(
        "if (document.readyState === 'loading') {\n"
        "  document.addEventListener('DOMContentLoaded', () => { boot(); });\n"
        "} else {\n"
        "  boot();\n"
        "}",
        "document.addEventListener('DOMContentLoaded', () => { boot(); });\n",
    )
    js = js.replace("__GH_STATE_TOKEN__", json.dumps(gh_token))
    return js


def _write_dashboard_bundle(html: str, out_html: str, gh_token: str = "") -> tuple[str, str]:
    html, css, js = _split_html_bundle(html)
    css_path = _dashboard_css_path(out_html)
    js_path = _dashboard_js_path(out_html)
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(html)
    with open(css_path, "w", encoding="utf-8") as f:
        f.write(css)
    with open(js_path, "w", encoding="utf-8") as f:
        f.write(_patch_dashboard_js(js, gh_token))
    return css_path, js_path


def _boltable_index_path() -> str:
    return os.path.join(_ROOT, "boltable", "mt-portfolio-rebalancer", "public", "index.html")


def _local_site_dir() -> str:
    return os.path.expanduser("~/Documents/Bolt food/mt-portfolio-site")


def _chart_js_path() -> str:
    return os.path.join(_ROOT, "boltable", "mt-portfolio-rebalancer", "public", "chart.umd.min.js")


def _render_boltable_index(monolith_html: str, payload: dict[str, Any], gh_token: str = "") -> str:
    import re

    js_m = re.search(
        r'<script src="chart\.umd\.min\.js" defer></script>\s*<script>\s*(.*?)\s*</script>',
        monolith_html,
        re.S,
    )
    if not js_m:
        raise ValueError("dashboard HTML missing inline app script")
    js = _patch_dashboard_js(js_m.group(1).strip(), gh_token)
    data_tag = (
        f'  <script type="application/json" id="portfolio-data">{_json_for_script(payload)}</script>\n'
    )
    scripts = (
        f"{data_tag}"
        '  <script src="chart.umd.min.js" defer></script>\n'
        f"  <script>\n{js}\n  </script>\n"
    )
    out = monolith_html[: js_m.start()] + scripts + monolith_html[js_m.end() :]
    out = out.replace(
        "<body>",
        "<body>",
        1,
    )
    out = out.replace(
        '<div id="pageLoader">Loading portfolio data…</div>',
        '<noscript><p style="color:#fca5a5">JavaScript is required for this dashboard.</p></noscript>\n'
        '  <div id="pageLoader">Loading portfolio data…</div>\n'
        '  <p id="bootStatus">Initialising…</p>',
        1,
    )
    return out


def _write_local_site(
    split_html: str,
    css_path: str,
    js_path: str,
    data_json_path: str,
) -> str:
    site_dir = _local_site_dir()
    os.makedirs(site_dir, exist_ok=True)
    shutil.copy2(split_html, os.path.join(site_dir, "index.html"))
    shutil.copy2(css_path, os.path.join(site_dir, "dashboard.css"))
    shutil.copy2(js_path, os.path.join(site_dir, "dashboard.js"))
    shutil.copy2(data_json_path, os.path.join(site_dir, "data.json"))
    moves_state = _moves_state_json_path()
    if os.path.isfile(moves_state):
        shutil.copy2(moves_state, os.path.join(site_dir, "moves-state.json"))
    chart_src = _chart_js_path()
    if os.path.isfile(chart_src):
        shutil.copy2(chart_src, os.path.join(site_dir, "chart.umd.min.js"))
    return site_dir


def _shift_month(y: int, m: int, delta: int) -> tuple[int, int]:
    idx = y * 12 + (m - 1) + delta
    ny, nm0 = divmod(idx, 12)
    return ny, nm0 + 1


def month_keys_last_n(n: int, as_of: dt.date | None = None) -> list[str]:
    """YYYY-MM labels oldest → newest, ending at as_of calendar month."""
    d = as_of or dt.datetime.now(_MALTA_TZ).date()
    out: list[str] = []
    for k in range(n - 1, -1, -1):
        yy, mm = _shift_month(d.year, d.month, -k)
        out.append(f"{yy:04d}-{mm:02d}")
    return out


def _month_partition(ym: str) -> str:
    return f"{ym}-01"


def gmv_period_label(month_keys: list[str]) -> str:
    if not month_keys:
        return ""
    first = month_keys[0]
    last = month_keys[-1]
    fy, fm = map(int, first.split("-"))
    ly, lm = map(int, last.split("-"))
    fmon = calendar.month_abbr[fm]
    lmon = calendar.month_abbr[lm]
    if first == last:
        return f"{fmon} {fy}"
    if fy == ly:
        return f"{fmon}–{lmon} {fy}"
    return f"{fmon} {fy}–{lmon} {ly}"


def query_team_gmv_by_month(
    dbx: Any, country_code: str, month_keys: list[str]
) -> pd.DataFrame:
    parts_sql = ", ".join(f"DATE '{_month_partition(k)}'" for k in month_keys)
    return dbx.query(
        f"""
        SELECT
          CAST(p.provider_id AS BIGINT) AS provider_id,
          SUBSTRING(CAST(m.metric_timestamp_partition AS STRING), 1, 7) AS month_key,
          CAST(COALESCE(m.total_gmv_before_discounts_eur, 0) AS DOUBLE) AS gmv
        FROM ng_delivery_spark.dim_provider_v2 p
        INNER JOIN ng_delivery_spark.fact_provider_monthly m
          ON m.provider_id = p.provider_id
        WHERE LOWER(p.country_code) = '{country_code.lower()}'
          AND p.account_manager_name IN ({_sql_in_str(TEAM_AMS)})
          AND {_status_filter_sql("p")}
          AND m.metric_timestamp_partition IN ({parts_sql})
        """
    )


def build_gmv_by_provider(gmv_df: pd.DataFrame) -> dict[int, dict[str, float]]:
    out: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    if gmv_df is None or gmv_df.empty:
        return out
    for row in gmv_df.itertuples(index=False):
        pid = int(row.provider_id)
        month = str(row.month_key)[:7]
        out[pid][month] += float(row.gmv or 0)
    return out


def query_provider_rows(dbx: Any, country_code: str) -> pd.DataFrame:
    return dbx.query(
        f"""
        SELECT
          CAST(p.provider_id AS BIGINT) AS provider_id,
          UPPER(COALESCE(NULLIF(TRIM(p.brand_name), ''), p.provider_name, 'Unknown')) AS brand_key,
          COALESCE(NULLIF(TRIM(p.brand_name), ''), p.provider_name, 'Unknown') AS brand_name,
          COALESCE(p.account_manager_name, '') AS am,
          COALESCE(NULLIF(TRIM(p.business_segment_v2), ''), 'Missing') AS segment,
          COALESCE(NULLIF(TRIM(p.business_subsegment_v2), ''), '') AS subsegment,
          NULLIF(TRIM(p.group_name), '') AS group_name,
          LOWER(COALESCE(p.provider_status, '')) AS provider_status
        FROM ng_delivery_spark.dim_provider_v2 p
        WHERE LOWER(p.country_code) = '{country_code.lower()}'
          AND p.account_manager_name IN ({_sql_in_str(TEAM_AMS)})
          AND {_status_filter_sql("p")}
        """
    )


def _segment_label(segment: str, subsegment: str) -> str:
    short = SEGMENT_SHORT.get(segment, segment)
    if segment == "Enterprise (AM Segment)" and subsegment:
        if "International" in subsegment:
            return "ENT · Int'l"
        if "National" in subsegment:
            return "ENT · National"
    return short


def build_brand_payload(
    df: pd.DataFrame,
    gmv_by_provider: dict[int, dict[str, float]],
    month_keys: list[str],
) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for row in df.itertuples(index=False):
        key = (str(row.brand_key), str(row.am))
        if key not in buckets:
            buckets[key] = {
                "brand_key": str(row.brand_key),
                "brand_name": str(row.brand_name),
                "original_am": str(row.am),
                "provider_ids": set(),
                "group_names": set(),
                "segments": defaultdict(int),
                "provider_segment": {},
                "statuses": defaultdict(int),
            }
        b = buckets[key]
        pid = int(row.provider_id)
        b["provider_ids"].add(pid)
        if row.group_name:
            b["group_names"].add(str(row.group_name))
        segment_raw = str(row.segment)
        if _is_mm_brand_key(str(row.brand_key)) or _is_mm_provider(pid):
            segment_raw = "Mid-market (AM Segment)"
        seg_lbl = _segment_label(segment_raw, str(row.subsegment or ""))
        b["segments"][seg_lbl] += 1
        b["provider_segment"][pid] = seg_lbl
        status = str(row.provider_status or "").strip().lower() or "unknown"
        b["statuses"][status] += 1

    brands: list[dict[str, Any]] = []
    for i, ((_, _), b) in enumerate(sorted(buckets.items(), key=lambda x: (-len(x[1]["provider_ids"]), x[1]["brand_name"].lower()))):
        segs = dict(b["segments"])
        statuses = dict(b["statuses"])
        primary_segment = max(segs, key=segs.get) if segs else "—"
        primary_status = max(statuses, key=statuses.get) if statuses else "—"
        if len(statuses) > 1:
            primary_status = "mixed"
        gmv_by_month: dict[str, float] = {mk: 0.0 for mk in month_keys}
        segment_gmv: dict[str, float] = defaultdict(float)
        for pid in b["provider_ids"]:
            prov_months = gmv_by_provider.get(pid, {})
            prov_total = 0.0
            for mk in month_keys:
                val = float(prov_months.get(mk, 0) or 0)
                gmv_by_month[mk] += val
                prov_total += val
            segment_gmv[b["provider_segment"].get(pid, primary_segment)] += prov_total
        gmv_total = round(sum(gmv_by_month.values()), 2)
        sorted_groups = sorted(b["group_names"])
        primary_group = sorted_groups[0] if len(sorted_groups) == 1 else (
            sorted_groups[0] if sorted_groups else ""
        )
        brands.append(
            {
                "id": f"b{i}",
                "brand_key": b["brand_key"],
                "brand_name": b["brand_name"],
                "original_am": b["original_am"],
                "provider_ids": sorted(b["provider_ids"]),
                "providers": len(b["provider_ids"]),
                "groups": len(b["group_names"]),
                "group_names": sorted_groups,
                "primary_group": primary_group,
                "segments": segs,
                "primary_segment": primary_segment,
                "statuses": statuses,
                "primary_status": primary_status,
                "gmv_total": gmv_total,
                "gmv_by_month": {mk: round(gmv_by_month[mk], 2) for mk in month_keys},
                "segment_gmv": {k: round(v, 2) for k, v in segment_gmv.items()},
            }
        )

    group_members: dict[str, list[str]] = defaultdict(list)
    for brand in brands:
        pg = brand["primary_group"]
        if pg:
            gk = f"{pg}|||{brand['original_am']}"
        else:
            gk = f"__solo_{brand['id']}"
        brand["group_key"] = gk
        group_members[gk].append(brand["id"])

    return brands, dict(group_members)


def _is_mm_brand_key(brand_key: str) -> bool:
    return (brand_key or "").upper() in MM_BRAND_KEYS


def _is_mm_provider(provider_id: int) -> bool:
    return int(provider_id) in MM_PROVIDER_IDS


def _is_smb_brand(brand: dict[str, Any]) -> bool:
    return bool((brand.get("segments") or {}).get("SMB"))


def _is_mm_brand(brand: dict[str, Any]) -> bool:
    """Any MM provider or explicit SF override — never route as SMB."""
    return bool((brand.get("segments") or {}).get("MM")) or _is_mm_brand_key(
        brand.get("brand_key", "")
    )


def _is_pure_smb_brand(brand: dict[str, Any]) -> bool:
    return _is_smb_brand(brand) and not _is_mm_brand(brand)


def _is_mm_only_brand(brand: dict[str, Any]) -> bool:
    return _is_mm_brand(brand) and not _is_smb_brand(brand)


def _is_mm_for_balance(brand: dict[str, Any]) -> bool:
    return _is_mm_brand(brand)


def _is_pastizzeria_brand(brand: dict[str, Any]) -> bool:
    """Pastizzeria / pizzeria (incl. common typos) — policy: MM on Rico."""
    name = (brand.get("brand_name") or brand.get("brand_key") or "").lower()
    return (
        "pastizzeria" in name
        or "pastitseria" in name
        or "pastizzerr" in name
        or "pizzeria" in name
    )


def _reclassify_brand_as_mm(brand: dict[str, Any]) -> None:
    prov = int(brand.get("providers") or 1)
    gmv = float(brand.get("gmv_total") or 0)
    brand["segments"] = {"MM": prov}
    brand["primary_segment"] = "MM"
    brand["segment_gmv"] = {"MM": gmv}


def _apply_mm_brand_key_overrides(payload: dict[str, Any]) -> None:
    """Align dashboard segment with Salesforce when Databricks/SF disagree."""
    for brand in payload["brands"]:
        if _is_mm_brand_key(brand.get("brand_key", "")):
            _reclassify_brand_as_mm(brand)


def _apply_mm_provider_overrides(payload: dict[str, Any]) -> None:
    """Reclassify brands with SF-updated provider IDs (works on cached data.json too)."""
    for brand in payload["brands"]:
        if _is_mm_brand_key(brand.get("brand_key", "")):
            continue
        pids = [int(x) for x in (brand.get("provider_ids") or [])]
        if not pids:
            continue
        mm_pids = [pid for pid in pids if _is_mm_provider(pid)]
        if not mm_pids:
            continue
        smb_count = len(pids) - len(mm_pids)
        if smb_count <= 0:
            _reclassify_brand_as_mm(brand)
            continue
        gmv = float(brand.get("gmv_total") or 0)
        brand["segments"] = {"MM": len(mm_pids), "SMB": smb_count}
        brand["primary_segment"] = "MM"
        seg_gmv = brand.get("segment_gmv") or {}
        if seg_gmv:
            mm_share = len(mm_pids) / len(pids)
            brand["segment_gmv"] = {
                "MM": round(gmv * mm_share, 2),
                "SMB": round(gmv * (1 - mm_share), 2),
            }


def _apply_preset_mm_reclassify(payload: dict[str, Any]) -> None:
    preset = payload.get("preset") or {}
    ids = set(preset.get("mm_reclassify") or [])
    for brand in payload["brands"]:
        if brand["id"] in ids or _is_mm_brand_key(brand.get("brand_key", "")):
            _reclassify_brand_as_mm(brand)


def _smb_to_mm_upgrade_brand_keys() -> frozenset[str]:
    """Brand keys promoted SMB → MM (manifest + active SF pending list)."""
    keys = set(MM_BRAND_KEYS) - set(_MM_OVERRIDE_BASE_BRAND_KEYS)
    sf_csv = os.path.expanduser("~/Documents/Bolt food/sf_smb_to_mm_changes.csv")
    if os.path.isfile(sf_csv):
        import csv

        with open(sf_csv, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("brand_key"):
                    keys.add(str(row["brand_key"]).upper())
    return frozenset(keys)


def _compute_smb_to_mm_portfolio_placements(
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    """SMB→MM upgrades: segment MM in dashboard; keep each brand on its current AM."""
    upgrade_keys = _smb_to_mm_upgrade_brand_keys()
    incoming = [
        b for b in payload["brands"] if (b.get("brand_key") or "").upper() in upgrade_keys
    ]
    rows: list[dict[str, Any]] = []
    for b in sorted(incoming, key=lambda x: -(float(x.get("gmv_total") or 0))):
        orig = b["original_am"]
        gmv = float(b.get("gmv_total") or 0)
        rows.append(
            {
                "id": b["id"],
                "brand_key": b.get("brand_key"),
                "brand_name": b.get("brand_name"),
                "gmv_6m_eur": round(gmv, 2),
                "providers": int(b.get("providers") or 0),
                "current_am": orig,
                "suggested_am": orig,
                "segment": "MM",
                "rationale": "MM segment upgrade — stay on current AM (no Rico removals)",
                "portfolio_move": False,
            }
        )
    return rows


def _apply_smb_to_mm_portfolio_placements(payload: dict[str, Any]) -> str:
    """Export placements CSV + embed metadata only — do not change preset assignments."""
    rows = _compute_smb_to_mm_portfolio_placements(payload)
    payload["smb_to_mm_portfolio"] = rows
    return _write_smb_to_mm_placements_csv(rows)


def _write_smb_to_mm_placements_csv(rows: list[dict[str, Any]]) -> str:
    import csv

    out_dir = os.path.expanduser("~/Documents/Bolt food")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "sf_smb_to_mm_portfolio_placements.csv")
    fields = [
        "brand_key",
        "brand_name",
        "gmv_6m_eur",
        "providers",
        "current_am",
        "suggested_am",
        "segment",
        "portfolio_move",
        "rationale",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in sorted(rows, key=lambda r: -(r.get("gmv_6m_eur") or 0)):
            w.writerow({k: row.get(k, "") for k in fields})
        f.write("\n")
    return path


def _rico_book_locked(brand: dict[str, Any]) -> bool:
    """Rico's book stays intact for MM / SMB ≥€1k. Pure SMB <€1k may leave to Cognisant."""
    return brand.get("original_am") == "Rico Spagnol"


def _rico_smb_u1k_to_cognisant_ok(brand: dict[str, Any]) -> bool:
    """Allow Rico-original pure SMB under €1k 6m GMV to Cognisant (→ Kimberley in SF)."""
    if not _rico_book_locked(brand):
        return False
    if not _is_pure_smb_brand(brand):
        return False
    if _pim_cognisant_blocked(brand):
        return False
    return float(brand.get("gmv_total") or 0) < 1000.0


SF_DEFAULT_ORG = "duncan.calleja@bolt.eu"

_PIM_INDEX: dict[str, Any] | None = None


def _load_fiona_pim_brand_keys() -> frozenset[str]:
    path = os.path.join(_ROOT, "Context", "malta", "fiona_pim_brand_keys.json")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return frozenset(str(k).strip().upper() for k in (data.get("brand_keys") or []) if k)
    cached = os.path.join(_ROOT, "Context", "malta", "fiona_pim_sf_accounts.json")
    if os.path.isfile(cached):
        with open(cached, encoding="utf-8") as f:
            data = json.load(f)
        return frozenset(str(k).strip().upper() for k in (data.get("brand_keys") or []) if k)
    return frozenset()


def _sf_parent_brand_key(parent_name: str | None) -> str:
    if not parent_name:
        return ""
    return re.sub(r"\s+", " ", str(parent_name).split("|")[0].strip().upper())


def _is_sf_pim_record(rec: dict[str, Any]) -> bool:
    return bool(rec.get("Should_Display_SKU_in_Provider_App__c")) or (
        rec.get("Menu_Link_Status__c") == "Menu Management"
    )


def _sf_query_mt_pim_accounts(target_org: str = SF_DEFAULT_ORG) -> list[dict[str, Any]]:
    soql = (
        "SELECT Id, Name, Provider_Id__c, Should_Display_SKU_in_Provider_App__c, "
        "Menu_Link_Status__c, Parent.Name "
        "FROM Account "
        "WHERE City_Id__c = 324 AND Provider_Id__c != null "
        "AND (Should_Display_SKU_in_Provider_App__c = true "
        "OR Menu_Link_Status__c = 'Menu Management')"
    )
    r = subprocess.run(
        [
            "npx",
            "-y",
            "@salesforce/cli",
            "data",
            "query",
            "--query",
            soql,
            "--target-org",
            target_org,
            "--all-rows",
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=_ROOT,
    )
    if r.returncode != 0:
        raise RuntimeError(f"SF PIM query failed: {(r.stderr or r.stdout)[:800]}")
    data = json.loads(r.stdout)
    return list(data.get("result", {}).get("records") or [])


def _load_pim_sf_accounts_json() -> dict[str, Any] | None:
    path = os.path.join(_ROOT, "Context", "malta", "fiona_pim_sf_accounts.json")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_pim_sf_accounts_json(data: dict[str, Any]) -> None:
    path = os.path.join(_ROOT, "Context", "malta", "fiona_pim_sf_accounts.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _build_pim_index_from_accounts(records: list[dict[str, Any]], source: str) -> dict[str, Any]:
    accounts: list[dict[str, Any]] = []
    brand_keys: set[str] = set()
    provider_ids: set[int] = set()
    for rec in records:
        if not _is_sf_pim_record(rec):
            continue
        pid_raw = rec.get("Provider_Id__c")
        if pid_raw is None:
            continue
        pid = int(pid_raw)
        parent = rec.get("Parent")
        parent_name = parent.get("Name") if isinstance(parent, dict) else None
        pk = _sf_parent_brand_key(parent_name)
        accounts.append(
            {
                "sf_account_id": rec.get("Id") or "",
                "account_name": rec.get("Name") or "",
                "provider_id": pid,
                "parent_brand_key": pk,
                "sku_display": bool(rec.get("Should_Display_SKU_in_Provider_App__c")),
                "menu_management": rec.get("Menu_Link_Status__c") == "Menu Management",
            }
        )
        provider_ids.add(pid)
        if pk:
            brand_keys.add(pk)
    return {
        "source": source,
        "captured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "definition": (
            "SF Account: Should_Display_SKU_in_Provider_App__c "
            "OR Menu_Link_Status__c = Menu Management"
        ),
        "accounts": accounts,
        "brand_keys": sorted(brand_keys),
        "provider_ids": sorted(provider_ids),
    }


def _refresh_pim_index() -> dict[str, Any]:
    global _PIM_INDEX
    if _PIM_INDEX is not None:
        return _PIM_INDEX
    try:
        records = _sf_query_mt_pim_accounts()
        index = _build_pim_index_from_accounts(records, "salesforce")
        _save_pim_sf_accounts_json(index)
        print(
            f"PIM accounts (SF): {len(index['accounts'])} accounts → "
            f"{len(index['brand_keys'])} brand keys"
        )
    except (RuntimeError, json.JSONDecodeError, subprocess.SubprocessError, OSError) as e:
        cached = _load_pim_sf_accounts_json()
        if cached and cached.get("accounts"):
            index = cached
            print(
                f"PIM accounts (cached): {len(index['accounts'])} accounts "
                f"(SF unavailable: {e})"
            )
        else:
            legacy = _load_fiona_pim_brand_keys()
            index = {
                "source": "legacy_brand_keys",
                "captured_at": None,
                "definition": "legacy brand_keys fallback",
                "accounts": [],
                "brand_keys": sorted(legacy),
                "provider_ids": [],
            }
            print(f"PIM accounts (legacy): {len(legacy)} brand keys only", file=sys.stderr)
    _PIM_INDEX = index
    return index


def _pim_brand_keys() -> frozenset[str]:
    return frozenset(str(k).upper() for k in (_refresh_pim_index().get("brand_keys") or []))


def _pim_provider_ids() -> frozenset[int]:
    return frozenset(int(p) for p in (_refresh_pim_index().get("provider_ids") or []))


def _is_fiona_pim_brand(brand: dict[str, Any]) -> bool:
    key = str(brand.get("brand_key") or "").strip().upper()
    if key in _pim_brand_keys():
        return True
    for pid in brand.get("provider_ids") or []:
        try:
            if int(pid) in _pim_provider_ids():
                return True
        except (TypeError, ValueError):
            pass
    return False


def _pim_cognisant_blocked(brand: dict[str, Any]) -> bool:
    """PIM = Product Information Management (SKU catalog). Cognisant cannot run these."""
    return _is_fiona_pim_brand(brand)


def _apply_fiona_pim_flags(payload: dict[str, Any]) -> None:
    index = _refresh_pim_index()
    pim_by_key: dict[str, int] = defaultdict(int)
    pim_by_pid: dict[int, int] = defaultdict(int)
    for acct in index.get("accounts") or []:
        pk = str(acct.get("parent_brand_key") or "").upper()
        if pk:
            pim_by_key[pk] += 1
        pid = acct.get("provider_id")
        if pid is not None:
            pim_by_pid[int(pid)] += 1
    for brand in payload.get("brands") or []:
        on_pim = _is_fiona_pim_brand(brand)
        brand["on_pim"] = on_pim
        if on_pim:
            key = str(brand.get("brand_key") or "").strip().upper()
            count = pim_by_key.get(key, 0)
            if not count:
                for pid in brand.get("provider_ids") or []:
                    count += pim_by_pid.get(int(pid), 0)
            brand["pim_accounts"] = count or 1
        else:
            brand.pop("pim_accounts", None)
    payload["pim_index"] = {
        "source": index.get("source"),
        "captured_at": index.get("captured_at"),
        "account_count": len(index.get("accounts") or []),
        "brand_key_count": len(index.get("brand_keys") or []),
    }


def _portfolio_final_assignments(payload: dict[str, Any]) -> dict[str, str]:
    brand_by_id = {b["id"]: b for b in payload.get("brands") or []}
    assign = {b["id"]: b["original_am"] for b in payload.get("brands") or []}
    preset = payload.get("preset") or {}
    assign.update(preset.get("assignments") or {})
    for bid, dec in (payload.get("team_decisions") or {}).items():
        if bid not in brand_by_id or not isinstance(dec, dict):
            continue
        if dec.get("approval") is True:
            assign[bid] = str(dec.get("to_am") or brand_by_id[bid]["original_am"])
        elif dec.get("approval") is False:
            assign[bid] = brand_by_id[bid]["original_am"]
    return assign


def _export_pim_cognisant_check(payload: dict[str, Any]) -> str:
    """Account-level PIM vs final portfolio assignment (SF account grain)."""
    import csv

    index = _refresh_pim_index()
    brand_by_key = {str(b["brand_key"]).upper(): b for b in payload.get("brands") or []}
    assign = _portfolio_final_assignments(payload)
    rows: list[dict[str, Any]] = []
    for acct in index.get("accounts") or []:
        pk = str(acct.get("parent_brand_key") or "").upper()
        brand = brand_by_key.get(pk)
        if brand:
            final_am = assign.get(brand["id"], brand["original_am"])
            in_rebalancer = True
            mapped_brand = brand["brand_name"]
            brand_id = brand["id"]
        else:
            final_am = "OUTSIDE_REBALANCER"
            in_rebalancer = False
            mapped_brand = ""
            brand_id = ""
        rows.append(
            {
                "sf_account_id": acct.get("sf_account_id"),
                "account_name": acct.get("account_name"),
                "provider_id": acct.get("provider_id"),
                "parent_brand_key": pk,
                "sku_display": acct.get("sku_display"),
                "menu_management": acct.get("menu_management"),
                "in_rebalancer": in_rebalancer,
                "mapped_brand": mapped_brand,
                "brand_id": brand_id,
                "portfolio_final_am": final_am,
                "on_cognisant": final_am == "Cognisant",
            }
        )
    out_dir = os.path.expanduser("~/Documents/Bolt food")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "pim_accounts_cognisant_check.csv")
    fields = list(rows[0].keys()) if rows else []
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(
            sorted(rows, key=lambda x: (not x["on_cognisant"], not x["in_rebalancer"], x["account_name"]))
        )
    on_cog = sum(1 for r in rows if r["in_rebalancer"] and r["on_cognisant"])
    print(f"PIM account audit → {path} ({len(rows)} accounts, {on_cog} in-scope on Cognisant)")
    return path


def _enforce_pim_no_cognisant(
    assign: dict[str, str], brand_by_id: dict[str, dict[str, Any]]
) -> int:
    n = 0
    for bid, brand in brand_by_id.items():
        if not _pim_cognisant_blocked(brand):
            continue
        if assign.get(bid) == "Cognisant":
            assign[bid] = brand["original_am"]
            n += 1
    return n


def _enforce_rico_book_assignments(
    assign: dict[str, str], brand_by_id: dict[str, dict[str, Any]]
) -> int:
    """Force Rico-original brands back onto Rico, except pure SMB <€1k → Cognisant."""
    n = 0
    for bid, brand in brand_by_id.items():
        if not _rico_book_locked(brand):
            continue
        if assign.get(bid) == "Rico Spagnol":
            continue
        if assign.get(bid) == "Cognisant" and _rico_smb_u1k_to_cognisant_ok(brand):
            continue
        assign[bid] = "Rico Spagnol"
        n += 1
    return n


def _group_unit_ids(
    brand_id: str,
    assign: dict[str, str],
    brand_by_id: dict[str, dict[str, Any]],
    group_members: dict[str, list[str]],
    allowed_ams: set[str] | None = None,
) -> list[str]:
    brand = brand_by_id[brand_id]
    key = brand.get("group_key")
    ids = list(group_members.get(key, [brand_id])) if key else [brand_id]
    am = assign[brand_id]
    if all(assign.get(i) == am for i in ids):
        if allowed_ams is None or all(assign.get(i) in allowed_ams for i in ids):
            return ids
    return [brand_id]


def compute_smb_rico_mm_balance_preset(payload: dict[str, Any]) -> dict[str, Any]:
    """Pure SMB <€1k → Cognisant; pure SMB ≥€1k → Rico; MM never Rico; balance MM on Gulcin/Mariem/Yousef."""
    cog = "Cognisant"
    rico = "Rico Spagnol"
    fiona = "Fiona Borg"
    yousef = "Yousef Moungad"
    balance_ams = ["Gulcin Erguven", "Mariem Slimen", yousef]
    brand_by_id = {b["id"]: b for b in payload["brands"]}
    group_members = payload.get("group_members") or {}
    assign = {b["id"]: b["original_am"] for b in payload["brands"]}
    stats = {"smb_to_rico": 0, "smb_u1k_to_cog": 0, "balance_moves": 0}
    mm_override_ids = [
        bid for bid, b in brand_by_id.items() if _is_mm_brand_key(b.get("brand_key", ""))
    ]
    mm_reclassify = list(mm_override_ids)

    seen_groups: set[str] = set()
    for gk, member_ids in group_members.items():
        if gk in seen_groups:
            continue
        seen_groups.add(gk)
        if not member_ids:
            continue
        anchor = brand_by_id[member_ids[0]]
        smb_ids = [i for i in member_ids if _is_pure_smb_brand(brand_by_id[i])]
        routable = [i for i in smb_ids if not _pim_cognisant_blocked(brand_by_id[i])]
        if not routable:
            continue
        gmv = sum(brand_by_id[i].get("gmv_total") or 0 for i in routable)
        if gmv < 1000:
            for i in routable:
                assign[i] = cog
                stats["smb_u1k_to_cog"] += 1
        elif _rico_book_locked(anchor):
            # Rico keeps SMB ≥€1k — do not re-route elsewhere
            continue
        elif anchor["original_am"] != fiona:
            for i in routable:
                if assign[i] != rico:
                    assign[i] = rico
                    stats["smb_to_rico"] += 1

    def unit_providers(ids: list[str]) -> int:
        return sum(int(brand_by_id[i].get("providers") or 0) for i in ids)

    def balance_units() -> list[dict[str, Any]]:
        seen: set[str] = set()
        units: list[dict[str, Any]] = []
        for bid in brand_by_id:
            if bid in seen or assign[bid] not in balance_ams:
                continue
            if not _is_mm_for_balance(brand_by_id[bid]):
                continue
            ids = _group_unit_ids(bid, assign, brand_by_id, group_members, set(balance_ams))
            if any(assign[i] not in balance_ams for i in ids):
                ids = [bid]
            if any(not _is_mm_for_balance(brand_by_id[i]) for i in ids):
                ids = [bid] if _is_mm_for_balance(brand_by_id[bid]) else []
            if not ids:
                continue
            for i in ids:
                seen.add(i)
            units.append(
                {
                    "ids": ids,
                    "gmv": sum(brand_by_id[i].get("gmv_total") or 0 for i in ids),
                    "providers": unit_providers(ids),
                    "am": assign[ids[0]],
                }
            )
        return units

    def am_totals() -> dict[str, dict[str, float]]:
        st = {a: {"n": 0.0, "providers": 0.0, "gmv": 0.0} for a in balance_ams}
        for unit in balance_units():
            st[unit["am"]]["n"] += len(unit["ids"])
            st[unit["am"]]["providers"] += unit["providers"]
            st[unit["am"]]["gmv"] += unit["gmv"]
        return st

    def imbalance(st: dict[str, dict[str, float]]) -> float:
        n_ams = len(balance_ams)
        tgt_n = sum(st[a]["n"] for a in balance_ams) / n_ams
        tgt_p = sum(st[a]["providers"] for a in balance_ams) / n_ams
        tgt_g = sum(st[a]["gmv"] for a in balance_ams) / n_ams
        if tgt_n <= 0 or tgt_p <= 0 or tgt_g <= 0:
            return 0.0
        return max(
            max(abs(st[a]["n"] - tgt_n) / tgt_n for a in balance_ams),
            max(abs(st[a]["providers"] - tgt_p) / tgt_p for a in balance_ams),
            max(abs(st[a]["gmv"] - tgt_g) / tgt_g for a in balance_ams),
        )

    def dim_imbalance(st: dict[str, dict[str, float]], key: str) -> float:
        tgt = sum(st[a][key] for a in balance_ams) / len(balance_ams)
        if tgt <= 0:
            return 0.0
        return max(abs(st[a][key] - tgt) / tgt for a in balance_ams)

    def simulate_move_unit(
        st: dict[str, dict[str, float]], src: str, dst: str, unit: dict[str, Any]
    ) -> dict[str, dict[str, float]]:
        out = {a: dict(v) for a, v in st.items()}
        n = len(unit["ids"])
        out[src]["n"] -= n
        out[src]["providers"] -= unit["providers"]
        out[src]["gmv"] -= unit["gmv"]
        out[dst]["n"] += n
        out[dst]["providers"] += unit["providers"]
        out[dst]["gmv"] += unit["gmv"]
        return out

    def balance_score(st: dict[str, dict[str, float]]) -> tuple[float, float]:
        """Providers first, GMV second — lower is better."""
        return (dim_imbalance(st, "providers"), dim_imbalance(st, "gmv"))

    # Step 3: small MM only (≤€100k) — balance providers first, then GMV across Gulcin/Mariem/Yousef
    max_small_gmv = 100_000.0
    balance_tol = 0.05
    stats["small_mm_balance"] = 0
    moved_units: set[str] = set()

    for _ in range(500):
        st = am_totals()
        prov_imb = dim_imbalance(st, "providers")
        gmv_imb = dim_imbalance(st, "gmv")
        if prov_imb < balance_tol and gmv_imb < balance_tol:
            break

        tgt_p = sum(st[a]["providers"] for a in balance_ams) / len(balance_ams)
        tgt_g = sum(st[a]["gmv"] for a in balance_ams) / len(balance_ams)

        if prov_imb >= balance_tol:
            src = max(balance_ams, key=lambda a: st[a]["providers"] - tgt_p)
            dst = min(balance_ams, key=lambda a: st[a]["providers"] - tgt_p)
            if st[src]["providers"] <= tgt_p or st[dst]["providers"] >= tgt_p:
                break
        else:
            src = max(balance_ams, key=lambda a: st[a]["gmv"] - tgt_g)
            dst = min(balance_ams, key=lambda a: st[a]["gmv"] - tgt_g)
            if st[src]["gmv"] <= tgt_g or st[dst]["gmv"] >= tgt_g:
                break

        candidates = [
            u
            for u in balance_units()
            if u["am"] == src and u["gmv"] <= max_small_gmv and u["ids"][0] not in moved_units
        ]
        if not candidates:
            break

        cur_score = balance_score(st)
        best_unit: dict[str, Any] | None = None
        best_score: tuple[float, float] | None = None
        for unit in candidates:
            new_score = balance_score(simulate_move_unit(st, src, dst, unit))
            if best_score is None or new_score < best_score:
                best_score = new_score
                best_unit = unit

        if not best_unit or best_score is None or best_score >= cur_score:
            break

        for i in best_unit["ids"]:
            assign[i] = dst
        moved_units.add(best_unit["ids"][0])
        n = len(best_unit["ids"])
        stats["balance_moves"] += n
        stats["small_mm_balance"] += n

    # Rico: keep pure SMB units only when group SMB GMV ≥€1k; revert MM / stray SMB
    for gk, member_ids in group_members.items():
        smb_ids = [i for i in member_ids if _is_pure_smb_brand(brand_by_id[i])]
        on_rico = [
            i
            for i in smb_ids
            if assign[i] == rico and brand_by_id[i]["original_am"] != rico
        ]
        if not on_rico:
            continue
        group_smb_gmv = sum(brand_by_id[i].get("gmv_total") or 0 for i in smb_ids)
        if group_smb_gmv >= 1000:
            continue
        for i in on_rico:
            assign[i] = brand_by_id[i]["original_am"]

    for bid, brand in brand_by_id.items():
        if assign[bid] != rico:
            continue
        if brand["original_am"] == rico:
            continue
        if _is_pure_smb_brand(brand):
            continue
        assign[bid] = brand["original_am"]

    stats["rico_book_locked"] = _enforce_rico_book_assignments(assign, brand_by_id)
    stats["pim_no_cognisant"] = _enforce_pim_no_cognisant(assign, brand_by_id)

    moved = sum(1 for b in payload["brands"] if assign[b["id"]] != b["original_am"])
    final_st = am_totals()
    final_imb = imbalance(final_st)
    return {
        "id": "smb_rico_mm_minimal_v17",
        "label": "SMB ≥€1k→Rico (excl. Fiona) · SMB <€1k→Cognisant (incl. Rico; excl. PIM) · small MM ≤€100k (providers first)",
        "preset_includes_mm_balance": True,
        "small_mm_balance": True,
        "balance_providers_first": True,
        "small_mm_max_gmv": max_small_gmv,
        "assignments": assign,
        "mm_reclassify": mm_reclassify,
        "stats": {
            **stats,
            "moved_from_original": moved,
            "balance_imbalance_pct": round(final_imb * 100, 1),
            "balance_providers_imbalance_pct": round(dim_imbalance(final_st, "providers") * 100, 1),
            "balance_gmv_imbalance_pct": round(dim_imbalance(final_st, "gmv") * 100, 1),
            "balance_final": {
                am: {
                    "brands": int(final_st[am]["n"]),
                    "providers": int(final_st[am]["providers"]),
                    "gmv": round(final_st[am]["gmv"], 2),
                }
                for am in balance_ams
            },
        },
    }


def build_payload(dbx: Any, country_code: str) -> dict[str, Any]:
    month_keys = month_keys_last_n(GMV_MONTHS)
    df = query_provider_rows(dbx, country_code)
    gmv_df = query_team_gmv_by_month(dbx, country_code, month_keys)
    gmv_by_provider = build_gmv_by_provider(gmv_df)
    brands, group_members = build_brand_payload(df, gmv_by_provider, month_keys)
    payload = {
        "country": country_code.upper(),
        "group_members": group_members,
        "gmv_month_keys": month_keys,
        "gmv_period_label": gmv_period_label(month_keys),
        "ams": [
            {
                "name": name,
                "slug": AM_META[name]["slug"],
                "role_segment": AM_META[name]["role_segment"],
            }
            for name in TEAM_AMS
        ]
        + [
            {
                "name": col["name"],
                "slug": col["slug"],
                "role_segment": col["role_segment"],
            }
            for col in EXTRA_AM_COLUMNS
        ],
        "brands": brands,
        "segment_labels": list(SEGMENT_SHORT.keys()),
    }
    _finalize_payload(payload)
    return payload


def _try_load_team_review_from_git() -> dict[str, Any] | None:
    """Recover v8 approval session from boltable git (saved before team reset to original)."""
    repo = os.path.join(_ROOT, "boltable", "mt-portfolio-rebalancer")
    if not os.path.isdir(repo):
        return None
    try:
        r = subprocess.run(
            ["git", "-C", repo, "show", "300d691:public/moves-state.json"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return None
        return json.loads(r.stdout)
    except (json.JSONDecodeError, subprocess.SubprocessError, OSError):
        return None


def _load_moves_state() -> dict[str, Any]:
    path = _moves_state_json_path()
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _team_move_row(
    brand: dict[str, Any], dest_am: str, approval: bool | None = None
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": brand["id"],
        "brand_name": brand["brand_name"],
        "brand_key": brand.get("brand_key"),
        "from_am": brand["original_am"],
        "to_am": dest_am,
        "gmv_total": brand.get("gmv_total"),
        "segments": brand.get("segments"),
    }
    if approval is not None:
        row["approval"] = approval
    return row


def _build_team_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    brand_by_id = {b["id"]: b for b in payload["brands"]}
    moves = _load_moves_state()
    decisions = moves.get("decisions") or {}
    if not decisions and moves.get("approvals"):
        for bid, appr in moves["approvals"].items():
            if not isinstance(appr, bool) or bid not in brand_by_id:
                continue
            b = brand_by_id[bid]
            assign = (moves.get("assignments") or {}).get(bid, b["original_am"])
            decisions[bid] = {
                "approval": appr,
                "to_am": assign,
                "from_am": b["original_am"],
            }

    decided_rows = []
    for bid, dec in decisions.items():
        b = brand_by_id.get(bid)
        if not b or not isinstance(dec, dict):
            continue
        decided_rows.append(
            _team_move_row(b, dec.get("to_am", b["original_am"]), dec.get("approval"))
        )

    agreed = [m for m in decided_rows if m.get("approval") is True]
    disagreed = [m for m in decided_rows if m.get("approval") is False]

    return {
        "captured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "moves_state": {
            "version": moves.get("version"),
            "updated_at": moves.get("updatedAt"),
            "format": "decisions_v3",
            "decisions_count": len(decided_rows),
            "agreed": agreed,
            "disagreed": disagreed,
            "agreed_count": len(agreed),
            "disagreed_count": len(disagreed),
        },
        "mm_overrides": {
            "brand_keys": sorted(MM_BRAND_KEYS),
            "provider_ids": sorted(MM_PROVIDER_IDS),
        },
    }


def _write_team_snapshot_export(snapshot: dict[str, Any]) -> str:
    out_dir = os.path.expanduser("~/Documents/Bolt food")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "team-portfolio-snapshot.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return path


def _sync_moves_state_review_metadata(snapshot: dict[str, Any]) -> None:
    """No-op — team state is decisions-only; saved from the dashboard."""
    return


def _embed_team_decisions(payload: dict[str, Any]) -> None:
    """Bake current moves-state decisions into data.json so boot works before CDN catches up."""
    moves = _load_moves_state()
    decisions = moves.get("decisions") or {}
    if not decisions and moves.get("approvals"):
        brand_by_id = {b["id"]: b for b in payload["brands"]}
        assign = moves.get("assignments") or {}
        for bid, appr in moves["approvals"].items():
            if appr not in (True, False) or bid not in brand_by_id:
                continue
            b = brand_by_id[bid]
            decisions[bid] = {
                "approval": appr,
                "to_am": assign.get(bid, b["original_am"]),
                "from_am": b["original_am"],
            }
    payload["team_decisions"] = decisions
    payload["team_decisions_version"] = moves.get("version") or 0
    payload["team_decisions_updated_at"] = moves.get("updatedAt")


def _rebuild_group_members(payload: dict[str, Any]) -> None:
    """Group brands by SF parent group within the same AM (cross-AM parents stay separate)."""
    group_members: dict[str, list[str]] = defaultdict(list)
    for brand in payload.get("brands") or []:
        pg = brand.get("primary_group") or ""
        if pg:
            gk = f"{pg}|||{brand['original_am']}"
        else:
            gk = f"__solo_{brand['id']}"
        brand["group_key"] = gk
        group_members[gk].append(brand["id"])
    payload["group_members"] = dict(group_members)


def _finalize_payload(payload: dict[str, Any]) -> None:
    _apply_mm_brand_key_overrides(payload)
    _apply_mm_provider_overrides(payload)
    _rebuild_group_members(payload)
    _apply_fiona_pim_flags(payload)
    payload["preset"] = compute_smb_rico_mm_balance_preset(payload)
    _apply_preset_mm_reclassify(payload)
    csv_path = _apply_smb_to_mm_portfolio_placements(payload)
    print(f"SMB→MM portfolio placements → {csv_path} ({len(payload.get('smb_to_mm_portfolio') or [])} brands)")
    payload["team_snapshot"] = _build_team_snapshot(payload)
    _embed_team_decisions(payload)
    _export_pim_cognisant_check(payload)


def _load_payload_from_cache(cache_path: str) -> dict[str, Any]:
    with open(cache_path, encoding="utf-8") as f:
        payload = json.load(f)
    if not payload.get("brands"):
        raise ValueError(f"Cached payload missing brands: {cache_path}")
    _finalize_payload(payload)
    return payload


def _moves_state_json_path() -> str:
    return os.path.join(_ROOT, "boltable", "mt-portfolio-rebalancer", "public", "moves-state.json")


def _ensure_moves_state_json() -> None:
    path = _moves_state_json_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.isfile(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"version": 0, "updatedAt": None, "decisions": {}}, f)
            f.write("\n")


def _export_sf_apply_preview(boltable_public: str) -> dict[str, Any] | None:
    """Query SF + team decisions; write preview JSON/CSV and copy to boltable public."""
    try:
        from sf_portfolio_apply import run_preview

        plan = run_preview(SF_DEFAULT_ORG)
        src = plan["preview_paths"]["json"]
        dest = os.path.join(boltable_public, "sf_apply_preview.json")
        shutil.copy2(src, dest)
        print(
            f"SF apply preview → {src} "
            f"({plan['summary']['owner_changes']} owner, "
            f"{plan['summary']['cognisant_parent_moves']} Cognisant→Kimberley, "
            f"{plan['summary']['team_agreed_parent_moves']} team-agreed)"
        )
        return plan
    except Exception as e:
        print(f"SF apply preview skipped: {e}", file=sys.stderr)
        return None


def _write_all_outputs(payload: dict[str, Any], gen: str, out: str) -> str:
    gh_token = _resolve_gh_state_token()
    if gh_token:
        print("Team sync: GitHub token embedded for live moves-state.json")
    else:
        print(
            "Team sync: no GH token — moves only persist per browser. "
            "Set MT_PORTFOLIO_GH_TOKEN or gh auth login, then rebuild.",
            file=sys.stderr,
        )
    _ensure_moves_state_json()
    snapshot = payload.get("team_snapshot") or _build_team_snapshot(payload)
    snap_path = _write_team_snapshot_export(snapshot)
    _sync_moves_state_review_metadata(snapshot)
    print(f"Team snapshot → {snap_path}")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    html = _render_html(payload, gen)
    data_js = _data_js_path(out)
    data_json = _data_json_path(out)
    css_path, js_path = _write_dashboard_bundle(html, out, gh_token)
    _write_data_js(payload, data_js)
    _write_data_json(payload, data_json)
    boltable_public = os.path.dirname(_boltable_index_path())
    os.makedirs(boltable_public, exist_ok=True)
    shutil.copy2(data_json, os.path.join(boltable_public, "data.json"))
    shutil.copy2(data_js, os.path.join(boltable_public, "data.js"))
    shutil.copy2(css_path, os.path.join(boltable_public, "dashboard.css"))
    shutil.copy2(js_path, os.path.join(boltable_public, "dashboard.js"))
    sf_plan = _export_sf_apply_preview(boltable_public)
    if sf_plan:
        payload["sf_apply_preview"] = {
            "summary": sf_plan.get("summary"),
            "generated_at": sf_plan.get("generated_at"),
        }
        _write_data_json(payload, data_json)
        shutil.copy2(data_json, os.path.join(boltable_public, "data.json"))
    boltable_path = _boltable_index_path()
    with open(boltable_path, "w", encoding="utf-8") as f:
        f.write(_render_boltable_index(html, payload, gh_token))
    site_dir = _write_local_site(out, css_path, js_path, data_json)
    print(
        f"Wrote {len(payload['brands'])} brands → {out} + {css_path} + {js_path} + {data_json}"
    )
    print(f"Boltable bundle → {boltable_path} ({os.path.getsize(boltable_path)} bytes)")
    print(f"Local site → {site_dir}")
    print("Open locally: bash scripts/serve_mt_portfolio_rebalancer.sh")
    return out


def _render_html(payload: dict[str, Any], generated: str) -> str:
    title = "Malta portfolio rebalancer"
    esc_title = html_lib.escape(title)
    esc_gen = html_lib.escape(generated)
    esc_country = html_lib.escape(payload["country"])

    html_raw = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>__TITLE__</title>
  <script>
    (function () {
      try {
        var k = 'mt_portfolio_rebalancer_theme';
        var t = localStorage.getItem(k);
        if (t !== 'light' && t !== 'dark') {
          t = window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
        }
        document.documentElement.dataset.theme = t;
      } catch (e) {
        document.documentElement.dataset.theme = 'dark';
      }
    })();
  </script>
  <style>
    html[data-theme="dark"], html:not([data-theme]) {
      color-scheme: dark;
      --bg: #0f1419;
      --card: #1a2332;
      --text: #e7ecf3;
      --muted: #8b9bb4;
      --accent: #3b82f6;
      --border: #2d3a4f;
      --moved: #f59e0b;
      --moved-bg: rgba(245, 158, 11, 0.14);
      --mm-suggested: #2dd4bf;
      --mm-suggested-bg: rgba(45, 212, 191, 0.14);
      --smb-policy: #64748b;
      --smb-policy-bg: rgba(100, 116, 139, 0.12);
      --pending-incoming: #22d3ee;
      --pending-incoming-bg: rgba(34, 211, 238, 0.14);
      --pending-outgoing: #94a3b8;
      --pending-outgoing-bg: rgba(148, 163, 184, 0.1);
      --up: #34d399;
      --down: #f87171;
      --chart-grid: #2d3a4f;
      --chart-tick: #8b9bb4;
      --chart-legend: #8b9bb4;
      --chart-label-before: #93c5fd;
      --hover-row: rgba(255, 255, 255, 0.03);
      --badge-accent-fg: #93c5fd;
      --badge-accent-bg: rgba(59, 130, 246, 0.15);
      --badge-active-fg: #6ee7b7;
      --badge-active-bg: rgba(52, 211, 153, 0.15);
      --badge-muted-fg: #cbd5e1;
      --badge-muted-bg: rgba(148, 163, 184, 0.18);
      --banner-info-bg: #1e3a5f;
      --banner-info-fg: #93c5fd;
      --banner-pending-bg: #3b2f1a;
      --banner-pending-fg: #fcd34d;
      --banner-error-bg: #451a1a;
      --banner-error-fg: #fca5a5;
      --banner-preset-fg: #99f6e4;
      --banner-preset-strong: #5eead4;
      --col-extra-border: #4b5563;
      --seg-pill-active-fg: #93c5fd;
      --seg-pill-active-count: #bfdbfe;
      --approval-label-fg: #93c5fd;
      --signoff-agree-fg: #6ee7b7;
      --signoff-disagree-fg: #fca5a5;
      --route-open-bg: rgba(245, 158, 11, 0.04);
      --route-highlight-bg: rgba(245, 158, 11, 0.1);
      --loader-bg: rgba(59, 130, 246, 0.12);
      --loader-border: rgba(59, 130, 246, 0.35);
      --loader-fg: #93c5fd;
      --error-banner-bg: rgba(248, 113, 113, 0.12);
      --error-banner-border: rgba(248, 113, 113, 0.4);
      --error-banner-fg: #fca5a5;
      --preset-banner-bg: rgba(45, 212, 191, 0.12);
      --preset-banner-border: rgba(45, 212, 191, 0.35);
    }
    html[data-theme="light"] {
      color-scheme: light;
      --bg: #f1f5f9;
      --card: #ffffff;
      --text: #0f172a;
      --muted: #64748b;
      --accent: #2563eb;
      --border: #cbd5e1;
      --moved: #d97706;
      --moved-bg: rgba(217, 119, 6, 0.12);
      --mm-suggested: #0d9488;
      --mm-suggested-bg: rgba(13, 148, 136, 0.1);
      --smb-policy: #64748b;
      --smb-policy-bg: rgba(100, 116, 139, 0.1);
      --pending-incoming: #0891b2;
      --pending-incoming-bg: rgba(8, 145, 178, 0.1);
      --pending-outgoing: #64748b;
      --pending-outgoing-bg: rgba(100, 116, 139, 0.08);
      --up: #059669;
      --down: #dc2626;
      --chart-grid: #e2e8f0;
      --chart-tick: #64748b;
      --chart-legend: #475569;
      --chart-label-before: #2563eb;
      --hover-row: rgba(15, 23, 42, 0.04);
      --badge-accent-fg: #1d4ed8;
      --badge-accent-bg: rgba(37, 99, 235, 0.1);
      --badge-active-fg: #047857;
      --badge-active-bg: rgba(5, 150, 105, 0.12);
      --badge-muted-fg: #475569;
      --badge-muted-bg: rgba(100, 116, 139, 0.12);
      --banner-info-bg: #dbeafe;
      --banner-info-fg: #1e40af;
      --banner-pending-bg: #fef3c7;
      --banner-pending-fg: #92400e;
      --banner-error-bg: #fee2e2;
      --banner-error-fg: #b91c1c;
      --banner-preset-fg: #115e59;
      --banner-preset-strong: #0f766e;
      --col-extra-border: #94a3b8;
      --seg-pill-active-fg: #1d4ed8;
      --seg-pill-active-count: #1e3a8a;
      --approval-label-fg: #1d4ed8;
      --signoff-agree-fg: #047857;
      --signoff-disagree-fg: #b91c1c;
      --route-open-bg: rgba(217, 119, 6, 0.06);
      --route-highlight-bg: rgba(217, 119, 6, 0.12);
      --loader-bg: rgba(37, 99, 235, 0.08);
      --loader-border: rgba(37, 99, 235, 0.25);
      --loader-fg: #1d4ed8;
      --error-banner-bg: rgba(220, 38, 38, 0.08);
      --error-banner-border: rgba(220, 38, 38, 0.25);
      --error-banner-fg: #b91c1c;
      --preset-banner-bg: rgba(13, 148, 136, 0.1);
      --preset-banner-border: rgba(13, 148, 136, 0.28);
    }
    * { box-sizing: border-box; }
    body {
      font-family: "Segoe UI", system-ui, sans-serif;
      background: var(--bg);
      color: var(--text);
      margin: 0;
      padding: 1rem 1.25rem 3rem;
      line-height: 1.45;
    }
    h1 { font-size: 1.35rem; margin: 0 0 0.35rem; }
    .title-row {
      display: flex;
      flex-wrap: wrap;
      align-items: flex-start;
      justify-content: space-between;
      gap: 0.75rem 1rem;
      margin-bottom: 0.35rem;
    }
    .title-row .title-block { flex: 1; min-width: 200px; }
    .theme-toggle {
      flex-shrink: 0;
      font-size: 0.8rem;
      padding: 0.4rem 0.75rem;
      white-space: nowrap;
    }
    .sub { color: var(--muted); font-size: 0.85rem; margin-bottom: 1rem; }
    .toolbar {
      display: flex;
      flex-wrap: wrap;
      gap: 0.75rem;
      align-items: flex-end;
      margin-bottom: 1rem;
    }
    .toolbar label {
      display: flex;
      flex-direction: column;
      gap: 0.25rem;
      font-size: 0.75rem;
      color: var(--muted);
    }
    input, select, button {
      background: var(--bg);
      color: var(--text);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 0.45rem 0.6rem;
      font: inherit;
    }
    button {
      cursor: pointer;
      background: var(--card);
    }
    button:hover { border-color: var(--accent); }
    button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
    .sf-apply-summary { font-size: 0.88rem; color: var(--muted); margin: 0 0 0.75rem; line-height: 1.45; }
    .sf-apply-toolbar { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; margin-bottom: 0.75rem; }
    .sf-apply-toolbar .pill {
      font-size: 0.72rem;
      padding: 0.2rem 0.5rem;
      border-radius: 999px;
      border: 1px solid var(--border);
      background: var(--card);
      cursor: pointer;
    }
    .sf-apply-toolbar .pill.active { border-color: var(--accent); color: var(--accent); }
    #sfApplyTable { width: 100%; border-collapse: collapse; font-size: 0.78rem; }
    #sfApplyTable th, #sfApplyTable td { border-bottom: 1px solid var(--border); padding: 0.35rem 0.5rem; text-align: left; }
    #sfApplyTable th { color: var(--muted); font-weight: 600; }
    .sf-action-owner { color: var(--accent); }
    .sf-action-segment { color: var(--signoff-agree-fg); }
    .sf-action-cognisant { color: #c084fc; }
    #btnSaveTeam.save-dirty, .btn-save-team.save-dirty { box-shadow: 0 0 0 2px var(--pending-incoming); }
    #btnSaveTeam.save-ok, .btn-save-team.save-ok { background: var(--up); border-color: var(--up); }
    #btnSaveTeam.save-error, .btn-save-team.save-error { background: var(--down); border-color: var(--down); }
    #btnSaveTeam:disabled, .btn-save-team:disabled { opacity: 0.65; cursor: wait; }
    .save-team-bar {
      position: sticky;
      top: 0;
      z-index: 200;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 0.65rem 1rem;
      margin: 0 0 1rem;
      padding: 0.7rem 0.9rem;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 10px;
      box-shadow: 0 4px 16px rgba(0, 0, 0, 0.18);
    }
    .save-team-bar .btn-save-team {
      font-size: 0.95rem;
      font-weight: 600;
      padding: 0.55rem 1.1rem;
    }
    .save-team-hint {
      color: var(--muted);
      font-size: 0.82rem;
    }
    .portfolio-toolbar .btn-save-team {
      font-weight: 600;
      margin-left: auto;
    }
    .summary {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 0.75rem;
      margin-bottom: 1rem;
    }
    .stat {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 0.85rem 1rem;
    }
    .stat .label { color: var(--muted); font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.04em; }
    .stat .value { font-size: 1.35rem; font-weight: 700; font-variant-numeric: tabular-nums; }
    .stat .delta { font-size: 0.8rem; margin-top: 0.2rem; }
    .delta-up { color: var(--up); }
    .delta-down { color: var(--down); }
    .delta-zero { color: var(--muted); }
    .card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 1rem;
      margin-bottom: 1rem;
    }
    h2 { font-size: 1.05rem; margin: 0; color: var(--accent); }
    .card-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 0.5rem;
      margin-bottom: 0.75rem;
      cursor: pointer;
      user-select: none;
    }
    .card-head h2 { flex: 1; }
    .collapse-btn {
      flex-shrink: 0;
      border: 1px solid var(--border);
      background: var(--bg);
      color: var(--muted);
      border-radius: 6px;
      width: 1.75rem;
      height: 1.75rem;
      font-size: 1rem;
      line-height: 1;
      cursor: pointer;
      padding: 0;
    }
    .collapse-btn:hover { border-color: var(--accent); color: var(--text); }
    .is-collapsed .collapse-body { display: none; }
    .is-collapsed .card-head { margin-bottom: 0; }
    .bulk-bar .card-head h2,
    .legend .card-head h2 { font-size: 0.88rem; }
    .summary .card-head h2 { font-size: 0.95rem; }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.78rem;
    }
    th, td {
      border-bottom: 1px solid var(--border);
      padding: 0.4rem 0.45rem;
      text-align: left;
      vertical-align: top;
    }
    th { color: var(--muted); font-weight: 600; }
    .num { text-align: right; font-variant-numeric: tabular-nums; }
    .board {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 0.75rem;
      overflow-x: auto;
      padding-bottom: 0.5rem;
    }
    .col.extra-am {
      border-style: dashed;
      border-color: var(--col-extra-border);
    }
    .col {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 10px;
      min-height: 320px;
      display: flex;
      flex-direction: column;
    }
    .col.drag-over { border-color: var(--accent); box-shadow: 0 0 0 2px rgba(59,130,246,0.25); }
    .col-head {
      padding: 0.75rem;
      border-bottom: 1px solid var(--border);
      position: sticky;
      top: 0;
      background: var(--card);
      border-radius: 10px 10px 0 0;
    }
    .col-head h3 { margin: 0; font-size: 0.92rem; }
    .col-head .role { color: var(--muted); font-size: 0.72rem; }
    .col-totals {
      display: flex;
      flex-wrap: wrap;
      gap: 0.35rem 0.6rem;
      margin-top: 0.45rem;
      font-size: 0.72rem;
      color: var(--muted);
    }
    .col-totals strong { color: var(--text); }
    .col-body {
      padding: 0.5rem;
      flex: 1;
      min-height: 120px;
    }
    .brand {
      background: var(--bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0.55rem 0.6rem;
      margin-bottom: 0.45rem;
      cursor: grab;
      font-size: 0.78rem;
    }
    .brand:active { cursor: grabbing; }
    .brand.moved {
      border-color: var(--moved);
      background: var(--moved-bg);
      box-shadow: inset 3px 0 0 var(--moved);
    }
    .brand.pending-incoming {
      border-color: var(--pending-incoming);
      background: var(--pending-incoming-bg);
      box-shadow: inset 3px 0 0 var(--pending-incoming);
    }
    .brand.pending-outgoing {
      border-color: var(--pending-outgoing);
      background: var(--pending-outgoing-bg);
      border-style: dashed;
      box-shadow: inset 3px 0 0 var(--pending-outgoing);
      opacity: 0.94;
      cursor: default;
    }
    .brand.pending-outgoing:active { cursor: default; }
    .brand.not-agreed-veto {
      border-color: var(--signoff-disagree-fg);
      background: rgba(248, 113, 113, 0.08);
      box-shadow: inset 3px 0 0 var(--signoff-disagree-fg);
    }
    .brand.mm-suggested {
      border-color: var(--mm-suggested);
      background: var(--mm-suggested-bg);
      box-shadow: inset 3px 0 0 var(--mm-suggested);
    }
    .brand.smb-policy {
      border-color: var(--smb-policy);
      background: var(--smb-policy-bg);
      box-shadow: inset 3px 0 0 var(--smb-policy);
    }
    .brand.hidden { display: none; }
    .brand-name { font-weight: 600; margin-bottom: 0.25rem; word-break: break-word; }
    .brand-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 0.35rem;
      color: var(--muted);
      font-size: 0.7rem;
      margin-bottom: 0.35rem;
    }
    .badge {
      display: inline-block;
      padding: 0.1rem 0.35rem;
      border-radius: 4px;
      background: var(--badge-accent-bg);
      color: var(--badge-accent-fg);
      font-size: 0.68rem;
    }
    .badge.status-active { background: var(--badge-active-bg); color: var(--badge-active-fg); }
    .badge.status-hidden { background: var(--badge-muted-bg); color: var(--badge-muted-fg); }
    .badge.status-onboarding { background: var(--badge-accent-bg); color: var(--badge-accent-fg); }
    .badge.status-mixed { background: var(--moved-bg); color: var(--moved); }
    .badge.group-badge {
      background: var(--badge-muted-bg);
      color: var(--badge-muted-fg);
      max-width: 100%;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .brand.group-split {
      outline: 1px dashed var(--down);
    }
    .group-pill {
      display: inline-block;
      font-size: 0.65rem;
      color: var(--down);
      font-weight: 600;
      margin-left: 0.25rem;
    }
    .brand.selected {
      box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.45);
    }
    .brand-check {
      display: flex;
      align-items: flex-start;
      gap: 0.4rem;
      margin-bottom: 0.3rem;
    }
    .brand-check input { margin-top: 0.15rem; cursor: pointer; accent-color: var(--accent); }
    .brand-check .brand-title { flex: 1; min-width: 0; }
    .bulk-bar {
      display: flex;
      flex-wrap: wrap;
      gap: 0.75rem;
      align-items: center;
      padding: 0.65rem 0.85rem;
      margin-bottom: 1rem;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 10px;
      font-size: 0.82rem;
    }
    .bulk-bar label { display: flex; align-items: center; gap: 0.35rem; color: var(--muted); }
    .bulk-bar select { min-width: 160px; }
    #bulkSummary { color: var(--text); font-variant-numeric: tabular-nums; }
    #bulkSummary strong { color: var(--accent); }
    .move-row { display: flex; gap: 0.35rem; margin-top: 0.25rem; }
    .move-row select { flex: 1; font-size: 0.7rem; padding: 0.25rem 0.35rem; }
    .brand.needs-approval {
      box-shadow: inset 0 0 0 1px rgba(59, 130, 246, 0.35);
    }
    .card-approval {
      margin-top: 0.5rem;
      padding: 0.5rem;
      background: rgba(59, 130, 246, 0.1);
      border: 1px solid rgba(59, 130, 246, 0.35);
      border-radius: 6px;
    }
    .card-approval-label {
      display: block;
      font-size: 0.68rem;
      font-weight: 700;
      color: var(--approval-label-fg);
      margin-bottom: 0.4rem;
      letter-spacing: 0.02em;
    }
    .card-approval-status {
      font-weight: 600;
      color: var(--muted);
    }
    .card-approval-status.agreed { color: var(--signoff-agree-fg); }
    .card-approval-status.not-agreed { color: var(--signoff-disagree-fg); }
    .card-approval .signoff-actions { margin-top: 0; }
    .card-approval .signoff-btn {
      flex: 1;
      padding: 0.42rem 0.5rem;
      font-size: 0.74rem;
    }
    .approval-pill {
      display: inline-block;
      font-size: 0.65rem;
      font-weight: 600;
      padding: 0.1rem 0.35rem;
      border-radius: 4px;
      margin-left: 0.25rem;
    }
    .approval-pill.agreed { background: var(--badge-active-bg); color: var(--signoff-agree-fg); }
    .approval-pill.not-agreed { background: rgba(248, 113, 113, 0.15); color: var(--signoff-disagree-fg); }
    #portfolioApprovalSummary {
      font-size: 0.78rem;
      color: var(--muted);
    }
    #portfolioApprovalSummary strong { color: var(--accent); }
    .signoff-actions {
      display: flex;
      gap: 0.35rem;
      flex-wrap: wrap;
    }
    .signoff-btn {
      border: 1px solid var(--border);
      background: var(--bg);
      color: var(--muted);
      border-radius: 6px;
      padding: 0.3rem 0.55rem;
      font-size: 0.75rem;
      cursor: pointer;
      font-weight: 600;
    }
    .signoff-btn:hover { border-color: var(--accent); color: var(--text); }
    .signoff-btn.agree.active {
      background: var(--badge-active-bg);
      border-color: var(--up);
      color: var(--signoff-agree-fg);
    }
    .signoff-btn.disagree.active {
      background: rgba(248, 113, 113, 0.18);
      border-color: var(--down);
      color: var(--signoff-disagree-fg);
    }
    .moved-pill {
      display: inline-block;
      font-size: 0.65rem;
      color: var(--moved);
      font-weight: 600;
      margin-left: 0.25rem;
    }
    .pending-incoming-pill {
      display: inline-block;
      font-size: 0.65rem;
      color: var(--pending-incoming);
      font-weight: 700;
      margin-left: 0.25rem;
    }
    .pending-outgoing-pill {
      display: inline-block;
      font-size: 0.65rem;
      color: var(--pending-outgoing);
      font-weight: 600;
      margin-left: 0.25rem;
    }
    .mm-suggested-pill {
      display: inline-block;
      font-size: 0.65rem;
      color: var(--mm-suggested);
      font-weight: 600;
      margin-left: 0.25rem;
    }
    .smb-policy-pill {
      display: inline-block;
      font-size: 0.65rem;
      color: var(--smb-policy);
      font-weight: 600;
      margin-left: 0.25rem;
    }
    .balance-plan {
      font-size: 0.82rem;
      color: var(--muted);
      margin: 0 0 0.75rem;
      line-height: 1.5;
    }
    .balance-plan strong { color: var(--mm-suggested); }
    #mmSuggestTable { margin-top: 0.75rem; font-size: 0.78rem; }
    .legend {
      display: flex;
      gap: 1rem;
      font-size: 0.75rem;
      color: var(--muted);
      margin-bottom: 0.75rem;
    }
    .swatch {
      display: inline-block;
      width: 12px;
      height: 12px;
      border-radius: 3px;
      vertical-align: -2px;
      margin-right: 0.25rem;
      border: 1px solid var(--border);
    }
    .swatch.moved { background: var(--moved-bg); border-color: var(--moved); box-shadow: inset 2px 0 0 var(--moved); }
    .swatch.smb-policy { background: var(--smb-policy-bg); border-color: var(--smb-policy); box-shadow: inset 2px 0 0 var(--smb-policy); }
    .swatch.mm-suggested { background: var(--mm-suggested-bg); border-color: var(--mm-suggested); box-shadow: inset 2px 0 0 var(--mm-suggested); }
    .portfolio-toolbar {
      display: flex;
      flex-wrap: wrap;
      gap: 0.75rem 1.25rem;
      align-items: center;
      margin-bottom: 0.85rem;
      padding: 0.65rem 0.75rem;
      background: var(--bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      font-size: 0.82rem;
    }
    .portfolio-toolbar label {
      display: flex;
      align-items: center;
      gap: 0.4rem;
      color: var(--muted);
    }
    .portfolio-toolbar input[type="search"],
    .portfolio-toolbar select {
      font-size: 0.82rem;
      padding: 0.3rem 0.45rem;
      border-radius: 6px;
      border: 1px solid var(--border);
      background: var(--card);
      color: var(--text);
    }
    .seg-pills-wrap {
      display: flex;
      align-items: center;
      gap: 0.45rem;
      flex-wrap: wrap;
    }
    .seg-pills-wrap .filter-label {
      color: var(--muted);
      font-size: 0.78rem;
      white-space: nowrap;
    }
    .seg-pills {
      display: flex;
      flex-wrap: wrap;
      gap: 0.35rem;
    }
    .seg-pill {
      border: 1px solid var(--border);
      background: var(--card);
      color: var(--text);
      border-radius: 999px;
      padding: 0.22rem 0.65rem;
      font-size: 0.75rem;
      cursor: pointer;
      transition: background 0.12s, border-color 0.12s, color 0.12s;
    }
    .seg-pill:hover { border-color: var(--accent); color: var(--accent); }
    .seg-pill.active {
      background: var(--badge-accent-bg);
      border-color: var(--accent);
      color: var(--seg-pill-active-fg);
      font-weight: 600;
    }
    .seg-pill .pill-count {
      color: var(--muted);
      font-weight: 400;
      margin-left: 0.2rem;
    }
    .seg-pill.active .pill-count { color: var(--seg-pill-active-count); }
    #portfolioFilterSummary {
      margin-left: auto;
      color: var(--muted);
      font-size: 0.78rem;
      font-variant-numeric: tabular-nums;
      white-space: nowrap;
    }
    #portfolioFilterSummary strong { color: var(--accent); }
    #fSegment { display: none; }
    .charts-top { margin-bottom: 1rem; }
    .chart-grid {
      display: grid;
      gap: 1rem;
    }
    @media (min-width: 900px) {
      .chart-grid { grid-template-columns: 1.2fr 1fr; }
    }
    .chart-panel {
      background: var(--bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0.75rem;
      min-height: 260px;
    }
    .chart-panel h3 {
      margin: 0 0 0.5rem;
      font-size: 0.82rem;
      color: var(--muted);
      font-weight: 600;
    }
    .chart-panel .chart-wrap { position: relative; height: 240px; }
    .chart-moves-row { margin-top: 1rem; padding-top: 1rem; border-top: 1px solid var(--border); }
    .chart-panel-wide { min-height: auto; }
    .chart-moves-grid {
      display: grid;
      gap: 1rem;
    }
    @media (min-width: 900px) {
      .chart-moves-grid { grid-template-columns: 1fr 1fr; }
    }
    .chart-panel-wide .chart-wrap-moves { height: 160px; min-height: 120px; }
    #movesFlowTable { margin-top: 0.75rem; font-size: 0.78rem; }
    #movesFlowTable th { white-space: nowrap; }
    .moves-flow-hint {
      font-size: 0.72rem;
      color: var(--muted);
      margin: 0.65rem 0 0.35rem;
    }
    .moves-flow-accordion { margin-top: 0.5rem; font-size: 0.78rem; }
    .move-route-header {
      display: grid;
      grid-template-columns: 1fr 4.5rem 4.5rem 6.5rem;
      gap: 0.5rem;
      padding: 0.35rem 0.5rem 0.35rem 1.6rem;
      color: var(--muted);
      font-weight: 600;
      font-size: 0.72rem;
      border-bottom: 1px solid var(--border);
    }
    .move-route-header .num { text-align: right; }
    details.move-route {
      border-bottom: 1px solid var(--border);
    }
    details.move-route[open] {
      background: var(--route-open-bg);
    }
    details.move-route.move-route-highlight {
      background: var(--route-highlight-bg);
    }
    summary.move-route-summary {
      display: grid;
      grid-template-columns: 1.1rem 1fr 4.5rem 4.5rem 6.5rem;
      gap: 0.5rem;
      align-items: center;
      padding: 0.45rem 0.5rem;
      cursor: pointer;
      list-style: none;
      user-select: none;
    }
    summary.move-route-summary::-webkit-details-marker { display: none; }
    summary.move-route-summary::marker { display: none; content: ''; }
    .move-route-chevron {
      width: 0.55rem;
      height: 0.55rem;
      border-right: 2px solid var(--muted);
      border-bottom: 2px solid var(--muted);
      transform: rotate(-45deg);
      transition: transform 0.15s ease;
      margin-left: 0.15rem;
    }
    details.move-route[open] .move-route-chevron {
      transform: rotate(45deg);
      margin-top: -0.15rem;
    }
    summary.move-route-summary:hover {
      background: var(--hover-row);
    }
    .move-route-label { font-weight: 600; color: var(--text); }
    .move-route-stat { text-align: right; color: var(--muted); }
    .move-route-stat strong { color: var(--moved); }
    .move-route-accounts {
      padding: 0 0.5rem 0.55rem 1.6rem;
      max-height: 280px;
      overflow-y: auto;
    }
    .move-route-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.76rem;
    }
    .move-route-table th {
      text-align: left;
      color: var(--muted);
      font-weight: 600;
      padding: 0.25rem 0.35rem;
      border-bottom: 1px solid var(--border);
    }
    .move-route-table th.num { text-align: right; }
    .move-route-table td {
      padding: 0.3rem 0.35rem;
      border-bottom: 1px solid rgba(255, 255, 255, 0.04);
      vertical-align: top;
    }
    .move-route-table td.num { text-align: right; white-space: nowrap; }
    .move-route-table tbody tr:hover td { background: var(--hover-row); }
    .chart-empty {
      color: var(--muted);
      font-size: 0.82rem;
      padding: 1.5rem 0.75rem;
      text-align: center;
    }
    .moves-chart-summary {
      font-size: 0.78rem;
      color: var(--muted);
      margin: 0 0 0.5rem;
    }
    .moves-chart-summary strong { color: var(--moved); }
    .chart-split-section { margin-bottom: 1.25rem; }
    .chart-split-section:last-of-type { margin-bottom: 0; }
    .chart-split-label {
      font-size: 0.88rem;
      font-weight: 600;
      margin: 0 0 0.65rem;
      padding-bottom: 0.35rem;
      border-bottom: 1px solid var(--border);
    }
    .chart-split-label.before { color: var(--chart-label-before); }
    .chart-split-label.after { color: var(--moved); }
    #pageLoader {
      padding: 0.5rem 0.75rem;
      margin-bottom: 1rem;
      background: var(--loader-bg);
      border: 1px solid var(--loader-border);
      border-radius: 8px;
      font-size: 0.85rem;
      color: var(--loader-fg);
    }
    #pageLoader.hidden { display: none; }
    #bootStatus {
      color: var(--loader-fg);
      font-size: 0.85rem;
      margin: 0 0 1rem;
    }
    #bootError {
      display: none;
      padding: 0.75rem 1rem;
      margin-bottom: 1rem;
      background: var(--error-banner-bg);
      border: 1px solid var(--error-banner-border);
      border-radius: 8px;
      color: var(--error-banner-fg);
      font-size: 0.88rem;
    }
    #teamSyncBanner {
      display: none;
      margin: 0.5rem 0 1rem;
      padding: 0.6rem 0.85rem;
      border-radius: 8px;
      font-size: 0.85rem;
      background: var(--banner-info-bg);
      color: var(--banner-info-fg);
    }
    #teamSyncBanner.banner-pending {
      background: var(--banner-pending-bg);
      color: var(--banner-pending-fg);
    }
    #teamSyncBanner.banner-error {
      background: var(--banner-error-bg);
      color: var(--banner-error-fg);
    }
    #presetBanner {
      display: none;
      padding: 0.65rem 0.85rem;
      margin-bottom: 1rem;
      background: var(--preset-banner-bg);
      border: 1px solid var(--preset-banner-border);
      border-radius: 8px;
      font-size: 0.84rem;
      color: var(--banner-preset-fg);
    }
    #presetBanner strong { color: var(--banner-preset-strong); }
  </style>
</head>
<body>
  <div id="pageLoader">Loading portfolio data…</div>
  <p id="bootStatus">Initialising…</p>
  <div id="presetBanner"></div>
  <div id="teamSyncBanner"></div>
  <div class="save-team-bar" id="saveTeamBar">
    <button type="button" id="btnSaveTeam" class="btn-save-team primary save-team-btn">Save for team</button>
    <span class="save-team-hint" id="saveTeamHint">After moving brands, click Save — everyone on the team sees the same board</span>
  </div>
  <div id="bootError"></div>
  <div class="title-row">
    <div class="title-block">
      <h1>__TITLE__</h1>
      <p class="sub">__COUNTRY__ · brand-level moves · GMV __GMV_PERIOD__ · active/hidden/onboarding only (archived/deleted excluded) · generated __GEN__</p>
    </div>
    <button type="button" id="btnTheme" class="theme-toggle" aria-label="Toggle light or dark mode">Light</button>
  </div>

  <div class="card charts-top" id="chartsTopCard" data-collapse-id="charts">
    <h2>Portfolio split by AM</h2>
    <div class="chart-split-section">
      <h3 class="chart-split-label before">Before moves (original assignment)</h3>
      <div class="chart-grid">
        <div class="chart-panel">
          <h3>Brands · providers · groups</h3>
          <div class="chart-wrap"><canvas id="chartCountsBefore"></canvas></div>
        </div>
        <div class="chart-panel">
          <h3>GMV (last 6 months)</h3>
          <div class="chart-wrap"><canvas id="chartGmvBefore"></canvas></div>
        </div>
      </div>
    </div>
    <div class="chart-split-section">
      <h3 class="chart-split-label after">After moves (current simulation)</h3>
      <div class="chart-grid">
        <div class="chart-panel">
          <h3>Brands · providers · groups</h3>
          <div class="chart-wrap"><canvas id="chartCountsAfter"></canvas></div>
        </div>
        <div class="chart-panel">
          <h3>GMV (last 6 months)</h3>
          <div class="chart-wrap"><canvas id="chartGmvAfter"></canvas></div>
        </div>
      </div>
    </div>
    <div class="chart-moves-row">
      <h3 style="margin:0 0 0.35rem;font-size:0.92rem;color:var(--accent)">What has been moved</h3>
      <p class="moves-chart-summary" id="movesChartSummary"></p>
      <div id="movesChartEmpty" class="chart-empty" style="display:none">No accounts moved yet — drag cards between columns to simulate rebalancing.</div>
      <div id="movesChartWrap">
        <div class="chart-moves-grid">
          <div class="chart-panel">
            <h3>Accounts moved (brands)</h3>
            <div class="chart-wrap chart-wrap-moves"><canvas id="chartMovesAccounts"></canvas></div>
          </div>
          <div class="chart-panel">
            <h3>GMV moved (6 months)</h3>
            <div class="chart-wrap chart-wrap-moves"><canvas id="chartMovesGmv"></canvas></div>
          </div>
        </div>
        <div class="moves-flow-accordion" id="movesFlowAccordion">
          <p class="moves-flow-hint">Click a bar or route below to expand the accounts underneath.</p>
          <div class="move-route-header">
            <span>Route</span>
            <span class="num">Accounts</span>
            <span class="num">Providers</span>
            <span class="num">GMV (6m)</span>
          </div>
          <div id="movesFlowList"></div>
        </div>
      </div>
    </div>
  </div>

  <select id="fSegment" aria-hidden="true"><option value="all">All</option></select>

  <div class="toolbar">
    <button type="button" id="btnReset">Reset all moves</button>
    <button type="button" id="btnApplyMmSuggestions">Apply MM balance</button>
    <button type="button" id="btnExport">Export moves (JSON)</button>
    <button type="button" id="btnExpandAll">Expand all sections</button>
    <button type="button" id="btnCollapseAll">Minimise all sections</button>
  </div>

  <div class="card" id="sfApplyCard" data-collapse-id="sf-apply" data-collapse-title="Salesforce apply preview">
    <h2>Salesforce — parent account preview</h2>
    <p class="sf-apply-summary" id="sfApplySummary">Loading preview…</p>
    <div class="sf-apply-toolbar">
      <button type="button" class="pill active" data-sf-filter="all">All</button>
      <button type="button" class="pill" data-sf-filter="team_agreed">Team agreed owner</button>
      <button type="button" class="pill" data-sf-filter="cognisant">Cognisant → Kimberley Gatt</button>
      <button type="button" class="pill" data-sf-filter="segment">Segment requests</button>
      <button type="button" id="btnSfApplyCopy">Copy apply command</button>
      <a id="btnSfPreviewDownload" href="sf_apply_preview.json" download="sf_apply_preview.json">Download JSON</a>
    </div>
    <div style="overflow-x:auto;max-height:420px;overflow-y:auto">
      <table id="sfApplyTable">
        <thead>
          <tr>
            <th>Action</th>
            <th>Parent account</th>
            <th>Current owner</th>
            <th>New owner / segment</th>
            <th>Brands</th>
          </tr>
        </thead>
        <tbody id="sfApplyBody"></tbody>
      </table>
    </div>
  </div>

  <div class="bulk-bar" id="bulkBar" data-collapse-id="bulk" data-collapse-title="Bulk actions">
    <label><input type="checkbox" id="bulkSelectVisible" /> Select all visible</label>
    <span id="bulkSummary"><strong>0</strong> selected</span>
    <label>Move selected to
      <select id="bulkTargetAm"></select>
    </label>
    <button type="button" id="btnBulkMove">Move selected</button>
    <button type="button" id="btnClearSelection">Clear selection</button>
  </div>

  <div class="legend" data-collapse-id="legend" data-collapse-title="Legend">
    <span><span class="swatch"></span> Original assignment</span>
    <span><span class="swatch moved"></span> Moved (agreed)</span>
    <span><span class="swatch" style="background:var(--pending-incoming-bg);border-color:var(--pending-incoming);box-shadow:inset 2px 0 0 var(--pending-incoming)"></span> Incoming — check your portfolio (until ✓ Agree)</span>
    <span><span class="swatch" style="background:var(--pending-outgoing-bg);border-color:var(--pending-outgoing);border-style:dashed;box-shadow:inset 2px 0 0 var(--pending-outgoing)"></span> Leaving your column (until ✓ Agree)</span>
    <span><span class="swatch mm-suggested"></span> Suggested MM move (Gulcin · Mariem · Yousef only)</span>
    <span>Drag / dropdown moves whole <strong>group</strong> · checkbox bulk moves <strong>selected brands only</strong> (red outline = split)</span>
    <span>Review preset moves with ✓ Agree / ✗ Not agree · click <strong>Save for team</strong> to share decisions live (polls every 4s)</span>
  </div>

  <div class="card" id="balancePlanCard" data-collapse-id="rebalance">
    <h2>Rebalance plan</h2>
    <p class="balance-plan" id="balancePlanSummary"></p>
    <div style="overflow-x:auto">
      <table id="mmSuggestTable">
        <thead>
          <tr>
            <th>Brand</th>
            <th>Group</th>
            <th class="num">GMV (6m)</th>
            <th>From</th>
            <th>To</th>
          </tr>
        </thead>
        <tbody></tbody>
      </table>
    </div>
  </div>

  <div class="card" id="portfolioBoardCard" data-collapse-id="portfolios">
    <h2>Portfolios — drag brands between columns</h2>
    <div class="portfolio-toolbar">
      <label>Search
        <input type="search" id="search" placeholder="Brand or group…" />
      </label>
      <label>Show
        <select id="fShow">
          <option value="all">All brands</option>
          <option value="not-reviewed">Not reviewed yet</option>
        </select>
      </label>
      <span id="portfolioFilterSummary"></span>
      <span id="portfolioApprovalSummary"></span>
      <button type="button" class="btn-save-team primary">Save for team</button>
      <button type="button" id="btnShowApprovals">Jump to next review</button>
    </div>
    <div class="board" id="board"></div>
  </div>

  <div class="summary" id="teamSummary" data-collapse-id="summary" data-collapse-title="Team totals"></div>

  <div class="card">
    <h2>Team by segment</h2>
    <div style="overflow-x:auto">
      <table id="segTable">
        <thead>
          <tr>
            <th>Segment</th>
            <th class="num">Brands</th>
            <th class="num">Providers</th>
            <th class="num">Groups</th>
            <th class="num">GMV (6m)</th>
            <th class="num">Δ Brands</th>
            <th class="num">Δ Providers</th>
            <th class="num">Δ Groups</th>
            <th class="num">Δ GMV</th>
          </tr>
        </thead>
        <tbody></tbody>
      </table>
    </div>
  </div>

  <div class="card">
    <h2>GMV by AM — last 6 months</h2>
    <div style="overflow-x:auto">
      <table id="gmvAmTable">
        <thead></thead>
        <tbody></tbody>
      </table>
    </div>
  </div>

  <script src="chart.umd.min.js" defer></script>
  <script>
let D = null;
let assignments = {};
let brandById = {};
const LS_APPROVALS = 'mt_portfolio_rebalancer_approvals_v1';
const LS_ASSIGNMENTS = 'mt_portfolio_rebalancer_assignments_v1';
let dragId = null;
let chartCountsBefore = null;
let chartGmvBefore = null;
let chartCountsAfter = null;
let chartGmvAfter = null;
let chartMovesAccounts = null;
let chartMovesGmv = null;
let boardRenderHandle = null;
let pageReady = false;
const LS_COLLAPSE = 'mt_portfolio_rebalancer_collapse_v1';
const LS_THEME = 'mt_portfolio_rebalancer_theme';

function chartThemeColors() {
  const s = getComputedStyle(document.documentElement);
  return {
    grid: s.getPropertyValue('--chart-grid').trim() || '#2d3a4f',
    tick: s.getPropertyValue('--chart-tick').trim() || '#8b9bb4',
    legend: s.getPropertyValue('--chart-legend').trim() || '#8b9bb4',
  };
}

function currentTheme() {
  return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
}

function applyTheme(theme) {
  const next = theme === 'light' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  try {
    localStorage.setItem(LS_THEME, next);
  } catch (_) { /* ignore */ }
  const btn = document.getElementById('btnTheme');
  if (btn) {
    btn.textContent = next === 'light' ? 'Dark' : 'Light';
    btn.setAttribute('aria-label', next === 'light' ? 'Switch to dark mode' : 'Switch to light mode');
  }
  if (pageReady && D) renderTopCharts();
}

function initTheme() {
  let theme = currentTheme();
  try {
    const saved = localStorage.getItem(LS_THEME);
    if (saved === 'light' || saved === 'dark') theme = saved;
  } catch (_) { /* ignore */ }
  applyTheme(theme);
}

function toggleTheme() {
  applyTheme(currentTheme() === 'light' ? 'dark' : 'light');
}

const TEAM_STATE_REPO = 'boltable/mt-portfolio-rebalancer';
const TEAM_STATE_PATH = 'public/moves-state.json';
const TEAM_STATE_BRANCH = 'main';
const TEAM_STATE_READ_URLS = [
  `https://raw.githubusercontent.com/${TEAM_STATE_REPO}/${TEAM_STATE_BRANCH}/${TEAM_STATE_PATH}`,
  '/moves-state.json',
];
const GH_STATE_TOKEN = __GH_STATE_TOKEN__;
const TEAM_SYNC_POLL_MS = 4000;

let teamStateVersion = 0;
let teamStateUpdatedAt = '';
let teamStateBlobSha = null;
let teamStateSaving = false;
let teamStateSyncTimer = null;
let teamSyncDirty = false;

const BALANCE_DONORS = ['Gulcin Erguven', 'Mariem Slimen', 'Yousef Moungad'];
const BALANCE_SINK = 'Cognisant';
const BALANCE_EXCLUDED = new Set(['Fiona Borg', 'Alena Tokareva', 'Rico Spagnol']);
const RICO_AM = 'Rico Spagnol';

function isSmbBrand(b) {
  return !!(b.segments && b.segments.SMB);
}

function isMmOnlyBrand(b) {
  return !!(b.segments && b.segments.MM) && !isSmbBrand(b);
}

function isRicoRetainedSmb(b) {
  return isRicoBookLocked(b);
}

function isRicoBookLocked(b) {
  return b && b.original_am === RICO_AM;
}

function isPureSmbBrand(b) {
  return !!(b && b.segments && b.segments.SMB && !b.segments.MM);
}

function ricoSmbU1kToCognisantOk(b) {
  if (!isRicoBookLocked(b) || !isPureSmbBrand(b) || isPimCognisantBlocked(b)) return false;
  return (b.gmv_total || 0) < 1000;
}

function isFionaPimBrand(b) {
  return !!(b && (b.on_pim || b.onPim));
}

function isPimCognisantBlocked(b) {
  return isFionaPimBrand(b);
}

function enforceRicoBook() {
  let n = 0;
  for (const b of D.brands) {
    if (!isRicoBookLocked(b)) continue;
    if (assignments[b.id] === RICO_AM) continue;
    if (assignments[b.id] === BALANCE_SINK && ricoSmbU1kToCognisantOk(b)) continue;
    assignments[b.id] = RICO_AM;
    n += 1;
  }
  return n;
}

function enforcePimNoCognisant() {
  let n = 0;
  for (const b of D.brands) {
    if (!isPimCognisantBlocked(b)) continue;
    if (assignments[b.id] === BALANCE_SINK) {
      assignments[b.id] = b.original_am;
      n += 1;
    }
  }
  return n;
}

function ricoRetainedSmbStats() {
  const list = D.brands.filter(isRicoRetainedSmb);
  return {
    brands: list.length,
    providers: list.reduce((s, b) => s + b.providers, 0),
    gmv: list.reduce((s, b) => s + (b.gmv_total || 0), 0),
  };
}

const selectedIds = new Set();
let moveApprovals = loadApprovals();
let mmBalancePlan = { suggested: new Map(), pool: [], targetGmv: 0, totalGmv: 0 };
let mmSuggestedMoves = mmBalancePlan.suggested;

function groupBrandIds(brandId) {
  const b = brandById[brandId];
  if (!b) return [brandId];
  const key = b.group_key;
  if (!key || !D.group_members || !D.group_members[key]) return [brandId];
  return D.group_members[key];
}

function groupLabel(b) {
  return b.primary_group || '—';
}

function statusBadgeClass(status) {
  const s = String(status || '').toLowerCase();
  if (s === 'active') return 'status-active';
  if (s === 'hidden') return 'status-hidden';
  if (s === 'onboarding') return 'status-onboarding';
  if (s === 'mixed') return 'status-mixed';
  return '';
}

function statusLabel(b) {
  const s = b.primary_status || '—';
  if (s !== 'mixed' || !b.statuses) return s;
  return Object.entries(b.statuses).map(([k, n]) => `${k}:${n}`).join(' ');
}

function isGroupSplit(b) {
  const key = b.group_key;
  if (!key || key.startsWith('__solo_')) return false;
  const ids = D.group_members[key] || [];
  const ams = new Set(ids.map(id => assignments[id]));
  return ams.size > 1;
}

function isMoved(b) {
  return assignments[b.id] !== b.original_am;
}

function isCognisantMove(b) {
  return assignments[b.id] === BALANCE_SINK && b.original_am !== BALANCE_SINK;
}

function isPendingMove(b) {
  if (isCognisantMove(b)) return false;
  if (hasTeamDecision(b.id)) return false;
  return isMoved(b);
}

function boardEntriesForAm(am) {
  const entries = [];
  for (const b of D.brands) {
    const dest = assignments[b.id];
    const pending = isPendingMove(b);
    if (dest === am) {
      let slot = 'normal';
      if (isMoved(b)) slot = pending ? 'incoming-pending' : 'moved-in';
      entries.push({ b, slot });
    } else if (pending && b.original_am === am) {
      entries.push({ b, slot: 'outgoing-pending' });
    }
  }
  return entries;
}

function brandsForAm(am) {
  return D.brands.filter(b => assignments[b.id] === am);
}

function brandsVisibleInColumn(am) {
  const seen = new Set();
  const out = [];
  for (const { b } of boardEntriesForAm(am)) {
    if (seen.has(b.id)) continue;
    seen.add(b.id);
    out.push(b);
  }
  return out;
}

function loadApprovals() {
  try {
    const raw = localStorage.getItem(LS_APPROVALS);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function saveApprovalsLocal() {
  localStorage.setItem(LS_APPROVALS, JSON.stringify(moveApprovals));
  localStorage.setItem(LS_ASSIGNMENTS, JSON.stringify(assignments));
}

function saveApprovals() {
  saveApprovalsLocal();
  teamSyncDirty = true;
  updateSaveTeamButton('dirty');
}

function hasTeamDecision(id) {
  return moveApprovals[id] === true || moveApprovals[id] === false;
}

function proposedDestination(b) {
  const preset = D.preset && D.preset.assignments && D.preset.assignments[b.id];
  if (preset && preset !== b.original_am) return preset;
  return assignments[b.id];
}

function clearSavedAssignments() {
  localStorage.removeItem(LS_ASSIGNMENTS);
}

function updateTeamSyncBanner(msg, tone) {
  const el = document.getElementById('teamSyncBanner');
  if (!el) return;
  if (!msg) {
    el.style.display = 'none';
    el.className = '';
    return;
  }
  el.style.display = 'block';
  el.textContent = msg;
  el.className = tone === 'error' ? 'banner-error' : tone === 'pending' ? 'banner-pending' : '';
}

function toBase64Utf8(str) {
  const bytes = new TextEncoder().encode(str);
  let bin = '';
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin);
}

function buildTeamStatePayload() {
  const decisions = {};
  for (const b of D.brands) {
    if (!hasTeamDecision(b.id)) continue;
    if (isCognisantMove(b)) continue;
    const agreed = moveApprovals[b.id] === true;
    decisions[b.id] = {
      approval: agreed,
      to_am: agreed ? assignments[b.id] : proposedDestination(b),
      from_am: b.original_am,
    };
  }
  return {
    version: teamStateVersion + 1,
    updatedAt: new Date().toISOString(),
    decisions,
  };
}

function normalizeTeamDecisions(state) {
  if (!state) return {};
  if (state.decisions && typeof state.decisions === 'object') {
    return state.decisions;
  }
  const decisions = {};
  const assign = state.assignments || {};
  const appr = state.approvals || {};
  for (const [id, v] of Object.entries(appr)) {
    if (v !== true && v !== false) continue;
    const b = brandById[id];
    if (!b) continue;
    decisions[id] = {
      approval: v,
      to_am: assign[id] || b.original_am,
      from_am: b.original_am,
    };
  }
  return decisions;
}

function teamStateHasDecisions(state) {
  if (!state) return false;
  const d = normalizeTeamDecisions(state);
  return Object.keys(d).length > 0;
}

function applyTeamDecisions(state) {
  if (!state || !D) return false;
  const decisions = normalizeTeamDecisions(state);
  if (!Object.keys(decisions).length) return false;
  let changed = false;
  for (const [id, dec] of Object.entries(decisions)) {
    const b = brandById[id];
    if (!b || typeof dec.approval !== 'boolean') continue;
    if (moveApprovals[id] !== dec.approval) {
      moveApprovals[id] = dec.approval;
      changed = true;
    }
    const target = dec.approval === true
      ? (dec.to_am || assignments[id])
      : b.original_am;
    const safeTarget = isRicoBookLocked(b) ? RICO_AM
      : (isPimCognisantBlocked(b) && target === BALANCE_SINK ? b.original_am : target);
    const cur = assignments[b.id];
    const peers = groupBrandIds(b.id);
    const groupDiffers = peers.some(pid => assignments[pid] !== safeTarget);
    if (cur !== safeTarget || groupDiffers) {
      assignBrandAndGroup(b.id, safeTarget);
      changed = true;
    }
  }
  if (state.version) teamStateVersion = state.version;
  if (state.updatedAt) teamStateUpdatedAt = state.updatedAt;
  saveApprovalsLocal();
  return changed;
}

function reapplyPresetAndTeamDecisions(teamState) {
  for (const b of D.brands) assignments[b.id] = b.original_am;
  moveApprovals = {};
  applyPresetAssignments();
  enforceRicoBook();
  enforcePimNoCognisant();
  applyAutoApproveCognisantMoves();
  if (teamState) applyTeamDecisions(teamState);
  enforceRicoBook();
  enforcePimNoCognisant();
  pruneApprovals();
}

async function readTeamStateFromNetwork() {
  for (const base of TEAM_STATE_READ_URLS) {
    try {
      const url = base + (base.includes('?') ? '&' : '?') + 't=' + Date.now();
      const res = await fetch(url, { cache: 'no-store' });
      if (!res.ok) continue;
      const data = await res.json();
      if (data && typeof data === 'object') return data;
    } catch (e) {
      console.warn('team state read failed', base, e);
    }
  }
  return null;
}

async function fetchTeamStateMeta(syncVersionFromRemote) {
  if (!GH_STATE_TOKEN) return null;
  try {
    const res = await fetch(
      `https://api.github.com/repos/${TEAM_STATE_REPO}/contents/${TEAM_STATE_PATH}?ref=${TEAM_STATE_BRANCH}`,
      { headers: { Authorization: `Bearer ${GH_STATE_TOKEN}`, Accept: 'application/vnd.github+json' } }
    );
    if (!res.ok) return null;
    const meta = await res.json();
    teamStateBlobSha = meta.sha || null;
    if (meta.content) {
      const json = JSON.parse(atob(meta.content.replace(/\\n/g, '')));
      if (syncVersionFromRemote && json.version) {
        teamStateVersion = Math.max(teamStateVersion, json.version);
      }
      return json;
    }
  } catch (e) {
    console.warn('team state meta fetch failed', e);
  }
  return null;
}

async function initTeamState() {
  setBootStatus('Loading team decisions…');
  let state = null;
  if (GH_STATE_TOKEN) state = await fetchTeamStateMeta();
  if (!state) state = await readTeamStateFromNetwork();
  const embeddedV = (D && D.team_decisions_version) || 0;
  if (embeddedV > teamStateVersion) teamStateVersion = embeddedV;
  if (teamStateHasDecisions(state)) {
    const remoteV = state.version || 0;
    if (remoteV >= teamStateVersion) {
      applyTeamDecisions(state);
    }
    const n = Object.keys(normalizeTeamDecisions(state)).length;
    updateTeamSyncBanner(
      GH_STATE_TOKEN
        ? `Team sync on · v${teamStateVersion} · ${n} saved decision(s) · ${teamStateUpdatedAt ? new Date(teamStateUpdatedAt).toLocaleString() : '—'}`
        : `Loaded ${n} team decision(s) (read-only — rebuild with GH token to enable live save)`,
      'ok'
    );
    return true;
  }
  if (embeddedV > 0 && D.team_decisions) {
    updateTeamSyncBanner(
      `Embedded team decisions v${embeddedV} · ${Object.keys(D.team_decisions).length} saved`,
      'ok'
    );
    return true;
  }
  if (state && state.version) {
    teamStateVersion = state.version;
    teamStateUpdatedAt = state.updatedAt || '';
  }
  if (GH_STATE_TOKEN) {
    updateTeamSyncBanner('Team sync on · preset loaded — agree/not agree then Save for team', 'ok');
  }
  return false;
}

function updateSaveTeamButton(state) {
  const btns = document.querySelectorAll('.btn-save-team');
  if (!btns.length) return;
  const hint = document.getElementById('saveTeamHint');
  for (const btn of btns) {
    btn.classList.remove('save-dirty', 'save-ok', 'save-error');
    if (!GH_STATE_TOKEN) {
      btn.disabled = true;
      btn.textContent = 'Save for team (offline)';
      btn.title = 'Team sync token missing on this build';
      continue;
    }
    if (state === 'saving') {
      btn.disabled = true;
      btn.textContent = 'Saving…';
      continue;
    }
    btn.disabled = false;
    if (state === 'ok') {
      btn.textContent = 'Saved for team ✓';
      btn.classList.add('save-ok');
      continue;
    }
    if (state === 'error') {
      btn.textContent = 'Save failed — retry';
      btn.classList.add('save-error');
      continue;
    }
    if (state === 'dirty' || teamSyncDirty) {
      btn.textContent = 'Save for team *';
      btn.classList.add('save-dirty');
      continue;
    }
    btn.textContent = 'Save for team';
  }
  if (hint) {
    if (!GH_STATE_TOKEN) {
      hint.textContent = 'Team save not configured on this build — moves only save in your browser';
    } else if (state === 'saving') {
      hint.textContent = 'Saving to shared board…';
    } else if (state === 'ok') {
      hint.textContent = 'Saved — teammates will see updates within a few seconds';
    } else if (state === 'error') {
      hint.textContent = 'Save failed — click Save for team to retry';
    } else if (teamSyncDirty) {
      hint.textContent = 'Unsaved decisions — click Save for team to update the live board';
    } else {
      hint.textContent = 'Agree or not agree to preset moves, then Save for team — everyone sees updates within seconds';
    }
  }
  if (state === 'ok') {
    setTimeout(() => updateSaveTeamButton(teamSyncDirty ? 'dirty' : 'idle'), 3500);
  }
}

async function pushTeamState() {
  if (!GH_STATE_TOKEN || teamStateSaving) return false;
  teamStateSaving = true;
  updateTeamSyncBanner('Saving team moves…', 'pending');
  updateSaveTeamButton('saving');
  try {
    for (let attempt = 0; attempt < 3; attempt++) {
      await fetchTeamStateMeta(true);
      const payload = buildTeamStatePayload();
      const remote = await readTeamStateFromNetwork();
      if (remote) {
        const remoteDec = normalizeTeamDecisions(remote);
        payload.decisions = { ...remoteDec, ...payload.decisions };
        payload.version = Math.max(teamStateVersion, remote.version || 0) + 1;
      }
      const body = {
        message: `Portfolio team decisions v${payload.version}`,
        content: toBase64Utf8(JSON.stringify(payload, null, 2)),
        branch: TEAM_STATE_BRANCH,
      };
      if (teamStateBlobSha) body.sha = teamStateBlobSha;
      const res = await fetch(
        `https://api.github.com/repos/${TEAM_STATE_REPO}/contents/${TEAM_STATE_PATH}`,
        {
          method: 'PUT',
          headers: {
            Authorization: `Bearer ${GH_STATE_TOKEN}`,
            Accept: 'application/vnd.github+json',
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(body),
        }
      );
      if (res.ok) {
        const data = await res.json();
        teamStateBlobSha = (data.content && data.content.sha) || teamStateBlobSha;
        teamStateVersion = payload.version;
        teamStateUpdatedAt = payload.updatedAt;
        teamSyncDirty = false;
        saveApprovalsLocal();
        updateTeamSyncBanner(
          `Team sync on · saved v${teamStateVersion} · ${new Date(teamStateUpdatedAt).toLocaleTimeString()}`,
          'ok'
        );
        updateSaveTeamButton('ok');
        return true;
      }
      if (res.status === 409 && attempt < 2) continue;
      const err = await res.text();
      throw new Error('GitHub ' + res.status + ': ' + err.slice(0, 240));
    }
    throw new Error('GitHub save failed after retries');
  } catch (e) {
    console.error(e);
    updateTeamSyncBanner('Team save failed — ' + (e.message || e) + ' · click Save for team to retry', 'error');
    updateSaveTeamButton('error');
    return false;
  } finally {
    teamStateSaving = false;
  }
}

async function saveTeamStateNow() {
  if (!GH_STATE_TOKEN) {
    updateTeamSyncBanner('Team save unavailable — rebuild dashboard with MT_PORTFOLIO_GH_TOKEN', 'error');
    updateSaveTeamButton('error');
    return false;
  }
  return pushTeamState();
}

async function pullTeamStateIfNewer() {
  if (!D || dragId || teamStateSaving) return;
  const state = await readTeamStateFromNetwork();
  if (!state) return;
  if (state.version <= teamStateVersion && state.updatedAt === teamStateUpdatedAt) return;
  if (teamSyncDirty && state.version < teamStateVersion) return;
  const prev = JSON.stringify(moveApprovals);
  reapplyPresetAndTeamDecisions(state);
  const changed = prev !== JSON.stringify(moveApprovals) || D.brands.some(b => {
    const preset = D.preset && D.preset.assignments && D.preset.assignments[b.id];
    return preset && assignments[b.id] !== b.original_am;
  });
  teamStateVersion = state.version || teamStateVersion;
  teamStateUpdatedAt = state.updatedAt || teamStateUpdatedAt;
  if (changed) {
    refresh();
    updateTeamSyncBanner(
      `Team sync · pulled v${teamStateVersion} · ${new Date(teamStateUpdatedAt).toLocaleTimeString()}`,
      'ok'
    );
  }
}

function startTeamSyncPolling() {
  if (teamStateSyncTimer) clearInterval(teamStateSyncTimer);
  teamStateSyncTimer = setInterval(() => pullTeamStateIfNewer(), TEAM_SYNC_POLL_MS);
}

function loadSavedAssignments() {
  try {
    const raw = localStorage.getItem(LS_ASSIGNMENTS);
    if (!raw) return false;
    const saved = JSON.parse(raw);
    if (!saved || typeof saved !== 'object') return false;
    const validAms = new Set(D.ams.map(a => a.name));
    for (const b of D.brands) {
      const am = saved[b.id];
      if (am && validAms.has(am)) assignments[b.id] = am;
    }
    const rawAp = localStorage.getItem(LS_APPROVALS);
    if (rawAp) {
      try {
        Object.assign(moveApprovals, JSON.parse(rawAp));
      } catch (_) { /* ignore */ }
    }
    return D.brands.some(b => assignments[b.id] !== b.original_am);
  } catch {
    return false;
  }
}

function needsSignOff(b) {
  if (isCognisantMove(b)) return false;
  if (hasTeamDecision(b.id)) return true;
  return isMoved(b) || isMmSuggested(b);
}

function signOffItems() {
  const items = [];
  const seen = new Set();
  for (const b of D.brands.filter(isMoved)) {
    items.push({ b, kind: 'active', from: b.original_am, to: assignments[b.id] });
    seen.add(b.id);
  }
  for (const b of D.brands) {
    if (!hasTeamDecision(b.id) || seen.has(b.id)) continue;
    items.push({
      b,
      kind: teamAgrees(b.id) ? 'agreed' : 'rejected',
      from: b.original_am,
      to: proposedDestination(b),
    });
    seen.add(b.id);
  }
  for (const [id, to] of mmSuggestedMoves) {
    if (seen.has(id)) continue;
    const b = brandById[id];
    if (!b || isRicoRetainedSmb(b)) continue;
    items.push({ b, kind: 'suggested', from: b.original_am, to });
    seen.add(id);
  }
  return items.sort((a, b) => a.b.brand_name.localeCompare(b.b.brand_name));
}

function pruneApprovals() {
  let changed = false;
  for (const id of Object.keys(moveApprovals)) {
    if (hasTeamDecision(id)) continue;
    const b = brandById[id];
    if (!b || !isMoved(b)) {
      delete moveApprovals[id];
      changed = true;
    }
  }
  if (changed) saveApprovalsLocal();
}

function teamAgrees(id) {
  return moveApprovals[id] === true;
}

function teamDisagrees(id) {
  return moveApprovals[id] === false;
}

function approvalLabel(id) {
  if (teamAgrees(id)) return 'Agreed';
  if (teamDisagrees(id)) return 'Not agreed';
  return 'Not reviewed';
}

function approvalPillHtml(id) {
  if (teamAgrees(id)) return '<span class="approval-pill agreed">AGREED</span>';
  if (teamDisagrees(id)) return '<span class="approval-pill not-agreed">NOT AGREED</span>';
  return '';
}

function approvalActionsHtml(id) {
  const agreed = teamAgrees(id);
  const disagreed = teamDisagrees(id);
  return `<div class="signoff-actions" onclick="event.stopPropagation()">
    <button type="button" class="signoff-btn agree${agreed ? ' active' : ''}"
      onclick="setMoveApproval('${id}', true)">✓ Agree</button>
    <button type="button" class="signoff-btn disagree${disagreed ? ' active' : ''}"
      onclick="setMoveApproval('${id}', false)">✗ No</button>
  </div>`;
}

function approvalStatusOnCard(id) {
  if (teamAgrees(id)) return '<span class="card-approval-status agreed">Agreed</span>';
  if (teamDisagrees(id)) return '<span class="card-approval-status not-agreed">Not agreed</span>';
  return '<span class="card-approval-status">Not reviewed</span>';
}

function approvalRowHtml(b) {
  if (!needsSignOff(b)) return '';
  return `<div class="card-approval" onclick="event.stopPropagation()" onmousedown="event.stopPropagation()">
    <span class="card-approval-label">Team agrees to move? ${approvalStatusOnCard(b.id)}</span>
    ${approvalActionsHtml(b.id)}
  </div>`;
}

function setMoveApproval(id, value) {
  const b = brandById[id];
  if (!b) return;
  if (value === true) {
    moveApprovals[id] = true;
    const dest = proposedDestination(b);
    if (dest && dest !== b.original_am) assignments[id] = dest;
  } else if (value === false) {
    moveApprovals[id] = false;
    assignments[id] = b.original_am;
  } else {
    delete moveApprovals[id];
  }
  saveApprovals();
  refresh();
}

function approvalCounts() {
  const items = signOffItems();
  let agreed = 0;
  let notAgreed = 0;
  let pending = 0;
  for (const { b } of items) {
    if (teamAgrees(b.id)) agreed += 1;
    else if (teamDisagrees(b.id)) notAgreed += 1;
    else pending += 1;
  }
  return { agreed, notAgreed, pending, total: items.length };
}

function isMmSuggested(b) {
  return mmSuggestedMoves.has(b.id) && assignments[b.id] === b.original_am;
}

function buildMmUnits() {
  const pool = D.brands.filter(b =>
    isMmOnlyBrand(b) &&
    BALANCE_DONORS.includes(b.original_am) &&
    !BALANCE_EXCLUDED.has(b.original_am)
  );
  const seen = new Set();
  const units = [];
  for (const b of pool) {
    if (seen.has(b.id)) continue;
    const ids = groupBrandIds(b.id).filter(id => {
      const x = brandById[id];
      return x && isMmOnlyBrand(x) && BALANCE_DONORS.includes(x.original_am);
    });
    ids.forEach(id => seen.add(id));
    if (!ids.length) continue;
    const cur = assignments[ids[0]];
    if (!BALANCE_DONORS.includes(cur)) continue;
    const brands = ids.map(id => brandById[id]).filter(Boolean);
    units.push({
      ids,
      brands,
      gmv: brands.reduce((s, x) => s + (x.gmv_total || 0), 0),
      currentAm: cur,
      rep: ids[0],
      groupLabel: groupLabel(brands[0]),
    });
  }
  return units;
}

function computeMmBalanceSuggestions() {
  const units = buildMmUnits();
  const totalGmv = units.reduce((s, u) => s + u.gmv, 0);
  const targetGmv = units.length ? totalGmv / BALANCE_DONORS.length : 0;

  const gmvByAm = Object.fromEntries(BALANCE_DONORS.map(am => [am, 0]));
  const unitsByAm = Object.fromEntries(BALANCE_DONORS.map(am => [am, []]));
  for (const u of units) {
    gmvByAm[u.currentAm] += u.gmv;
    unitsByAm[u.currentAm].push(u);
  }

  const suggested = new Map();
  const movedUnits = new Set();
  const tol = 0.03;

  function mostOver() {
    return BALANCE_DONORS
      .filter(am => gmvByAm[am] > targetGmv * (1 + tol))
      .sort((a, b) => gmvByAm[b] - gmvByAm[a])[0];
  }
  function mostUnder() {
    return BALANCE_DONORS
      .filter(am => gmvByAm[am] < targetGmv * (1 - tol))
      .sort((a, b) => gmvByAm[a] - gmvByAm[b])[0];
  }

  let guard = 0;
  while (mostOver() && mostUnder() && guard < units.length * 2) {
    guard += 1;
    const from = mostOver();
    const to = mostUnder();
    const pick = unitsByAm[from]
      .filter(u => !movedUnits.has(u.rep))
      .sort((a, b) => a.gmv - b.gmv)[0];
    if (!pick) break;
    movedUnits.add(pick.rep);
    for (const id of pick.ids) suggested.set(id, to);
    gmvByAm[from] -= pick.gmv;
    gmvByAm[to] += pick.gmv;
  }

  const pool = units.flatMap(u => u.brands);
  return { suggested, pool, targetGmv, totalGmv, projected: BALANCE_DONORS.map(am => ({
    am, gmv: gmvByAm[am],
  })) };
}

function euro(n) {
  n = Number(n) || 0;
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return '€' + (n / 1_000_000).toFixed(2) + 'M';
  if (abs >= 1_000) return '€' + Math.round(n).toLocaleString('en-GB');
  return '€' + n.toLocaleString('en-GB', { maximumFractionDigits: 0 });
}

function euroDelta(cur, orig) {
  const d = cur - orig;
  if (Math.abs(d) < 0.5) return '<span class="delta-zero">±€0</span>';
  const cls = d > 0 ? 'delta-up' : 'delta-down';
  const sign = d > 0 ? '+' : '−';
  return `<span class="${cls}">${sign}${euro(Math.abs(d)).replace('€', '€')}</span>`;
}

function amStats(am) {
  const brands = brandsVisibleInColumn(am);
  const groupSet = new Set();
  let providers = 0;
  let gmv = 0;
  const gmvByMonth = Object.fromEntries(D.gmv_month_keys.map(mk => [mk, 0]));
  const segCounts = {};
  for (const b of brands) {
    providers += b.providers;
    gmv += b.gmv_total || 0;
    for (const mk of D.gmv_month_keys) {
      gmvByMonth[mk] += (b.gmv_by_month && b.gmv_by_month[mk]) || 0;
    }
    for (const g of b.group_names) groupSet.add(g);
    for (const [s, n] of Object.entries(b.segments)) {
      segCounts[s] = (segCounts[s] || 0) + n;
    }
  }
  return {
    brands: brands.length,
    providers,
    groups: groupSet.size,
    gmv,
    gmvByMonth,
    segCounts,
  };
}

function teamStats() {
  const out = { brands: D.brands.length, providers: 0, groups: new Set(), gmv: 0, segCounts: {}, segGmv: {} };
  for (const b of D.brands) {
    out.providers += b.providers;
    out.gmv += b.gmv_total || 0;
    for (const g of b.group_names) out.groups.add(g);
    for (const [seg, n] of Object.entries(b.segments)) {
      out.segCounts[seg] = (out.segCounts[seg] || 0) + n;
    }
    for (const [seg, val] of Object.entries(b.segment_gmv || {})) {
      out.segGmv[seg] = (out.segGmv[seg] || 0) + val;
    }
  }
  return {
    brands: out.brands,
    providers: out.providers,
    groups: out.groups.size,
    gmv: out.gmv,
    segCounts: out.segCounts,
    segGmv: out.segGmv,
  };
}

function originalTeamStats() {
  const out = { brands: D.brands.length, providers: 0, groups: new Set(), gmv: 0, segCounts: {}, segGmv: {} };
  for (const b of D.brands) {
    out.providers += b.providers;
    out.gmv += b.gmv_total || 0;
    for (const g of b.group_names) out.groups.add(g);
    for (const [seg, n] of Object.entries(b.segments)) {
      out.segCounts[seg] = (out.segCounts[seg] || 0) + n;
    }
    for (const [seg, val] of Object.entries(b.segment_gmv || {})) {
      out.segGmv[seg] = (out.segGmv[seg] || 0) + val;
    }
  }
  return { ...out, groups: out.groups.size };
}

function originalAmStats(am) {
  const saved = { ...assignments };
  for (const b of D.brands) assignments[b.id] = b.original_am;
  const stats = amStats(am);
  Object.assign(assignments, saved);
  return stats;
}

function deltaFmt(cur, orig) {
  const d = cur - orig;
  if (d === 0) return '<span class="delta-zero">±0</span>';
  const cls = d > 0 ? 'delta-up' : 'delta-down';
  const sign = d > 0 ? '+' : '';
  return `<span class="${cls}">${sign}${d}</span>`;
}

function renderSummary() {
  const cur = teamStats();
  const orig = originalTeamStats();
  const moved = D.brands.filter(isMoved).length;
  const appr = approvalCounts();
  const el = document.querySelector('#teamSummary .collapse-body') || document.getElementById('teamSummary');
  el.innerHTML = [
    ['Brands', cur.brands, orig.brands, false],
    ['Providers', cur.providers, orig.providers, false],
    ['Groups', cur.groups, orig.groups, false],
    ['GMV (6 months)', cur.gmv, orig.gmv, true],
    ['Moved brands', moved, 0, false],
    ['Team agreed', appr.agreed, 0, false],
    ['Not agreed', appr.notAgreed, 0, false],
    ['Not reviewed', appr.pending, 0, false],
  ].map(([label, val, base, isMoney]) => `
    <div class="stat">
      <div class="label">${label}</div>
      <div class="value">${isMoney ? euro(val) : val}</div>
      ${label.startsWith('Moved') ? '' : `<div class="delta">vs original: ${isMoney ? euroDelta(val, base) : deltaFmt(val, base)}</div>`}
    </div>
  `).join('');
}

function renderSegmentTable() {
  const cur = teamStats();
  const orig = originalTeamStats();
  const segs = [...new Set([...Object.keys(orig.segCounts), ...Object.keys(cur.segCounts)])].sort();
  const tbody = document.querySelector('#segTable tbody');
  tbody.innerHTML = segs.map(seg => {
    const cB = brandsInSegment(seg);
    const oB = brandsInSegmentOrig(seg);
    return `<tr>
      <td>${esc(seg)}</td>
      <td class="num">${cB.brands}</td>
      <td class="num">${cB.providers}</td>
      <td class="num">${cB.groups}</td>
      <td class="num">${euro(cB.gmv)}</td>
      <td class="num">${deltaFmt(cB.brands, oB.brands)}</td>
      <td class="num">${deltaFmt(cB.providers, oB.providers)}</td>
      <td class="num">${deltaFmt(cB.groups, oB.groups)}</td>
      <td class="num">${euroDelta(cB.gmv, oB.gmv)}</td>
    </tr>`;
  }).join('');
}

function brandsInSegment(seg) {
  const groupSet = new Set();
  let providers = 0;
  let brands = 0;
  let gmv = 0;
  for (const b of D.brands) {
    if (!b.segments[seg]) continue;
    brands += 1;
    providers += b.segments[seg];
    gmv += (b.segment_gmv && b.segment_gmv[seg]) || 0;
    for (const g of b.group_names) groupSet.add(g);
  }
  return { brands, providers, groups: groupSet.size, gmv };
}

function brandsInSegmentOrig(seg) {
  return brandsInSegment(seg);
}

function monthLabel(mk) {
  const [y, m] = mk.split('-').map(Number);
  const names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  return names[m - 1] + ' ' + String(y).slice(2);
}

function renderGmvAmTable() {
  const thead = document.querySelector('#gmvAmTable thead');
  const tbody = document.querySelector('#gmvAmTable tbody');
  const monthCols = D.gmv_month_keys.map(mk => `<th class="num">${esc(monthLabel(mk))}</th>`).join('');
  thead.innerHTML = `<tr><th>AM</th>${monthCols}<th class="num">Total (6m)</th><th class="num">Δ GMV vs original</th></tr>`;
  tbody.innerHTML = D.ams.map(am => {
    const cur = amStats(am.name);
    const orig = originalAmStats(am.name);
    const monthCells = D.gmv_month_keys.map(mk =>
      `<td class="num">${euro(cur.gmvByMonth[mk] || 0)}</td>`
    ).join('');
    return `<tr>
      <td>${esc(am.name)}</td>
      ${monthCells}
      <td class="num"><strong>${euro(cur.gmv)}</strong></td>
      <td class="num">${euroDelta(cur.gmv, orig.gmv)}</td>
    </tr>`;
  }).join('');
}

function isAwaitingReview(b) {
  if (isCognisantMove(b)) return false;
  if (hasTeamDecision(b.id)) return false;
  return isMoved(b);
}

function passesFilter(b) {
  const q = (document.getElementById('search').value || '').trim().toLowerCase();
  const show = document.getElementById('fShow')?.value || 'all';
  if (q) {
    const blob = (b.brand_name + ' ' + groupLabel(b) + ' ' + (b.group_names || []).join(' ')).toLowerCase();
    if (!blob.includes(q)) return false;
  }
  if (show === 'not-reviewed' && !isAwaitingReview(b)) return false;
  return true;
}

function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function setAssignment(id, toAm) {
  const b = brandById[id];
  if (!b || !D.ams.some(a => a.name === toAm)) return;
  if (isRicoBookLocked(b) && toAm !== RICO_AM) return;
  if (isPimCognisantBlocked(b) && toAm === BALANCE_SINK) return;
  const wasMoved = assignments[id] !== b.original_am;
  const willMove = toAm !== b.original_am;
  assignments[id] = toAm;
  if (toAm === BALANCE_SINK && willMove) {
    moveApprovals[id] = true;
  } else if (wasMoved !== willMove) {
    delete moveApprovals[id];
  }
}

function assignBrandAndGroup(id, toAm) {
  const anchor = brandById[id];
  if (!anchor || !D.ams.some(a => a.name === toAm)) return;
  const movingRetainedSmb = isRicoRetainedSmb(anchor);
  for (const peerId of groupBrandIds(id)) {
    const peer = brandById[peerId];
    if (!movingRetainedSmb && isRicoRetainedSmb(peer)) continue;
    if (toAm === BALANCE_SINK && isPimCognisantBlocked(peer)) continue;
    setAssignment(peerId, toAm);
  }
}

function moveBrand(id, toAm) {
  if (!D.ams.some(a => a.name === toAm)) return;
  assignBrandAndGroup(id, toAm);
  saveApprovals();
  refresh();
}

function toggleBrandSelect(id, checked) {
  if (checked) selectedIds.add(id);
  else selectedIds.delete(id);
  syncSelectionUi();
}

function syncSelectionUi() {
  document.querySelectorAll('.brand[data-id]').forEach(el => {
    const pid = el.dataset.id;
    const on = selectedIds.has(pid);
    el.classList.toggle('selected', on);
    const cb = el.querySelector('.brand-select');
    if (cb) cb.checked = on;
  });
  updateBulkBar();
  const vis = D.brands.filter(passesFilter);
  const visSelected = vis.filter(b => selectedIds.has(b.id)).length;
  const bulkVis = document.getElementById('bulkSelectVisible');
  if (bulkVis) {
    bulkVis.indeterminate = visSelected > 0 && visSelected < vis.length;
    bulkVis.checked = vis.length > 0 && visSelected === vis.length;
  }
}

function updateBulkBar() {
  const el = document.getElementById('bulkSummary');
  if (!el) return;
  const n = selectedIds.size;
  const gmv = [...selectedIds].reduce((s, id) => s + (brandById[id]?.gmv_total || 0), 0);
  const prov = [...selectedIds].reduce((s, id) => s + (brandById[id]?.providers || 0), 0);
  el.innerHTML = n
    ? `<strong>${n}</strong> selected · <strong>${prov}</strong> providers · <strong>${euro(gmv)}</strong> GMV`
    : '<strong>0</strong> selected';
}

function selectAllVisible(checked) {
  if (!checked) {
    selectedIds.clear();
    refresh();
    return;
  }
  for (const b of D.brands) {
    if (passesFilter(b)) selectedIds.add(b.id);
  }
  refresh();
}

function moveSelectedBulk() {
  const to = document.getElementById('bulkTargetAm')?.value;
  if (!to || !selectedIds.size) return;
  for (const id of selectedIds) setAssignment(id, to);
  saveApprovals();
  selectedIds.clear();
  refresh();
}

function clearSelection() {
  selectedIds.clear();
  const bulkVis = document.getElementById('bulkSelectVisible');
  if (bulkVis) bulkVis.checked = false;
  refresh();
}

function populateBulkTargetAm() {
  const sel = document.getElementById('bulkTargetAm');
  if (!sel) return;
  sel.innerHTML = D.ams.map(am =>
    `<option value="${esc(am.name)}">${esc(am.name)}</option>`
  ).join('');
}

function renderBoard() {
  const board = document.getElementById('board');
  board.innerHTML = D.ams.map(am => {
    const stats = amStats(am.name);
    const segLine = Object.entries(stats.segCounts)
      .sort((a,b) => b[1]-a[1])
      .slice(0, 3)
      .map(([s,n]) => `${esc(s)}: ${n}`)
      .join(' · ');
    const cards = boardEntriesForAm(am.name)
      .filter(({ b }) => passesFilter(b))
      .sort((a, b) => (b.b.gmv_total || 0) - (a.b.gmv_total || 0) || b.b.providers - a.b.providers || a.b.brand_name.localeCompare(b.b.brand_name))
      .map(({ b, slot }) => brandCardHtml(b, am.name, slot))
      .join('');
    const extraCls = am.slug === 'cognisant' ? ' extra-am' : '';
    return `<div class="col${extraCls}" data-am="${esc(am.name)}"
      ondragover="onDragOver(event)" ondragleave="onDragLeave(event)" ondrop="onDrop(event)">
      <div class="col-head">
        <h3>${esc(am.name)}</h3>
        <div class="role">${esc(am.role_segment)}</div>
        <div class="col-totals">
          <span><strong>${stats.brands}</strong> brands</span>
          <span><strong>${stats.providers}</strong> prov</span>
          <span><strong>${stats.groups}</strong> groups</span>
          <span><strong>${euro(stats.gmv)}</strong> GMV</span>
        </div>
        ${segLine ? `<div class="col-totals" style="margin-top:0.2rem">${segLine}</div>` : ''}
      </div>
      <div class="col-body">${cards || `<div style="color:var(--muted);font-size:0.75rem;padding:0.5rem">${am.slug === 'cognisant' ? 'Empty — drag brands here' : 'No brands'}</div>`}</div>
    </div>`;
  }).join('');
}

function brandCardHtml(b, currentAm, slot) {
  slot = slot || (assignments[b.id] === currentAm ? (isMoved(b) ? 'moved-in' : 'normal') : 'outgoing-pending');
  const moved = isMoved(b);
  const agreed = teamAgrees(b.id);
  const disagreed = teamDisagrees(b.id);
  const pending = isPendingMove(b);
  const destAm = assignments[b.id];
  const mmSuggested = isMmSuggested(b);
  const mmTarget = mmSuggested ? mmSuggestedMoves.get(b.id) : '';
  const split = isGroupSplit(b);
  const peers = groupBrandIds(b.id).length;
  const selected = selectedIds.has(b.id);
  const ricoLocked = isRicoBookLocked(b);
  const fionaPim = isFionaPimBrand(b);
  const signOff = needsSignOff(b);
  const isOutgoing = slot === 'outgoing-pending';
  const isIncomingPending = slot === 'incoming-pending';
  const cls = [
    isIncomingPending ? 'pending-incoming' : '',
    isOutgoing ? 'pending-outgoing' : '',
    moved && agreed && !isOutgoing ? 'moved' : '',
    disagreed ? 'not-agreed-veto' : '',
    mmSuggested ? 'mm-suggested' : '',
    ricoLocked ? 'smb-policy' : '',
    signOff && !agreed ? 'needs-approval' : '',
    split ? 'group-split' : '',
    selected ? 'selected' : '',
  ].filter(Boolean).join(' ');
  const opts = D.ams.map(a =>
    `<option value="${esc(a.name)}" ${a.name === (isOutgoing ? b.original_am : destAm) ? 'selected' : ''}>${esc(a.name)}</option>`
  ).join('');
  const incomingPill = isIncomingPending
    ? '<span class="pending-incoming-pill">INCOMING — CHECK</span>' : '';
  const outgoingPill = isOutgoing
    ? `<span class="pending-outgoing-pill">LEAVING → ${esc(amShortName(destAm))}</span>` : '';
  const movedPill = moved && agreed && !isOutgoing && !isIncomingPending
    ? '<span class="moved-pill">MOVED</span>' : '';
  const dragAttrs = isOutgoing
    ? 'draggable="false"'
    : 'draggable="true" ondragstart="onDragStart(event)" ondragend="onDragEnd(event)"';
  return `<div class="brand ${cls}" ${dragAttrs} data-id="${b.id}" data-slot="${slot}">
    <label class="brand-check" onclick="event.stopPropagation()">
      <input type="checkbox" class="brand-select" ${selected ? 'checked' : ''}
        onchange="toggleBrandSelect('${b.id}', this.checked)" />
      <div class="brand-title">
        <div class="brand-name">${esc(b.brand_name)}${ricoLocked ? '<span class="smb-policy-pill">KEPT ON RICO</span>' : ''}${fionaPim ? `<span class="smb-policy-pill" title="PIM catalog (SF account) — stays on Fiona, not Cognisant${b.pim_accounts ? ' · ' + b.pim_accounts + ' account(s)' : ''}">PIM</span>` : ''}${incomingPill}${outgoingPill}${movedPill}${needsSignOff(b) ? approvalPillHtml(b.id) : ''}${mmSuggested ? `<span class="mm-suggested-pill">→ ${esc(amShortName(mmTarget))}</span>` : ''}${split ? '<span class="group-pill">SPLIT GROUP</span>' : ''}</div>
      </div>
    </label>
    <div class="brand-meta">
      <span class="badge group-badge" title="${esc(groupLabel(b))}">${esc(groupLabel(b))}</span>
      ${peers > 1 ? `<span>${peers} brands/grp</span>` : ''}
      <span>${euro(b.gmv_total || 0)} GMV</span>
      <span>${b.providers} prov</span>
      <span class="badge ${statusBadgeClass(b.primary_status)}">${esc(statusLabel(b))}</span>
      <span class="badge">${esc(b.primary_segment)}</span>
    </div>
    ${isIncomingPending ? `<div class="brand-meta" style="color:var(--pending-incoming)">from: ${esc(b.original_am)} · pending your ✓ Agree</div>` : ''}
    ${isOutgoing ? `<div class="brand-meta" style="color:var(--pending-outgoing)">moving to: ${esc(destAm)} · still in your column until agreed</div>` : ''}
    ${moved && agreed && !isOutgoing ? `<div class="brand-meta" style="color:var(--moved)">was: ${esc(b.original_am)}</div>` : ''}
    ${mmSuggested ? `<div class="brand-meta" style="color:var(--mm-suggested)">suggested → ${esc(amShortName(mmTarget))}</div>` : ''}
    ${approvalRowHtml(b)}
    ${isOutgoing ? '' : `<div class="move-row">
      <select onchange="moveBrand('${b.id}', this.value)" onclick="event.stopPropagation()">${opts}</select>
    </div>`}
  </div>`;
}

function updatePortfolioApprovalSummary() {
  const el = document.getElementById('portfolioApprovalSummary');
  if (!el) return;
  const appr = approvalCounts();
  if (!appr.total) {
    el.innerHTML = '';
    return;
  }
  el.innerHTML =
    `Approvals: <strong>${appr.agreed}</strong> agreed · ` +
    `<strong>${appr.notAgreed}</strong> no · ` +
    `<strong>${appr.pending}</strong> pending`;
}

function onDragStart(e) {
  dragId = e.currentTarget.dataset.id;
  e.dataTransfer.effectAllowed = 'move';
  e.currentTarget.style.opacity = '0.5';
}
function onDragEnd(e) {
  e.currentTarget.style.opacity = '';
  dragId = null;
  document.querySelectorAll('.col.drag-over').forEach(c => c.classList.remove('drag-over'));
}
function onDragOver(e) {
  e.preventDefault();
  e.currentTarget.classList.add('drag-over');
}
function onDragLeave(e) {
  e.currentTarget.classList.remove('drag-over');
}
function onDrop(e) {
  e.preventDefault();
  const am = e.currentTarget.dataset.am;
  if (dragId && am) moveBrand(dragId, am);
  e.currentTarget.classList.remove('drag-over');
}

function exportMoves() {
  const moves = signOffItems().map(({ b, kind, from, to }) => ({
    brand_name: b.brand_name,
    brand_key: b.brand_key,
    providers: b.providers,
    groups: b.groups,
    gmv_total: b.gmv_total,
    gmv_by_month: b.gmv_by_month,
    from_am: from,
    to_am: to,
    move_kind: kind,
    primary_segment: b.primary_segment,
    team_agrees: isCognisantMove(b) ? true : (teamAgrees(b.id) ? true : (teamDisagrees(b.id) ? false : null)),
    team_approval: isCognisantMove(b) ? 'Agreed (auto)' : approvalLabel(b.id),
  }));
  const blob = new Blob([JSON.stringify({ exported: new Date().toISOString(), moves }, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'mt_portfolio_moves.json';
  a.click();
}

let sfApplyPlan = null;
let sfApplyFilter = 'all';

function sfApplyRows(plan) {
  const rows = [];
  for (const item of plan.owner_changes || []) {
    const brands = (item.brands || []).map(b => b.brand_name).join(', ');
    const isCog = item.new_am === BALANCE_SINK;
    rows.push({
      kind: isCog ? 'cognisant' : 'team_agreed',
      action: isCog ? 'Owner → Kimberley Gatt' : `Owner → ${item.new_am}`,
      actionClass: isCog ? 'sf-action-cognisant' : 'sf-action-owner',
      parent: item.parent_name || item.parent_id,
      current: item.current_owner_name || '—',
      target: isCog ? 'Kimberley Gatt' : item.new_am,
      brands,
      reason: item.reason,
    });
  }
  for (const item of plan.segment_requests || []) {
    const brands = (item.brands || []).map(b => b.brand_name).join(', ');
    rows.push({
      kind: 'segment',
      action: 'Segment request (Pending)',
      actionClass: 'sf-action-segment',
      parent: item.parent_name || item.parent_id,
      current: item.current_segment || '—',
      target: item.requested_segment,
      brands,
      reason: 'team_agreed_mm',
    });
  }
  return rows;
}

function renderSfApplyPreview() {
  const summaryEl = document.getElementById('sfApplySummary');
  const body = document.getElementById('sfApplyBody');
  if (!summaryEl || !body) return;
  if (!sfApplyPlan) {
    summaryEl.textContent = 'No preview loaded — rebuild dashboard or run scripts/sf_apply_portfolio_moves.py --preview';
    body.innerHTML = '';
    return;
  }
  const s = sfApplyPlan.summary || {};
  summaryEl.innerHTML =
    `Generated ${esc(sfApplyPlan.generated_at || '—')} · ` +
    `<strong>${s.owner_changes || 0}</strong> parent owner changes ` +
    `(${s.team_agreed_parent_moves || 0} team agreed, ${s.cognisant_parent_moves || 0} Cognisant→Kimberley) · ` +
    `<strong>${s.segment_requests || 0}</strong> segment requests · ` +
    `${s.skips || 0} skipped · ✗ Not agree = excluded`;
  const rows = sfApplyRows(sfApplyPlan).filter(r => {
    if (sfApplyFilter === 'all') return true;
    if (sfApplyFilter === 'team_agreed') return r.kind === 'team_agreed';
    if (sfApplyFilter === 'cognisant') return r.kind === 'cognisant';
    if (sfApplyFilter === 'segment') return r.kind === 'segment';
    return true;
  });
  body.innerHTML = rows.map(r => `<tr>
    <td class="${r.actionClass}">${esc(r.action)}</td>
    <td>${esc(r.parent)}</td>
    <td>${esc(r.current)}</td>
    <td>${esc(r.target)}</td>
    <td>${esc(r.brands)}</td>
  </tr>`).join('');
}

async function loadSfApplyPreview() {
  const urls = ['sf_apply_preview.json', '/sf_apply_preview.json'];
  for (const path of urls) {
    try {
      const res = await fetch(path + '?t=' + Date.now(), { cache: 'no-store' });
      if (!res.ok) continue;
      sfApplyPlan = await res.json();
      renderSfApplyPreview();
      return;
    } catch (e) {
      console.warn('sf apply preview load failed', path, e);
    }
  }
  if (D && D.sf_apply_preview && D.sf_apply_preview.summary) {
    sfApplyPlan = { summary: D.sf_apply_preview.summary, generated_at: D.sf_apply_preview.generated_at, owner_changes: [], segment_requests: [] };
    renderSfApplyPreview();
    return;
  }
  renderSfApplyPreview();
}

function amShortLabel(am) {
  if (am.slug === 'cognisant') return 'Cognisant';
  return am.name.split(' ')[0];
}

function amShortName(name) {
  if (name === 'Cognisant') return 'Cognisant';
  const am = D.ams.find(a => a.name === name);
  return am ? amShortLabel(am) : name.split(' ')[0];
}

function buildMoveFlows() {
  const flows = {};
  for (const b of D.brands) {
    if (!isMoved(b)) continue;
    const from = b.original_am;
    const to = assignments[b.id];
    const key = from + '|||' + to;
    if (!flows[key]) {
      flows[key] = { from, to, brands: 0, providers: 0, gmv: 0, items: [] };
    }
    flows[key].brands += 1;
    flows[key].providers += b.providers;
    flows[key].gmv += b.gmv_total || 0;
    flows[key].items.push(b);
  }
  return Object.values(flows).sort((a, b) => b.gmv - a.gmv || b.brands - a.brands);
}

function openMoveRoute(idx) {
  const el = document.querySelector(`#movesFlowList details[data-route-idx="${idx}"]`);
  if (!el) return;
  el.open = true;
  el.classList.add('move-route-highlight');
  setTimeout(() => el.classList.remove('move-route-highlight'), 1200);
  el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function renderMoveFlowList(flows) {
  const listEl = document.getElementById('movesFlowList');
  if (!listEl) return;
  listEl.innerHTML = flows.map((f, i) => {
    const sorted = [...f.items].sort((a, b) => (b.gmv_total || 0) - (a.gmv_total || 0));
    const rows = sorted.map(b => `<tr>
      <td>${esc(b.brand_name)}</td>
      <td class="num">${b.providers}</td>
      <td class="num">${euro(b.gmv_total || 0)}</td>
    </tr>`).join('');
    return `<details class="move-route" data-route-idx="${i}">
      <summary class="move-route-summary">
        <span class="move-route-chevron" aria-hidden="true"></span>
        <span class="move-route-label">${esc(amShortName(f.from))} → ${esc(amShortName(f.to))}</span>
        <span class="move-route-stat num"><strong>${f.brands}</strong></span>
        <span class="move-route-stat num">${f.providers}</span>
        <span class="move-route-stat num"><strong>${euro(f.gmv)}</strong></span>
      </summary>
      <div class="move-route-accounts">
        <table class="move-route-table">
          <thead>
            <tr>
              <th>Brand</th>
              <th class="num">Providers</th>
              <th class="num">GMV (6m)</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </details>`;
  }).join('');
}

function chartScales() {
  const c = chartThemeColors();
  return {
    x: {
      ticks: { color: c.tick, maxRotation: 0 },
      grid: { color: c.grid },
    },
    y: {
      ticks: { color: c.tick },
      grid: { color: c.grid },
      beginAtZero: true,
    },
  };
}

function gmvBarColors() {
  return D.ams.map(am =>
    am.slug === 'cognisant' ? 'rgba(107,114,128,0.75)' : 'rgba(245,158,11,0.9)'
  );
}

function renderCountsChart(ctx, stats, chartRef) {
  if (!ctx || typeof Chart === 'undefined') return chartRef;
  if (chartRef) chartRef.destroy();
  const labels = D.ams.map(amShortLabel);
  const legendColor = chartThemeColors().legend;
  return new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [
        { label: 'Brands', data: stats.map(s => s.brands), backgroundColor: 'rgba(59,130,246,0.88)', borderRadius: 4 },
        { label: 'Providers', data: stats.map(s => s.providers), backgroundColor: 'rgba(52,211,153,0.88)', borderRadius: 4 },
        { label: 'Groups', data: stats.map(s => s.groups), backgroundColor: 'rgba(167,139,250,0.88)', borderRadius: 4 },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: legendColor, boxWidth: 12 } },
        tooltip: { mode: 'index', intersect: false },
      },
      scales: chartScales(),
    },
  });
}

function renderGmvChart(ctx, stats, chartRef) {
  if (!ctx || typeof Chart === 'undefined') return chartRef;
  if (chartRef) chartRef.destroy();
  const labels = D.ams.map(amShortLabel);
  const c = chartThemeColors();
  return new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: 'GMV (6m)',
        data: stats.map(s => s.gmv),
        backgroundColor: gmvBarColors(),
        borderRadius: 4,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: c => 'GMV: ' + euro(c.parsed.y),
          },
        },
      },
      scales: {
        x: chartScales().x,
        y: {
          ticks: { color: c.tick, callback: v => euro(v) },
          grid: { color: c.grid },
          beginAtZero: true,
        },
      },
    },
  });
}

function renderTopCharts() {
  if (typeof Chart === 'undefined') return;
  const statsBefore = D.ams.map(am => originalAmStats(am.name));
  const statsAfter = D.ams.map(am => amStats(am.name));
  chartCountsBefore = renderCountsChart(
    document.getElementById('chartCountsBefore'), statsBefore, chartCountsBefore
  );
  chartGmvBefore = renderGmvChart(
    document.getElementById('chartGmvBefore'), statsBefore, chartGmvBefore
  );
  chartCountsAfter = renderCountsChart(
    document.getElementById('chartCountsAfter'), statsAfter, chartCountsAfter
  );
  chartGmvAfter = renderGmvChart(
    document.getElementById('chartGmvAfter'), statsAfter, chartGmvAfter
  );
  renderMovesChart();
}

function loadCollapseState() {
  try {
    const raw = localStorage.getItem(LS_COLLAPSE);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function saveCollapseState(id, collapsed) {
  const state = loadCollapseState();
  state[id] = collapsed;
  localStorage.setItem(LS_COLLAPSE, JSON.stringify(state));
}

function resizeChartsIfVisible() {
  [chartCountsBefore, chartGmvBefore, chartCountsAfter, chartGmvAfter,
    chartMovesAccounts, chartMovesGmv].forEach(ch => ch?.resize());
}

function directChildH2(el) {
  for (const child of el.children) {
    if (child.tagName === 'H2') return child;
  }
  return null;
}

function sectionByCollapseId(id) {
  return document.querySelector('[data-collapse-id="' + id + '"]');
}

function isSectionCollapsed(id) {
  const el = sectionByCollapseId(id);
  return el ? el.classList.contains('is-collapsed') : false;
}

function setSectionCollapsed(el, collapsed, persist) {
  const id = el.dataset.collapseId;
  el.classList.toggle('is-collapsed', collapsed);
  const btn = el.querySelector('.collapse-btn');
  if (btn) {
    btn.textContent = collapsed ? '+' : '-';
    btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    btn.title = collapsed ? 'Expand section' : 'Minimise section';
  }
  if (persist && id) saveCollapseState(id, collapsed);
  if (!collapsed) {
    resizeChartsIfVisible();
    if (id === 'portfolios') scheduleBoardRender();
  }
}

function toggleSection(el) {
  setSectionCollapsed(el, !el.classList.contains('is-collapsed'), true);
}

function setAllSectionsCollapsed(collapsed, persist) {
  document.querySelectorAll('[data-collapse-id]').forEach(el => {
    setSectionCollapsed(el, collapsed, persist);
  });
}

function initCollapsibleSections() {
  const state = loadCollapseState();
  document.querySelectorAll('.card, .bulk-bar, .legend, .summary').forEach((el, i) => {
    if ([...el.children].some(c => c.classList && c.classList.contains('card-head'))) return;
    const h2 = directChildH2(el);
    const title = h2 ? h2.textContent : (el.dataset.collapseTitle || 'Section');
    const id = el.dataset.collapseId || el.id || ('section-' + i);
    el.dataset.collapseId = id;

    const head = document.createElement('div');
    head.className = 'card-head';
    if (h2) {
      head.appendChild(h2);
    } else {
      const titleEl = document.createElement('h2');
      titleEl.textContent = title;
      head.appendChild(titleEl);
    }
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'collapse-btn';
    btn.setAttribute('aria-expanded', 'true');
    btn.textContent = '-';
    btn.title = 'Minimise section';
    head.appendChild(btn);

    const body = document.createElement('div');
    body.className = 'collapse-body';
    [...el.childNodes].forEach(n => {
      if (n !== head) body.appendChild(n);
    });

    el.appendChild(head);
    el.appendChild(body);

    const toggle = () => toggleSection(el);
    head.addEventListener('click', toggle);
    btn.addEventListener('click', e => { e.stopPropagation(); toggle(); });

    if (state[id]) setSectionCollapsed(el, true, false);
  });
}

function scheduleBoardRender() {
  const board = document.getElementById('board');
  if (!board) return;
  if (isSectionCollapsed('portfolios')) {
    board.innerHTML = '<div class="chart-empty">Click <strong>+</strong> on <strong>Portfolios</strong> (or use Expand all) to load brand cards.</div>';
    return;
  }
  if (boardRenderHandle) cancelAnimationFrame(boardRenderHandle);
  board.innerHTML = '<div class="chart-empty">Loading brand cards…</div>';
  boardRenderHandle = requestAnimationFrame(() => {
    boardRenderHandle = null;
    renderBoard();
    syncSelectionUi();
  });
}

function hidePageLoader() {
  if (pageReady) return;
  pageReady = true;
  const loader = document.getElementById('pageLoader');
  if (loader) loader.classList.add('hidden');
}

function barEndLabels(formatter) {
  return {
    id: 'barEndLabels',
    afterDatasetsDraw(chart) {
      const { ctx } = chart;
      const dataset = chart.data.datasets[0];
      const meta = chart.getDatasetMeta(0);
      if (!dataset || meta.hidden) return;
      ctx.save();
      ctx.fillStyle = '#e7ecf3';
      ctx.font = '11px system-ui, sans-serif';
      ctx.textBaseline = 'middle';
      meta.data.forEach((bar, i) => {
        const val = dataset.data[i];
        const label = formatter(val, i);
        const x = bar.x + (bar.horizontal ? 6 : 0);
        const y = bar.y;
        if (bar.horizontal) {
          ctx.textAlign = 'left';
          ctx.fillText(label, x, y);
        }
      });
      ctx.restore();
    },
  };
}

function renderMovesChart() {
  const flows = buildMoveFlows();
  const emptyEl = document.getElementById('movesChartEmpty');
  const wrapEl = document.getElementById('movesChartWrap');
  const summaryEl = document.getElementById('movesChartSummary');
  const accountsCtx = document.getElementById('chartMovesAccounts');
  const gmvCtx = document.getElementById('chartMovesGmv');
  if (!emptyEl || !wrapEl || typeof Chart === 'undefined') return;

  if (chartMovesAccounts) { chartMovesAccounts.destroy(); chartMovesAccounts = null; }
  if (chartMovesGmv) { chartMovesGmv.destroy(); chartMovesGmv = null; }

  const movedBrands = D.brands.filter(isMoved);
  const totalGmv = movedBrands.reduce((s, b) => s + (b.gmv_total || 0), 0);
  const totalProv = movedBrands.reduce((s, b) => s + b.providers, 0);

  if (!flows.length) {
    emptyEl.style.display = 'block';
    wrapEl.style.display = 'none';
    if (summaryEl) summaryEl.innerHTML = '';
    return;
  }

  emptyEl.style.display = 'none';
  wrapEl.style.display = 'block';
  const chartH = Math.max(140, flows.length * 44) + 'px';
  wrapEl.querySelectorAll('.chart-wrap-moves').forEach(el => { el.style.height = chartH; });

  if (summaryEl) {
    summaryEl.innerHTML =
      `Total: <strong>${movedBrands.length}</strong> accounts · ` +
      `<strong>${euro(totalGmv)}</strong> GMV · ` +
      `<strong>${totalProv}</strong> providers across <strong>${flows.length}</strong> route${flows.length === 1 ? '' : 's'}`;
  }

  const labels = flows.map(f => `${amShortName(f.from)} → ${amShortName(f.to)}`);
  const hBarOpts = (xTitle, xTicks) => {
    const c = chartThemeColors();
    return {
    indexAxis: 'y',
    responsive: true,
    maintainAspectRatio: false,
    onClick: (_evt, elements) => {
      if (elements.length) openMoveRoute(elements[0].index);
    },
    onHover: (evt, elements) => {
      const canvas = evt.native?.target;
      if (canvas) canvas.style.cursor = elements.length ? 'pointer' : 'default';
    },
    plugins: {
      legend: { display: false },
      tooltip: {
        callbacks: {
          label: item => {
            const f = flows[item.dataIndex];
            if (!f) return '';
            return [
              `${f.brands} account${f.brands === 1 ? '' : 's'}`,
              `${f.providers} providers`,
              euro(f.gmv) + ' GMV',
            ];
          },
        },
      },
    },
    scales: {
      x: {
        ticks: { color: c.tick, ...(xTicks || {}) },
        grid: { color: c.grid },
        beginAtZero: true,
        title: { display: true, text: xTitle, color: c.tick, font: { size: 11 } },
      },
      y: {
        ticks: { color: c.tick, autoSkip: false },
        grid: { display: false },
      },
    },
  };
  };

  if (accountsCtx) {
    chartMovesAccounts = new Chart(accountsCtx, {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          label: 'Accounts',
          data: flows.map(f => f.brands),
          backgroundColor: 'rgba(245, 158, 11, 0.88)',
          borderRadius: 4,
        }],
      },
      options: hBarOpts('Accounts'),
      plugins: [barEndLabels((val) => String(val))],
    });
  }

  if (gmvCtx) {
    chartMovesGmv = new Chart(gmvCtx, {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          label: 'GMV',
          data: flows.map(f => f.gmv),
          backgroundColor: 'rgba(251, 191, 36, 0.88)',
          borderRadius: 4,
        }],
      },
      options: hBarOpts('GMV', { callback: v => euro(v) }),
      plugins: [barEndLabels((_val, i) => euro(flows[i].gmv))],
    });
  }

  renderMoveFlowList(flows);
}

function presetMinimalMovement() {
  return !!(D.preset && D.preset.minimal_movement);
}

function presetIncludesMmBalance() {
  return !!(D.preset && D.preset.preset_includes_mm_balance);
}

function renderBalancePlan() {
  const el = document.getElementById('balancePlanSummary');
  const tbody = document.querySelector('#mmSuggestTable tbody');
  if (!el) return;

  if (presetMinimalMovement()) {
    el.innerHTML =
      '<strong>Minimum movement preset</strong> — MM brands stay on their original AM. ' +
      'Only SMB policy moves are applied (see preset banner). ' +
      'Drag cards manually if you want to rebalance Gulcin · Mariem · Yousef.';
    if (tbody) {
      tbody.innerHTML =
        '<tr><td colspan="5" style="color:var(--muted)">No automatic MM moves — manual only.</td></tr>';
    }
    return;
  }

  if (presetIncludesMmBalance()) {
    const stats = D.preset.stats || {};
    const fin = stats.balance_final || {};
    const lines = ['Gulcin Erguven', 'Mariem Slimen', 'Yousef Moungad']
      .filter(am => fin[am])
      .map(am => {
        const v = fin[am];
        return `${esc(amShortName(am))}: ${v.brands} brands · ${v.providers} prov · ${euro(v.gmv)}`;
      })
      .join(' · ');
    const smallMm = D.preset.small_mm_balance
      ? ` Small MM only (≤${euro(D.preset.small_mm_max_gmv || 100000)} per group, providers first) —`
      : '';
    el.innerHTML =
      '<strong>MM balanced in preset</strong> —' + smallMm +
      ` ${stats.balance_moves || 0} group move(s) (Rico & Fiona untouched). ` +
      `Imbalance ≈ ${stats.balance_imbalance_pct || 0}%.` +
      (lines ? ` Final: ${lines}.` : '');
    if (tbody) {
      tbody.innerHTML =
        '<tr><td colspan="5" style="color:var(--muted)">MM balance already applied — use board to tweak.</td></tr>';
    }
    return;
  }

  const mmN = mmSuggestedMoves.size;
  const mmGmv = [...mmSuggestedMoves.keys()].reduce((s, id) => {
    const b = D.brands.find(x => x.id === id);
    return s + (b ? (b.gmv_total || 0) : 0);
  }, 0);

  const mmByRoute = {};
  for (const [id, to] of mmSuggestedMoves) {
    const b = D.brands.find(x => x.id === id);
    if (!b) continue;
    const key = `${b.original_am}|||${to}`;
    mmByRoute[key] = (mmByRoute[key] || 0) + 1;
  }
  const routeLine = Object.entries(mmByRoute)
    .sort((a, b) => b[1] - a[1])
    .map(([k, c]) => {
      const [from, to] = k.split('|||');
      return `${amShortName(from)}→${amShortName(to)} (${c})`;
    })
    .join(', ');

  el.innerHTML =
    `Equalise <strong>Gulcin · Mariem · Yousef</strong> on MM-only GMV at ≈` +
    `<strong>${euro(mmBalancePlan.targetGmv)}</strong> each — ` +
    `<strong>Rico</strong>, <strong>Fiona</strong>, and <strong>Alena</strong> excluded from rebalance. ` +
    `Suggest <strong>${mmN}</strong> MM brand moves (<strong>${euro(mmGmv)}</strong> GMV) — ` +
    `whole <strong>groups</strong> move together.` +
    (routeLine ? ` Routes: ${routeLine}.` : '.');

  if (tbody) {
    const rows = [...mmSuggestedMoves.entries()]
      .map(([id, to]) => {
        const b = D.brands.find(x => x.id === id);
        if (!b) return '';
        return `<tr>
          <td>${esc(b.brand_name)}</td>
          <td>${esc(groupLabel(b))}</td>
          <td class="num">${euro(b.gmv_total || 0)}</td>
          <td>${esc(amShortName(b.original_am))}</td>
          <td><strong>${esc(amShortName(to))}</strong></td>
        </tr>`;
      })
      .filter(Boolean)
      .sort((a, b) => a.localeCompare(b));
    tbody.innerHTML = rows.length ? rows.join('') :
      '<tr><td colspan="5" style="color:var(--muted)">No MM moves suggested — portfolios already balanced.</td></tr>';
  }
}

function applyMmSuggestions() {
  const done = new Set();
  for (const [id, to] of mmSuggestedMoves) {
    if (done.has(id)) continue;
    assignBrandAndGroup(id, to);
    for (const peerId of groupBrandIds(id)) done.add(peerId);
  }
  saveApprovals();
  refresh();
}

function applyZeroGmvToCognisant() {
  let n = 0;
  const seen = new Set();
  for (const b of D.brands) {
    if (seen.has(b.id)) continue;
    if (isRicoRetainedSmb(b) || isPimCognisantBlocked(b)) continue;
    const ids = groupBrandIds(b.id);
    const totalGmv = ids.reduce((s, pid) => s + (brandById[pid]?.gmv_total || 0), 0);
    if (totalGmv >= 0.5) continue;
    ids.forEach(pid => seen.add(pid));
    assignBrandAndGroup(b.id, BALANCE_SINK);
    n += ids.length;
  }
  if (n) saveApprovals();
  return n;
}

function applyRicoSmbRetention() {
  return 0;
}

function applyPresetAssignments() {
  const preset = D.preset;
  if (!preset || !preset.assignments) return false;
  const seen = new Set();
  for (const b of D.brands) {
    const ids = groupBrandIds(b.id);
    if (ids.some(id => seen.has(id))) continue;
    ids.forEach(id => seen.add(id));
    const dest = preset.assignments[ids[0]];
    if (!dest || !brandById[ids[0]]) continue;
    assignBrandAndGroup(ids[0], dest);
  }
  applyAutoApproveCognisantMoves();
  return true;
}

function applyAutoApproveCognisantMoves() {
  let changed = false;
  for (const b of D.brands) {
    if (isCognisantMove(b) && moveApprovals[b.id] !== true) {
      moveApprovals[b.id] = true;
      changed = true;
    }
  }
  if (changed) saveApprovals();
}

function showPresetBanner() {
  const el = document.getElementById('presetBanner');
  const preset = D.preset;
  if (!el || !preset) return;
  const stats = preset.stats || {};
  el.style.display = 'block';
  el.innerHTML =
    `<strong>Preset loaded:</strong> ${esc(preset.label || preset.id || 'scenario')} · ` +
    `${stats.moved_from_original ?? '—'} brands moved from original · ` +
    `SMB ≥€1k→Rico ${stats.smb_to_rico || 0}, ` +
    `SMB &lt;€1k→Cognisant ${stats.smb_u1k_to_cog || 0}` +
    (presetIncludesMmBalance()
      ? ` · <strong>small MM balance ${stats.balance_moves || 0}</strong> (providers first, ≤€100k)`
      : presetMinimalMovement()
        ? ' · <strong>MM unchanged</strong>'
        : ` · MM balance ${stats.balance_moves || 0}`);
}

function refreshMmSuggestions() {
  if (presetMinimalMovement() || presetIncludesMmBalance()) {
    mmBalancePlan = { suggested: new Map(), pool: [], targetGmv: 0, totalGmv: 0, projected: [] };
    mmSuggestedMoves = mmBalancePlan.suggested;
    return;
  }
  mmBalancePlan = computeMmBalanceSuggestions();
  mmSuggestedMoves = mmBalancePlan.suggested;
}

const SEG_PILL_ORDER = ['ENT', 'MM', 'SMB', 'ENT · Int\\'l', 'ENT · National', '—'];

function segmentBrandCounts() {
  const counts = { all: D.brands.length };
  for (const b of D.brands) {
    for (const seg of Object.keys(b.segments || {})) {
      counts[seg] = (counts[seg] || 0) + 1;
    }
  }
  return counts;
}

function orderedSegments() {
  const segs = new Set();
  for (const b of D.brands) Object.keys(b.segments || {}).forEach(s => segs.add(s));
  const ordered = SEG_PILL_ORDER.filter(s => segs.has(s));
  for (const s of [...segs].sort()) {
    if (!ordered.includes(s)) ordered.push(s);
  }
  return ordered;
}

function populateSegmentFilter() {
  const sel = document.getElementById('fSegment');
  for (const s of orderedSegments()) {
    const o = document.createElement('option');
    o.value = s;
    o.textContent = s;
    sel.appendChild(o);
  }
  renderSegmentPills();
}

function setSegmentFilter(seg) {
  const sel = document.getElementById('fSegment');
  if (!sel) return;
  sel.value = seg;
  document.querySelectorAll('.seg-pill').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.seg === seg);
  });
  refresh();
}

function renderSegmentPills() {
  const wrap = document.getElementById('segPills');
  if (!wrap) return;
  const counts = segmentBrandCounts();
  const current = document.getElementById('fSegment')?.value || 'all';
  const pills = [
    { seg: 'all', label: 'All', count: counts.all },
    ...orderedSegments().map(s => ({ seg: s, label: s, count: counts[s] || 0 })),
  ];
  wrap.innerHTML = pills.map(p => `
    <button type="button" class="seg-pill${current === p.seg ? ' active' : ''}"
      data-seg="${esc(p.seg)}">
      ${esc(p.label)}<span class="pill-count">(${p.count})</span>
    </button>
  `).join('');
  wrap.querySelectorAll('.seg-pill').forEach(btn => {
    btn.addEventListener('click', () => setSegmentFilter(btn.dataset.seg || 'all'));
  });
}

function updatePortfolioFilterSummary() {
  const el = document.getElementById('portfolioFilterSummary');
  if (!el) return;
  const visible = D.brands.filter(passesFilter).length;
  const total = D.brands.length;
  const show = document.getElementById('fShow')?.value || 'all';
  const pending = D.brands.filter(isAwaitingReview).length;
  if (show === 'not-reviewed') {
    el.innerHTML = `Showing <strong>${visible}</strong> not reviewed · <strong>${pending}</strong> total pending`;
    return;
  }
  el.innerHTML = visible === total
    ? `Showing <strong>${total}</strong> brands · <strong>${pending}</strong> not reviewed`
    : `Showing <strong>${visible}</strong> of <strong>${total}</strong> · <strong>${pending}</strong> not reviewed`;
}

function refresh() {
  refreshMmSuggestions();
  enforceRicoBook();
  enforcePimNoCognisant();
  applyAutoApproveCognisantMoves();
  pruneApprovals();
  renderTopCharts();
  renderBalancePlan();
  renderSummary();
  renderSegmentTable();
  renderGmvAmTable();
  scheduleBoardRender();
  updatePortfolioFilterSummary();
  updatePortfolioApprovalSummary();
  hidePageLoader();
}

function apprPendingDefault() {
  const appr = approvalCounts();
  return appr.pending > 0 ? 'not-reviewed' : 'moved';
}

function showBootError(msg) {
  const bootErr = document.getElementById('bootError');
  if (bootErr) {
    bootErr.style.display = 'block';
    bootErr.textContent = msg;
  }
  hidePageLoader();
}

async function loadPortfolioData() {
  const res = await fetch('data.json', { cache: 'no-store' });
  if (!res.ok) throw new Error('data.json HTTP ' + res.status);
  return res.json();
}

function wireControls() {
  document.getElementById('search').addEventListener('input', refresh);
  document.getElementById('fShow').addEventListener('change', refresh);
  document.getElementById('btnReset').addEventListener('click', async () => {
    for (const b of D.brands) assignments[b.id] = b.original_am;
    moveApprovals = {};
    clearSavedAssignments();
    applyPresetAssignments();
    applyAutoApproveCognisantMoves();
    teamStateVersion = 0;
    teamStateUpdatedAt = '';
    teamSyncDirty = true;
    saveApprovalsLocal();
    if (GH_STATE_TOKEN) await pushTeamState();
    selectedIds.clear();
    refresh();
  });
  document.getElementById('btnApplyMmSuggestions').addEventListener('click', applyMmSuggestions);
  document.querySelectorAll('.btn-save-team').forEach(btn => {
    btn.addEventListener('click', () => saveTeamStateNow());
  });
  document.getElementById('btnExport').addEventListener('click', exportMoves);
  document.getElementById('btnExpandAll').addEventListener('click', () => {
    setAllSectionsCollapsed(false, true);
    scheduleBoardRender();
    resizeChartsIfVisible();
  });
  document.getElementById('btnCollapseAll').addEventListener('click', () => {
    setAllSectionsCollapsed(true, true);
  });
  document.getElementById('bulkSelectVisible').addEventListener('change', e => selectAllVisible(e.target.checked));
  document.getElementById('btnBulkMove').addEventListener('click', moveSelectedBulk);
  document.getElementById('btnClearSelection').addEventListener('click', clearSelection);
  document.getElementById('btnShowApprovals').addEventListener('click', () => {
    const sel = document.getElementById('fShow');
    if (sel) sel.value = 'not-reviewed';
    refresh();
    const next = D.brands.find(b => isAwaitingReview(b) && passesFilter(b));
    if (next) {
      const el = document.querySelector(`.brand[data-id="${next.id}"]`);
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    } else {
      document.getElementById('portfolioBoardCard')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  });
  const themeBtn = document.getElementById('btnTheme');
  if (themeBtn) themeBtn.addEventListener('click', toggleTheme);
  document.querySelectorAll('[data-sf-filter]').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('[data-sf-filter]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      sfApplyFilter = btn.dataset.sfFilter || 'all';
      renderSfApplyPreview();
    });
  });
  const sfCopy = document.getElementById('btnSfApplyCopy');
  if (sfCopy) {
    sfCopy.addEventListener('click', async () => {
      const cmd = 'python3 scripts/sf_apply_portfolio_moves.py --preview && python3 scripts/sf_apply_portfolio_moves.py --apply';
      try {
        await navigator.clipboard.writeText(cmd);
        sfCopy.textContent = 'Copied!';
        setTimeout(() => { sfCopy.textContent = 'Copy apply command'; }, 2000);
      } catch (e) {
        window.prompt('Run after reviewing preview:', cmd);
      }
    });
  }
}

async function boot() {
  try {
    initTheme();
    D = await loadPortfolioData();
    if (!D || !D.brands) throw new Error('Portfolio data missing brands');
    assignments = Object.fromEntries(D.brands.map(b => [b.id, b.original_am]));
    brandById = Object.fromEntries(D.brands.map(b => [b.id, b]));
    populateSegmentFilter();
    populateBulkTargetAm();
    initCollapsibleSections();
    wireControls();
    if (applyPresetAssignments()) {
      showPresetBanner();
      console.info('Applied rebalance preset:', D.preset.id);
    }
    enforceRicoBook();
    enforcePimNoCognisant();
    if (D.team_decisions && Object.keys(D.team_decisions).length) {
      applyTeamDecisions({
        decisions: D.team_decisions,
        version: D.team_decisions_version || 0,
        updatedAt: D.team_decisions_updated_at || '',
      });
      console.info('Applied embedded team decisions:', Object.keys(D.team_decisions).length);
    }
    enforceRicoBook();
    enforcePimNoCognisant();
    applyAutoApproveCognisantMoves();
    const hadTeam = await initTeamState();
    if (hadTeam) {
      console.info('Merged team decisions onto preset');
    }
    pruneApprovals();
    startTeamSyncPolling();
    updateSaveTeamButton(teamSyncDirty ? 'dirty' : 'idle');
    setTimeout(refresh, 0);
    loadSfApplyPreview();
  } catch (err) {
    console.error(err);
    showBootError('Dashboard error: ' + (err && err.message ? err.message : String(err)));
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => { boot(); });
} else {
  boot();
}
  </script>
</body>
</html>"""
    esc_gmv = html_lib.escape(payload.get("gmv_period_label", ""))
    return (
        html_raw.replace("__TITLE__", esc_title)
        .replace("__COUNTRY__", esc_country)
        .replace("__GEN__", esc_gen)
        .replace("__GMV_PERIOD__", esc_gmv)
    )


BOLTABLE_URL = "https://mt-portfolio-rebalancer.boltable.eu"


def _deploy_to_boltable(html_path: str) -> int:
    deploy_sh = os.path.join(_ROOT, "scripts", "deploy_mt_portfolio_boltable.sh")
    if not os.path.isfile(deploy_sh):
        print(f"Skip boltable deploy (missing {deploy_sh})", file=sys.stderr)
        return 0
    print(f"Deploying to boltable ({BOLTABLE_URL})...")
    env = {
        **os.environ,
        "HTML_SRC": os.path.abspath(html_path),
        "BOLTABLE_HTML": _boltable_index_path(),
        "DATA_JS": _data_js_path(html_path),
        "DATA_JSON": _data_json_path(html_path),
    }
    r = subprocess.run(["bash", deploy_sh], cwd=_ROOT, env=env)
    if r.returncode != 0:
        print("Boltable deploy failed.", file=sys.stderr)
    return r.returncode


def _resolve_cache_json_path(output_html: str) -> str:
    candidate = _data_json_path(output_html)
    if os.path.isfile(candidate):
        return candidate
    fallback = os.path.join(os.path.expanduser("~/Documents/Bolt food"), "data.json")
    if os.path.isfile(fallback):
        return fallback
    return candidate


def main() -> int:
    ap = argparse.ArgumentParser(description="Malta portfolio rebalancer (Databricks → interactive HTML)")
    ap.add_argument("--country", default="mt", help="Country code (default: mt)")
    ap.add_argument("-o", "--output", default="", help="Output HTML path")
    ap.add_argument(
        "--no-deploy",
        action="store_true",
        help="Skip git push to boltable/mt-portfolio-rebalancer after build",
    )
    ap.add_argument(
        "--from-cache",
        action="store_true",
        help="Skip Databricks; reload data.json and re-render preset/HTML",
    )
    ap.add_argument(
        "--oauth",
        action="store_true",
        help="Allow browser OAuth if no PAT (opens localhost:8020 — avoid unless needed)",
    )
    args = ap.parse_args()

    _ensure_dbx_on_path()
    from dbx import DBX, has_access_token  # noqa: E402

    gen = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out = args.output.strip() or _default_output()
    cache_path = _resolve_cache_json_path(out)

    use_cache = args.from_cache or (not has_access_token() and not args.oauth)
    if use_cache:
        if not os.path.isfile(cache_path):
            print(
                "No Databricks token and no cached data.json.\n"
                "  Add PAT to ~/.databricks_token, or pass --oauth for browser login.",
                file=sys.stderr,
            )
            return 1
        print(f"Using cached data (no Databricks, no browser): {cache_path}")
        payload = _load_payload_from_cache(cache_path)
    else:
        with DBX(allow_oauth=args.oauth) as dbx:
            payload = build_payload(dbx, args.country.lower().strip())

    out = _write_all_outputs(payload, gen, out)
    if not args.no_deploy:
        return _deploy_to_boltable(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
