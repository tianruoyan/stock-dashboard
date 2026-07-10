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

if ! { [ "$hhmm" -ge 0915 ] && [ "$hhmm" -le 1135 ]; } && \
   ! { [ "$hhmm" -ge 1255 ] && [ "$hhmm" -le 1505 ]; }; then
  exit 0
fi

cd "$ROOT" || exit 1
"$PYTHON_BIN" scripts/update_intraday_market.py || exit 1
PUBLISH_MESSAGE="Update intraday market snapshot" exec scripts/publish_dashboard.sh
