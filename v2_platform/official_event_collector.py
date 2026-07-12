from __future__ import annotations

import hashlib
import json
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from v2_platform.learning import as_list, load_json


def fetch_bytes(url: str, timeout: int = 25) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 V2Research/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except Exception as first_error:
        proc = subprocess.run(
            ["curl", "-L", "--fail", "--silent", "--show-error", "--max-time", str(timeout), url],
            capture_output=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"official_source_fetch_failed:{type(first_error).__name__}:{proc.stderr.decode(errors='ignore')[:160]}") from first_error
        return proc.stdout


class V2OfficialEventCollector:
    TYPE_MAP = {
        "official_policy": "official_policy",
        "official_plan_report": "official_policy",
        "official_definition": "official_policy",
        "official_industry": "official_policy",
        "official_research": "official_research",
        "official_energy_media": "mainstream_media",
    }

    def __init__(self, root: Path, *, fetcher: Callable[[str], bytes] = fetch_bytes) -> None:
        self.root = root.resolve()
        self.fetcher = fetcher
        self.templates = load_json(self.root / "config" / "v2-research-templates.json")

    def collect(self) -> dict[str, Any]:
        unique: dict[str, dict[str, Any]] = {}
        failures = []
        for template in as_list(self.templates.get("templates")):
            if not isinstance(template, dict):
                continue
            domain_id = str(template.get("domain_id") or "unknown")
            for source in as_list(template.get("source_refs")):
                if not isinstance(source, dict) or not source.get("url"):
                    continue
                url = str(source["url"])
                if url in unique:
                    unique[url]["domains"] = sorted(set([*unique[url]["domains"], domain_id]))
                    continue
                try:
                    raw = self.fetcher(url)
                except Exception as exc:
                    failures.append({"url": url, "title": source.get("title"), "reason": str(exc)})
                    continue
                if not raw:
                    failures.append({"url": url, "title": source.get("title"), "reason": "empty_response"})
                    continue
                published_at = source.get("published_at")
                try:
                    parsed = datetime.fromisoformat(str(published_at))
                    if parsed.tzinfo is None:
                        raise ValueError
                except ValueError:
                    failures.append({"url": url, "title": source.get("title"), "reason": "published_at_invalid"})
                    continue
                digest = hashlib.sha256(raw).hexdigest()
                host = urllib.parse.urlparse(url).hostname or "official-source"
                event_id = f"official_{hashlib.sha256(url.encode('utf-8')).hexdigest()[:20]}"
                unique[url] = {
                    "event_id": event_id,
                    "source_id": host,
                    "source_type": self.TYPE_MAP.get(str(source.get("type")), "official_policy"),
                    "published_at": published_at,
                    "observed_at": f"{source.get('retrieved_at')}T12:00:00+08:00",
                    "title": source.get("title"),
                    "url": url,
                    "content_hash": f"sha256:{digest}",
                    "content_hash_scope": "original_response_bytes",
                    "role": "fact_candidate",
                    "fact_state": "source_verified",
                    "domains": [domain_id],
                }
        return {
            "schema_version": 1,
            "events": sorted(unique.values(), key=lambda item: (item["published_at"], item["event_id"]), reverse=True),
            "collection_failures": failures,
            "collection_state": "usable" if unique and not failures else ("partial" if unique else "failed"),
        }
