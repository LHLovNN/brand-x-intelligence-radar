#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$ROOT/scripts/macos/local_env.sh"

LOG_DIR="$ROOT/data/logs/macos"
STATE_DIR="${BRAND_RADAR_HEALTH_STATE_DIR:-$LOG_DIR/health}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
EXPECTED_DATE="${BRAND_RADAR_HEALTH_EXPECTED_DATE:-$(TZ=Asia/Shanghai date '+%Y-%m-%d')}"
BASE_URL="${BRAND_RADAR_PUBLIC_BASE_URL:-https://lhlovnn.github.io/brand-x-intelligence-radar}"
REPORT_PATH="$STATE_DIR/public-freshness-$EXPECTED_DATE.json"
ATTEMPT_PATH="$STATE_DIR/repair-attempts-$EXPECTED_DATE.json"
MAX_REPAIR_ATTEMPTS="${BRAND_RADAR_HEALTH_MAX_REPAIR_ATTEMPTS:-2}"
DAILY_LOCK_DIR="${TMPDIR:-/tmp}/brand-radar-daily.lock"
DITING_LOCK_DIR="${TMPDIR:-/tmp}/brand-radar-diting-digests.lock"

if [[ ! "$EXPECTED_DATE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  printf 'Invalid health-check date: %s\n' "$EXPECTED_DATE" >&2
  exit 2
fi
if [[ ! "$MAX_REPAIR_ATTEMPTS" =~ ^[0-9]+$ ]]; then
  printf 'Invalid repair-attempt limit: %s\n' "$MAX_REPAIR_ATTEMPTS" >&2
  exit 2
fi

mkdir -p "$STATE_DIR"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "$*"
}

check_freshness() {
  set +e
  "$PYTHON_BIN" "$ROOT/scripts/check_public_freshness.py" \
    --base-url "$BASE_URL" \
    --expected-date "$EXPECTED_DATE" \
    --output "$REPORT_PATH"
  local result=$?
  set -e
  return "$result"
}

component_is_stale() {
  local component="$1"
  "$PYTHON_BIN" - "$REPORT_PATH" "$component" <<'PY'
import json
import sys
from pathlib import Path

report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
raise SystemExit(0 if not report["components"][sys.argv[2]]["fresh"] else 1)
PY
}

repair_attempts() {
  local component="$1"
  "$PYTHON_BIN" - "$ATTEMPT_PATH" "$component" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
print(int(data.get(sys.argv[2], 0)))
PY
}

record_repair_attempt() {
  local component="$1"
  "$PYTHON_BIN" - "$ATTEMPT_PATH" "$component" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
data[sys.argv[2]] = int(data.get(sys.argv[2], 0)) + 1
temporary = path.with_suffix(path.suffix + ".tmp")
temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
temporary.replace(path)
PY
}

lock_is_active() {
  local lock_dir="$1"
  local owner_pid=""
  [[ -f "$lock_dir/pid" ]] || return 1
  owner_pid="$(cat "$lock_dir/pid" 2>/dev/null || true)"
  [[ "$owner_pid" =~ ^[0-9]+$ ]] && kill -0 "$owner_pid" 2>/dev/null
}

repair_daily_modules() {
  local attempts
  if lock_is_active "$DAILY_LOCK_DIR"; then
    log "Daily job is still running; deferring repair without consuming an attempt."
    return 1
  fi
  attempts="$(repair_attempts daily)"
  if (( attempts >= MAX_REPAIR_ATTEMPTS )); then
    log "Daily module repair limit reached for $EXPECTED_DATE; manual investigation required."
    return 1
  fi
  record_repair_attempt daily
  if [[ -f "$ROOT/data/checkpoints/daily/$EXPECTED_DATE.json" ]]; then
    log "Repairing daily modules from the exact-date checkpoint without repeating primary collection."
    if component_is_stale xiaohongshu; then
      log "Xiaohongshu is stale; the repair will refresh platform trends and may use up to its configured source-request limit."
      if component_is_stale brand; then
        BRAND_RADAR_RESUME_FROM_CHECKPOINT=1 \
          BRAND_RADAR_CHECKPOINT_DATE="$EXPECTED_DATE" \
          BRAND_RADAR_REFRESH_PLATFORM_TRENDS=1 \
          "$ROOT/scripts/macos/run_local_daily.sh"
      else
        BRAND_RADAR_RESUME_FROM_CHECKPOINT=1 \
          BRAND_RADAR_CHECKPOINT_DATE="$EXPECTED_DATE" \
          BRAND_RADAR_REFRESH_PLATFORM_TRENDS=1 \
          BRAND_RADAR_PLATFORM_TRENDS_ONLY=1 \
          "$ROOT/scripts/macos/run_local_daily.sh"
      fi
    else
      BRAND_RADAR_RESUME_FROM_CHECKPOINT=1 \
        BRAND_RADAR_CHECKPOINT_DATE="$EXPECTED_DATE" \
        "$ROOT/scripts/macos/run_local_daily.sh"
    fi
  else
    log "No checkpoint exists for $EXPECTED_DATE; starting one bounded full daily run. This consumes the configured primary source quota."
    if component_is_stale xiaohongshu; then
      BRAND_RADAR_REPORT_DATE="$EXPECTED_DATE" "$ROOT/scripts/macos/run_local_daily.sh"
    else
      log "Xiaohongshu is already current; skipping its collection during brand repair."
      BRAND_RADAR_REPORT_DATE="$EXPECTED_DATE" \
        BRAND_RADAR_PLATFORM_TRENDS=0 \
        "$ROOT/scripts/macos/run_local_daily.sh"
    fi
  fi
}

repair_diting_modules() {
  local attempts
  if lock_is_active "$DITING_LOCK_DIR"; then
    log "AI/TG job is still running; deferring repair without consuming an attempt."
    return 1
  fi
  attempts="$(repair_attempts diting)"
  if (( attempts >= MAX_REPAIR_ATTEMPTS )); then
    log "AI/TG repair limit reached for $EXPECTED_DATE; manual investigation required."
    return 1
  fi
  record_repair_attempt diting
  log "Repairing AI/TG digests; this does not use the X source quota."
  "$ROOT/scripts/macos/run_diting_digest_sync.sh"
}

log "Checking public dashboard freshness for $EXPECTED_DATE."
if check_freshness; then
  log "All four public modules are current."
  exit 0
else
  freshness_exit=$?
fi
if [[ "$freshness_exit" == "2" ]]; then
  log "Public dashboard could not be reached reliably; skipping repair to avoid duplicate collection."
  exit 1
fi

daily_stale=0
diting_stale=0
if component_is_stale brand || component_is_stale xiaohongshu; then daily_stale=1; fi
if component_is_stale ai || component_is_stale tg; then diting_stale=1; fi

repair_failed=0
if [[ "$daily_stale" == "1" ]]; then repair_daily_modules || repair_failed=1; fi
if [[ "$diting_stale" == "1" ]]; then repair_diting_modules || repair_failed=1; fi
if [[ "$repair_failed" == "1" ]]; then exit 1; fi

if check_freshness; then
  log "Freshness repair succeeded for all four modules."
  exit 0
fi
log "Repair completed, but at least one public module is still stale."
exit 1
