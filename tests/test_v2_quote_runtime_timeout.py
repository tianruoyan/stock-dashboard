from __future__ import annotations

import json
import subprocess
import unittest
from unittest.mock import patch

from scripts.collect_v2_representative_quotes import fetch_futu_quotes_bounded


class RepresentativeQuoteRuntimeTimeoutTests(unittest.TestCase):
    @patch("scripts.collect_v2_representative_quotes.subprocess.run")
    def test_futu_worker_result_is_returned(self, run) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({"sh600000": {"close": 10.0}}),
            stderr="",
        )
        payload = fetch_futu_quotes_bounded(["sh600000"], host="127.0.0.1", port=11111, timeout_seconds=9)
        self.assertEqual(payload["sh600000"]["close"], 10.0)
        self.assertEqual(run.call_args.kwargs["timeout"], 9)

    @patch("scripts.collect_v2_representative_quotes.subprocess.run")
    def test_futu_worker_timeout_becomes_explicit_source_error(self, run) -> None:
        run.side_effect = subprocess.TimeoutExpired(cmd=["worker"], timeout=7)
        with self.assertRaisesRegex(RuntimeError, "futu_quote_timeout:7s"):
            fetch_futu_quotes_bounded(["sh600000"], host="127.0.0.1", port=11111, timeout_seconds=7)


if __name__ == "__main__":
    unittest.main()
