"""Databricks SQL for smart promotions (order metrics + enrollment cohorts)."""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

import pandas as pd

def _smart_promo_predicate(alias: str = "m") -> str:
    a = alias
    return (
        f"(LOWER({a}.spend_objective) LIKE 'sp_%' "
        f"OR {a}.spend_objective IN ('sp_engagement', 'sp_reactivation'))"
    )


def _report_reason_expr(alias: str = "m", cohort_alias: str = "c") -> str:
    """SQL expression aliased as report_reason."""
    m, c = alias, cohort_alias
    return f"""COALESCE(
  NULLIF(TRIM({c}.lcs_cohort), ''),
  NULLIF(TRIM({c}.cohort), ''),
  CONCAT_WS(' · ',
    COALESCE(NULLIF(TRIM({m}.spend_objective), ''), '?'),
    COALESCE(NULLIF(TRIM({m}.target), ''), '?')
  )
) AS report_reason"""


def _audience_cohort_sql() -> str:
    """Map rows to the five Bolt Food 'Choose an audience' cohorts (+ other). Uses name + LCS heuristics."""
    # hay = lower concat of name, lcs, enrollment for keyword hits from partner-facing copy
    hay = (
        "LOWER(CONCAT_WS(' ', COALESCE(campaign_name, ''), COALESCE(lcs_cohort, ''), "
        "COALESCE(enrollment_cohort, '')))"
    )
    lc = "LOWER(COALESCE(lcs_cohort, ''))"
    nm = "LOWER(COALESCE(campaign_name, ''))"
    return f"""CASE
  WHEN {nm} LIKE '%loyal high frequency%' OR {hay} LIKE '%loyal%high frequency%'
    THEN 'Loyal high frequency customers'
  WHEN {nm} LIKE '%most active%' OR {hay} LIKE '%most active%'
    THEN 'Most active customers'
  WHEN {nm} LIKE '%high-spending%' OR {nm} LIKE '%high spending%' OR {hay} LIKE '%high-spending%'
    OR {hay} LIKE '%high spending%'
    THEN 'High-spending customers'
  WHEN {nm} LIKE '%promising returning%' OR ({hay} LIKE '%promising%' AND {hay} LIKE '%returning%')
    THEN 'Promising returning customers'
  WHEN {nm} LIKE '%new bolt food%' OR {hay} LIKE '%new bolt food%' OR {nm} LIKE '%new bolt%customer%'
    THEN 'New Bolt Food customers'
  WHEN {lc} LIKE '1_new%' OR {lc} LIKE '%new_user%' THEN 'New Bolt Food customers'
  WHEN {lc} LIKE '%_03_high_conversion%' OR ({lc} LIKE '2_engaged_03%' AND {lc} LIKE '%high_conversion%')
    THEN 'High-spending customers'
  WHEN {lc} LIKE '2_engaged_02%' THEN 'Most active customers'
  WHEN {lc} LIKE '2_engaged_01%' THEN 'Promising returning customers'
  WHEN {lc} LIKE '2_engaged_00%' THEN 'Promising returning customers'
  WHEN {lc} LIKE '2_engaged%' THEN 'Most active customers'
  ELSE 'Other / unclassified'
END AS audience_cohort"""


