# 第一项修复：语义验收派发与作用域

## 已完成

修改 `app/cad_semantic_acceptance.py`：只有已识别为 straight_capital_a 的请求才进入字母 A 检查；已完成的其他语义检查返回其自身证据。未知语义不默认套用字母检查，仍为 unverified/review_required。多对象请求不套用整图单轮廓语义。没有新增生成器、固定生产坐标或放宽原有特征阈值。

新增 `tests/test_semantic_dispatch_regression.py` 和 `tests/fixtures/recorded_semantic_dispatch.json`。夹具来自本轮真实 A1 第一份模型计划，明确保留来源；它仅用于离线回放，不是生产生成模板。

## 证据

- 修改前，新回归可重现爱心误入字母 A 检查；修改后，同一计划通过完整 interpret_construction_request，返回 ready。
- 倒置该边界仍被原特征检查拒绝；将同一几何用于真实字母 A 请求仍被拒绝；未知 profile 不算成功。
- 语义、解释器、需求契约与构造回归：143 passed / 1 failed。另运行候选提交、来源验收、构造评测：47 passed。合计 190 passed / 1 failed。
- 剩余失败 `test_structural_counter_schema_preserves_multiple_paths_without_coordinates` 在修改前也存在：期望步骤 maxItems=1，当前为100。未改原断言，未收缩多段轮廓表达能力来迎合断言。
- 新增的5个测试均通过。
- 使用真实 deepseek-flash 对 A1/A9 定向复测，仍为0/2：错误已回到真实缺失特征/候选待复核，不能宣称端到端成功率提高。原70条基线保持不动。

复现（backend 目录，使用 Conda test Python 3.11.18）：

```powershell
python -m pytest tests/test_semantic_dispatch_regression.py tests/test_cad_semantic_acceptance.py tests/test_cad_construction_interpreter.py tests/test_cad_requirement_contract.py tests/test_cad_construction.py -q
python -m pytest tests/test_cad_construction_commit.py tests/test_cad_source_acceptance.py tests/test_cad_construction_evaluation.py -q
```

原文件备份、差异和真实复测分别在 `C:\Users\29924\Codes\cad-eval-20261117\before-fixes`、`semantic-dispatch.patch`、`after-dispatch`。本地 backend Git 无原始 HEAD，不将未提交的整份源码冒充已知基线；本项以文件备份和差异留存，未推送或合并。

## 待继续解决

1. 来源尺寸与摘要尺寸之间的权威性、整体/部件作用域，避免补充门尺寸覆盖房子总尺寸。
2. 根据独立失败测量选择局部参数修复或结构重规划，保护非目标部件与来源；不局限修改参数域。
3. 修复进展按相关部件的实际几何与失败特征判断，不把 JSON 变化算进步。
4. 坐标单位、轴长等完整要求的澄清闭环；确认上下文跨请求存取。
5. 评测分别报告首次交付、补充后交付、合理澄清、前置阻塞和待人工验收；评测调整不能改写原始结果。

本文件为阶段记录，未声称所有根因解决或项目研发完成。
