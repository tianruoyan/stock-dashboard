#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME = Path.home() / "stock-dashboard-v2-local"
FORBIDDEN_KEYS = {"user_note", "account_id", "source_account_id"}
FILES = (
    "data/intraday.json",
    "data/evening-sentiment.json",
    "data/v2/inputs/market-breadth.json",
    "data/v2/inputs/market-liquidity.json",
    "data/v2/inputs/mainline-structure.json",
    "data/v2/inputs/external-market.json",
    "data/v2/inputs/sentiment-structure.json",
    "data/v2/inputs/representative-stock-quotes.json",
    "data/v2/market-structure.json",
    "data/v2/decision-system.json",
    "data/v2/stock-pool.json",
    "data/v2/public-market-fact-health.json",
)
LOCAL_PUBLIC_INPUTS = (
    "market-breadth.json",
    "market-liquidity.json",
    "mainline-structure.json",
    "external-market.json",
    "microcap-observation.json",
    "sentiment-structure.json",
    "events.json",
)
V22_EXCLUDES = {
    "baseline-audit.json",
    "platform-skill-validation.json",
    "runtime-deployment.json",
    "runtime-import-report.json",
    "watchlist-migration-audit.json",
    "watchlist-three-way-summary.json",
}


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def forbidden_keys(value: Any, *, found: set[str] | None = None) -> set[str]:
    result = found if found is not None else set()
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key) in FORBIDDEN_KEYS:
                result.add(str(key))
            forbidden_keys(child, found=result)
    elif isinstance(value, list):
        for child in value:
            forbidden_keys(child, found=result)
    return result


def import_json(source: Path, target: Path) -> bool:
    payload = load(source)
    if not payload:
        return False
    blocked = forbidden_keys(payload)
    if blocked:
        raise ValueError(f"runtime_result_contains_private_keys:{','.join(sorted(blocked))}:{source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".runtime-import.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, target)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="将受治理的V2.2运行时公开结果合并回工作树。")
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    runtime = args.runtime.expanduser().resolve()
    deployment = load(runtime / "data/v2/v22/runtime-deployment.json")
    if deployment.get("all_hashes_equal") is not True or Path(str(deployment.get("runtime_root") or "")).resolve() != runtime:
        raise SystemExit("运行时来源没有通过部署指纹核验。")
    candidates = [relative for relative in FILES if (runtime / relative).exists()]
    candidates.extend(
        f"local_inputs/{filename}"
        for filename in LOCAL_PUBLIC_INPUTS
        if (runtime / "local_inputs" / filename).exists()
    )
    runtime_v22 = runtime / "data/v2/v22"
    if runtime_v22.exists():
        candidates.extend(
            str(path.relative_to(runtime))
            for path in runtime_v22.rglob("*.json")
            if path.name not in V22_EXCLUDES
        )
    candidates = sorted(set(candidates))
    imported = []
    for relative in candidates:
        source = runtime / relative
        payload = load(source)
        if not payload:
            continue
        blocked = forbidden_keys(payload)
        if blocked:
            raise SystemExit(f"运行时结果含私有字段，已阻断：{relative}")
        if not args.check and import_json(source, ROOT / relative):
            imported.append(relative)
    generated_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    report = {
        "schema_version": 1,
        "generated_at": generated_at,
        "mode": "check" if args.check else "governed_public_import",
        "runtime_root": str(runtime),
        "deployment_fingerprint_verified": True,
        "candidate_count": len(candidates),
        "imported_count": 0 if args.check else len(imported),
        "state": "ready" if args.check else "completed",
        "guardrails": {
            "v1_modified": False,
            "private_runtime_data_imported": False,
            "user_assets_modified": False,
            "automatic_trading": False,
            "model_promoted": False,
        },
    }
    if not args.check:
        output = ROOT / "data/v2/v22/runtime-import-report.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"state": report["state"], "candidate_count": len(candidates), "imported_count": report["imported_count"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
