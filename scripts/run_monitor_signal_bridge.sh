#!/bin/zsh
set -u

ROOT="${STOCK_DASHBOARD_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
PYTHON_BIN="${PYTHON_BIN:-$HOME/.local/bin/python3}"
[ -x "$PYTHON_BIN" ] || PYTHON_BIN="/usr/bin/python3"
weekday=$(date +%u)
hhmm=$(date +%H%M)

if [ "$weekday" -gt 5 ] || [ "$hhmm" -lt 0850 ] || [ "$hhmm" -gt 1510 ]; then
  exit 0
fi

cd "$ROOT" || exit 1
exec "$PYTHON_BIN" scripts/import_monitor_signals.py --ensure-monitor
