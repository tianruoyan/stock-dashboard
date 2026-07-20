#!/bin/zsh
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.stock-dashboard.alert-quote-verifier"
SOURCE="$ROOT/scripts/$LABEL.plist"
TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/logs"
cp "$SOURCE" "$TARGET"
chmod +x "$ROOT/scripts/run_alert_quote_verifier.sh" "$ROOT/scripts/verify_alert_quotes.py"
launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
launchctl bootstrap "$DOMAIN" "$TARGET"
launchctl enable "$DOMAIN/$LABEL"
launchctl kickstart -k "$DOMAIN/$LABEL"
echo "installed $LABEL"
