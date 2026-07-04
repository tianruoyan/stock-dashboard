# 同花顺自选股同步到观察池

## 推荐设置

1. 在同花顺里把自选股导出为文本或 CSV。
2. 保存到：

```text
/Users/sweet_orange/Documents/同花顺自选股.txt
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

## 手动同步一次

```bash
cd /Users/sweet_orange/stock-dashboard
python3 scripts/import_ths_watchlist.py --source /Users/sweet_orange/Documents/同花顺自选股.txt
```

脚本只会追加或补全 `config/watchlist.json` 里的 `watch_only`，不会删除已有观察池股票。

## 开机自动同步

```bash
cp /Users/sweet_orange/stock-dashboard/scripts/com.stock-dashboard.ths-watchlist.plist ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.stock-dashboard.ths-watchlist.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.stock-dashboard.ths-watchlist.plist
```

默认每 30 分钟同步一次，开机后自动跑一次。同步成功后会 `touch .push-now`，由现有推送守护负责发布。

## 改同步频率

编辑 `scripts/com.stock-dashboard.ths-watchlist.plist` 里的：

```xml
<key>StartInterval</key>
<integer>1800</integer>
```

`1800` 表示 1800 秒，也就是 30 分钟。
