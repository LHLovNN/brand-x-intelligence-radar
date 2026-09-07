#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$ROOT/scripts/macos/local_env.sh"
source "$ROOT/scripts/macos/publish_helpers.sh"

LOG_DIR="$ROOT/data/logs/macos"
LOCK_DIR="${TMPDIR:-/tmp}/brand-radar-daily.lock"
PYTHON_BIN="${PYTHON_BIN:-python3}"
RESUME_FROM_CHECKPOINT="${BRAND_RADAR_RESUME_FROM_CHECKPOINT:-0}"
ATTACH_CONTEXT_FROM_PROVIDER="${BRAND_RADAR_ATTACH_CONTEXT_FROM_PROVIDER:-0}"
REPORT_DATE="${BRAND_RADAR_REPORT_DATE:-}"
BRANCH="${BRAND_RADAR_BRANCH:-main}"
RUN_ID="$(date '+%Y%m%d-%H%M%S')"
RUN_STARTED_EPOCH="$(date '+%s')"
RUN_STATUS="failed"
CURRENT_STAGE="startup"

mkdir -p "$LOG_DIR"
find "$LOG_DIR" -type f -name 'daily-run-*.log' -mtime +30 -delete 2>/dev/null || true
RUN_LOG="$LOG_DIR/daily-run-$RUN_ID.log"
exec > >(tee -a "$RUN_LOG") 2>&1

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "$*"
}

fail() {
  log "ERROR: $*"
  exit 1
}

cleanup() {
  local exit_code=$?
  local finished_epoch
  local elapsed
  finished_epoch="$(date '+%s')"
  elapsed=$((finished_epoch - RUN_STARTED_EPOCH))
  release_publish_lock
  rmdir "$LOCK_DIR" 2>/dev/null || true
  if [[ "$exit_code" == "0" ]]; then
    RUN_STATUS="success"
  fi
  printf '{"job":"daily","run_id":"%s","status":"%s","stage":"%s","elapsed_seconds":%s,"log":"%s"}\n' \
    "$RUN_ID" "$RUN_STATUS" "$CURRENT_STAGE" "$elapsed" "$RUN_LOG"
}

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  fail "Another ${BRAND_RADAR_DISPLAY_NAME} daily run is already active."
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

ensure_no_local_source_changes() {
  local untracked
  # Daily automation owns dashboard artifacts. Top-level docs are project
  # collateral and should not block the monitoring run when left in progress.
  if ! git diff --quiet -- . \
    ':!public/index.html' \
    ':!public/dashboard-data/*.json' \
    ':!public/dashboard-data/daily/*.json' \
    ':!public/dashboard-data/platform-trends/**' \
    ':!public/dashboard-data/lazy/conversations/**' \
    ':!public/dashboard-data-bundle.js' \
    ':!docs/*.md' \
    ':!docs/*.html'; then
    fail "Local non-dashboard source changes exist. Commit or stash them before the scheduled run."
  fi

  untracked="$(
    git ls-files --others --exclude-standard \
      | grep -vE '^(public/index\.html|public/dashboard-data/[^/]+\.json|public/dashboard-data/daily/[^/]+\.json|public/dashboard-data/platform-trends/.+\.json|public/dashboard-data/lazy/conversations/.+\.json|public/dashboard-data-bundle\.js|docs/[^/]+\.(md|html))$' \
      || true
  )"
  if [[ -n "$untracked" ]]; then
    printf '%s\n' "$untracked" >&2
    fail "Untracked non-dashboard files exist. Commit, ignore or remove them before the scheduled run."
  fi
}

ensure_real_dashboard_data() {
  "$PYTHON_BIN" - <<'PY'
import json
import sys
from pathlib import Path

source_path = Path("public/dashboard-data/source-status.json")
if not source_path.exists():
    raise SystemExit("source-status.json is missing")

source = json.loads(source_path.read_text(encoding="utf-8"))
if source.get("status") == "sample":
    raise SystemExit("Local daily produced sample data; refusing to publish.")
if source.get("raw_posts_collected", 0) <= 0:
    raise SystemExit("Local daily produced no public source records; refusing to publish.")
PY
}

commit_with_repo_identity() {
  local message="$1"
  local author_name
  local author_email
  local committer_name
  local committer_email

  author_name="$(git config user.name || git log -1 --format=%an)"
  author_email="$(git config user.email || git log -1 --format=%ae)"
  committer_name="${GIT_COMMITTER_NAME:-$author_name}"
  committer_email="${GIT_COMMITTER_EMAIL:-$author_email}"

  GIT_AUTHOR_NAME="${GIT_AUTHOR_NAME:-$author_name}" \
    GIT_AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL:-$author_email}" \
    GIT_COMMITTER_NAME="$committer_name" \
    GIT_COMMITTER_EMAIL="$committer_email" \
    git commit -m "$message"
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

command -v git >/dev/null 2>&1 || fail "git is not available."
command -v security >/dev/null 2>&1 || fail "macOS security command is not available."
command -v "$PYTHON_BIN" >/dev/null 2>&1 || fail "$PYTHON_BIN is not available."

