import json
import re
from collections import Counter, defaultdict
from datetime import datetime

import pandas as pd


AS_OF = pd.Timestamp("2026-07-14")
SW1 = {
    "11": "农林牧渔",
    "22": "基础化工",
    "23": "钢铁",
    "24": "有色金属",
    "27": "电子",
    "28": "汽车",
    "33": "家用电器",
    "34": "食品饮料",
    "35": "纺织服饰",
    "36": "轻工制造",
    "37": "医药生物",
    "41": "公用事业",
    "42": "交通运输",
    "43": "房地产",
    "45": "商贸零售",
    "46": "社会服务",
    "47": "综合",
    "48": "银行",
    "49": "非银金融",
    "51": "建筑材料",
    "61": "建筑装饰",
    "62": "电力设备",
    "63": "机械设备",
    "64": "国防军工",
    "65": "计算机",
    "72": "传媒",
    "73": "通信",
    "74": "煤炭",
    "75": "石油石化",
    "76": "环保",
    "77": "美容护理",
}


def code6(value):
    digits = re.sub(r"\D", "", str(value).split(".")[0])
    return digits[-6:].zfill(6)


spot = pd.DataFrame(json.load(open("/tmp/a_spot_sina_20260714.json")))
spot["代码"] = spot["代码"].map(code6)
spot["涨跌幅"] = pd.to_numeric(spot["涨跌幅"], errors="coerce")
spot["成交额"] = pd.to_numeric(spot["成交额"], errors="coerce")

ipo = pd.DataFrame(json.load(open("/tmp/stock_new_ipo_cninfo_20260714.json")))
ipo["上市日期"] = pd.to_datetime(ipo["上市日期"], errors="coerce")
recent_ipo = set(
    ipo.loc[
        ipo["上市日期"].between(pd.Timestamp("2026-07-08"), AS_OF), "证劵代码"
    ].map(code6)
)

valid = spot[
    ~spot["名称"].str.contains(r"ST|退", case=False, na=False)
    & ~spot["名称"].str.match(r"^[NC]", na=False)
    & ~spot["代码"].isin(recent_ipo)
].copy()

sw = pd.DataFrame(json.load(open("/tmp/sw_class_20260714.json")))
sw["symbol"] = sw["symbol"].map(code6)
sw["start_date"] = pd.to_datetime(sw["start_date"], errors="coerce")
sw = sw[sw["start_date"].le(AS_OF)].sort_values(["symbol", "start_date"])
sw = sw.drop_duplicates("symbol", keep="last")
sw["申万一级"] = sw["industry_code"].astype(str).str[:2].map(SW1).fillna("未分类")
valid = valid.merge(sw[["symbol", "申万一级"]], left_on="代码", right_on="symbol", how="left")
valid["申万一级"] = valid["申万一级"].fillna("未分类")


def group_payload(frame):
    counts = Counter(frame["申万一级"])
    total = len(frame)
    rows = []
    for name, count in counts.most_common(12):
        sub = frame[frame["申万一级"] == name].sort_values("成交额", ascending=False)
        reps = [
            {
                "code": row["代码"],
                "name": row["名称"],
                "change_pct": round(float(row["涨跌幅"]), 2),
                "amount_yi": round(float(row["成交额"]) / 1e8, 2),
            }
            for _, row in sub.head(5).iterrows()
        ]
        rows.append(
            {
                "name": name,
                "count": int(count),
                "share_pct": round(count / total * 100, 2) if total else 0,
                "representatives": reps,
            }
        )
    return rows


g8 = valid[valid["涨跌幅"] >= 8].copy()
g5 = valid[(valid["涨跌幅"] >= 5) & (valid["涨跌幅"] < 8)].copy()

zt = pd.DataFrame(json.load(open("/tmp/zt_20260714.json")))
dt = pd.DataFrame(json.load(open("/tmp/dt_20260714.json")))
zb = pd.DataFrame(json.load(open("/tmp/zb_20260714.json")))

result = {
    "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    "universe": int(len(valid)),
    "recent_ipo_excluded": sorted(recent_ipo),
    "group_5_to_lt8": {
        "count": int(len(g5)),
        "industries": group_payload(g5),
    },
    "group_8_plus": {
        "count": int(len(g8)),
        "industries": group_payload(g8),
    },
    "limit_up": int(len(zt)),
    "limit_down": int(len(dt)),
    "broken": int(len(zb)),
    "limit_up_industries": Counter(zt["所属行业"]).most_common(),
    "limit_down_industries": Counter(dt["所属行业"]).most_common(),
    "broken_industries": Counter(zb["所属行业"]).most_common(),
}
json.dump(result, open("/tmp/postmarket_analysis_20260714.json", "w"), ensure_ascii=False, indent=2)
print(json.dumps(result, ensure_ascii=False, indent=2))
