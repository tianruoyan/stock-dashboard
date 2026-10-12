"""Deterministic tests: no network, real collection, publication or fixture edits."""
import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import build_automation_health as health
import build_topics as topics
import update_intraday_market as market
from intraday_recovery import TZ, assess_freshness, recover
from test_intraday_recovery import write_calendar


DAY = "2026-10-12"


def at(hhmm, day=DAY):
    return datetime.fromisoformat(f"{day}T{hhmm}:00+08:00")


def intraday(quote="14:58", analysis="14:30"):
    return {"timestamp": at(analysis).isoformat(), "analysis_time": at(analysis).isoformat(),
            "trade_date": DAY, "summary": "原始14:30分析",
            "market_data_as_of": at(quote).isoformat(),
            "indices": [{"code": "sh000001", "quote_time": at(quote).isoformat()}]}


class CloseCheckpointTests(unittest.TestCase):
    def test_1455_1458_do_not_count_as_1500_close(self):
        for quote, expected in [("14:55", False), ("14:58", False), ("15:00", True)]:
            with self.subTest(quote=quote):
                self.assertEqual(assess_freshness(intraday(quote), at("15:05")).fresh, expected)

    def test_midday_and_intraday_thresholds_are_unchanged(self):
        self.assertTrue(assess_freshness(intraday("14:55"), at("14:58")).fresh)
        self.assertTrue(assess_freshness(intraday("11:25"), at("12:00")).fresh)

    def test_newest_quote_cannot_conceal_preclose_missing_or_prior_day_quote(self):
        for stamp in [at("14:58").isoformat(), None, at("15:00", "2026-10-09").isoformat()]:
            data = intraday("15:00")
            data["indices"].append({"code": "sz399001", "quote_time": stamp})
            with self.subTest(stamp=stamp):
                self.assertFalse(assess_freshness(data, at("15:05")).fresh)

    def test_next_day_and_future_close_quotes_are_not_fresh(self):
        self.assertFalse(assess_freshness(intraday("15:00"), at("15:05", "2026-10-13")).fresh)
        self.assertFalse(assess_freshness(intraday("15:10"), at("15:05")).fresh)

    def test_offline_close_then_recovery_preserves_original_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_calendar(root)
            (root / "data").mkdir()
            path = root / "data/intraday.json"
            original = intraday()
            path.write_text(json.dumps(original))
            with patch("intraday_recovery.run_command", return_value=SimpleNamespace(returncode=1, stdout="offline", stderr="")):
                result = recover(root, at("15:05"), publish=False)
            self.assertEqual(result["state"], "网络或行情源待恢复")
            self.assertEqual(json.loads(path.read_text()), original)

            def update_only(command, cwd):
                self.assertTrue(command[0].endswith("update_intraday_market.py"))
                data = copy.deepcopy(original)
                data["indices"][0]["quote_time"] = at("15:00").isoformat()
                data["market_data_as_of"] = at("15:00").isoformat()
                path.write_text(json.dumps(data))
                return SimpleNamespace(returncode=0, stdout="ok", stderr="")

            with patch("intraday_recovery.run_command", side_effect=update_only) as runner:
                result = recover(root, at("15:07"), publish=False)
            self.assertEqual(runner.call_count, 1)
            self.assertEqual(result["state"], "已自动补充最新行情")
            data = json.loads(path.read_text())
            for key in ("timestamp", "analysis_time", "summary"):
                self.assertEqual(data[key], original[key])
            spec = next(spec for spec in health.EXPECTED if spec["id"] == "intraday")
            coverage = health.evidence_coverage(spec, data, at("15:07"), DAY)
            self.assertEqual(coverage["quote_coverage"]["status"], "ready")
            self.assertEqual(coverage["analysis_coverage"]["status"], "stale")

    def test_successful_but_preclose_response_keeps_retrying(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_calendar(root)
            (root / "data").mkdir()
            path = root / "data/intraday.json"
            path.write_text(json.dumps(intraday()))
            with patch("intraday_recovery.run_command", return_value=SimpleNamespace(returncode=0, stdout="ok", stderr="")):
                result = recover(root, at("15:05"), publish=False)
            self.assertEqual(result["state"], "网络或行情源待恢复")
            self.assertIn("15:00", result["detail"])
            self.assertTrue(result["next_retry_at"])

    def test_actual_quote_merge_never_retimes_same_day_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "intraday.json"
            original = intraday()
            path.write_text(json.dumps(original))
            rows = [{"name": "上证指数", "code": "sh000001", "value": 3000,
                     "change_pct": 1.0, "quote_time": at("15:00").isoformat(), "source": "fixture"}]
            with patch.object(market, "fetch_indices", return_value=rows), \
                 patch.object(market, "fetch_industries", return_value=[]), \
                 patch.object(market, "collect", return_value={"breadth": None, "pools": {}, "errors": {}}), \
                 patch.object(market, "apply_facts"), \
                 patch.object(market, "fetch_watchlist_quotes", return_value={}), \
                 patch.object(market, "WATCHLIST_QUOTES_PATH", root / "watchlist.json"), \
                 patch.object(market, "now_iso", return_value=at("15:07").isoformat()):
                market.update(path)
            result = json.loads(path.read_text())
            for key in ("timestamp", "analysis_time", "summary"):
                self.assertEqual(result[key], original[key])
            self.assertEqual(result["market_data_as_of"], at("15:00").isoformat())


class HealthCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.intraday = next(row for row in health.EXPECTED if row["id"] == "intraday")
        self.topics = next(row for row in health.EXPECTED if row["id"] == "topics")

    def row(self, spec, data, now, next_session=False):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / spec["file"]).write_text(json.dumps(data))
            with patch.object(health, "DATA_DIR", directory):
                return (health.next_session_row(spec, now, DAY) if next_session else
                        health.check_expected(spec, now, DAY, {}, {}))

    def test_quote_and_analysis_coverage_are_independent(self):
        for quote, analysis, quote_status, analysis_status in [
            ("14:55", "15:00", "stale", "ready"),
            ("14:58", "15:00", "stale", "ready"),
            ("15:00", "14:30", "ready", "stale"),
            ("15:00", "15:00", "ready", "ready"),
        ]:
            with self.subTest(quote=quote, analysis=analysis):
                row = self.row(self.intraday, intraday(quote, analysis), at("15:05"))
                self.assertEqual(row["quote_coverage"]["status"], quote_status)
                self.assertEqual(row["analysis_coverage"]["status"], analysis_status)
                self.assertEqual(row["status"], "ok" if quote_status == analysis_status == "ready" else "late")

    def test_fact_snapshot_with_new_analysis_time_is_not_research(self):
        data = intraday("15:00", "15:00")
        data["status"] = "partial_intraday_factual_snapshot"
        row = self.row(self.intraday, data, at("15:05"), next_session=True)
        self.assertEqual(row["quote_coverage"]["status"], "ready")
        self.assertEqual(row["analysis_coverage"]["status"], "missing")
        self.assertEqual(row["status"], "overdue")

    def research(self, updated="15:35"):
        return {"name": "真实专题", "updated_at": at(updated).isoformat(), "conclusion": "已有研究结论"}

    def test_topic_file_and_collection_timestamps_cannot_complete_research(self):
        item = self.research("14:30")
        item["representative_facts"] = {"updated_at": at("18:35").isoformat(),
            "source_as_of": at("15:00").isoformat(),
            "representatives": [{"code": "test", "quote_time": at("15:00").isoformat()}]}
        data = {"timestamp": at("18:35").isoformat(), "topics": [item]}
        row = self.row(self.topics, data, at("18:40"))
        self.assertEqual(row["research_coverage"]["status"], "missing")
        self.assertEqual(row["representative_coverage"]["status"], "available")
        self.assertEqual(row["status"], "late")
        self.assertEqual(row["failure_type"], "missing_topic_research")
        self.assertFalse(row["grace_is_producer"])

    def test_legacy_representative_only_is_never_research(self):
        item = self.research()
        item["update_scope"] = "closing_representatives_only"
        data = {"timestamp": at("15:35").isoformat(), "topics": [item]}
        row = self.row(self.topics, data, at("18:30"), next_session=True)
        self.assertEqual(row["research_coverage"]["status"], "missing")
        self.assertEqual(row["status"], "overdue")

    def test_1830_is_grace_deadline_not_second_producer(self):
        data = {"timestamp": at("15:10").isoformat(), "topics": [self.research("14:30")]}
        for now, expected in [("15:30", "waiting"), ("18:29", "waiting"), ("18:30", "late")]:
            with self.subTest(now=now):
                row = self.row(self.topics, data, at(now))
                self.assertEqual(row["status"], expected)
                self.assertEqual(row["research_coverage"]["status"], "missing")
                self.assertEqual(row["research_due"], "15:30")
                self.assertEqual(row["deadline"], at("18:30").isoformat())

    def test_every_topic_needs_actual_research_for_full_readiness(self):
        data = {"timestamp": at("15:35").isoformat(), "topics": [self.research(), self.research("14:30")]}
        row = self.row(self.topics, data, at("18:35"))
        self.assertEqual(row["research_coverage"]["status"], "partial")
        self.assertEqual(row["research_coverage"]["ready_count"], 1)
        data["topics"][1] = self.research()
        self.assertEqual(self.row(self.topics, data, at("18:35"))["status"], "ok")

    def test_next_day_file_cannot_refresh_old_topic_research(self):
        data = {"timestamp": at("15:35", "2026-10-13").isoformat(), "topics": [self.research()]}
        coverage = health.evidence_coverage(self.topics, data, at("18:35", "2026-10-13"), "2026-10-13")
        self.assertEqual(coverage["research_coverage"]["status"], "missing")


