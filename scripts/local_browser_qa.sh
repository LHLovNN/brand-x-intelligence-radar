#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "Brand Radar local browser QA"
echo "Project: $ROOT"
echo

if ! node -e "require.resolve('playwright')" >/dev/null 2>&1; then
  echo "ERROR: Playwright 1.62.1 is required. Run npm install first." >&2
  exit 1
fi

node scripts/verify_dashboard.cjs
