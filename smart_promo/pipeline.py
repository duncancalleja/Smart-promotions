"""Fetch from Databricks, build JSON payload, render / write HTML."""
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
    create_smart_orders_session_view,
    drop_smart_orders_session_view,
    query_by_audience_cohort,
    query_by_enrollment_cohort,
    query_by_lcs_cohort_top,
    query_by_lifecycle_bucket,
    query_by_report_reason,
    query_enrollments,
    query_provider_reason_detail,
)

_SMART_ORDERS_SESSION_VIEW = "smart_orders_sp_sess"


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
        if isinstance(value, dt.datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")
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
    out: list[dict[str, Any]] = []
    for rec in clean.to_dict(orient="records"):
        out.append({k: _to_jsonable(v) for k, v in rec.items()})
    return out


def default_demo_output_path(country_code: str) -> str:
    """Fixed path for sample-data export (no warehouse)."""
    docs_dir = os.path.expanduser("~/Documents")
    preferred = os.path.join(docs_dir, "Bolt food")
    base_dir = preferred if os.path.isdir(preferred) else docs_dir
    return os.path.join(base_dir, f"smart_promo_dashboard_DEMO_{country_code.lower()}.html")


def build_demo_payload(
    *,
    country_code: str = "mt",
    start: dt.date | None = None,
    end: dt.date | None = None,
) -> dict[str, Any]:
    """Same JSON shape as a live build, with small synthetic rows (offline / preview)."""
    today = dt.date.today()
    end_d = end or today
    start_d = start or (end_d - dt.timedelta(days=14))
    cc = country_code.strip().lower()
    mid_days = max(0, (end_d - start_d).days // 2)
    d_mid = start_d + dt.timedelta(days=mid_days)

    by_report_reason = [
        {
            "report_reason": "2_engaged_02_medium_conversion_02_high_profit",
            "bolt_spend_local": 1200.5,
            "provider_spend_local": 2800.25,
            "total_spend_local": 4000.75,
            "orders": 420,
            "providers": 55,
        },
        {
            "report_reason": "5_not_active",
            "bolt_spend_local": 800.0,
            "provider_spend_local": 400.0,
            "total_spend_local": 1200.0,
            "orders": 95,
            "providers": 22,
        },
        {
            "report_reason": "6_never_activated",
            "bolt_spend_local": 150.0,
            "provider_spend_local": 600.0,
            "total_spend_local": 750.0,
            "orders": 40,
            "providers": 18,
        },
    ]
    by_audience = [
        {
            "audience_cohort": "Most active customers",
            "bolt_spend_local": 900.0,
            "provider_spend_local": 2100.0,
            "total_spend_local": 3000.0,
            "orders": 200,
            "providers": 30,
        },
        {
            "audience_cohort": "New Bolt Food customers",
            "bolt_spend_local": 1100.0,
            "provider_spend_local": 900.0,
            "total_spend_local": 2000.0,
            "orders": 180,
            "providers": 25,
        },
        {
            "audience_cohort": "Other / unclassified",
            "bolt_spend_local": 150.5,
            "provider_spend_local": 800.25,
            "total_spend_local": 950.75,
            "orders": 120,
            "providers": 40,
        },
    ]
    by_lifecycle = [
        {
            "lifecycle_bucket": "Engaged",
            "bolt_spend_local": 1000.0,
            "provider_spend_local": 2200.0,
            "total_spend_local": 3200.0,
            "orders": 310,
            "providers": 42,
        },
        {
            "lifecycle_bucket": "Not active",
            "bolt_spend_local": 700.0,
            "provider_spend_local": 500.0,
            "total_spend_local": 1200.0,
            "orders": 90,
            "providers": 20,
        },
    ]
    by_lcs = [
        {
            "lcs_cohort": "2_engaged_02_medium_conversion_02_high_profit",
            "bolt_spend_local": 1100.0,
            "provider_spend_local": 2400.0,
            "total_spend_local": 3500.0,
            "orders": 280,
            "providers": 38,
        },
    ]
    by_enroll_cohort = [
        {
            "enrollment_cohort": "control_q1",
            "bolt_spend_local": 300.0,
            "provider_spend_local": 700.0,
            "total_spend_local": 1000.0,
            "orders": 60,
            "providers": 12,
        },
    ]

    def pr_row(
        od: dt.date,
        pid: int,
        pname: str,
        reason: str,
        bolt: float,
        prov: float,
        orders: int,
        aud: str = "Most active customers",
        life: str = "Engaged",
    ) -> dict[str, Any]:
        tot = bolt + prov
        return {
            "order_date": od.isoformat(),
            "provider_id": pid,
            "provider_name": pname,
            "brand_name": "Demo Brand",
            "am": "Alex Merchant",
            "segment": "Growth",
            "audience_cohort": aud,
            "lifecycle_bucket": life,
            "lcs_cohort": reason,
            "enrollment_cohort": "control_q1",
            "report_reason": reason,
            "spend_objective": "sp_engagement",
            "target": "eater",
            "bolt_spend_local": bolt,
            "provider_spend_local": prov,
            "total_spend_local": tot,
            "orders": orders,
        }

    by_pr = [
        pr_row(start_d, 10001, "Taste of Malta", by_report_reason[0]["report_reason"], 40, 90, 3),
        pr_row(d_mid, 10002, "Harbour Kitchen", by_report_reason[0]["report_reason"], 55, 120, 4),
        pr_row(end_d, 10003, "Sliema Bites", by_report_reason[1]["report_reason"], 20, 35, 2),
        pr_row(end_d, 10004, "Valletta Plates", by_report_reason[2]["report_reason"], 10, 50, 1),
    ]

    enrollments = [
        {
            "provider_id": 10001,
            "provider_name": "Taste of Malta",
            "brand_name": "Demo Brand",
            "am": "Alex Merchant",
            "segment": "Growth",
            "smart_promo_offer_type": "PERCENTAGE_DISCOUNT",
            "smart_promo_type": "STANDARD",
            "enrollment_state": "ENROLLED",
            "smart_promo_offer_mode": "AUTOMATIC",
            "enrollment_start_date": f"{d_mid.isoformat()}T10:00:00.000+0000",
            "campaign_spend_objective": "sp_engagement",
            "campaign_id": "900001",
            "is_valid_promotion": "true",
        },
        {
            "provider_id": 10002,
            "provider_name": "Harbour Kitchen",
            "brand_name": "Demo Brand",
            "am": "Alex Merchant",
            "segment": "Growth",
            "smart_promo_offer_type": "PERCENTAGE_DISCOUNT",
            "smart_promo_type": "STANDARD",
            "enrollment_state": "ENROLLED",
            "smart_promo_offer_mode": "AUTOMATIC",
            "enrollment_start_date": f"{end_d.isoformat()}T14:30:00.000+0000",
            "campaign_spend_objective": "sp_engagement",
            "campaign_id": "900002",
            "is_valid_promotion": "true",
        },
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
        "by_report_reason": by_report_reason,
        "by_audience_cohort": by_audience,
        "by_lifecycle_bucket": by_lifecycle,
        "by_lcs_cohort": by_lcs,
        "by_enrollment_cohort": by_enroll_cohort,
        "by_provider_reason": by_pr,
        "enrollments": enrollments,
    }


def default_output_path(country_code: str, start: dt.date, end: dt.date) -> str:
    """New default filename (distinct from legacy smart_promotions_*_databricks.html)."""
    docs_dir = os.path.expanduser("~/Documents")
    preferred = os.path.join(docs_dir, "Bolt food")
    base_dir = preferred if os.path.isdir(preferred) else docs_dir
    fn = f"smart_promo_dashboard_{country_code.lower()}_{start.isoformat()}_{end.isoformat()}.html"
    return os.path.join(base_dir, fn)


_QUERY_LABELS: dict[str, str] = {
    "by_reason": "Spend by report_reason (rollup)",
    "by_audience": "Product audience cohorts",
    "by_lifecycle": "Lifecycle buckets",
    "by_lcs": "LCS cohort (top)",
    "by_enroll_cohort": "Enrollment cohort",
    "by_pr": "Provider × reason detail",
    "enroll": "Smart promo enrollments",
}


def fetch_smart_promo_dataframes(
    *,
    country_code: str,
    start: dt.date,
    end: dt.date,
    provider_reason_limit: int = 40000,
    enrollment_limit: int = 3000,
    on_query_complete: Optional[Callable[[str], None]] = None,
) -> dict[str, pd.DataFrame]:
    cc = country_code.strip().lower()
    logging.getLogger("databricks.sql.client").setLevel(logging.ERROR)
    _ensure_dbx_on_path()
    from dbx import DBX  # type: ignore

    results: dict[str, pd.DataFrame] = {}
    view = _SMART_ORDERS_SESSION_VIEW
    # One DBX session: enrollments (separate tables), materialize smart_orders once, rollups from TEMP VIEW, then DROP.
    with DBX() as dbx:
        results["enroll"] = query_enrollments(dbx, cc, start, end, int(enrollment_limit))
        if on_query_complete is not None:
            on_query_complete(_QUERY_LABELS["enroll"])

        create_smart_orders_session_view(dbx, cc, start, end, view)
        if on_query_complete is not None:
            on_query_complete("Materialized smart_orders (session view)")

        try:
            rollups: list[tuple[str, Callable[..., pd.DataFrame], tuple[Any, ...], dict[str, Any]]] = [
                ("by_reason", query_by_report_reason, (cc, start, end), {"session_view": view}),
                ("by_audience", query_by_audience_cohort, (cc, start, end), {"session_view": view}),
                ("by_lifecycle", query_by_lifecycle_bucket, (cc, start, end), {"session_view": view}),
                ("by_lcs", query_by_lcs_cohort_top, (cc, start, end, 100), {"session_view": view}),
                ("by_enroll_cohort", query_by_enrollment_cohort, (cc, start, end, 120), {"session_view": view}),
                (
                    "by_pr",
                    query_provider_reason_detail,
                    (cc, start, end, int(provider_reason_limit)),
                    {"session_view": view},
                ),
            ]
            for name, fn, args, kwargs in rollups:
                results[name] = fn(dbx, *args, **kwargs)
                if on_query_complete is not None:
                    on_query_complete(_QUERY_LABELS.get(name, name))
        finally:
            drop_smart_orders_session_view(dbx, view)
    return {
        "by_reason": results["by_reason"],
        "by_audience": results["by_audience"],
        "by_lifecycle": results["by_lifecycle"],
        "by_lcs": results["by_lcs"],
        "by_enroll_cohort": results["by_enroll_cohort"],
        "by_pr": results["by_pr"],
        "enroll": results["enroll"],
    }


def build_smart_promo_payload_from_dfs(
    dfs: dict[str, pd.DataFrame],
    *,
    country_code: str,
    start: dt.date,
    end: dt.date,
) -> dict[str, Any]:
    cc = country_code.strip().lower()
    return {
        "meta": {
            "country": cc,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "built_at": dt.datetime.now().isoformat(timespec="seconds"),
            "dashboard_version": DASHBOARD_VERSION,
        },
        "by_report_reason": _records(dfs["by_reason"]),
        "by_audience_cohort": _records(dfs["by_audience"]),
        "by_lifecycle_bucket": _records(dfs["by_lifecycle"]),
        "by_lcs_cohort": _records(dfs["by_lcs"]),
        "by_enrollment_cohort": _records(dfs["by_enroll_cohort"]),
        "by_provider_reason": _records(dfs["by_pr"]),
        "enrollments": _records(dfs["enroll"]),
    }


def build_smart_promo_payload(
    *,
    country_code: str,
    start: dt.date,
    end: dt.date,
    provider_reason_limit: int = 40000,
    enrollment_limit: int = 3000,
    on_query_complete: Optional[Callable[[str], None]] = None,
) -> dict[str, Any]:
    cc = country_code.strip().lower()
    dfs = fetch_smart_promo_dataframes(
        country_code=cc,
        start=start,
        end=end,
        provider_reason_limit=provider_reason_limit,
        enrollment_limit=enrollment_limit,
        on_query_complete=on_query_complete,
    )
    return build_smart_promo_payload_from_dfs(dfs, country_code=cc, start=start, end=end)


def smart_promo_dashboard_html_string(data: dict[str, Any]) -> str:
    meta = data["meta"]
    cc = str(meta["country"]).strip().lower()
    start = dt.date.fromisoformat(str(meta["start"]))
    end = dt.date.fromisoformat(str(meta["end"]))
    if meta.get("is_demo"):
        subtitle = (
            f"{cc.upper()} · Sample window {start.isoformat()}–{end.isoformat()} · "
            "Illustrative numbers so you can try filters and charts. Not production data."
        )
    else:
        subtitle = (
            f"{cc.upper()} · Orders with smart promotions from {start.isoformat()} through {end.isoformat()}. "
            "Compare Bolt vs merchant spend, then slice by report reason, audience, lifecycle, and targeting cohorts "
            "using the filters and Order dates above."
        )
    title = f"{cc.upper()} — Smart promotions"
    data_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    if meta.get("is_demo"):
        build_banner = (
            f"Sample data · layout preview only · {dt.datetime.now().strftime('%d %b %Y, %H:%M')} · "
            "Figures are not from your warehouse."
        )
    else:
        build_banner = (
            f"Updated {dt.datetime.now().strftime('%d %b %Y, %H:%M')} · "
            f"Use Order dates (green) and filters to explore this export."
        )
    return _html_template(
        title=title,
        subtitle=subtitle,
        data_json=data_json,
        build_banner=build_banner,
        dashboard_version=DASHBOARD_VERSION,
    )


def write_smart_promo_dashboard_html(out_path: str, data: dict[str, Any]) -> None:
    html = smart_promo_dashboard_html_string(data)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
