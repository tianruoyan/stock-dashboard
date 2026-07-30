#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
STAMP = "2026-07-30T10:38:00+08:00"


def load(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def write_atomic(name: str, payload: dict) -> None:
    path = DATA / name
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    os.replace(tmp, path)


limit_up_groups = [
    {
        "theme": "消费/酒店/食品/零售/白酒",
        "count": 9,
        "stocks": ["华天酒店", "西安饮食", "一鸣食品", "均瑶健康", "安记食品", "海欣食品", "南宁百货", "舍得酒业", "爱丽家居"],
        "evidence": "酒店、食品、零售和白酒多分支封板，爱丽家居8连板、华天酒店4连板。",
    },
    {
        "theme": "汽车整车/零部件",
        "count": 7,
        "stocks": ["江淮汽车", "浙江世宝", "明新旭腾", "大明电子", "纳百川", "文灿股份", "至信股份"],
        "evidence": "江淮汽车封板、纳百川20cm，整车向零部件扩散；但飞龙股份、祥鑫科技跌停，分支内部强分歧。",
    },
    {
        "theme": "软件/财税数字化/教育",
        "count": 8,
        "stocks": ["恒锋信息", "普联软件", "南天信息", "税友股份", "中科金财", "苏州科达", "传智教育", "学大教育"],
        "evidence": "恒锋信息、普联软件20cm封板，财税、软件和教育具备前后排。",
    },
    {
        "theme": "电网设备",
        "count": 3,
        "stocks": ["金龙羽", "广电电气", "昊创瑞通"],
        "evidence": "含昊创瑞通20cm，仍需行业中军和成交持续性确认。",
    },
    {
        "theme": "农化/化学制品",
        "count": 3,
        "stocks": ["利尔化学", "美邦股份", "高争民爆"],
        "evidence": "农化保持低位扩散，但利尔化学已有两次开板，承接质量需继续核验。",
    },
]

limit_down_pool = [
    {"name": "广合科技", "change_pct": -10.00, "theme": "PCB/元件"},
    {"name": "至纯科技", "change_pct": -10.01, "theme": "半导体设备/材料"},
    {"name": "通富微电", "change_pct": -10.00, "theme": "先进封装/半导体"},
    {"name": "瑞芯微", "change_pct": -10.00, "theme": "半导体"},
    {"name": "剑桥科技", "change_pct": -10.00, "theme": "通信设备/CPO"},
    {"name": "共进股份", "change_pct": -9.98, "theme": "交换机ODM/通信设备"},
    {"name": "紫光股份", "change_pct": -9.99, "theme": "交换机整机/平台"},
    {"name": "东山精密", "change_pct": -10.00, "theme": "PCB/元件"},
    {"name": "飞龙股份", "change_pct": -10.00, "theme": "汽车零部件"},
    {"name": "祥鑫科技", "change_pct": -9.99, "theme": "汽车零部件"},
    {"name": "圣晖集成", "change_pct": -10.00, "theme": "半导体洁净室/工程"},
    {"name": "百合花", "change_pct": -9.99, "theme": "化学制品"},
]

broken_pool = [
    {"name": "永鼎股份", "theme": "通信设备", "change_pct": 3.87},
    {"name": "凯撒文化", "theme": "游戏", "change_pct": 5.60},
    {"name": "东晶电子", "theme": "元件", "change_pct": 7.92},
    {"name": "安阳钢铁", "theme": "钢铁", "change_pct": 4.55},
    {"name": "利欧股份", "theme": "通用设备", "change_pct": 5.38},
    {"name": "海南海药", "theme": "化学制药", "change_pct": 7.76},
    {"name": "国风新材", "theme": "塑料/电子布映射", "change_pct": 5.59},
]

switch_special = {
    "conclusion": "风险线，交换机主线未确认",
    "market_structure": "10:32通信设备-8.69%，固定七核心0涨停、0个20cm、2只跌停；剑桥科技跌停、永鼎股份炸板，整机/ODM/交换芯片无低位补涨。",
    "ranking": [
        {"rank": 1, "name": "中兴通讯", "role": "整机/平台", "change_pct": -1.64, "amount_yi": 18.38, "intraday_state": "低于开盘、接近日内低点，仍强于通信设备行业"},
        {"rank": 2, "name": "锐捷网络", "role": "整机/平台", "change_pct": -2.97, "amount_yi": 15.64, "intraday_state": "高开后持续回落，未突破日内高点"},
        {"rank": 3, "name": "工业富联", "role": "ODM制造/服务器配套", "change_pct": -7.15, "amount_yi": 45.37, "intraday_state": "高成交下行、接近日内低点"},
        {"rank": 4, "name": "菲菱科思", "role": "ODM制造/弹性", "change_pct": -8.27, "amount_yi": 3.05, "intraday_state": "高开转弱、接近日内低点"},
        {"rank": 5, "name": "盛科通信-U", "role": "交换芯片", "change_pct": -8.88, "amount_yi": 17.41, "intraday_state": "跌破开盘并接近日内低点"},
        {"rank": 6, "name": "共进股份", "role": "ODM制造", "change_pct": -9.98, "amount_yi": 12.43, "intraday_state": "跌停，六次开板后仍未形成有效承接"},
        {"rank": 7, "name": "紫光股份", "role": "整机/平台", "change_pct": -9.99, "amount_yi": 83.07, "intraday_state": "跌停且成交高度集中，负反馈最重"},
    ],
    "technology_order_validation": "未取得400G/800G/1.6T、AI/白盒交换机、Spectrum-X新增客户验证、订单、量产、收入占比或毛利改善公告；半年度订单、收入、库存、应收和产能利用率也无新增证据。",
    "cross_market": "隔夜Arista-6.92%、Cisco-2.68%、Broadcom-2.78%、Marvell-6.34%、NVIDIA-3.55%；10:21恒生科技-0.70%、中兴H-1.67%，海外整机、交换芯片、GPU网络生态与A/H均未形成正向共振。",
    "upgrade_condition": "至少2至3只整机/ODM/交换芯片核心同步放量收复开盘价，通信设备脱离末位，紫光和共进打开跌停且炸板不扩大。",
    "invalidate_condition": "紫光、共进继续跌停或高成交核心继续创新低；只有CPO单独反抽而整机、ODM、交换芯片不跟，仍按主线未确认。",
    "operation_risk": "题材级只观察跌停打开和低位扩散；代表股级先看中兴、锐捷能否稳住日内低点以及紫光、共进能否打开跌停，不给确定性买卖指令。",
}

fiberglass_watch = {
    "conclusion": "反抽失败/再度退潮，列风险线",
    "jushi_classification": "中国巨石冲高回落至-2.97%并贴近日内低点，国际复材由早盘约+4%收窄至+1.32%；上游与PCB未同步，定性为反抽失败。",
    "upstream_core": [
        {"name": "国际复材", "change_pct": 1.32, "assessment": "仍红盘但明显冲高回落，单股不足以确认板块"},
        {"name": "中国巨石", "change_pct": -2.97, "assessment": "冲高回落至低点，中军承接转弱"},
    ],
    "repair_samples": [
        {"name": "山东玻纤", "change_pct": -4.54}, {"name": "长海股份", "change_pct": -1.32},
        {"name": "宏和科技", "change_pct": -9.25}, {"name": "东材科技", "change_pct": -8.14},
        {"name": "中材科技", "change_pct": -4.17}, {"name": "南玻A", "change_pct": 1.03},
    ],
    "secondary_feedback": [
        {"name": "卓郎智能", "change_pct": -4.69}, {"name": "兴业股份", "change_pct": -4.78},
        {"name": "国风新材", "change_pct": 5.46, "assessment": "炸板，二排情绪锚不构成主线"},
    ],
    "pcb_feedback": [
        {"name": "胜宏科技", "change_pct": -7.97}, {"name": "沪电股份", "change_pct": -8.05},
        {"name": "生益科技", "change_pct": -7.34}, {"name": "鹏鼎控股", "change_pct": -8.95},
        {"name": "东山精密", "change_pct": -10.00}, {"name": "景旺电子", "change_pct": -7.47},
        {"name": "世运电路", "change_pct": -2.91},
    ],
    "evidence": [
        "中国巨石-2.97%且处于日内低点，国际复材+1.32%但从31.90元高点明显回落。",
        "山东玻纤-4.54%、宏和科技-9.25%、东材科技-8.14%、中材科技-4.17%，上游/电子布未形成2至3只同步修复。",
        "PCB核心全部下跌，东山精密跌停，胜宏、沪电、生益、鹏鼎、景旺均跌超7%，下游负反馈继续扩大。",
        "国风新材+5.46%但已经炸板，卓郎和兴业走弱，属于二排异动而非主线。",
    ],
    "relative_strength": "显著弱于消费防御和汽车强线，也弱于财税软件观察线；当前不是资金回流或有效反抽。",
    "upgrade_condition": "至少2至3只上游/电子布核心同步翻红或大幅收敛，PCB核心离开低点，跌停和炸板减少，并出现新增大涨样本。",
    "invalidate_condition": "中国巨石、国际复材继续回落，宏和/东材与PCB核心扩大跌幅，维持风险线并放弃弱反弹。",
    "next_check": "11:00核对中国巨石能否离开低点、国际复材能否重回3%以上，以及东山跌停和PCB跌幅是否收缩。",
}

style_radar = {
    "status": "风格切换风险进一步确认",
    "evidence": [
        "白酒核心全线上涨：贵州茅台+2.51%、五粮液+4.48%、山西汾酒+5.19%、泸州老窖+3.71%、洋河股份+5.46%。",
        "畜牧核心全线上涨，牧原+2.34%、温氏+2.07%；白酒+畜牧满足双方向同向走强条件。",
        "保险获得部分承接：中国太保+2.82%、中国平安+1.40%；券商仅东方财富+0.60%，金融共振仍不完整。",
        "科创50-4.04%、创业板-3.87%，通信设备-8.69%、半导体-5.26%，科技明显弱于消费防御。",
    ],
    "condition_to_reverse": "消费封板快速减少、白酒畜牧核心跌回开盘，同时科创50和科技高成交核心成组收复开盘。",
}

main_trends = [
    {
        "name": "白酒/食品酒店/畜牧消费防御",
        "status": "强主线/风格切换确认",
        "evidence": [
            "10:32白酒行业+3.25%、酒店餐饮+3.26%、食品饮料+2.70%，消费相关9只普通股封板。",
            "舍得酒业封板，茅台+2.51%、五粮液+4.48%、山西汾酒+5.19%、洋河+5.46%；畜牧五只样本全部上涨。",
            "爱丽家居8连板、华天酒店4连板，高位拥挤仍是主要风险；若封板减少且白酒权重跌回开盘，强度降级。",
        ],
    },
    {
        "name": "汽车整车/零部件",
        "status": "强主线/扩散但分歧加大",
        "evidence": [
            "商用车行业+3.68%，江淮汽车、浙江世宝、明新旭腾、大明电子、纳百川、文灿股份、至信股份共7只封板。",
            "纳百川20cm、江淮汽车成交约16.56亿元，兼具弹性与中军；但飞龙股份、祥鑫科技跌停，分支内部强分歧。",
            "若江淮或20cm前排炸板、汽车跌停继续增加，则由强主线降为分化观察。",
        ],
    },
    {
        "name": "财税数字化/软件/教育",
        "status": "观察线偏强/涨停扩散",
        "evidence": [
            "恒锋信息、普联软件20cm封板，南天信息、税友股份、中科金财、苏州科达、传智教育、学大教育封板。",
            "软件ETF+1.20%，在成长指数深跌时体现抱团承接；本轮概念排行接口空返回，沿用10:05已核验方向但不冒充10:30概念幅度。",
            "只有板块继续新增低位封板且20cm前排不炸板，才可升级；单纯抱团不视为全科技修复。",
        ],
    },
    {
        "name": "农化/农药兽药",
        "status": "观察线偏强/低位扩散",
        "evidence": [
            "利尔化学、美邦股份、高争民爆封板，农化维持3只扩散。",
            "利尔化学已有两次开板，若再度炸板且后排不增，按低位轮动而非持续主线。",
        ],
    },
    {
        "name": "存储/HBM个别抗跌",
        "status": "资金博弈线/不构成主线",
        "evidence": [
            "德明利+1.81%、佰维存储-0.41%相对抗跌，但兆易创新-3.69%、澜起科技-3.21%，半导体行业-5.26%。",
            "港股兆易+1.10%仍是单股资本动作映射，澜起H-2.67%、华虹-7.09%、中芯-4.32%，A/H没有成组确认。",
            "需至少3只存储核心同步翻红、半导体跌停减少后才继续观察承接。",
        ],
    },
    {
        "name": "半导体设备/材料/零部件",
        "status": "风险线/负反馈扩大",
        "evidence": [
            "半导体行业-5.26%，科创半导体ETF-6.02%、科创芯片ETF-5.77%；至纯科技、通富微电、瑞芯微跌停。",
            "设备：北方-4.03%、中微-3.26%、拓荆-4.35%、华海-5.63%、芯源微-11.22%、中科飞测-6.78%。",
            "材料：雅克-9.99%、安集-7.64%、有研硅-13.11%、江丰-7.78%；零部件富创-5.17%、正帆-7.24%、新莱-8.61%、华海诚科-7.84%。",
            "日本设备早盘正映射没有传导，且没有订单、收入、毛利或产能利用率新增证据，盘前科技假设继续被证伪。",
        ],
    },
    {
        "name": "CPO/光模块/AI硬件",
        "status": "风险线/高成交放量下杀",
        "evidence": [
            "中际旭创-12.72%、成交293.15亿元；新易盛-14.50%、成交189.23亿元；天孚-11.24%、光迅跌停、光库-9.41%。",
            "通信设备居行业末位，剑桥科技跌停、永鼎股份炸板；没有CPO低位扩散或港股正向共振。",
            "高成交核心仍靠近日内低点，当前不属于资金博弈反抽。",
        ],
    },
    {
        "name": "交换机/高速以太网",
        "status": "风险线/交换机主线未确认",
        "evidence": [switch_special["market_structure"], switch_special["cross_market"], switch_special["technology_order_validation"]],
    },
    {
        "name": "电子布/玻纤与PCB",
        "status": "风险线/反抽失败",
        "evidence": fiberglass_watch["evidence"],
    },
    {
        "name": "医药修复",
        "status": "观察线降温/AH不共振",
        "evidence": [
            "联环药业封板但海南海药炸板；医药ETF持平、创新药ETF-1.73%。",
            "10:21港股药明康德-1.39%、药明生物-2.39%、百济神州-0.90%，竞价强势已经消退。",
            "CRO/创新药未形成A/H扩散，保持观察，不作为强主线。",
        ],
    },
]

actions = [
    {"priority": 1, "tier": "主动作", "action": "风险释放。科技题材级先等跌停、跌超5%和高成交抛压收缩；代表股级看中际旭创、新易盛、紫光股份、东山精密能否离开日内低点，不抢第一轮反弹。"},
    {"priority": 2, "tier": "强主线", "action": "消费防御和汽车只跟踪封板留存、权重承接与低位扩散；爱丽家居8板不追，汽车内部已有两只跌停，炸板或跌停增加时等待二次确认。"},
    {"priority": 3, "tier": "观察线", "action": "财税软件、农化只看成组放量和后排扩散；核心单强、概念排行缺失或20cm前排炸板时不升级。"},
    {"priority": 4, "tier": "资金博弈线", "action": "存储仅个别抗跌，不是强主线；电子布/玻纤已经从弱修复转为反抽失败，未出现核心翻红、资金回流和跌停减少前放弃弱反弹。"},
    {"priority": 5, "tier": "风险线", "action": "半导体、CPO、交换机、PCB继续放量下跌并扩大跌停，降低博弈频率、避免抢反弹；观察池仅作代表样本，不替代全市场结论。"},
]

intraday = load("intraday.json")
intraday.update({
    "timestamp": STAMP,
    "analysis_as_of": STAMP,
    "analysis_phase": "10:30盘中更新（真实行情10:32-10:36）",
    "phase": "上午交易",
    "session": "盘中",
    "summary": "10:30后消费与汽车仍维持封板扩散，但科技尾部风险继续扩大：普通股涨停46只、跌停12只，跌超5%增至542只，科创50跌逾4%，科技当前仍是风险释放而非可交易反抽。",
    "primary_action": "风险释放",
    "limit_up_count": 47,
    "limit_down_count": 13,
    "limit_diff": 34,
    "limit_ratio": 3.62,
    "broken_count": 7,
    "broken_limit_count": 7,
    "broken_rate_pct": 13.21,
    "market_breadth": {"up": 2716, "down": 2647, "flat": 170, "denominator": 5533, "up_5_count": 132, "down_5_count": 542, "up_8_count": 61, "down_8_count": 158, "turnover_yi_estimate": 10551.34},
    "sentiment": {
        "open_style": "强分歧/风格切换",
        "judgement": "涨停由10:10的43只增至47只，但跌停由5只增至13只，涨跌停同时扩张；跌超5%由309只增至542只，科技风险明显扩大。",
        "limit_up_count": 47, "limit_down_count": 13, "limit_diff": 34,
        "limit_up_share_pct": 0.8494, "limit_down_share_pct": 0.2350, "limit_ratio": 3.62,
        "denominator": 5533, "broken_count": 7, "broken_rate_pct": 13.21,
        "up_count": 2716, "down_count": 2647, "flat_count": 170,
        "comparison_to_previous": "10:10至10:33：涨停43→47、跌停5→13、跌超5% 309→542、跌超8% 74→158，风险扩张速度显著快于封板扩张。",
        "evidence": [
            "10:32上证-0.41%、深成指-2.43%、创业板-3.87%、科创50-4.04%、沪深300-1.27%。",
            "行业前五为商用车+3.68%、酒店餐饮+3.26%、白酒+3.25%、调味发酵品+2.82%、食品饮料+2.70%。",
            "行业后五为通信设备-8.69%、元件-6.75%、半导体-5.26%、电子-5.09%、消费电子-4.77%。",
            "普通股封板46只、跌停12只、炸板7只；全A上涨2716、下跌2647，但跌超5%有542只。",
        ],
        "next_check": "11:00重点看科技跌停和跌超5%数量是否收缩、科创50是否停止创新低，以及消费/汽车封板能否在分歧中留存。",
    },
    "market_snapshot": {
        "trade_date": "2026-07-30",
        "full_market_quote_time": "2026-07-30 10:33:46",
        "index_industry_quote_time": "2026-07-30T10:32:03+08:00",
        "representative_quote_time": "2026-07-30 10:36:36-10:36:42",
        "collected_at": STAMP,
        "valid_sample_count": 5533,
        "breadth": {"up_count": 2716, "down_count": 2647, "flat_count": 170, "up_5_count": 132, "down_5_count": 542, "up_8_count": 61, "down_8_count": 158, "judgement": "上涨下跌家数接近，但下跌尾部极厚，跌超5%和8%数量远高于上涨同阈值，属于强分歧风险扩张。"},
        "limit_structure": {"limit_up_count": 47, "limit_up_ordinary_count": 46, "limit_up_st_count": 1, "limit_down_count": 13, "limit_down_ordinary_count": 12, "limit_down_st_count": 1, "limit_diff": 34, "limit_up_share_pct": 0.8494, "limit_down_share_pct": 0.2350, "limit_ratio": 3.62, "broken_count": 7, "broken_rate_pct": 13.21, "highest_board": "爱丽家居8连板", "twenty_cm_limit_up": ["恒锋信息", "普联软件", "纳百川", "昊创瑞通"], "comparison_to_previous": "较10:10涨停43→47、跌停5→13；涨跌停同时增加，且跌停扩张更快。", "scope_note": "腾讯全A5533只有效样本；涨跌停合计含各1只ST，不含N/C无涨跌幅限制新股。炸板率按东财普通股封板46只与炸板7只计算。"},
        "limit_up_pool": limit_up_groups,
        "limit_down_pool": limit_down_pool,
        "broken_pool": broken_pool,
        "top_turnover_risk": ["中际旭创-12.72%、成交293.15亿元", "新易盛-14.50%、成交189.23亿元", "东山精密跌停、成交111.12亿元", "紫光股份跌停、成交83.07亿元", "通富微电跌停、成交约64.83亿元"],
        "turnover_yi_estimate": 10551.34,
        "turnover_note": "上证指数与深证成指成交额字段合计代理值，不等同于剔重后的全A成交额。",
    },
    "main_trends": main_trends,
    "themes": [{**item, "tier": ("强主线" if "强主线" in item["status"] else "观察线" if "观察线" in item["status"] else "资金博弈线" if "资金博弈" in item["status"] else "风险线")} for item in main_trends],
    "actions": actions,
    "style_radar": style_radar,
    "style_rotation_radar": style_radar,
    "switch_chain_special": switch_special,
    "switch_chain_tracking": switch_special,
    "switch_special": switch_special,
    "electronic_cloth_fiberglass_watch": fiberglass_watch,
    "electron_cloth_rotation": fiberglass_watch,
    "fiberglass_special": fiberglass_watch,
    "fiberglass_rotation_special": fiberglass_watch,
    "cross_market": {"hk_market_time": "2026-07-30 10:21（免费行情约延迟15分钟）", "hk": "恒指+0.15%、恒生科技-0.70%；兆易H+1.10%、五一视界+3.99%，但澜起H-2.67%、华虹-7.09%、中芯-4.32%、智谱-10.45%、中兴H-1.67%。", "japan_korea": "沿用09:18已核验快照：日本设备/测试偏强、SK hynix偏弱；A股设备未跟随日本正映射。", "judgement": "A/H科技与海外硬件缺乏成组正共振，港股少数单股强势不足以抵消A股科技高成交负反馈。"},
    "hk_market": {"quote_time": "2026-07-30 10:21", "delayed": True, "hsi_pct": 0.15, "hstech_pct": -0.70, "assessment": "港股科技偏弱且报价延迟，仅作A/H方向映射。"},
    "hypothesis_tracking": {"premarket_tech_hypothesis": "证伪", "reason": "半导体设备、材料、零部件、CPO、交换机和PCB均出现行业后排、跌停或高成交深跌；消费和汽车取代科技成为盘面强线。", "expansion_iteration_bom_token": "盘中未获得新增订单、客户验证、量产、收入占比、毛利或产能利用率证据；扩产与技术迭代叙事不能对冲交易端风险。"},
    "premarket_hypothesis": {"status": "科技映射证伪/分化预判确认", "assessment": "盘前分化型开盘预判成立，但科技映射不只未扩散，反而演化为高成交风险释放。", "H1": "部分确认：高BOM硬件的价格与估值承接出现明显天花板。", "H2": "暂未交易确认：扩产解决紧缺未成为全市场主线。", "H3": "暂未验证：没有新增客户验证、订单、量产或收入占比证据。", "H4": "暂未验证：国产算力缺少订单、库存、授信、物料、收入和毛利成组验证，交易端反而走弱。", "H5": "盘面证伪：电子布/玻纤冲高回落且PCB成片深跌，涨价链资金承接失败。"},
    "opportunity_watch_updates": [
        {"theme": "老登风格切换", "status": "confirmed", "evidence": ["白酒与畜牧双方向同向走强，科技指数和科技行业显著走弱"]},
        {"theme": "交换机/高速以太网", "status": "invalidated", "evidence": ["通信设备-8.69%，紫光和共进跌停，固定七核心无扩散"]},
        {"theme": "CPO/光模块", "status": "invalidated", "evidence": ["中际、新易盛、天孚成组跌超11%，光迅和剑桥跌停"]},
        {"theme": "半导体设备材料", "status": "invalidated", "evidence": ["设备、材料、零部件成组走弱，半导体ETF跌约6%"]},
        {"theme": "PCB/电子布", "status": "invalidated", "evidence": ["中国巨石冲高回落，东山跌停，PCB核心成片跌超7%"]},
    ],
    "configured_portfolio_risk": {"status": "半导体ETF第一层风险信号继续强化", "evidence": "10:32科创半导体ETF-6.02%、科创芯片ETF-5.77%，配置核心和Alpha层成组走弱。", "configured_action": "研究层继续执行alert-config的分层观察与ETF回撤约束；系统不掌握持仓和成本，不执行交易。", "boundary": "不修改用户资产；实际仓位、成本与止损由用户自行核对。"},
    "source_status": "degraded_concept_and_hk_delay",
    "data_status": "全A、指数、行业、涨跌停结构和代表股可核验；概念排行空返回、港股约延迟15分钟。",
    "data_quality": {"status": "degraded", "detail": ["新浪代码主表取得5533只代码，腾讯批量报价5533只全部有效。", "腾讯五大指数、98个行业和专项代表股报价成功。", "东财涨停46、跌停12、炸板7的普通股结构数据成功。", "东财概念排行本轮空返回，保留10:05已核验方向但不冒充10:30概念幅度。", "腾讯港股行情约延迟15分钟，只作A/H方向映射。"]},
    "sources": [
        {"name": "腾讯财经HTTP", "usage": "全A实时行情、指数、行业、观察池与专项报价", "market_time": "10:32-10:36", "status": "ok"},
        {"name": "新浪全A节点", "usage": "全A代码主表", "market_time": "10:32-10:33", "status": "ok"},
        {"name": "东方财富push2ex", "usage": "涨停池、跌停池、炸板池、连板与行业归属", "market_time": "约10:34", "status": "ok"},
        {"name": "东方财富push2", "usage": "概念排行", "market_time": "10:34请求", "status": "degraded_empty_preserve_previous"},
        {"name": "腾讯港股行情", "usage": "恒指、恒科及港股映射", "market_time": "10:21", "status": "delayed"},
        {"name": "配置文件", "usage": "watchlist、alert-config、topics-list", "market_time": "本轮读取", "status": "ok"},
    ],
    "disclaimer": "仅作研究跟踪和风险管理参考，不构成投资建议。",
})
write_atomic("intraday.json", intraday)

topics = load("topics.json")
updates = {
    "半导体设备": ("风险", "等待北方华创、中微公司、拓荆科技、华海清科、芯源微、中科飞测至少3只同步收复开盘，半导体行业脱离后排且ETF止跌后再恢复观察。", "10:36半导体行业-5.26%、科创半导体ETF-6.02%；设备六核心全部下跌，芯源微-11.22%、中科飞测-6.78%，至纯科技跌停，无涨停扩散和业绩新增证据。"),
    "半导体材料": ("风险", "雅克、安集、沪硅、有研硅、江丰、南大至少3只放量收复开盘且半导体跌停减少前，不做反抽升级。", "雅克-9.99%、安集-7.64%、沪硅-5.09%、有研硅-13.11%、江丰-7.78%、南大-5.89%，材料成组深跌，没有价格、订单、毛利或产能利用率新增验证。"),
    "半导体零部件": ("风险", "富创、新莱、正帆、华海诚科、长川至少3只同步收复开盘且设备主线止跌后，再评估订单外溢。", "富创-5.17%、新莱-8.61%、正帆-7.24%、华海诚科-7.84%、长川-5.31%，分支无涨停和低位补涨，零部件弹性继续弱化。"),
    "交换机/高速以太网": ("风险", "紫光与共进打开跌停，且中兴/锐捷/工业富联/盛科至少3只同步收复开盘前，不抢反弹。", "通信设备-8.69%，紫光和共进跌停，菲菱-8.27%、盛科-8.88%、工业富联-7.15%；七核心无涨停，永鼎炸板，交换机主线未确认。"),
    "科技硬件链": ("风险", "等待通信设备、元件、半导体至少两个行业跌幅收窄，科创50停止创新低且高成交核心离开日内低点。", "科创50-4.04%，通信设备-8.69%、元件-6.75%、半导体-5.26%；中际、新易盛、东山、紫光等高成交核心集中深跌，科技风险扩张。"),
    "老登风格切换": ("强化", "验证白酒、畜牧、酒店食品至少两类继续强于科技；高位消费炸板增加时不追。", "白酒+3.25%、酒店餐饮+3.26%，白酒与畜牧核心全线上涨；科创50-4.04%、创业板-3.87%，风格切换风险进一步确认。"),
    "电子布/玻纤轮动": ("风险", "等待中国巨石离开低点、国际复材重回3%以上且PCB核心跌幅成组收窄，再评估反抽。", "中国巨石-2.97%、国际复材+1.32%冲高回落；宏和-9.25%、东材-8.14%，东山跌停且PCB核心成片跌超7%，反抽失败。"),
    "PCB/电子布": ("风险", "只有上游2至3只同步翻红、PCB核心离开低点并伴随跌停减少，才恢复资金博弈观察。", "国际复材单股红盘不能抵消中国巨石回落和PCB成片深跌；国风新材炸板，不构成板块修复。"),
    "光模块/CPO": ("风险", "等待中际、新易盛、天孚、光迅至少3只离开日内低点，通信设备跌幅显著收窄后再观察。", "中际-12.72%、新易盛-14.50%、天孚-11.24%，光迅和剑桥跌停，高成交抛压继续扩大。"),
    "CPO/光模块": ("风险", "等待中际、新易盛、天孚、光迅至少3只离开日内低点，通信设备跌幅显著收窄后再观察。", "中际-12.72%、新易盛-14.50%、天孚-11.24%，光迅和剑桥跌停，高成交抛压继续扩大。"),
}
for topic in topics.get("topics", []):
    values = updates.get(topic.get("name"))
    if not values:
        continue
    topic["status"], topic["action"], topic["note"] = values
    topic["updated_at"] = STAMP
    topic["last_checked_at"] = STAMP
topics["timestamp"] = STAMP
write_atomic("topics.json", topics)

health = load("source-health.json")
health["timestamp"] = STAMP
health.update({
    "sina_all_a_code_master_intraday_1033_20260730": {"status": "ok", "checked_at": STAMP, "market_time": "2026-07-30 10:32-10:33", "usage": "腾讯全A批量报价的代码主表", "sample_count": 5533, "evidence": "新浪节点分页去重5533个代码。", "errors": []},
    "tencent_all_a_intraday_1033_20260730": {"status": "ok", "checked_at": STAMP, "market_time": "2026-07-30 10:33:46", "usage": "全A宽度、涨跌停、成交与专项代表股", "sample_count": 5533, "evidence": "5533只全部有效；上涨2716、下跌2647、跌超5%有542只。", "errors": []},
    "tencent_index_industry_intraday_1032_20260730": {"status": "ok", "checked_at": STAMP, "market_time": "2026-07-30 10:32:03", "usage": "五大指数、98行业与成交代理", "sample_count": 103, "evidence": "科创50-4.04%、创业板-3.87%；商用车/酒店/白酒居前，通信设备/元件/半导体居后。", "errors": []},
    "eastmoney_structure_pools_intraday_1034_20260730": {"status": "ok", "checked_at": STAMP, "market_time": "2026-07-30 约10:34", "usage": "普通股涨停池、跌停池、炸板池、连板与行业归属", "sample_count": 65, "evidence": "普通股封板46只、跌停12只、炸板7只；爱丽家居8连板，4只20cm封板。", "errors": []},
    "eastmoney_concept_ranking_intraday_1034_20260730": {"status": "degraded_preserve_previous", "checked_at": STAMP, "usage": "10:30概念排行、涨跌宽度与资金方向", "sample_count": 0, "evidence": "单次串行请求空返回；保留10:05已核验方向，不冒充10:30概念幅度。", "errors": ["Empty reply from server"]},
    "tencent_special_quotes_intraday_1036_20260730": {"status": "ok", "checked_at": STAMP, "market_time": "2026-07-30 10:36:36-10:36:42", "usage": "消费、金融、交换机、玻纤PCB、半导体与CPO代表股", "sample_count": 62, "evidence": "代表股均返回可核验现价、涨跌幅、日高低和成交额。", "errors": []},
    "tencent_hk_delayed_intraday_1021_20260730": {"status": "degraded", "checked_at": STAMP, "market_time": "2026-07-30 10:21", "usage": "10:30 A/H方向映射", "sample_count": 13, "evidence": "恒指+0.15%、恒科-0.70%；兆易H+1.10%，华虹-7.09%、中芯-4.32%、智谱-10.45%。", "errors": ["免费港股报价相对A股检查点延迟约15分钟"]},
})
write_atomic("source-health.json", health)

print("updated intraday.json, topics.json, source-health.json")
