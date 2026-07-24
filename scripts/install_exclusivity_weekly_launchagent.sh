#!/bin/bash
# Install LaunchAgent: rebuild + deploy exclusivity dashboard every Monday 08:30 local.
# Run once:  bash scripts/install_exclusivity_weekly_launchagent.sh
# Unload:    launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.bolt.mt-exclusivity.weekly.plist

set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$REPO/scripts/exclusivity_weekly_refresh.sh"
PLIST="$HOME/Library/LaunchAgents/com.bolt.mt-exclusivity.weekly.plist"
LABEL="com.bolt.mt-exclusivity.weekly"
SUPPORT="$HOME/Library/Application Support/mt-exclusivity-targeting"

chmod +x "$SCRIPT" "$REPO/scripts/fetch_brands_by_platform_export.py"
mkdir -p "$SUPPORT" "$HOME/Library/LaunchAgents"

cat >"$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/sh</string>
    <string>${SCRIPT}</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Weekday</key>
    <integer>1</integer>
    <key>Hour</key>
    <integer>8</integer>
    <key>Minute</key>
    <integer>30</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>${SUPPORT}/launchd.out.log</string>
  <key>StandardErrorPath</key>
  <string>${SUPPORT}/launchd.err.log</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
launchctl unload "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null || launchctl load "$PLIST"

echo "Installed $PLIST"
echo "Runs every Monday at 08:30 local time."
echo "Requires: Mac awake, NetBird VPN, ~/.databricks_token"
echo "Logs: $SUPPORT/weekly_refresh.log (and weekly_refresh.err.log)"
echo "Manual run: bash $SCRIPT"
echo "Build only (no deploy): EXCLUSIVITY_SKIP_DEPLOY=1 bash $SCRIPT"
