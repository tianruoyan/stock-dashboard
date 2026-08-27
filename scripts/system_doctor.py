#!/usr/bin/env python3
"""Read-only operational health check for the V1 production and V2 shadow runtimes."""
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
V2_SOURCE = Path.home() / "Documents" / "投资" / "worktrees" / "stock-dashboard-v2"
V2_RUNTIME = Path.home() / "stock-dashboard-v2-local"
STATUS_PATH = ROOT / "logs" / "system-doctor.json"
USER_DOMAIN = f"gui/{subprocess.check_output(['/usr/bin/id', '-u'], text=True).strip()}"


@dataclass
class Check:
    name: str
    status: str
    detail: str


def port_ready(port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def fetch_json(url: str, timeout: float = 3.0) -> dict:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def job_loaded(label: str) -> bool:
    result = subprocess.run(
        ["/bin/launchctl", "print", f"{USER_DOMAIN}/{label}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def git_clean(path: Path) -> tuple[bool, str]:
    result = subprocess.run(
        ["/usr/bin/git", "-C", str(path), "status", "--porcelain"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return False, "not a readable Git worktree"
    rows = [row for row in result.stdout.splitlines() if row.strip()]
    return not rows, "clean" if not rows else f"{len(rows)} uncommitted paths"


def capture(name: str, severity: str, probe: Callable[[], bool], ok: str, failed: str) -> Check:
    try:
        passed = probe()
    except Exception as exc:
        return Check(name, severity, f"{failed}: {type(exc).__name__}: {exc}")
    return Check(name, "ok" if passed else severity, ok if passed else failed)


def run_checks() -> list[Check]:
    checks = [
        capture("V1 production health", "critical", lambda: fetch_json("http://127.0.0.1:8877/_health").get("status") == "ok", "127.0.0.1:8877 healthy", "V1 health endpoint unavailable"),
        capture("V2 shadow health", "warning", lambda: fetch_json("http://127.0.0.1:8878/_health").get("status") == "ok", "127.0.0.1:8878 healthy", "V2 shadow health endpoint unavailable"),
        capture("Retired port 8765", "critical", lambda: not port_ready(8765), "no listener", "legacy listener is still active"),
        capture("Legacy 8765 job", "critical", lambda: not job_loaded("com.sweetorange.investment-dashboard"), "unloaded", "legacy job is still loaded"),
        capture("THS periodic sync", "critical", lambda: not job_loaded("com.stock-dashboard.ths-watchlist"), "disabled", "protected periodic sync is loaded"),
        capture("Codex login launcher", "warning", lambda: not job_loaded("com.stock-dashboard.codex-runtime"), "disabled; Codex is on-demand", "login launcher is still loaded"),
        capture("Log maintenance", "warning", lambda: job_loaded("com.stock-dashboard.log-maintenance"), "loaded", "log maintenance job is not loaded"),
        capture("Alert verifier lock isolation", "critical", lambda: '.alert-quote-verify.lock' in (ROOT / "scripts" / "verify_alert_quotes.py").read_text(encoding="utf-8"), "dedicated lock configured", "alert verifier still shares the monitor bridge lock"),
        capture("Futu OpenD optional endpoint", "warning", lambda: port_ready(11111), "127.0.0.1:11111 ready", "unavailable; quote verification remains degraded without promotion"),
    ]

    for label in (
        "com.tianruoyan.stock-dashboard.local",
        "com.stock-dashboard.local-health",
        "com.stock-dashboard.intraday-data",
        "com.stock-dashboard.intraday-recovery",
        "com.stock-dashboard.monitor-signal-bridge",
        "com.stock-dashboard.alert-quote-verifier",
        "com.stock-dashboard.publisher",
    ):
        checks.append(capture(f"LaunchAgent {label}", "critical", lambda label=label: job_loaded(label), "loaded", "not loaded"))

    clean, detail = git_clean(ROOT)
    checks.append(Check("V1 Git baseline", "ok" if clean else "warning", detail))
    clean, detail = git_clean(V2_SOURCE)
    checks.append(Check("V2 shadow Git baseline", "ok" if clean else "warning", detail))

    large_logs = []
    for directory in (ROOT / "logs", V2_RUNTIME / "logs"):
        for path in directory.glob("*.log"):
            if path.stat().st_size > 8 * 1024 * 1024:
                large_logs.append(f"{path.name}:{path.stat().st_size // (1024 * 1024)}MB")
    checks.append(Check("Runtime log bounds", "warning" if large_logs else "ok", ", ".join(large_logs) if large_logs else "all active logs <= 8MB"))
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description="检查AI投资决策系统本机运行状态")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    checks = run_checks()
    counts = {status: sum(item.status == status for item in checks) for status in ("ok", "warning", "critical")}
    report = {
        "checked_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "status": "critical" if counts["critical"] else ("warning" if counts["warning"] else "ok"),
        "counts": counts,
        "checks": [asdict(item) for item in checks],
    }
    if not args.no_write:
        STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = STATUS_PATH.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(STATUS_PATH)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"system doctor: {report['status']} (ok={counts['ok']}, warning={counts['warning']}, critical={counts['critical']})")
        for item in checks:
            if item.status != "ok":
                print(f"- {item.status}: {item.name}: {item.detail}")
    return 1 if counts["critical"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
