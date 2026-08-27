#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_platform.learning import as_list, load_json, write_json


ALERT_PATH = ROOT / "data" / "alert.json"
BACKUP_PATH = ROOT / "data" / "v2" / "migrations" / "p01-alert-semantics" / "before" / "alert.json"
AUDIT_PATH = ROOT / "data" / "v2" / "p01-alert-semantics-audit.json"


def main() -> int:
    payload = load_json(ALERT_PATH)
    if not payload:
        print("p0.1-alert-semantics: alert.json missing or invalid")
        return 1
    if not BACKUP_PATH.exists():
        write_json(BACKUP_PATH, payload)

    audit = {
        "schema_version": 1,
        "alerts_scanned": 0,
        "theme_metrics_migrated": 0,
        "sector_metrics_migrated": 0,
        "leader_change_fields_removed": 0,
        "ambiguous_scores_removed": 0,
        "leader_factor_lists_migrated": 0,
        "theme_metrics_current": 0,
        "legacy_leader_fields_remaining": 0,
        "backup": str(BACKUP_PATH.relative_to(ROOT)),
    }
    root_quote = payload.get("quote_audit") if isinstance(payload.get("quote_audit"), dict) else {}
    pct_field = str(root_quote.get("pct_field") or "")
    is_group_metric = bool(re.search(r"底池|题材|板块", pct_field))

    for alert in as_list(payload.get("alerts")):
        if not isinstance(alert, dict):
            continue
        audit["alerts_scanned"] += 1
        leaders = [item for item in as_list(alert.get("leaders")) if isinstance(item, dict)]
        legacy_values = [float(item["change_pct"]) for item in leaders if isinstance(item.get("change_pct"), (int, float))]
        alert_text = " ".join(
            str(value)
            for value in (
                pct_field,
                alert.get("reason"),
                alert.get("trigger"),
                alert.get("summary"),
                *as_list(alert.get("trigger_context")),
            )
            if value
        )
        window_match = re.search(r"(\d+)\s*分钟", alert_text)
        if is_group_metric and legacy_values and len({round(value, 6) for value in legacy_values}) == 1:
            alert["trigger_metrics"] = {
                "metric_scope": "theme_pool",
                "scope_label": "题材/底池",
                "window": f"{window_match.group(1)}m" if window_match else None,
                "change_pct": legacy_values[0],
                "as_of": root_quote.get("quote_time"),
                "source_label": "盘中异动监测记录",
            }
            audit["theme_metrics_migrated"] += 1
        elif not isinstance(alert.get("trigger_metrics"), dict):
            alert["trigger_metrics"] = {
                "metric_scope": "sector",
                "scope_label": "板块",
                "window": f"{window_match.group(1)}m" if window_match else None,
                "change_pct": None,
                "as_of": root_quote.get("quote_time"),
                "source_label": "盘中异动监测记录",
            }
            audit["sector_metrics_migrated"] += 1

        trigger_context = [str(value) for value in as_list(alert.get("trigger_context")) if value]
        for leader in leaders:
            if "change_pct" in leader:
                leader.pop("change_pct", None)
                audit["leader_change_fields_removed"] += 1
            if "score" in leader:
                leader.pop("score", None)
                audit["ambiguous_scores_removed"] += 1
            factors = [str(value) for value in as_list(leader.pop("factors", [])) if value]
            if factors:
                audit["leader_factor_lists_migrated"] += 1
            trigger_context.extend(value for value in factors if not value.startswith("领跌贡献"))
            leader["role"] = "同步领跌样本"
            leader["basis"] = "盘中异动记录列为同步领跌样本；个股涨跌幅由独立行情源提供。"
        alert["trigger_context"] = list(dict.fromkeys(trigger_context))
        if (
            isinstance(alert.get("trigger_metrics"), dict)
            and alert["trigger_metrics"].get("metric_scope") in {"theme_pool", "sector"}
        ):
            audit["theme_metrics_current"] += 1
        audit["legacy_leader_fields_remaining"] += sum(
            1 for leader in leaders if any(key in leader for key in ("change_pct", "score", "factors"))
        )

    sanity = root_quote.get("sanity_checks") if isinstance(root_quote.get("sanity_checks"), dict) else {}
    if "max_abs_leader_change_pct" in root_quote:
        root_quote["max_abs_trigger_change_pct"] = root_quote.pop("max_abs_leader_change_pct")
    if "max_abs_leader_change_pct" in sanity:
        sanity["max_abs_trigger_change_pct"] = sanity.pop("max_abs_leader_change_pct")
    has_group_metrics = any(
        isinstance(alert, dict)
        and isinstance(alert.get("trigger_metrics"), dict)
        and alert["trigger_metrics"].get("metric_scope") in {"theme_pool", "sector"}
        for alert in as_list(payload.get("alerts"))
    )
    root_quote["metric_scope"] = "theme_pool" if is_group_metric else ("sector" if has_group_metrics else root_quote.get("metric_scope"))
    payload["schema_version"] = max(int(payload.get("schema_version") or 1), 2)
    payload["semantic_migration"] = {
        "version": "p0.1-theme-metric-2",
        "rule": "题材/板块触发指标只保存在alert.trigger_metrics；缺少可核验数值时保留为空，不再写入leaders或冒充个股涨跌幅。",
    }
    write_json(ALERT_PATH, payload)
    write_json(AUDIT_PATH, audit)
    print(
        "p0.1-alert-semantics: "
        f"alerts={audit['alerts_scanned']} theme_metrics={audit['theme_metrics_migrated']} "
        f"sector_metrics={audit['sector_metrics_migrated']} "
        f"leader_pct_removed={audit['leader_change_fields_removed']} scores_removed={audit['ambiguous_scores_removed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
