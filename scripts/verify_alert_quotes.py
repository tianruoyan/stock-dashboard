#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional


ROOT = Path(__file__).resolve().parents[1]
ALERT_PATH = ROOT / "data" / "alert.json"
WATCHLIST_PATH = ROOT / "config" / "watchlist.json"
SOURCE_HEALTH_PATH = ROOT / "data" / "source-health.json"
STATUS_PATH = ROOT / "logs" / "alert-quote-verifier-status.json"
PENDING_PATH = ROOT / ".publish-pending"
LOCK_PATH = ROOT / ".alert-quote-verify.lock"
TENCENT_MINUTE_URL = "https://web.ifzq.gtimg.cn/appstock/app/minute/query?code={}"
EASTMONEY_SEARCH_URL = "https://searchapi.eastmoney.com/api/suggest/get"
EASTMONEY_TOKEN = "D43BF722C8E33E1B5FBF8EF4C0C8ECBE"
TZ = timezone(timedelta(hours=8))
MAX_VERIFY_AGE_MINUTES = 10
MIN_SETTLE_SECONDS = 75


MinuteLoader = Callable[[str], List[Dict[str, Any]]]


def main() -> int:
    parser = argparse.ArgumentParser(description="用腾讯分钟行情复核当日新产生的 V1 盘中异动")
    parser.add_argument("--path", type=Path, default=ALERT_PATH)
    parser.add_argument("--watchlist", type=Path, default=WATCHLIST_PATH)
    parser.add_argument("--source-health", type=Path, default=SOURCE_HEALTH_PATH)
    parser.add_argument("--now", help="测试用当前时间，ISO 8601")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    now = parse_datetime(args.now) if args.now else datetime.now(TZ)
    if now is None:
        raise SystemExit("--now 必须是 ISO 8601 时间")

    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("w") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({"state": "skipped", "reason": "another_verifier_running"}, ensure_ascii=False))
            return 0
        result = run(
            args.path,
            args.watchlist,
            now.astimezone(TZ),
            args.dry_run,
            source_health_path=args.source_health,
        )
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result.get("state") == "failed" else 0


def run(
    path: Path,
    watchlist_path: Path,
    now: datetime,
    dry_run: bool = False,
    source_health_path: Path = SOURCE_HEALTH_PATH,
) -> Dict[str, Any]:
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        result = {"state": "failed", "reason": f"alert_read_failed: {exc}"}
        write_status(result)
        return result
    if not isinstance(payload, dict):
        result = {"state": "failed", "reason": "alert_payload_not_object"}
        write_status(result)
        return result

    alerts = payload.get("alerts")
    if not isinstance(alerts, list) or not alerts:
        result = {"state": "no_alerts", "verified": 0, "mismatched": 0, "pending": 0, "changed": False}
        write_status(result)
        return result

    identity_map = load_identity_map(watchlist_path)
    names = sorted({
        str(leader.get("name") or "").strip()
        for alert in alerts
        if isinstance(alert, dict) and alert_needs_live_quotes(alert, now)
        for leader in alert.get("leaders") or []
        if isinstance(leader, dict) and leader.get("name")
    })
    for name in names:
        if name not in identity_map:
            code = lookup_a_share_code(name)
            if code:
                identity_map[name] = code

    code_set = sorted({identity_map[name] for name in names if name in identity_map})
    minute_rows = fetch_many_minute_rows(code_set)
    before = canonical_json(payload)
    enriched = enrich_payload(payload, identity_map, lambda code: minute_rows.get(code, []), now)
    after = canonical_json(enriched)
    alert_changed = before != after
    source_health_update = prepare_source_health_update(source_health_path, enriched)
    source_health_changed = bool(source_health_update and source_health_update[2])
    changed = alert_changed or source_health_changed

    states = [str((item.get("quote_audit") or {}).get("secondary_verification", {}).get("state") or "unprocessed") for item in enriched.get("alerts") or [] if isinstance(item, dict)]
    result = {
        "state": "dry_run" if dry_run else "completed",
        "verified": states.count("passed"),
        "mismatched": states.count("mismatch"),
        "pending": sum(1 for state in states if state in {"pending", "unprocessed"}),
        "not_backfilled": states.count("too_late_no_backfill"),
        "changed": changed,
        "alert_changed": alert_changed,
        "source_health_changed": source_health_changed,
        "alert_count": len(alerts),
    }
    if not changed or dry_run:
        write_status(result)
        return result

    if alert_changed:
        current_raw = path.read_bytes()
        if hashlib.sha256(current_raw).digest() != hashlib.sha256(raw).digest():
            result.update({"state": "source_changed_retry", "changed": False})
            write_status(result)
            return result
        write_atomic(path, enriched)
    if source_health_changed and source_health_update:
        source_raw, source_payload, _ = source_health_update
        try:
            current_source_raw = source_health_path.read_bytes()
        except OSError:
            current_source_raw = b""
        if hashlib.sha256(current_source_raw).digest() == hashlib.sha256(source_raw).digest():
            write_atomic(source_health_path, source_payload)
        else:
            result["source_health_changed"] = False
    PENDING_PATH.touch()
    write_status(result)
    return result


