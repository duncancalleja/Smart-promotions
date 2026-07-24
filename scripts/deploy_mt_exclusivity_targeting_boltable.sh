#!/usr/bin/env bash
# Deploy mt_exclusivity_targeting dashboard to boltable/mt-exclusivity-targeting
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO_DIR="$ROOT/boltable/mt-exclusivity-targeting"
HTML_SRC="${HTML_SRC:-$HOME/Documents/Bolt food/mt_exclusivity_targeting.html}"
GH="${GH:-gh}"

if ! command -v "$GH" >/dev/null 2>&1; then
  for candidate in \
    "$HOME/.local/bin/gh" \
    /tmp/gh/gh_2.65.0_macOS_arm64/bin/gh \
    /tmp/gh-extract/gh_2.65.0_macOS_arm64/bin/gh; do
    if [ -x "$candidate" ]; then
      GH="$candidate"
      break
    fi
  done
fi
if ! command -v "$GH" >/dev/null 2>&1; then
  echo "gh not found. Install: brew install gh  OR  see https://cli.github.com/" >&2
  exit 1
fi

if [ ! -f "$HTML_SRC" ]; then
  echo "Missing dashboard: $HTML_SRC" >&2
  echo "Run: python3 build_mt_exclusivity_targeting_dashboard.py" >&2
  exit 1
fi

ASSET_SRC="${ASSET_SRC:-$(dirname "$HTML_SRC")}"
PUBLIC="$REPO_DIR/public"

stage_public_assets() {
  mkdir -p "$PUBLIC"
  cp "$HTML_SRC" "$PUBLIC/index.html"
  for f in dashboard.css dashboard.js data.js; do
    if [ -f "$ASSET_SRC/$f" ]; then
      cp "$ASSET_SRC/$f" "$PUBLIC/$f"
    elif [ -f "$PUBLIC/$f" ]; then
      :
    else
      echo "Missing asset: $f (expected in $ASSET_SRC or $PUBLIC)" >&2
      exit 1
    fi
  done
  GETPLACE_SNAP="$PUBLIC/getplace-brands.json"
  if [ -f "$ROOT/boltable/mt-exclusivity-targeting/public/getplace-brands.json" ]; then
    cp "$ROOT/boltable/mt-exclusivity-targeting/public/getplace-brands.json" "$GETPLACE_SNAP"
  fi
}

ensure_template_scaffold() {
  local missing=0
  for f in AGENTS.md .gitignore nginx-include.conf project.toml; do
    if [ ! -f "$REPO_DIR/$f" ]; then
      missing=1
      break
    fi
  done
  if [ "$missing" = 0 ]; then
    return 0
  fi
  echo "Bootstrapping boltable folder from template-static…" >&2
  local tmp
  tmp="$(mktemp -d)"
  gh repo clone boltable/template-static "$tmp" -- --depth 1
  mkdir -p "$REPO_DIR"
  rsync -a --exclude .git "$tmp/" "$REPO_DIR/"
  rm -rf "$tmp"
}

mkdir -p "$PUBLIC"
ensure_template_scaffold

stage_public_assets
STATE_SRC="$PUBLIC/exclusivity-state.json"
if [ ! -f "$STATE_SRC" ]; then
  echo '{"version":0,"updatedAt":null,"decisions":{}}' > "$STATE_SRC"
fi

