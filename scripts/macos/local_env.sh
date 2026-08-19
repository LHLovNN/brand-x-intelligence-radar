#!/usr/bin/env bash

BRAND_RADAR_DISPLAY_NAME="${BRAND_RADAR_DISPLAY_NAME:-Brand Radar}"
BRAND_RADAR_LAUNCHD_LABEL="${BRAND_RADAR_LAUNCHD_LABEL:-com.brand-radar.daily}"
BRAND_RADAR_DITING_LAUNCHD_LABEL="${BRAND_RADAR_DITING_LAUNCHD_LABEL:-com.brand-radar.diting-digests}"
BRAND_RADAR_LEGACY_LAUNCHD_LABEL="${BRAND_RADAR_LEGACY_LAUNCHD_LABEL:-com.joybuy-radar.daily}"
BRAND_RADAR_KEYCHAIN_ACCOUNT="${BRAND_RADAR_KEYCHAIN_ACCOUNT:-${JOYBUY_RADAR_KEYCHAIN_ACCOUNT:-${USER:-$(id -un)}}}"
BRAND_RADAR_KEYCHAIN_SERVICE_PREFIX="${BRAND_RADAR_KEYCHAIN_SERVICE_PREFIX:-brand-radar}"
BRAND_RADAR_LEGACY_KEYCHAIN_SERVICE_PREFIX="${BRAND_RADAR_LEGACY_KEYCHAIN_SERVICE_PREFIX:-joybuy-radar}"
BRAND_RADAR_USE_ENV_VALUES="${BRAND_RADAR_USE_ENV_VALUES:-${JOYBUY_RADAR_USE_ENV_SECRETS:-}}"

brand_radar_primary_keychain_service() {
  local name="$1"
  printf '%s.%s' "$BRAND_RADAR_KEYCHAIN_SERVICE_PREFIX" "$name"
}

brand_radar_keychain_service_candidates() {
  local name="$1"
  local primary legacy
  primary="$(brand_radar_primary_keychain_service "$name")"
  legacy="$BRAND_RADAR_LEGACY_KEYCHAIN_SERVICE_PREFIX.$name"

  printf '%s\n' "$primary"
  if [[ "$legacy" != "$primary" ]]; then
    printf '%s\n' "$legacy"
  fi
}

brand_radar_keychain_value() {
  local name="$1"
  local service value

  while IFS= read -r service; do
    [[ -n "$service" ]] || continue
    value="$(security find-generic-password -a "$BRAND_RADAR_KEYCHAIN_ACCOUNT" -s "$service" -w 2>/dev/null || true)"
    if [[ -n "$value" ]]; then
      printf '%s' "$value"
      return 0
    fi
  done < <(brand_radar_keychain_service_candidates "$name")

  return 1
}

brand_radar_store_keychain_value() {
  local name="$1"
  local value="$2"
  local service
  service="$(brand_radar_primary_keychain_service "$name")"

  security add-generic-password -a "$BRAND_RADAR_KEYCHAIN_ACCOUNT" -s "$service" -w "$value" -U >/dev/null
}
