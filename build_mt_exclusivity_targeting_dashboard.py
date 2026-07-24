#!/usr/bin/env python3
"""
Malta exclusivity targeting dashboard — TEAM_AMS brands ranked by GMV market share.

Includes segment, Databricks AM, Salesforce owner, SP/SL, Bolt+, commission,
local vs non-local order share (+356 phone prefix), and team-synced status/comments.

Output: ~/Documents/Bolt food/mt_exclusivity_targeting.html
        ~/Documents/Bolt food/mt_exclusivity_data.json
Boltable: https://mt-exclusivity-targeting.boltable.eu

Usage:
  python3 build_mt_exclusivity_targeting_dashboard.py
  python3 build_mt_exclusivity_targeting_dashboard.py --from-cache
  python3 build_mt_exclusivity_targeting_dashboard.py --no-deploy
"""

from __future__ import annotations

import argparse
import datetime as dt
import html as html_lib
import json
import os
import shutil
import subprocess
import sys
from collections import defaultdict
from typing import Any

import pandas as pd
from zoneinfo import ZoneInfo

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from build_mt_account_performance_dashboard import (  # noqa: E402
    query_sp_enrollment_summary,
)
from build_mt_portfolio_rebalancer import (  # noqa: E402
    GMV_MONTHS,
    TEAM_AMS,
    _ensure_dbx_on_path,
    _is_mm_brand_key,
    _is_mm_provider,
    _json_for_script,
    _resolve_gh_state_token,
    _segment_label,
    _sql_in_str,
    _status_filter_sql,
    build_gmv_by_provider,
    gmv_period_label,
    month_keys_last_n,
    query_provider_rows,
    query_team_gmv_by_month,
)
from mt_getplace_market_share import (  # noqa: E402
    load_getplace_market_share,
    merge_getplace_into_brands,
    save_getplace_snapshot,
)

_MALTA_TZ = ZoneInfo("Europe/Malta")
_COUNTRY = "mt"
_PHONE_COLUMN: str | None = None
_BOLT_PLUS_ORDER_EXPR: str | None = None
_STATUS_OPTIONS = [
    "Not started",
    "Researching",
    "In discussion",
    "Negotiating",
    "Signed",
    "Not viable",
]


def _default_html() -> str:
    out_dir = os.path.expanduser("~/Documents/Bolt food")
    os.makedirs(out_dir, exist_ok=True)
    return os.path.join(out_dir, "mt_exclusivity_targeting.html")


def _default_data_json() -> str:
    return os.path.join(os.path.dirname(_default_html()), "mt_exclusivity_data.json")


def _boltable_public() -> str:
    return os.path.join(_ROOT, "boltable", "mt-exclusivity-targeting", "public")


def _state_json_path() -> str:
    return os.path.join(_boltable_public(), "exclusivity-state.json")


def _load_state_json() -> dict[str, Any]:
    path = _state_json_path()
    if not os.path.isfile(path):
        return {"version": 0, "updatedAt": None, "decisions": {}}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _embed_team_state(payload: dict[str, Any]) -> None:
    state = _load_state_json()
    payload["team_state"] = state.get("decisions") or {}
    payload["team_state_version"] = state.get("version") or 0
    payload["team_state_updated_at"] = state.get("updatedAt")


def _load_market_share_config() -> dict[str, Any]:
    """Optional Malta Bolt vs Wolt platform split for estimated delivery market share."""
    for path in (
        os.path.expanduser("~/Documents/Bolt food/mt_delivery_market_share.json"),
        os.path.join(_ROOT, "config", "mt_delivery_market_share.json"),
        os.path.join(_ROOT, "Context", "malta", "delivery_market_share.json"),
    ):
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            bolt = data.get("bolt_platform_share_pct")
            wolt = data.get("wolt_platform_share_pct")
            if bolt is not None and wolt is None:
                wolt = 100.0 - float(bolt)
            if wolt is not None and bolt is None:
                bolt = 100.0 - float(wolt)
            return {
                "bolt_platform_share_pct": float(bolt) if bolt is not None else None,
                "wolt_platform_share_pct": float(wolt) if wolt is not None else None,
                "source": path,
            }
    return {
        "bolt_platform_share_pct": None,
        "wolt_platform_share_pct": None,
        "source": None,
    }


def _table_columns(dbx: Any, table: str) -> set[str]:
    try:
        desc = dbx.query(f"DESCRIBE {table}")
        col_name = "col_name" if "col_name" in desc.columns else desc.columns[0]
        return {str(x).strip().lower() for x in desc[col_name].astype(str)}
    except Exception:
        return set()


def _detect_phone_column(dbx: Any) -> tuple[str, str]:
    """Return (table_ref, column) for eater phone prefix used in +356 local rule."""
    global _PHONE_COLUMN
    if _PHONE_COLUMN and "|" in _PHONE_COLUMN:
        table, col = _PHONE_COLUMN.split("|", 1)
        return table, col

    dim_user_cols = _table_columns(dbx, "core_models_spark.dim_user")
    if "user_phone_prefix" in dim_user_cols:
        _PHONE_COLUMN = "core_models_spark.dim_user|user_phone_prefix"
        return "core_models_spark.dim_user", "user_phone_prefix"

    candidates: list[str] = []
    try:
        desc = dbx.query("DESCRIBE ng_delivery_spark.dim_user_delivery")
        col_name = "col_name" if "col_name" in desc.columns else desc.columns[0]
        for raw in desc[col_name].astype(str):
            name = raw.strip().lower()
            if "phone" in name:
                candidates.append(raw.strip())
    except Exception:
        pass
    col = candidates[0] if candidates else "user_phone_prefix"
    _PHONE_COLUMN = f"ng_delivery_spark.dim_user_delivery|{col}"
    return "ng_delivery_spark.dim_user_delivery", col


