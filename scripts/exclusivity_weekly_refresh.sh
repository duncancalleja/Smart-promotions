#!/bin/sh
# Weekly live rebuild of Malta exclusivity targeting dashboard + boltable deploy.
# 1) Sync GetPlace / brands-by-platform export (best effort)
# 2) Live Databricks build
# 3) Push to https://mt-exclusivity-targeting.boltable.eu/
#
# Manual:  bash scripts/exclusivity_weekly_refresh.sh
# Install: bash scripts/install_exclusivity_weekly_launchagent.sh

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SUPPORT="$HOME/Library/Application Support/mt-exclusivity-targeting"
LOG="$SUPPORT/weekly_refresh.log"
ERR="$SUPPORT/weekly_refresh.err.log"
DOC_DIR="$HOME/Documents/Bolt food"
OUT_HTML="$DOC_DIR/mt_exclusivity_targeting.html"

mkdir -p "$SUPPORT" "$DOC_DIR"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

PYTHON=""
for CAND in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
  if [ -x "$CAND" ] && "$CAND" -c "import databricks.sql" 2>/dev/null; then
    PYTHON="$CAND"
    break
  fi
done

{
  echo "=== $(date) exclusivity weekly refresh ==="
  echo "REPO=$REPO"

  if [ -z "$PYTHON" ]; then
    echo "FAIL: no Python with databricks-sql-connector"
    exit 1
  fi

  if [ -z "${EXCLUSIVITY_SKIP_GETPLACE:-}" ]; then
    if "$PYTHON" "$REPO/scripts/fetch_brands_by_platform_export.py"; then
      echo "OK: GetPlace sync"
    else
      echo "WARN: GetPlace sync — using existing export or snapshot if any"
    fi
  else
    echo "SKIP GetPlace (EXCLUSIVITY_SKIP_GETPLACE set)"
  fi

  if ! "$PYTHON" "$REPO/build_mt_exclusivity_targeting_dashboard.py"; then
    echo "FAIL: build_mt_exclusivity_targeting_dashboard.py"
    exit 1
  fi
  echo "OK: built $OUT_HTML"

  if [ -n "${EXCLUSIVITY_SKIP_DEPLOY:-}" ]; then
    echo "SKIP deploy (EXCLUSIVITY_SKIP_DEPLOY set)"
    exit 0
  fi

  if bash "$REPO/scripts/deploy_mt_exclusivity_targeting_boltable.sh"; then
    echo "OK: deployed to boltable"
  else
    echo "FAIL: boltable deploy"
    exit 1
  fi

  echo ""
} >>"$LOG" 2>>"$ERR"
