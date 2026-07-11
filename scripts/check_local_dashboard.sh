#!/bin/zsh
set -u

URL="http://127.0.0.1:8877/_health"
LABEL="com.tianruoyan.stock-dashboard.local"
DOMAIN="gui/$(id -u)"
ROOT="${0:A:h:h}"
EVENT_LOG="$ROOT/logs/local-health-events.log"
MAX_EVENT_LOG_BYTES=65536

log_failure() {
  local message="$1"
  local size=0

  if [[ -f "$EVENT_LOG" ]]; then
    size=$(/usr/bin/stat -f%z "$EVENT_LOG" 2>/dev/null || echo 0)
  fi
  if (( size >= MAX_EVENT_LOG_BYTES )); then
    /bin/mv -f "$EVENT_LOG" "$EVENT_LOG.1"
  fi
  /usr/bin/printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$message" >>"$EVENT_LOG"
}

if /usr/bin/curl -fsS --connect-timeout 2 --max-time 4 "$URL" >/dev/null 2>&1; then
  exit 0
fi

log_failure "local dashboard unhealthy; restarting"
if ! /bin/launchctl kickstart -k "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  log_failure "local dashboard restart failed"
  exit 1
fi
