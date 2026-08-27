from __future__ import annotations

import json
import plistlib
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from v2_platform.evening_sentiment import EveningNetworkUnavailable, EveningSentimentRunner


ROOT = Path(__file__).resolve().parents[1]
CHINA = ZoneInfo("Asia/Shanghai")
NEW_YORK = ZoneInfo("America/New_York")


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class FakeEveningRunner(EveningSentimentRunner):
    fail_announcements = False
    quote_time = "2026-07-28 10:35:00"

    def _collect_announcements(self, target):
        if self.fail_announcements:
            raise EveningNetworkUnavailable("test_network_down")
        row = {
            "announcement_id": "test-1",
            "code": "601138",
            "name": "工业富联",
            "title": "工业富联拟回购股份",
            "announcement_time": "2026-07-28T20:30:00+08:00",
            "source": "https://example.test/announcement.pdf",
        }
        return [row], {
            "source": "测试公告源",
            "pages": 1,
            "retrieved_records": 1,
            "api_reported_total": 1,
            "watchlist_match_count": 1,
            "important_match_count": 1,
        }

    def _collect_us_quotes(self):
        market_time = datetime.strptime(self.quote_time, "%Y-%m-%d %H:%M:%S").replace(tzinfo=NEW_YORK)
        return [{
            "symbol": "MU",
            "name": "美光科技",
            "price": 820.0,
            "previous_close": 900.0,
            "change_pct": -8.89,
            "quote_time_raw": self.quote_time,
            "market_time": market_time.isoformat(timespec="seconds"),
            "beijing_time": market_time.astimezone(CHINA).isoformat(timespec="seconds"),
            "collected_at": self.now.isoformat(timespec="seconds"),
            "source": "测试美股行情",
            "is_final_close": market_time.hour >= 16,
        }]


class FakeNoPositiveEveningRunner(FakeEveningRunner):
    def _collect_announcements(self, target):
        rows, meta = super()._collect_announcements(target)
        rows[0]["title"] = "工业富联关于董事会会议召开的公告"
        return rows, meta


