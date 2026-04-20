"""Databricks SQL queries for the Smart Promotions ROI dashboard."""
from __future__ import annotations

import datetime as dt
from typing import Any

import pandas as pd


# ---------------------------------------------------------------------------
# Promotion-type label (derived from spend_objective / campaign name)
# ---------------------------------------------------------------------------

def _promo_type_expr(m: str = "m") -> str:
    return f"""CASE
  WHEN LOWER({m}.spend_objective) LIKE 'sp_%'
    THEN 'Smart Promotion'
  WHEN LOWER({m}.spend_objective) LIKE '%marketing%campaign%'
    OR LOWER({m}.spend_objective) = 'marketing_campaign'
    THEN 'Marketing Campaign'
  WHEN LOWER({m}.spend_objective) LIKE '%sponsored%'
    OR LOWER({m}.spend_objective) LIKE '%listing%'
    THEN 'Sponsored Listing'
  WHEN LOWER(COALESCE({m}.name, '')) LIKE '%self%service%'
    THEN 'Self-Service Portal'
  ELSE COALESCE(NULLIF(TRIM({m}.spend_objective), ''), 'Other')
END"""


# ---------------------------------------------------------------------------
# Audience cohort label — the 5 named cohorts shown in the partner portal
# (mapped from campaign name + lcs_cohort, matching smart_promo/queries.py)
# ---------------------------------------------------------------------------

def _audience_cohort_sql(lcs: str = "lcs_cohort", nm: str = "campaign_name") -> str:
    """SQL CASE expression → one of the 5 partner-portal audience names + Other."""
    hay = f"LOWER(CONCAT_WS(' ', COALESCE({nm}, ''), COALESCE({lcs}, '')))"
    lc  = f"LOWER(COALESCE({lcs}, ''))"
    n   = f"LOWER(COALESCE({nm}, ''))"
    return f"""CASE
  WHEN {n} LIKE '%loyal high frequency%' OR {hay} LIKE '%loyal%high frequency%'
    THEN 'Loyal high frequency customers'
  WHEN {n} LIKE '%most active%' OR {hay} LIKE '%most active%'
    THEN 'Most active customers'
  WHEN {n} LIKE '%high-spending%' OR {n} LIKE '%high spending%'
    OR {hay} LIKE '%high-spending%' OR {hay} LIKE '%high spending%'
    THEN 'High-spending customers'
  WHEN {n} LIKE '%promising returning%'
    OR ({hay} LIKE '%promising%' AND {hay} LIKE '%returning%')
    THEN 'Promising returning customers'
  WHEN {n} LIKE '%new bolt food%' OR {hay} LIKE '%new bolt food%'
    OR {n} LIKE '%new bolt%customer%'
    THEN 'New Bolt Food customers'
  WHEN {lc} LIKE '1_new%' OR {lc} LIKE '%new_user%'
    THEN 'New Bolt Food customers'
  WHEN {lc} LIKE '%_03_high_conversion%'
    OR ({lc} LIKE '2_engaged_03%' AND {lc} LIKE '%high_conversion%')
    THEN 'High-spending customers'
  WHEN {lc} LIKE '2_engaged_02%' THEN 'Most active customers'
  WHEN {lc} LIKE '2_engaged_01%' OR {lc} LIKE '2_engaged_00%'
    THEN 'Promising returning customers'
  WHEN {lc} LIKE '2_engaged%'    THEN 'Most active customers'
  ELSE 'Other / unclassified'
END"""


# ---------------------------------------------------------------------------
# Provider list
# ---------------------------------------------------------------------------

