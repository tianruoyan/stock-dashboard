#!/bin/zsh
set -u

ROOT="${STOCK_DASHBOARD_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
PYTHON_BIN="${PYTHON_BIN:-$HOME/.local/bin/python3}"
[ -x "$PYTHON_BIN" ] || PYTHON_BIN="/usr/bin/python3"

ICLOUD_SOURCE="$HOME/Library/Mobile Documents/com~apple~CloudDocs/同花顺自选股.txt"
COOKIE_SOURCE="$HOME/Library/Containers/cn.com.10jqka.macstockPro/Data/Library/Cookies/Cookies.binarycookies"
COOKIE_MIRROR_DIR="$ROOT/logs/ths-cookie-source"
COOKIE_MIRROR_FILE="$COOKIE_MIRROR_DIR/Cookies.binarycookies"
MIRROR_DIR="$ROOT/logs/ths-watchlist-source"
MIRROR_FILE="$MIRROR_DIR/同花顺自选股.txt"
DRY_RUN_ARGS=()
[ "${1:-}" = "--dry-run" ] && DRY_RUN_ARGS+=("--dry-run")

mkdir -p "$COOKIE_MIRROR_DIR" "$MIRROR_DIR"

if /usr/bin/osascript - "$COOKIE_SOURCE" "$COOKIE_MIRROR_DIR" >/dev/null <<'APPLESCRIPT'
on run argv
  set sourcePath to item 1 of argv
  set targetPath to item 2 of argv
  set sourceFile to POSIX file sourcePath
  set targetFolder to POSIX file targetPath
  tell application "Finder"
    duplicate sourceFile to targetFolder with replacing
  end tell
end run
APPLESCRIPT
then
  if [ -s "$COOKIE_MIRROR_FILE" ]; then
    cd "$ROOT" || exit 1
    THS_COOKIE_FILE="$COOKIE_MIRROR_FILE" "$PYTHON_BIN" scripts/import_ths_watchlist.py --mode ths "${DRY_RUN_ARGS[@]}"
    desktop_status=$?
    [ "$desktop_status" -eq 0 ] && exit 0
    echo "desktop watchlist sync failed; try iCloud text fallback"
  fi
fi

/usr/bin/osascript - "$ICLOUD_SOURCE" "$MIRROR_DIR" >/dev/null <<'APPLESCRIPT'
on run argv
  set sourcePath to item 1 of argv
  set targetPath to item 2 of argv
  set sourceFile to POSIX file sourcePath
  set targetFolder to POSIX file targetPath
  tell application "Finder"
    duplicate sourceFile to targetFolder with replacing
  end tell
end run
APPLESCRIPT
copy_status=$?

if [ "$copy_status" -ne 0 ] || [ ! -s "$MIRROR_FILE" ]; then
  echo "iCloud mirror failed; keep existing watchlist"
  exit 1
fi

if [ "$MIRROR_FILE" -ot "$ROOT/config/watchlist.json" ]; then
  echo "iCloud watchlist is older than current config; refuse stale fallback"
  exit 2
fi

cd "$ROOT" || exit 1
exec "$PYTHON_BIN" scripts/import_ths_watchlist.py --mode file --source "$MIRROR_FILE" "${DRY_RUN_ARGS[@]}"
