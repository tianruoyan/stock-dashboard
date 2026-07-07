# Stock Dashboard Version Log

| Display Version | Date | Edition | Tag / Commit | Summary | Rollback Note |
|---|---:|---:|---|---|---|
| 2026-07-07 第38版｜审计前置发布 | 2026-07-07 | 第38版 | tag: `v2026.07.07-m38-audit-before-push` | 新增 `scripts/push_with_audit.sh` 标准发布入口；自动化写完 JSON 后先生成 `quality-report.json`，critical 时不发布；同花顺观察池同步后也自动运行数据审计再触发 `.push-now`。 | 回滚到第37版可用 `git checkout v2026.07.07-m37-data-audit`，或回滚到本版本 tag。 |
| 2026-07-07 第37版｜数据审计管道 | 2026-07-07 | 第37版 | tag: `v2026.07.07-m37-data-audit` | 新增 `scripts/audit_dashboard_data.py` 和 `data/quality-report.json`，将 JSON 解析、坏字面量、过期时间戳、污染 alert、降级数据源、观察池异常涨跌幅、盘后/晚间必填字段纳入自动审计，并由看板数据质量闸门优先读取审计报告。 | 回滚到第36版可用 `git checkout v2026.07.07-m36-quality-radar`，或回滚到本版本 tag。 |
| 2026-07-07 第36版｜数据闸门-机会风险雷达 | 2026-07-07 | 第36版 | tag: `v2026.07.07-m36-quality-radar` | 第一屏新增数据质量闸门和主动机会/风险雷达：先提示数据是否降级、污染或过期，再从主线、观察池、涨跌停宽度、尾盘校验里主动提炼机会候选、风险提示和下一步验证条件。 | 回滚到第35版可用 `git checkout v2026.07.07-m35-alert-source-fix`，或回滚到本版本 tag。 |
| 2026-07-07 第35版｜异动数据源校验 | 2026-07-07 | 第35版 | tag: `v2026.07.07-m35-alert-source-fix` | 撤下 14:13 异常 alert 批次；观察池分类在已有收盘数据时不再使用盘中 alert 覆盖；老登小登提醒改为优先使用行情源原始涨跌幅，避免错误昨收/解码异常导致个股被误标跌停或大跌。 | 回滚到第34版可用 `git checkout v2026.07.07-m34-watch-strength`，或回滚到本版本 tag。 |
| 2026-07-07 第34版｜观察池强弱分层 | 2026-07-07 | 第34版 | tag: `v2026.07.07-m34-watch-strength` | 观察池从“触发/风险/承压”改为“强势股/弱势股/一般股”，结合所在主线、个股当日涨跌、涨停/封板/放量等资金强度信号判定，避免涨停股被旧风险文本误归类。 | 回滚到第33版可用 `git checkout v2026.07.05-m33-panel-style-unify`，或回滚到本版本 tag。 |
| 2026-07-05 第33版｜全板块结论风格统一 | 2026-07-05 | 第33版 | tag: `v2026.07.05-m33-panel-style-unify` | 将第32版的“核心结论 + 关联题材 + 回避/降级 + 下一步验证”口径同步到总控、盘中异动、盘中全景、早盘、午盘、盘后、晚间舆情等前置板块。 | 回滚到第32版可用 `git checkout v2026.07.05-m32-topic-integration`，或回滚到本版本 tag。 |
| 2026-07-05 第32版｜7月题材整合-结论优先 | 2026-07-05 | 第32版 | tag: `v2026.07.05-m32-topic-integration` | 7月投资点分散时，专题从细分清单升级为母题材聚合：科技硬件链、机器人/工业自动化、医药修复链、老登风格切换、回避/降级集合；页面突出核心结论和关联题材。 | 回滚到第31版可用 `git checkout v2026.07.04-m31-control-watchlist-risk-review`，或回滚到本版本 tag。 |
| 2026-07-04 第31版｜总控-观察池-仓位风控-信号复盘 | 2026-07-04 | 第31版 | tag: `v2026.07.04-m31-control-watchlist-risk-review` | 个性化高时效辅助决策改造：今日总控、观察池决策、仓位风控、信号复盘、信息减负。 | 回滚到上一稳定版本可用 `git checkout 8f29b88`，或回滚到本版本 tag。 |
| 2026-07-04 第30版｜七区聚焦摘要 | 2026-07-04 | 第30版 | `8f29b88` | 完成七个核心区的聚焦摘要：异动、全景、盘前、午盘、盘后、晚间、专题。 | 当前大版本前的稳定展示版本。 |
| 2026-07-04 第23版｜设置页和说明书独立 | 2026-07-04 | 第23版 | `52aa978` | 设置页独立化，分析模型说明书独立化。 | 回滚到较早的配置/说明书页面版本。 |

## Naming Rule

- 页面显示使用中文解释名：`2026-07-05 第33版｜全板块结论风格统一`。
- Git tag 使用英文安全名：`v2026.07.05-m33-panel-style-unify`。
- `m33` 是页面缓存版本；“第33版”是给人看的迭代序号；后面的中文短语说明主要修改点。
- 大版本命名必须能回答：“这版主要改了什么？”

## Rollback Commands

```bash
# 查看版本点
git tag --list "v2026.07.04*"
git log --oneline -10

# 临时查看某版本
git checkout v2026.07.04-m31-control-watchlist-risk-review

# 回滚到上一稳定版本并重新发布
git checkout main
git revert 8f29b88..HEAD
git push
```

## Version Rule

- 每次大范围 UI、数据结构、自动化规则或风控逻辑变更，都新增一行版本记录。
- 小修小补只需要 commit；影响回滚判断的改动才升级版本号。
- 页面显示格式：`YYYY-MM-DD 第N版｜中文主要修改点`。
- tag 格式：`vYYYY.MM.DD-m序号-english-keywords`。
