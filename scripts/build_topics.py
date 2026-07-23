#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
TOPICS_PATH = DATA_DIR / "topics.json"
POSTMARKET_PATH = DATA_DIR / "postmarket.json"


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def find_named(rows: list[Any], name: str) -> dict[str, Any]:
    return next(
        (
            item
            for item in rows
            if isinstance(item, dict)
            and str(item.get("name") or item.get("industry") or "") == name
        ),
        {},
    )


def integer(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def main() -> int:
    topics = load_json(TOPICS_PATH)
    postmarket = load_json(POSTMARKET_PATH)
    source_as_of = str(postmarket.get("timestamp") or "")
    rows = [item for item in as_list(topics.get("topics")) if isinstance(item, dict)]
    if not source_as_of or not rows:
        print("topics-refresh: waiting - 专题或盘后数据不可用")
        return 0

    breadth = as_dict(postmarket.get("market_breadth"))
    machinery = find_named(as_list(postmarket.get("hotspots")), "机械设备/低位装备")
    industry_concentration = as_list(breadth.get("industry_concentration"))
    industry_gte8 = as_list(breadth.get("industry_gte8"))
    limit_industries = {
        str(item.get("name") or ""): integer(item.get("limit_up_count"))
        for item in as_list(breadth.get("limit_pool_industry"))
        if isinstance(item, dict)
    }
    theme_concentration = as_list(breadth.get("theme_concentration"))

    updates: dict[str, dict[str, Any]] = {}
    machinery_breadth = find_named(industry_concentration, "机械设备")
    if machinery and machinery_breadth:
        strong_count = integer(machinery_breadth.get("count"))
        special_limit = limit_industries.get("专用设备", 0)
        general_limit = limit_industries.get("通用设备", 0)
        updates["机器人/工业自动化"] = {
            "status": "观察线/分化",
            "conclusion": (
                "机械设备收盘明显活跃，但专用设备和通用设备的涨停中混有电网、"
                "油服和军工，机器人主线尚未确认。"
            ),
            "action": (
                "次日先看绿的谐波、埃斯顿、步科股份等核心股是否至少3只同步转强，"
                "再看减速器、伺服、控制器和机器视觉是否出现涨停扩散；"
                "两者缺一，只按低位装备轮动观察。"
            ),
            "note": (
                f"机械设备{strong_count}只涨超5%，专用设备{special_limit}只、"
                f"通用设备{general_limit}只涨停；这些强势股并非来自同一机器人产业催化。"
            ),
            "updated_at": source_as_of,
        }

    medical_breadth = find_named(industry_concentration, "医药生物")
    medical_gte8 = find_named(industry_gte8, "医药生物")
    medical_theme = find_named(theme_concentration, "医药")
    if medical_breadth and medical_theme:
        strong_count = integer(medical_breadth.get("count"))
        very_strong_count = integer(medical_gte8.get("count"))
        limit_count = integer(medical_theme.get("limit_up_count"))
        industries = as_dict(medical_theme.get("industries"))
        representatives = "、".join(str(value) for value in as_list(medical_theme.get("representatives"))[:6])
        updates["医药修复链"] = {
            "status": "修复观察",
            "conclusion": (
                f"医药收盘出现{limit_count}只涨停、{strong_count}只涨超5%，低位修复已经出现；"
                f"但涨停主要分布在中药{integer(industries.get('中药Ⅱ'))}只、"
                f"化学制药{integer(industries.get('化学制药'))}只和"
                f"医疗器械{integer(industries.get('医疗器械'))}只，尚未形成全行业一致主线。"
            ),
            "action": (
                f"次日先看化学制药涨停能否继续增加、医药涨超5%的股票能否保持在"
                f"{strong_count}只以上，再看恒瑞、科伦、普洛等核心股是否多数上涨；"
                "否则只按低位轮动观察。"
            ),
            "note": (
                f"医药生物涨超8%的股票有{very_strong_count}只；"
                f"涨停代表包括{representatives or '等待代表股名单'}，当前强点偏中药和少数化学制药。"
            ),
            "updated_at": source_as_of,
        }

    updated_names = []
    for item in rows:
        name = str(item.get("name") or "")
        if name not in updates:
            continue
        item.update(updates[name])
        updated_names.append(name)

    if not updated_names:
        print("topics-refresh: waiting - 当天盘后证据不足，保留原专题结论")
        return 0

    topics["topics"] = rows
    TOPICS_PATH.write_text(
        json.dumps(topics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"topics-refresh: ok - 已更新{'、'.join(updated_names)}，依据截至{source_as_of}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
