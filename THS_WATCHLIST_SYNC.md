# 同花顺自选股同步到观察池

## 推荐方式：桌面同花顺直连

现在默认读取桌面版同花顺的登录 Cookie，并通过同花顺“我的自选”接口拉取手机端同步后的自选股。

前提：

1. Mac 已安装并登录「同花顺」桌面版。
2. 手机端同花顺和 Mac 桌面端使用同一个账号。
3. 桌面端能看到手机同步过来的自选股。

手动同步一次：

```bash
cd /Users/sweet_orange/stock-dashboard
python3 scripts/import_ths_watchlist.py --mode ths
```

脚本会把 `config/watchlist.json` 里的 `watch_only` 镜像为同花顺当前自选股：同花顺新增则新增，同花顺删除则删除。`small_deng` 和 `old_deng` 仍是独立风格监测池，不跟随同花顺删除。同步成功后直接调用 Codex 单智能体发布器完成校验、提交和推送；网络失败时由本机发布重试服务继续处理。

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

## 开机自动同步

```bash
cp /Users/sweet_orange/stock-dashboard/scripts/com.stock-dashboard.ths-watchlist.plist ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.stock-dashboard.ths-watchlist.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.stock-dashboard.ths-watchlist.plist
```

默认每 30 分钟同步一次，开机后自动跑一次。后台任务先通过 Finder 把桌面同花顺 Cookie 复制到 `logs/ths-cookie-source/`，再调用同花顺自选接口；桌面登录态失效时才回退到 iCloud 文本镜像。观察池没有变化时不会重复构建和推送。

为避免旧文件误删当前观察池，系统有两层保护：iCloud 文本早于当前 `watchlist.json` 时拒绝覆盖；一次同步拟删除超过当前观察池40%时也拒绝覆盖，必须人工确认后才能使用 `--allow-large-removal`。

## macOS 权限

如果日志里出现：

```text
Operation not permitted: .../Mobile Documents/com~apple~CloudDocs/同花顺自选股.txt
```

说明仍在运行旧版“Python 直接读取受保护目录”任务。新版通过 Finder 中转桌面登录 Cookie 和 iCloud 备用文本，不需要给 `/usr/bin/python3` 完全磁盘访问权限。重新安装并加载任务：

```bash
launchctl unload ~/Library/LaunchAgents/com.stock-dashboard.ths-watchlist.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.stock-dashboard.ths-watchlist.plist
```

手动运行脚本通常不受这个限制，所以可以先用手动同步确认文件格式没问题。

如果桌面同花顺直连失败，优先确认桌面同花顺是否仍处于登录状态。

## 改同步频率

编辑 `scripts/com.stock-dashboard.ths-watchlist.plist` 里的：

```xml
<key>StartInterval</key>
<integer>1800</integer>
```

`1800` 表示 1800 秒，也就是 30 分钟。
