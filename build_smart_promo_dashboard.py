#!/usr/bin/env python3
"""Write the Smart Promotions dashboard HTML (self-contained file you open in a browser).

Output default: ~/Documents/Bolt food/smart_promo_dashboard_<cc>_<start>_<end>.html
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import warnings

warnings.filterwarnings("ignore", message=".*urllib3 v2 only supports OpenSSL.*")

import smart_promo
from smart_promo import (
    build_demo_payload,
    build_smart_promo_payload_from_dfs,
    default_demo_output_path,
    default_output_path,
    fetch_smart_promo_dataframes,
    write_smart_promo_dashboard_html,
)


def _parse_date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"Invalid date '{value}'. Expected YYYY-MM-DD.") from e


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build Smart Promotions HTML from Databricks (cohorts, report_reason, Bolt vs provider)."
    )
    parser.add_argument("--country-code", default="mt", help="Country code (default: mt)")
    parser.add_argument("--start-date", type=_parse_date, help="Start date inclusive YYYY-MM-DD")
    parser.add_argument("--end-date", type=_parse_date, help="End date inclusive YYYY-MM-DD")
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=60,
        help="If dates omitted, end=today, start=today−N (default: 60)",
    )
    parser.add_argument(
        "--provider-reason-limit",
        type=int,
        default=40000,
        help="Max rows for provider×reason×day detail (default: 40000)",
    )
    parser.add_argument("--enrollment-limit", type=int, default=3000, help="Max enrollment rows")
    parser.add_argument("--output", default=None, help="Output HTML path")
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print each warehouse query as it finishes (stderr)",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Write a sample dashboard (no Databricks) to ~/Documents/Bolt food/smart_promo_dashboard_DEMO_<cc>.html",
    )
    args = parser.parse_args()

    today = dt.date.today()
    if args.start_date and args.end_date:
        start, end = args.start_date, args.end_date
    elif args.start_date or args.end_date:
        print("Provide both --start-date and --end-date, or neither.", file=sys.stderr)
        return 1
    else:
        end = today
        start = today - dt.timedelta(days=int(args.lookback_days))

    if end < start:
        print("end-date must be >= start-date", file=sys.stderr)
        return 1

    cc = args.country_code.strip().lower()

    if args.demo:
        out_path = os.path.abspath(os.path.expanduser(args.output or default_demo_output_path(cc)))
        data = build_demo_payload(country_code=cc, start=start, end=end)
        write_smart_promo_dashboard_html(out_path, data)
        print(f"Wrote (sample data): {out_path}")
        print(f"Dashboard build id: {smart_promo.DASHBOARD_VERSION}")
        return 0

    out_path = os.path.abspath(os.path.expanduser(args.output or default_output_path(cc, start, end)))

    print(
        "Querying Databricks (enrollments, then materialize smart_orders once, then rollups — can take several minutes)…",
        flush=True,
    )
    on_done = (lambda label: print(f"  ok: {label}", flush=True)) if args.verbose else None
    dfs = fetch_smart_promo_dataframes(
        country_code=cc,
        start=start,
        end=end,
        provider_reason_limit=int(args.provider_reason_limit),
        enrollment_limit=int(args.enrollment_limit),
        on_query_complete=on_done,
    )
    by_reason = dfs["by_reason"]
    by_audience = dfs["by_audience"]
    by_lifecycle = dfs["by_lifecycle"]
    by_lcs = dfs["by_lcs"]
    by_enroll_cohort = dfs["by_enroll_cohort"]
    by_pr = dfs["by_pr"]
    enroll = dfs["enroll"]

    data = build_smart_promo_payload_from_dfs(dfs, country_code=cc, start=start, end=end)
    write_smart_promo_dashboard_html(out_path, data)

    print(f"Wrote: {out_path}")
    print(f"Dashboard build id: {smart_promo.DASHBOARD_VERSION}")
    print(f"Distinct report reasons (server): {len(by_reason)}")
    print(f"Product audience cohorts: {len(by_audience)}")
    print(f"Lifecycle buckets: {len(by_lifecycle)}")
    print(f"LCS cohort rows (capped): {len(by_lcs)}")
    print(f"Enrollment cohort rows (capped): {len(by_enroll_cohort)}")
    print(f"Provider×reason rows: {len(by_pr)}")
    print(f"Enrollment rows: {len(enroll)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
