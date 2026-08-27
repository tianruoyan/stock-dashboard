#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from functools import partial
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_platform.learning import write_json
from v2_platform.learning import load_json
from v2_platform.futu_quote_provider import FutuQuoteProvider
from v2_platform.representative_quote_collector import V2RepresentativeQuoteCollector


def fetch_futu_quotes_bounded(
    codes: list[str],
    *,
    host: str,
    port: int,
    timeout_seconds: int = 25,
) -> dict[str, dict]:
    """Keep an unavailable OpenD gateway from stalling the whole dashboard build."""
    try:
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--futu-worker", host, str(port)],
            input=json.dumps(codes, ensure_ascii=False),
            text=True,
            capture_output=True,
            timeout=max(5, int(timeout_seconds)),
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"futu_quote_timeout:{max(5, int(timeout_seconds))}s") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "unknown_error").strip()
        raise RuntimeError(f"futu_quote_worker_failed:{detail[:180]}")
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("futu_quote_worker_invalid_response") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("futu_quote_worker_invalid_payload")
    return payload


def run_futu_worker() -> int:
    try:
        codes = json.loads(sys.stdin.read() or "[]")
        if not isinstance(codes, list):
            raise ValueError("codes_not_list")
        host = str(sys.argv[2]) if len(sys.argv) > 2 else "127.0.0.1"
        port = int(sys.argv[3]) if len(sys.argv) > 3 else 11111
        payload = FutuQuoteProvider(host=host, port=port).fetch_quotes([str(code) for code in codes])
        sys.stdout.write(json.dumps(payload, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f"{type(exc).__name__}:{str(exc)[:180]}", file=sys.stderr)
        return 1


def main() -> int:
    policy = load_json(ROOT / "config" / "v2-quote-consistency.json")
    secondary = None
    if policy.get("enabled") is True:
        source = policy.get("secondary_source") if isinstance(policy.get("secondary_source"), dict) else {}
        provider = FutuQuoteProvider(
            host=str(source.get("host") or "127.0.0.1"),
            port=int(source.get("port") or 11111),
        )
        secondary = partial(
            fetch_futu_quotes_bounded,
            host=provider.host,
            port=provider.port,
            timeout_seconds=int(source.get("timeout_seconds") or 25),
        )
    payload = V2RepresentativeQuoteCollector(
        ROOT,
        secondary_quote_fetcher=secondary,
        consistency_policy=policy.get("thresholds") if isinstance(policy.get("thresholds"), dict) else {},
    ).collect()
    if payload["quote_count"] < 3:
        print(json.dumps({"status": "failed", **payload}, ensure_ascii=False))
        return 1
    output = ROOT / "data" / "v2" / "inputs" / "representative-stock-quotes.json"
    write_json(output, payload)
    print(
        f"v2-representative-quotes: quotes={payload['quote_count']} "
        f"dual_confirmed={payload.get('dual_source_confirmed_count', 0)} "
        f"conflicts={payload.get('conflict_count', 0)} "
        f"missing={len(payload['missing'])} source={payload['source_id']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run_futu_worker() if "--futu-worker" in sys.argv else main())
