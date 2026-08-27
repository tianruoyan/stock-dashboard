# V2/V2.2 Shadow 运行说明

## 边界

- V1 继续生产；V2/V2.2 未明确晋升前只做并行验证。
- 所有交易能力为 `false`；不能自动修改 V1、用户资产、组合、模型注册或晋升状态。
- 同花顺周期读取任务必须禁用；Longbridge 只作为规范化外部研究观点。

## 配置入口

- 市场环境：`config/v2-market-environment-policy.json`
- 决策门：`config/v2-decision-gates.json`
- 热点与风格：`config/v2-theme-taxonomy.json`、`v2-style-taxonomy.json`、`v2-style-baskets.json`
- 代表股与跨市场：`config/v2-representative-stock-codes.json`、`v2-cross-market-mappings.json`
- 行情一致性与来源治理：`config/v2-quote-consistency.json`、`v2-source-governance.json`
- 自动化路由和发布：`config/v2-automation-routing.json`、`v2-publish-policy.json`
- 功能与灰度：`config/v2-v22-feature-flags.json`、`v2-rollout.json`

规则调整优先改配置，并用对应 `tests/test_v22_*.py` 或 `tests/test_v2_*.py` 验证。

## 本机任务

- `com.tianruoyan.stock-dashboard.v2-local`：8878 shadow 页面。
- `com.stock-dashboard.ai-hardware-monitor`：AI 半导体/硬件二次启动雷达，交易窗口巡检。
- `com.stock-dashboard.v22-intraday-shadow`：盘中检查点 shadow。
- `com.stock-dashboard.v22-evening-sentiment`：19:30–22:30 与次日 07:30–08:30 补跑。
- `com.stock-dashboard.futu-opend`：可选只读第二行情源；11111 不可用时不得阻塞其他任务。

任务在非运行窗口静默退出，避免每分钟空跑日志。日志由 V1 的 `com.stock-dashboard.log-maintenance` 统一维护。

## 部署原则

1. 在本 Git 工作树修改和测试。
2. 运行 `deploy_v22_intraday_runtime.sh` 和/或 `deploy_ai_hardware_monitor_runtime.sh`。
3. 检查 `data/v2/v22/runtime-deployment.json` 的 `all_hashes_equal`。
4. 重启受影响的 LaunchAgent，检查 8878 健康。
5. 提交到 `codex/v2-platform`；不得把 `.v2_private/`、`local_inputs/` 或用户资产加入提交。
