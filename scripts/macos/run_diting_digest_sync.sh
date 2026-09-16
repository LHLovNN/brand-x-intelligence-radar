#!/usr/bin/env bash
set -euo pipefail

PRIMARY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ROOT="$PRIMARY_ROOT"
source "$PRIMARY_ROOT/scripts/macos/local_env.sh"
source "$PRIMARY_ROOT/scripts/macos/publish_helpers.sh"

LOG_DIR="$ROOT/data/logs/macos"
TMP_BASE="${TMPDIR:-/tmp}"
TMP_BASE="${TMP_BASE%/}"
LOCK_DIR="$TMP_BASE/brand-radar-diting-digests.lock"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SYNC_TIMEOUT_SECONDS="${BRAND_RADAR_DITING_SYNC_TIMEOUT_SECONDS:-1800}"
NETWORK_COMMAND_TIMEOUT_SECONDS="${BRAND_RADAR_NETWORK_COMMAND_TIMEOUT_SECONDS:-600}"
DETAIL_DAYS="${BRAND_RADAR_DITING_DETAIL_DAYS:-60}"
BRANCH="${BRAND_RADAR_DITING_BRANCH:-main}"
ISOLATED_WORKTREE="${BRAND_RADAR_DITING_ISOLATED_WORKTREE:-1}"
SOURCE_REPO="${BRAND_RADAR_DITING_SOURCE_REPO:-git@github.com:codew1028/dt.git}"
SYNC_PARENT=""
SOURCE_PARENT=""
SOURCE_DIR=""
RUN_ID="$(date '+%Y%m%d-%H%M%S')"
RUN_STARTED_EPOCH="$(date '+%s')"
RUN_STATUS="failed"
CURRENT_STAGE="startup"
source "$PRIMARY_ROOT/scripts/macos/runner_lock_helpers.sh"

mkdir -p "$LOG_DIR"
find "$LOG_DIR" -type f -name 'diting-run-*.log' -mtime +30 -delete 2>/dev/null || true
RUN_LOG="$LOG_DIR/diting-run-$RUN_ID.log"
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
  release_run_lock
  if [[ -n "$SYNC_PARENT" && -d "$SYNC_PARENT" ]]; then
    case "$SYNC_PARENT" in
      "$TMP_BASE"/brand-radar-diting-sync.*) rm -rf "$SYNC_PARENT" ;;
    esac
  fi
  if [[ -n "$SOURCE_PARENT" && -d "$SOURCE_PARENT" ]]; then
    case "$SOURCE_PARENT" in
      "$TMP_BASE"/brand-radar-diting-source.*) rm -rf "$SOURCE_PARENT" ;;
    esac
  fi
  if [[ "$exit_code" == "0" && "$CURRENT_STAGE" == "complete" ]]; then
    RUN_STATUS="success"
  else
    RUN_STATUS="failed"
    if [[ "$exit_code" == "0" ]]; then
      exit_code=1
    fi
  fi
  printf '{"job":"diting","run_id":"%s","status":"%s","stage":"%s","elapsed_seconds":%s,"log":"%s"}\n' \
    "$RUN_ID" "$RUN_STATUS" "$CURRENT_STAGE" "$elapsed" "$RUN_LOG"
  trap - EXIT
  exit "$exit_code"
}

if ! acquire_run_lock; then
  fail "Another ${BRAND_RADAR_DISPLAY_NAME} Diting digest sync is already active."
fi
trap cleanup EXIT
trap 'handle_runner_signal INT' INT
trap 'handle_runner_signal TERM' TERM

ensure_no_local_source_changes() {
  local untracked
  if ! git diff --quiet -- . \
    ':!public/index.html' \
    ':!public/dashboard-data/dt-digests/**' \
    ':!public/dashboard-data/lazy/tg-replies/**' \
    ':!public/dashboard-data-bundle.js' \
    ':!docs/*.md' \
    ':!docs/*.html'; then
    fail "Local non-Diting source changes exist. Commit or stash them before the scheduled sync."
  fi

  untracked="$(
    git ls-files --others --exclude-standard \
      | grep -vE '^(public/index\.html|public/dashboard-data/dt-digests/.+\.json|public/dashboard-data/lazy/tg-replies/.+\.json|public/dashboard-data-bundle\.js|docs/[^/]+\.(md|html))$' \
      || true
  )"
  if [[ -n "$untracked" ]]; then
    printf '%s\n' "$untracked" >&2
    fail "Untracked non-Diting files exist. Commit, ignore or remove them before the scheduled sync."
  fi
}

prepare_sync_checkout() {
  local remote_url
  if [[ "$ISOLATED_WORKTREE" != "1" ]]; then
    ROOT="$PRIMARY_ROOT"
    ensure_no_local_source_changes
    log "Syncing repository."
    run_bounded "$NETWORK_COMMAND_TIMEOUT_SECONDS" git pull --ff-only origin "$BRANCH"
    return
  fi

  remote_url="$(git -C "$PRIMARY_ROOT" config --get remote.origin.url || true)"
  if [[ -z "$remote_url" ]]; then
    fail "Cannot determine origin remote for isolated Diting digest sync."
  fi

  SYNC_PARENT="$(mktemp -d "$TMP_BASE/brand-radar-diting-sync.XXXXXX")"
  ROOT="$SYNC_PARENT/repo"
  log "Preparing isolated clean checkout for Diting digest sync."
  run_bounded "$NETWORK_COMMAND_TIMEOUT_SECONDS" git clone --quiet --depth 1 --branch "$BRANCH" "$remote_url" "$ROOT"
}

