# V2 本地数据输入

将需要导入的模板复制到项目根目录的 `local_inputs/`，填写真实数据后运行 `python3 scripts/import_v2_inputs.py`。

导入器先校验字段、时区和数值，再原子写入 `data/v2/`。校验失败不会覆盖上一次可用数据。持仓输入只用于风险上下文，不授权自动交易；博主内容只能作为市场预期或情绪来源。

长桥机构分析使用独立模板 `longbridge-analysis.json`，复制到 `local_inputs/longbridge-analysis.json` 后运行 `python3 scripts/import_longbridge_analysis.py`。它只生成外部机构分析引用，不读取或写入长桥账户、订单、持仓、自选，也不替代同花顺自选。完整规则见 `LONGBRIDGE_ANALYSIS_REFERENCE.md`。
