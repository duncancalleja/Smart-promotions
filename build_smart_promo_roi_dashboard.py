#!/usr/bin/env python3
"""Build the Smart Promotions ROI dashboard HTML (self-contained, open in browser).

Replicates the per-provider ROI report previously served by Google Apps Script —
dark theme, hero ROAS, investment vs sales charts, weekly ROAS trend, and an
AI-generated summary + recommendation per provider.

Output default: ~/Documents/Bolt food/smart_promo_roi_<cc>_<start>_<end>.html

Usage examples
--------------
# Preview with sample data (no Databricks connection needed)
python3 build_smart_promo_roi_dashboard.py --demo

# Full build for Malta, last 90 days
python3 build_smart_promo_roi_dashboard.py --country-code mt --lookback-days 90

# Specific date range
python3 build_smart_promo_roi_dashboard.py --country-code mt \
    --start-date 2025-12-22 --end-date 2026-03-30

# Save to a custom path
python3 build_smart_promo_roi_dashboard.py --output ~/Desktop/roi_dashboard.html
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import warnings

warnings.filterwarnings("ignore", message=".*urllib3 v2 only supports OpenSSL.*")

import smart_promo_roi
from smart_promo_roi import (
    build_demo_payload,
    build_payload_from_dfs,
    default_demo_output_path,
    default_output_path,
    fetch_roi_dataframes,
    write_roi_dashboard_html,
)


def _parse_date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"Invalid date '{value}'. Expected YYYY-MM-DD.") from e


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build the Smart Promotions ROI dashboard HTML from Databricks. "
            "Shows per-provider ROAS, investment vs sales charts, and AI-generated summaries."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--country-code", default="mt",
                        help="Country code (default: mt)")
    parser.add_argument("--start-date", type=_parse_date,
                        help="Start date inclusive YYYY-MM-DD")
    parser.add_argument("--end-date",   type=_parse_date,
                        help="End date inclusive YYYY-MM-DD")
    parser.add_argument("--lookback-days", type=int, default=90,
                        help="If dates omitted, end=today, start=today−N (default: 90)")
    parser.add_argument("--output", default=None,
                        help="Output HTML path (default: ~/Documents/Bolt food/smart_promo_roi_…html)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print each query as it completes (stderr)")
    parser.add_argument("--demo", action="store_true",
                        help="Write sample dashboard (no Databricks) for layout preview")
    args = parser.parse_args()

    today = dt.date.today()
    if args.start_date and args.end_date:
        start, end = args.start_date, args.end_date
    elif args.start_date or args.end_date:
        print("Provide both --start-date and --end-date, or neither.", file=sys.stderr)
        return 1
    else:
        end   = today
        start = today - dt.timedelta(days=int(args.lookback_days))

    if end < start:
        print("--end-date must be >= --start-date", file=sys.stderr)
        return 1

    cc = args.country_code.strip().lower()

    # ── Demo mode ──────────────────────────────────────────────────────────
    if args.demo:
        out_path = os.path.abspath(
            os.path.expanduser(args.output or default_demo_output_path(cc))
        )
        data = build_demo_payload(country_code=cc, start=start, end=end)
        write_roi_dashboard_html(out_path, data)
        print(f"Wrote (sample data): {out_path}")
        print(f"Dashboard version: {smart_promo_roi.DASHBOARD_VERSION}")
        print("Tip: open the file in your browser and use the provider dropdown to switch providers.")
        return 0

    # ── Live Databricks build ───────────────────────────────────────────────
    out_path = os.path.abspath(
        os.path.expanduser(args.output or default_output_path(cc, start, end))
    )

    print(
        f"Querying Databricks for {cc.upper()} · {start.isoformat()} – {end.isoformat()} …",
        flush=True,
    )
    on_done = (lambda label: print(f"  ok: {label}", flush=True)) if args.verbose else None

    dfs = fetch_roi_dataframes(
        country_code=cc,
        start=start,
        end=end,
        on_query_complete=on_done,
    )

    n_providers = len(dfs["providers"])
    n_weekly    = len(dfs["weekly"])
    n_promo     = len(dfs["by_promo_type"])

    if n_providers == 0:
        print(
            "Warning: no providers found with promotion spend in this window. "
            "Check country code and date range.",
            file=sys.stderr,
        )

    data = build_payload_from_dfs(dfs, country_code=cc, start=start, end=end)
    write_roi_dashboard_html(out_path, data)

    print(f"\nWrote: {out_path}")
    print(f"Dashboard version : {smart_promo_roi.DASHBOARD_VERSION}")
    print(f"Providers in file : {n_providers}")
    print(f"Weekly rows       : {n_weekly}")
    print(f"Promo-type rows   : {n_promo}")
    print("\nOpen the file in your browser — use the provider dropdown and click Load Report.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
