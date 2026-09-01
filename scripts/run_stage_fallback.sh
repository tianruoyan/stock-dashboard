#!/bin/zsh
set -u

ROOT="${STOCK_DASHBOARD_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
PYTHON_BIN="${PYTHON_BIN:-$HOME/.local/bin/python3}"
[ -x "$PYTHON_BIN" ] || PYTHON_BIN="/usr/bin/python3"
LOCK_FILE="$ROOT/.stage-fallback.lock"

cd "$ROOT" || exit 1
if ! /usr/bin/shlock -f "$LOCK_FILE" -p $$; then
  exit 0
fi
cleanup() {
  /bin/rm -f "$LOCK_FILE"
}
trap cleanup EXIT INT TERM

PUBLISH_MESSAGE="Update required V1 market stage" \
  "$PYTHON_BIN" scripts/stage_fallback.py