log "Starting ${BRAND_RADAR_DISPLAY_NAME} local daily run (run_id=$RUN_ID)."
if [[ "$RESUME_FROM_CHECKPOINT" == "1" && -n "$REPORT_DATE" ]]; then
  fail "BRAND_RADAR_RESUME_FROM_CHECKPOINT and BRAND_RADAR_REPORT_DATE cannot be used together."
fi
if [[ "$ATTACH_CONTEXT_FROM_PROVIDER" == "1" && "$RESUME_FROM_CHECKPOINT" != "1" ]]; then
  fail "BRAND_RADAR_ATTACH_CONTEXT_FROM_PROVIDER requires BRAND_RADAR_RESUME_FROM_CHECKPOINT."
fi
ensure_no_local_source_changes

CURRENT_STAGE="initial_repository_sync"
log "Syncing repository."
git pull --ff-only origin "$BRANCH"

export X_SOURCE_PROVIDER="${X_SOURCE_PROVIDER:-twitterapi_io}"
export X_DAILY_LIMIT="${X_DAILY_LIMIT:-120}"
export X_JOYBUY_DAILY_LIMIT="${X_JOYBUY_DAILY_LIMIT:-100}"
export X_TEMU_DAILY_LIMIT="${X_TEMU_DAILY_LIMIT:-20}"
export X_MAX_API_REQUESTS="${X_MAX_API_REQUESTS:-6}"
export TRANSLATION_PROVIDER="${TRANSLATION_PROVIDER:-joybuilder}"
export JDBUILDER_TRANSLATION_MODEL="${JDBUILDER_TRANSLATION_MODEL:-GPT-5.5}"
export JDBUILDER_TRANSLATION_TIMEOUT_SECONDS="${JDBUILDER_TRANSLATION_TIMEOUT_SECONDS:-90}"
export JDBUILDER_TRANSLATION_BATCH_SIZE="${JDBUILDER_TRANSLATION_BATCH_SIZE:-6}"
export JDBUILDER_TRANSLATION_RETRIES="${JDBUILDER_TRANSLATION_RETRIES:-1}"
export JDBUILDER_TRANSLATION_MAX_CHARS="${JDBUILDER_TRANSLATION_MAX_CHARS:-3500}"
export BRAND_RADAR_DEFER_SHARED_ASSETS=1
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
    log "Generating historical dashboard data for report date $REPORT_DATE."
  fi
  TWITTERAPI_IO_KEY="$(require_local_secret TWITTERAPI_IO_KEY "source connector credential")"
fi
JDCLOUD_GPT_API_KEY="$(require_local_secret JDCLOUD_GPT_API_KEY "language processing credential")"

log "Generating real daily dashboard data."
CURRENT_STAGE="collection_and_generation"
run_daily

log "Verifying generated dashboard data."
CURRENT_STAGE="local_verification"
"$PYTHON_BIN" scripts/security_check.py
"$PYTHON_BIN" scripts/check_dashboard_data.py
"$PYTHON_BIN" scripts/verify_data.py
"$PYTHON_BIN" scripts/report_run_summary.py
ensure_real_dashboard_data

log "Staging public dashboard artifacts only."
CURRENT_STAGE="stage_module_artifacts"
git add public/dashboard-data/*.json public/dashboard-data/daily/*.json
if [[ -d public/dashboard-data/platform-trends ]]; then
  git add public/dashboard-data/platform-trends
fi
if [[ -d public/dashboard-data/lazy/conversations ]]; then
  git add public/dashboard-data/lazy/conversations
fi

COMMIT_REPORT_DATE="${REPORT_DATE:-$("$PYTHON_BIN" - <<'PY'
import json
from pathlib import Path

try:
    print(json.loads(Path("public/dashboard-data/daily/latest.json").read_text(encoding="utf-8")).get("date") or "")
except Exception:
    print("")
PY
)}"
if git diff --cached --quiet; then
  log "No dashboard data changes to commit."
else
  CURRENT_STAGE="commit_module_artifacts"
  commit_with_repo_identity "Archive local daily dashboard data ${COMMIT_REPORT_DATE:-$(date '+%Y-%m-%d')}"
fi

acquire_publish_lock
publish_committed_changes "$BRANCH" "Refresh shared dashboard assets ${COMMIT_REPORT_DATE:-$(date '+%Y-%m-%d')}"
release_publish_lock

CURRENT_STAGE="public_verification"
VERIFY_ARGS=(--brand-date "$COMMIT_REPORT_DATE")
if [[ "$RESUME_FROM_CHECKPOINT" != "1" ]]; then
  VERIFY_ARGS+=(--xiaohongshu-date "$COMMIT_REPORT_DATE")
fi
"$PYTHON_BIN" scripts/verify_publication.py \
  --base-url "${BRAND_RADAR_PUBLIC_BASE_URL:-https://lhlovnn.github.io/brand-x-intelligence-radar}" \
  "${VERIFY_ARGS[@]}"

CURRENT_STAGE="complete"
log "${BRAND_RADAR_DISPLAY_NAME} local daily run finished."
