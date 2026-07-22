#!/bin/zsh
set -euo pipefail

ROOT="${STOCK_DASHBOARD_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
AGENTS_DIR="$HOME/Library/LaunchAgents"
DOMAIN="gui/$(id -u)"
labels=(
  com.stock-dashboard.publisher
  com.stock-dashboard.intraday-data
  com.stock-dashboard.intraday-recovery
  com.stock-dashboard.codex-runtime
  com.stock-dashboard.local-health
)

mkdir -p "$AGENTS_DIR" "$ROOT/logs"

for label in "${labels[@]}"; do
  source_plist="$ROOT/scripts/$label.plist"
  target_plist="$AGENTS_DIR/$label.plist"
  plutil -lint "$source_plist" >/dev/null
  cp "$source_plist" "$target_plist"
  launchctl bootout "$DOMAIN/$label" >/dev/null 2>&1 || true
  launchctl bootstrap "$DOMAIN" "$target_plist"
  launchctl enable "$DOMAIN/$label"
done

echo "single-agent services installed"