def _detect_bolt_plus_order_expr(dbx: Any) -> str:
    """Return SQL expression (0/1) for Bolt+ orders."""
    global _BOLT_PLUS_ORDER_EXPR
    if _BOLT_PLUS_ORDER_EXPR:
        return _BOLT_PLUS_ORDER_EXPR

    monetary_cols = _table_columns(dbx, "ng_public_spark.etl_delivery_order_monetary_metrics")
    for col in (
        "is_bolt_plus_order",
        "is_bolt_plus_user",
        "bolt_plus_order",
        "is_bolt_plus_eater",
        "is_bolt_plus",
    ):
        if col in monetary_cols:
            _BOLT_PLUS_ORDER_EXPR = (
                f"CASE WHEN COALESCE(o.{col}, false) THEN 1 ELSE 0 END"
            )
            return _BOLT_PLUS_ORDER_EXPR

    order_cols = _table_columns(dbx, "ng_delivery_spark.fact_order_delivery")
    for col in ("is_bolt_plus_order", "is_bolt_plus_user", "is_bolt_plus"):
        if col in order_cols:
            _BOLT_PLUS_ORDER_EXPR = (
                "CASE WHEN COALESCE(fo."
                f"{col}, false) THEN 1 ELSE 0 END"
            )
            return _BOLT_PLUS_ORDER_EXPR

    # Fallback: eater had active Bolt+ subscription on order date
    _BOLT_PLUS_ORDER_EXPR = (
        "CASE WHEN s.user_id IS NOT NULL THEN 1 ELSE 0 END"
    )
    return _BOLT_PLUS_ORDER_EXPR


def _uses_bolt_plus_subscription_join(expr: str) -> bool:
    return "s.user_id" in expr


def query_total_mt_bolt_gmv(dbx: Any, country_code: str, month_keys: list[str]) -> float:
    """All Malta providers on Bolt (not TEAM_AMS only)."""
    parts_sql = ", ".join(
        f"DATE '{mk}-01'" for mk in month_keys
    )
    cc = country_code.lower()
    df = dbx.query(
        f"""
        SELECT CAST(SUM(COALESCE(m.total_gmv_before_discounts_eur, 0)) AS DOUBLE) AS gmv
        FROM ng_delivery_spark.dim_provider_v2 p
        INNER JOIN ng_delivery_spark.fact_provider_monthly m
          ON m.provider_id = p.provider_id
        WHERE LOWER(p.country_code) = '{cc}'
          AND {_status_filter_sql("p")}
          AND m.metric_timestamp_partition IN ({parts_sql})
        """
    )
    if df.empty:
        return 0.0
    return float(df.iloc[0]["gmv"] or 0)


def query_order_breakdown_by_provider(
    dbx: Any,
    country_code: str,
    range_start: str,
    range_end_exclusive: str,
) -> pd.DataFrame:
    cc = country_code.lower()
    user_table, phone_col = _detect_phone_column(dbx)
    user_alias = "du"
    bp_expr = _detect_bolt_plus_order_expr(dbx)
    sub_join = ""
    if _uses_bolt_plus_subscription_join(bp_expr):
        sub_join = f"""
        LEFT JOIN (
          SELECT DISTINCT CAST(user_id AS BIGINT) AS user_id
          FROM core_models_spark.fact_user_subscriptions
          WHERE LOWER(COALESCE(country_code, country, '')) IN ('{cc}', 'mt', 'malta')
            AND COALESCE(subscription_state, status, '') IN ('active', 'Active', 'ACTIVE')
        ) s ON s.user_id = o.user_id
        """
    fact_join = ""
    if bp_expr.startswith("CASE WHEN COALESCE(fo."):
        fact_join = """
        LEFT JOIN ng_delivery_spark.fact_order_delivery fo
          ON fo.order_id = o.order_id
        """

    return dbx.query(
        f"""
        WITH team_providers AS (
          SELECT CAST(p.provider_id AS BIGINT) AS provider_id
          FROM ng_delivery_spark.dim_provider_v2 p
          WHERE LOWER(p.country_code) = '{cc}'
            AND p.account_manager_name IN ({_sql_in_str(TEAM_AMS)})
            AND {_status_filter_sql("p")}
        ),
        orders AS (
          SELECT
            CAST(o.provider_id AS BIGINT) AS provider_id,
            CAST(o.order_id AS BIGINT) AS order_id,
            CASE
              WHEN REGEXP_REPLACE(COALESCE({user_alias}.{phone_col}, ''), '[^0-9+]', '') RLIKE '^\\\\+?356'
              THEN 1 ELSE 0
            END AS is_local,
            {bp_expr} AS is_bolt_plus
          FROM ng_public_spark.etl_delivery_order_monetary_metrics o
          INNER JOIN team_providers tp ON tp.provider_id = o.provider_id
          LEFT JOIN {user_table} {user_alias} ON {user_alias}.user_id = o.user_id
          {sub_join}
          {fact_join}
          WHERE LOWER(o.country) = '{cc}'
            AND o.order_created_date >= DATE '{range_start}'
            AND o.order_created_date < DATE '{range_end_exclusive}'
            AND o.user_id IS NOT NULL
        )
        SELECT
          provider_id,
          CAST(COUNT(DISTINCT order_id) AS BIGINT) AS orders_total,
          CAST(COUNT(DISTINCT CASE WHEN is_local = 1 THEN order_id END) AS BIGINT) AS orders_local,
          CAST(COUNT(DISTINCT CASE WHEN is_local = 0 THEN order_id END) AS BIGINT) AS orders_non_local,
          CAST(COUNT(DISTINCT CASE WHEN is_bolt_plus = 1 THEN order_id END) AS BIGINT) AS orders_bolt_plus
        FROM orders
        GROUP BY provider_id
        """
    )


