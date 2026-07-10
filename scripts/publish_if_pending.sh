#!/bin/zsh
set -u

ROOT="${STOCK_DASHBOARD_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"

if [ ! -f "$ROOT/.publish-pending" ] && [ ! -f "$ROOT/.push-now" ]; then
  exit 0
fi

exec "$ROOT/scripts/publish_dashboard.sh"
