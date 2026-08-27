# 系统运行说明

更新时间：2026-08-27。本文是运行架构的唯一简明入口；投资分析口径仍以 `RULES.md` 和 V2 配置文件为准。

## 1. 生产与影子边界

| 层级 | 位置 | 入口 | 状态 | 权限 |
|---|---|---|---|---|
| V1 生产源码 | `/Users/sweet_orange/stock-dashboard` | `127.0.0.1:8877` | 生产 | 可更新 V1 公开数据；用户资产受保护 |
| V2/V2.2 源码 | `/Users/sweet_orange/Documents/投资/worktrees/stock-dashboard-v2` | 无常驻端口 | `codex/v2-platform` shadow 分支 | 只做影子研究与验收 |
| V2/V2.2 运行镜像 | `/Users/sweet_orange/stock-dashboard-v2-local` | `127.0.0.1:8878` | 本机 shadow | 由部署脚本生成，不作为 Git 真相源 |
| 投资研究资料 | `/Users/sweet_orange/Documents/投资` | 无生产入口 | 数据、报告、专题 | `monitor.log` 等只作为输入证据 |

`/Users/sweet_orange/Documents/投资/worktrees/stock-dashboard-v2` 是 V2 的 Git 真相源；`stock-dashboard-v2-local` 只保存运行镜像和私有状态。修改 V2 后必须从源码运行部署脚本，不能只改运行镜像。

## 2. 责任边界

| 承担者 | 负责 | 不负责 |
|---|---|---|
| ChatGPT Work | 盘前/午盘/盘后研究、跨来源解释、形成需人工判断的结论 | 高频轮询、守护服务、自动交易、改用户资产 |
| Codex | 有明确验收标准的小步代码修改、测试、文档和版本基线 | 每分钟行情采集、长期常驻、无证据扩功能、自动晋升 V2 |
| 本地自动化 | 行情采集、固定规则构建、网页服务、健康检查、失败重试、日志维护 | 生成主观投资观点、越过证据门禁、调用交易接口 |

Codex 不需要登录时自动启动。`com.stock-dashboard.codex-runtime` 已停用；本地服务在没有 ChatGPT/Codex 的情况下也应正常运行。

## 3. 核心工作流

### 盘前

1. 本地数据层保留上一有效版本并更新可核验行情事实。
2. ChatGPT Work 在关键节点形成盘前预案与 9:25 竞价补充。
3. 写入 `data/premarket.json` 后调用统一发布器。

### 盘中

1. `com.stock-dashboard.intraday-data` 每 15 分钟更新指数与行业事实。
2. `monitor_guard.py` 运行老登/小登监控，结构化信号由 `monitor-signal-bridge` 接入。
3. `alert-quote-verifier` 使用独立锁；富途 OpenD 不可用时快速降级，不得阻塞监控接线，也不得把腾讯备用源冒充富途双源确认。
4. `intraday-recovery` 只补网络恢复后可核验的最新行情，不补造错过时点。

### 午盘、盘后与晚间

- 午盘与盘后由 ChatGPT Work 负责解释和结论；固定程序负责结构校验、衍生报告和发布。
- V2 晚间舆情只在 19:30–22:30 或次日 07:30–08:30 补跑窗口工作。
- V2/V2.2 输出始终保持 shadow，不自动回写 V1。

## 4. 配置与数据目录

### V1

- `config/watchlist.json`：用户观察池现有快照；来源失败时不得清空或推断删除。
- `config/alert-config.json`：异动阈值和告警配置。
- `config/topics-list.json`：专题列表。
- `config/cn-market-calendar.json`：经验证的交易日历。
- `data/`：公开看板输入和衍生审计报告。
- `logs/`：运行状态与日志，Git 忽略。
- `tmp/`：临时下载与中间文件，Git 忽略。

### V2/V2.2

- `config/v2-decision-gates.json`：决策升级/阻断条件。
- `config/v2-market-environment-policy.json`：市场环境规则。
- `config/v2-theme-taxonomy.json`、`v2-style-taxonomy.json`、`v2-style-baskets.json`：热点、风格与样本配置。
- `config/v2-representative-stock-codes.json`、`v2-cross-market-mappings.json`：代表股与跨市场映射。
- `config/v2-source-governance.json`、`v2-quote-consistency.json`：数据源治理和行情一致性。
- `config/v2-v22-feature-flags.json`、`v2-rollout.json`：功能开关与 shadow 发布边界。
- `.v2_private/`、`local_inputs/`、`data/v2/inputs/`：私有或本机输入，不进入公开发布。