def alert_needs_live_quotes(alert: Dict[str, Any], now: datetime) -> bool:
    fingerprint = alert_fingerprint(alert)
    audit = alert.get("quote_audit") if isinstance(alert.get("quote_audit"), dict) else {}
    previous = audit.get("secondary_verification") if isinstance(audit.get("secondary_verification"), dict) else {}
    if previous.get("fingerprint") == fingerprint and previous.get("state") in {"passed", "mismatch", "too_late_no_backfill", "different_trade_date", "insufficient_identity"}:
        return False
    event_at = parse_datetime(alert.get("time"))
    if event_at is None:
        return False
    event_at = event_at.astimezone(TZ)
    age = (now - event_at).total_seconds()
    return event_at.date() == now.date() and 0 <= age <= MAX_VERIFY_AGE_MINUTES * 60


def enrich_payload(
    payload: Dict[str, Any],
    identity_map: Dict[str, str],
    minute_loader: MinuteLoader,
    now: datetime,
) -> Dict[str, Any]:
    result = copy.deepcopy(payload)
    alerts = result.get("alerts") if isinstance(result.get("alerts"), list) else []
    for alert in alerts:
        if not isinstance(alert, dict):
            continue
        fingerprint = alert_fingerprint(alert)
        audit = alert.get("quote_audit") if isinstance(alert.get("quote_audit"), dict) else {}
        previous = audit.get("secondary_verification") if isinstance(audit.get("secondary_verification"), dict) else {}
        if previous.get("fingerprint") == fingerprint and previous.get("state") in {"passed", "mismatch", "too_late_no_backfill", "different_trade_date", "insufficient_identity"}:
            if previous.get("state") == "passed" and isinstance(audit.get("missing_confirmation"), str):
                audit["missing_confirmation"] = remove_cross_source_missing(audit["missing_confirmation"])
                alert["quote_audit"] = audit
            continue
        verification = verify_alert(alert, identity_map, minute_loader, now)
        verification["fingerprint"] = fingerprint
        audit.update({
            "provider": "本地盘中监控、腾讯分钟行情",
            "secondary_source": "腾讯分钟行情",
            "secondary_verification": verification,
        })
        sanity = audit.get("sanity_checks") if isinstance(audit.get("sanity_checks"), dict) else {}
        sanity["cross_source_verified"] = verification.get("state") == "passed"
        audit["sanity_checks"] = sanity
        if verification.get("state") == "passed" and isinstance(audit.get("missing_confirmation"), str):
            audit["missing_confirmation"] = remove_cross_source_missing(audit["missing_confirmation"])
        alert["quote_audit"] = audit

    result["quote_audit"] = aggregate_quote_audit(alerts, result.get("timestamp"))
    return result