cat > "$PUBLIC/ping.html" <<'PING'
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Exclusivity targeting ping</title>
  <style>body{font:16px system-ui,sans-serif;margin:2rem;background:#0f1419;color:#e7ecf3}</style>
</head>
<body>
  <h1>Boltable is serving mt-exclusivity-targeting</h1>
  <p>Open <a href="/" style="color:#93c5fd">the dashboard</a>.</p>
  <p id="t"></p>
  <script>document.getElementById('t').textContent = 'Loaded at ' + new Date().toLocaleString();</script>
</body>
</html>
PING

INDEX_BYTES=$(wc -c < "$PUBLIC/index.html" | tr -d ' ')
DATA_JS="$PUBLIC/data.js"
if [ "$INDEX_BYTES" -lt 800 ]; then
  echo "Refusing to deploy: index.html is only ${INDEX_BYTES} bytes." >&2
  exit 1
fi
if [ ! -f "$DATA_JS" ] || [ "$(wc -c < "$DATA_JS" | tr -d ' ')" -lt 5000 ]; then
  echo "Refusing to deploy: missing or tiny public/data.js — run build first." >&2
  exit 1
fi

cd "$REPO_DIR"
if [ ! -d .git ]; then
  git init -b main
fi

gh auth setup-git 2>/dev/null || true

GETPLACE_SNAP="$PUBLIC/getplace-brands.json"
TMP_GETPLACE=""
TMP_ASSETS="$(mktemp -d)"
for f in dashboard.css dashboard.js data.js index.html; do
  [ -f "$PUBLIC/$f" ] && cp "$PUBLIC/$f" "$TMP_ASSETS/$f"
done
if [ -f "$GETPLACE_SNAP" ]; then
  TMP_GETPLACE="$(mktemp)"
  cp "$GETPLACE_SNAP" "$TMP_GETPLACE"
  cp "$GETPLACE_SNAP" "$TMP_ASSETS/getplace-brands.json"
fi

if git remote get-url origin >/dev/null 2>&1; then
  git fetch origin main 2>/dev/null || true
  if git rev-parse origin/main >/dev/null 2>&1; then
    git reset --hard origin/main
    cp "$TMP_ASSETS/index.html" "$PUBLIC/index.html"
    for f in dashboard.css dashboard.js data.js; do
      cp "$TMP_ASSETS/$f" "$PUBLIC/$f"
    done
    if [ -f "$TMP_ASSETS/getplace-brands.json" ]; then
      cp "$TMP_ASSETS/getplace-brands.json" "$GETPLACE_SNAP"
    fi
    if [ ! -f "$STATE_SRC" ]; then
      echo '{"version":0,"updatedAt":null,"decisions":{}}' > "$STATE_SRC"
    fi
    cat > "$PUBLIC/ping.html" <<'PING2'
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Exclusivity targeting ping</title>
  <style>body{font:16px system-ui,sans-serif;margin:2rem;background:#0f1419;color:#e7ecf3}</style>
</head>
<body>
  <h1>Boltable is serving mt-exclusivity-targeting</h1>
  <p>Open <a href="/" style="color:#93c5fd">the dashboard</a>.</p>
  <p id="t"></p>
  <script>document.getElementById('t').textContent = 'Loaded at ' + new Date().toLocaleString();</script>
</body>
</html>
PING2
  fi
fi

if [ -n "$TMP_GETPLACE" ] && [ -f "$TMP_GETPLACE" ]; then
  rm -f "$TMP_GETPLACE"
fi
rm -rf "$TMP_ASSETS"

git add public/index.html public/exclusivity-state.json public/ping.html public/dashboard.css public/dashboard.js public/data.js
if [ -f public/getplace-brands.json ]; then
  git add public/getplace-brands.json
fi
for f in project.toml AGENTS.md .gitignore nginx-include.conf README.md; do
  [ -e "$f" ] && git add "$f" 2>/dev/null || true
done

if git diff --cached --quiet; then
  echo "Dashboard unchanged — checking remote/push..."
  HAS_CHANGES=0
else
  git commit -m "Update exclusivity targeting dashboard"
  HAS_CHANGES=1
fi

if ! git remote get-url origin >/dev/null 2>&1; then
  if ! $GH repo view boltable/mt-exclusivity-targeting >/dev/null 2>&1; then
    $GH repo create boltable/mt-exclusivity-targeting --private --source=. --remote=origin --push
  else
    git remote add origin "https://github.com/boltable/mt-exclusivity-targeting.git" 2>/dev/null || true
    git push -u origin main
  fi
elif [ "$HAS_CHANGES" = 1 ]; then
  git push origin main
else
  echo "Already up to date on boltable."
fi

echo "Live in ~60s: https://mt-exclusivity-targeting.boltable.eu"
echo "Diagnostics: https://mt-exclusivity-targeting.boltable.eu/ping.html"
