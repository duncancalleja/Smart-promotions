"""Streamlit UI for Smart Promotions (Databricks → embedded HTML).

Used by ``smart_promo_app.py`` (minimal entry) and ``team_food_dashboards.py`` (team + Boltable hints).
"""

from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import smart_promo
from smart_promo import (
    build_smart_promo_payload,
    default_output_path,
    smart_promo_dashboard_html_string,
    write_smart_promo_dashboard_html,
)


def _databricks_configured() -> bool:
    if os.environ.get("DATABRICKS_TOKEN", "").strip():
        return True
    return Path.home().joinpath(".databricks_token").is_file()


def render_smart_promotions(*, team_mode: bool = False) -> None:
    title = "Bolt Food · team — Smart Promotions" if team_mode else "Smart Promotions — live from Databricks"
    st.set_page_config(page_title=title, layout="wide")
    if team_mode:
        with st.sidebar:
            st.markdown("### Team access")
            st.caption("Share this **browser URL** with teammates who can open Boltable.")
            st.caption("Data refreshes when someone picks dates and clicks **Load from Databricks**.")
            st.divider()
            st.markdown("**Boltable**")
            st.caption("Set secret `DATABRICKS_TOKEN` in the app settings (ask `#boltable-support`).")
            st.caption("Allow long runtimes — first load can take many minutes.")
            st.divider()
            st.caption(f"Dashboard package v**{smart_promo.DASHBOARD_VERSION}**")

    st.title("Smart Promotions — live from Databricks")
    st.caption(
        f"Dashboard **v{smart_promo.DASHBOARD_VERSION}** · choose dates and limits, then **Load** to refresh data."
    )

    if not _databricks_configured():
        st.warning(
            "No `DATABRICKS_TOKEN` env var and no `~/.databricks_token` file. "
            "On Boltable, set `DATABRICKS_TOKEN` as a runtime secret. "
            "Locally you can still try **Load** if OAuth works in your environment."
        )

    today = dt.date.today()
    default_start = today - dt.timedelta(days=60)

    with st.form("filters"):
        c1, c2, c3 = st.columns([1, 1, 1])
        with c1:
            country_code = st.text_input("Country code", value="mt", max_chars=4).strip().lower() or "mt"
        with c2:
            start_date = st.date_input("Start date (inclusive)", value=default_start)
        with c3:
            end_date = st.date_input("End date (inclusive)", value=today)
        c4, c5 = st.columns(2)
        with c4:
            provider_reason_limit = st.number_input(
                "Max rows (provider × reason detail)",
                min_value=1000,
                max_value=500000,
                value=40000,
                step=1000,
            )
        with c5:
            enrollment_limit = st.number_input(
                "Max enrollment rows",
                min_value=100,
                max_value=50000,
                value=3000,
                step=100,
            )
        submitted = st.form_submit_button("Load from Databricks", type="primary")

    if submitted:
        if end_date < start_date:
            st.error("End date must be on or after start date.")
        else:
            prog_slot = st.empty()
            status_slot = st.empty()
            progress = prog_slot.progress(0)
            status_slot.caption("Databricks: running 7 queries on one connection…")
            nq = 7
            done = {"n": 0}

            def _on_query(label: str) -> None:
                done["n"] += 1
                progress.progress(min(done["n"] / nq, 1.0))
                status_slot.caption(f"{done['n']}/{nq} — {label}")

            try:
                data = build_smart_promo_payload(
                    country_code=country_code,
                    start=start_date,
                    end=end_date,
                    provider_reason_limit=int(provider_reason_limit),
                    enrollment_limit=int(enrollment_limit),
                    on_query_complete=_on_query,
                )
            except Exception as e:
                prog_slot.empty()
                status_slot.empty()
                st.error(str(e))
                data = None
            else:
                prog_slot.empty()
                status_slot.empty()
            if data is not None:
                st.session_state["smart_promo_data"] = data
                st.session_state["smart_promo_meta"] = {
                    "country": country_code,
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat(),
                }
                st.success("Loaded. Dashboard below.")

    data = st.session_state.get("smart_promo_data")
    if data:
        meta = data.get("meta", {})
        st.subheader(
            f"Snapshot · {str(meta.get('country', '')).upper()} · "
            f"{meta.get('start')} → {meta.get('end')} · "
            f"build {meta.get('dashboard_version', '?')} · {meta.get('built_at', '')}"
        )
        html = smart_promo_dashboard_html_string(data)
        components.html(html, height=1400, scrolling=True)

        out_default = os.path.abspath(
            os.path.expanduser(
                default_output_path(
                    str(meta.get("country", "mt")),
                    dt.date.fromisoformat(str(meta.get("start"))),
                    dt.date.fromisoformat(str(meta.get("end"))),
                )
            )
        )
        st.download_button(
            label="Download HTML (this payload)",
            data=html.encode("utf-8"),
            file_name=os.path.basename(out_default),
            mime="text/html",
        )
        if st.button("Save HTML under ~/Documents/Bolt food/ (default filename)"):
            path = out_default
            try:
                write_smart_promo_dashboard_html(path, data)
                st.info(f"Wrote: {path}")
            except Exception as e:
                st.error(str(e))