def verify_alert(
    alert: Dict[str, Any],
    identity_map: Dict[str, str],
    minute_loader: MinuteLoader,
    now: datetime,
) -> Dict[str, Any]:
    event_at = parse_datetime(alert.get("time"))
    if event_at is None:
        return verification_result("pending", now, reason="异动时间无法解析，等待下一轮。")
    event_at = event_at.astimezone(TZ)
    if event_at.date() != now.date():
        return verification_result("different_trade_date", now, reason="只核验当日新异动，不反向补造历史证据。")
    age = (now - event_at).total_seconds()
    if age < 0:
        return verification_result("pending", now, reason="异动时间尚未到达。")
    if age > MAX_VERIFY_AGE_MINUTES * 60:
        return verification_result("too_late_no_backfill", now, reason="超过实时核验窗口，不事后补成已确认。")
    if age < MIN_SETTLE_SECONDS:
        return verification_result("pending", now, reason="等待触发分钟行情完整落盘。")

    audit = alert.get("quote_audit") if isinstance(alert.get("quote_audit"), dict) else {}
    window = parse_window_minutes(audit.get("pct_field"))
    rows = []
    for leader in alert.get("leaders") or []:
        if not isinstance(leader, dict):
            continue
        name = str(leader.get("name") or "").strip()
        code = identity_map.get(name)
        primary = as_float(leader.get("change_pct"))
        if not name or not code or primary is None:
            continue
        secondary = minute_change(minute_loader(code), event_at, window)
        if secondary is None:
            rows.append({"股票": name, "代码": display_code(code), "监控涨跌幅": primary, "腾讯涨跌幅": None, "方向一致": False, "幅度一致": False})
            continue
        direction_match = direction(primary) != 0 and direction(primary) == direction(secondary["change_pct"])
        tolerance = max(0.8, abs(primary) * 0.75)
        magnitude_match = abs(primary - secondary["change_pct"]) <= tolerance
        rows.append({
            "股票": name,
            "代码": display_code(code),
            "监控涨跌幅": round(primary, 4),
            "腾讯涨跌幅": secondary["change_pct"],
            "起始分钟": secondary["start_minute"],
            "结束分钟": secondary["end_minute"],
            "方向一致": direction_match,
            "幅度一致": magnitude_match,
        })

    comparable = [row for row in rows if row.get("腾讯涨跌幅") is not None]
    if len(comparable) < 2:
        return verification_result("insufficient_identity", now, reason="可解析且有分钟行情的代表股不足2只。", representatives=rows, window=window)
    direction_ratio = sum(bool(row["方向一致"]) for row in comparable) / len(comparable)
    magnitude_ratio = sum(bool(row["幅度一致"]) for row in comparable) / len(comparable)
    passed = direction_ratio >= 2 / 3 and magnitude_ratio >= 2 / 3
    return verification_result(
        "passed" if passed else "mismatch",
        now,
        reason="代表股方向与幅度达到双源一致要求。" if passed else "腾讯分钟行情与监控源的方向或幅度不一致，维持待确认/失效。",
        representatives=rows,
        window=window,
        direction_ratio=direction_ratio,
        magnitude_ratio=magnitude_ratio,
    )


def verification_result(
    state: str,
    now: datetime,
    reason: str,
    representatives: Optional[List[Dict[str, Any]]] = None,
    window: Optional[int] = None,
    direction_ratio: Optional[float] = None,
    magnitude_ratio: Optional[float] = None,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "state": state,
        "checked_at": now.astimezone(TZ).replace(microsecond=0).isoformat(),
        "source": "腾讯分钟行情",
        "reason": reason,
        "representatives": representatives or [],
    }
    if window is not None:
        result["window_minutes"] = window
    if direction_ratio is not None:
        result["direction_agreement_ratio"] = round(direction_ratio, 4)
    if magnitude_ratio is not None:
        result["magnitude_agreement_ratio"] = round(magnitude_ratio, 4)
    return result


