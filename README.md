# AI 投资决策系统 V2/V2.2 Shadow

本分支是 V2/V2.2 的 Git 真相源，当前状态为 shadow。V1 `/Users/sweet_orange/stock-dashboard` 与 `127.0.0.1:8877` 仍是唯一生产入口。

## 入口与部署

- 源码：`/Users/sweet_orange/Documents/投资/worktrees/stock-dashboard-v2`
- 分支：`codex/v2-platform`
- 本机运行镜像：`/Users/sweet_orange/stock-dashboard-v2-local`
- 影子看板：`http://127.0.0.1:8878/v2.html`

```bash
cd /Users/sweet_orange/Documents/投资/worktrees/stock-dashboard-v2
python3 -m unittest discover -s tests -p 'test_*.py'
scripts/deploy_v22_intraday_runtime.sh
scripts/deploy_ai_hardware_monitor_runtime.sh
curl --noproxy '*' -fsS http://127.0.0.1:8878/_health
```

运行镜像不是源码仓库，不要只修改 `stock-dashboard-v2-local`。私有输入、用户资产与运行状态不得进入公开发布。

维护前先读父目录 `AGENTS.md`、本目录 `AI_HANDOFF.md` 和 `SYSTEM.md`。