def query_local_order_share_by_provider(
    dbx: Any,
    country_code: str,
    range_start: str,
    range_end_exclusive: str,
) -> pd.DataFrame:
    """Backward-compatible alias."""
    return query_order_breakdown_by_provider(dbx, country_code, range_start, range_end_exclusive)


def query_sl_enrollment_summary(dbx: Any, country_code: str) -> pd.DataFrame:
    """SL active/inactive per provider; signup table replaces offer_enrollment here."""
    cc = country_code.lower()
    for table in (
        "core_models_spark.fact_provider_sponsored_listing_offer_enrollment",
        "core_models_spark.fact_provider_sponsored_listing_signup",
    ):
        try:
            return dbx.query(
                f"""
                SELECT
                  CAST(e.provider_id AS BIGINT) AS provider_id,
                  CASE
                    WHEN MAX(CASE WHEN LOWER(TRIM(COALESCE(e.sponsored_listing_state, ''))) = 'active'
                      THEN 1 ELSE 0 END) = 1 THEN 'Active'
                    ELSE 'Inactive'
                  END AS status
                FROM {table} e
                INNER JOIN ng_delivery_spark.dim_provider_v2 p
                  ON p.provider_id = e.provider_id AND LOWER(p.country_code) = '{cc}'
                WHERE LOWER(e.country_code) = '{cc}'
                GROUP BY e.provider_id
                """
            )
        except Exception as exc:
            if "TABLE_OR_VIEW_NOT_FOUND" not in str(exc) and "42P01" not in str(exc):
                raise
    return pd.DataFrame(columns=["provider_id", "status"])


def query_commercial_fields(dbx: Any, country_code: str) -> pd.DataFrame:
    cc = country_code.lower()
    return dbx.query(
        f"""
        SELECT
          CAST(p.provider_id AS BIGINT) AS provider_id,
          COALESCE(p.sf_account_owner_name, '') AS sf_owner,
          CAST(COALESCE(p.regular_commission_rate, 0) AS DOUBLE) AS commission,
          CASE WHEN COALESCE(p.is_bolt_plus_enrolled_provider, false) THEN 1 ELSE 0 END AS bolt_plus,
          CASE
            WHEN LOWER(COALESCE(p.provider_trait_slugs_list, '')) LIKE '%home-category-exclusive-all%'
            THEN 1 ELSE 0
          END AS admin_exclusive,
          CASE
            WHEN LOWER(COALESCE(p.provider_trait_slugs_list, '')) LIKE '%just-on-bolt%'
            THEN 1 ELSE 0
          END AS bolt_food_exclusive
        FROM ng_delivery_spark.dim_provider_v2 p
        WHERE LOWER(p.country_code) = '{cc}'
          AND p.account_manager_name IN ({_sql_in_str(TEAM_AMS)})
          AND {_status_filter_sql("p")}
        """
    )


def _range_dates_months(month_keys: list[str]) -> tuple[str, str]:
    first_y, first_m = map(int, month_keys[0].split("-"))
    last_y, last_m = map(int, month_keys[-1].split("-"))
    start = f"{first_y:04d}-{first_m:02d}-01"
    idx = last_y * 12 + (last_m - 1) + 1
    ey, em0 = divmod(idx, 12)
    end_excl = f"{ey:04d}-{em0 + 1:02d}-01"
    return start, end_excl


def _mom_pct(gmv_by_month: dict[str, float], month_keys: list[str]) -> float | None:
    if len(month_keys) < 2:
        return None
    cur = float(gmv_by_month.get(month_keys[-1], 0) or 0)
    prev = float(gmv_by_month.get(month_keys[-2], 0) or 0)
    if prev <= 0:
        return None
    return round((cur - prev) / prev * 100, 1)


