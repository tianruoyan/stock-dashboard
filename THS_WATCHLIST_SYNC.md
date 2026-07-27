# 同花顺自选股同步到观察池

## 当前架构决策（2026-07-27）

同花顺自选属于**低频、用户确认的资产入口**，不是盘中行情源。当前停止后台每 30 分钟读取桌面同花顺 Cookie：

- `com.stock-dashboard.ths-watchlist` 必须保持禁用；
- 不得为了同步给 `/bin/zsh`、`osascript`、Python 或 ChatGPT/Codex 开启“完全磁盘访问权限”；
- 保留现有 `config/watchlist.json`，数据源失败时不得清空、覆盖或推断删除；
- 新同步只在用户明确发起时执行，先生成影子结果和差异预览；
- V2.2 未取得完整列表证据前，不把同花顺结果自动应用为用户资产，也不安装周期任务。

这样处理符合“用户资产、AI分析、风格样本分离”的系统边界，也避免 macOS 因后台 shell 读取其他 App 容器而反复显示权限弹框。

## 推荐方式：用户触发的中性文件导入

1. 用户通过 Finder 将自选股文本放入项目的私有中转目录，例如：

```text
/Users/sweet_orange/Documents/投资/worktrees/stock-dashboard-v2/.v2_private/inbox/同花顺自选股.txt
```

2. Codex 只读取这个中性文件，先生成影子批次和新增、缺失、冲突预览。
3. 缺失只表示“本次来源未返回”，不能自动解释为用户删除。
4. 只有用户确认且来源完整性可核验时，才允许按既有删除保护规则应用；默认仍然只新增、不删除。

中性文件每行支持以下格式：

```text
301526 国际复材
300033 同花顺
688160 步科股份
688017 绿的谐波
002747 埃斯顿
```

## 旧版方式：桌面同花顺直连（仅迁移取证）

旧实现会读取桌面版同花顺的登录 Cookie，并通过同花顺“我的自选”接口拉取手机端同步后的自选股。该方式会访问同花顺 App 的私有容器，容易触发 macOS 的“zsh 想访问其他 App 数据”提示，不再作为后台默认链路。

前提：

1. Mac 已安装并登录「同花顺」桌面版。
2. 手机端同花顺和 Mac 桌面端使用同一个账号。
3. 桌面端能看到手机同步过来的自选股。

只有用户明确要求进行一次迁移取证时，才允许手动同步：

```bash
cd /Users/sweet_orange/stock-dashboard
python3 scripts/import_ths_watchlist.py --mode ths
```

脚本默认把同花顺返回的股票安全合并到 `config/watchlist.json` 的 `watch_only`：新增股票会加入，已有股票会更新，但来源没有证明为完整列表时绝不自动删除用户资产。`small_deng` 和 `old_deng` 仍是独立风格监测池，不参与用户自选同步。同步成功后直接调用 Codex 单智能体发布器完成校验、提交和推送；网络失败时由本机发布重试服务继续处理。

只有人工确认本次数据确实是完整云端列表时，才允许按来源执行删除：

```bash
python3 scripts/import_ths_watchlist.py --mode ths --complete-sync-confirmed
```

如完整列表相较现有观察池减少超过 40%，还需在核对删除预览后同时增加 `--allow-large-removal`。日常后台任务不会传入这两个参数，因此只能增补和更新，不能删除。

## 备用方式：iCloud 文本

如果同花顺登录态失效，仍可用文本文件导入。

在 iPhone 的「文件」App 里打开 iCloud Drive，保存到：

```text
/Users/sweet_orange/Library/Mobile Documents/com~apple~CloudDocs/同花顺自选股.txt
```

3. 文件每行支持以下格式：

```text
301526 国际复材
300033 同花顺
688160 步科股份
688017 绿的谐波
002747 埃斯顿
```

只写代码或只写股票名也可以，脚本会尽量自动补全。

手动同步文本：

```bash
cd /Users/sweet_orange/stock-dashboard
python3 scripts/import_ths_watchlist.py --mode file --source "/Users/sweet_orange/Library/Mobile Documents/com~apple~CloudDocs/同花顺自选股.txt"
```

## 后台周期同步（已停用）

旧任务默认每 30 分钟运行一次，并通过 Finder/AppleScript 复制桌面同花顺 Cookie。该任务已因用户资产边界和 macOS 隐私权限问题停用，不得重新安装、加载或提高权限绕过提示。

为避免不完整接口响应或旧文件误删当前观察池，系统采用三层保护：日常同步默认禁止删除；iCloud 文本早于当前 `watchlist.json` 时拒绝使用；即使人工确认完整同步，一次拟删除超过当前观察池 40% 时仍会拒绝，必须再次核对后联合使用 `--complete-sync-confirmed --allow-large-removal`。

## macOS 权限

如果日志里出现：

```text
Operation not permitted: .../Mobile Documents/com~apple~CloudDocs/同花顺自选股.txt
```

说明进程正在读取受保护目录。若弹框显示 `zsh`，通常是旧的 `com.stock-dashboard.ths-watchlist` 周期任务被重新启用；应停用该任务，而不是授予完全磁盘访问权限。

手动取证可能在用户明确发起的当次操作中请求一次权限。日常同步应通过 Finder 把输入文件放入 `.v2_private/inbox/`，再由 Codex 读取中性文件。

如果桌面同花顺直连失败，优先确认桌面同花顺是否仍处于登录状态。

## 历史频率说明

编辑 `scripts/com.stock-dashboard.ths-watchlist.plist` 里的：

```xml
<key>StartInterval</key>
<integer>1800</integer>
```

`1800` 表示旧任务每 30 分钟运行一次。该字段仅供历史排查，不应通过修改频率重新启用周期同步。