def aggregate_quote_audit(alerts: List[Any], fallback_time: Any) -> Dict[str, Any]:
    valid_alerts = [item for item in alerts if isinstance(item, dict)]
    verifications = [
        (item.get("quote_audit") or {}).get("secondary_verification") or {}
        for item in valid_alerts
    ]
    cross_verified = bool(verifications) and all(item.get("state") == "passed" for item in verifications)
    max_move = max(
        [abs(as_float(leader.get("change_pct")) or 0.0) for item in valid_alerts for leader in item.get("leaders") or [] if isinstance(leader, dict)] or [0.0]
    )
    quote_time = max([str(item.get("time") or "") for item in valid_alerts] or [str(fallback_time or "")])
    return {
        "provider": "本地盘中监控、腾讯分钟行情",
        "quote_time": quote_time,
        "pct_field": "各异动卡标注的短周期涨跌幅",
        "sanity_checks": {
            "sample_count": len(valid_alerts),
            "max_abs_leader_change_pct": round(max_move, 4),
            "cross_source_verified": cross_verified,
            "verified_alert_count": sum(item.get("state") == "passed" for item in verifications),
        },
    }


def fetch_many_minute_rows(codes: Iterable[str]) -> Dict[str, List[Dict[str, Any]]]:
    code_list = list(codes)
    result: Dict[str, List[Dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=min(6, max(1, len(code_list)))) as pool:
        futures = {pool.submit(fetch_tencent_minutes, code): code for code in code_list}
        for future in as_completed(futures):
            code = futures[future]
            try:
                result[code] = future.result()
            except Exception:
                result[code] = []
    return result


def fetch_tencent_minutes(code: str) -> List[Dict[str, Any]]:
    request = urllib.request.Request(
        TENCENT_MINUTE_URL.format(urllib.parse.quote(code)),
        headers={"User-Agent": "Mozilla/5.0 stock-dashboard/1.0"},
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))
    raw_rows = (((payload.get("data") or {}).get(code) or {}).get("data") or {}).get("data") or []
    rows = []
    for raw in raw_rows:
        fields = str(raw).split()
        if len(fields) < 2 or not re.fullmatch(r"\d{4}", fields[0]):
            continue
        price = as_float(fields[1])
        if price is not None and price > 0:
            rows.append({"hhmm": fields[0], "price": price})
    return rows


def minute_change(rows: List[Dict[str, Any]], event_at: datetime, window: int) -> Optional[Dict[str, Any]]:
    points = []
    for row in rows:
        hhmm = str(row.get("hhmm") or "")
        price = as_float(row.get("price"))
        if not re.fullmatch(r"\d{4}", hhmm) or price is None or price <= 0:
            continue
        points.append((int(hhmm[:2]) * 60 + int(hhmm[2:]), hhmm, price))
    if not points:
        return None
    event_minute = event_at.hour * 60 + event_at.minute
    end = latest_point(points, event_minute)
    start = latest_point(points, event_minute - window)
    if end is None or start is None:
        return None
    if event_minute - end[0] > 1 or event_minute - window - start[0] > 1:
        return None
    return {
        "change_pct": round((end[2] / start[2] - 1) * 100, 4),
        "start_minute": start[1],
        "end_minute": end[1],
    }


def latest_point(points: List[Any], target: int) -> Optional[Any]:
    eligible = [point for point in points if point[0] <= target]
    return max(eligible, key=lambda point: point[0]) if eligible else None


def load_identity_map(path: Path) -> Dict[str, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    result: Dict[str, str] = {}

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            name = str(value.get("name") or value.get("stock_name") or "").strip()
            code = normalize_code(value.get("code") or value.get("stock_code") or value.get("symbol"))
            if name and code and not code.startswith("hk"):
                result.setdefault(name, code)
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload)
    return result


