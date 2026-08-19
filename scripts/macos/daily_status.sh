#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$ROOT/scripts/macos/local_env.sh"

LABEL="$BRAND_RADAR_LAUNCHD_LABEL"
DITING_LABEL="$BRAND_RADAR_DITING_LAUNCHD_LABEL"
LEGACY_LABEL="$BRAND_RADAR_LEGACY_LAUNCHD_LABEL"
LOG_DIR="$ROOT/data/logs/macos"
LAUNCHD_DOMAIN="gui/$(id -u)"

cd "$ROOT"

printf '%s local automation status\n' "$BRAND_RADAR_DISPLAY_NAME"
printf 'Project: %s\n' "$ROOT"
printf 'LaunchAgent: %s\n' "$LABEL"

if launchctl print "$LAUNCHD_DOMAIN/$LABEL" >/dev/null 2>&1; then
  printf 'LaunchAgent loaded: yes\n'
else
  printf 'LaunchAgent loaded: no\n'
fi

if [[ "$LEGACY_LABEL" != "$LABEL" ]] && launchctl print "$LAUNCHD_DOMAIN/$LEGACY_LABEL" >/dev/null 2>&1; then
  printf 'Legacy LaunchAgent loaded: yes; run npm run local:daily:install to replace it.\n'
fi

printf 'Diting LaunchAgent: %s\n' "$DITING_LABEL"
if launchctl print "$LAUNCHD_DOMAIN/$DITING_LABEL" >/dev/null 2>&1; then
  printf 'Diting LaunchAgent loaded: yes\n'
else
  printf 'Diting LaunchAgent loaded: no\n'
fi

printf '\nGit status:\n'
git status --short

if [[ -f "$LOG_DIR/daily.out.log" ]]; then
  printf '\nLast stdout log lines:\n'
  tail -n 80 "$LOG_DIR/daily.out.log"
fi

if [[ -f "$LOG_DIR/daily.err.log" ]]; then
  printf '\nLast stderr log lines:\n'
  tail -n 80 "$LOG_DIR/daily.err.log"
fi

if [[ -f "$LOG_DIR/diting-digests.out.log" ]]; then
  printf '\nLast Diting stdout log lines:\n'
  tail -n 80 "$LOG_DIR/diting-digests.out.log"
fi

if [[ -f "$LOG_DIR/diting-digests.err.log" ]]; then
  printf '\nLast Diting stderr log lines:\n'
  tail -n 80 "$LOG_DIR/diting-digests.err.log"
fi
