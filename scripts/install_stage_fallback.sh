#!/bin/zsh
set -euo pipefail

ROOT="${STOCK_DASHBOARD_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
LABEL="com.stock-dashboard.stage-fallback"
SOURCE_PLIST="$ROOT/scripts/$LABEL.plist"
TARGET_PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/logs"
plutil -lint "$SOURCE_PLIST" >/dev/null
cp "$SOURCE_PLIST" "$TARGET_PLIST"
launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
launchctl bootstrap "$DOMAIN" "$TARGET_PLIST"
launchctl enable "$DOMAIN/$LABEL"

echo "stage fallback service installed"
