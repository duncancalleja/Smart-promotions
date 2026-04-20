"""Smart Promotions ROI dashboard — Databricks-powered per-provider ROI report."""
from .constants import DASHBOARD_VERSION
from .pipeline import (
    build_demo_payload,
    build_payload_from_dfs,
    default_demo_output_path,
    default_output_path,
    fetch_roi_dataframes,
    roi_dashboard_html_string,
    write_roi_dashboard_html,
)

__all__ = [
    "DASHBOARD_VERSION",
    "build_demo_payload",
    "build_payload_from_dfs",
    "default_demo_output_path",
    "default_output_path",
    "fetch_roi_dataframes",
    "roi_dashboard_html_string",
    "write_roi_dashboard_html",
]
