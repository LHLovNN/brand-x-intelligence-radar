#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$ROOT/scripts/macos/local_env.sh"

LOCK_DIR="${TMPDIR:-/tmp}/brand-radar-daily-preview.lock"
PYTHON_BIN="${PYTHON_BIN:-python3}"
RESUME_FROM_CHECKPOINT="${BRAND_RADAR_RESUME_FROM_CHECKPOINT:-0}"
ATTACH_CONTEXT_FROM_PROVIDER="${BRAND_RADAR_ATTACH_CONTEXT_FROM_PROVIDER:-0}"
REPORT_DATE="${BRAND_RADAR_REPORT_DATE:-}"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "$*"
}

fail() {
  log "ERROR: $*"
  exit 1
}

cleanup() {
  rmdir "$LOCK_DIR" 2>/dev/null || true
}

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  fail "Another ${BRAND_RADAR_DISPLAY_NAME} daily preview run is already active."
fi
trap cleanup EXIT

require_local_secret() {
  local name="$1"
  local label="$2"
  local value

  value="$(brand_radar_keychain_value "$name" || true)"
  if [[ -z "$value" ]]; then
    fail "Required $label is missing from local secure storage. Run npm run local:setup."
  fi
  printf '%s' "$value"
}

ensure_real_dashboard_data() {
  "$PYTHON_BIN" - <<'PY'
import json
from pathlib import Path

source_path = Path("public/dashboard-data/source-status.json")
if not source_path.exists():
    raise SystemExit("source-status.json is missing")

source = json.loads(source_path.read_text(encoding="utf-8"))
if source.get("status") == "sample":
    raise SystemExit("Local daily preview produced sample data; refusing to treat it as real data.")
if source.get("raw_posts_collected", 0) <= 0:
    raise SystemExit("Local daily preview produced no public source records; refusing to treat it as real data.")
PY
}

run_daily() {
  local args=()
  if [[ "$RESUME_FROM_CHECKPOINT" == "1" ]]; then
    args+=(--resume-from-checkpoint)
    if [[ "$ATTACH_CONTEXT_FROM_PROVIDER" == "1" ]]; then
      args+=(--attach-context-from-provider)
    fi
  elif [[ -n "$REPORT_DATE" ]]; then
    args+=(--report-date "$REPORT_DATE")
  fi
  if command -v caffeinate >/dev/null 2>&1; then
    if [[ ${#args[@]} -gt 0 ]]; then
      caffeinate -dimsu "$PYTHON_BIN" scripts/run_daily.py "${args[@]}"
    else
      caffeinate -dimsu "$PYTHON_BIN" scripts/run_daily.py
    fi
  else
    if [[ ${#args[@]} -gt 0 ]]; then
      "$PYTHON_BIN" scripts/run_daily.py "${args[@]}"
    else
      "$PYTHON_BIN" scripts/run_daily.py
    fi
  fi
}

cd "$ROOT"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

command -v security >/dev/null 2>&1 || fail "macOS security command is not available."
command -v "$PYTHON_BIN" >/dev/null 2>&1 || fail "$PYTHON_BIN is not available."

log "Starting ${BRAND_RADAR_DISPLAY_NAME} real daily preview run."
log "This preview will not run git pull, git commit, or git push."
if [[ "$RESUME_FROM_CHECKPOINT" == "1" && -n "$REPORT_DATE" ]]; then
  fail "BRAND_RADAR_RESUME_FROM_CHECKPOINT and BRAND_RADAR_REPORT_DATE cannot be used together."
fi

export X_SOURCE_PROVIDER="${X_SOURCE_PROVIDER:-twitterapi_io}"
export X_DAILY_LIMIT="${X_DAILY_LIMIT:-240}"
export X_JOYBUY_DAILY_LIMIT="${X_JOYBUY_DAILY_LIMIT:-160}"
export X_TEMU_DAILY_LIMIT="${X_TEMU_DAILY_LIMIT:-80}"
export X_MAX_API_REQUESTS="${X_MAX_API_REQUESTS:-12}"
export TRANSLATION_PROVIDER="${TRANSLATION_PROVIDER:-joybuilder}"
export JDBUILDER_TRANSLATION_MODEL="${JDBUILDER_TRANSLATION_MODEL:-GPT-5.5}"
export JDBUILDER_TRANSLATION_TIMEOUT_SECONDS="${JDBUILDER_TRANSLATION_TIMEOUT_SECONDS:-90}"
export JDBUILDER_TRANSLATION_BATCH_SIZE="${JDBUILDER_TRANSLATION_BATCH_SIZE:-6}"
export JDBUILDER_TRANSLATION_RETRIES="${JDBUILDER_TRANSLATION_RETRIES:-1}"
export JDBUILDER_TRANSLATION_MAX_CHARS="${JDBUILDER_TRANSLATION_MAX_CHARS:-3500}"
export TWITTERAPI_IO_KEY
export JDCLOUD_GPT_API_KEY

if [[ "$RESUME_FROM_CHECKPOINT" == "1" ]]; then
  if [[ "$ATTACH_CONTEXT_FROM_PROVIDER" == "1" ]]; then
    TWITTERAPI_IO_KEY="$(require_local_secret TWITTERAPI_IO_KEY "source connector credential")"
    log "Resuming daily dashboard generation from local checkpoint and fetching eligible conversation context only."
  else
    log "Resuming daily dashboard generation from local checkpoint without calling X."
  fi
else
  if [[ -n "$REPORT_DATE" ]]; then
    log "Generating historical dashboard data preview for report date $REPORT_DATE."
  fi
  TWITTERAPI_IO_KEY="$(require_local_secret TWITTERAPI_IO_KEY "source connector credential")"
fi
JDCLOUD_GPT_API_KEY="$(require_local_secret JDCLOUD_GPT_API_KEY "language processing credential")"

log "Generating real daily dashboard data preview."
run_daily

log "Verifying generated dashboard data preview."
"$PYTHON_BIN" scripts/security_check.py
"$PYTHON_BIN" scripts/check_dashboard_data.py
"$PYTHON_BIN" scripts/verify_data.py
"$PYTHON_BIN" scripts/report_run_summary.py
ensure_real_dashboard_data

log "Preview finished. Public dashboard files were updated locally only."