class EveningSentimentTests(unittest.TestCase):
    def prepare(self, root: Path) -> None:
        for name in (
            "v2-market-calendar.json",
            "v2-evening-sentiment.json",
            "v2-representative-stock-codes.json",
        ):
            write(root / f"config/{name}", json.loads((ROOT / f"config/{name}").read_text(encoding="utf-8")))
        write(root / "config/v2-evening-verified-events.json", {"trade_date": "2026-07-28", "events": []})
        write(root / "data/v2/stock-pool.json", {
            "stocks": [{"code": "sh601138", "name": "工业富联"}],
        })
        write(root / "data/v2/v22/market-environment.json", {
            "trade_date": "2026-07-28",
            "as_of": "2026-07-28T15:30:00+08:00",
            "user_view": {"当前判断": "收盘风险仍高。", "抑制项": 4, "当前允许": "先防守。"},
            "sentiment_view": {
                "judgment": "亏钱效应明显。",
                "drivers": [{"evidence": "跌停数量较多。"}],
            },
        })

    def test_generates_current_trader_facing_evening_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            runner = FakeEveningRunner(root, now=datetime(2026, 7, 28, 22, 0, tzinfo=CHINA))
            report = runner.run(force=True)
            payload = json.loads((root / "data/evening-sentiment.json").read_text(encoding="utf-8"))
            cockpit = json.loads((root / "data/v2/v22/cockpit-phase-view.json").read_text(encoding="utf-8"))
            self.assertEqual(report["state"], "completed")
            self.assertEqual(payload["current_signal_date"], "2026-07-28")
            self.assertEqual(payload["coverage"]["us_market_session"]["status"], "intraday")
            self.assertIn("盘中快照", payload["summary"])
            self.assertIn("公司公告中有1条偏正面信息", payload["summary"])
            self.assertTrue(payload["coverage"]["recovery"]["enabled"])
            self.assertIn("工业富联", json.dumps(payload, ensure_ascii=False))
            self.assertEqual(cockpit["sessions"]["evening"]["availability"], "ready")
            for forbidden in ("user_note", "user_priority", "watchlist_source"):
                self.assertNotIn(forbidden, json.dumps(payload, ensure_ascii=False))

    def test_network_failure_preserves_last_valid_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            old = {"current_signal_date": "2026-07-27", "summary": "最近一次有效结果"}
            write(root / "data/evening-sentiment.json", old)
            before = (root / "data/evening-sentiment.json").read_bytes()
            runner = FakeEveningRunner(root, now=datetime(2026, 7, 28, 20, 5, tzinfo=CHINA))
            runner.fail_announcements = True
            report = runner.run(force=True)
            self.assertEqual(report["state"], "waiting_network")
            self.assertEqual(report["next_retry_seconds"], 300)
            self.assertEqual((root / "data/evening-sentiment.json").read_bytes(), before)

    def test_zero_positive_announcements_use_plain_chinese(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            runner = FakeNoPositiveEveningRunner(root, now=datetime(2026, 7, 28, 22, 0, tzinfo=CHINA))
            runner.run(force=True)
            payload = json.loads((root / "data/evening-sentiment.json").read_text(encoding="utf-8"))
            self.assertIn("公司公告暂未发现可直接支持板块交易的正向信息", payload["summary"])
            self.assertNotIn("有0条偏正面信息", payload["summary"])

    def test_no_reduction_commitment_is_not_misread_as_reduction_risk(self) -> None:
        item = {"name": "兆易创新", "title": "控股股东自愿承诺未来12个月不减持公司股份"}
        self.assertEqual(EveningSentimentRunner._generic_severity(item["title"]), "P1/正向观察")
        impact = EveningSentimentRunner._generic_impact(item)
        self.assertIn("个股偏正面", impact)
        self.assertNotIn("风险公告", impact)

    def test_recovery_succeeds_after_network_returns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            write(root / "data/evening-sentiment.json", {"current_signal_date": "2026-07-27"})
            runner = FakeEveningRunner(root, now=datetime(2026, 7, 28, 20, 5, tzinfo=CHINA))
            runner.fail_announcements = True
            self.assertEqual(runner.run(force=True)["state"], "waiting_network")
            runner.fail_announcements = False
            self.assertEqual(runner.run(force=True)["state"], "completed")
            payload = json.loads((root / "data/evening-sentiment.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["current_signal_date"], "2026-07-28")

    def test_next_morning_replaces_intraday_quote_with_final_close(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            evening_runner = FakeEveningRunner(root, now=datetime(2026, 7, 28, 22, 0, tzinfo=CHINA))
            evening_runner.run(force=True)
            morning_runner = FakeEveningRunner(root, now=datetime(2026, 7, 29, 10, 0, tzinfo=CHINA))
            morning_runner.quote_time = "2026-07-28 16:00:00"
            report = morning_runner.run()
            payload = json.loads((root / "data/evening-sentiment.json").read_text(encoding="utf-8"))
            self.assertEqual(report["state"], "completed")
            self.assertEqual(payload["current_signal_date"], "2026-07-28")
            self.assertEqual(payload["coverage"]["us_market_session"]["status"], "final_close")
            self.assertIn("隔夜美股收盘", payload["summary"])
            self.assertNotIn("美股正式收盘结果", payload["sentiment_summary"]["pending"])

    def test_launch_agent_runs_every_five_minutes_and_on_load(self) -> None:
        payload = plistlib.loads((ROOT / "scripts/com.stock-dashboard.v22-evening-sentiment.plist").read_bytes())
        self.assertEqual(payload["StartInterval"], 300)
        self.assertTrue(payload["RunAtLoad"])
        self.assertIn("run_v22_evening_sentiment.py", payload["ProgramArguments"][1])


if __name__ == "__main__":
    unittest.main()
