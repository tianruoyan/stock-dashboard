# -*- coding: utf-8 -*-
import json
import random
import time
import urllib.parse
import urllib.request


STOCKS = {
    "sh688981": "中芯国际A", "sh688037": "芯源微", "sh688120": "华海清科", "sh688012": "中微公司", "sz002371": "北方华创",
    "sh688596": "正帆科技", "sh688019": "安集科技", "sz300666": "江丰电子", "sz300346": "南大光电", "sz300260": "新莱应材",
    "sh688361": "中科飞测", "sh688200": "华峰测控", "sz300604": "长川科技", "sh688396": "华润微", "sh605111": "新洁能", "sh603290": "斯达半导",
    "sz002409": "雅克科技", "sh688126": "沪硅产业", "sh688432": "有研硅", "sh688409": "富创精密", "sh600460": "士兰微",
    "sh603986": "兆易创新", "sz300475": "香农芯创", "sh688008": "澜起科技", "sh601138": "工业富联",
    "sz300308": "中际旭创", "sz300502": "新易盛", "sz300394": "天孚通信", "sz002281": "光迅科技", "sz002396": "星网锐捷",
    "sh600176": "中国巨石", "sz301526": "国际复材", "sh605006": "山东玻纤", "sz300196": "长海股份", "sh603256": "宏和科技", "sh601208": "东材科技", "sz002080": "中材科技", "sz000012": "南玻A",
    "sh600545": "卓郎智能", "sh603928": "兴业股份", "sz000859": "国风新材",
    "sz300476": "胜宏科技", "sz002463": "沪电股份", "sh600183": "生益科技", "sz002938": "鹏鼎控股", "sz002384": "东山精密", "sh603228": "景旺电子", "sh603920": "世运电路",
    "sh600030": "中信证券", "sz300059": "东方财富", "sh601688": "华泰证券", "sh601881": "中国银河", "sh601318": "中国平安", "sh601628": "中国人寿", "sh601601": "中国太保", "sh601336": "新华保险",
    "sz002714": "牧原股份", "sz300498": "温氏股份", "sz000876": "新希望", "sh603477": "巨星农牧", "sz002567": "唐人神", "sh600519": "贵州茅台", "sz000858": "五粮液", "sz000568": "泸州老窖", "sh600809": "山西汾酒", "sz002304": "洋河股份",
}

HK = {"r_hkHSI": "恒生指数", "r_hkHSTECH": "恒生科技", "hk00981": "中芯国际H", "hk01347": "华虹半导体", "hk09988": "阿里巴巴-W", "hk00700": "腾讯控股", "hk09926": "康方生物"}


def fetch(url, encoding="utf-8"):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 stock-dashboard/1.0", "Referer": "https://quote.eastmoney.com/"})
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.read().decode(encoding, errors="replace")


def tencent(codes, names):
    text = fetch("https://qt.gtimg.cn/q=" + ",".join(codes), "gbk")
    rows = []
    for line in text.splitlines():
        if '="' not in line:
            continue
        query = line.split('="', 1)[0].replace("v_", "")
        fields = line.split('="', 1)[1].rsplit('";', 1)[0].split("~")
        if len(fields) < 38 or not fields[1]:
            continue
        def num(index):
            try:
                return round(float(fields[index]), 2)
            except (ValueError, IndexError):
                return None
        rows.append({"code": query, "name": names.get(query, fields[1]), "price": num(3), "pct": num(32), "open": num(5), "high": num(33), "low": num(34), "amount_yi": round(num(37) / 10000, 2) if num(37) is not None and query.startswith(("sh", "sz")) else num(37), "quote_time": fields[30] if len(fields) > 30 else None})
    return rows


def pool(endpoint):
    params = urllib.parse.urlencode({"ut": "7eea3edcaed734bea9cbfc24409ed989", "dpt": "wz.ztzt", "Pageindex": 0, "pagesize": 200, "sort": "fbt:asc", "date": "20260713"})
    payload = json.loads(fetch(f"https://push2ex.eastmoney.com/{endpoint}?{params}"))
    data = payload.get("data") or {}
    return {"total": data.get("tc"), "rows": data.get("pool") or []}


result = {"tencent_a": tencent(list(STOCKS), STOCKS), "tencent_hk": tencent(list(HK), HK), "eastmoney": {}, "errors": []}
for endpoint in ("getTopicZTPool", "getTopicZBPool", "getTopicDTPool"):
    try:
        result["eastmoney"][endpoint] = pool(endpoint)
    except Exception as exc:
        result["errors"].append(f"{endpoint}: {type(exc).__name__}: {exc}")
    time.sleep(random.uniform(1.2, 2.0))
print(json.dumps(result, ensure_ascii=False))
