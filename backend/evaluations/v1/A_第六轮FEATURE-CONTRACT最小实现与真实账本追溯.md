# 第六轮 · FEATURE-CONTRACT 最小实现与真实账本追溯报告（A 线，准入·A 线）

## 0. 本轮定位与纪律

- 采用后端内部 Sidecar；Feature Contract / Binding / Measurement 独立生命周期。
- **不进入** `CadConstructionPlan v1` 断言/约束联合类型，**不修改**公开 HTTP Schema。
- **未接入** `agent_service.py` 判定路径；第一阶段只做 Shadow Measurement。即使 Feature Contract 判定失败，也**不阻断、不放行**候选，只记录影子结论。
- 复用既有 `requirement_contract()` 与 `build_requirement_source_index()`，**不建第二份**尺寸/用户来源事实账本。
- 零模型调用、零联网；未新增图形专用生成器；未改动第四轮冻结证据。
- 复跑环境：pytest 9.2.0 / Python 3.11.18；在 `backend/` 目录下执行 `python -m pytest <测试文件>`。

## 1. 交付物清单

| 产物 | 说明 | 行数 |
|---|---|---|
| `backend/app/cad_feature_contract.py` | Sidecar 最小实现：结构、校验、绑定、冲突记录、影子报告 | 343 |
| `backend/tests/test_cad_feature_contract.py` | 真实账本追溯、ID 稳定性、负向守卫测试 | 291 |
| `backend/evaluations/v1/proposals/feature_contract_fields.v1.json` | 正式机器可读规格（正式来源类名，未接入生产 schema） | 见提交统计 |
| 本报告 | 追溯样例、负向逐条结果、稳定性证据、缺口说明 | — |

提交拆分：实现模块单独一个 commit；测试、规格与报告为第二个 commit。

## 2. 结构落地（与锁定口径对照）

### 2.1 FeatureContract（`cad.feature-contract.v1`）

字段：`feature_id`、`feature_class`、`source_class`、`source_refs`、`evidence`、`derivation`、`measurement`、`acceptance_scope`、`conclusion`、`provenance`、`valid`。

- `feature_class` 枚举：`boundary_extremum` / `cusp` / `notch` / `mirror_symmetry` / `continuity`。
- `evidence`：`source_ref` + 字符跨度 `start`/`end` + 原文 `text` + `source_revision`。
- `derivation`：`rule_id` + `rule_version`（+ `input_refs`、`inference_steps`），仅 `derived_semantic` 必填。
- `measurement`：`status`（`measured` / `undetermined` / `not_applicable`）、`metrics`、`tolerance_ref`、`note`。
- `provenance`：`contract_version`、`source_index_schema`、`shadow_only=true`。

### 2.2 FeatureBinding（`cad.feature-binding.v1`）

字段：`binding_id`、`schema="cad.feature-binding.v1"`、`contract_id`、`target_ref`、`reference_ref`、`source_refs`。一个契约只绑一个 `target_ref`；成对特征（如两段间连续性）用 `reference_ref` 指向第二对象。

### 2.3 FeatureMeasurement（`cad.feature-measurement.v1`）

测量量结构留位；**A 线不自造测量算法**。几何测量由 B 线混合机制实现：双向最近点距离 + 方向/端点/闭合/部件对应/拓扑；不得只用 Hausdorff 判等价。无法给出可靠误差证据时返回 `undetermined`。`tolerance_ref` 只引用既有容差族标识，不在本模块新设阈值。

## 3. 来源三类与互斥升级约束

### 3.1 正式名与允许验收范围

| 正式 `source_class` | 含义 | 允许 `acceptance_scope` | 说明 |
|---|---|---|---|
| `explicit` | 用户明确要求 | `mandatory` / `semantic_only` / `advisory` | 可参与强制验收，可提供 H3 用户来源授权 |
| `derived_semantic` | 版本化规则授权的系统推导 | `semantic_only` / `advisory` | 不能冒充 `explicit`，不能替代 H3 用户授权 |
| `model_assumption` | 非权威假设 | `advisory` | 不得进入强制验收 |

三者**不得互相升级**：`derived_semantic -> mandatory`、`derived_semantic -> explicit`、`model_assumption -> semantic_only`、`model_assumption -> mandatory` 均在校验层拒绝。

### 3.2 第五轮草案改名映射表

| 第五轮草案旧名 | 第六轮正式名 | 备注 |
|---|---|---|
| `user_explicit` | `explicit` | 仅改名，语义不变 |
| `semantic_derived` | `derived_semantic` | 仅改名，语义不变；新增规则版本化授权要求 |
| —（无） | `model_assumption` | 本轮新增；非权威假设，仅 `advisory` |

## 4. 真实账本追溯样例（已查证）

### 4.1 输入与账本

真实输入文本（通用措辞，不含任何形状专用分支）：

> 生成一个平行排列的矩形，宽度4米，高度3米，中心在(2,3)