def build_exclusivity_brands(
    df: pd.DataFrame,
    gmv_by_provider: dict[int, dict[str, float]],
    month_keys: list[str],
    commercial: dict[int, dict[str, Any]],
    sp_map: dict[int, str],
    sl_map: dict[int, str],
    order_map: dict[int, dict[str, int]],
    total_portfolio_gmv: float,
    total_mt_bolt_gmv: float,
    market_config: dict[str, Any],
) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for row in df.itertuples(index=False):
        key = (str(row.brand_key), str(row.am))
        if key not in buckets:
            buckets[key] = {
                "brand_key": str(row.brand_key),
                "brand_name": str(row.brand_name),
                "am": str(row.am),
                "provider_ids": set(),
                "segments": defaultdict(int),
            }
        b = buckets[key]
        pid = int(row.provider_id)
        b["provider_ids"].add(pid)
        segment_raw = str(row.segment)
        if _is_mm_brand_key(str(row.brand_key)) or _is_mm_provider(pid):
            segment_raw = "Mid-market (AM Segment)"
        seg_lbl = _segment_label(segment_raw, str(getattr(row, "subsegment", "") or ""))
        b["segments"][seg_lbl] += 1

    brands: list[dict[str, Any]] = []
    for i, ((_, _), b) in enumerate(
        sorted(buckets.items(), key=lambda x: (x[1]["brand_name"].lower(), x[1]["am"]))
    ):
        segs = dict(b["segments"])
        primary_segment = max(segs, key=segs.get) if segs else "—"
        gmv_by_month: dict[str, float] = {mk: 0.0 for mk in month_keys}
        sf_owners: set[str] = set()
        commissions: list[float] = []
        bolt_plus_any = False
        sp_active = False
        sl_active = False
        orders_total = 0
        orders_local = 0
        orders_non_local = 0
        orders_bolt_plus = 0
        exclusive_outlets = 0
        admin_exclusive_outlets = 0
        bolt_food_exclusive_outlets = 0

        for pid in b["provider_ids"]:
            for mk in month_keys:
                gmv_by_month[mk] += float(gmv_by_provider.get(pid, {}).get(mk, 0) or 0)
            comm = commercial.get(pid, {})
            sf = str(comm.get("sf_owner") or "").strip()
            if sf:
                sf_owners.add(sf)
            commissions.append(float(comm.get("commission") or 0))
            if comm.get("bolt_plus"):
                bolt_plus_any = True
            if sp_map.get(pid) == "Active":
                sp_active = True
            if sl_map.get(pid) == "Active":
                sl_active = True
            om = order_map.get(pid, {})
            orders_total += int(om.get("orders_total") or 0)
            orders_local += int(om.get("orders_local") or 0)
            orders_non_local += int(om.get("orders_non_local") or 0)
            orders_bolt_plus += int(om.get("orders_bolt_plus") or 0)
            if comm.get("admin_exclusive") or comm.get("bolt_food_exclusive"):
                exclusive_outlets += 1
            if comm.get("admin_exclusive"):
                admin_exclusive_outlets += 1
            if comm.get("bolt_food_exclusive"):
                bolt_food_exclusive_outlets += 1

        provider_count = len(b["provider_ids"])
        if exclusive_outlets <= 0:
            exclusive_status = "—"
            exclusive_detail = ""
        elif exclusive_outlets >= provider_count:
            exclusive_status = "Yes"
        else:
            exclusive_status = f"Partial ({exclusive_outlets}/{provider_count})"
        if exclusive_outlets > 0:
            parts: list[str] = []
            if admin_exclusive_outlets:
                parts.append("Admin tag")
            if bolt_food_exclusive_outlets:
                parts.append("Bolt exclusive")
            exclusive_detail = " · ".join(parts)

        gmv_total = round(sum(gmv_by_month.values()), 2)
        sf_owner = sorted(sf_owners)[0] if len(sf_owners) == 1 else (
            "Mixed" if len(sf_owners) > 1 else ""
        )
        avg_comm = round(sum(commissions) / len(commissions), 4) if commissions else 0.0
        local_pct = round(orders_local / orders_total * 100, 1) if orders_total else None
        non_local_pct = round(orders_non_local / orders_total * 100, 1) if orders_total else None
        bolt_plus_order_pct = (
            round(orders_bolt_plus / orders_total * 100, 1) if orders_total else None
        )
        bolt_platform = market_config.get("bolt_platform_share_pct")
        est_delivery_market_share_pct = None
        if bolt_platform and total_mt_bolt_gmv > 0:
            est_total_market = total_mt_bolt_gmv / (float(bolt_platform) / 100.0)
            if est_total_market > 0:
                est_delivery_market_share_pct = round(gmv_total / est_total_market * 100, 2)

        brands.append(
            {
                "id": f"b{i}",
                "brand_key": b["brand_key"],
                "brand_name": b["brand_name"],
                "am": b["am"],
                "sf_owner": sf_owner,
                "segment": primary_segment,
                "providers": len(b["provider_ids"]),
                "gmv_total": gmv_total,
                "gmv_by_month": {mk: round(gmv_by_month[mk], 2) for mk in month_keys},
                "gmv_mom_pct": _mom_pct(gmv_by_month, month_keys),
                "portfolio_share_pct": 0.0,
                "share_pct": 0.0,
                "bolt_mt_share_pct": 0.0,
                "est_delivery_market_share_pct": est_delivery_market_share_pct,
                "sp": "Active" if sp_active else "Inactive",
                "sl": "Active" if sl_active else "Inactive",
                "bolt_plus": bolt_plus_any,
                "commission": avg_comm,
                "orders_total": orders_total,
                "orders_local": orders_local,
                "orders_non_local": orders_non_local,
                "orders_bolt_plus": orders_bolt_plus,
                "local_order_share_pct": local_pct,
                "non_local_order_share_pct": non_local_pct,
                "bolt_plus_order_share_pct": bolt_plus_order_pct,
                "exclusive_status": exclusive_status,
                "exclusive_detail": exclusive_detail,
                "exclusive_outlets": exclusive_outlets,
                "is_exclusive": exclusive_outlets >= provider_count and provider_count > 0,
                "provider_ids": sorted(b["provider_ids"]),
            }
        )

    for b in brands:
        b["portfolio_share_pct"] = (
            round(b["gmv_total"] / total_portfolio_gmv * 100, 2) if total_portfolio_gmv else 0.0
        )
        b["share_pct"] = b["portfolio_share_pct"]
        b["bolt_mt_share_pct"] = (
            round(b["gmv_total"] / total_mt_bolt_gmv * 100, 2) if total_mt_bolt_gmv else 0.0
        )

    brands.sort(key=lambda x: (-(x["gmv_total"] or 0), x["brand_name"].lower()))
    return brands


