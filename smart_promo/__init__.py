"""Smart promotions dashboard: Databricks queries + self-contained HTML."""

from .constants import DASHBOARD_VERSION
from .pipeline import (
    build_demo_payload,
    build_smart_promo_payload,
    build_smart_promo_payload_from_dfs,
    default_demo_output_path,
    default_output_path,
    fetch_smart_promo_dataframes,
    smart_promo_dashboard_html_string,
    write_smart_promo_dashboard_html,
)

__all__ = [
    "DASHBOARD_VERSION",
    "build_demo_payload",
    "build_smart_promo_payload",
    "build_smart_promo_payload_from_dfs",
    "default_demo_output_path",
    "default_output_path",
    "fetch_smart_promo_dataframes",
    "smart_promo_dashboard_html_string",
    "write_smart_promo_dashboard_html",
]
