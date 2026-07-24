#!/bin/sh
# GitHub Actions (and manual CI): live Databricks build + boltable deploy for exclusivity dashboard.
#
# Required env:
#   DATABRICKS_TOKEN
#   MT_PORTFOLIO_GH_TOKEN  (boltable push + team Save in dashboard)
#
# Optional:
#   ARTIFACT_DIR           (default: $REPO/artifacts)
#   EXCLUSIVITY_SKIP_GETPLACE=1
#
# Manual (from repo root, with secrets exported):
#   bash scripts/exclusivity_ci_refresh.sh

set -eu

REPO="$(cd "$(dirname "$0")/.." && pwd)"
ARTIFACT_DIR="${ARTIFACT_DIR:-$REPO/artifacts}"
OUT_HTML="$ARTIFACT_DIR/mt_exclusivity_targeting.html"
OUT_JSON="$ARTIFACT_DIR/mt_exclusivity_data.json"
GETPLACE_JSON="$ARTIFACT_DIR/mt_brands_by_platform.json"
BOLTABLE_DIR="$REPO/boltable/mt-exclusivity-targeting"

mkdir -p "$ARTIFACT_DIR"

if [ -z "${DATABRICKS_TOKEN:-}" ]; then
  echo "FAIL: set repository secret DATABRICKS_TOKEN" >&2
  exit 1
fi

if [ -z "${MT_PORTFOLIO_GH_TOKEN:-}" ]; then
  echo "FAIL: set repository secret MT_PORTFOLIO_GH_TOKEN (contents:write on boltable/mt-exclusivity-targeting)" >&2
  exit 1
fi

export GH_TOKEN="${GH_TOKEN:-$MT_PORTFOLIO_GH_TOKEN}"

PYTHON=""
for CAND in python3 python; do
  if command -v "$CAND" >/dev/null 2>&1; then
    PYTHON="$CAND"
    break
  fi
done
if [ -z "$PYTHON" ]; then
  echo "FAIL: python3 not found" >&2
  exit 1
fi

echo "=== exclusivity CI refresh ==="
echo "REPO=$REPO"
echo "ARTIFACT_DIR=$ARTIFACT_DIR"

if [ ! -d "$BOLTABLE_DIR/.git" ]; then
  echo "Cloning boltable/mt-exclusivity-targeting (state + GetPlace snapshot)…"
  rm -rf "$BOLTABLE_DIR"
  gh repo clone boltable/mt-exclusivity-targeting "$BOLTABLE_DIR" -- --depth 1
fi

if [ -z "${EXCLUSIVITY_SKIP_GETPLACE:-}" ]; then
  if "$PYTHON" "$REPO/scripts/fetch_brands_by_platform_export.py" --output "$GETPLACE_JSON"; then
    echo "OK: GetPlace sync"
  else
    echo "WARN: GetPlace sync skipped — Databricks columns still refresh"
  fi
else
  echo "SKIP GetPlace (EXCLUSIVITY_SKIP_GETPLACE set)"
fi

GETPLACE_ARG=""
if [ -f "$GETPLACE_JSON" ]; then
  GETPLACE_ARG="--getplace-path $GETPLACE_JSON"
fi

# shellcheck disable=SC2086
"$PYTHON" "$REPO/build_mt_exclusivity_targeting_dashboard.py" \
  --output "$OUT_HTML" \
  --data-json "$OUT_JSON" \
  $GETPLACE_ARG \
  --no-deploy

if [ ! -f "$OUT_HTML" ]; then
  echo "FAIL: build did not write $OUT_HTML" >&2
  exit 1
fi
echo "OK: built $OUT_HTML ($(wc -c <"$OUT_HTML" | tr -d ' ') bytes)"

export HTML_SRC="$OUT_HTML"
bash "$REPO/scripts/deploy_mt_exclusivity_targeting_boltable.sh"
echo "OK: https://mt-exclusivity-targeting.boltable.eu"
