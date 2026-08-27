#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_platform.learning import V2LearningBuilder, as_list, load_json, write_json


DERIVED_FILES = (
    "replay-index.json",
    "signal-outcomes.json",
    "signal-review.json",
    "model-evaluation.json",
)


def counts(index: dict[str, Any], outcomes: dict[str, Any]) -> dict[str, int]:
    refs = [item for item in as_list(index.get("snapshots")) if isinstance(item, dict)]
    groups = {str(item.get("canonical_key") or item.get("decision_as_of") or "missing") for item in refs}
    return {
        "raw_snapshot_count": len(refs),
        "canonical_group_count": len(groups),
        "evaluation_snapshot_count": sum(item.get("evaluation_eligible") is True for item in refs),
        "excluded_variant_count": sum(item.get("evaluation_eligible") is False for item in refs),
        "outcome_signal_count": len(as_list(outcomes.get("signals"))),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="V2.1 P0 replay canonicalization migration")
    parser.add_argument("--apply", action="store_true", help="write migrated index and derived review data")
    args = parser.parse_args()
    data_dir = ROOT / "data" / "v2"
    builder = V2LearningBuilder(ROOT)
    before_index = load_json(data_dir / "replay-index.json")
    before_outcomes = load_json(data_dir / "signal-outcomes.json")
    refs = [item for item in as_list(before_index.get("snapshots")) if isinstance(item, dict)]
    preview_refs = builder._canonicalize_entries(refs)
    preview_index = {**before_index, "snapshots": preview_refs}
    preview_outcomes = builder._resolve_outcomes(preview_index)
    report = {
        "schema_version": 1,
        "mode": "apply" if args.apply else "dry_run",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "before": counts(before_index, before_outcomes),
        "after": counts(preview_index, preview_outcomes),
        "unresolved_groups": sorted({
            str(item.get("canonical_key"))
            for item in preview_refs
            if not item.get("canonical_snapshot_id")
        }),
        "original_snapshots_deleted": False,
    }
    if not args.apply:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = data_dir / "migrations" / stamp / "before"
    backup_dir.mkdir(parents=True, exist_ok=False)
    for name in DERIVED_FILES:
        source = data_dir / name
        if source.exists():
            shutil.copy2(source, backup_dir / name)
    index, outcomes, review = builder.migrate_existing()
    report["after"] = counts(index, outcomes)
    report["backup_dir"] = str(backup_dir.relative_to(ROOT))
    report["pending_signal_count"] = review.get("pending_signal_count")
    write_json(data_dir / "p0-migration-audit.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
