from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2_platform.environment_evidence import parse_datetime, trade_date_of
from v2_platform.learning import as_dict, load_json, write_json


OUTPUT = "data/v2/v22/time-semantics.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def first_trade_date(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and len(value) == 10:
            try:
                datetime.fromisoformat(value)
            except ValueError:
                continue
            return value
        parsed = trade_date_of(value)
        if parsed:
            return parsed
    return None


def timezone_aware(value: Any) -> bool:
    return parse_datetime(value) is not None


class V22TimeSemanticsBuilder:
    """Audit time meanings without rewriting any business or historical data."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.baseline = load_json(self.root / "data/v2/decision-system.json")
        self.environment = load_json(self.root / "data/v2/v22/market-environment.json")
        self.cases = load_json(self.root / "data/v2/v22/decision-cases.json")

    def build(self) -> dict[str, Any]:
        system = as_dict(self.baseline.get("system"))
        baseline_decision_at = system.get("decision_as_of")
        baseline_market_date = first_trade_date(
            system.get("market_date"),
            baseline_decision_at,
        )
        v22_market_date = first_trade_date(
            self.environment.get("trade_date"),
            self.cases.get("trade_date"),
        )
        case_evidence_at = self.cases.get("as_of")
        case_evidence_date = first_trade_date(case_evidence_at)
        same_market_date = bool(baseline_market_date and baseline_market_date == v22_market_date)
        case_evidence_aligned = bool(v22_market_date and case_evidence_date == v22_market_date)
        if not baseline_market_date or not v22_market_date:
            reason = "双轨一侧缺少可核验交易日，暂不比较结果。"
        elif not same_market_date:
            reason = f"V2证据属于{baseline_market_date}，V2.2市场事实属于{v22_market_date}；交易日未统一，暂不比较命中率。"
        elif not case_evidence_aligned:
            reason = "V2.2案例证据时间与市场事实交易日不一致，暂不比较结果。"
        else:
            reason = "两侧交易日期一致；仍须满足结果完整性和样本门槛后才能比较。"
        return {
            "schema_version": 1,
            "generated_at": now_iso(),
            "mode": "shadow_only",
            "field_definitions": {
                "market_date": "事实所属的交易日",
                "decision_as_of": "当时判断所依据的最新证据时间",
                "quote_time": "行情源给出的实际行情时间",
                "collected_at": "系统取得该数据的时间",
                "generated_at": "报告或投影生成时间",
            },
            "sources": {
                "v2_baseline": {
                    "market_date": baseline_market_date,
                    "decision_as_of": baseline_decision_at,
                    "latest_source_at": system.get("latest_source_at"),
                    "generated_at": system.get("generated_at"),
                    "timezone_aware": timezone_aware(baseline_decision_at),
                },
                "v22_market_environment": {
                    "market_date": v22_market_date,
                    "evidence_as_of": self.environment.get("as_of"),
                    "generated_at": self.environment.get("built_at") or self.environment.get("generated_at"),
                    "timezone_aware": timezone_aware(self.environment.get("as_of")),
                },
                "v22_decision_cases": {
                    "market_date": first_trade_date(self.cases.get("trade_date")),
                    "evidence_as_of": case_evidence_at,
                    "generated_at": self.cases.get("built_at"),
                    "evidence_date_aligned": case_evidence_aligned,
                    "timezone_aware": timezone_aware(case_evidence_at),
                },
            },
            "comparison": {
                "allowed": same_market_date and case_evidence_aligned,
                "same_market_date": same_market_date,
                "case_evidence_aligned": case_evidence_aligned,
                "reason": reason,
                "hit_rate_comparison_allowed": False,
            },
            "guardrails": {
                "mixed_trade_dates_compared": False,
                "generated_at_used_as_market_date": False,
                "historical_data_rewritten": False,
                "user_assets_modified": False,
            },
        }

    def write(self) -> dict[str, Any]:
        payload = self.build()
        write_json(self.root / OUTPUT, payload)
        return payload
