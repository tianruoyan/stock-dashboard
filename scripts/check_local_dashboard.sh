#!/bin/zsh
set -u

URL="http://127.0.0.1:8877/_health"
LABEL="com.tianruoyan.stock-dashboard.local"
DOMAIN="gui/$(id -u)"

if /usr/bin/curl -fsS --connect-timeout 2 --max-time 4 "$URL" >/dev/null; then
  exit 0
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') local dashboard unhealthy; restarting"
/bin/launchctl kickstart -k "$DOMAIN/$LABEL"
