#!/bin/zsh
set -u

ROOT="${STOCK_DASHBOARD_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
PYTHON_BIN="${PYTHON_BIN:-$HOME/.local/bin/python3}"
[ -x "$PYTHON_BIN" ] || PYTHON_BIN="/usr/bin/python3"
weekday=$(date +%u)
hhmm=$(date +%H%M)

if [ "$weekday" -gt 5 ]; then
  exit 0
fi

if ! { [ "$hhmm" -ge 0930 ] && [ "$hhmm" -le 1135 ]; } && \
   ! { [ "$hhmm" -ge 1300 ] && [ "$hhmm" -le 1505 ]; }; then
  exit 0
fi

cd "$ROOT" || exit 1
exec "$PYTHON_BIN" scripts/verify_alert_quotes.py
