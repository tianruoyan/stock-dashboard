# 长桥机构分析模型引用规范

## 定位

长桥仅作为外部机构分析模型和观点来源，不是本系统的交易系统、行情唯一真相源、持仓来源或自选来源。同花顺自选继续按既有低频控制面规则管理；长桥不得替代、同步或修改同花顺自选。

本接入只生成 `shadow_reference_only` 证据。长桥观点可以补充研究、解释和反证，但不能独立通过 G0、绕过 G0—G7、升级决策案例、改变行动语言、修改用户资产或晋升模型。

## Codex 必须遵守的工作流

1. 需要市场或证券分析时使用 Longbridge Skill；优先读取长桥的机构分析、LongbridgeAI、Agent Platform 或长桥官方研究内容。
2. 原始对话、提示词和完整输出只保存在本机 `local_inputs/`，不得写入公开数据目录。
3. 把需要引用的内容整理到 `local_inputs/longbridge-analysis.json`。每条内容必须包含：
   - 长桥产品、模型名称和版本披露状态；
   - 标题、长桥原始链接、发布时间、观察时间；
   - 涉及的证券、行业、主题或市场；
   - `reported_fact`、`inference`、`risk`、`counter_view`、`trading_view` 分层；
   - 引文、反证、适用时间窗和失效条件。
4. 运行 `python3 scripts/import_longbridge_analysis.py`。只有 `accepted` 项会进入公开引用集。
5. 分析时只读取 `data/v2/v22/longbridge-analysis-references.json`，不得绕过导入器直接把原始对话写进决策案例。
6. 前台引用必须使用归属表达，例如“长桥分析认为……（生成于……，来源……）”。不得把长桥观点改写成本地事实。
7. `reported_fact` 必须通过本地独立来源、时间、主体和口径核验；核验前状态固定为 `pending_independent_verification`。
8. `trading_view` 即使包含买卖倾向，也只能显示为“外部机构观点”，`action_permitted=false`。
9. 长桥不可用、引用缺失、模型版本未披露或反证不足时，应明确降级或进入复核队列，不得补造观点。

## 禁止调用与写入

- 不调用或授权长桥账户、持仓、订单、DCA、交易和自选写入能力；
- 不把长桥注册为 `watchlist_source`；
- 不从长桥推断用户持仓、优先级、关注目的或备注；
- 不向长桥社区自动发布内容；
- 不因“长桥是优秀机构”而提高事实等级或绕过本地证据门禁。

## 验收

```bash
python3 -m unittest tests.test_v22_longbridge_analysis
python3 scripts/import_longbridge_analysis.py
python3 scripts/accept_v22_longbridge_analysis.py
```

验收通过条件：完整引用可进入 shadow；长桥声称的事实仍待本地核验；交易观点不可执行；包含交易、账户、自选或用户资产字段的输入被拒绝；缺少反证的输入进入复核；V1/V2/V2.2 和同花顺自选边界不变。
