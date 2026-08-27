from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from v2_platform.decision_cases import V22DecisionCaseBuilder, humanize


ROOT = Path(__file__).resolve().parents[1]


class V22DecisionCaseTests(unittest.TestCase):
    def test_serialized_evidence_is_reduced_to_user_facing_fact(self) -> None:
        raw = 'type": "external_quote", "source": "行情源", "timestamp": "2026-07-30T20:00:00+08:00", "detail": "英伟达 -3.55%，价格190.01美元"'
        result = humanize(raw)
        self.assertEqual(result, "英伟达 -3.55%，价格190.01美元")
        for forbidden in ("type", "source", "timestamp", "detail"):
            self.assertNotIn(forbidden, result)

    def test_workspace_cases_are_shadow_deduplicated_and_separate_from_baseline(self) -> None:
        baseline_before = (ROOT / "data/v2/decision-system.json").read_bytes()
        payload, candidate = V22DecisionCaseBuilder(ROOT).write()
        self.assertEqual((ROOT / "data/v2/decision-system.json").read_bytes(), baseline_before)
        self.assertEqual(payload["mode"], "shadow_only")
        self.assertEqual(candidate["mode"], "shadow_only")
        self.assertEqual(payload["case_count"], len(payload["cases"]))
        self.assertEqual(payload["case_count"], len({item["case_id"] for item in payload["cases"]}))
        duplicate_count = sum(item["occurrence_count"] for item in payload["cases"]) - payload["case_count"]
        self.assertGreaterEqual(duplicate_count, 0)
        self.assertEqual(candidate["summary"]["deduplicated_occurrences"], duplicate_count)
        self.assertFalse(payload["guardrails"]["user_assets_modified"])
        self.assertFalse(payload["guardrails"]["automatic_trading"])

    def test_current_validation_history_and_unformed_clues_are_strictly_separated(self) -> None:
        payload, candidate = V22DecisionCaseBuilder(ROOT).build()
        groups = [set(payload[key]) for key in ("current_case_ids", "validation_case_ids", "unformed_clue_ids", "parked_clue_ids", "history_case_ids")]
        for index, group in enumerate(groups):
            for other in groups[index + 1:]:
                self.assertFalse(group & other)
        self.assertEqual(candidate["summary"]["decision_ready"], 0)
        self.assertGreaterEqual(candidate["summary"]["unformed_clues"], 0)
        self.assertGreater(candidate["summary"]["parked_clues"], 0)
        self.assertLess(candidate["summary"]["unformed_clues"], candidate["summary"]["parked_clues"])
        self.assertIn("不影响盘中", candidate["unformed_clue_summary"]["impact"])

    def test_repeated_build_keeps_same_case_batch_and_one_index_entry(self) -> None:
        first, _ = V22DecisionCaseBuilder(ROOT).write()
        second, _ = V22DecisionCaseBuilder(ROOT).write()
        self.assertEqual(first["case_batch_id"], second["case_batch_id"])
        self.assertEqual(first["immutable_hash"], second["immutable_hash"])
        index = json.loads((ROOT / "data/v2/v22/decision-case-snapshot-index.json").read_text(encoding="utf-8"))
        self.assertEqual(sum(item.get("case_batch_id") == first["case_batch_id"] for item in index["snapshots"]), 1)

    def test_no_private_user_fields_are_published(self) -> None:
        payload, candidate = V22DecisionCaseBuilder(ROOT).build()
        raw = json.dumps([payload, candidate], ensure_ascii=False)
        for forbidden in ("user_note", "user_priority", "user_intent", "watchlist_source", "source_account_id"):
            self.assertNotIn(forbidden, raw)

    def test_same_day_market_facts_create_read_only_observation_cases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def write(relative: str, payload: dict) -> None:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            write("data/v2/decision-system.json", {"data_quality_gate": {"state": "degraded"}})
            write("data/v2/v22/market-environment.json", {
                "trade_date": "2026-07-20", "as_of": "2026-07-20T10:00:00+08:00", "conclusion": "宽度偏弱",
                "action_constraint": "降低追高许可", "dimension_summary": {"suppress": 1, "risk_release": 0},
                "dimensions": [{"label": "市场宽度", "support_level": "suppress", "conclusion": "多数个股下跌", "as_of": "2026-07-20T10:00:00+08:00"}],
                "evidence_refs": [{"evidence_role": "risk", "representative_securities": [{"code": "sh600000", "name": "测试股份", "role": "风险代表"}]}],
            })
            write("data/v2/v22/environment-decision.json", {"g5_links": []})
            write("data/v2/inputs/mainline-structure.json", {
                "trade_date": "2026-07-20", "as_of": "2026-07-20T10:00:00+08:00", "source_name": "测试来源",
                "themes": [{"theme": "行业A", "state": "partial_support", "fact": "涨停2只", "conclusion": "等待宽度确认", "representative_securities": [{"code": "sh600000", "name": "测试股份", "role": "涨停代表"}]}],
                "counter_evidence": ["仅有涨停样本"], "missing_evidence": ["行业宽度"],
            })
            write("data/v2/inputs/representative-stock-quotes.json", {"quotes": [{
                "code": "sh600000", "name": "测试股份", "stock_change_pct": 3.0,
                "stock_quote_as_of": "2026-07-20T10:00:00+08:00", "stock_quote_source": "测试行情",
            }]})
            built_at = datetime(2026, 7, 20, 10, 1, tzinfo=timezone(timedelta(hours=8)))
            payload, _ = V22DecisionCaseBuilder(root, built_at=built_at).build()
            self.assertEqual(payload["case_count"], 2)
            self.assertTrue(all(item["user_assets_modified"] is False for item in payload["cases"]))
            self.assertTrue(all(item["representative_stocks"] for item in payload["cases"]))


if __name__ == "__main__":
    unittest.main()