class RepresentativeProducerTests(unittest.TestCase):
    def setUp(self):
        self.name = "医药修复链"
        self.research = {"name": self.name, "status": "旧研究状态", "updated_at": at("15:40").isoformat(),
                         "conclusion": "原研究结论", "history": [{"conclusion": "更早研究"}]}

    def raw(self, codes):
        result = []
        for code, name in codes.items():
            fields = [""] * 40
            for index, value in {1: name, 3: "9.8", 4: "10", 33: "10.1", 32: "-2", 30: "20261012150000"}.items():
                fields[index] = value
            result.append({"query_code": code, "fields": fields})
        return result

    def run_producer(self, offline=False, next_day=False):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "topics.json"
            close = Path(tmp) / "postmarket.json"
            original = {"timestamp": at("15:40").isoformat(), "status": "authored_research", "topics": [self.research]}
            path.write_text(json.dumps(original))
            close.write_text(json.dumps({"timestamp": at("15:10").isoformat()}))
            fetch = (lambda codes: (_ for _ in ()).throw(OSError("offline"))) if offline else self.raw
            now = at("16:00", "2026-10-13") if next_day else at("16:00")
            with patch.object(topics, "TOPICS_PATH", path), patch.object(topics, "POSTMARKET_PATH", close), patch.object(topics, "fetch_quotes", side_effect=fetch) as runner:
                topics.main(now=now)
                first = path.read_bytes()
                if not offline:
                    runner.reset_mock()
                    topics.main(now=now + timedelta(minutes=5))
                    runner.assert_not_called()
                    self.assertEqual(path.read_bytes(), first)
            return original, json.loads(first)

    def test_representative_update_preserves_research_and_does_not_skip_newer_research(self):
        original, result = self.run_producer()
        updated = copy.deepcopy(result["topics"][0])
        facts = updated.pop("representative_facts")
        self.assertEqual(updated, original["topics"][0])
        for key in ("timestamp", "status"):
            self.assertEqual(result[key], original[key])
        self.assertEqual(facts["trade_date"], DAY)
        self.assertNotIn("conclusion", facts)
        self.assertEqual(result["representative_facts_updated_at"], at("16:00").isoformat())

    def test_offline_preserves_research_and_file(self):
        original, result = self.run_producer(offline=True)
        self.assertEqual(result, original)

    def test_late_collection_preserves_original_quote_and_research_dates(self):
        original, result = self.run_producer(next_day=True)
        self.assertEqual(result["timestamp"], original["timestamp"])
        self.assertEqual(result["representative_facts_trade_date"], DAY)
        self.assertTrue(result["representative_facts_updated_at"].startswith("2026-10-13"))
        facts = result["topics"][0]["representative_facts"]
        self.assertTrue(facts["source_as_of"].startswith(DAY))

    def test_concurrent_research_write_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "topics.json"
            close = Path(tmp) / "postmarket.json"
            path.write_text(json.dumps({"timestamp": at("14:30").isoformat(), "topics": [self.research]}))
            close.write_text(json.dumps({"timestamp": at("15:10").isoformat()}))

            def concurrent_update(codes):
                data = json.loads(path.read_text())
                data["topics"][0].update(conclusion="并发写入的真实研究", updated_at=at("16:00").isoformat())
                path.write_text(json.dumps(data))
                return self.raw(codes)

            with patch.object(topics, "TOPICS_PATH", path), patch.object(topics, "POSTMARKET_PATH", close), patch.object(topics, "fetch_quotes", side_effect=concurrent_update):
                topics.main(now=at("16:00"))
            item = json.loads(path.read_text())["topics"][0]
            self.assertEqual(item["conclusion"], "并发写入的真实研究")
            self.assertEqual(item["updated_at"], at("16:00").isoformat())
            self.assertIn("representative_facts", item)


if __name__ == "__main__":
    unittest.main()