def sql_smart_orders_cte(country: str, start: dt.date, end: dt.date) -> str:
    """Cohort map only for campaign_ids seen in the smart-promo window (faster than global scan)."""
    cc = country.lower()
    sp = _smart_promo_predicate("m")
    lookback = start - dt.timedelta(days=730)
    return f"""
WITH smart_campaign_ids AS (
  SELECT DISTINCT m.campaign_id
  FROM ng_public_spark.etl_delivery_campaign_order_metrics m
  WHERE LOWER(m.country) = '{cc}'
    AND m.order_created_date >= DATE '{start.isoformat()}'
    AND m.order_created_date <= DATE '{end.isoformat()}'
    AND {sp}
    AND m.campaign_id IS NOT NULL
),
cohort_map AS (
  SELECT
    e.campaign_id,
    ANY_VALUE(NULLIF(TRIM(e.lcs_cohort), '')) AS lcs_cohort,
    ANY_VALUE(NULLIF(TRIM(e.cohort), '')) AS cohort,
    ANY_VALUE(NULLIF(TRIM(e.treatment_type), '')) AS treatment_type
  FROM ng_public_spark.etl_delivery_campaigns_enrollments e
  INNER JOIN smart_campaign_ids sc ON sc.campaign_id = e.campaign_id
  WHERE e.enrolled_at_date >= DATE '{lookback.isoformat()}'
    AND e.enrolled_at_date <= DATE '{end.isoformat()}'
  GROUP BY e.campaign_id
),
smart_orders_base AS (
  SELECT
    m.order_id,
    m.provider_id,
    m.campaign_id,
    m.order_created_date,
    m.spend_objective,
    m.target,
    {_report_reason_expr('m', 'c')},
    COALESCE(NULLIF(TRIM(c.lcs_cohort), ''), '') AS lcs_cohort,
    COALESCE(NULLIF(TRIM(c.cohort), ''), '') AS enrollment_cohort,
    COALESCE(NULLIF(TRIM(c.treatment_type), ''), '') AS treatment_type,
    COALESCE(NULLIF(TRIM(m.name), ''), '') AS campaign_name,
    CAST(COALESCE(m.bolt_spend_local, 0) AS DOUBLE) AS bolt_local,
    CAST(COALESCE(m.provider_spend_local, 0) AS DOUBLE) AS provider_local
  FROM ng_public_spark.etl_delivery_campaign_order_metrics m
  LEFT JOIN cohort_map c ON c.campaign_id = m.campaign_id
  WHERE LOWER(m.country) = '{cc}'
    AND m.order_created_date >= DATE '{start.isoformat()}'
    AND m.order_created_date <= DATE '{end.isoformat()}'
    AND {sp}
),
smart_orders AS (
  SELECT
    order_id,
    provider_id,
    campaign_id,
    order_created_date,
    spend_objective,
    target,
    campaign_name,
    report_reason,
    lcs_cohort,
    enrollment_cohort,
    treatment_type,
    CASE
      WHEN LOWER(lcs_cohort) LIKE '%churned%' THEN 'Churned'
      WHEN LOWER(lcs_cohort) LIKE '%churning%' THEN 'Churning'
      WHEN LOWER(lcs_cohort) LIKE '%engaged%' THEN 'Engaged'
      WHEN LOWER(lcs_cohort) LIKE '%not_active%' OR LOWER(lcs_cohort) LIKE '%not active%' THEN 'Not active'
      WHEN LOWER(lcs_cohort) LIKE '%new_user%' OR LOWER(lcs_cohort) LIKE '1_new%' THEN 'New / early'
      WHEN NULLIF(lcs_cohort, '') IS NULL THEN '(not mapped)'
      ELSE 'Other'
    END AS lifecycle_bucket,
    {_audience_cohort_sql()},
    bolt_local,
    provider_local
  FROM smart_orders_base
)
""".strip()


def _smart_orders_sql_prefix(country: str, start: dt.date, end: dt.date, session_view: Optional[str]) -> str:
    """Inline heavy CTE, or cheap wrap when `session_view` was built from that CTE in-session."""
    if session_view:
        safe = session_view.replace("`", "").replace(";", "")
        return f"WITH smart_orders AS (SELECT * FROM {safe})\n"
    return sql_smart_orders_cte(country, start, end) + "\n"


def create_smart_orders_session_view(
    dbx: Any, country: str, start: dt.date, end: dt.date, view_name: str
) -> None:
    """Materialize smart_orders once (TEMPORARY VIEW) for follow-up rollups on the same connection."""
    safe = view_name.replace("`", "").replace(";", "")
    ddl = (
        f"CREATE OR REPLACE TEMPORARY VIEW {safe} AS\n"
        + sql_smart_orders_cte(country, start, end)
        + "\nSELECT * FROM smart_orders"
    )
    dbx.execute(ddl)


def drop_smart_orders_session_view(dbx: Any, view_name: str) -> None:
    safe = view_name.replace("`", "").replace(";", "")
    dbx.execute(f"DROP VIEW IF EXISTS {safe}")


def query_by_report_reason(
    dbx: Any,
    country: str,
    start: dt.date,
    end: dt.date,
    session_view: Optional[str] = None,
) -> pd.DataFrame:
    q = (
        _smart_orders_sql_prefix(country, start, end, session_view)
        + """
SELECT
  report_reason,
  CAST(SUM(bolt_local) AS DOUBLE) AS bolt_spend_local,
  CAST(SUM(provider_local) AS DOUBLE) AS provider_spend_local,
  CAST(SUM(bolt_local + provider_local) AS DOUBLE) AS total_spend_local,
  CAST(COUNT(DISTINCT order_id) AS BIGINT) AS orders,
  CAST(COUNT(DISTINCT provider_id) AS BIGINT) AS providers
FROM smart_orders
GROUP BY report_reason
ORDER BY total_spend_local DESC
"""
    )
    return dbx.query(q)


