# Stock Dashboard Version Log

| Display Version | Date | Edition | Tag / Commit | Summary | Rollback Note |
|---|---:|---:|---|---|---|
| 2026-07-04 第31版｜总控-观察池-仓位风控-信号复盘 | 2026-07-04 | 第31版 | tag: `v2026.07.04-m31-control-watchlist-risk-review` | 个性化高时效辅助决策改造：今日总控、观察池决策、仓位风控、信号复盘、信息减负。 | 回滚到上一稳定版本可用 `git checkout 8f29b88`，或回滚到本版本 tag。 |
| 2026-07-04 第30版｜七区聚焦摘要 | 2026-07-04 | 第30版 | `8f29b88` | 完成七个核心区的聚焦摘要：异动、全景、盘前、午盘、盘后、晚间、专题。 | 当前大版本前的稳定展示版本。 |
| 2026-07-04 第23版｜设置页和说明书独立 | 2026-07-04 | 第23版 | `52aa978` | 设置页独立化，分析模型说明书独立化。 | 回滚到较早的配置/说明书页面版本。 |

## Naming Rule

- 页面显示使用中文解释名：`2026-07-04 第31版｜总控-观察池-仓位风控-信号复盘`。
- Git tag 使用英文安全名：`v2026.07.04-m31-control-watchlist-risk-review`。
- `m31` 是页面缓存版本；“第31版”是给人看的迭代序号；后面的中文短语说明主要修改点。
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
