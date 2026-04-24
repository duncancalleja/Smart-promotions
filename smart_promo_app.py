"""Streamlit app: load Smart Promotions dashboard data from Databricks when you set dates and submit.

Run from repo root:
  streamlit run smart_promo_app.py

Uses the `smart_promo` package (same queries as the CLI builder). Static HTML alone cannot call Databricks
safely from the browser; this app runs queries server-side and embeds the full dashboard UI.

For a team-oriented entry with Boltable hints in the sidebar, use:
  streamlit run team_food_dashboards.py
"""

from __future__ import annotations

from smart_promo.streamlit_team import render_smart_promotions

if __name__ == "__main__":
    render_smart_promotions(team_mode=False)
