#!/bin/zsh
set -u

ROOT="${STOCK_DASHBOARD_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
PYTHON_BIN="${PYTHON_BIN:-$HOME/.local/bin/python3}"
[ -x "$PYTHON_BIN" ] || PYTHON_BIN="/usr/bin/python3"
LOCK_FILE="$ROOT/.intraday-refresh.lock"
weekday=$(date +%u)
hhmm=$(date +%H%M)

if [ "$weekday" -gt 5 ] || [ "$hhmm" -lt 0920 ] || [ "$hhmm" -gt 1635 ]; then
  exit 0
fi

cd "$ROOT" || exit 1
if ! /usr/bin/shlock -f "$LOCK_FILE" -p $$; then
  exit 0
fi
cleanup() {
  /bin/rm -f "$LOCK_FILE"
}
trap cleanup EXIT INT TERM

PUBLISH_MESSAGE="Recover latest verified intraday market snapshot" \
  "$PYTHON_BIN" scripts/intraday_recovery.py