def build_payload_live(dbx: Any, months: int = GMV_MONTHS) -> dict[str, Any]:
    as_of = dt.datetime.now(_MALTA_TZ).date()
    month_keys = month_keys_last_n(months)
    range_start, range_end_excl = _range_dates_months(month_keys)

    df = query_provider_rows(dbx, _COUNTRY)
    gmv_df = query_team_gmv_by_month(dbx, _COUNTRY, month_keys)
    gmv_by_provider = build_gmv_by_provider(gmv_df)

    comm_df = query_commercial_fields(dbx, _COUNTRY)
    commercial: dict[int, dict[str, Any]] = {}
    for row in comm_df.itertuples(index=False):
        commercial[int(row.provider_id)] = {
            "sf_owner": str(row.sf_owner or ""),
            "commission": float(row.commission or 0),
            "bolt_plus": bool(int(row.bolt_plus or 0)),
            "admin_exclusive": bool(int(getattr(row, "admin_exclusive", 0) or 0)),
            "bolt_food_exclusive": bool(int(getattr(row, "bolt_food_exclusive", 0) or 0)),
        }

    sp_df = query_sp_enrollment_summary(dbx, _COUNTRY)
    sl_df = query_sl_enrollment_summary(dbx, _COUNTRY)
    sp_map = {int(r.provider_id): str(r.status) for r in sp_df.itertuples(index=False)}
    sl_map = {int(r.provider_id): str(r.status) for r in sl_df.itertuples(index=False)}

    order_df = query_order_breakdown_by_provider(dbx, _COUNTRY, range_start, range_end_excl)
    order_map: dict[int, dict[str, int]] = {}
    for row in order_df.itertuples(index=False):
        order_map[int(row.provider_id)] = {
            "orders_total": int(row.orders_total or 0),
            "orders_local": int(row.orders_local or 0),
            "orders_non_local": int(row.orders_non_local or 0),
            "orders_bolt_plus": int(getattr(row, "orders_bolt_plus", 0) or 0),
        }

    # Portfolio GMV = sum of TEAM_AMS provider GMV in window
    team_pids = {int(row.provider_id) for row in df.itertuples(index=False)}
    total_portfolio_gmv = round(
        sum(
            float(gmv_by_provider.get(pid, {}).get(mk, 0) or 0)
            for pid in team_pids
            for mk in month_keys
        ),
        2,
    )

    total_mt_bolt_gmv = round(query_total_mt_bolt_gmv(dbx, _COUNTRY, month_keys), 2)
    market_config = _load_market_share_config()

    brands = build_exclusivity_brands(
        df,
        gmv_by_provider,
        month_keys,
        commercial,
        sp_map,
        sl_map,
        order_map,
        total_portfolio_gmv,
        total_mt_bolt_gmv,
        market_config,
    )
    total_gmv = round(sum(b["gmv_total"] for b in brands), 2)

    payload: dict[str, Any] = {
        "country": "MT",
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "as_of_malta": as_of.isoformat(),
        "gmv_month_keys": month_keys,
        "gmv_period_label": gmv_period_label(month_keys),
        "order_window_start": range_start,
        "order_window_end_exclusive": range_end_excl,
        "phone_column": (_PHONE_COLUMN or "core_models_spark.dim_user|user_phone_prefix").split("|")[-1],
        "phone_source": _PHONE_COLUMN or "core_models_spark.dim_user|user_phone_prefix",
        "bolt_plus_order_expr": _BOLT_PLUS_ORDER_EXPR,
        "total_gmv": total_gmv,
        "total_portfolio_gmv": total_portfolio_gmv,
        "total_mt_bolt_gmv": total_mt_bolt_gmv,
        "market_share_config": market_config,
        "brand_count": len(brands),
        "ams": TEAM_AMS,
        "status_options": _STATUS_OPTIONS,
        "brands": brands,
        "local_order_rule": "Local = eater user_phone_prefix normalised starts with +356 (core_models_spark.dim_user); unmatched users count as non-local.",
        "market_share_rule": (
            "Bolt MT share = brand GMV ÷ all Malta Bolt GMV. "
            "Est. delivery share = brand GMV ÷ estimated total market "
            "(Malta Bolt GMV ÷ Bolt platform % from market config). "
            "Per-brand Wolt GMV is not in Databricks."
        ),
        "exclusive_rule": (
            "Exclusive = Admin Panel trait Exclusive (home-category-exclusive-all) and/or "
            "Exclusive on Bolt Food (just-on-bolt). Partial = some outlets tagged, not all."
        ),
    }
    _embed_team_state(payload)
    return payload


