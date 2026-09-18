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
INITIAL_PASS_PATH="$STATE_DIR/initial-fresh-$EXPECTED_DATE.ok"
DITING_UPSTREAM_REPORT_PATH="$STATE_DIR/diting-upstream-$EXPECTED_DATE.json"
DITING_UPSTREAM_BLOCK_PATH="$STATE_DIR/diting-upstream-manual-$EXPECTED_DATE.json"
MAX_REPAIR_ATTEMPTS="${BRAND_RADAR_HEALTH_MAX_REPAIR_ATTEMPTS:-2}"
RUN_HOUR_RAW="${BRAND_RADAR_HEALTH_RUN_HOUR:-$(TZ=Asia/Shanghai date '+%H')}"
FORCE_CHECK="${BRAND_RADAR_HEALTH_FORCE_CHECK:-0}"
OVERRIDE_DITING_UPSTREAM_BLOCK="${BRAND_RADAR_HEALTH_OVERRIDE_DITING_UPSTREAM_BLOCK:-0}"
DITING_SOURCE_BASE_URL="${BRAND_RADAR_DITING_SOURCE_BASE_URL:-https://codew1028.github.io/dt}"
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
if [[ ! "$RUN_HOUR_RAW" =~ ^[0-9]{1,2}$ ]] || (( 10#$RUN_HOUR_RAW > 23 )); then
  printf 'Invalid health-check run hour: %s\n' "$RUN_HOUR_RAW" >&2
  exit 2
fi
if [[ "$FORCE_CHECK" != "0" && "$FORCE_CHECK" != "1" ]]; then
  printf 'Invalid force-check flag: %s\n' "$FORCE_CHECK" >&2
  exit 2
fi
if [[ "$OVERRIDE_DITING_UPSTREAM_BLOCK" != "0" && "$OVERRIDE_DITING_UPSTREAM_BLOCK" != "1" ]]; then
  printf 'Invalid Diting upstream-block override flag: %s\n' "$OVERRIDE_DITING_UPSTREAM_BLOCK" >&2
  exit 2
fi

RUN_HOUR=$((10#$RUN_HOUR_RAW))

mkdir -p "$STATE_DIR"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "$*"
}

record_initial_freshness() {
  local temporary="$INITIAL_PASS_PATH.tmp.$$"
  printf '%s\n' "$EXPECTED_DATE" > "$temporary"
  mv "$temporary" "$INITIAL_PASS_PATH"
}

if (( RUN_HOUR >= 11 )) && [[ "$FORCE_CHECK" == "0" && -f "$INITIAL_PASS_PATH" ]]; then
  log "Skipping the secondary freshness check: the initial check passed with all four modules current."
  exit 0
fi

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

upstream_component_is_fresh() {
  local component="$1"
  "$PYTHON_BIN" - "$DITING_UPSTREAM_REPORT_PATH" "$component" <<'PY'
import json
import sys
from pathlib import Path

report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
raise SystemExit(0 if report["components"][sys.argv[2]]["fresh"] else 1)
PY
}

upstream_component_observed() {
  local component="$1"
  "$PYTHON_BIN" - "$DITING_UPSTREAM_REPORT_PATH" "$component" <<'PY'
import json
import sys
from pathlib import Path

report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
item = report["components"][sys.argv[2]]
print(item.get("observed") or item.get("error") or "unknown")
PY
}

check_diting_upstream() {
  set +e
  "$PYTHON_BIN" "$ROOT/scripts/check_diting_upstream.py" \
    --base-url "$DITING_SOURCE_BASE_URL" \
    --expected-date "$EXPECTED_DATE" \
    --output "$DITING_UPSTREAM_REPORT_PATH"
  local result=$?
  set -e
  return "$result"
}

diting_component_is_blocked() {
  local component="$1"
  [[ "$OVERRIDE_DITING_UPSTREAM_BLOCK" == "0" && -f "$DITING_UPSTREAM_BLOCK_PATH" ]] || return 1
  "$PYTHON_BIN" - "$DITING_UPSTREAM_BLOCK_PATH" "$component" <<'PY'
import json
import sys
from pathlib import Path

report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
raise SystemExit(0 if sys.argv[2] in (report.get("blocked_components") or {}) else 1)
PY
}

record_diting_upstream_block() {
  local component="$1"
  "$PYTHON_BIN" - "$DITING_UPSTREAM_REPORT_PATH" "$DITING_UPSTREAM_BLOCK_PATH" "$component" <<'PY'
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

report_path = Path(sys.argv[1])
block_path = Path(sys.argv[2])
component = sys.argv[3]
report = json.loads(report_path.read_text(encoding="utf-8"))
existing = json.loads(block_path.read_text(encoding="utf-8")) if block_path.exists() else {}
blocked = existing.get("blocked_components") or {}
now = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
upstream = report["components"][component]
previous = blocked.get(component) or {}
blocked[component] = {
    "reason": "upstream_unreachable" if not report.get("reachable") else "upstream_missing",
    "expected": upstream.get("expected") or report.get("expected_date") or "",
    "observed": upstream.get("observed") or "",
    "error": upstream.get("error") or "",
    "first_detected_at": previous.get("first_detected_at") or now,
    "last_detected_at": now,
}
payload = {
    "expected_date": report.get("expected_date") or "",
    "updated_at": now,
    "blocked_components": blocked,
}
temporary = block_path.with_suffix(block_path.suffix + ".tmp")
temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
temporary.replace(block_path)
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
  local upstream_exit=0
  local repair_ai=0
  local repair_tg=0
  local blocked=0
  local check_ai=0
  local check_tg=0
  local kinds=""
  local observed=""

  if component_is_stale ai; then
    if diting_component_is_blocked ai; then
      log "AI日报 remains paused because its upstream issue requires manual investigation."
    else
      check_ai=1
    fi
  fi
  if component_is_stale tg; then
    if diting_component_is_blocked tg; then
      log "TG日报 remains paused because its upstream issue requires manual investigation."
    else
      check_tg=1
    fi
  fi
  if [[ "$check_ai" == "0" && "$check_tg" == "0" ]]; then
    return 1
  fi
  if lock_is_active "$DITING_LOCK_DIR"; then
    log "AI/TG job is still running; deferring repair without consuming an attempt."
    return 1
  fi

  check_diting_upstream || upstream_exit=$?
  if [[ "$upstream_exit" == "2" ]]; then
    if [[ "$check_ai" == "1" ]]; then record_diting_upstream_block ai; fi
    if [[ "$check_tg" == "1" ]]; then record_diting_upstream_block tg; fi
    log "The AI/TG upstream source could not be checked reliably; skipping sync and recording manual intervention."
    return 1
  fi

  if [[ "$check_ai" == "1" ]]; then
    if upstream_component_is_fresh ai; then
      repair_ai=1
    else
      observed="$(upstream_component_observed ai)"
      log "AI日报 is also missing upstream (expected $EXPECTED_DATE, observed $observed); skipping ineffective sync."
      record_diting_upstream_block ai
      blocked=1
    fi
  fi
  if [[ "$check_tg" == "1" ]]; then
    if upstream_component_is_fresh tg; then
      repair_tg=1
    else
      observed="$(upstream_component_observed tg)"
      log "TG日报 is also missing upstream (expected $EXPECTED_DATE, observed $observed); skipping ineffective sync."
      record_diting_upstream_block tg
      blocked=1
    fi
  fi
  if [[ "$blocked" == "1" ]]; then
    log "Recorded the upstream AI/TG cause at $DITING_UPSTREAM_BLOCK_PATH; automatic retries are paused for manual investigation."
  fi
  if [[ "$repair_ai" == "0" && "$repair_tg" == "0" ]]; then
    return 1
  fi

  attempts="$(repair_attempts diting)"
  if (( attempts >= MAX_REPAIR_ATTEMPTS )); then
    log "AI/TG repair limit reached for $EXPECTED_DATE; manual investigation required."
    return 1
  fi
  record_repair_attempt diting
  if [[ "$repair_ai" == "1" ]]; then kinds="ai"; fi
  if [[ "$repair_tg" == "1" ]]; then
    if [[ -n "$kinds" ]]; then kinds="$kinds,tg"; else kinds="tg"; fi
  fi
  log "Repairing local Diting modules from available upstream data: $kinds."
  BRAND_RADAR_DITING_KINDS="$kinds" \
    BRAND_RADAR_DITING_DATE="$EXPECTED_DATE" \
    "$ROOT/scripts/macos/run_diting_digest_sync.sh"
}

log "Checking public dashboard freshness for $EXPECTED_DATE."
if check_freshness; then
  if (( RUN_HOUR < 11 )); then
    record_initial_freshness
    log "Initial freshness check passed; today's secondary check will skip external verification."
  fi
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
