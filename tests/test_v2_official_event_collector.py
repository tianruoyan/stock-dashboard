from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from v2_platform.official_event_collector import V2OfficialEventCollector


ROOT = Path(__file__).resolve().parents[1]


class V2OfficialEventCollectorTests(unittest.TestCase):
    def test_sources_are_hashed_and_duplicate_urls_merge_domains(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            (root / "config/v2-research-templates.json").write_text((ROOT / "config/v2-research-templates.json").read_text(encoding="utf-8"), encoding="utf-8")
            report = V2OfficialEventCollector(root, fetcher=lambda url: f"content:{url}".encode()).collect()
            self.assertEqual(report["collection_state"], "usable")
            urls = [item["url"] for item in report["events"]]
            self.assertEqual(len(urls), len(set(urls)))
            self.assertTrue(all(item["content_hash"].startswith("sha256:") for item in report["events"]))
            shared = next(item for item in report["events"] if "453271" in item["url"])
            self.assertEqual(set(shared["domains"]), {"fusion", "quantum"})


if __name__ == "__main__":
    unittest.main()
