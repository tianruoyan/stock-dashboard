# Codex 最小上下文交接

## 先读什么

按顺序只读：

1. `AGENTS.md`
2. 本文件
3. `SYSTEM.md` 中与问题相关的一节
4. 用户点名的脚本、配置或失败状态文件

除非验收失败，不要先扫描整个 `data/`、`logs/`、V2 工作树或历史报告。运行状态先用：

```bash
cd /Users/sweet_orange/stock-dashboard
python3 scripts/system_doctor.py
git status --short --branch
```

## 不可改变的默认边界

- V1 `main` + 8877 是唯一生产入口。
- V2/V2.2 `codex/v2-platform` + 8878 是 shadow，禁止自动晋升。
- 不自动交易，不读取账户/订单，不自动修改用户自选、优先级、关注目的或备注。
- `com.stock-dashboard.ths-watchlist` 和 `com.stock-dashboard.v2-ths-shadow` 必须保持禁用。
- 数据源失败时保留上一有效版本并降级；禁止编造或用备用源冒充正式双源确认。
- 改规则优先改 `config/`；改代码必须补对应测试。

## 一次小维护的标准流程

1. 复现单一问题，保存最小证据。
2. 确认改动属于 V1 生产还是 V2 shadow；不要同时扩展两个版本。
3. 只打开相关配置、脚本和测试。
4. 做最小修改；不得顺手新增功能。
5. 运行相关单测，再运行系统巡检或构建门。
6. 检查 `git diff`，确保没有用户资产和私有输入进入提交。
7. 用一个目的明确的提交固化；只有影响回滚判断时才新增版本标签。

## 常用最小验证

```bash
# V1 代码回归
PYTHONPATH=scripts python3 -m unittest discover -s scripts -p 'test_*.py'

# V1 数据与页面门禁
python3 scripts/build_dashboard_reports.py

# 运行边界
python3 scripts/system_doctor.py

# V2 只运行与改动相关的测试；大版本收口才跑全套
cd /Users/sweet_orange/Documents/投资/worktrees/stock-dashboard-v2
python3 -m unittest discover -s tests -p 'test_*.py'
```

## 给 Codex 的低额度请求模板

```text
仓库：/Users/sweet_orange/stock-dashboard
范围：V1 生产（或 V2 shadow，二选一）
问题：<一个可复现问题>
证据：<状态文件、错误或页面>
允许修改：<1-3 个文件或一个模块>
禁止修改：用户资产、V2 晋升、自动交易、无关数据
验收：<一条测试命令 + 一个运行结果>
完成后：给出 diff 摘要、风险和回滚提交
```

如果问题无法用一个范围和一个验收标准描述，先拆成多个小任务；这比把全部历史背景重新交给 Codex 更节省 Plus 用量。

## 当前稳定运行说明

- `8765` 已退役；不要恢复。
- Codex 登录启动器已停用；本地自动化不依赖 ChatGPT 常驻。
- 富途 OpenD 是可选第二源。端口 11111 未就绪时应快速降级，不得卡住监控接线。
- GitHub 发布依赖本机 Clash 7897；代理中断时保留待发布标记，不要重复手工提交同一批数据。
- V2 运行目录不是 Git 真相源；修改后从 V2 工作树部署并验证哈希。

## 适合 Plus 后做的事

- 单一数据源适配、小范围 UI 修复、阈值配置调整、单测补齐、文档更新。
- 每次只给相关文件和明确验收，不要求 Codex“重新理解整个系统”。

不适合在稳定期做的事：重写全套框架、再造新看板、引入第二智能体发布链、自动交易、无样本基础的模型权重自学习。
