#!/bin/zsh
set -u

ROOT="${STOCK_DASHBOARD_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
PYTHON_BIN="${PYTHON_BIN:-$HOME/.local/bin/python3}"
[ -x "$PYTHON_BIN" ] || PYTHON_BIN="/usr/bin/python3"
LOCK_DIR="$ROOT/.publish-lock"
PENDING_FILE="$ROOT/.publish-pending"
LEGACY_PENDING_FILE="$ROOT/.push-now"
STATUS_FILE="$ROOT/logs/publisher-status.json"
REMOTE="${PUBLISH_REMOTE:-origin}"
BRANCH="${PUBLISH_BRANCH:-main}"
MESSAGE="${PUBLISH_MESSAGE:-Update dashboard data}"
MAX_ATTEMPTS="${PUBLISH_MAX_ATTEMPTS:-3}"

mkdir -p "$ROOT/logs"
touch "$PENDING_FILE"

write_status() {
  local state="$1"
  local detail="$2"
  local attempts="${3:-0}"
  PUBLISH_STATE="$state" PUBLISH_DETAIL="$detail" PUBLISH_ATTEMPTS="$attempts" \
    PUBLISH_STATUS_FILE="$STATUS_FILE" "$PYTHON_BIN" - <<'PY'
import json
import os
from datetime import datetime, timezone
from pathlib import Path

path = Path(os.environ["PUBLISH_STATUS_FILE"])
payload = {
    "updated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    "state": os.environ["PUBLISH_STATE"],
    "detail": os.environ["PUBLISH_DETAIL"],
    "attempts": int(os.environ["PUBLISH_ATTEMPTS"]),
}
tmp = path.with_suffix(".json.tmp")
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
tmp.replace(path)
PY
}

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  write_status "waiting" "another publisher is running"
  exit 0
fi

cleanup() {
  /bin/rmdir "$LOCK_DIR" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

cd "$ROOT" || exit 1
write_status "building" "running dashboard audit and smoke checks"

"$PYTHON_BIN" scripts/build_dashboard_reports.py
build_status=$?
if [ "$build_status" -ne 0 ]; then
  write_status "blocked" "dashboard audit or smoke check failed"
  echo "dashboard audit/smoke found critical issues; publish remains pending"
  exit 1
fi

stage_paths=(.gitignore data config index.html style.css app.js RULES.md VERSION.md scripts settings.html settings.js rules.html topics THS_WATCHLIST_SYNC.md)
existing_paths=()
for stage_path in "${stage_paths[@]}"; do
  [ -e "$stage_path" ] && existing_paths+=("$stage_path")
done
git add -- "${existing_paths[@]}"

if ! git diff --cached --quiet; then
  git commit -m "$MESSAGE"
  commit_status=$?
  if [ "$commit_status" -ne 0 ]; then
    write_status "failed" "git commit failed"
    exit "$commit_status"
  fi
fi

if ! git remote get-url "$REMOTE" >/dev/null 2>&1; then
  rm -f "$PENDING_FILE" "$LEGACY_PENDING_FILE"
  write_status "local_only" "no git remote configured"
  exit 0
fi

write_status "syncing" "checking remote before push"
if git fetch "$REMOTE" "$BRANCH" >/dev/null 2>&1; then
  remote_ref="$REMOTE/$BRANCH"
  if git show-ref --verify --quiet "refs/remotes/$remote_ref"; then
    counts=$(git rev-list --left-right --count "HEAD...$remote_ref" 2>/dev/null || echo "0 0")
    ahead=$(echo "$counts" | awk '{print $1}')
    behind=$(echo "$counts" | awk '{print $2}')
    if [ "${behind:-0}" -gt 0 ]; then
      if ! git rebase "$remote_ref"; then
        git rebase --abort >/dev/null 2>&1 || true
        write_status "failed" "remote changed and automatic rebase conflicted"
        exit 1
      fi
    fi
  fi
fi

attempt=1
while [ "$attempt" -le "$MAX_ATTEMPTS" ]; do
  write_status "pushing" "push attempt $attempt of $MAX_ATTEMPTS" "$attempt"
  if git push "$REMOTE" "$BRANCH"; then
    rm -f "$PENDING_FILE" "$LEGACY_PENDING_FILE" .push-fails
    write_status "ok" "published to $REMOTE/$BRANCH" "$attempt"
    echo "dashboard publish ok"
    exit 0
  fi
  echo "$attempt" > .push-fails
  sleep $((attempt * 5))
  attempt=$((attempt + 1))
done

write_status "failed" "push failed after $MAX_ATTEMPTS attempts" "$MAX_ATTEMPTS"
echo "dashboard publish failed; retry marker retained"
exit 1
