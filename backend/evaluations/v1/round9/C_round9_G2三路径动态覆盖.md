# Round9 G2 三路径受控动态触发覆盖报告（Agent C）

- 工作树：`tmp/g2-dynamic`；父节点 `fe63db32249205abcdb8d0677067dd597ddcbc26`（G1 护栏提交，父 `2989e8c4…`）。
- 性质：零费用、无真实模型的受控动态触发夹具；三路径均走**真实执行链**（本地 Mock 模型 callback + 真实构造/执行器/独立语义验收/汇总/候选谓词），未使用 monkeypatch 注入触发条件。
- 本轮未改生产代码语义：变更集仅含探针、结果 JSON、测试与本报告；A 的两个语义模块未触碰。
- 机器可读记录：`c_round9_g2_path_results.json`；可复跑驱动：`c_round9_g2_path_harness.py`；单测：`tests/test_c_round9_g2_paths.py`（6 项）。

## 1. 覆盖路径与触发方式

| 路径 | 解释器入口（行号） | 触发方式 | 夹具标识 | 自然触发条件 |
|---|---|---|---|---|
| A 诊断回放 | `:1026` 诊断 trial 重执行；`:1028` 绑定语义验收；记录 `:1041-1047` | natural | `A-diagnostic-replay` | `entity_count` 断言要求 2 个图元、实际仅 1 个圆，执行器自然抛 `assertion_failed`；断言清空后的诊断 trial 仍跑独立语义验收并落诊断记录 |
| B astroid 修复试算 | `:1085` 修复 trial 语义验收；修复记录 `:1093-1097` | natural | `B-astroid-repair` | 星形线参数曲线被挂不适用的 `radial_pattern/profile=smooth` 断言，断言自然失败；移除该断言后独立 astroid 身份证明通过，递归重解释 |
| C 多边形边界修复试算 | `:1118` 修复 trial 语义验收；修复记录 `:1127-1131` | natural | `C-polygon-boundary-repair` | 正六边形折线被挂不适用的 `bounds_size 2×2` 断言，断言自然失败；移除后独立正多边形证明通过，递归重解释 |

三路径 `trigger_kind` 均为 `natural`；无 `injected` 项，未在生产代码留测试缝。

## 2. 每条路径六项证据

### 2.1 路径 A — 诊断回放

- **输入夹具**：source「画一个半径1米的圆」；单 `add_circle`，圆心 (0,0)、半径 1；断言 `entity_count/wrong-count/equals=2`。
- **验收输出**（诊断记录 `independent_source_failure`）：
  - `status=not_checked`，`review_required=True`，`reason=no_semantic_requirement_matched`，`coverage=partial`；
  - `binding`：`binding_source=execute_construction_plan.logical_objects`、`binding_trust=trusted`、`issues=[]`、`model_declared_object_id_trusted=False`、`identity_anchor=backend_resolved_geometry_refs`；
  - `diagnostic_only=True`，`candidate_accepted=False`。
- **汇总输出**：诊断结果为 `invalid`，按生产语义**不挂正式汇总**；探针用诊断记录中的语义报告离线重建审计汇总（仅审计用途，不落候选）：`status=review_required`、`review_required=True`、`semantic_requirement_state=no_applicable_requirement`、`semantic_applicable_requirement_kinds=[]`。
- **候选状态**：`candidate_is_accepted=False`；`authoritative_acceptance_summary=None`。
- **修复计数**：确定性修复 0 次；修复预算 `max_repairs=2`（`bounded_repair_available` 默认值未变，`__defaults__=(2,)`）。
- **Mock 调用计数**：1（仅本地 callback，0 真实模型请求）。

### 2.2 路径 B — astroid 修复试算

- **输入夹具**：source「生成星形线，最大半径2米」；`add_parametric_curve`，`x=2·cos³t`、`y=2·sin³t`，`0..2π`，闭合；断言 `radial_pattern/smooth/lobes=4/profile=smooth`。
- **验收输出**（独立证明 `independent_acceptance`）：
  - `status=passed`，`review_required=False`，`coverage=astroid_identity_radius_and_four_cusps`；
  - `binding`：trusted、`issues=[]`、模型声明对象 ID 不可信、后端解析几何引用锚定；
  - 修复记录 `geometry_unchanged=True`，修复 kind `source_curve_identity_replaces_inapplicable_smoothness`。
- **汇总输出**（真实生产入口 `result.acceptance_summary`）：`status=review_required`、`review_required=True`、`semantic_requirement_state=fully_verified`、`semantic_applicable_requirement_kinds=[astroid_identity]`、`semantic_incomplete_objects=[]`、`semantic_incomplete_reasons=[]`。
  - 说明：汇总仍 `review_required=True` 来自既有覆盖/检查计数兜底（`verified_checks=0`、`requirement_coverage=unknown`），语义通道本身已 `fully_verified`；该兜底口径与 G1 一致，未在本轮改动。
- **候选状态**：`candidate_is_accepted=False`；`authoritative_acceptance_summary=None`。
- **修复计数**：确定性修复 1 次（预算 2 内）；`max_repairs` 未改。
- **Mock 调用计数**：1。递归重解释使用解释器内联 callback，未再触发外部模型；本路径外部 Mock 仅调用一次。

### 2.3 路径 C — 多边形边界修复试算