def lookup_a_share_code(name: str) -> str:
    params = urllib.parse.urlencode({"input": name, "type": "14", "token": EASTMONEY_TOKEN, "count": "5"})
    request = urllib.request.Request(f"{EASTMONEY_SEARCH_URL}?{params}", headers={"User-Agent": "Mozilla/5.0 stock-dashboard/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        rows = ((payload.get("QuotationCodeTable") or {}).get("Data") or [])
    except Exception:
        return ""
    exact = next((row for row in rows if row.get("Classify") == "AStock" and str(row.get("Name") or "").strip() == name), None)
    return normalize_code((exact or {}).get("Code"))


def normalize_code(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if re.fullmatch(r"(?:sh|sz|bj|hk)\d{5,6}", raw):
        return raw
    if not re.fullmatch(r"\d{6}", raw):
        return ""
    if raw.startswith("6"):
        return "sh" + raw
    if raw.startswith(("0", "3")):
        return "sz" + raw
    if raw.startswith(("4", "8", "9")):
        return "bj" + raw
    return ""


def display_code(code: str) -> str:
    if re.fullmatch(r"sh\d{6}", code):
        return f"{code[2:]}.SH"
    if re.fullmatch(r"sz\d{6}", code):
        return f"{code[2:]}.SZ"
    if re.fullmatch(r"bj\d{6}", code):
        return f"{code[2:]}.BJ"
    return code


def parse_datetime(value: Any) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=TZ) if parsed.tzinfo is None else parsed


def parse_window_minutes(value: Any) -> int:
    match = re.search(r"(\d+)\s*分钟", str(value or ""))
    return min(10, max(1, int(match.group(1)))) if match else 3


def direction(value: float) -> int:
    if value > 0.05:
        return 1
    if value < -0.05:
        return -1
    return 0


def as_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def remove_cross_source_missing(value: str) -> str:
    text = re.sub(
        r"(?:还差|仍缺少|(?:也)?缺少)第二行情源交叉验证\s*[，,]\s*或\s*",
        "还需",
        value,
    )
    text = re.sub(r"[；;]?\s*(?:还差|仍缺少|(?:也)?缺少)第二行情源交叉验证[。.]?", "", text)
    text = re.sub(r"[；;]\s*$", "", text).strip()
    return text or "第二行情源已核验；仍需满足卡片列出的价格、成交和扩散条件。"


def prepare_source_health_update(path: Path, payload: Dict[str, Any]) -> Optional[tuple[bytes, Dict[str, Any], bool]]:
    try:
        raw = path.read_bytes()
        source_health = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    if not isinstance(source_health, dict):
        return None
    verifications = []
    for alert in payload.get("alerts") or []:
        if not isinstance(alert, dict):
            continue
        verification = ((alert.get("quote_audit") or {}).get("secondary_verification") or {})
        if not isinstance(verification, dict) or verification.get("state") not in {"passed", "mismatch"}:
            continue
        if not verification.get("checked_at"):
            continue
        verifications.append(verification)
    if not verifications:
        return raw, source_health, False
    latest_check = max(str(item.get("checked_at")) for item in verifications)
    quote_count = sum(
        1
        for item in verifications
        for row in item.get("representatives") or []
        if isinstance(row, dict) and row.get("腾讯涨跌幅") is not None
    )
    passed_count = sum(item.get("state") == "passed" for item in verifications)
    mismatch_count = sum(item.get("state") == "mismatch" for item in verifications)
    sources = source_health.get("sources")
    if not isinstance(sources, dict):
        sources = {}
        source_health["sources"] = sources
    sources["tencent_minute_alert_verifier"] = {
        "status": "ok",
        "last_check": latest_check,
        "usage": "盘中异动代表股第二行情源交叉验证",
        "detail": f"腾讯分钟行情完成{len(verifications)}张异动卡复核：{passed_count}张一致、{mismatch_count}张不一致；不一致卡保持待确认或失效。",
        "sample_count": quote_count,
        "errors": [],
    }
    return raw, source_health, canonical_json(json.loads(raw.decode("utf-8"))) != canonical_json(source_health)


def alert_fingerprint(alert: Dict[str, Any]) -> str:
    core = {"id": alert.get("id"), "time": alert.get("time"), "leaders": alert.get("leaders"), "pct_field": (alert.get("quote_audit") or {}).get("pct_field")}
    return hashlib.sha256(canonical_json(core).encode("utf-8")).hexdigest()[:20]


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_atomic(path: Path, payload: Dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    tmp.replace(path)


def write_status(payload: Dict[str, Any]) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    status = {"updated_at": datetime.now(TZ).replace(microsecond=0).isoformat(), **payload}
    tmp = STATUS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(STATUS_PATH)


if __name__ == "__main__":
    raise SystemExit(main())
