#!/bin/zsh
set -euo pipefail

ROOT="${STOCK_DASHBOARD_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
LABEL="com.stock-dashboard.monitor-signal-bridge"
DOMAIN="gui/$(id -u)"
SOURCE="$ROOT/scripts/$LABEL.plist"
TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"

mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/logs"
plutil -lint "$SOURCE" >/dev/null
cp "$SOURCE" "$TARGET"
chmod +x "$ROOT/scripts/run_monitor_signal_bridge.sh" "$ROOT/scripts/import_monitor_signals.py"
launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
launchctl bootstrap "$DOMAIN" "$TARGET"
launchctl enable "$DOMAIN/$LABEL"
launchctl kickstart -k "$DOMAIN/$LABEL"
echo "monitor signal bridge installed"