def _attach_getplace_market_share(
    payload: dict[str, Any], getplace_path: str | None = None
) -> None:
    getplace, meta = load_getplace_market_share(getplace_path)
    brands = payload.get("brands") or []
    matched = merge_getplace_into_brands(brands, getplace)
    payload["getplace_market_share"] = meta
    payload["getplace_match_count"] = matched
    payload["getplace_updated_at"] = (meta or {}).get("updated_at")
    if meta:
        payload["getplace_rule"] = (
            "GetPlace Bolt MS % = Bolt orders ÷ (Bolt + Wolt orders) from "
            "brands-by-platform / GetPlace export (per-brand competitive share)."
        )
        print(f"GetPlace market share: {matched}/{len(brands)} brands matched ({meta.get('source')})")
    else:
        payload["getplace_rule"] = (
            "GetPlace market share not loaded — export from "
            "https://brands-by-platform.boltable.eu/ to "
            "~/Documents/Bolt food/mt_brands_by_platform.json (or drop the GetPlace CSV there)."
        )
        print("GetPlace market share: no export file found (see getplace_rule in dashboard footnote)")
    snap = save_getplace_snapshot(brands, meta)
    if snap:
        payload["getplace_snapshot_path"] = snap
        print(f"GetPlace snapshot: {snap}")


def _bootstrap_from_portfolio_cache() -> dict[str, Any] | None:
    path = os.path.expanduser("~/Documents/Bolt food/data.json")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        src = json.load(f)
    month_keys = src.get("gmv_month_keys") or month_keys_last_n(GMV_MONTHS)
    range_start, range_end_excl = _range_dates_months(month_keys)
    brands: list[dict[str, Any]] = []
    for i, b in enumerate(src.get("brands") or []):
        if b.get("original_am") not in TEAM_AMS:
            continue
        brands.append(
            {
                "id": b.get("id") or f"b{i}",
                "brand_key": b.get("brand_key"),
                "brand_name": b.get("brand_name"),
                "am": b.get("original_am"),
                "sf_owner": "",
                "segment": b.get("primary_segment") or "—",
                "providers": int(b.get("providers") or 0),
                "gmv_total": round(float(b.get("gmv_total") or 0), 2),
                "gmv_by_month": b.get("gmv_by_month") or {},
                "gmv_mom_pct": None,
                "share_pct": 0.0,
                "portfolio_share_pct": 0.0,
                "bolt_mt_share_pct": None,
                "est_delivery_market_share_pct": None,
                "sp": "Inactive",
                "sl": "Inactive",
                "bolt_plus": False,
                "commission": 0.0,
                "orders_total": 0,
                "orders_local": 0,
                "orders_non_local": 0,
                "orders_bolt_plus": 0,
                "local_order_share_pct": None,
                "non_local_order_share_pct": None,
                "bolt_plus_order_share_pct": None,
                "exclusive_status": "—",
                "exclusive_detail": "",
                "exclusive_outlets": 0,
                "is_exclusive": False,
                "provider_ids": b.get("provider_ids") or [],
            }
        )
    total_gmv = sum(x["gmv_total"] for x in brands)
    market_config = _load_market_share_config()
    for x in brands:
        x["portfolio_share_pct"] = round(x["gmv_total"] / total_gmv * 100, 2) if total_gmv else 0.0
        x["share_pct"] = x["portfolio_share_pct"]
        x["bolt_mt_share_pct"] = None
        x["est_delivery_market_share_pct"] = None
        x["orders_bolt_plus"] = 0
        x["bolt_plus_order_share_pct"] = None
    brands.sort(key=lambda z: (-(z["gmv_total"] or 0), z["brand_name"].lower()))
    payload = {
        "country": "MT",
        "generated_at": "cache-bootstrap",
        "as_of_malta": dt.datetime.now(_MALTA_TZ).date().isoformat(),
        "gmv_month_keys": month_keys,
        "gmv_period_label": gmv_period_label(month_keys),
        "order_window_start": range_start,
        "order_window_end_exclusive": range_end_excl,
        "phone_column": "phone_number",
        "total_gmv": round(total_gmv, 2),
        "total_portfolio_gmv": round(total_gmv, 2),
        "total_mt_bolt_gmv": None,
        "market_share_config": market_config,
        "brand_count": len(brands),
        "ams": TEAM_AMS,
        "status_options": _STATUS_OPTIONS,
        "brands": brands,
        "local_order_rule": "Local = eater user_phone_prefix normalised starts with +356 (core_models_spark.dim_user); unmatched users count as non-local.",
        "market_share_rule": (
            "Bolt MT share = brand GMV ÷ all Malta Bolt GMV. "
            "Est. delivery share = brand GMV ÷ estimated total market "
            "(Malta Bolt GMV ÷ Bolt platform % from market config). "
            "Per-brand Wolt GMV is not in Databricks."
        ),
        "exclusive_rule": (
            "Exclusive = Admin Panel trait Exclusive (home-category-exclusive-all) and/or "
            "Exclusive on Bolt Food (just-on-bolt). Partial = some outlets tagged, not all."
        ),
        "data_source": "portfolio data.json bootstrap (no live order share)",
    }
    _embed_team_state(payload)
    return payload


