import copy
import json
import tempfile
import unittest
from datetime import datetime, date
from pathlib import Path
from unittest.mock import patch

from close_sentiment import update_close_sentiment
from intraday_structure import CN
from stage_fallback import refresh_close_structure


class CloseSentimentTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 11, 20, tzinfo=CN)
        self.payload = {"trade_date": "2026-10-09", "timestamp": "2026-10-09T16:00:00+08:00",
                        "analysis_time": "original", "review": {"summary": "original"}, "closing_auction_patch": {},
                        "index": {"a_share_indices": [{"code": str(i), "change_pct": v} for i, v in enumerate([.05,.17,.22,.07,.16])]},
                        "market_breadth": {"effective_limit_up_count":69,"limit_down_count":8,"broken_board_count":14,
                                           "up5_count":325,"valid_a_share_count":5562,"total_count":5562},
                        "sentiment_indicator": {}}

    def test_historical_recalculation_preserves_authored_judgement_and_archives(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            before = copy.deepcopy(self.payload)
            update_close_sentiment(root, self.payload, self.now)
            score = self.payload["sentiment_indicator"]
            self.assertEqual(score["score"], 86.21)
            self.assertTrue(score["historical_backfill"])
            self.assertIn("历史补算", score["display_note"])
            for key in ("review", "analysis_time", "timestamp"):
                self.assertEqual(before[key], self.payload[key])
            self.assertTrue((root / score["history_record"]).exists())
            update_close_sentiment(root, self.payload, self.now)
            self.assertEqual(len(list((root / "data/history/sentiment").rglob("*.json"))), 1)

    def test_missing_never_creates_numeric_score_or_complete_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.payload["market_breadth"]["up5_count"] = None
            update_close_sentiment(root, self.payload, self.now)
            self.assertIsNone(self.payload["sentiment_indicator"]["score"])
            self.assertFalse((root / "data/history/sentiment").exists())

    def test_close_retry_transfers_new_fields_and_preserves_original_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data/postmarket.json").write_text(json.dumps(self.payload))
            row = {"as_of": "2026-10-09T15:30:00+08:00", "source_name": "verified", "up5_count":325,
                   "advance_count":3296,"decline_count":2145,"flat_count":121,"total_count":5562,
                   "missing_quote_count":10,"valid_a_share_count":5562,"scope":"全A有效报价",
                   "strong_5pct_rule":"source_change_pct > 5.0","close_detail_archive":"data/archive.json"}
            facts = {"collected_at":self.now.isoformat(),"breadth":row,"pools":{},"errors":{}}
            with patch("stage_fallback.postmarket_complete", return_value=True), patch("stage_fallback.collect_structure", return_value=facts):
                self.assertTrue(refresh_close_structure(root,self.now,force=True,trade_date=date(2026,10,9)))
            after = json.loads((root / "data/postmarket.json").read_text())
            self.assertEqual(after["sentiment_indicator"]["score"],86.21)
            self.assertEqual(after["review"],self.payload["review"])
            self.assertEqual(after["analysis_time"],self.payload["analysis_time"])


if __name__ == "__main__":
    unittest.main()
