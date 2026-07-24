#!/usr/bin/env python3
"""
Try to refresh GetPlace / brands-by-platform export for exclusivity dashboard.

Writes: ~/Documents/Bolt food/mt_brands_by_platform.json

Sources (first match wins):
  1. Existing file if --keep-if-fresh (default 8 days) and no newer source
  2. BOLTABLE_GETPLACE_JSON or --input path (copy/normalize)
  3. boltable/mt-exclusivity-targeting/public/getplace-brands.json (last deploy snapshot)
  4. HTTPS fetch to brands-by-platform.boltable.eu (needs NetBird + BOLTABLE_COOKIE if SSO)
  5. gh download from boltable/brands-by-platform (if repo exists)

Usage:
  python3 scripts/fetch_brands_by_platform_export.py
  python3 scripts/fetch_brands_by_platform_export.py --input ~/Downloads/export.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Any

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from mt_getplace_market_share import brand_key, load_from_csv, load_from_json  # noqa: E402

_OUT = os.path.expanduser("~/Documents/Bolt food/mt_brands_by_platform.json")
_BBP_URLS = (
    "https://brands-by-platform.boltable.eu/data.json",
    "https://brands-by-platform.boltable.eu/public/data.json",
    "https://brands-by-platform.boltable.eu/brands.json",
)
_SNAPSHOT = os.path.join(
    _ROOT, "boltable", "mt-exclusivity-targeting", "public", "getplace-brands.json"
)


def _write_export(
    brands: dict[str, dict[str, Any]], source: str, out_path: str
) -> None:
    payload = {
        "updated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "source": source,
        "brand_count": len(brands),
        "brands": [
            {"brand_key": k, **v} for k, v in sorted(brands.items(), key=lambda x: x[0])
        ],
    }
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"Wrote {out_path} ({len(brands)} brands from {source})")


def _file_age_days(path: str) -> float | None:
    if not os.path.isfile(path):
        return None
    mtime = os.path.getmtime(path)
    return (dt.datetime.now().timestamp() - mtime) / 86400.0


def _normalize_input(path: str) -> dict[str, dict[str, Any]]:
    if path.lower().endswith(".csv"):
        brands, _ = load_from_csv(path)
        return brands
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, dict) and isinstance(raw.get("brands"), list):
        brands, _ = load_from_json(path)
        return brands
    if isinstance(raw, dict) and all(isinstance(v, dict) for v in raw.values()):
        return raw
    brands, _ = load_from_json(path)
    return brands


def _load_snapshot(path: str) -> dict[str, dict[str, Any]] | None:
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data.get("brands"), list):
        out: dict[str, dict[str, Any]] = {}
        for row in data["brands"]:
            if not isinstance(row, dict):
                continue
            key = brand_key(str(row.get("brand_key") or row.get("brand_name") or ""))
            if key:
                out[key] = row
        return out or None
    return None


def _fetch_url(url: str, cookie: str | None) -> Any | None:
    headers = {"User-Agent": "mt-exclusivity-weekly/1.0", "Accept": "application/json"}
    if cookie:
        headers["Cookie"] = cookie.strip()
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        print(f"Fetch {url}: HTTP {exc.code}", file=sys.stderr)
        return None
    except Exception as exc:
        print(f"Fetch {url}: {exc}", file=sys.stderr)
        return None
    body = body.strip()
    if not body or body.startswith("<!") or body.startswith("<html"):
        print(f"Fetch {url}: not JSON (SSO HTML?)", file=sys.stderr)
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        print(f"Fetch {url}: invalid JSON", file=sys.stderr)
        return None


def _fetch_boltable_urls(cookie: str | None) -> dict[str, dict[str, Any]] | None:
    for url in _BBP_URLS:
        data = _fetch_url(url, cookie)
        if not isinstance(data, (dict, list)):
            continue
        tmp = os.path.join(os.path.dirname(_OUT), ".bbp_fetch_tmp.json")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        brands, _ = load_from_json(tmp)
        os.remove(tmp)
        if brands:
            return brands
    return None


def _fetch_gh_repo() -> dict[str, dict[str, Any]] | None:
    if not shutil.which("gh"):
        return None
    repo = "boltable/brands-by-platform"
    try:
        subprocess.run(
            ["gh", "repo", "view", repo],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError:
        return None
    tmp_dir = os.path.join(os.path.dirname(_OUT), ".bbp_gh_clone")
    shutil.rmtree(tmp_dir, ignore_errors=True)
    try:
        subprocess.run(
            ["gh", "repo", "clone", repo, tmp_dir, "--", "--depth", "1"],
            check=True,
            capture_output=True,
            text=True,
        )
        for rel in (
            "public/data.json",
            "public/brands.json",
            "data.json",
            "brands.json",
        ):
            path = os.path.join(tmp_dir, rel)
            if os.path.isfile(path):
                return _normalize_input(path)
    except subprocess.CalledProcessError as exc:
        print(f"gh clone {repo} failed: {exc}", file=sys.stderr)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync brands-by-platform GetPlace export")
    parser.add_argument("-o", "--output", default=_OUT)
    parser.add_argument("--input", help="Local JSON/CSV export to normalize")
    parser.add_argument(
        "--max-age-days",
        type=float,
        default=8.0,
        help="Skip fetch if output file is newer than this (unless --force)",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    env_input = os.environ.get("BOLTABLE_GETPLACE_JSON", "").strip()
    cookie = os.environ.get("BOLTABLE_COOKIE", "").strip() or None

    if not args.force and not args.input and not env_input:
        age = _file_age_days(args.output)
        if age is not None and age <= args.max_age_days:
            print(
                f"Keep existing export ({args.output}, {age:.1f}d old, max {args.max_age_days}d)"
            )
            return 0

    sources: list[tuple[str, dict[str, dict[str, Any]] | None]] = []

    if args.input:
        sources.append((args.input, _normalize_input(args.input)))
    if env_input and os.path.isfile(env_input):
        sources.append((env_input, _normalize_input(env_input)))
    sources.append((_SNAPSHOT, _load_snapshot(_SNAPSHOT)))
    sources.append(("brands-by-platform HTTPS", _fetch_boltable_urls(cookie)))
    sources.append(("gh:boltable/brands-by-platform", _fetch_gh_repo()))

    for label, brands in sources:
        if brands:
            _write_export(brands, label, args.output)
            return 0

    if os.path.isfile(args.output):
        age = _file_age_days(args.output)
        print(
            f"No new GetPlace source — keeping existing {args.output}"
            + (f" ({age:.1f}d old)" if age is not None else ""),
            file=sys.stderr,
        )
        return 0

    print(
        "No GetPlace export found. Options:\n"
        "  • Export from https://brands-by-platform.boltable.eu/ → "
        f"{args.output}\n"
        "  • Or: python3 scripts/fetch_brands_by_platform_export.py --input /path/to/export.json\n"
        "  • Weekly job will still refresh Databricks metrics; GetPlace columns stay empty until export exists.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
