"""Fetch data from Databricks and build the JSON payload for the ROI dashboard."""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import sys
from typing import Any, Callable, Optional

import pandas as pd

from .constants import DASHBOARD_VERSION
from .html import _html_template
from .queries import (
    query_by_promo_type,
    query_by_sp_cohort,
    query_customers,
    query_providers,
    query_total_orders,
    query_weekly_roi,
)


def _ensure_dbx_on_path() -> None:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dbx_dir = os.path.join(repo_root, "databricks-setup")
    if dbx_dir not in sys.path:
        sys.path.insert(0, dbx_dir)


def _to_jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    try:
        import decimal
        if isinstance(value, decimal.Decimal):
            return float(value)
    except Exception:
        pass
    return str(value)


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    clean = df.where(pd.notnull(df), None)
    return [{k: _to_jsonable(v) for k, v in row.items()} for row in clean.to_dict(orient="records")]


# ---------------------------------------------------------------------------
# Default output paths
# ---------------------------------------------------------------------------

def default_output_path(country_code: str, start: dt.date, end: dt.date) -> str:
    docs_dir = os.path.expanduser("~/Documents")
    preferred = os.path.join(docs_dir, "Bolt food")
    base_dir = preferred if os.path.isdir(preferred) else docs_dir
    fn = f"smart_promo_roi_{country_code.lower()}_{start.isoformat()}_{end.isoformat()}.html"
    return os.path.join(base_dir, fn)


def default_demo_output_path(country_code: str) -> str:
    docs_dir = os.path.expanduser("~/Documents")
    preferred = os.path.join(docs_dir, "Bolt food")
    base_dir = preferred if os.path.isdir(preferred) else docs_dir
    return os.path.join(base_dir, f"smart_promo_roi_DEMO_{country_code.lower()}.html")


# ---------------------------------------------------------------------------
# Demo payload (matches the screenshots — Afro Deli & Coffee example)
# ---------------------------------------------------------------------------