def query_by_audience_cohort(
    dbx: Any,
    country: str,
    start: dt.date,
    end: dt.date,
    session_view: Optional[str] = None,
) -> pd.DataFrame:
    q = (
        _smart_orders_sql_prefix(country, start, end, session_view)
        + """
SELECT
  audience_cohort,
  CAST(SUM(bolt_local) AS DOUBLE) AS bolt_spend_local,
  CAST(SUM(provider_local) AS DOUBLE) AS provider_spend_local,
  CAST(SUM(bolt_local + provider_local) AS DOUBLE) AS total_spend_local,
  CAST(COUNT(DISTINCT order_id) AS BIGINT) AS orders,
  CAST(COUNT(DISTINCT provider_id) AS BIGINT) AS providers
FROM smart_orders
GROUP BY audience_cohort
ORDER BY total_spend_local DESC
"""
    )
    return dbx.query(q)


def query_by_lifecycle_bucket(
    dbx: Any,
    country: str,
    start: dt.date,
    end: dt.date,
    session_view: Optional[str] = None,
) -> pd.DataFrame:
    q = (
        _smart_orders_sql_prefix(country, start, end, session_view)
        + """
SELECT
  lifecycle_bucket,
  CAST(SUM(bolt_local) AS DOUBLE) AS bolt_spend_local,
  CAST(SUM(provider_local) AS DOUBLE) AS provider_spend_local,
  CAST(SUM(bolt_local + provider_local) AS DOUBLE) AS total_spend_local,
  CAST(COUNT(DISTINCT order_id) AS BIGINT) AS orders,
  CAST(COUNT(DISTINCT provider_id) AS BIGINT) AS providers
FROM smart_orders
GROUP BY lifecycle_bucket
ORDER BY total_spend_local DESC
"""
    )
    return dbx.query(q)


def query_by_lcs_cohort_top(
    dbx: Any,
    country: str,
    start: dt.date,
    end: dt.date,
    limit: int = 100,
    session_view: Optional[str] = None,
) -> pd.DataFrame:
    q = (
        _smart_orders_sql_prefix(country, start, end, session_view)
        + f"""
SELECT * FROM (
  SELECT
    COALESCE(NULLIF(TRIM(lcs_cohort), ''), '(not mapped)') AS lcs_cohort,
    CAST(SUM(bolt_local) AS DOUBLE) AS bolt_spend_local,
    CAST(SUM(provider_local) AS DOUBLE) AS provider_spend_local,
    CAST(SUM(bolt_local + provider_local) AS DOUBLE) AS total_spend_local,
    CAST(COUNT(DISTINCT order_id) AS BIGINT) AS orders,
    CAST(COUNT(DISTINCT provider_id) AS BIGINT) AS providers
  FROM smart_orders
  GROUP BY COALESCE(NULLIF(TRIM(lcs_cohort), ''), '(not mapped)')
) t
ORDER BY t.total_spend_local DESC
LIMIT {int(limit)}
"""
    )
    return dbx.query(q)


def query_by_enrollment_cohort(
    dbx: Any,
    country: str,
    start: dt.date,
    end: dt.date,
    limit: int = 120,
    session_view: Optional[str] = None,
) -> pd.DataFrame:
    q = (
        _smart_orders_sql_prefix(country, start, end, session_view)
        + f"""
SELECT * FROM (
  SELECT
    COALESCE(NULLIF(TRIM(enrollment_cohort), ''), '(not mapped)') AS enrollment_cohort,
    CAST(SUM(bolt_local) AS DOUBLE) AS bolt_spend_local,
    CAST(SUM(provider_local) AS DOUBLE) AS provider_spend_local,
    CAST(SUM(bolt_local + provider_local) AS DOUBLE) AS total_spend_local,
    CAST(COUNT(DISTINCT order_id) AS BIGINT) AS orders,
    CAST(COUNT(DISTINCT provider_id) AS BIGINT) AS providers
  FROM smart_orders
  GROUP BY COALESCE(NULLIF(TRIM(enrollment_cohort), ''), '(not mapped)')
) t
ORDER BY t.total_spend_local DESC
LIMIT {int(limit)}
"""
    )
    return dbx.query(q)


