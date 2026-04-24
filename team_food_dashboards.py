#!/usr/bin/env python3
"""Team entrypoint: Smart Promotions from Databricks in Streamlit.

Deploy on Boltable (or run locally):
  streamlit run team_food_dashboards.py

Uses the same UI as ``smart_promo_app.py`` plus a sidebar with sharing / Boltable notes.
"""

from __future__ import annotations

from smart_promo.streamlit_team import render_smart_promotions

if __name__ == "__main__":
    render_smart_promotions(team_mode=True)
