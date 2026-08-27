# Codex 项目约束

在本项目工作前先读取 `RULES.md` 和 `THS_WATCHLIST_SYNC.md`。

## 同花顺与用户资产

- `config/watchlist.json` 是 V1 生产观察池的现有快照；来源失败时保留，不得清空、覆盖或推断删除。
- 同花顺自选是低频、用户确认的资产入口，不是盘中行情源。
- 不得启用或重新安装 `com.stock-dashboard.ths-watchlist` 周期任务，不得从后台 shell/AppleScript 周期读取 `~/Library/Containers/cn.com.10jqka.macstockPro`。
- 不得为了自选同步给 `/bin/zsh`、`osascript`、Python、Terminal 或 ChatGPT/Codex 授予完全磁盘访问权限。
- 用户明确要求“同步自选”时，优先从投资工作区内的私有中性文件生成影子结果和差异预览；默认只新增、不删除。
- 同花顺返回缺少完整列表证据时，缺失项不能解释为删除；应用任何删除前必须取得用户明确确认并通过既有批量删除保护。
- V2/V2.2 在明确晋升前保持 shadow，不能从影子结果自动回写 V1 用户资产。
