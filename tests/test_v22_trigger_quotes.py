from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from v2_platform.v22_trigger_quotes import V22TriggerQuoteCapture


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def case_payload(*, maturity: str = "observe", judgment: str = "等待确认", quote_pct: float = 88.0, trade_date: str = "2026-07-17") -> dict:
    return {
        "case_batch_id": "batch1",
        "trade_date": trade_date,
        "built_at": f"{trade_date}T10:00:00+08:00",
        "cases": [{
            "case_id": "case1",
            "business_path": "theme_opportunity",
            "signal_state": "candidate",
            "maturity": maturity,
            "ended": False,
            "current_judgment": judgment,
            "trigger": "个股与板块共振",
            "risk_factors": ["板块回落"],
            "confirm_conditions": ["放量确认"],
            "invalidation_conditions": ["跌破支撑"],
            "last_evidence_at": f"{trade_date}T09:58:00+08:00",
            "representative_stocks": [{"name": "测试股份", "stock_code": "sh600000", "stock_change_pct": quote_pct, "role": "代表股"}],
            "environment_gate": {"g5_result": "neutral"},
        }],
    }


def quotes(*, quote_at: str = "2026-07-17T09:59:30+08:00") -> dict:
    return {
        "generated_at": "2026-07-17T10:00:01+08:00",
        "source_id": "real_quote_fixture",
        "source_label": "真实行情测试源",
        "quotes": [{
            "name": "测试股份", "code": "sh600000", "close": 11.0, "previous_close": 10.0,
            "stock_change_pct": 10.0, "stock_quote_as_of": quote_at,
            "stock_quote_source_id": "real_quote_fixture", "stock_quote_source": "真实行情测试源",
        }],
    }


class V22TriggerQuoteTests(unittest.TestCase):
    def test_same_state_is_idempotent_and_state_change_creates_new_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "data/v2/v22/decision-cases.json", case_payload())
            write(root / "data/v2/inputs/representative-stock-quotes.json", quotes())
            first, first_report = V22TriggerQuoteCapture(root).capture()
            second, second_report = V22TriggerQuoteCapture(root).capture()
            self.assertEqual(first_report["created_snapshot_count"], 1)
            self.assertEqual(second_report["created_snapshot_count"], 0)
            self.assertEqual(first["snapshot_count"], second["snapshot_count"])
            write(root / "data/v2/v22/decision-cases.json", case_payload(maturity="await_confirmation", judgment="加强观察"))
            third, third_report = V22TriggerQuoteCapture(root).capture()
            self.assertEqual(third_report["created_snapshot_count"], 1)
            self.assertEqual(third["snapshot_count"], 2)

    def test_quote_fields_not_theme_change_are_frozen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "data/v2/v22/decision-cases.json", case_payload(quote_pct=88.0))
            write(root / "data/v2/inputs/representative-stock-quotes.json", quotes())
            index, _ = V22TriggerQuoteCapture(root).capture()
            snapshot = json.loads((root / index["snapshots"][0]["relative_path"]).read_text())
            frozen = snapshot["representative_quotes"][0]
            self.assertEqual(frozen["trigger_price"], 11.0)
            self.assertEqual(frozen["stock_change_pct"], 10.0)
            self.assertNotEqual(frozen["stock_change_pct"], 88.0)

    def test_old_or_cross_date_quote_cannot_backfill_trigger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "data/v2/v22/decision-cases.json", case_payload())
            write(root / "data/v2/inputs/representative-stock-quotes.json", quotes(quote_at="2026-07-16T15:00:00+08:00"))
            index, report = V22TriggerQuoteCapture(root).capture()
            self.assertEqual(index["snapshot_count"], 0)
            self.assertEqual(report["hold_reasons"]["quote_trade_date_mismatch"], 1)
            self.assertFalse(index["guardrails"]["historical_quotes_backfilled"])

    def test_same_day_but_stale_quote_is_not_called_trigger_quote(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "data/v2/v22/decision-cases.json", case_payload())
            write(root / "data/v2/inputs/representative-stock-quotes.json", quotes(quote_at="2026-07-17T09:30:00+08:00"))
            index, report = V22TriggerQuoteCapture(root).capture()
            self.assertEqual(index["snapshot_count"], 0)
            self.assertEqual(report["hold_reasons"]["quote_not_near_first_observation"], 1)

    def test_same_state_can_be_observed_once_on_a_new_trade_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "data/v2/v22/decision-cases.json", case_payload())
            write(root / "data/v2/inputs/representative-stock-quotes.json", quotes())
            first, _ = V22TriggerQuoteCapture(root).capture()
            write(root / "data/v2/v22/decision-cases.json", case_payload(trade_date="2026-07-20"))
            write(root / "data/v2/inputs/representative-stock-quotes.json", quotes(quote_at="2026-07-20T09:59:30+08:00"))
            second, report = V22TriggerQuoteCapture(root).capture()
            self.assertEqual(first["snapshot_count"], 1)
            self.assertEqual(report["created_snapshot_count"], 1)
            self.assertEqual(second["snapshot_count"], 2)


if __name__ == "__main__":
    unittest.main()
