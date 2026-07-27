#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$ROOT/scripts/macos/local_env.sh"

LABEL="$BRAND_RADAR_LAUNCHD_LABEL"
LEGACY_LABEL="$BRAND_RADAR_LEGACY_LAUNCHD_LABEL"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LEGACY_PLIST="$HOME/Library/LaunchAgents/$LEGACY_LABEL.plist"
LOG_DIR="$ROOT/data/logs/macos"
RUNNER="$ROOT/scripts/macos/run_local_daily.sh"
LAUNCHD_DOMAIN="gui/$(id -u)"

mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"

if [[ ! -x "$RUNNER" ]]; then
  chmod 700 "$RUNNER"
fi

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$RUNNER</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$ROOT</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>8</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/daily.out.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/daily.err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
</dict>
</plist>
PLIST

if [[ "$LEGACY_PLIST" != "$PLIST" ]]; then
  launchctl bootout "$LAUNCHD_DOMAIN/$LEGACY_LABEL" >/dev/null 2>&1 || true
  launchctl unload "$LEGACY_PLIST" >/dev/null 2>&1 || true
  rm -f "$LEGACY_PLIST"
fi

launchctl unsetenv TWITTERAPI_IO_KEY >/dev/null 2>&1 || true
launchctl unsetenv JDCLOUD_GPT_API_KEY >/dev/null 2>&1 || true

launchctl bootout "$LAUNCHD_DOMAIN/$LABEL" >/dev/null 2>&1 || true
launchctl unload "$PLIST" >/dev/null 2>&1 || true
if ! launchctl bootstrap "$LAUNCHD_DOMAIN" "$PLIST" >/dev/null 2>&1; then
  launchctl load -w "$PLIST" >/dev/null
fi
launchctl enable "$LAUNCHD_DOMAIN/$LABEL" >/dev/null 2>&1 || true

if ! launchctl print "$LAUNCHD_DOMAIN/$LABEL" >/dev/null 2>&1; then
  printf 'ERROR: %s was written but not loaded by macOS.\n' "$PLIST" >&2
  printf 'Run npm run local:daily:status for details, then reinstall from a normal user terminal.\n' >&2
  exit 1
fi

printf 'Installed %s.\n' "$PLIST"
printf '%s local daily run is scheduled for 08:00 local time.\n' "$BRAND_RADAR_DISPLAY_NAME"
printf 'Keep the Mac awake and network/VPN available at that time. Lock screen is fine; sleep is not.\n'