def build_demo_payload(
    *,
    country_code: str = "mt",
    start: dt.date | None = None,
    end: dt.date | None = None,
) -> dict[str, Any]:
    today = dt.date.today()
    end_d = end or today
    start_d = start or dt.date(2025, 12, 22)
    cc = country_code.strip().lower()

    providers = [
        {"provider_id": 10001, "provider_name": "Afro Deli & Coffee", "segment": "SMB", "brand_name": "Afro Deli", "am": "Alex Merchant"},
        # Two locations share one brand (group of providers) for Brand-mode demo
        {"provider_id": 10002, "provider_name": "Harbour Kitchen", "segment": "SMB", "brand_name": "Coastal Group", "am": "Alex Merchant"},
        {"provider_id": 10003, "provider_name": "Sliema Bites",    "segment": "SMB", "brand_name": "Coastal Group", "am": "Alex Merchant"},
    ]

    # Weekly data for Afro Deli (provider 10001)
    weeks_10001 = [
        ("2025-12-22", 3.2,  0, 195.0, 3),
        ("2025-12-29", 5.1,  0, 258.0, 5),
        ("2026-01-19", 4.8,  0, 241.0, 4),
        ("2026-01-26", 6.2,  0, 262.0, 5),
        ("2026-02-16", 7.5,  0, 140.0, 4),
        ("2026-02-23", 8.3,  0, 82.0,  4),
        ("2026-03-02", 7.1,  0, 65.0,  4),
        ("2026-03-09", 6.4,  0, 95.0,  4),
        ("2026-03-16", 5.8,  0, 75.0,  4),
        ("2026-03-23", 4.8,  0, 68.0,  4),
        ("2026-03-30", 4.6,  0, 46.0,  3),
    ]
    # Weekly for Harbour Kitchen (10002) — same brand as 10003
    weeks_10002 = [
        ("2025-12-22", 10.0, 0, 310.0, 8),
        ("2025-12-29", 15.0, 0, 420.0, 12),
        ("2026-01-19", 12.0, 0, 380.0, 10),
        ("2026-01-26", 18.0, 0, 490.0, 14),
        ("2026-02-16", 14.0, 0, 360.0, 11),
        ("2026-03-16", 11.0, 0, 280.0, 9),
        ("2026-03-30",  8.0, 0, 210.0, 7),
    ]
    weeks_10003 = [
        ("2025-12-22", 6.0, 0, 180.0, 5),
        ("2026-01-26", 9.0, 0, 240.0, 6),
        ("2026-03-30", 5.0, 0, 120.0, 4),
    ]

    weekly = (
        [{"provider_id": 10001, "week_start": w, "provider_invest": pi, "bolt_invest": bi,
          "sales_gmv": gmv, "promoted_orders": po}
         for w, pi, bi, gmv, po in weeks_10001]
        + [{"provider_id": 10002, "week_start": w, "provider_invest": pi, "bolt_invest": bi,
            "sales_gmv": gmv, "promoted_orders": po}
           for w, pi, bi, gmv, po in weeks_10002]
        + [{"provider_id": 10003, "week_start": w, "provider_invest": pi, "bolt_invest": bi,
            "sales_gmv": gmv, "promoted_orders": po}
           for w, pi, bi, gmv, po in weeks_10003]
    )

    by_promo_type = [
        {"provider_id": 10001, "promotion_type": "Smart Promotion",
         "provider_invest": 54.0, "bolt_invest": 0.0, "sales_gmv": 1287.0, "promoted_orders": 36},
        {"provider_id": 10002, "promotion_type": "Smart Promotion",
         "provider_invest": 88.0, "bolt_invest": 12.0, "sales_gmv": 2450.0, "promoted_orders": 71},
        {"provider_id": 10003, "promotion_type": "Smart Promotion",
         "provider_invest": 40.0, "bolt_invest": 20.0, "sales_gmv": 830.0,  "promoted_orders": 28},
    ]

    by_sp_cohort = [
        {"provider_id": 10001, "audience_cohort": "Most active customers",
         "provider_invest": 22.0, "bolt_invest": 0.0, "sales_gmv": 560.0,  "promoted_orders": 15},
        {"provider_id": 10001, "audience_cohort": "New Bolt Food customers",
         "provider_invest": 18.0, "bolt_invest": 0.0, "sales_gmv": 410.0,  "promoted_orders": 11},
        {"provider_id": 10001, "audience_cohort": "Promising returning customers",
         "provider_invest": 9.0,  "bolt_invest": 0.0, "sales_gmv": 210.0,  "promoted_orders": 6},
        {"provider_id": 10001, "audience_cohort": "High-spending customers",
         "provider_invest": 5.0,  "bolt_invest": 0.0, "sales_gmv": 107.0,  "promoted_orders": 4},
        {"provider_id": 10002, "audience_cohort": "Most active customers",
         "provider_invest": 38.0, "bolt_invest": 5.0, "sales_gmv": 1050.0, "promoted_orders": 30},
        {"provider_id": 10002, "audience_cohort": "Loyal high frequency customers",
         "provider_invest": 30.0, "bolt_invest": 4.0, "sales_gmv": 850.0,  "promoted_orders": 24},
        {"provider_id": 10002, "audience_cohort": "New Bolt Food customers",
         "provider_invest": 20.0, "bolt_invest": 3.0, "sales_gmv": 550.0,  "promoted_orders": 17},
        {"provider_id": 10003, "audience_cohort": "High-spending customers",
         "provider_invest": 20.0, "bolt_invest": 10.0,"sales_gmv": 420.0,  "promoted_orders": 14},
        {"provider_id": 10003, "audience_cohort": "Promising returning customers",
         "provider_invest": 20.0, "bolt_invest": 10.0,"sales_gmv": 410.0,  "promoted_orders": 14},
    ]

    total_orders = [
        {"provider_id": 10001, "total_orders": 196},
        {"provider_id": 10002, "total_orders": 312},
        {"provider_id": 10003, "total_orders": 148},
    ]

    customers = [
        {"provider_id": 10001, "customers_reached": 34, "first_time_customers": 3},
        {"provider_id": 10002, "customers_reached": 58, "first_time_customers": 9},
        {"provider_id": 10003, "customers_reached": 25, "first_time_customers": 4},
    ]

    return {
        "meta": {
            "country": cc,
            "start": start_d.isoformat(),
            "end": end_d.isoformat(),
            "built_at": dt.datetime.now().isoformat(timespec="seconds"),
            "dashboard_version": DASHBOARD_VERSION,
            "is_demo": True,
        },
        "providers": providers,
        "weekly": weekly,
        "by_promo_type": by_promo_type,
        "by_sp_cohort":  by_sp_cohort,
        "total_orders": total_orders,
        "customers": customers,
    }


