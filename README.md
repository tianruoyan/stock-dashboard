# AI 投资决策系统

这是当前系统的生产仓库。目标是让本地程序承担高频、确定性的采集与恢复，让 ChatGPT/Codex 只承担需要判断的研究和小步维护。

## 当前入口

- V1 生产看板：`http://127.0.0.1:8877/`
- V2/V2.2 影子看板：`http://127.0.0.1:8878/v2.html`
- `8765`：历史投资资料页服务，已退役，不再作为入口

V1 是唯一生产入口。V2/V2.2 未经明确晋升前只用于并行验证，不能自动改写 V1 用户资产、交易结论或发布状态。

## 一分钟检查

```bash
cd /Users/sweet_orange/stock-dashboard
python3 scripts/system_doctor.py
python3 scripts/build_dashboard_reports.py
```

第一条检查端口、LaunchAgents、锁、日志和 Git 基线；第二条执行数据审计与页面烟雾测试。`system_doctor.py` 是只读巡检，报告写入被 Git 忽略的 `logs/system-doctor.json`。

## 维护入口

- 系统架构、目录、服务、恢复和数据源：`SYSTEM.md`
- 给下一次 Codex 的最小上下文：`AI_HANDOFF.md`
- 分析规则、阈值和证据门禁：`RULES.md`
- 用户资产与同花顺同步边界：`THS_WATCHLIST_SYNC.md`
- 版本与回滚点：`VERSION.md`

日常维护先读 `AGENTS.md`、`AI_HANDOFF.md`，再只打开与问题直接相关的文件。不要从日志、历史数据和整个 V2 目录开始全量扫描。

## 常用操作

```bash
# V1 健康
curl --noproxy '*' -fsS http://127.0.0.1:8877/_health

# V2 shadow 健康
curl --noproxy '*' -fsS http://127.0.0.1:8878/_health

# 运行 V1 回归测试
PYTHONPATH=scripts python3 -m unittest discover -s scripts -p 'test_*.py'

# 手动执行日志维护（默认 8MB，保留 3 份）
python3 scripts/rotate_runtime_logs.py --json
```

系统不提供自动交易能力，也不会自动新增、删除或覆盖用户自选。行情或证据不足时必须降级为观察，不能用推断填补缺失事实。
