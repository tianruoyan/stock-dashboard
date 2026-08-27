#!/bin/sh

set -eu

host="${FUTU_OPEND_HOST:-127.0.0.1}"
port="${FUTU_OPEND_PORT:-11111}"
weekday=$(/bin/date +%u)
hhmm=$(/bin/date +%H%M)

if [ "$weekday" -gt 5 ] || [ "$hhmm" -lt 0830 ] || [ "$hhmm" -gt 1510 ]; then
  exit 0
fi

if /usr/bin/nc -z -w 1 "$host" "$port" >/dev/null 2>&1; then
  exit 0
fi

if /usr/bin/pgrep -f '/Futu_OpenD.app/Contents/MacOS/Futu_OpenD' >/dev/null 2>&1; then
  exit 0
fi

if [ ! -d /Applications/Futu_OpenD.app ]; then
  exit 0
fi

/usr/bin/open -j -g -a Futu_OpenD

# The GUI build may activate itself after LaunchServices starts it, even when
# open receives --hide/--background. Keep hiding it during startup until the
# API port is ready, or until this short startup window expires.
attempt=0
while [ "$attempt" -lt 30 ]; do
  if /usr/bin/nc -z -w 1 "$host" "$port" >/dev/null 2>&1; then
    exit 0
  fi
  attempt=$((attempt + 1))
  /bin/sleep 1
done

exit 0
