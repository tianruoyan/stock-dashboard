#!/bin/zsh
set -euo pipefail

ROOT="${STOCK_DASHBOARD_V2_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
LABEL="com.stock-dashboard.v22-evening-sentiment"
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
echo "V2晚间舆情任务已安装；交易日晚间自动更新、次日凌晨回填美股收盘，断网或休眠恢复后自动补跑。"
