#!/bin/zsh
set -euo pipefail

SOURCE_ROOT="${STOCK_DASHBOARD_V2_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
RUNTIME_ROOT="${STOCK_DASHBOARD_V2_RUNTIME:-$HOME/stock-dashboard-v2-local}"
SEED_DATA="${1:-}"

mkdir -p "$RUNTIME_ROOT" "$RUNTIME_ROOT/logs"

for directory in config scripts v2_platform; do
  rsync -a --delete "$SOURCE_ROOT/$directory/" "$RUNTIME_ROOT/$directory/"
done

for file in server.py v2.html v2.css v2.js v2-trading.html v2-premarket.html v2-radar.html v2-midday.html v2-postmarket.html v2-evening.html v2-market.html v2-research.html v2-stock-pool.html v2-review.html v2-system.html v2-governance.html v2-logic.html; do
  if [[ -f "$SOURCE_ROOT/$file" ]]; then
    cp "$SOURCE_ROOT/$file" "$RUNTIME_ROOT/$file"
  fi
done

if [[ "$SEED_DATA" == "--seed-data" ]]; then
  rsync -a "$SOURCE_ROOT/data/" "$RUNTIME_ROOT/data/"
  rsync -a "$SOURCE_ROOT/local_inputs/" "$RUNTIME_ROOT/local_inputs/"
fi

python3 - "$SOURCE_ROOT" "$RUNTIME_ROOT" <<'PY'
import hashlib, json, sys
from datetime import datetime, timezone
from pathlib import Path

source, runtime = map(Path, sys.argv[1:])
paths = [
    "scripts/run_v22_intraday_shadow.py",
    "scripts/run_v22_evening_sentiment.py",
    "scripts/collect_v2_representative_quotes.py",
    "v2_platform/intraday_shadow.py",
    "v2_platform/evening_sentiment.py",
    "v2_platform/market_fact_collector.py",
    "v2_platform/futu_quote_provider.py",
    "v2_platform/quote_consistency.py",
    "v2_platform/representative_quote_collector.py",
    "v2_platform/sentiment_collector.py",
    "config/v2-intraday-shadow.json",
    "config/v2-evening-sentiment.json",
    "config/v2-evening-verified-events.json",
    "config/v2-quote-consistency.json",
    "config/v2-v22-feature-flags.json",
]
files = []
for relative in paths:
    source_path = source / relative
    runtime_path = runtime / relative
    files.append({
        "path": relative,
        "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "runtime_sha256": hashlib.sha256(runtime_path.read_bytes()).hexdigest(),
    })
payload = {
    "schema_version": 1,
    "deployed_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    "source_root": str(source),
    "runtime_root": str(runtime),
    "files": files,
    "all_hashes_equal": all(item["source_sha256"] == item["runtime_sha256"] for item in files),
    "guardrails": {
        "v1_modified": False,
        "user_asset_store_copied": False,
        "automatic_trading": False,
        "model_promoted": False,
    },
}
(runtime / "data/v2/v22").mkdir(parents=True, exist_ok=True)
(runtime / "data/v2/v22/runtime-deployment.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"all_hashes_equal": payload["all_hashes_equal"], "runtime_root": str(runtime)}, ensure_ascii=False))
PY
