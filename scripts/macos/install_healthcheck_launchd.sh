#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$ROOT/scripts/macos/local_env.sh"

LABEL="$BRAND_RADAR_HEALTH_LAUNCHD_LABEL"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$ROOT/data/logs/macos"
RUNNER="$ROOT/scripts/macos/run_daily_healthcheck.sh"
LAUNCHD_DOMAIN="gui/$(id -u)"

mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"
chmod 700 "$RUNNER"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$RUNNER</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$ROOT</string>
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Hour</key><integer>10</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>14</integer><key>Minute</key><integer>0</integer></dict>
  </array>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/healthcheck.out.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/healthcheck.err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
</dict>
</plist>
PLIST

launchctl bootout "$LAUNCHD_DOMAIN/$LABEL" >/dev/null 2>&1 || true
launchctl unload "$PLIST" >/dev/null 2>&1 || true
if ! launchctl bootstrap "$LAUNCHD_DOMAIN" "$PLIST" >/dev/null 2>&1; then
  launchctl load -w "$PLIST" >/dev/null
fi
launchctl enable "$LAUNCHD_DOMAIN/$LABEL" >/dev/null 2>&1 || true
launchctl print "$LAUNCHD_DOMAIN/$LABEL" >/dev/null 2>&1 || {
  printf 'ERROR: %s was written but not loaded by macOS.\n' "$PLIST" >&2
  exit 1
}

printf 'Installed %s.\n' "$PLIST"
printf '%s freshness repair checks are scheduled for 10:00 and 14:00 local time.\n' "$BRAND_RADAR_DISPLAY_NAME"
