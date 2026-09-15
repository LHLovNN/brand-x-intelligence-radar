#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/brand-radar-lock-test.XXXXXX")"
trap 'rm -rf "$TEST_ROOT"' EXIT

log() { :; }
source "$ROOT/scripts/macos/runner_lock_helpers.sh"

LOCK_DIR="$TEST_ROOT/new.lock"
acquire_run_lock
[[ -f "$LOCK_DIR/pid" ]]
[[ "$(cat "$LOCK_DIR/pid")" == "$$" ]]
release_run_lock
[[ ! -e "$LOCK_DIR" ]]

LOCK_DIR="$TEST_ROOT/stale.lock"
mkdir "$LOCK_DIR"
printf '99999999\n' > "$LOCK_DIR/pid"
acquire_run_lock
[[ "$(cat "$LOCK_DIR/pid")" == "$$" ]]
release_run_lock

LOCK_DIR="$TEST_ROOT/active.lock"
mkdir "$LOCK_DIR"
printf '%s\n' "$$" > "$LOCK_DIR/pid"
if acquire_run_lock; then
  printf 'Active lock was incorrectly replaced.\n' >&2
  exit 1
fi
rm -f "$LOCK_DIR/pid"
rmdir "$LOCK_DIR"

LOCK_DIR="$TEST_ROOT/fresh-empty.lock"
mkdir "$LOCK_DIR"
if acquire_run_lock; then
  printf 'Fresh lock without a PID was incorrectly replaced during its creation window.\n' >&2
  exit 1
fi
rmdir "$LOCK_DIR"

set +e
signal_result="$({
  RUN_STATUS="success"
  CURRENT_STAGE="running"
  trap 'printf "%s:%s" "$RUN_STATUS" "$CURRENT_STAGE"' EXIT
  handle_runner_signal TERM
} 2>/dev/null)"
signal_exit=$?
set -e
[[ "$signal_exit" == "143" ]]
[[ "$signal_result" == "failed:interrupted_sigterm" ]]

TMPDIR="$TEST_ROOT"
source "$ROOT/scripts/macos/publish_helpers.sh"
mkdir "$PUBLISH_LOCK_DIR"
printf '99999999\n' > "$PUBLISH_LOCK_DIR/pid"
acquire_publish_lock
[[ "$(cat "$PUBLISH_LOCK_DIR/pid")" == "$$" ]]
release_publish_lock
[[ ! -e "$PUBLISH_LOCK_DIR" ]]

printf 'Runner lock tests passed.\n'
