#!/bin/zsh
set -u

ROOT="/Users/sweet_orange/stock-dashboard"
cd "$ROOT" || exit 1

python3 scripts/build_decision_feed.py >/dev/null 2>&1 || true
python3 scripts/audit_dashboard_data.py >/dev/null 2>&1 || true
python3 scripts/build_data_trust.py >/dev/null 2>&1 || true
python3 scripts/audit_dashboard_data.py
audit_status=$?
python3 scripts/build_data_trust.py >/dev/null 2>&1 || true
python3 scripts/build_section_health.py >/dev/null 2>&1 || true
python3 scripts/smoke_dashboard_static.py
smoke_status=$?
NODE_BIN="/Users/sweet_orange/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
if [ ! -x "$NODE_BIN" ]; then
  NODE_BIN="node"
fi
"$NODE_BIN" scripts/smoke_dashboard_runtime.js
runtime_status=$?

git add data/quality-report.json data/decision-feed.json data/data-trust.json data/section-health.json data/smoke-report.json data/runtime-smoke-report.json >/dev/null 2>&1 || true

if [ "$audit_status" -ne 0 ] || [ "$smoke_status" -ne 0 ] || [ "$runtime_status" -ne 0 ]; then
  echo "dashboard audit/smoke found critical issues; skip push"
  git commit -m "Update dashboard quality report" >/dev/null 2>&1 || true
  exit 1
fi

git add data config index.html style.css app.js RULES.md VERSION.md scripts settings.html settings.js rules.html topics >/dev/null 2>&1 || true

if ! git diff --cached --quiet; then
  git commit -m "Update dashboard data" >/dev/null 2>&1 || true
fi

git push 2>&1 || true
rm -f .push-now
