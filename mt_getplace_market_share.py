"""Load GetPlace / brands-by-platform market share for exclusivity dashboard joins."""

from __future__ import annotations

import json
import os
import re
import datetime as dt
from typing import Any

import pandas as pd

_DEFAULT_PATHS = (
    os.path.expanduser("~/Documents/Bolt food/mt_brands_by_platform.json"),
    os.path.expanduser("~/Documents/Bolt food/brands_by_platform.json"),
    os.path.expanduser("~/Documents/Bolt food/mt_getplace_market_share.json"),
    os.path.expanduser("~/Documents/Bolt food/MT _ Market Share - Merger (1).csv"),
    os.path.expanduser("~/Documents/Bolt food/mt_getplace_market_share.csv"),
)
_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
_BOLTABLE_SNAPSHOT = os.path.join(
    _REPO_ROOT, "boltable", "mt-exclusivity-targeting", "public", "getplace-brands.json"
)


def brand_key(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip()).upper()


def _pick(d: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    lower = {str(k).lower(): v for k, v in d.items()}
    for k in keys:
        v = lower.get(k.lower())
        if v is not None:
            return v
    return None


def _as_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        s = str(v).strip().replace("%", "").replace(",", "")
        if not s:
            return None
        return float(s)
    except (TypeError, ValueError):
        return None


def _as_int(v: Any) -> int:
    f = _as_float(v)
    return int(f) if f is not None else 0


def _find_col(columns: list[str], *needles: str) -> str | None:
    for col in columns:
        cl = col.lower()
        if all(n.lower() in cl for n in needles):
            return col
    for col in columns:
        cl = col.lower()
        if any(n.lower() in cl for n in needles):
            return col
    return None


def _rollup_bucket(
    buckets: dict[str, dict[str, Any]], key: str, row: dict[str, Any]
) -> None:
    if key not in buckets:
        buckets[key] = {
            "brand_key": key,
            "brand_name": row.get("brand_name") or key,
            "bolt_orders": 0,
            "wolt_orders": 0,
            "providers": 0,
            "trends": [],
            "ms_changes": [],
        }
    b = buckets[key]
    b["bolt_orders"] += int(row.get("bolt_orders") or 0)
    b["wolt_orders"] += int(row.get("wolt_orders") or 0)
    b["providers"] += 1
    if row.get("trend"):
        b["trends"].append(str(row["trend"]))
    if row.get("ms_change_pp") is not None:
        b["ms_changes"].append(float(row["ms_change_pp"]))


def _finalize_bucket(b: dict[str, Any]) -> dict[str, Any]:
    total = int(b["bolt_orders"]) + int(b["wolt_orders"])
    bolt_ms = round(b["bolt_orders"] / total * 100, 1) if total > 0 else None
    wolt_ms = round(100 - bolt_ms, 1) if bolt_ms is not None else None
    trend = None
    trends = [t for t in b.get("trends") or [] if t]
    if trends:
        from collections import Counter

        trend = Counter(trends).most_common(1)[0][0]
    ms_change = None
    if b.get("ms_changes"):
        ms_change = round(sum(b["ms_changes"]) / len(b["ms_changes"]), 1)
    return {
        "brand_key": b["brand_key"],
        "brand_name": b.get("brand_name") or b["brand_key"],
        "bolt_ms_pct": bolt_ms,
        "wolt_ms_pct": wolt_ms,
        "bolt_orders": int(b["bolt_orders"]),
        "wolt_orders": int(b["wolt_orders"]),
        "total_orders": total,
        "providers": int(b["providers"]),
        "trend": trend,
        "ms_change_pp": ms_change,
    }


def _parse_json_records(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if not isinstance(data, dict):
        return []
    for key in ("brands", "rows", "providers", "data"):
        if isinstance(data.get(key), list):
            return [x for x in data[key] if isinstance(x, dict)]
    return []


def load_from_json(path: str) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    buckets: dict[str, dict[str, Any]] = {}
    for raw in _parse_json_records(data):
        name = _pick(
            raw,
            "brand_name",
            "brand",
            "Brand Name",
            "brand_key",
            "Brand",
        )
        if not name:
            continue
        key = brand_key(str(_pick(raw, "brand_key", "brand_key_normalized") or name))
        bolt_orders = _as_int(
            _pick(raw, "bolt_orders", "bolt_food_orders", "bolt_order_count", "orders_bolt")
        )
        wolt_orders = _as_int(
            _pick(raw, "wolt_orders", "wolt_order_count", "orders_wolt")
        )
        bolt_ms = _as_float(
            _pick(
                raw,
                "bolt_ms_pct",
                "bolt_market_share_pct",
                "bolt_ms",
                "market_share_bolt",
                "Bolt Food market share %",
                "bolt_food_market_share_pct",
            )
        )
        wolt_ms = _as_float(
            _pick(raw, "wolt_ms_pct", "wolt_market_share_pct", "wolt_ms", "market_share_wolt")
        )
        if bolt_ms is None and bolt_orders + wolt_orders > 0:
            bolt_ms = round(bolt_orders / (bolt_orders + wolt_orders) * 100, 1)
        if wolt_ms is None and bolt_ms is not None:
            wolt_ms = round(100 - bolt_ms, 1)
        trend_raw = _pick(raw, "trend", "Trend", "ms_trend", "gaining_ms")
        trend = None
        if trend_raw is not None:
            ts = str(trend_raw).strip().lower()
            if ts in ("1", "true", "yes", "gaining"):
                trend = "Gaining"
            elif ts in ("0", "false", "no", "losing"):
                trend = "Losing"
            elif ts:
                trend = str(trend_raw).strip()
        ms_change = _as_float(
            _pick(raw, "ms_change_pp", "ms_change", "market_share_change_pp", "change_pp")
        )
        if bolt_orders or wolt_orders or bolt_ms is not None:
            _rollup_bucket(
                buckets,
                key,
                {
                    "brand_name": name,
                    "bolt_orders": bolt_orders,
                    "wolt_orders": wolt_orders,
                    "trend": trend,
                    "ms_change_pp": ms_change,
                },
            )
        elif bolt_ms is not None:
            buckets[key] = {
                "brand_key": key,
                "brand_name": str(name),
                "bolt_orders": 0,
                "wolt_orders": 0,
                "providers": 1,
                "trends": [trend] if trend else [],
                "ms_changes": [ms_change] if ms_change is not None else [],
                "_bolt_ms": bolt_ms,
                "_wolt_ms": wolt_ms,
            }
    out: dict[str, dict[str, Any]] = {}
    for key, b in buckets.items():
        if "_bolt_ms" in b:
            out[key] = {
                "brand_key": key,
                "brand_name": b["brand_name"],
                "bolt_ms_pct": b["_bolt_ms"],
                "wolt_ms_pct": b.get("_wolt_ms"),
                "bolt_orders": 0,
                "wolt_orders": 0,
                "total_orders": 0,
                "providers": 1,
                "trend": (b.get("trends") or [None])[0],
                "ms_change_pp": (b.get("ms_changes") or [None])[0],
            }
        else:
            out[key] = _finalize_bucket(b)
    meta = {
        "source": path,
        "format": "json",
        "brand_count": len(out),
        "brands_by_platform_url": "https://brands-by-platform.boltable.eu/",
    }
    return out, meta


def load_from_csv(path: str) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    df = pd.read_csv(path, dtype=str, low_memory=False)
    cols = [str(c) for c in df.columns]
    brand_col = _find_col(cols, "brand") or _find_col(cols, "brand name")
    provider_col = _find_col(cols, "provider id") or _find_col(cols, "provider_id")
    trend_col = _find_col(cols, "trend") or _find_col(cols, "gaining")
    ms_col = _find_col(cols, "market share") or _find_col(cols, "bolt food market share")

    bolt_order_cols = [c for c in cols if "bolt" in c.lower() and "order" in c.lower()]
    wolt_order_cols = [c for c in cols if "wolt" in c.lower() and "order" in c.lower()]

    buckets: dict[str, dict[str, Any]] = {}
    for _, row in df.iterrows():
        name = str(row.get(brand_col) or "").strip() if brand_col else ""
        if not name:
            pname = _find_col(cols, "provider name")
            name = str(row.get(pname) or "").strip() if pname else ""
        if not name:
            continue
        key = brand_key(name)
        bolt_orders = sum(_as_int(row.get(c)) for c in bolt_order_cols)
        wolt_orders = sum(_as_int(row.get(c)) for c in wolt_order_cols)
        bolt_ms = _as_float(row.get(ms_col)) if ms_col else None
        trend = str(row.get(trend_col)).strip() if trend_col and pd.notna(row.get(trend_col)) else None
        if trend and trend.lower() in ("true", "1", "yes"):
            trend = "Gaining"
        elif trend and trend.lower() in ("false", "0", "no"):
            trend = "Losing"
        _rollup_bucket(
            buckets,
            key,
            {
                "brand_name": name,
                "bolt_orders": bolt_orders,
                "wolt_orders": wolt_orders,
                "trend": trend,
                "ms_change_pp": None,
            },
        )
        if bolt_ms is not None and key in buckets:
            buckets[key].setdefault("_ms_samples", []).append(bolt_ms)

    out: dict[str, dict[str, Any]] = {}
    for key, b in buckets.items():
        rec = _finalize_bucket(b)
        samples = b.get("_ms_samples") or []
        if samples and rec["bolt_ms_pct"] is None:
            rec["bolt_ms_pct"] = round(sum(samples) / len(samples), 1)
            rec["wolt_ms_pct"] = round(100 - rec["bolt_ms_pct"], 1)
        out[key] = rec

    meta = {
        "source": path,
        "format": "csv",
        "brand_count": len(out),
        "provider_rows": len(df),
        "brands_by_platform_url": "https://brands-by-platform.boltable.eu/",
    }
    return out, meta


def load_getplace_market_share(
    extra_path: str | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any] | None]:
    """Return brand_key -> GetPlace metrics and load metadata (or None if missing)."""
    paths = ([extra_path] if extra_path else []) + [_BOLTABLE_SNAPSHOT] + list(_DEFAULT_PATHS)
    seen: set[str] = set()
    for path in paths:
        if not path or path in seen or not os.path.isfile(path):
            continue
        seen.add(path)
        try:
            if path.lower().endswith(".json"):
                brands, meta = load_from_json(path)
                if os.path.isfile(path):
                    try:
                        with open(path, encoding="utf-8") as f:
                            wrapper = json.load(f)
                        if isinstance(wrapper, dict) and wrapper.get("updated_at"):
                            meta["updated_at"] = wrapper["updated_at"]
                    except Exception:
                        pass
                return brands, meta
            if path.lower().endswith(".csv"):
                return load_from_csv(path)
        except Exception as exc:
            print(f"GetPlace load failed for {path}: {exc}", file=__import__("sys").stderr)
    return {}, None


def merge_getplace_into_brands(
    brands: list[dict[str, Any]], getplace: dict[str, dict[str, Any]]
) -> int:
    """Attach GetPlace fields to dashboard brands; return match count."""
    matched = 0
    for b in brands:
        key = brand_key(str(b.get("brand_key") or b.get("brand_name") or ""))
        gp = getplace.get(key)
        if not gp:
            gp = getplace.get(brand_key(str(b.get("brand_name") or "")))
        b["getplace_bolt_ms_pct"] = gp.get("bolt_ms_pct") if gp else None
        b["getplace_wolt_ms_pct"] = gp.get("wolt_ms_pct") if gp else None
        b["getplace_total_orders"] = gp.get("total_orders") if gp else None
        b["getplace_ms_trend"] = gp.get("trend") if gp else None
        b["getplace_ms_change_pp"] = gp.get("ms_change_pp") if gp else None
        if gp:
            matched += 1
    return matched


def save_getplace_snapshot(
    brands: list[dict[str, Any]], meta: dict[str, Any] | None, path: str | None = None
) -> str | None:
    """Persist merged GetPlace fields for next week's fallback sync."""
    rows = []
    for b in brands:
        if b.get("getplace_bolt_ms_pct") is None and b.get("getplace_wolt_ms_pct") is None:
            continue
        rows.append(
            {
                "brand_key": brand_key(str(b.get("brand_key") or b.get("brand_name") or "")),
                "brand_name": b.get("brand_name"),
                "bolt_ms_pct": b.get("getplace_bolt_ms_pct"),
                "wolt_ms_pct": b.get("getplace_wolt_ms_pct"),
                "total_orders": b.get("getplace_total_orders"),
                "trend": b.get("getplace_ms_trend"),
                "ms_change_pp": b.get("getplace_ms_change_pp"),
            }
        )
    if not rows:
        return None
    out_path = path or _BOLTABLE_SNAPSHOT
    payload = {
        "updated_at": (meta or {}).get("updated_at")
        or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "source": (meta or {}).get("source") or "mt-exclusivity build snapshot",
        "brand_count": len(rows),
        "brands": rows,
    }
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return out_path
