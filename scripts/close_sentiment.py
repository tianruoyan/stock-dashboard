"""Save recalculable daily sentiment without changing an authored judgement."""
import hashlib
import json
from datetime import datetime

from market_sentiment import sentiment_payload


def update_close_sentiment(root, payload, now):
    indices = payload["index"]["a_share_indices"]
    breadth = payload["market_breadth"]
    day = payload["trade_date"]
    indicator = sentiment_payload(indices, breadth)
    historical = day != now.date().isoformat()
    indicator["trade_date"] = day
    indicator["calculated_at"] = now.isoformat(timespec="seconds")
    indicator["historical_backfill"] = historical or breadth.get("historical_backfill") is True
    indicator["display_note"] = (f"{day}收盘情绪；历史补算，不代表当时已发布的判断。"
                                 if indicator["historical_backfill"] else f"{day}收盘情绪。")
    payload["sentiment_indicator"] = indicator
    payload["sentiment_indicator_as_of"] = indicator["calculated_at"]
    if indicator["score"] is None:
        return
    facts = {"trade_date": day, "indices": indices, "market_breadth": breadth,
             "score": indicator["score"], "components": indicator["components"],
             "method_version": indicator["method_version"]}
    digest = hashlib.sha256(json.dumps(facts, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    relative = f"data/history/sentiment/{day}/{digest}.json"
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    record = dict(facts, calculated_at=indicator["calculated_at"],
                  historical_backfill=indicator["historical_backfill"], evaluation_eligible=False,
                  original_analysis_time=payload.get("analysis_time"),
                  source_close_detail_archive=breadth.get("close_detail_archive"),
                  use="收盘统计复核，不新增交易信号或回写历史判断")
    if not path.exists():
        with path.open("x", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    indicator["history_record"] = relative
