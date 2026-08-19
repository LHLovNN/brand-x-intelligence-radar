#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$ROOT/scripts/macos/local_env.sh"

LOG_DIR="$ROOT/data/logs/macos"
LOCK_DIR="${TMPDIR:-/tmp}/brand-radar-diting-digests.lock"
PYTHON_BIN="${PYTHON_BIN:-python3}"
DETAIL_DAYS="${BRAND_RADAR_DITING_DETAIL_DAYS:-60}"

mkdir -p "$LOG_DIR"

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
  fail "Another ${BRAND_RADAR_DISPLAY_NAME} Diting digest sync is already active."
fi
trap cleanup EXIT

ensure_no_local_source_changes() {
  local untracked
  if ! git diff --quiet -- . \
    ':!public/index.html' \
    ':!public/dashboard-data/dt-digests/**' \
    ':!public/dashboard-data-bundle.js' \
    ':!docs/*.md' \
    ':!docs/*.html'; then
    fail "Local non-Diting source changes exist. Commit or stash them before the scheduled sync."
  fi

  untracked="$(
    git ls-files --others --exclude-standard \
      | grep -vE '^(public/index\.html|public/dashboard-data/dt-digests/.+\.json|public/dashboard-data-bundle\.js|docs/[^/]+\.(md|html))$' \
      || true
  )"
  if [[ -n "$untracked" ]]; then
    printf '%s\n' "$untracked" >&2
    fail "Untracked non-Diting files exist. Commit, ignore or remove them before the scheduled sync."
  fi
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

cd "$ROOT"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

command -v git >/dev/null 2>&1 || fail "git is not available."
command -v "$PYTHON_BIN" >/dev/null 2>&1 || fail "$PYTHON_BIN is not available."

log "Starting ${BRAND_RADAR_DISPLAY_NAME} Diting digest sync."
ensure_no_local_source_changes

log "Syncing repository."
git pull --ff-only origin main

log "Syncing AI/TG digest data from Diting."
if command -v caffeinate >/dev/null 2>&1; then
  caffeinate -dimsu "$PYTHON_BIN" scripts/sync_dt_digests.py --detail-days "$DETAIL_DAYS"
else
  "$PYTHON_BIN" scripts/sync_dt_digests.py --detail-days "$DETAIL_DAYS"
fi

log "Verifying Diting digest artifacts."
"$PYTHON_BIN" scripts/security_check.py
"$PYTHON_BIN" scripts/check_dashboard_data.py
"$PYTHON_BIN" scripts/verify_data.py

log "Staging Diting public artifacts only."
git add public/index.html public/dashboard-data/dt-digests public/dashboard-data-bundle.js

if git diff --cached --quiet; then
  log "No Diting digest changes to commit."
else
  COMMIT_DATE="$(latest_diting_date)"
  commit_with_repo_identity "Sync Diting digest archive ${COMMIT_DATE:-$(date '+%Y-%m-%d')}"
  git push
fi

log "${BRAND_RADAR_DISPLAY_NAME} Diting digest sync finished."