prepare_source_checkout() {
  SOURCE_PARENT="$(mktemp -d "$TMP_BASE/brand-radar-diting-source.XXXXXX")"
  SOURCE_DIR="$SOURCE_PARENT/repo"
  log "Preparing sparse local Diting source checkout."
  run_bounded "$NETWORK_COMMAND_TIMEOUT_SECONDS" git clone --quiet --depth 1 --filter=blob:none --no-checkout "$SOURCE_REPO" "$SOURCE_DIR"
  git -C "$SOURCE_DIR" sparse-checkout set --no-cone \
    '/search-index.json' \
    '/*-AI日报.html' \
    '/*-tg-digest.html' \
    '/*-tg-digest.json'
  run_bounded "$NETWORK_COMMAND_TIMEOUT_SECONDS" git -C "$SOURCE_DIR" checkout --quiet
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

latest_diting_date() {
  "$PYTHON_BIN" - <<'PY'
import json
from pathlib import Path

path = Path("public/dashboard-data/dt-digests/index.json")
if not path.exists():
    print("")
else:
    data = json.loads(path.read_text(encoding="utf-8"))
    print(data.get("latest_date") or "")
PY
}

cd "$PRIMARY_ROOT"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
export BRAND_RADAR_FORCE_IPV4="${BRAND_RADAR_FORCE_IPV4:-1}"
export GIT_TERMINAL_PROMPT=0
export GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh -o BatchMode=yes -o ConnectTimeout=20}"

command -v git >/dev/null 2>&1 || fail "git is not available."
command -v "$PYTHON_BIN" >/dev/null 2>&1 || fail "$PYTHON_BIN is not available."

log "Starting ${BRAND_RADAR_DISPLAY_NAME} Diting digest sync."
CURRENT_STAGE="prepare_checkout"
prepare_sync_checkout
cd "$ROOT"
export BRAND_RADAR_DEFER_SHARED_ASSETS=1

CURRENT_STAGE="prepare_source_checkout"
prepare_source_checkout

log "Syncing AI/TG digest data from Diting."
CURRENT_STAGE="upstream_sync"
if command -v caffeinate >/dev/null 2>&1; then
  run_bounded "$SYNC_TIMEOUT_SECONDS" caffeinate -dimsu "$PYTHON_BIN" scripts/sync_dt_digests.py --detail-days "$DETAIL_DAYS" --source-dir "$SOURCE_DIR"
else
  run_bounded "$SYNC_TIMEOUT_SECONDS" "$PYTHON_BIN" scripts/sync_dt_digests.py --detail-days "$DETAIL_DAYS" --source-dir "$SOURCE_DIR"
fi

log "Verifying Diting digest artifacts."
CURRENT_STAGE="local_verification"
"$PYTHON_BIN" scripts/security_check.py
"$PYTHON_BIN" scripts/check_dashboard_data.py
"$PYTHON_BIN" scripts/verify_data.py

log "Staging Diting public artifacts only."
CURRENT_STAGE="stage_module_artifacts"
git add public/dashboard-data/dt-digests
if [[ -d public/dashboard-data/lazy/tg-replies ]]; then
  git add public/dashboard-data/lazy/tg-replies
fi

COMMIT_DATE="$(latest_diting_date)"
if git diff --cached --quiet; then
  log "No Diting digest changes to commit."
else
  CURRENT_STAGE="commit_module_artifacts"
  commit_with_repo_identity "Sync Diting digest archive ${COMMIT_DATE:-$(date '+%Y-%m-%d')}"
fi

acquire_publish_lock
publish_committed_changes "$BRANCH" "Refresh shared dashboard assets ${COMMIT_DATE:-$(date '+%Y-%m-%d')}"
release_publish_lock

CURRENT_STAGE="public_verification"
AI_DATE="$("$PYTHON_BIN" - <<'PY'
import json
from pathlib import Path

data = json.loads(Path("public/dashboard-data/dt-digests/index.json").read_text(encoding="utf-8"))
print((data.get("latest") or {}).get("ai") or "")
PY
)"
TG_DATE="$("$PYTHON_BIN" - <<'PY'
import json
from pathlib import Path

data = json.loads(Path("public/dashboard-data/dt-digests/index.json").read_text(encoding="utf-8"))
print((data.get("latest") or {}).get("tg") or "")
PY
)"
run_bounded "$NETWORK_COMMAND_TIMEOUT_SECONDS" "$PYTHON_BIN" scripts/verify_publication.py \
  --base-url "${BRAND_RADAR_PUBLIC_BASE_URL:-https://lhlovnn.github.io/brand-x-intelligence-radar}" \
  --ai-date "$AI_DATE" \
  --tg-date "$TG_DATE"

if [[ "$ISOLATED_WORKTREE" == "1" && -z "$(git -C "$PRIMARY_ROOT" status --porcelain)" ]]; then
  CURRENT_STAGE="refresh_primary_checkout"
  run_bounded "$NETWORK_COMMAND_TIMEOUT_SECONDS" git -C "$PRIMARY_ROOT" pull --ff-only origin "$BRANCH"
else
  log "Primary checkout has local changes; leaving it untouched after isolated publication."
fi

CURRENT_STAGE="complete"
log "${BRAND_RADAR_DISPLAY_NAME} Diting digest sync finished."
