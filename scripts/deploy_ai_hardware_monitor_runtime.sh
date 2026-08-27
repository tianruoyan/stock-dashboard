#!/bin/zsh
set -euo pipefail

SOURCE_ROOT="${STOCK_DASHBOARD_V2_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
RUNTIME_ROOT="${STOCK_DASHBOARD_V2_RUNTIME:-$HOME/stock-dashboard-v2-local}"

mkdir -p "$RUNTIME_ROOT/ai_hardware_monitor" "$RUNTIME_ROOT/scripts" "$RUNTIME_ROOT/logs"
for directory in config engine dashboard; do
  rsync -a --delete "$SOURCE_ROOT/ai_hardware_monitor/$directory/" "$RUNTIME_ROOT/ai_hardware_monitor/$directory/"
done
cp "$SOURCE_ROOT/ai_hardware_monitor/__init__.py" "$RUNTIME_ROOT/ai_hardware_monitor/__init__.py"
cp "$SOURCE_ROOT/ai_hardware_monitor/README.md" "$RUNTIME_ROOT/ai_hardware_monitor/README.md"
cp "$SOURCE_ROOT/scripts/run_ai_hardware_monitor.py" "$RUNTIME_ROOT/scripts/run_ai_hardware_monitor.py"
cp "$SOURCE_ROOT/v2.html" "$RUNTIME_ROOT/v2.html"

mkdir -p "$RUNTIME_ROOT/ai_hardware_monitor/data"
for file in history.json signals.json status.json input-snapshot.json intraday-trigger-status.json intraday-trigger-signals.json; do
  if [[ -f "$SOURCE_ROOT/ai_hardware_monitor/data/$file" && ! -f "$RUNTIME_ROOT/ai_hardware_monitor/data/$file" ]]; then
    cp "$SOURCE_ROOT/ai_hardware_monitor/data/$file" "$RUNTIME_ROOT/ai_hardware_monitor/data/$file"
  fi
done

echo "AI硬件雷达已部署到本机V2运行目录。"
