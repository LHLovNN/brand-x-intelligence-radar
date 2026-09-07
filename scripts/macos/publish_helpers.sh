#!/usr/bin/env bash

PUBLISH_LOCK_DIR="${TMPDIR:-/tmp}/brand-radar-publication.lock"
PUBLISH_LOCK_HELD=0

acquire_publish_lock() {
  local attempt
  CURRENT_STAGE="waiting_for_publish_lock"
  for attempt in $(seq 1 180); do
    if mkdir "$PUBLISH_LOCK_DIR" 2>/dev/null; then
      PUBLISH_LOCK_HELD=1
      log "Acquired shared publication lock."
      return 0
    fi
    if [[ "$attempt" == "1" ]]; then
      log "Another dashboard job is publishing; waiting without repeating collection."
    fi
    sleep 5
  done
  fail "Timed out waiting for the shared publication lock."
}

release_publish_lock() {
  if [[ "$PUBLISH_LOCK_HELD" == "1" ]]; then
    rmdir "$PUBLISH_LOCK_DIR" 2>/dev/null || true
    PUBLISH_LOCK_HELD=0
  fi
}

publish_committed_changes() {
  local branch="$1"
  local message="$2"
  local attempt
  for attempt in 1 2 3; do
    CURRENT_STAGE="sync_before_publish"
    git pull --rebase origin "$branch"

    CURRENT_STAGE="rebuild_shared_assets"
    "$PYTHON_BIN" scripts/rebuild_shared_assets.py
    git add public/index.html public/dashboard-data-bundle.js
    if [[ -d public/dashboard-data/lazy ]]; then
      git add -u public/dashboard-data/lazy
    fi
    if ! git diff --cached --quiet; then
      if [[ "$(git rev-list --count "origin/$branch..HEAD")" -gt 0 ]]; then
        git commit --amend --no-edit
      else
        commit_with_repo_identity "$message"
      fi
    fi

    if [[ "$(git rev-list --count "origin/$branch..HEAD")" -eq 0 ]]; then
      log "No publication changes to push."
      return 0
    fi

    CURRENT_STAGE="push"
    if git push origin "HEAD:$branch"; then
      return 0
    fi
    log "Push raced with another remote update; retrying publication only ($attempt/3)."
    sleep $((attempt * 3))
  done
  fail "Publication push failed after three publish-only retries."
}
