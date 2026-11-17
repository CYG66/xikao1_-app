# 第四轮隔离响应日志目录（D 线自有范围）

本目录仅用于第四轮真实模型受控评测的脱敏原始响应日志。

- 当前状态：**A9 爱心案例已完成一次受控真实评测**，`real_model_calls = 2`；主控仅批准 A9 一个案例，完成后即停止，未启动 S1 / 多对象 / Arc / 自由曲线案例。
- 每个案例独立项目、独立会话、独立候选与独立存储；不写真实用户项目。
- 写入前即脱敏：`Authorization`、API Key、Key 片段一律替换为 `<redacted>`，不做事后补丁。
- 本目录不保存生产配置、不保存全局默认模型设置。
- 历史第一至三轮 `real_model_calls = 0`；本轮账本见 `../D1_round4_budget_ledger.json`。

## 已落盘文件

- `A9_case_record.json`：A9 预检、案例记录与脱敏后的生产返回快照。
- `A9_raw_responses.jsonl`：两次真实结构化请求的脱敏原始响应（`id` / `model` / `finish_reason` / `usage`，不含 Key 与 Authorization）。
