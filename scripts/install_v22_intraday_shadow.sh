#!/bin/zsh
set -euo pipefail

ROOT="${STOCK_DASHBOARD_V2_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
LABEL="com.stock-dashboard.v22-intraday-shadow"
SOURCE="$ROOT/scripts/$LABEL.plist"
TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/logs"
zsh "$ROOT/scripts/deploy_v22_intraday_runtime.sh" --seed-data
plutil -lint "$SOURCE" >/dev/null
cp "$SOURCE" "$TARGET"
launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
launchctl bootstrap "$DOMAIN" "$TARGET"
launchctl enable "$DOMAIN/$LABEL"
echo "V2.2盘中影子任务已安装；只在已验证交易日和配置检查点运行。"
