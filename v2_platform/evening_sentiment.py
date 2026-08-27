from __future__ import annotations

import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .cockpit_phase import CockpitPhaseViewBuilder
from .learning import TradingCalendar, as_dict, as_list, load_json, parse_iso, write_json


CHINA = ZoneInfo("Asia/Shanghai")
NEW_YORK = ZoneInfo("America/New_York")


class EveningNetworkUnavailable(RuntimeError):
    pass


def text(value: Any, default: str = "") -> str:
    result = str(value or "").strip()
    return result or default


def unique(values: list[str], limit: int | None = None) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = text(value)
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
        if limit and len(result) >= limit:
            break
    return result


class EveningSentimentRunner:
    """Collect governed public evening inputs and produce a trader-facing next-day brief."""

    def __init__(self, root: Path, *, now: datetime | None = None) -> None:
        self.root = root.resolve()
        observed = now or datetime.now(timezone.utc).astimezone(CHINA)
        if observed.tzinfo is None:
            raise ValueError("evening_time_timezone_required")
        self.now = observed.astimezone(CHINA)
        self.config = load_json(self.root / "config/v2-evening-sentiment.json")
        self.calendar = TradingCalendar(load_json(self.root / "config/v2-market-calendar.json"), "CN")
        self.output = self.root / "data/evening-sentiment.json"
        self.status_path = self.root / "data/v2/v22/evening-sentiment-runtime.json"
        self.scan_path = self.root / "data/v2/v22/evening-announcement-scan.json"
        self.cockpit_path = self.root / "data/v2/v22/cockpit-phase-view.json"

    def run(self, *, force: bool = False, dry_run: bool = False) -> dict[str, Any]:
        target = self._target_trade_date()
        if target is None:
            return self._status("calendar_unverified", None, "交易日历未确认，晚间任务未运行。", dry_run=dry_run)
        existing = load_json(self.output)
        if not force and not self._refresh_due(existing, target):
            return self._status("current", target, "今晚结果已经更新，无需重复生成。", dry_run=dry_run)
        try:
            announcements, scan = self._collect_announcements(target)
        except EveningNetworkUnavailable as exc:
            return self._status(
                "waiting_network",
                target,
                "网络暂不可用，保留上一次晚间结果；恢复联网后会自动补跑。",
                error=str(exc),
                dry_run=dry_run,
            )
        quotes: list[dict[str, Any]] = []
        quote_error = ""
        try:
            quotes = self._collect_us_quotes()
        except EveningNetworkUnavailable as exc:
            quote_error = str(exc)
        payload = self._build_payload(target, announcements, quotes, scan, quote_error)
        if dry_run:
            return {
                "state": "dry_run",
                "trade_date": target.isoformat(),
                "summary": payload["summary"],
                "announcement_count": len(announcements),
                "us_quote_count": len(quotes),
            }
        write_json(self.output, payload)
        write_json(self.scan_path, scan)
        cockpit = CockpitPhaseViewBuilder(self.root, now=self.now).build()
        write_json(self.cockpit_path, cockpit)
        return self._status(
            "completed",
            target,
            "今日晚间舆情已更新；公告、市场风险和次日验证条件已经写入页面。",
            details={
                "announcement_count": len(announcements),
                "watchlist_match_count": scan["watchlist_match_count"],
                "important_match_count": scan["important_match_count"],
                "us_quote_count": len(quotes),
                "output": str(self.output.relative_to(self.root)),
            },
            dry_run=False,
        )

    def _target_trade_date(self) -> date | None:
        due = self._configured_time("due_time", "20:00")
        today_state = self.calendar.is_open(self.now.date())
        if today_state is None:
            return None
        if today_state is True and self.now.timetz().replace(tzinfo=None) >= due:
            return self.now.date()
        cursor = self.now.date()
        lookback = int(self.config.get("catchup_lookback_days") or 10)
        for _ in range(lookback):
            cursor -= timedelta(days=1)
            state = self.calendar.is_open(cursor)
            if state is None:
                return None
            if state:
                return cursor
        return None

    def _refresh_due(self, existing: dict[str, Any], target: date) -> bool:
        if text(existing.get("current_signal_date")) != target.isoformat():
            return True
        if target != self.now.date():
            refresh_after = self._configured_time("overnight_close_refresh_after", "05:05")
            refresh_until = self._configured_time("overnight_close_refresh_until", "08:45")
            now_time = self.now.timetz().replace(tzinfo=None)
            if not (refresh_after <= now_time <= refresh_until):
                return False
            session = as_dict(as_dict(existing.get("coverage")).get("us_market_session"))
            return text(session.get("status")) != "final_close"
        refresh_until = self._configured_time("refresh_until", "23:59")
        if self.now.timetz().replace(tzinfo=None) > refresh_until:
            return False
        collected = parse_iso(as_dict(existing.get("coverage")).get("actual_collection_time") or existing.get("timestamp"))
        if not collected:
            return True
        elapsed = (self.now - collected.astimezone(CHINA)).total_seconds()
        return elapsed >= int(self.config.get("refresh_minutes") or 60) * 60

    def _configured_time(self, key: str, fallback: str) -> time:
        raw = text(self.config.get(key), fallback)
        return time.fromisoformat(raw)

    def _collect_announcements(self, target: date) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        settings = as_dict(self.config.get("cninfo"))
        page_size = int(settings.get("page_size") or 30)
        first = self._fetch_cninfo_page(target, 1, page_size)
        total = int(first.get("totalAnnouncement") or first.get("totalRecordNum") or 0)
        pages = min(int(settings.get("max_pages") or 60), max(1, math.ceil(total / page_size)))
        rows = list(first.get("announcements") or [])
        for page in range(2, pages + 1):
            rows.extend(as_list(self._fetch_cninfo_page(target, page, page_size).get("announcements")))
        deduped: dict[str, dict[str, Any]] = {}
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            announcement_id = text(raw.get("announcementId"))
            if not announcement_id:
                continue
            relative_url = text(raw.get("adjunctUrl"))
            deduped[announcement_id] = {
                "announcement_id": announcement_id,
                "code": text(raw.get("secCode")),
                "name": text(raw.get("secName")).replace(" ", ""),
                "title": text(raw.get("announcementTitle")),
                "announcement_time": self._announcement_time(raw.get("announcementTime")),
                "source": f"https://static.cninfo.com.cn/{relative_url}" if relative_url else "https://www.cninfo.com.cn/",
            }
        pool = load_json(self.root / "data/v2/stock-pool.json")
        watch_codes = {
            text(item.get("code"))[2:]: text(item.get("name"))
            for item in as_list(pool.get("stocks"))
            if isinstance(item, dict) and text(item.get("code"))[:2] in {"sh", "sz", "bj"}
        }
        watch_names = set(watch_codes.values())
        matches = [
            item for item in deduped.values()
            if item["code"] in watch_codes or item["name"] in watch_names
        ]
        important = [item for item in matches if self._announcement_priority(item["title"]) > 0]
        important.sort(key=lambda item: (-self._announcement_priority(item["title"]), item["name"], item["announcement_id"]))
        scan = {
            "schema_version": 1,
            "generated_at": self.now.isoformat(timespec="seconds"),
            "trade_date": target.isoformat(),
            "source": "巨潮资讯全市场公告",
            "retrieved_records": len(deduped),
            "api_reported_total": total,
            "pages": pages,
            "watchlist_security_count": len(watch_codes),
            "watchlist_match_count": len(matches),
            "important_match_count": len(important),
            "important_matches": important,
            "errors": [],
        }
        return important, scan

    def _fetch_cninfo_page(self, target: date, page: int, page_size: int) -> dict[str, Any]:
        settings = as_dict(self.config.get("cninfo"))
        day = target.isoformat()
        form = {
            "pageNum": page,
            "pageSize": page_size,
            "column": text(settings.get("column"), "szse"),
            "tabName": "fulltext",
            "plate": "",
            "stock": "",
            "searchkey": "",
            "secid": "",
            "category": "",
            "trade": "",
            "seDate": f"{day}~{day}",
            "sortName": "",
            "sortType": "",
            "isHLtitle": "true",
        }
        request = urllib.request.Request(
            text(settings.get("url")),
            data=urllib.parse.urlencode(form).encode("utf-8"),
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": text(settings.get("referer"), "https://www.cninfo.com.cn/"),
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise EveningNetworkUnavailable(f"cninfo:{type(exc).__name__}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("announcements"), list):
            raise EveningNetworkUnavailable("cninfo:invalid_response")
        return payload

    def _collect_us_quotes(self) -> list[dict[str, Any]]:
        settings = as_dict(self.config.get("us_quotes"))
        symbols = [text(item) for item in as_list(settings.get("symbols")) if text(item)]
        url = text(settings.get("url")).format(symbols=",".join(symbols))
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": text(settings.get("referer"), "https://gu.qq.com/"),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                raw = response.read().decode("gb18030", "ignore")
        except (OSError, urllib.error.URLError) as exc:
            raise EveningNetworkUnavailable(f"us_quotes:{type(exc).__name__}") from exc
        result = []
        for symbol in symbols:
            match = re.search(rf'v_{re.escape(symbol)}="([^"]*)"', raw)
            if not match:
                continue
            parts = match.group(1).split("~")
            if len(parts) < 33:
                continue
            try:
                price = float(parts[3])
                previous_close = float(parts[4])
                change_pct = float(parts[32])
            except (TypeError, ValueError):
                continue
            quote_time_raw = text(parts[30])
            quote_time = None
            try:
                quote_time = datetime.strptime(quote_time_raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=NEW_YORK)
            except ValueError:
                pass
            result.append({
                "symbol": symbol.removeprefix("us"),
                "name": parts[1],
                "price": price,
                "previous_close": previous_close,
                "change_pct": change_pct,
                "quote_time_raw": quote_time_raw,
                "market_time": quote_time.isoformat(timespec="seconds") if quote_time else None,
                "beijing_time": quote_time.astimezone(CHINA).isoformat(timespec="seconds") if quote_time else None,
                "collected_at": self.now.isoformat(timespec="seconds"),
                "source": "腾讯美股公开行情",
                "is_final_close": bool(quote_time and quote_time.timetz().replace(tzinfo=None) >= time(16, 0)),
            })
        if not result:
            raise EveningNetworkUnavailable("us_quotes:no_valid_rows")
        return result

    def _build_payload(
        self,
        target: date,
        announcements: list[dict[str, Any]],
        quotes: list[dict[str, Any]],
        scan: dict[str, Any],
        quote_error: str,
    ) -> dict[str, Any]:
        verified = load_json(self.root / "config/v2-evening-verified-events.json")
        verified_rows = (
            [item for item in as_list(verified.get("events")) if isinstance(item, dict)]
            if text(verified.get("trade_date")) == target.isoformat()
            else []
        )
        verified_by_id = {text(item.get("announcement_id")): item for item in verified_rows}
        merged = []
        for announcement in announcements:
            merged.append({**announcement, **as_dict(verified_by_id.get(announcement["announcement_id"]))})
        known_ids = {item["announcement_id"] for item in merged}
        merged.extend(item for item in verified_rows if text(item.get("announcement_id")) not in known_ids)
        merged.sort(key=lambda item: (-self._announcement_priority(text(item.get("title"))), text(item.get("name"))))

        environment = load_json(self.root / "data/v2/v22/market-environment.json")
        environment_current = text(environment.get("trade_date")) == target.isoformat()
        market_view = as_dict(environment.get("user_view")) if environment_current else {}
        sentiment = as_dict(environment.get("sentiment_view")) if environment_current else {}
        weak_quotes = [item for item in quotes if float(item.get("change_pct") or 0) <= -3]
        strong_quotes = [item for item in quotes if float(item.get("change_pct") or 0) >= 3]
        quote_session = self._quote_session(quotes, target)
        quote_line = self._quote_line(weak_quotes or strong_quotes, quote_session)
        market_line = text(
            market_view.get("当前判断"),
            text(sentiment.get("judgment"), "收盘市场强弱等待补充"),
        )
        company_positive = [
            item for item in merged
            if "正向" in text(item.get("severity"), self._generic_severity(text(item.get("title"))))
        ]
        open_bias = "偏弱分化" if weak_quotes or int(market_view.get("抑制项") or 0) >= 3 else "分化观察"
        company_line = (
            f"公司公告中有{len(company_positive)}条偏正面信息，先按个股事件处理，只有代表股和板块一起转强才考虑行动。"
            if company_positive
            else "公司公告暂未发现可直接支持板块交易的正向信息。"
        )
        summary = (
            f"{target.month}月{target.day}日晚间结论：明日开盘先按{open_bias}应对。"
            f"{market_line}"
            f"{quote_line}"
            f"{company_line}"
        )

        p0_alerts = []
        if environment_current:
            drivers = as_list(sentiment.get("drivers"))
            p0_alerts.append({
                "title": "收盘亏钱效应仍明显，次日先看风险是否减少",
                "severity": "P0/风险",
                "why_p0": market_line,
                "evidence": [
                    {
                        "type": "market_close",
                        "source": "data/v2/v22/market-environment.json",
                        "timestamp": text(environment.get("as_of")),
                        "detail": text(item.get("evidence")),
                    }
                    for item in drivers[:4] if isinstance(item, dict)
                ],
                "watch_next_day": [
                    "先看跌停是否明显减少、高位股是否止跌，再决定是否从防守转为观察。",
                    "主要指数和核心代表股没有同步转强前，不因单个利好追高。",
                ],
                "source": "data/v2/v22/market-environment.json",
            })
        if weak_quotes:
            quote_is_final = quote_session["status"] == "final_close"
            p0_alerts.append({
                "title": (
                    "隔夜美股芯片股收跌，AI硬件次日先防守"
                    if quote_is_final
                    else "美股芯片股盘中走弱，AI硬件风险尚未解除"
                ),
                "severity": "P0/负向",
                "why_p0": quote_line,
                "evidence": [
                    {
                        "type": "external_quote",
                        "source": item["source"],
                        "timestamp": item["collected_at"],
                        "detail": (
                            f"{item['name']} {item['change_pct']:+.2f}%，价格{item['price']:.2f}美元；"
                            f"{'已收盘' if quote_is_final else '为盘中快照'}。"
                        ),
                    }
                    for item in weak_quotes[:4]
                ],
                "watch_next_day": [
                    (
                        "已取得隔夜正式收盘；9:25继续看A股代表股是否跟跌或出现抗跌。"
                        if quote_is_final
                        else "次日8:30复核美股正式收盘，盘中快照不能冒充收盘。"
                    ),
                    "若A股存储、光模块和算力代表股继续批量低开，先回避，不抄底。",
                ],
                "source": "腾讯美股公开行情",
            })
        for item in merged[:4]:
            p0_alerts.append({
                "title": text(item.get("title")),
                "severity": text(item.get("severity"), self._generic_severity(text(item.get("title")))),
                "why_p0": text(item.get("trading_impact"), self._generic_impact(item)),
                "evidence": [{
                    "type": "company_announcement",
                    "source": text(item.get("source"), "巨潮资讯"),
                    "timestamp": text(item.get("announcement_time"), self.now.isoformat(timespec="seconds")),
                    "detail": text(item.get("fact"), text(item.get("title"))),
                }],
                "watch_next_day": [
                    text(item.get("verify_next_day"), "先看公司股价是否得到成交确认，再看同板块代表股是否跟随。"),
                    f"主要风险：{text(item.get('risk'), '公告标题不能代替实际兑现，保持观察。')}",
                ],
                "source": text(item.get("source"), "https://www.cninfo.com.cn/"),
            })

        news = []
        if environment_current:
            news.append({
                "title": "今日收盘市场偏弱",
                "text": market_line,
                "source": "data/v2/v22/market-environment.json",
                "tag": "market_close",
                "impact": text(market_view.get("当前允许"), "先防守，等待代表股转强。"),
                "evidence": [text(item.get("evidence")) for item in as_list(sentiment.get("drivers")) if isinstance(item, dict)],
                "verify_next_day": "看跌停、高位股和核心代表股是否同时改善。",
            })
        for item in merged:
            news.append({
                "title": text(item.get("title")),
                "text": text(item.get("fact"), text(item.get("title"))),
                "source": text(item.get("source"), "https://www.cninfo.com.cn/"),
                "tag": "company_announcement",
                "impact": text(item.get("trading_impact"), self._generic_impact(item)),
                "evidence": [text(item.get("fact"), text(item.get("title")))],
                "verify_next_day": text(item.get("verify_next_day"), "先看个股，再看板块是否跟随。"),
            })
        if quotes:
            quote_is_final = quote_session["status"] == "final_close"
            news.append({
                "title": "隔夜美股科技股收盘" if quote_is_final else "美股科技股盘中表现",
                "text": self._quote_line(quotes, quote_session),
                "source": "腾讯美股公开行情",
                "tag": "external_market",
                "impact": (
                    "已进入次日预案；仍需由A股集合竞价和代表股走势确认，不能机械照搬。"
                    if quote_is_final
                    else "只作为次日预案背景，必须由正式收盘和A股代表股验证。"
                ),
                "evidence": [f"{item['name']}{item['change_pct']:+.2f}%" for item in quotes],
                "verify_next_day": (
                    "9:25观察A股代表股是跟随、抗跌还是反向走强。"
                    if quote_is_final
                    else "8:30复核正式收盘，9:25观察A股代表股是否跟随。"
                ),
            })

        sources = unique([
            "data/v2/v22/market-environment.json",
            "https://www.cninfo.com.cn/",
            *[text(item.get("source")) for item in merged],
            "https://qt.gtimg.cn/",
            *[text(item) for item in as_list(verified.get("sources"))],
        ])
        coverage = {
            "phase": "20:00_evening_scan_with_recovery",
            "date": target.isoformat(),
            "scheduled_time": f"{text(self.config.get('due_time'), '20:00')}+08:00",
            "actual_collection_time": self.now.isoformat(timespec="seconds"),
            "scope": [
                "V2当日收盘市场强弱与情绪",
                "巨潮资讯全市场公告分页及股票池代码/名称匹配",
                "股票池重大公告的次日交易影响",
                "美股科技代表股盘中行情及次日凌晨正式收盘回填",
            ],
            "us_market_session": quote_session,
            "announcement_scan": {
                "source": scan["source"],
                "pages": scan["pages"],
                "retrieved_records": scan["retrieved_records"],
                "api_reported_total": scan["api_reported_total"],
                "watchlist_matches": scan["watchlist_match_count"],
                "important_matches": scan["important_match_count"],
            },
            "degraded": unique([
                (
                    "隔夜美股已取得正式收盘，仍需观察A股代表股是否跟随。"
                    if quote_session["status"] == "final_close"
                    else "美股价格是晚间盘中快照，不是正式收盘，次日8:30必须复核。"
                ),
                "普通公告只按标题分类；没有公告原文量化依据时不写金额、订单或业绩结论。",
                quote_error,
            ]),
            "recovery": {
                "enabled": True,
                "retry_interval_seconds": int(self.config.get("retry_interval_seconds") or 300),
                "rule": "断网或电脑休眠时保留上次结果；恢复联网后补跑晚间公告，并在次日凌晨回填隔夜美股正式收盘。",
            },
        }
        return {
            "timestamp": self.now.isoformat(timespec="seconds"),
            "current_signal_date": target.isoformat(),
            "summary": summary,
            "disclaimer": "AI辅助分析，不构成投资建议；公告事实与交易判断分开，次日仍需竞价和代表股验证。",
            "sentiment_summary": {
                "date": target.isoformat(),
                "level": open_bias,
                "market_read": f"{market_line}{quote_line}",
                "open_bias": open_bias,
                "bullish": unique([text(item.get("trading_impact")) for item in company_positive], 4),
                "bearish": unique([
                    text(market_view.get("当前判断")),
                    self._quote_line(weak_quotes),
                ], 4),
                "pending": [
                    *([] if quote_session["status"] == "final_close" else ["美股正式收盘结果。"]),
                    "次日集合竞价和A股代表股是否跟随。",
                ],
                "risk_bias": (
                    "公司级利好不等于板块反转；隔夜美股方向仍需A股竞价和代表股确认。"
                    if quote_session["status"] == "final_close"
                    else "公司级利好不等于板块反转；外盘盘中快照不等于正式收盘。"
                ),
                "next_session_focus": unique([
                    "先看跌停是否减少、高位股是否止跌。",
                    "AI硬件先看工业富联、中际旭创及同板块代表股是否同步企稳。",
                    "医药公告先按公司事件观察，没有板块跟随不追高。",
                    *[text(item.get("verify_next_day")) for item in merged[:3]],
                ], 6),
            },
            "coverage": coverage,
            "p0_alerts": p0_alerts[:6],
            "news": news[:12],
            "sources": sources,
        }

    def _status(
        self,
        state: str,
        target: date | None,
        summary: str,
        *,
        error: str = "",
        details: dict[str, Any] | None = None,
        dry_run: bool,
    ) -> dict[str, Any]:
        payload = {
            "schema_version": 1,
            "generated_at": self.now.isoformat(timespec="seconds"),
            "state": state,
            "target_trade_date": target.isoformat() if target else None,
            "summary": summary,
            "error": error or None,
            "next_retry_seconds": int(self.config.get("retry_interval_seconds") or 300) if state == "waiting_network" else None,
            "details": details or {},
            "guardrails": as_dict(self.config.get("guardrails")),
        }
        if not dry_run:
            write_json(self.status_path, payload)
        return payload

    def _announcement_priority(self, title: str) -> int:
        severe = ("立案", "处罚", "退市", "重大诉讼", "控制权", "重大合同", "订单", "回购", "减持", "业绩预增", "临床试验", "药品注册", "H股")
        medium = tuple(text(item) for item in as_list(self.config.get("priority_keywords")))
        if any(token in title for token in severe):
            return 3
        if any(token in title for token in medium):
            return 2
        return 0

    @staticmethod
    def _generic_severity(title: str) -> str:
        if any(token in title for token in ("不减持", "承诺不减持")):
            return "P1/正向观察"
        if any(token in title for token in ("立案", "处罚", "减持", "退市", "风险提示")):
            return "P0/风险"
        if any(token in title for token in ("回购", "增持", "业绩预增", "临床试验", "中标", "订单")):
            return "P1/正向观察"
        return "P2/仅观察"

    @staticmethod
    def _generic_impact(item: dict[str, Any]) -> str:
        title = text(item.get("title"))
        name = text(item.get("name"), "相关公司")
        if any(token in title for token in ("不减持", "承诺不减持")):
            return f"{name}发布不减持承诺，属于个股偏正面信息；次日仍要看股价承接，不能直接当作板块机会。"
        if any(token in title for token in ("立案", "处罚", "减持", "退市", "风险提示")):
            return f"{name}出现风险公告，次日先看是否低开和风险是否向板块扩散。"
        if any(token in title for token in ("回购", "增持", "业绩预增", "临床试验", "中标", "订单")):
            return f"{name}出现偏正面公告，但先按公司事件处理，不能自动升级为板块机会。"
        return f"{name}出现新公告，当前只保留观察，等待价格和板块反应。"

    @staticmethod
    def _announcement_time(value: Any) -> str | None:
        try:
            stamp = int(value) / 1000
        except (TypeError, ValueError):
            return None
        return datetime.fromtimestamp(stamp, timezone.utc).astimezone(CHINA).isoformat(timespec="seconds")

    @staticmethod
    def _quote_session(rows: list[dict[str, Any]], target: date) -> dict[str, Any]:
        timestamps = [parse_iso(item.get("market_time")) for item in rows]
        timestamps = [item.astimezone(NEW_YORK) for item in timestamps if item]
        latest = max(timestamps) if timestamps else None
        if not latest:
            status = "unverified"
            label = "美股时点待核验"
        elif latest.date() < target:
            status = "previous_close"
            label = "上一交易日收盘参考"
        elif latest.timetz().replace(tzinfo=None) >= time(16, 0):
            status = "final_close"
            label = "隔夜美股已收盘"
        elif latest.timetz().replace(tzinfo=None) >= time(9, 30):
            status = "intraday"
            label = "美股盘中"
        else:
            status = "pre_market"
            label = "美股盘前"
        return {
            "status": status,
            "label": label,
            "market_time": latest.isoformat(timespec="seconds") if latest else None,
            "beijing_time": latest.astimezone(CHINA).isoformat(timespec="seconds") if latest else None,
        }

    @staticmethod
    def _quote_line(rows: list[dict[str, Any]], session: dict[str, Any] | None = None) -> str:
        if not rows:
            return ""
        text_rows = "、".join(f"{item['name']}{float(item['change_pct']):+.2f}%" for item in rows[:5])
        status = text(as_dict(session).get("status"))
        if status == "final_close":
            return f"隔夜美股收盘{text_rows}；该方向已进入次日预案，但仍需A股代表股确认。"
        if status == "previous_close":
            return f"上一交易日美股收盘{text_rows}；今晚行情尚未开始，只作背景参考。"
        if status == "pre_market":
            return f"美股盘前{text_rows}；尚未开盘，只作风险提示。"
        return f"美股盘中{text_rows}；这是盘中快照，不是正式收盘。"