def _enrich_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Backfill newer metric fields when loading an older cache JSON."""
    market_config = payload.get("market_share_config") or _load_market_share_config()
    payload["market_share_config"] = market_config
    payload.setdefault(
        "market_share_rule",
        "Bolt MT share = brand GMV ÷ all Malta Bolt GMV. "
        "Est. delivery share = brand GMV ÷ estimated total market "
        "(Malta Bolt GMV ÷ Bolt platform % from market config). "
        "Per-brand Wolt GMV is not in Databricks.",
    )
    payload.setdefault(
        "exclusive_rule",
        "Exclusive = Admin Panel trait Exclusive (home-category-exclusive-all) and/or "
        "Exclusive on Bolt Food (just-on-bolt). Partial = some outlets tagged, not all.",
    )
    brands = payload.get("brands") or []
    total_gmv = float(payload.get("total_gmv") or sum(b.get("gmv_total", 0) for b in brands) or 0)
    bolt_plat = market_config.get("bolt_platform_share_pct")
    total_mt = payload.get("total_mt_bolt_gmv")
    for b in brands:
        if "portfolio_share_pct" not in b:
            b["portfolio_share_pct"] = (
                round(float(b.get("gmv_total") or 0) / total_gmv * 100, 2) if total_gmv else 0.0
            )
        b.setdefault("share_pct", b["portfolio_share_pct"])
        b.setdefault("bolt_mt_share_pct", None)
        b.setdefault("est_delivery_market_share_pct", None)
        b.setdefault("orders_bolt_plus", 0)
        b.setdefault("bolt_plus_order_share_pct", None)
        b.setdefault("exclusive_status", "—")
        b.setdefault("exclusive_detail", "")
        b.setdefault("exclusive_outlets", 0)
        b.setdefault("is_exclusive", False)
        b.setdefault("getplace_bolt_ms_pct", None)
        b.setdefault("getplace_wolt_ms_pct", None)
        b.setdefault("getplace_total_orders", None)
        b.setdefault("getplace_ms_trend", None)
        b.setdefault("getplace_ms_change_pp", None)
        if b.get("est_delivery_market_share_pct") is None and bolt_plat and total_mt:
            gmv = float(b.get("gmv_total") or 0)
            est_total = float(total_mt) / (float(bolt_plat) / 100.0)
            if est_total > 0:
                b["est_delivery_market_share_pct"] = round(gmv / est_total * 100, 2)
        if b.get("bolt_mt_share_pct") is None and total_mt:
            gmv = float(b.get("gmv_total") or 0)
            if float(total_mt) > 0:
                b["bolt_mt_share_pct"] = round(gmv / float(total_mt) * 100, 2)
    return payload


def load_payload(from_cache: bool, cache_path: str) -> dict[str, Any]:
    if from_cache:
        if os.path.isfile(cache_path):
            with open(cache_path, encoding="utf-8") as f:
                payload = json.load(f)
            _embed_team_state(payload)
            return _enrich_payload(payload)
        boot = _bootstrap_from_portfolio_cache()
        if boot:
            print(f"Cache miss — bootstrapped from portfolio data.json ({boot['brand_count']} brands)")
            return boot
        raise FileNotFoundError(
            f"No cache at {cache_path} and no portfolio data.json to bootstrap"
        )

    _ensure_dbx_on_path()
    from dbx import DBX  # noqa: E402

    with DBX() as dbx:
        return build_payload_live(dbx)


def _render_html(payload: dict[str, Any], gh_token: str, build_id: str) -> str:
    gh_json = json.dumps(gh_token)
    tpl_dir = os.path.join(_ROOT, "templates")
    title = "Malta — Exclusivity targeting"
    esc_title = html_lib.escape(title)
    esc_gen = html_lib.escape(str(payload.get("generated_at") or ""))
    esc_build = html_lib.escape(build_id)
    getplace_link = '<a href="https://brands-by-platform.boltable.eu/" target="_blank" rel="noopener">brands-by-platform</a>'
    getplace_rule = html_lib.escape(str(payload.get("getplace_rule") or ""))
    getplace_meta = payload.get("getplace_market_share") or {}
    getplace_note = ""
    if getplace_meta.get("source"):
        getplace_note = (
            f" GetPlace data: {html_lib.escape(str(getplace_meta.get('source')))} "
            f"({payload.get('getplace_match_count', 0)} brands matched"
            f"{', updated ' + html_lib.escape(str(payload.get('getplace_updated_at'))) if payload.get('getplace_updated_at') else ''})."
        )
    period = html_lib.escape(str(payload.get("gmv_period_label") or ""))
    local_rule = html_lib.escape(str(payload.get("local_order_rule") or ""))
    market_rule = html_lib.escape(str(payload.get("market_share_rule") or ""))
    exclusive_rule = html_lib.escape(str(payload.get("exclusive_rule") or ""))
    msc = payload.get("market_share_config") or {}
    bolt_plat = msc.get("bolt_platform_share_pct")
    wolt_plat = msc.get("wolt_platform_share_pct")
    platform_note = ""
    if bolt_plat is not None:
        wolt_txt = f"{wolt_plat:.1f}%" if wolt_plat is not None else "—"
        platform_note = (
            f" Platform split for est. delivery share: Bolt {bolt_plat:.1f}% · Wolt {wolt_txt}."
        )
    brand_count = payload.get("brand_count", 0)
    total_gmv = payload.get("total_gmv", 0)
    v = html_lib.escape(build_id)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate" />
  <title>{esc_title}</title>
  <link rel="stylesheet" href="dashboard.css?v={v}" />
</head>
<body>
<header>
  <h1>{esc_title}</h1>
  <div class="meta">Generated {esc_gen} · GMV window {period} · {brand_count} brands · Book GMV €{total_gmv:,.0f} · build {esc_build} · Market share: {getplace_link}</div>
  <div id="syncBar" class="sync-bar">Loading dashboard…</div>
  <div class="toolbar">
    <input id="q" type="search" placeholder="Search brand…" />
    <button type="button" class="btn" id="btnClearFilters">Clear filters</button>
    <button type="button" class="btn primary btn-save-team" id="btnSaveTeam">Save for team</button>
    <span id="saveTeamHint" class="meta"></span>
  </div>
</header>
<main>
  <div class="cards" id="summaryCards"></div>
  <div class="table-wrap">
    <table id="brandTable">
      <thead id="brandHead"></thead>
      <tbody id="brandBody"></tbody>
    </table>
  </div>
  <p class="footnote">{local_rule} {market_rule} {exclusive_rule} {getplace_rule}{getplace_note}{html_lib.escape(platform_note)}</p>
</main>
<script src="data.js?v={v}"></script>
<script src="dashboard.js?v={v}"></script>
</body>
</html>"""