def query_provider_reason_detail(
    dbx: Any,
    country: str,
    start: dt.date,
    end: dt.date,
    limit: int,
    session_view: Optional[str] = None,
) -> pd.DataFrame:
    q = (
        _smart_orders_sql_prefix(country, start, end, session_view)
        + f"""
SELECT * FROM (
  SELECT
    CAST(s.order_created_date AS STRING) AS order_date,
    s.provider_id,
    COALESCE(NULLIF(TRIM(p.provider_name), ''), '') AS provider_name,
    COALESCE(NULLIF(TRIM(p.account_manager_name), ''), 'Unknown') AS am,
    COALESCE(NULLIF(TRIM(p.business_segment_v2), ''), '') AS segment,
    COALESCE(NULLIF(TRIM(p.brand_name), ''), '') AS brand_name,
    COALESCE(NULLIF(TRIM(p.provider_status), ''), '') AS provider_status,
    s.report_reason,
    s.lcs_cohort,
    s.enrollment_cohort,
    s.lifecycle_bucket,
    s.audience_cohort,
    COALESCE(NULLIF(TRIM(s.treatment_type), ''), '') AS treatment_type,
    s.spend_objective,
    s.target,
    CAST(SUM(s.bolt_local) AS DOUBLE) AS bolt_spend_local,
    CAST(SUM(s.provider_local) AS DOUBLE) AS provider_spend_local,
    CAST(SUM(s.bolt_local + s.provider_local) AS DOUBLE) AS total_spend_local,
    CAST(COUNT(DISTINCT s.order_id) AS BIGINT) AS orders
  FROM smart_orders s
  LEFT JOIN ng_delivery_spark.dim_provider_v2 p
    ON p.provider_id = s.provider_id AND LOWER(p.country_code) = '{country.lower()}'
  GROUP BY
    s.order_created_date,
    s.provider_id,
    p.provider_name,
    p.account_manager_name,
    p.business_segment_v2,
    p.brand_name,
    p.provider_status,
    s.report_reason,
    s.lcs_cohort,
    s.enrollment_cohort,
    s.lifecycle_bucket,
    s.audience_cohort,
    s.treatment_type,
    s.spend_objective,
    s.target
) t
WHERE t.total_spend_local > 0
ORDER BY t.total_spend_local DESC
LIMIT {int(limit)}
"""
    )
    return dbx.query(q)


def query_enrollments(dbx: Any, country: str, start: dt.date, end: dt.date, limit: int) -> pd.DataFrame:
    return dbx.query(
        f"""
        SELECT
          CAST(e.provider_id AS BIGINT) AS provider_id,
          COALESCE(p.provider_name, '') AS provider_name,
          COALESCE(NULLIF(TRIM(p.brand_name), ''), '') AS brand_name,
          COALESCE(NULLIF(TRIM(p.account_manager_name), ''), 'Unknown') AS am,
          COALESCE(p.business_segment_v2, '') AS segment,
          COALESCE(e.smart_promo_offer_type, '') AS smart_promo_offer_type,
          COALESCE(e.smart_promo_type, '') AS smart_promo_type,
          COALESCE(e.smart_promo_enrollment_state, '') AS enrollment_state,
          COALESCE(e.smart_promo_offer_mode, '') AS smart_promo_offer_mode,
          CAST(e.smart_promo_offer_provider_enrollment_start_date AS STRING) AS enrollment_start_date,
          COALESCE(e.campaign_spend_objective, '') AS campaign_spend_objective,
          CAST(e.campaign_id AS STRING) AS campaign_id,
          CAST(e.is_valid_promotion AS STRING) AS is_valid_promotion
        FROM core_models_spark.fact_provider_smart_promo_offer_campaign_enrollment e
        INNER JOIN ng_delivery_spark.dim_provider_v2 p
          ON p.provider_id = e.provider_id
         AND LOWER(p.country_code) = '{country.lower()}'
        WHERE e.smart_promo_offer_provider_enrollment_start_date >= DATE '{start.isoformat()}'
          AND e.smart_promo_offer_provider_enrollment_start_date <= DATE '{end.isoformat()}'
        ORDER BY e.smart_promo_offer_provider_enrollment_start_date DESC
        LIMIT {int(limit)}
        """
    )