热点、资金强度、个股角色与筛选规则优先改配置；只有配置无法表达且有测试覆盖时才改代码。AI 半导体二次启动雷达位于 V2 的 `ai_hardware_monitor/`，仍是 shadow 研究模块。

## 5. 数据源与降级

| 层级 | 主要来源 | 用途 | 失败动作 |
|---|---|---|---|
| 高频事实 | mootdx/通达信、腾讯财经 | 指数、盘口、短周期变化 | 保留上一有效版本，标记过期/降级 |
| 第二行情源 | 本机只读富途 OpenD | 新异动代表股交叉核验 | 快速跳过；不得升级双源确认 |
| 盘面结构 | 东方财富结构接口 | 涨跌停、板块、资金、龙虎榜 | 限流、重试、保留旧版并降权 |
| 事件证据 | 巨潮、交易所、官方政策源 | 公告、政策、晚间 P0 | 记录缺口，不用自媒体替代事实 |
| 外部研究 | Longbridge 规范化引用 | 机构观点与反证 | 只作外部观点，不自动通过 G0–G7 |

数据源状态统一写入 `data/source-health.json`。任何不可用来源都不得通过推断补数。

## 6. LaunchAgents

### 必须保留

- `com.tianruoyan.stock-dashboard.local`：V1 8877，多线程本地服务，KeepAlive。
- `com.stock-dashboard.local-health`：V1 健康检查与自动重启。
- `com.stock-dashboard.intraday-data`：盘中事实采集。
- `com.stock-dashboard.intraday-recovery`：盘中断网恢复。
- `com.stock-dashboard.monitor-signal-bridge`：监控结构化信号接线。
- `com.stock-dashboard.alert-quote-verifier`：异动第二源复核。
- `com.stock-dashboard.publisher`：待发布标记重试。
- `com.stock-dashboard.log-maintenance`：每小时日志维护。
- `com.tianruoyan.stock-dashboard.v2-local`：V2 8878 shadow 服务。
- V2 的 `ai-hardware-monitor`、`v22-intraday-shadow`、`v22-evening-sentiment`：只读 shadow 任务。

### 必须停用

- `com.sweetorange.investment-dashboard`：旧 8765 服务。
- `com.stock-dashboard.codex-runtime`：旧 ChatGPT 登录启动器。
- `com.stock-dashboard.ths-watchlist`、`com.stock-dashboard.v2-ths-shadow`：禁止周期读取同花顺用户资产。

## 7. 健康、恢复、日志与代理

运行 `python3 scripts/system_doctor.py` 可检查两个端口、关键任务、禁用任务、锁隔离、Git 基线和日志上限。V1 健康失败时，`local-health` 会重启 8877；V2 健康失败只影响 shadow。

日志超过 8MB 后使用 copy-truncate 轮转，保留 3 份历史。历史 `monitor.log` 同样受控；日志不是长期数据仓库。

Git 当前按仓库配置使用 `127.0.0.1:7897` Clash 代理。Clash 关闭时发布器保留 `.publish-pending` 并继续重试，不会丢失本地提交。排障时先检查：

```bash
lsof -nP -iTCP:7897 -sTCP:LISTEN
git ls-remote --heads origin main
cat logs/publisher-status.json
```

不要同时运行第二个 Clash/mihomo 守护进程，也不要把本地 `127.0.0.1` 请求送进代理。

## 8. 稳定基线验收

稳定版本必须同时满足：

1. 8877 健康、8878 shadow 健康、8765 无监听。
2. 受保护的同花顺周期任务和 Codex 登录启动器未加载。
3. 监控接线与行情复核使用不同锁；OpenD 不可用时复核器在秒级内退出。
4. V1 构建门无 critical，运行时烟雾测试为 ok。
5. V1 `main` 和 V2 `codex/v2-platform` 均有可回滚 Git 提交；运行镜像哈希与 V2 源码一致。
6. 活跃日志不超过 8MB，自动轮转任务已加载。
7. `README.md`、`SYSTEM.md`、`AI_HANDOFF.md` 能让下一次维护不扫描全仓库即可开始。
