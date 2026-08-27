#!/bin/zsh
set -euo pipefail

ROOT="${STOCK_DASHBOARD_V2_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
LABEL="com.stock-dashboard.ai-hardware-monitor"
SOURCE="$ROOT/scripts/$LABEL.plist"
TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/logs"
zsh "$ROOT/scripts/deploy_ai_hardware_monitor_runtime.sh"
plutil -lint "$SOURCE" >/dev/null
cp "$SOURCE" "$TARGET"
launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
launchctl bootstrap "$DOMAIN" "$TARGET"
launchctl enable "$DOMAIN/$LABEL"
echo "AI硬件雷达服务已安装；固定检查点之外，将在盘中窗口每3分钟巡检一次触发条件。"
