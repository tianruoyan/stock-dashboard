#!/usr/bin/env python3
"""V1-owned evening facts; reuse public collectors, never copy V2 judgments."""
from __future__ import annotations
import argparse
import json
import sys
from datetime import datetime, time, timedelta
from pathlib import Path
from stage_fallback import TZ, ROOT, cn_calendar, read_json, write_json_atomic, parse_datetime

SHARED = Path.home() / "Documents/投资/worktrees/stock-dashboard-v2"


def refresh(*, force=False, now=None):
    now = now or datetime.now(TZ)
    # Existing minute-level fallback calls this; fetching is bounded to five minutes.
    if not force and not (time(19, 30) <= now.time() <= time(22, 30) or time(7, 30) <= now.time() <= time(8, 30)):
        return {"state": "outside_window"}
    status_path = ROOT / "logs/evening-public-status.json"
    previous = read_json(status_path)
    attempted = parse_datetime(previous.get("attempted_at"))
    if not force and attempted and now - attempted < timedelta(minutes=5):
        return {"state": "retry_backoff"}
    sys.path.insert(0, str(SHARED))
    from v2_platform.evening_sentiment import EveningSentimentRunner
    from v2_platform.learning import TradingCalendar

    class V1Collector(EveningSentimentRunner):
        def _watchlist_projection(self):
            return read_json(ROOT / "config/watchlist.json").get("watch_only", {})

    collector = V1Collector(ROOT, now=now)
    collector.config = read_json(SHARED / "config/v2-evening-sentiment.json")
    collector.calendar = TradingCalendar({"calendars": [cn_calendar(ROOT)]}, "CN")
    target = collector._target_trade_date()
    if target is None:
        return {"state": "calendar_unverified"}
    existing = read_json(ROOT / "data/evening-sentiment.json")
    if not force and not collector._refresh_due(existing, target):
        return {"state": "current"}
    status = {"attempted_at": now.isoformat(), "trade_date": target.isoformat()}
    try:
        announcements, scan = collector._collect_announcements(target)
        quotes = collector._collect_us_quotes()
        session = collector._quote_session(quotes, target)
        quote_line = collector._quote_line(quotes, session)
        news = [{"title": item["title"], "text": item["title"], "source": item["source"],
                 "tag": "公司公告", "impact": collector._generic_impact(item),
                 "timestamp": item["announcement_time"], "evidence": [item["title"]]}
                for item in announcements[:10]]
        if quotes:
            news.append({"title": "海外科技股行情", "text": quote_line, "tag": "外盘观察", "source": "腾讯财经", "evidence": [quote_line], "impact": "下一交易日观察A股相关代表股是否同向，不把海外走势直接当作买卖信号。"})
        payload = {"timestamp": now.isoformat(timespec="seconds"), "current_signal_date": target.isoformat(),
                   "trade_date": target.isoformat(), "analysis_time": now.isoformat(timespec="seconds"),
                   "historical_backfill": target != now.date(),
                   "summary": f"{target.isoformat()}晚间材料补充：本次发现{len(announcements)}条与观察池有关的重要公告；先按公司事件观察，等待A股代表股确认。{quote_line}",
                   "sentiment_summary": {"level": "分化观察", "market_read": quote_line, "open_bias": "等待A股确认", "risk_bias": "公告标题不等于业绩兑现；海外涨跌不能直接替代A股交易判断。", "next_session_focus": ["先核对公告原文，再看相关个股与板块是否同步走强。"]},
                   "p0_alerts": [], "news": news,
                   "coverage": {"actual_collection_time": now.isoformat(), "announcement_scan": scan, "us_market_session": session,
                                "scope": "用户观察池重大公告与海外科技行情，不声称覆盖全部新闻舆情"}}
        write_json_atomic(ROOT / "data/evening-sentiment.json", payload)
        (ROOT / ".publish-pending").touch()
        status.update(state="completed", announcement_count=len(announcements), us_quote_count=len(quotes))
    except Exception as exc:
        status.update(state="waiting_network", detail=f"{type(exc).__name__}: {exc}", previous_result_preserved=True)
    write_json_atomic(status_path, status)
    return status


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    print(json.dumps(refresh(force=parser.parse_args().force), ensure_ascii=False))