经 `project_requirement_ledger()` 生成真实账本，再由 `build_requirement_source_index()` 产出不可变来源索引。

### 4.2 命中的来源条目

- `source_ref`：`user-1`
- 索引条目 `source_type`：`explicit`；`source_status`：`valid`
- `original_text`：`生成一个平行排列的矩形，宽度4米，高度3米，中心在(2,3)`
- `contract_version`（`source_revision`）：`bccfbb771cd3a1806f32d633856497b546e2c8811dcad1f515f6680021014cbb`

### 4.3 命中的真实事实与证据跨度

- 宽度事实 `fact_id`：`user-1:scalar-1:width:平行排列的矩形`；`field=width`；`status=effective`
- 证据：`start=12`、`end=16`、`text="宽度4米"`；切片 `original_text[12:16] == "宽度4米"` 校验通过。
- 同账本证据项 `requirement_id`：`user-1:req-1`（数量，“一个”，2–4）、`user-1:req-2`（连接，“平行”，4–6）、`user-1:req-3`（尺寸，“宽度4米”，12–16）、`user-1:req-4`（尺寸，“高度3米”，17–21）、`user-1:req-5`（位置，“中心”，22–24）。

### 4.4 构造的显式特征声明（追溯闭环）

- `feature_class=boundary_extremum`、`source_class=explicit`、`source_refs=["user-1"]`
- `evidence.source_ref="user-1"`，跨度 12–16，文本 `宽度4米`，`source_revision` 等于索引 `contract_version`
- `target_ref="step-1:outline"`，`acceptance_scope=mandatory`，`measurement.status=undetermined`，`tolerance_ref="distance.center_distance.default"`
- 校验结果：`valid=true`；绑定 `cad.feature-binding.v1` 生成；`shadow_only=true`，结果中无候选 `decision` 字段。

## 5. `requirement_id` / `fact_id` 稳定性证据（已查证）

构造“计划修复前后”两次快照：

1. 修复前：`project_requirement_ledger(ORIGINAL)`。
2. 修复轮：用户原文不变（试算反馈不是用户 follow-up），`project_requirement_ledger(ORIGINAL, previous=before)` 重建快照。

对比断言（测试 `test_requirement_and_fact_ids_are_stable_across_repair_turn_snapshot`）：

- 两次 `real_source_facts()` 的 `fact_id` 列表逐项相等；
- 两次 `evidence_items` 的 `requirement_id` 列表逐项相等（`user-1:req-1 … req-5`）；
- 两次来源索引 `contract_version` 相等；
- 同一来源事实在两轮都解析到同一 `source_id`，证据 `source_revision` 与各自索引版本一致。

结论：用户原文未变时，来源事实 ID 与证据 ID 不随修复轮次无故改变；原文变化产生新的 `source_id` 属预期行为。

## 6. 负向用例逐条结果

复跑命令（`backend/` 目录下）：

```
python -m pytest tests/test_cad_feature_contract.py -v
```

| # | 用例 | 触发条件 | 期望错误码 | 关键字段断言 | 结果 |
|---|---|---|---|---|---|
| 1 | `test_negative_1_unknown_source_ref_is_rejected_fail_closed` | `source_refs` 指向索引外 `no-such-source` | `fc_unknown_source_ref` | 记录 `valid=false`；不生成绑定 | PASSED |
| 2 | `test_negative_2_out_of_range_evidence_span_is_rejected` | 跨度 9999–10000 超出原文长度 | `fc_evidence_span_out_of_range` | 记录 `valid=false`；附 `start/end/source_length` | PASSED |
| 3 | `test_negative_3_evidence_text_mismatch_is_rejected` | 跨度内文本篡改为 `宽度9米` | `fc_evidence_text_mismatch` | `expected` 为原文切片，`actual="宽度9米"`；`valid=false` | PASSED |
| 4a | `test_negative_4a_derived_without_rule_version_is_rejected` | `derived_semantic` 缺 `rule_version` | `fc_derivation_rule_missing` | `valid=false` | PASSED |
| 4b | `test_negative_4b_unauthorized_derivation_rule_is_rejected` | 规则 `unregistered_rule` v9 不在授权注册表 | `fc_derivation_rule_unauthorized` | 附 `rule_id/rule_version`；`valid=false` | PASSED |
| 5 | `test_negative_5_model_assumption_cannot_enter_mandatory_acceptance` | `model_assumption` 声明 `mandatory` | `fc_assumption_forbidden_mandatory` | `valid=false` | PASSED |
| 5b | `test_negative_5b_derived_semantic_cannot_be_upgraded_to_mandatory` | `derived_semantic` 声明 `mandatory` | `fc_derived_cannot_be_mandatory` | `valid=false` | PASSED |
| 6 | `test_negative_6_multi_target_binding_ambiguity_is_rejected` | 一个契约绑 `step-1:outline`、`step-2:outline` 两个目标 | `fc_multi_target_ambiguous` | `valid=false`；绑定列表为空 | PASSED |
| 7 | `test_negative_7_explicit_derived_conflict_records_explicit_wins_without_overwrite` | 同特征同类下 `explicit` 结论 `true` 与 `derived_semantic` 结论 `false` 矛盾 | `fc_explicit_derived_conflict` | 冲突记录 `resolution=explicit_wins_derived_downgraded_to_advisory`；显式保留结论与 `mandatory`；派生降级 `advisory`；两条记录均不被静默覆盖 | PASSED |