def query_providers(dbx: Any, country: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    """All providers with any promotion spend in the period, with name + segment."""
    cc = country.lower()
    return dbx.query(f"""
SELECT
  CAST(m.provider_id AS BIGINT)                                  AS provider_id,
  COALESCE(NULLIF(TRIM(p.provider_name), ''),
           CAST(m.provider_id AS STRING))                        AS provider_name,
  COALESCE(NULLIF(TRIM(p.business_segment_v2), ''), '')          AS segment,
  COALESCE(NULLIF(TRIM(p.brand_name), ''), '')                   AS brand_name,
  COALESCE(NULLIF(TRIM(p.account_manager_name), ''), '')         AS am
FROM ng_public_spark.etl_delivery_campaign_order_metrics m
JOIN ng_delivery_spark.dim_provider_v2 p
  ON  p.provider_id   = m.provider_id
  AND LOWER(p.country_code) = '{cc}'
WHERE LOWER(m.country) = '{cc}'
  AND m.order_created_date >= DATE '{start.isoformat()}'
  AND m.order_created_date <= DATE '{end.isoformat()}'
  AND LOWER(m.spend_objective) LIKE 'sp_%'
  AND COALESCE(m.provider_spend_local, 0) > 0
GROUP BY
  m.provider_id,
  p.provider_name,
  p.business_segment_v2,
  p.brand_name,
  p.account_manager_name
ORDER BY p.provider_name
LIMIT 5000
""")


# ---------------------------------------------------------------------------
# Weekly investment vs sales GMV (for line charts)
# ---------------------------------------------------------------------------

def query_weekly_roi(dbx: Any, country: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    """
    Weekly: provider_invest, bolt_invest, sales_gmv, promoted_orders — per provider.

    NOTE: Joins etl_delivery_campaign_order_metrics with
          etl_delivery_order_monetary_metrics on order_id to get gmv_eur.
    """
    cc = country.lower()
    return dbx.query(f"""
SELECT
  CAST(m.provider_id AS BIGINT)                                      AS provider_id,
  CAST(DATE_TRUNC('week', m.order_created_date) AS STRING)           AS week_start,
  CAST(SUM(COALESCE(m.provider_spend_local, 0)) AS DOUBLE)           AS provider_invest,
  CAST(SUM(COALESCE(m.bolt_spend_local, 0)) AS DOUBLE)               AS bolt_invest,
  CAST(SUM(COALESCE(o.gmv_eur, 0)) AS DOUBLE)                        AS sales_gmv,
  CAST(COUNT(DISTINCT m.order_id) AS BIGINT)                         AS promoted_orders
FROM ng_public_spark.etl_delivery_campaign_order_metrics m
LEFT JOIN ng_public_spark.etl_delivery_order_monetary_metrics o
  ON o.order_id = m.order_id
WHERE LOWER(m.country) = '{cc}'
  AND m.order_created_date >= DATE '{start.isoformat()}'
  AND m.order_created_date <= DATE '{end.isoformat()}'
  AND LOWER(m.spend_objective) LIKE 'sp_%'
  AND COALESCE(m.provider_spend_local, 0) > 0
GROUP BY
  m.provider_id,
  DATE_TRUNC('week', m.order_created_date)
ORDER BY provider_id, week_start
LIMIT 100000
""")


# ---------------------------------------------------------------------------
# Performance by promotion type
# ---------------------------------------------------------------------------

def query_by_promo_type(dbx: Any, country: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    """Investment, GMV and orders broken down by promotion type — per provider."""
    cc = country.lower()
    pt = _promo_type_expr("m")
    return dbx.query(f"""
SELECT
  CAST(m.provider_id AS BIGINT)                              AS provider_id,
  {pt}                                                       AS promotion_type,
  CAST(SUM(COALESCE(m.provider_spend_local, 0)) AS DOUBLE)   AS provider_invest,
  CAST(SUM(COALESCE(m.bolt_spend_local, 0)) AS DOUBLE)       AS bolt_invest,
  CAST(SUM(COALESCE(o.gmv_eur, 0)) AS DOUBLE)                AS sales_gmv,
  CAST(COUNT(DISTINCT m.order_id) AS BIGINT)                 AS promoted_orders
FROM ng_public_spark.etl_delivery_campaign_order_metrics m
LEFT JOIN ng_public_spark.etl_delivery_order_monetary_metrics o
  ON o.order_id = m.order_id
WHERE LOWER(m.country) = '{cc}'
  AND m.order_created_date >= DATE '{start.isoformat()}'
  AND m.order_created_date <= DATE '{end.isoformat()}'
  AND LOWER(m.spend_objective) LIKE 'sp_%'
  AND COALESCE(m.provider_spend_local, 0) > 0
GROUP BY
  m.provider_id,
  {pt}
ORDER BY provider_id, provider_invest DESC
LIMIT 50000
""")


# ---------------------------------------------------------------------------
# Total orders per provider (all orders, for % promoted)
# ---------------------------------------------------------------------------

def query_total_orders(dbx: Any, country: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    """All orders per provider in period (denominator for % promoted orders)."""
    cc = country.lower()
    return dbx.query(f"""
SELECT
  CAST(provider_id AS BIGINT)              AS provider_id,
  CAST(COUNT(DISTINCT order_id) AS BIGINT) AS total_orders
FROM ng_public_spark.etl_delivery_order_monetary_metrics
WHERE LOWER(country) = '{cc}'
  AND order_created_date >= DATE '{start.isoformat()}'
  AND order_created_date <= DATE '{end.isoformat()}'
GROUP BY provider_id
LIMIT 20000
""")


# ---------------------------------------------------------------------------
# Customers reached & first-time customers
# ---------------------------------------------------------------------------

def query_customers(dbx: Any, country: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    """
    Customers reached (distinct eaters with a promoted order) and first-time
    customers (eaters whose first-ever order at this provider fell in this period).

    Uses 'user_id' from etl_delivery_order_monetary_metrics.
    first_order lookback is 2 years to keep the query bounded.
    """
    cc = country.lower()
    lookback = start - dt.timedelta(days=730)
    return dbx.query(f"""
WITH promo_eaters AS (
  SELECT
    CAST(m.provider_id AS BIGINT) AS provider_id,
    o.user_id
  FROM ng_public_spark.etl_delivery_campaign_order_metrics m
  JOIN ng_public_spark.etl_delivery_order_monetary_metrics o
    ON o.order_id = m.order_id
  WHERE LOWER(m.country) = '{cc}'
    AND m.order_created_date >= DATE '{start.isoformat()}'
    AND m.order_created_date <= DATE '{end.isoformat()}'
    AND LOWER(m.spend_objective) LIKE 'sp_%'
    AND COALESCE(m.provider_spend_local, 0) > 0
    AND o.user_id IS NOT NULL
),
first_orders AS (
  SELECT
    CAST(provider_id AS BIGINT) AS provider_id,
    user_id,
    MIN(order_created_date) AS first_order_date
  FROM ng_public_spark.etl_delivery_order_monetary_metrics
  WHERE LOWER(country) = '{cc}'
    AND user_id IS NOT NULL
    AND order_created_date >= DATE '{lookback.isoformat()}'
  GROUP BY provider_id, user_id
)
SELECT
  pe.provider_id,
  CAST(COUNT(DISTINCT pe.user_id) AS BIGINT) AS customers_reached,
  CAST(COUNT(DISTINCT CASE
    WHEN fo.first_order_date >= DATE '{start.isoformat()}'
     AND fo.first_order_date <= DATE '{end.isoformat()}'
    THEN pe.user_id
  END) AS BIGINT)                              AS first_time_customers
FROM promo_eaters pe
LEFT JOIN first_orders fo
  ON fo.provider_id = pe.provider_id
 AND fo.user_id     = pe.user_id
GROUP BY pe.provider_id
LIMIT 20000
""")


# ---------------------------------------------------------------------------
# SP audience cohort split (the 5 partner-portal cohorts) per provider
# ---------------------------------------------------------------------------

def query_by_sp_cohort(dbx: Any, country: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    """
    Investment, GMV and orders broken down by the 5 SP audience cohorts
    (New Bolt Food customers / Promising returning / High-spending /
     Most active / Loyal high frequency) — per provider.

    Uses a cohort_map CTE joining etl_delivery_campaigns_enrollments to map
    campaign_id → lcs_cohort, then applies the same audience label logic as
    the partner portal UI.
    """
    cc       = country.lower()
    # 90-day lookback for enrollments: smart promo campaigns enrolled well
    # before the query window are rare; this keeps the CTE fast.
    enr_from = start - dt.timedelta(days=90)
    aud_sql  = _audience_cohort_sql("c.lcs_cohort", "m.name")
    return dbx.query(f"""
WITH cohort_map AS (
  SELECT
    e.campaign_id,
    ANY_VALUE(NULLIF(TRIM(e.lcs_cohort), '')) AS lcs_cohort
  FROM   ng_public_spark.etl_delivery_campaigns_enrollments e
  WHERE  LOWER(e.country) = '{cc}'
    AND  e.enrolled_at_date >= DATE '{enr_from.isoformat()}'
    AND  e.enrolled_at_date <= DATE '{end.isoformat()}'
  GROUP BY e.campaign_id
)
SELECT
  CAST(m.provider_id AS BIGINT)                              AS provider_id,
  {aud_sql}                                                  AS audience_cohort,
  CAST(SUM(COALESCE(m.provider_spend_local, 0)) AS DOUBLE)   AS provider_invest,
  CAST(SUM(COALESCE(m.bolt_spend_local, 0)) AS DOUBLE)       AS bolt_invest,
  CAST(SUM(COALESCE(o.gmv_eur, 0)) AS DOUBLE)                AS sales_gmv,
  CAST(COUNT(DISTINCT m.order_id) AS BIGINT)                 AS promoted_orders
FROM   ng_public_spark.etl_delivery_campaign_order_metrics m
LEFT JOIN cohort_map c
  ON   c.campaign_id = m.campaign_id
LEFT JOIN ng_public_spark.etl_delivery_order_monetary_metrics o
  ON   o.order_id = m.order_id
WHERE  LOWER(m.country) = '{cc}'
  AND  m.order_created_date >= DATE '{start.isoformat()}'
  AND  m.order_created_date <= DATE '{end.isoformat()}'
  AND  LOWER(m.spend_objective) LIKE 'sp_%'
  AND  COALESCE(m.provider_spend_local, 0) > 0
GROUP BY m.provider_id, audience_cohort
ORDER BY provider_id, provider_invest DESC
LIMIT 50000
""")