- **输入夹具**：source「生成一个正六边形，外接圆半径1米」；`add_polyline` 六顶点 `(cos iπ/3, sin iπ/3)`，闭合；断言 `bounds_size/wrong_bbox/width=2/height=2`。
- **验收输出**（独立证明 `independent_acceptance`）：
  - `status=passed`，`coverage=explicit_regular_polygon_and_concentric_hole`，含 `regular_polygon_dimensions` 检查（sides=6、外接半径 1000 mm）；
  - `binding`：trusted、`issues=[]`、后端解析几何引用锚定；
  - 修复记录 `geometry_unchanged=True`，修复 kind `source_radial_acceptance_replaces_unrequested_bounds`。
  - 口径说明：passed 专用分支证明字典合法地不携带 `review_required`/`reason` 键；归属未丢弃的判定以 `status/coverage/binding` 在场为准，复核/原因字段仅在非 passed 证明中强制要求。
- **汇总输出**（真实生产入口）：`status=review_required`、`review_required=True`、`semantic_requirement_state=fully_verified`、`semantic_applicable_requirement_kinds=[regular_polygon]`、`semantic_incomplete_objects=[]`。
- **候选状态**：`candidate_is_accepted=False`；`authoritative_acceptance_summary=None`。
- **修复计数**：确定性修复 1 次（预算 2 内）；`max_repairs` 未改。
- **Mock 调用计数**：1。

## 3. 六项证据核对矩阵

| 证据项 | A 诊断回放 | B astroid 修复 | C 多边形边界修复 |
|---|---|---|---|
| 1. 可信绑定传入验收器（trusted + issues=[] + 后端几何锚定） | ✅ | ✅ | ✅ |
| 2. 异常/验收归属信息未丢弃（status/coverage/binding 在场；非 passed 记录 review_required/reason） | ✅ | ✅ | ✅ |
| 3. `unresolved`/`review_required` 传到汇总层（汇总字段实际值） | ✅（离线重建审计汇总 `review_required=True`；诊断记录字段齐全） | ✅（正式汇总 `review_required=True`） | ✅（正式汇总 `review_required=True`） |
| 4. 不生成 accepted 候选（`candidate_is_accepted=False`、权威汇总 None） | ✅ | ✅ | ✅ |
| 5. `max_repairs=2` 与自动修复次数未变（A 0 / B 1 / C 1，均 ≤2） | ✅ | ✅ | ✅ |
| 6. 全程 0 真实模型请求（Mock 计数各 1） | ✅ | ✅ | ✅ |

## 4. 回归计数（G1 后基线对照）

| 套件 | G1 改后基线 | G2 改后 | 说明 |
|---|---|---|---|
| 12 模块组合 + Round8 接线 + G1 护栏 + G2 三路径套件 | 211 passed / 0 failed（184 + 15 + 12） | **217 passed / 0 failed**（184 + 15 + 12 + 6） | 无新增失败 |
| 语义套件 `test_cad_semantic_acceptance.py` | 19 passed / 2 failed | 19 passed / 2 failed | 两项为 A 模块基线既有失败，非本轮引入 |
| 相邻 16 套件（候选保存/可见性门/编辑门/关系验收/对象约束/构造评估/最终源契约/恢复/提交/权威证据/项目候选/需求台账/路径/描边/投影/重复） | 162 passed / 0 failed | **162 passed / 0 failed** | 草稿可保存授权未变 |
| Round8 接线 + G1 护栏 + G2 路径 + 语义套件合计 | — | 76 passed / 2 failed | 失败两项同上，A 侧既有 |

- 收集期既有环境缺口（基线即存在）：`test_cad_history_replay.py`、`test_cad_acceptance_metrics.py` 依赖未入库 `tests.manual` 包，本地收集报错，未纳入计数。
- A 模块既有失败：`test_structural_counter_schema_preserves_multiple_paths_without_coordinates`、`test_unsupported_styles_and_multiple_objects_are_not_falsely_fully_verified`，归属 A 侧，本轮未触碰其文件。

## 5. 边界与未决说明

- 三路径均为自然触发；未新增专用验收器/专用生成器；未放宽 H2/H3/H4；未改 `max_repairs`；未改候选保存/草稿授权条件。
- 路径 A 的正式生产汇总在 `invalid` 结果上不存在，这是既有生产语义；离线重建汇总仅用于审计复核标记是否可达，不代表诊断 trial 可被持久化为候选。
- 本轮未改冻结输入；未重跑 A9；未启动 S1；未合并/推送/amend/rebase。
- 残留观察项沿用 G1 报告 §6：缺失报告的源信号盲区、其余 `*_acceptance` 子报告尚未接三状态判据、候选谓词不重复实现语义判断；本轮未扩大修复范围。

## 6. 复现命令（`backend/` 目录）

- 探针：`python evaluations/v1/round9/c_round9_g2_path_harness.py --out evaluations/v1/round9/c_round9_g2_path_results.json`
- 单测：`python -m pytest tests/test_c_round9_g2_paths.py -q`
- 组合回归：`python -m pytest tests/test_cad_requirement_contract.py tests/test_cad_plan_component_repair.py tests/test_cad_final_source_contract.py tests/test_cad_construction_interpreter.py tests/test_candidate_visibility_gate.py tests/test_cad_construction.py tests/test_cad_topology_safety_b1.py tests/test_cad_topology_safety_b11.py tests/test_cad_topology_safety_b12.py tests/test_c1_integration_mock.py tests/test_c11_service_two_round_mock.py tests/test_c12_production_loop_mock.py tests/test_c_round8_caller_wiring.py tests/test_c_round9_g1_summary_guard.py tests/test_c_round9_g2_paths.py -q`
