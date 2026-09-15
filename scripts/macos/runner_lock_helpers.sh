#!/usr/bin/env bash

RUN_LOCK_HELD=0
RUNNER_SUPPORT_ROOT="${PRIMARY_ROOT:-$ROOT}"
RUN_LOCK_STALE_MINUTES="${BRAND_RADAR_RUN_LOCK_STALE_MINUTES:-240}"

run_bounded() {
  local seconds="$1"
  shift
  "$PYTHON_BIN" "$RUNNER_SUPPORT_ROOT/scripts/run_with_timeout.py" --seconds "$seconds" -- "$@"
}

release_run_lock() {
  if [[ "$RUN_LOCK_HELD" == "1" ]]; then
    rm -f "$LOCK_DIR/pid" 2>/dev/null || true
    rmdir "$LOCK_DIR" 2>/dev/null || true
    RUN_LOCK_HELD=0
  fi
}

acquire_run_lock() {
  local owner_pid=""
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    printf '%s\n' "$$" > "$LOCK_DIR/pid"
    RUN_LOCK_HELD=1
    return 0
  fi
  if [[ -f "$LOCK_DIR/pid" ]]; then
    owner_pid="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
  fi
  if [[ "$owner_pid" =~ ^[0-9]+$ ]] \
    && kill -0 "$owner_pid" 2>/dev/null \
    && ! find "$LOCK_DIR" -maxdepth 0 -mmin "+$RUN_LOCK_STALE_MINUTES" -print 2>/dev/null | grep -q .; then
    return 1
  fi
  if [[ -z "$owner_pid" ]] && ! find "$LOCK_DIR" -maxdepth 0 -mmin +1 -print 2>/dev/null | grep -q .; then
    return 1
  fi
  log "Removing stale run lock at $LOCK_DIR."
  rm -f "$LOCK_DIR/pid" 2>/dev/null || true
  rmdir "$LOCK_DIR" 2>/dev/null || true
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    printf '%s\n' "$$" > "$LOCK_DIR/pid"
    RUN_LOCK_HELD=1
    return 0
  fi
  return 1
}

handle_runner_signal() {
  local signal_name="$1"
  RUN_STATUS="failed"
  case "$signal_name" in
    INT) CURRENT_STAGE="interrupted_sigint"; exit 130 ;;
    TERM) CURRENT_STAGE="interrupted_sigterm"; exit 143 ;;
    *) CURRENT_STAGE="interrupted_unknown"; exit 1 ;;
  esac
}
