from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from v2_platform.longbridge_analysis import (
    LongbridgeAnalysisImporter,
    acceptance_probe_payload,
    build_acceptance_report,
    content_hash,
)


ROOT = Path(__file__).resolve().parents[1]


class V22LongbridgeAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.importer = LongbridgeAnalysisImporter(ROOT, generated_at="2026-08-02T10:30:00+08:00")

    def test_complete_analysis_is_reference_only(self) -> None:
        evaluated = self.importer.evaluate_payload(acceptance_probe_payload())
        self.assertEqual(len(evaluated["accepted"]), 1)
        reference = evaluated["accepted"][0]
        self.assertEqual(reference["evidence_role"], "external_institutional_analysis_reference")
        self.assertEqual(reference["fact_state"], "provider_analysis_not_local_fact")
        self.assertTrue(reference["immutable_boundaries"])
        self.assertTrue(all(value is False for value in reference["immutable_boundaries"].values()))

    def test_reported_facts_and_trading_views_are_downgraded(self) -> None:
        reference = self.importer.evaluate_payload(acceptance_probe_payload())["accepted"][0]
        claims = {item["claim_type"]: item for item in reference["claims"]}
        self.assertEqual(claims["reported_fact"]["local_verification_status"], "pending_independent_verification")
        self.assertEqual(claims["reported_fact"]["normalized_role"], "fact_candidate_pending_local_verification")
        self.assertEqual(claims["trading_view"]["normalized_role"], "provider_view_non_actionable")
        self.assertFalse(claims["trading_view"]["action_permitted"])

    def test_trade_account_watchlist_and_user_asset_fields_are_rejected(self) -> None:
        for forbidden_key in ("order", "account", "positions", "watchlist", "user_note", "gate_override"):
            with self.subTest(forbidden_key=forbidden_key):
                payload = deepcopy(acceptance_probe_payload())
                payload["items"][0][forbidden_key] = {"test": True}
                evaluated = self.importer.evaluate_payload(payload)
                self.assertEqual(evaluated["accepted"], [])
                self.assertEqual(len(evaluated["rejected"]), 1)
                self.assertTrue(any("forbidden_input_keys" in item for item in evaluated["rejected"][0]["reason_codes"]))

    def test_missing_counter_evidence_or_invalidation_needs_review(self) -> None:
        payload = deepcopy(acceptance_probe_payload())
        payload["items"][0]["claims"] = [
            item for item in payload["items"][0]["claims"] if item["claim_type"] not in {"risk", "counter_view"}
        ]
        payload["items"][0]["invalidation_conditions"] = []
        evaluated = self.importer.evaluate_payload(payload)
        self.assertEqual(evaluated["accepted"], [])
        self.assertEqual(len(evaluated["review_queue"]), 1)
        reasons = evaluated["review_queue"][0]["reason_codes"]
        self.assertIn("counter_evidence_missing", reasons)
        self.assertIn("invalidation_conditions_missing", reasons)

    def test_non_longbridge_origin_is_rejected(self) -> None:
        payload = deepcopy(acceptance_probe_payload())
        payload["items"][0]["source_url"] = "https://example.com/not-longbridge"
        evaluated = self.importer.evaluate_payload(payload)
        self.assertEqual(evaluated["accepted"], [])
        self.assertIn("source_url_not_longbridge_official", evaluated["rejected"][0]["reason_codes"])

    def test_public_reference_never_contains_private_input_fields(self) -> None:
        payload = deepcopy(acceptance_probe_payload())
        payload["items"][0]["raw_prompt"] = "private prompt"
        payload["items"][0]["raw_response"] = "private response"
        evaluated = self.importer.evaluate_payload(payload)
        reference = evaluated["accepted"][0]
        serialized = json.dumps(reference, ensure_ascii=False)
        self.assertNotIn("raw_prompt", serialized)
        self.assertNotIn("raw_response", serialized)
        self.assertNotIn("private prompt", serialized)
        self.assertNotIn("private response", serialized)

    def test_invalid_import_preserves_last_valid_public_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir(parents=True)
            policy = json.loads((ROOT / "config/v2-longbridge-analysis-policy.json").read_text(encoding="utf-8"))
            policy["default_input"] = "local_inputs/longbridge-analysis.json"
            policy["public_output"] = "data/v2/v22/longbridge-analysis-references.json"
            policy["import_report"] = "data/v2/v22/longbridge-analysis-import-report.json"
            (root / "config/v2-longbridge-analysis-policy.json").write_text(json.dumps(policy), encoding="utf-8")
            input_path = root / "local_inputs/longbridge-analysis.json"
            input_path.parent.mkdir(parents=True)
            input_path.write_text(json.dumps(acceptance_probe_payload()), encoding="utf-8")
            importer = LongbridgeAnalysisImporter(root, generated_at="2026-08-02T10:30:00+08:00")
            report, artifact = importer.run()
            self.assertEqual(report["status"], "passed")
            output_path = root / policy["public_output"]
            before = content_hash(json.loads(output_path.read_text(encoding="utf-8")))

            invalid = deepcopy(acceptance_probe_payload())
            invalid["items"][0]["trade"] = {"side": "buy"}
            input_path.write_text(json.dumps(invalid), encoding="utf-8")
            report, preserved = importer.run()
            after = content_hash(json.loads(output_path.read_text(encoding="utf-8")))
            self.assertEqual(report["status"], "invalid")
            self.assertTrue(report["summary"]["last_valid_preserved"])
            self.assertEqual(before, after)
            self.assertEqual(preserved["immutable_hash"], artifact["immutable_hash"])

    def test_acceptance_report_passes_all_boundaries(self) -> None:
        report = build_acceptance_report(ROOT, generated_at="2026-08-02T10:30:00+08:00")
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["summary"]["failed"], 0)
        self.assertGreaterEqual(report["summary"]["passed"], 8)


if __name__ == "__main__":
    unittest.main()