# ---------------------------------------------------------------------------
# Live fetch from Databricks
# ---------------------------------------------------------------------------

def fetch_roi_dataframes(
    *,
    country_code: str,
    start: dt.date,
    end: dt.date,
    on_query_complete: Optional[Callable[[str], None]] = None,
) -> dict[str, pd.DataFrame]:
    cc = country_code.strip().lower()
    logging.getLogger("databricks.sql.client").setLevel(logging.ERROR)
    _ensure_dbx_on_path()
    from dbx import DBX  # type: ignore

    results: dict[str, pd.DataFrame] = {}
    with DBX() as dbx:
        results["providers"] = query_providers(dbx, cc, start, end)
        if on_query_complete:
            on_query_complete("Provider list")

        results["weekly"] = query_weekly_roi(dbx, cc, start, end)
        if on_query_complete:
            on_query_complete("Weekly investment vs GMV")

        results["by_promo_type"] = query_by_promo_type(dbx, cc, start, end)
        if on_query_complete:
            on_query_complete("By promotion type")

        results["by_sp_cohort"] = query_by_sp_cohort(dbx, cc, start, end)
        if on_query_complete:
            on_query_complete("By SP audience cohort")

        results["total_orders"] = query_total_orders(dbx, cc, start, end)
        if on_query_complete:
            on_query_complete("Total orders per provider")

        # Customers query may fail if eater_id column name differs — graceful fallback
        try:
            results["customers"] = query_customers(dbx, cc, start, end)
            if on_query_complete:
                on_query_complete("Customers reached + first-time")
        except Exception as exc:
            import sys as _sys
            print(f"  warn: customers query failed ({exc}); customers_reached will be N/A", file=_sys.stderr)
            results["customers"] = pd.DataFrame(columns=["provider_id", "customers_reached", "first_time_customers"])

    return results


def build_payload_from_dfs(
    dfs: dict[str, pd.DataFrame],
    *,
    country_code: str,
    start: dt.date,
    end: dt.date,
) -> dict[str, Any]:
    return {
        "meta": {
            "country": country_code.strip().lower(),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "built_at": dt.datetime.now().isoformat(timespec="seconds"),
            "dashboard_version": DASHBOARD_VERSION,
        },
        "providers":     _records(dfs["providers"]),
        "weekly":        _records(dfs["weekly"]),
        "by_promo_type": _records(dfs["by_promo_type"]),
        "by_sp_cohort":  _records(dfs.get("by_sp_cohort", pd.DataFrame())),
        "total_orders":  _records(dfs["total_orders"]),
        "customers":     _records(dfs.get("customers", pd.DataFrame())),
    }


# ---------------------------------------------------------------------------
# HTML rendering + writing
# ---------------------------------------------------------------------------

def roi_dashboard_html_string(data: dict[str, Any]) -> str:
    meta = data["meta"]
    cc = str(meta["country"]).strip().upper()
    start = dt.date.fromisoformat(str(meta["start"]))
    end = dt.date.fromisoformat(str(meta["end"]))
    is_demo = bool(meta.get("is_demo"))

    if is_demo:
        subtitle = (
            f"{cc} · Sample window {start.isoformat()} – {end.isoformat()} · "
            "Illustrative numbers so you can try the filters and charts. Not production data."
        )
        build_banner = (
            f"Sample data · layout preview only · {dt.datetime.now().strftime('%d %b %Y, %H:%M')} · "
            "Figures are not from your warehouse."
        )
    else:
        subtitle = (
            f"{cc} · Promotions data from {start.isoformat()} through {end.isoformat()}. "
            "Select a provider and click Load Report to view their ROI."
        )
        build_banner = (
            f"Built {dt.datetime.now().strftime('%d %b %Y, %H:%M')} · "
            f"Data covers {start.isoformat()} – {end.isoformat()}. "
            "Use the provider selector and date range to explore."
        )

    data_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return _html_template(
        country=cc,
        subtitle=subtitle,
        data_json=data_json,
        build_banner=build_banner,
        dashboard_version=DASHBOARD_VERSION,
    )


def write_roi_dashboard_html(out_path: str, data: dict[str, Any]) -> None:
    html = roi_dashboard_html_string(data)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