### 6.1 用例 6 的口径说明

多对象来源绑定歧义本轮取**拒绝（fail-closed）**，而不是返回 `undetermined`：Sidecar 阶段尚未建立部件对应关系，无法判断来源能否唯一对应到某一目标；在 B 线对应测量结果可辅助判定之前，宁可拒绝也不猜测。后续若测量侧能给出唯一对应证据，可将该场景降级为 `undetermined` 并记录原因。

## 7. 既有回归结果

在 `backend/` 目录下执行：

```
python -m pytest tests/test_cad_construction.py tests/test_cad_construction_interpreter.py tests/test_cad_generation_recovery.py -q
```

结果：**125 passed in 27.46s**（`test_cad_construction.py` 37 + `test_cad_construction_interpreter.py` 74 + `test_cad_generation_recovery.py` 14），无失败、无跳过异常。本轮未改动上述模块及其既有签名。

## 8. 容差族复用（不自造阈值）

`measurement.tolerance_ref` 仅引用既有容差族标识：

- `distance.center_distance.default`：既有中心距离默认容差 0.001（约束求解器距离族）；
- `angle.tangent`：既有切线角度容差与平行/垂直角度容差；
- `band.normalized`：实测外接框独立归一化带 [0,1]；
- `sampling.max_sampling_error`：既有弦采样误差检查。

具体测量量与数值由 B 线测量机制填充；A 线不在此标定阈值松紧。

## 9. 已查证 / 推断 / 待验证

### 9.1 已查证

- 来源索引条目字段、事实 `fact_id` 与证据跨度口径，均来自真实 `requirement_contract()` / `build_requirement_source_index()` 输出（§4 取值可复跑）。
- 三类来源与验收范围的拒绝规则在模块校验层生效，负向用例逐条通过（§6）。
- 未改动 `agent_service.py`、`cad_generation_recovery.py`、`cad_construction*.py`、公共 Schema、`cad_requirement_ledger.py` / `cad_requirement_contract.py` 既有签名；`git status` 仅含本轮自有新文件。
- 三组指定回归 125 项通过。

### 9.2 推断 / 设计判断

- Sidecar 结构与既有计划载荷解耦，预期不影响历史候选与既有夹具；该兼容性结论尚未以全量回放夹具实测。
- 授权规则注册表当前仅登记 `shape_outline_features` v1；其“原文到特征”的规则本体归属待与规则侧/B 线对齐。

### 9.3 待验证（交后续轮次 / B、C 交叉）

- B 线混合测量机制接入后，`metrics` 实测值、`tolerance_ref` 松紧与 `undetermined` 触发条件的真实表现。
- C 线消费影子结论的路由口径：特征缺失/拓扑错误如何映射到结构重规划，且不改变现有有界修复进度闸门。
- 派生特征与既有 H3 来源授权校验（`validate_junction_source_refs` 路径）的对接方式；本轮模块不直接产出 `authorization` 字段。
- 全量测试套件回归（本轮仅跑指定三组）。

## 10. 诚实缺口（本轮做不到的部分）

1. **没有真实几何测量**：所有 `measurement.status` 本轮为 `undetermined`；A 线未实现最近点、切线夹角、曲率符号、对称残差等测量算法，字段仅留位。
2. **没有候选判定接入**：影子结论未被任何编排路径消费；候选通过/放行条件与本轮前完全一致。
3. **规则推理本体未实现**：`derived_semantic` 的规则注册表是授权位，规则如何从原文展开为特征清单，不在本轮 A 线范围。
4. **多对象对应未求解**：歧义场景当前一律拒绝；唯一对应证据依赖 B 线部件/拓扑测量。
5. **对称/极值测量口径未标定**：最近点对应与参数对应残差的可比性、尖点切线估计稳定性，均待 B 线验证。
6. **未做全量回归**：除 §7 三组外，其余测试套件本轮未运行。
7. 本报告基于单案例背景形成的接口落地，不外推为全部形状场景的覆盖结论。

## 11. 边界核对清单

- 未调用任何模型接口，未联网；`real_model_calls=0`。
- 未修改冻结公共 Schema，未进入断言/约束联合类型。
- 未新增形状专用生成器、专用控制点或专用提示词；代码与测试中无形状专有分支字符串。
- 未放宽 H2/H3/H4、自相交、来源授权、候选保存条件；未增加 `max_repairs`。
- 未合并、未推送、未 amend；新提交基于 `45090f6`。
