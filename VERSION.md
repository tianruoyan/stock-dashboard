# Stock Dashboard Version Log

| Display Version | Date | Edition | Tag / Commit | Summary | Rollback Note |
|---|---:|---:|---|---|---|
| 2026-07-07 第67版｜失败数据源审计 | 2026-07-07 | 第67版 | tag: `v2026.07.07-m67-source-failed-audit` | 数据审计把 `source-health.json` 中的 `failed` 状态纳入质量报告，输出 `source_failed` warning；港股结构源等直接失败时不再只依赖盲区/可信度报告提示，而是在顶部数据质量卡中同步降权。 | 回滚到第66版可用 `git checkout v2026.07.07-m66-unplanned-theme-scan`，或回滚到本版本 tag。 |
| 2026-07-07 第66版｜非预设新线扫描 | 2026-07-07 | 第66版 | tag: `v2026.07.07-m66-unplanned-theme-scan` | `decision-feed` 新增非预设盘面扫描：从盘后热点中识别不在既有专题精确清单里、但出现涨停池/强势组/轮动增强证据的方向，生成“新线观察”候选；当前数据降级时仍按 C/D 级转入验证栏。静态烟雾测试新增门禁，确保非预设活跃方向必须进入机会或验证流。 | 回滚到第65版可用 `git checkout v2026.07.07-m65-radar-trigger-reason`，或回滚到本版本 tag。 |
| 2026-07-07 第65版｜雷达触发原因 | 2026-07-07 | 第65版 | tag: `v2026.07.07-m65-radar-trigger-reason` | `decision-feed` 每条机会、风险和验证新增 `trigger_reason`，用一句话解释系统为什么把该信号推入雷达；前端雷达卡片新增“触发”详情行。数据审计、静态烟雾和运行时烟雾测试同步要求触发原因存在并渲染，避免主动提示只有结论、缺少触发逻辑。 | 回滚到第64版可用 `git checkout v2026.07.07-m64-render-coverage`，或回滚到本版本 tag。 |
| 2026-07-07 第64版｜关键字段渲染门禁 | 2026-07-07 | 第64版 | tag: `v2026.07.07-m64-render-coverage` | 运行时烟雾测试新增“核心 JSON 字段必须渲染”检查：盘中 summary/主线/行动建议/港股快照、早盘 summary、午盘复盘和下午信号、盘后收盘竞价补丁和热点、专题首项都必须出现在对应页面区块。盘中全景补渲染 `summary`，并兼容 `index.HK_close_window_snapshot`，同时主线卡显示整合名和原始细分名，减少漏显和颗粒度误读。 | 回滚到第63版可用 `git checkout v2026.07.07-m63-alert-source-gate`，或回滚到本版本 tag。 |
| 2026-07-07 第63版｜异动可信源门禁 | 2026-07-07 | 第63版 | tag: `v2026.07.07-m63-alert-source-gate` | 数据审计新增 `validate_alert`：盘中异动非空时必须具备可信行情源证明；若污染源仍降级且 active alerts 缺少腾讯/mootdx/通达信/已审计源等证明，直接标为 critical 阻断发布。同时校验 alerts 基础字段、leaders 涨跌幅数值和异常 3 分钟涨跌幅。 | 回滚到第62版可用 `git checkout v2026.07.07-m62-opportunity-gating`，或回滚到本版本 tag。 |
| 2026-07-07 第62版｜降权机会转验证 | 2026-07-07 | 第62版 | tag: `v2026.07.07-m62-opportunity-gating` | 机会/风险雷达只把 A/B 级且非“降权/仅复核/等待确认”的信号放入机会候选栏；C/D 级机会自动转入“下一步验证”，保留证据、缺口和证伪条件。运行时烟雾测试新增门禁，防止 C/D 级降权机会再次进入机会栏。 | 回滚到第61版可用 `git checkout v2026.07.07-m61-automation-diagnosis`，或回滚到本版本 tag。 |
| 2026-07-07 第61版｜自动化异常诊断 | 2026-07-07 | 第61版 | tag: `v2026.07.07-m61-automation-diagnosis` | `automation-health` 每个进程新增 `failure_type/diagnosis/next_actions/related_sources`，把盘中异动异常区分为数据源污染批次撤下、产出缺失、时间戳异常或等待窗口；顶部质量卡显示异常类型和第一处理动作。盘前“日韩早盘”降级时只显示固定待复核清单，不再展开疑似乱码或未核实源文本。 | 回滚到第60版可用 `git checkout v2026.07.07-m60-automation-heartbeat`，或回滚到本版本 tag。 |
| 2026-07-07 第60版｜自动化心跳 | 2026-07-07 | 第60版 | tag: `v2026.07.07-m60-automation-heartbeat` | 新增 `scripts/build_automation_health.py` 和 `data/automation-health.json`，按盘前、盘中全景、盘中异动、午盘、盘后、晚间舆情、专题跟踪检查自动化是否按时产出、是否撤下或等待中；顶部质量卡新增“自动化心跳”，统一构建报告可显示 degraded 但非阻断发布。 | 回滚到第59版可用 `git checkout v2026.07.07-m59-unified-build`，或回滚到本版本 tag。 |
| 2026-07-07 第59版｜统一构建入口 | 2026-07-07 | 第59版 | tag: `v2026.07.07-m59-unified-build` | 新增 `scripts/build_dashboard_reports.py` 和 `data/build-report.json`，统一按依赖顺序生成主线变化、机会风险流、数据审计、文件可信度、监测盲区、区块健康、静态烟雾和运行时烟雾报告；`push_with_audit.sh` 改为调用统一入口，降低衍生数据版本错位导致的不稳定。 | 回滚到第58版可用 `git checkout v2026.07.07-m58-theme-shifts`，或回滚到本版本 tag。 |
| 2026-07-07 第58版｜主线变化雷达 | 2026-07-07 | 第58版 | tag: `v2026.07.07-m58-theme-shifts` | 新增 `scripts/build_theme_shifts.py` 和 `data/theme-shifts.json`，从盘中全景、盘后热点、专题跟踪中识别升温、新线、抱团、降温和风险变化；`decision-feed` 将主线变化并入机会/风险/验证栏，雷达显示“主线变化扫描”，发布门、文件可信度和区块健康同步纳入该文件。 | 回滚到第57版可用 `git checkout v2026.07.07-m57-freshness-sla`，或回滚到本版本 tag。 |
| 2026-07-07 第57版｜数据新鲜度SLA | 2026-07-07 | 第57版 | tag: `v2026.07.07-m57-freshness-sla` | `data-trust` 新增 `freshness_status/age_minutes/freshness_action/freshness_reason`，给盘中异动、盘中全景、盘前、午盘、盘后、晚间、专题和机会风险流分别设置刷新 SLA；当前阶段文件超时会自动降权并在顶部质量卡提示，阶段回看文件不再伪装成实时依据。 | 回滚到第56版可用 `git checkout v2026.07.07-m56-label-pct-audit`，或回滚到本版本 tag。 |
| 2026-07-07 第56版｜涨跌标签校验 | 2026-07-07 | 第56版 | tag: `v2026.07.07-m56-label-pct-audit` | 数据审计新增盘口标签一致性检查：`change_pct` 与“涨停/封板/跌停/强势/弱势/风险”等当前标签冲突时进入 warning；同时排除“前日强势后兑现、映射逻辑里其他标的涨停”等合理语境，降低伪跌停、伪强势和标签串线污染看板。 | 回滚到第55版可用 `git checkout v2026.07.07-m55-evidence-gap`，或回滚到本版本 tag。 |
| 2026-07-07 第55版｜信号证据缺口 | 2026-07-07 | 第55版 | tag: `v2026.07.07-m55-evidence-gap` | `decision-feed` 每条机会/风险/验证新增 `discovery_type`、`evidence_score`、`missing_evidence`，区分主动盘面扫描、主动个股扫描、专题继承、风险兜底和待验证队列；雷达卡片显示发现方式、证据分和证据缺口，发布门强制检查这些字段。 | 回滚到第54版可用 `git checkout v2026.07.07-m54-session-trust`，或回滚到本版本 tag。 |
| 2026-07-07 第54版｜交易阶段可信度 | 2026-07-07 | 第54版 | tag: `v2026.07.07-m54-session-trust` | `data-trust` 新增 `session_phase/session_relevance/session_action/session_reason`，把同一交易日内的早盘、午盘、盘中、盘后数据区分为当前阶段可用、阶段回看、待产出和背景参考；顶部质量卡同步显示“阶段回看”，避免过期阶段数据被当成实时交易依据。 | 回滚到第53版可用 `git checkout v2026.07.07-m53-japan-korea-guard`，或回滚到本版本 tag。 |
| 2026-07-07 第53版｜日韩早盘强防护 | 2026-07-07 | 第53版 | tag: `v2026.07.07-m53-japan-korea-guard` | 盘前“日韩早盘”不再展示原始字符串；字符串/数组字符串必须先提取日经、KOSPI、三星、SK海力士、东京电子、Advantest 等白名单行情数值，提取不到或发现降级/疑似乱码时统一显示中文降级提示。 | 回滚到第52版可用 `git checkout v2026.07.07-m52-blindspot-radar`，或回滚到本版本 tag。 |
| 2026-07-07 第52版｜盲区并入风险雷达 | 2026-07-07 | 第52版 | tag: `v2026.07.07-m52-blindspot-radar` | 将 `monitoring-coverage` 的 critical/warning 盲区并入机会/风险雷达：critical 盲区进入风险栏前排，替代观察动作进入验证栏；运行时烟雾测试新增校验，critical 盲区必须渲染到雷达风险栏。 | 回滚到第51版可用 `git checkout v2026.07.07-m51-monitoring-coverage`，或回滚到本版本 tag。 |
| 2026-07-07 第51版｜监测盲区雷达 | 2026-07-07 | 第51版 | tag: `v2026.07.07-m51-monitoring-coverage` | 新增 `scripts/build_monitoring_coverage.py` 和 `data/monitoring-coverage.json`，把不可用/降权数据翻译成交易监测盲区：影响哪些决策、为什么、临时替代观察动作是什么；顶部质量卡新增“监测盲区”，发布门强制检查盲区字段。 | 回滚到第50版可用 `git checkout v2026.07.07-m50-data-trust`，或回滚到本版本 tag。 |
| 2026-07-07 第50版｜数据文件可信度 | 2026-07-07 | 第50版 | tag: `v2026.07.07-m50-data-trust` | 新增 `scripts/build_data_trust.py` 和 `data/data-trust.json`，把全局审计翻译成每个核心数据文件的 trusted/degraded/stale/invalidated/missing、可信分、使用动作和原因；顶部质量卡新增“文件可信”，发布脚本先审计再生成文件级可信度并复审。 | 回滚到第49版可用 `git checkout v2026.07.07-m49-signal-usability`，或回滚到本版本 tag。 |
| 2026-07-07 第49版｜信号可用性分级 | 2026-07-07 | 第49版 | tag: `v2026.07.07-m49-signal-usability` | `decision-feed` 每条机会/风险/验证新增 `signal_score`、`signal_grade`、`use_action`、`use_reasons`，把“能不能用、怎么用”显式写清楚；雷达卡片显示 A/B/C/D 级和可跟踪/等待确认/降权观察/仅复核动作；审计和 smoke 测试强制检查信号可用性字段。 | 回滚到第48版可用 `git checkout v2026.07.07-m48-runtime-smoke`，或回滚到本版本 tag。 |
| 2026-07-07 第48版｜运行时渲染门禁 | 2026-07-07 | 第48版 | tag: `v2026.07.07-m48-runtime-smoke` | 新增 `scripts/smoke_dashboard_runtime.js` 和 `data/runtime-smoke-report.json`，发布前用真实 JSON 执行 `app.js` 的 `updateAll` 渲染路径，拦截 JS ERROR、console error、关键区块空白、`undefined`、`[object Object]`、NaN 和疑似乱码；`push_with_audit.sh` 接入动态门禁。 | 回滚到第47版可用 `git checkout v2026.07.07-m47-japan-korea-safe`，或回滚到本版本 tag。 |
| 2026-07-07 第47版｜日韩早盘防乱码 | 2026-07-07 | 第47版 | tag: `v2026.07.07-m47-japan-korea-safe` | 收紧盘前“日韩早盘”展示逻辑：只展示已识别的日经/KOSPI/三星/SK海力士/东京电子/Advantest数值字段；遇到降级、未核实、解码失败或疑似乱码时统一显示中文降级提示。数据审计和页面烟雾测试新增疑似乱码拦截。 | 回滚到第46版可用 `git checkout v2026.07.07-m46-section-deps`，或回滚到本版本 tag。 |
| 2026-07-07 第46版｜区块依赖校准 | 2026-07-07 | 第46版 | tag: `v2026.07.07-m46-section-deps` | 校准 `section-health` 依赖关系：观察池和专题跟踪也纳入 `quality-report`，当行情源或 alert 污染导致全局 degraded 时，这些二次研判区块不再显示 ok，而是原地提示“可看但降权”。 | 回滚到第45版可用 `git checkout v2026.07.07-m45-section-badges`，或回滚到本版本 tag。 |
| 2026-07-07 第45版｜面板健康贴条 | 2026-07-07 | 第45版 | tag: `v2026.07.07-m45-section-badges` | 将 `section-health.json` 的 ok/degraded/stale/invalidated 状态直接贴到对应面板标题下，盘中滚动到异动、晚间、盘中全景等区块时也能看到“等待重产/仅作历史/可看但降权”的状态；烟雾测试新增区块到 DOM 的映射校验。 | 回滚到第44版可用 `git checkout v2026.07.07-m44-section-health`，或回滚到本版本 tag。 |
| 2026-07-07 第44版｜区块健康矩阵 | 2026-07-07 | 第44版 | tag: `v2026.07.07-m44-section-health` | 新增 `scripts/build_section_health.py` 和 `data/section-health.json`，把全局数据质量拆到各页面区块，标明 ok/degraded/stale/invalidated/missing；数据质量区新增“区块健康”卡，直接提示哪些区块不可用或需降权。 | 回滚到第43版可用 `git checkout v2026.07.07-m43-quality-flags`，或回滚到本版本 tag。 |
| 2026-07-07 第43版｜机会信号质量降权 | 2026-07-07 | 第43版 | tag: `v2026.07.07-m43-quality-flags` | `decision-feed` 新增 `quality_gate` 和机会项 `quality_flags`；当数据审计为 degraded/critical 时，机会候选统一降为低置信并在雷达卡片显示“降权”原因，审计和烟雾测试同步拦截缺少降权标记或未降权的机会项。 | 回滚到第42版可用 `git checkout v2026.07.07-m42-smoke-gate`，或回滚到本版本 tag。 |
| 2026-07-07 第42版｜页面烟雾测试发布门 | 2026-07-07 | 第42版 | tag: `v2026.07.07-m42-smoke-gate` | 新增 `scripts/smoke_dashboard_static.py` 和 `data/smoke-report.json`，发布前检查关键容器、导航锚点、缓存版本、JS 语法、坏字面量、决策流泛化机会和旧相对日期；`push_with_audit.sh` 改为数据审计 + 页面烟雾测试双门禁。 | 回滚到第41版可用 `git checkout v2026.07.07-m41-radar-evidence`，或回滚到本版本 tag。 |
| 2026-07-07 第41版｜雷达证据化去噪 | 2026-07-07 | 第41版 | tag: `v2026.07.07-m41-radar-evidence` | 收紧结构化决策流的机会分类，过滤“风险线、未触发、反抽失败、泛化分类桶”等伪机会；雷达卡片新增证据、验证、证伪、来源分行展示，减少长文本堆叠和误读。 | 回滚到第40版可用 `git checkout v2026.07.07-m40-decision-feed`，或回滚到本版本 tag。 |
| 2026-07-07 第40版｜结构化机会风险流 | 2026-07-07 | 第40版 | tag: `v2026.07.07-m40-decision-feed` | 新增 `data/decision-feed.json` 和生成脚本，把机会候选、风险提示、下一步验证从前端临时拼文本升级为带来源、证据、置信度和证伪条件的结构化决策流；前端雷达优先读取该文件，发布脚本自动刷新并审计。 | 回滚到第39版可用 `git checkout v2026.07.07-m39-japan-korea-warning`，或回滚到本版本 tag。 |
| 2026-07-07 第39版｜日韩早盘降级提示 | 2026-07-07 | 第39版 | tag: `v2026.07.07-m39-japan-korea-warning` | 盘前外部环境里的“日韩早盘”遇到数据源降级、未核实或待确认时，改成清楚的黄色提示条，不再把原始长句混排行情展示，减少中英混排造成的乱码感。 | 回滚到第38版可用 `git checkout v2026.07.07-m38-audit-before-push`，或回滚到本版本 tag。 |
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