def _write_asset_bundle(out_dir: str, payload: dict[str, Any], gh_token: str) -> None:
    """Write dashboard.css, data.js, dashboard.js alongside index.html."""
    tpl_dir = os.path.join(_ROOT, "templates")
    os.makedirs(out_dir, exist_ok=True)
    css_src = os.path.join(tpl_dir, "mt_exclusivity_dashboard.css")
    js_src = os.path.join(tpl_dir, "mt_exclusivity_dashboard.js")
    shutil.copy2(css_src, os.path.join(out_dir, "dashboard.css"))
    with open(js_src, encoding="utf-8") as f:
        js = f.read().replace("__GH_TOKEN__", json.dumps(gh_token))
    with open(os.path.join(out_dir, "dashboard.js"), "w", encoding="utf-8") as f:
        f.write(js)
    with open(os.path.join(out_dir, "data.js"), "w", encoding="utf-8") as f:
        f.write("window.__MT_EXCLUSIVITY_DATA__ = ")
        f.write(_json_for_script(payload))
        f.write(";\n")


def _ensure_state_json() -> None:
    path = _state_json_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.isfile(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"version": 0, "updatedAt": None, "decisions": {}}, f)
            f.write("\n")


def _deploy_boltable(html_path: str) -> None:
    script = os.path.join(_ROOT, "scripts", "deploy_mt_exclusivity_targeting_boltable.sh")
    if not os.path.isfile(script):
        print("Deploy script missing — skipping boltable deploy", file=sys.stderr)
        return
    env = os.environ.copy()
    env["HTML_SRC"] = html_path
    subprocess.run(["bash", script], cwd=_ROOT, env=env, check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Malta exclusivity targeting dashboard")
    parser.add_argument("-o", "--output", default=_default_html())
    parser.add_argument("--data-json", default=_default_data_json())
    parser.add_argument("--months", type=int, default=GMV_MONTHS)
    parser.add_argument("--from-cache", action="store_true")
    parser.add_argument("--no-deploy", action="store_true")
    parser.add_argument(
        "--getplace-path",
        default="",
        help="GetPlace / brands-by-platform JSON or CSV export path",
    )
    args = parser.parse_args()

    payload = load_payload(args.from_cache, args.data_json)
    _attach_getplace_market_share(payload, args.getplace_path or None)
    gh_token = _resolve_gh_state_token()
    if gh_token:
        print("Team sync: GitHub token embedded")
    else:
        print("Team sync: no MT_PORTFOLIO_GH_TOKEN — save disabled", file=sys.stderr)

    _ensure_state_json()
    build_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M")
    html = _render_html(payload, gh_token, build_id)
    out_dir = os.path.dirname(os.path.abspath(args.output)) or "."
    os.makedirs(out_dir, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html)
    _write_asset_bundle(out_dir, payload, gh_token)

    with open(args.data_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")

    public = _boltable_public()
    os.makedirs(public, exist_ok=True)
    shutil.copy2(args.output, os.path.join(public, "index.html"))
    _write_asset_bundle(public, payload, gh_token)
    state_src = _state_json_path()
    state_dst = os.path.join(public, "exclusivity-state.json")
    if os.path.abspath(state_src) != os.path.abspath(state_dst):
        shutil.copy2(state_src, state_dst)

    print(f"Wrote {args.output}")
    print(f"Wrote {args.data_json} ({payload.get('brand_count', 0)} brands)")

    if not args.no_deploy:
        _deploy_boltable(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
