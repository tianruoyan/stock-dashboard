import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
import refresh_evening_public as evening


class EveningRecoveryTests(unittest.TestCase):
    def test_outside_window_has_no_collection(self):
        self.assertEqual(evening.refresh(now=datetime.fromisoformat("2026-10-09T10:00:00+08:00"))["state"], "outside_window")

    def test_recent_failed_attempt_backs_off(self):
        now = datetime.fromisoformat("2026-10-09T20:00:00+08:00")
        with patch.object(evening, "read_json", return_value={"attempted_at":now.isoformat(), "state":"waiting_network"}):
            self.assertEqual(evening.refresh(now=now)["state"], "retry_backoff")

    def test_network_failure_preserves_previous_result(self):
        import sys
        sys.path.insert(0, str(evening.SHARED))
        from v2_platform.evening_sentiment import EveningSentimentRunner
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "data").mkdir()
            output = root / "data/evening-sentiment.json"
            output.write_text('{"summary":"previous"}')
            before = output.read_bytes()
            with patch.object(evening, "ROOT", root), patch.object(evening, "cn_calendar", return_value={"market":"CN","verification_state":"verified","valid_from":"2026-01-01","valid_to":"2026-12-31"}), patch.object(EveningSentimentRunner, "_collect_announcements", side_effect=OSError("offline")):
                report = evening.refresh(force=True, now=datetime.fromisoformat("2026-10-09T20:00:00+08:00"))
            self.assertEqual(report["state"], "waiting_network")
            self.assertEqual(output.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
