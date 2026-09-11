"""Five-factor sentiment contract from RULES.md; missing facts are never neutral scores."""
import math

VERSION = "v1_sentiment_five_factors_20260911"


def number(value):
    if value is None or isinstance(value, bool) or str(value).strip() == "":
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def first(data, *keys):
    for key in keys:
        if key in data:
            result = number(data[key])
            return result if result is not None and result >= 0 else None
    return None


def sentiment_payload(indices, breadth):
    up = first(breadth, "effective_limit_up_count", "limit_up_count", "limit_up")
    down = first(breadth, "limit_down_count", "limit_down")
    broken = first(breadth, "broken_board_count", "broken_board")
    strong = first(breadth, "up5_count", "strong_5pct_count")
    total = first(breadth, "valid_a_share_count", "total_count")
    changes = [number(row.get("change_pct", row.get("pct"))) for row in indices]
    components = []

    def add(name, weight, score, evidence):
        components.append({"name": name, "weight_pct": weight,
                           "score": round(max(0, min(100, score)), 4) if score is not None else None,
                           "evidence": evidence})

    pair = up is not None and down is not None and up + down > 0
    add("涨跌停差", 25, 50 + 50 * (up - down) / (up + down) if pair else None,
        f"涨停{up:g}只、跌停{down:g}只。" if pair else "涨跌停统计不足，暂不评分。")
    ratio = (100 if down == 0 else 0 if up == 0 else 50 + 25 * math.log2(up / down)) if pair else None
    add("涨停与跌停比例", 20, ratio, "按同一统计范围的涨停与跌停数量比较。" if pair else "暂无可计算的涨跌停比例。")
    sealed = up is not None and broken is not None and up + broken > 0
    add("封板质量", 20, 100 * up / (up + broken) if sealed else None,
        f"涨停{up:g}只、炸板{broken:g}只。" if sealed else "涨停或炸板统计不足。")
    wide = strong is not None and total is not None and 0 < total and strong <= total
    add("涨幅超过5%的股票占比", 20, 100 * strong / total / .06 if wide else None,
        f"{strong:g}/{total:g}只股票涨幅超过5%。" if wide else "缺少涨幅超过5%的股票数量或同范围有效股票总数。")
    complete_indices = len(changes) == 5 and len({row.get("code") or row.get("name") for row in indices}) == 5 and all(x is not None for x in changes)
    add("五大核心指数", 15, 50 + 10 * sum(changes) / 5 if complete_indices else None,
        "；".join(f"{row.get('name', '指数')}{change:+.2f}%" for row, change in zip(indices, changes)) if complete_indices else "五大指数报价不齐。")
    missing = [row["name"] for row in components if row["score"] is None]
    score = round(sum(row["score"] * row["weight_pct"] / 100 for row in components), 2) if not missing else None
    level = "统计未齐" if score is None else ("热" if score >= 75 else "偏暖" if score >= 60 else "分化" if score >= 45 else "偏冷" if score >= 30 else "冰点")
    return {"method_version": VERSION, "score": score, "level": level, "components": components,
            "missing_components": missing, "judgement": f"市场情绪：{level}",
            "method": "涨跌停差25%＋涨跌停比20%＋封板质量20%＋5%以上强势股宽度20%＋核心指数15%；分项齐全后才计算总分。",
            "limitations": ["缺失分项不补50分、不重分配权重；旧算法分数不参与同口径比较。"]}
