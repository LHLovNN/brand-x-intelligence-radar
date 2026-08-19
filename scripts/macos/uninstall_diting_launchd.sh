#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$ROOT/scripts/macos/local_env.sh"

LABEL="$BRAND_RADAR_DITING_LAUNCHD_LABEL"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LAUNCHD_DOMAIN="gui/$(id -u)"

launchctl bootout "$LAUNCHD_DOMAIN/$LABEL" >/dev/null 2>&1 || true
launchctl unload "$PLIST" >/dev/null 2>&1 || true
rm -f "$PLIST"

printf 'Uninstalled %s Diting digest LaunchAgent.\n' "$BRAND_RADAR_DISPLAY_NAME"
