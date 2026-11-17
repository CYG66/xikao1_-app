# R0 GitHub 后端资产审计与新环境可恢复性报告

- 仓库：`CYG66/xikao1_-app`
- 审计基线：`9bd105fed075c717df88774f7abb4cd4e7a21c3a`
- 基线提交说明：`Sync backend source from local workspace`
- 审计分支：`v1/d0-baseline`
- 审计时间：2026-11-17
- 审计性质：只读审计 + 零依赖静态检查
- 生产代码修改：无
- 真实 DeepSeek 调用：0
- 依赖安装：未执行
- 全量 pytest：未执行

## 0. 结论摘要

1. **代码基线正确。** 当前 HEAD 等于指定提交，工作树干净，`v1/d0-baseline` 尚未推送。
2. **GitHub 后端源码基本完整。** `backend/` 共 353 个文件、约 4.34 MB；`app/` 128 个文件、127 个 Python 文件、59,432 行；`tests/` 139 个 Python 文件、1,484 个测试函数；`evaluations/` 68 个文件（51 个 Markdown、15 个 JSON、2 个 DXF）。
3. **代码可静态解析，但不能直接运行。** 当前 Python 3.13.18 环境缺少 pytest、fastapi、pydantic、numpy、scipy、shapely、ezdxf、Pillow 等全部项目依赖；270 个 Python 文件通过语法编译，0 个语法错误。
4. **测试基线不完整。** `tests/manual/` 未进入仓库，6 个测试模块在收集阶段就会导入失败；HTTP 测试还需要 `httpx`，而 `requirements.txt` 未声明。当前不能声称“测试全绿”。
5. **冻结案例状态分层明确。** A9、S1 已冻结；M1 未冻结。A9 的历史计划文件和原始模型响应不在仓库中，不能做精确回放。
6. **H2/H3/H4 代码存在，但没有当前端到端通过证据。** H3.3 仍缺完整 `conversation_id` / 目标版本自动继承；H4 尚无真实模型端到端验证。
7. **6 例和 55 例 Benchmark 不是端到端成功率。** 它们只覆盖构造解释、结构化计划和试执行，且明确 `persisted=False`、`project_persistence=False`。
8. **A1、B1、C1 的文件级任务已可定义。** A1 先修 `junction_constraints` 继承；B1 增加精确曲线求交与拓扑安全修复；C1 验证 HTTP 创建、候选保存、第二轮编辑和版本继承。
9. **本轮不进入 D0 执行、A1/B1 生产修改或依赖安装。** 只交付审计、D0 可执行方案和下一阶段任务边界。

## 1. 基线核验

已执行的只读核验：

```text
git rev-parse HEAD
9bd105fed075c717df88774f7abb4cd4e7a21c3a

git branch --show-current
v1/d0-baseline

git status --porcelain=v1
（空）

git log -1
9bd105fed075c717df88774f7abb4cd4e7a21c3a
cyg
2026-11-16T23:49:45+08:00
Sync backend source from local workspace
```

结论：

- 指定 Commit 与工作树 HEAD 一致。
- 当前分支是从该 Commit 创建的本地分支。
- 审计产物写入前，工作树无未提交改动。
- 本轮不推送远端，不修改 `main`。

## 2. 后端资产完整性

### 2.1 总量

| 区域 | 文件数 | 体积 | 说明 |
|---|---:|---:|---|
| `backend/` 全部 | 353 | 4.34 MB | 不含 `.git` 与 `__pycache__` |
| `backend/app/` | 128 | 2.75 MB | 其中 127 个 `.py`，59,432 行 |
| `backend/tests/` | 139 | 1.42 MB | 139 个 `.py`，1,484 个测试函数 |
| `backend/evaluations/` | 68 | 0.33 MB | 51 `.md`、15 `.json`、2 `.dxf` |

### 2.2 核心模块与职责

| 文件 | 关键函数/类 | 审计判断 |
|---|---|---|
| `backend/app/agent_service.py` | `RobotAgentService`、`_cad_construction_model_callback`、`_interpret_cad_construction_plan`、`_request` | 生产规划入口；规则优先，模型仅在 advanced + configured 时启用 |
| `backend/app/agent_http_service.py` | `agent_chat`、`_prepare_agent_chat_context`、`_agent_chat`、`agent_chat_stream` | HTTP 会话、run 记录、候选可见性绑定 |
| `backend/app/cad_construction_interpreter.py` | `clarify_construction_request`、`interpret_construction_request`、`parse_rule_construction_plan`、`construction_acceptance_summary` | 自然语言澄清、确定性规则、结构化解释、验收摘要 |
| `backend/app/cad_construction.py` | `CadConstructionPlan`、`AddCompositePathStep`、`execute_construction_plan`、`_validate_composite_path_quality`、`_self_intersection_count` | 确定性几何执行、复合路径采样、自相交/重复段/C1 检查 |
| `backend/app/cad_requirement_contract.py` | `requirement_contract`、`build_requirement_source_index`、`validate_junction_source_refs`、`inherit_requirement_source_index` | H2 需求契约、H3 来源索引和局部约束来源校验 |
| `backend/app/cad_requirement_ledger.py` | `project_requirement_ledger`、`candidate_requirement_snapshot`、`requirement_ledger` | 需求台账与候选需求快照 |
| `backend/app/cad_source_acceptance.py` | `verify_final_source_contract`、`verify_scoped_primitives` | 最终来源契约和分部件来源验收 |
| `backend/app/cad_semantic_acceptance.py` | `semantic_requirements`、`verify_semantic_requirements` | 语义特征验收 |
| `backend/app/cad_candidate_orchestrator.py` | `prepare_new_candidate`、`persist_prepared_candidate`、`persist_candidate_variant` | 候选预检、准备、持久化 |
| `backend/app/cad_construction_commit.py` | `commit_construction_interpretation` | 构造解释到项目/候选的提交边界 |
| `backend/app/cad_project_candidates.py` | `candidate_response_payload`、`validate_candidate_geometries`、`effective_parent_variant` | 候选响应、几何校验、父版本选择 |
| `backend/app/routers/agent.py` | `/api/agent/chat`、`/api/agent/runs`、`/api/agent/confirm` | Agent HTTP 入口 |
| `backend/app/routers/projects.py` | 生成候选、保存图纸、选择版本、开始迭代 | 候选与版本 HTTP 入口 |

### 2.3 关键文件 SHA256

| 文件 | SHA256 |
|---|---|
| `backend/evaluations/p1.3e_dual_case_frozen.json` | `35932E3C831FF5B8750298A629F0AAB560DF81CE244B927A3E96A565A09ECB4D` |
| `backend/evaluations/cad_construction_model_benchmark.json` | `46A9B00DBBA14997FA808B62A55D4C7A61D8D3B9DC05887590FD9B30048CC76D` |
| `backend/evaluations/cad_construction_model_benchmark_extended.json` | `F8255040FC670254DD3BE69DCAEF009BDB81992A2B25FD8E677655A26EEC18BA` |
| `backend/app/cad_construction.py` | `C55256FB03D79743AEA7A6BCEA4224624B90C9EC125713BFEA0DFC91E591C4F6` |
| `backend/app/cad_construction_interpreter.py` | `87808D2D33C4B55F8C801BAEEB2922D28E2A7762DA89C64709F4E63C4C6FB33C` |
| `backend/app/cad_plan_component_repair.py` | `B960A7A81FA34AF144E604C0F33A2CF57134E5E260A44F12DDDD7DC0471F5AA3` |
| `backend/app/cad_requirement_contract.py` | `5158DEDF7569BF9EB8F703C60CEE9958AB01546030CE85AEE2CD052A2A7535E4` |
| `backend/app/cad_source_acceptance.py` | `C2DEFC2DDEB408F562A05F7AA4858E5300FEA0D2291C2D8EF2185CBBD77D2D81` |
| `backend/app/cad_semantic_acceptance.py` | `423ED2FF4D23D2090921C19542E2E8D9C8DCFECB49B196E3E619EB543C3A1D09` |
| `backend/app/cad_candidate_orchestrator.py` | `6F64F0FC77B3B1917F9B748D1EE107F367BF8F42951B4707C5B9609909372AB5` |
| `backend/app/agent_http_service.py` | `F36C7E5B1223A8C8CB90C10C8CE965E46FCD469123738A2A2569A472515AE618` |

### 2.4 资产完整性判断

**已保留、可直接审计：**

- CAD 构造解释器、几何执行器、约束求解器、局部修复器。
- H2 需求契约、需求台账、来源验收、语义验收。
- 候选编排、候选持久化、项目/版本路由。
- Agent HTTP 入口、run 记录、流式入口。
- A9/S1 冻结输入。
- 6 例和 55 例构造 Benchmark。
- 51 份历史评测/诊断 Markdown。

**未保留、不能假定存在：**

- A9 历史运行计划和原始模型响应。
- `evaluations/reports/` 下的历史运行报告（`.gitignore` 已排除）。
- 旧 SQLite 数据库、运行状态 JSON、`app.zip`、`.local-ai-test` 运行目录。
- `tests/manual/` 手工语料目录。
- 旧虚拟环境和完整 wheelhouse。

## 3. 自然语言 CAD 主链路：代码实际效果

当前后端不是“模型直接输出 CAD 坐标”，而是混合式链路：

```text
用户自然语言
  → 澄清与确定性规则（clarify_construction_request）
  → 规则命中：parse_rule_construction_plan
  → 规则未命中且已配置模型：结构化模型输出 CadConstructionPlan
  → execute_construction_plan 做确定性几何执行
  → 复合路径质量检查（自相交、重复段、C0/C1、曲率、采样误差）
  → H2 来源契约 / H3 来源索引 / H4 局部连续性验收
  → 候选预检、候选持久化、项目版本
```

### 3.1 已经具备的能力

- 尺寸明确的简单图元：直线、矩形、圆、圆弧、椭圆、多段线、样条。
- 复合路径：线、二次/三次 Bezier、B 样条、圆弧组合。
- 复合路径连接质量：
  - C0 端点连接；
  - 全局 `continuity=C0/C1`；
  - 局部 `junction_constraints` 的 `C0/G1/C1` 覆盖；
  - 切线角容差；
  - 重复段检测；
  - 自相交检测；
  - 曲率上限和采样误差上限。
- 几何验收：闭合、尺寸、数量、边界、面积、径向模式、中心距等断言。
- 需求来源：H2 契约、H3 来源索引、局部连接意图来源校验。
- 候选：候选预检、候选持久化、版本父链选择。
- HTTP：`/api/agent/chat`、run 列表/详情/取消/恢复、确认、项目候选与保存。

### 3.2 当前限制

1. **复杂自由轮廓仍依赖结构化模型。** 规则解析器主要覆盖明确尺寸和标准图元；复杂爱心、自由曲线、拓扑规划仍要模型输出计划。
2. **曲线仍是采样折线近似。** `add_composite_path` 执行后落库为 `polyline`，其顶点来自 `_sample_composite_path`；没有精确曲线与曲线的求交。
3. **`AddBezierStep` 落库不是 Bézier 类型。** `backend/app/cad_construction.py:1028-1034` 将 `add_bezier` 落为 `type="spline"`，`degree=len(control_points)-1`。生产构造的四控制点 Bézier 在后续通用样条路径中会被规范化，缺少可信 provenance。
4. **全局自相交只在执行/验收阶段发现。** 现有 `_self_intersection_count` 对采样边做非相邻线段求交；能复现 A9 的段 0/5 交叉，但不能给出精确曲线参数交点，也不能在规划阶段保证全局拓扑。
5. **局部约束可能在修复链中丢失。** 历史报告已证明 A9 最终模型修复响应主动返回 `junction_constraints: []`；`merge_component_repair` 只显式保留 `step_id`、`output_ref`、`semantic`、`layer_id`，没有保护连接约束。
6. **端到端未验证。** 当前没有本轮运行的 HTTP 创建 → 候选保存 → 第二轮编辑 → 版本继承证据；H3.3 也明确缺少完整会话/目标版本自动继承。

### 3.3 对“自然语言 CAD 具体效果”的判断

- **简单、尺寸明确、标准图元**：可靠性和可验证性较高，规则路径可以独立完成。
- **复杂自由轮廓**：可生成结构化计划，但几何正确性取决于模型拓扑规划；A9 是已证实失败案例。
- **连续性与局部意图**：Schema 和验收代码存在，但模型修复链会丢失局部约束，H4 没有真实模型端到端通过证据。
- **候选与版本**：代码路径存在，但没有当前环境的端到端通过证据。
- **不能声称**“后端已经能可靠完成任意自然语言 CAD 设计”。

## 4. 冻结案例审计

### 4.1 A9

来源：`backend/evaluations/p1.3e_dual_case_frozen.json`

| 字段 | 值 |
|---|---|
| `kind` | `historical_regression` |
| 原始输入 | `生成一个左右对称、平滑闭合的爱心，中心在(2,3)，宽4米高4米` |
| 单位 | m |
| 验收 | 宽 4000 mm、高 4000 mm、中心 `[2000,3000]` mm、闭合、无自交、`left_lobe/right_lobe/center_notch/lower_tip`、C0/C1 测量且不得虚构尖点豁免 |
| 冻结状态 | `frozen` |
| 历史计划 | `p1.2e-live-20261107/A9/service-step-3.json`（未入库，当前不可用） |

哈希口径已验证：

- 文件整体 SHA256：`35932E3C...A09ECB4D`
- 文件声明的 `frozen_input_sha256`：`726a5da06e2130c9a4f4b905ece27cc1c3fa922e931f079de4e57243183054c3`
- 对 `cases` 做排序键、紧凑分隔符、UTF-8 的 canonical JSON 哈希，结果正好等于 `726a5d...54c3`。
- 因此这不是哈希不一致，而是“文件哈希”和“冻结内容哈希”两种口径。

历史诊断事实（来自仓库内报告，不是本轮运行结果）：

- 最终执行器复现 `self_intersecting_composite_path`。
- 冲突段索引为段 0 和段 5（`expanded_segment_indices=[0,5]`）。
- 采样边索引 `[5,186]`，交点约 `(2.0, 3.5289)` m。
- 根因是模型生成的首尾 Bezier 控制点在中央凹口附近回穿，属于全局拓扑规划错误。
- 最终计划 `junction_constraints=[]`；不是 JSON 解析或 H2/H3 过滤丢失。
- 历史 `service-step-3.json` 与 `model-responses.jsonl` 不在仓库中，无法做原始响应回放。

本轮状态：

```text
A9 current_execution = not_run
A9 historical_failure = known_and_documented
A9 exact_replay = unavailable
A9 pass/fail baseline = unknown
```

### 4.2 S1

来源：同一冻结文件。

| 字段 | 值 |
|---|---|
| `kind` | `new_unseen_synthetic_case` |
| 原始输入 | `新建一条开放式、平滑的 S 形曲线，使用 3 段三次 Bezier 曲线连接。起点为 (0,0) 米，依次经过 (2,1) 米、(4,-1) 米，终点为 (6,0) 米。两处内部连接点必须满足 C1 连续，不允许尖点或自交，曲线不闭合。` |
| 验收 | 开放、端点 `[(0,0),(6,0)]` m、内部锚点 `[(2,1),(4,-1)]` m、3 段 Bezier、C1、切线容差 0.01°、无自交、无退化段 |
| 冻结状态 | `frozen` |

代码状态：

- `clarify_construction_request` 已包含 `explicit_free_curve_scope` 判断（`backend/app/cad_construction_interpreter.py:170`）。
- 显式控制点自由曲线在没有整体宽高时不再被错误拦截为 `size`，而是进入 `construction_scope`。
- 仓库中存在相关回归：`backend/tests/test_cad_construction_interpreter.py:115`、`backend/tests/test_agent_orchestration_contract.py:45`。
- 但仓库中没有 S1 原始模型响应、没有 S1 完整三段三次 Bezier 计划、没有 S1 端到端几何结果。

本轮状态：

```text
S1 route = ready_for_structured_planning
S1 geometry = not_run / unverified
S1 pass/fail baseline = unknown
```

### 4.3 M1

仓库正式依据：`backend/evaluations/P1.4 A9-S1-M1真实DeepSeek评测零费用准入报告20261107.md`

该报告明确写明：

- A9 已冻结；
- S1 已冻结；
- M1 尚未冻结；
- 冻结前不调用模型。

M1 缺失的正式定义字段：

1. 原始自然语言输入。
2. 单位。
3. 折角位置（点坐标或相对位置）。
4. 允许的曲线连接方式（直线/圆弧/Bezier/样条，段数）。
5. 折角处要求 `C0` 还是允许 `G1/C1`；其他连接点的连续性要求。
6. 独立验收字段：折角角度、段数、端点、尺寸、闭合/开放、无自交、无退化段。
7. 冻结输入 SHA256 与冻结状态。

注意：旧 `backend/evaluations/parallel/00`、`parallel/05` 把 M1 列入冻结案例，这与正式准入报告冲突。**以正式报告为准：M1 未冻结。**

本轮状态：

```text
M1 freeze_status = unfrozen
M1 execution = not_run
M1 cannot be included in D0 scoring
```

## 5. H2/H3/H4、候选与版本

### 5.1 H2

- `backend/app/cad_requirement_contract.py:37` `requirement_contract`
- `backend/app/cad_requirement_ledger.py:8` `project_requirement_ledger`
- 已有来源、假设、澄清、需求项结构。
- 仓库中有 `backend/tests/test_cad_requirement_contract.py`、`test_cad_requirement_ledger.py`。
- 当前未运行，不能引用历史通过数作为本轮证据。

### 5.2 H3

- `backend/app/cad_requirement_contract.py:137` `build_requirement_source_index`
- `backend/app/cad_requirement_contract.py:151` `validate_junction_source_refs`
- `backend/app/cad_requirement_contract.py:178` `inherit_requirement_source_index`
- H3.3 报告明确剩余边界：尚未接入完整 `conversation_id` / 目标版本自动继承策略。
- 结论：来源索引和局部约束来源校验已实现，但多轮会话/版本继承仍需 C1 验证。

### 5.3 H4

- `backend/app/cad_construction.py:1151` `_validate_composite_path_quality`
- `backend/app/cad_construction.py:304` `effective_junction_constraints`
- H4 读取局部约束；未覆盖的连接点回退到全局 `continuity`。
- H4 报告明确：尚无局部连接意图的专用端到端真实模型测试；A9 的尖点意图仍需 H3 来源证据。
- 结论：H4 是最小接入，不是“端到端已完成”。

### 5.4 候选与版本

代码存在：

- `backend/app/cad_candidate_orchestrator.py:218` `prepare_new_candidate`
- `backend/app/cad_candidate_orchestrator.py:341` `persist_prepared_candidate`
- `backend/app/cad_candidate_orchestrator.py:27` `persist_candidate_variant`
- `backend/app/cad_construction_commit.py:23` `commit_construction_interpretation`
- `backend/app/cad_project_candidates.py:499` `candidate_response_payload`
- `backend/app/cad_project_candidates.py:622` `validate_candidate_geometries`
- `backend/app/cad_project_candidates.py:1065` `effective_parent_variant`

HTTP 路由存在：

- `backend/app/routers/agent.py:283` `/api/agent/chat`
- `backend/app/routers/projects.py:216` 生成候选
- `backend/app/routers/projects.py:242` 保存候选图纸
- `backend/app/routers/projects.py:292` 选择版本
- `backend/app/routers/projects.py:308` 开始迭代

当前状态：

```text
candidate_code = present
candidate_http_routes = present
candidate_e2e = not_run
version_inheritance_e2e = not_run
```

### 5.5 `junction_constraints` 丢失：代码级风险点

历史事实：

- 早期模型修复响应包含非空 `junction_constraints`。
- 最终修复响应主动返回 `[]`。
- 最终计划采用空数组。
- 不是 JSON 解析错误，也不是 H2/H3 过滤。

代码级风险：

- `backend/app/cad_plan_component_repair.py:40` 只保留 `step_id`、`output_ref`、`semantic`、`layer_id`。
- 替换步骤中的 `junction_constraints`、`continuity`、`tangent_tolerance_deg`、`allow_self_intersection` 没有显式继承。
- `backend/app/cad_construction.py:304` 在局部约束缺失时回退到全局 `continuity`，这会把“约束丢失”伪装成“使用全局默认”。
- `backend/app/agent_service.py:6229-6232` 的部件修复协议也只说保留其他部件、布局和断言，没有明确要求保留已验证的连接语义。

结论：A1 是必要修复，不是可选优化。

### 5.6 A9 自相交：代码级风险点

已有检测：

- `backend/app/cad_construction.py:1322` `_self_intersection_count`
- `backend/app/cad_construction.py:1343` `_segments_intersect_with_tolerance`
- `backend/app/cad_construction.py:1187` `allow_self_intersection=false` 时拒绝
- 冲突详情包含 `expanded_segment_indices`、`edge_indices`、`edges`
- 测试 `backend/tests/test_cad_construction.py:518` 覆盖默认拒绝自相交

缺口：

- 仅对采样折线求交，没有 Bezier-Bezier 精确求交。
- 采样密度不足时可能漏检；近切线/端点接触可能误判。
- 不能在规划阶段给出全局拓扑证据。
- 不能定位曲线参数 `t_left/t_right`，只能用采样边索引。
- A9 的第 1/6 段交叉已被历史报告复现，但当前无法用原始计划复跑。

结论：B1 应做“精确曲线求交 + 全局拓扑规划/安全局部修复”，不是重新发明自相交检测。

## 6. Benchmark 审计

### 6.1 6 例基础 Benchmark

文件：`backend/evaluations/cad_construction_model_benchmark.json`

| id | category |
|---|---|
| `l_shaped_workshop` | `freeform_outline` |
| `warehouse_with_aisles` | `composite_layout` |
| `parking_rows_and_driveway` | `repeated_layout` |
| `circular_plaza_radial_paths` | `radial_geometry` |
| `stepped_foundation` | `nested_geometry` |
| `irregular_closed_boundary` | `coordinate_geometry` |

### 6.2 55 例扩充 Benchmark

文件：`backend/evaluations/cad_construction_model_benchmark_extended.json`

- 55 例 = 原有 6 例 + 新增 49 例。
- 前 6 个 id 与基础 Benchmark 一致。
- 不包含 A9、S1、M1。
- 主要覆盖 `freeform_outline`、`composite_layout`、`repeated_layout`、`radial_geometry`、`nested_geometry`、`coordinate_geometry`。

### 6.3 运行路径与边界

| 脚本 | 模型调用 | 持久化 | 用途 |
|---|---|---|---|
| `backend/run_extended_rule_benchmark.py` | 不需要 API Key，默认规则路径 | 写 `evaluations/reports/` 下的报告 | 零费用规则基线 |
| `backend/run_cad_construction_benchmark.py` | 需要已配置 provider | 不创建项目/候选 | 真实供应商构造评测 |
| `backend/app/cad_construction_evaluation.py` | 由 callback 决定 | `persisted=False`、`experimental=True`、`project_persistence=False` | 隔离评测入口 |

`backend/app/cad_construction_evaluation.py:34` 明确写明：

> Exercise evaluation-only construction modes without persistence.

`backend/app/cad_construction_evaluation.py:86` 明确写明：

> This function never persists CAD projects, reads credentials or retries failed model calls.

因此：

- 6/55 Benchmark 可以证明构造解释、结构化计划和试执行结果。
- 不能证明 HTTP 端到端成功。
- 不能证明 H3/H4 全通过。
- 不能证明候选正式保存。
- 不能证明第二轮编辑成功。
- 不能证明项目版本正确继承。
- 不能把 6/55 的通过率写成“自然语言 CAD Agent 端到端成功率”。

## 7. 缺失文件与外部依赖

### 7.1 缺失资产

| 资产 | 状态 | 影响 | 处理 |
|---|---|---|---|
| `backend/tests/manual/` | 缺失 | 6 个测试模块收集失败 | 重新编写最小手工语料，或加 `pytest.importorskip` / marker |
| `backend/evaluations/reports/` | 缺失（`.gitignore` 排除） | 历史运行报告不可直接读取 | 可由脚本重新生成，不能冒充原始证据 |
| A9 `service-step-3.json` | 缺失 | 无法精确回放 A9 历史计划 | 标记 `unavailable`，不要重建假历史 |
| A9 `model-responses.jsonl` | 缺失 | 无法回放原始模型响应 | 标记 `unavailable` |
| 旧 SQLite 数据库 | 缺失 | 旧项目/候选状态不可恢复 | 新环境重新生成 |
| `.local-ai-test/` | 缺失 | 旧运行目录、模型响应、日志不可用 | 不作为基线证据 |
| `app.zip` | 缺失 | 旧打包运行态不可用 | 不需要 |
| 旧虚拟环境 | 存在但不可依赖 | 不能作为新基线证据 | 新建独立 venv |
| 旧 wheelhouse | 不完整 | 包含 Linux aarch64 wheel，不适配当前 Windows | 不用作完整依赖源 |
| 旧 R1 代码/备份 bundle | 不在当前仓库 | 与当前 `9bd105f` 基线不是同一仓库 | 不合并，不依赖 |

### 7.2 外部依赖

核心 `requirements.txt`：

```text
fastapi==0.116.1
uvicorn[standard]==0.35.0
pydantic==2.11.7
python-multipart==0.0.20
ezdxf==1.4.2
numpy>=2.0,<3
opencv-python-headless>=4.10,<5
scikit-image>=0.24,<1
scipy>=1.14,<2
networkx>=3.3,<4
shapely>=2.0,<3
PyYAML>=6.0,<7
Pillow>=10.4,<13
```

测试/HTTP 额外缺失：

- `pytest`：139 个测试文件、1,484 个测试函数的基础运行器。
- `httpx`：`fastapi.testclient` 需要；`backend/tests/test_agent_run_api.py`、`test_cad_manual_review_http.py`、`test_web_demo.py` 使用。
- `pytest-asyncio`：若运行异步测试，需要确认；仓库未声明。

可选原生 CAD 后端：

```text
planegcs==0.9.6
slvs==3.2
```

可选 ROS/机器人依赖：

```text
rclpy
geometry_msgs
nav_msgs
sensor_msgs
std_msgs
std_srvs
visualization_msgs
xline_msgs
xline_path_planner
```

可选图像 devkit：

```text
line2semantic（通过 XLINE_DRAWING_DEVKIT 指向外部目录，不是 pip 包）
```

### 7.3 环境变量

代码中出现的 `XLINE_*` / provider 变量（节选）：

- Agent 供应商：`XLINE_AGENT_PROVIDER`、`DEEPSEEK_API_KEY`、`DEEPSEEK_MODEL`、`DEEPSEEK_CAD_PLANNING_MODEL`、`DEEPSEEK_BASE_MODEL`、`DEEPSEEK_ADVANCED_MODEL`。
- 存储：`XLINE_DATABASE_PATH`、`XLINE_AGENT_RUN_STORE`、`XLINE_AGENT_PLAN_STORE`、`XLINE_AGENT_MEMORY_STORE`、`XLINE_AGENT_TASK_STORE`、`XLINE_AGENT_AUDIT_STORE`、`XLINE_CREATIVE_PROJECT_STORE`、`XLINE_DRAWING_VERSION_STORE`、`XLINE_MISSION_LEDGER_STORE`。
- CAD/绘图：`XLINE_CAD_DIR`、`XLINE_DRAWING_DEVKIT`、`XLINE_DEMO_MODE`。
- 约束求解：`XLINE_CONSTRAINT_BACKEND_AUTO`、`XLINE_PLANEGCS_PYTHON`、`XLINE_SOLVESPACE_PYTHON`、`XLINE_NATIVE_SOLVER_TIMEOUT_SECONDS`。
- 机器人/ROS：`XLINE_WS_ROOT`、`XLINE_WS_DIR`、`XLINE_RUNTIME_PROFILE`、`XLINE_SETUP_FILE`、`XLINE_USE_TOTAL_STATION`、`XLINE_VIRTUAL_TOTAL_STATION`、`XLINE_CAN_INTERFACE`、`XLINE_CAN_TRANSPORT`、`XLINE_USB2CAN_DEVICE`。
- 发现/演示：`XLINE_EMBEDDED_DISCOVERY`、`XLINE_DEVICE_ID`、`XLINE_DEVICE_MODEL`、`XLINE_SOFTWARE_VERSION`。

### 7.4 写入边界

生产代码中会写文件的模块（节选）：

- `backend/app/agent_attachments.py`
- `backend/app/agent_plan_store.py`
- `backend/app/agent_run_store.py`
- `backend/app/conversation_memory.py`
- `backend/app/creative_projects.py`
- `backend/app/drawing_versions.py`
- `backend/app/mission_ledger.py`
- `backend/app/task_store.py`
- `backend/app/user_model_config.py`
- `backend/app/routers/drawings.py`
- `backend/app/routers/missions.py`

评测隔离：

- `cad_construction_evaluation` 明确不持久化 CAD 项目/候选。
- `run_extended_rule_benchmark.py` 会写 `evaluations/reports/`，该目录被 `.gitignore` 排除。
- D0 必须使用临时目录/独立存储路径，禁止污染真实 `data/`。

### 7.5 真实模型调用边界

- `backend/app/deepseek_transport.py:15` `DeepSeekTransport`
- `backend/app/model_request_gateway.py` 统一请求边界
- `backend/app/agent_service.py:465` `configured` 只在 `mode == "local"` 或存在 API Key 时为真
- `backend/app/agent_service.py:6197-6203` 只有 `advanced` + 非 `local` + `configured` 才注入结构化模型 callback

零费用约束：

- 不设置任何 provider API Key。
- 使用 `local` 模式或让 `configured=False`。
- 在 D0 Mock 中显式断言 `provider_attempted=False`。
- 不运行 `run_cad_construction_benchmark.py`（它要求 provider key）。
- 不运行 `run_extended_deepseek_benchmark.py`。

## 8. 新环境基础测试结果

### 8.1 当前环境

| 项 | 结果 |
|---|---|
| Python | 3.13.18（Doubao sandbox runtime） |
| `pytest` | 未安装；`python -m pytest --version` 退出码 1 |
| 项目依赖 | 未安装；`import fastapi` 即失败 |
| 实测导入 | `fastapi`、`pydantic`、`numpy`、`scipy`、`shapely`、`ezdxf`、`networkx`、`cv2`、`skimage`、`yaml`、`PIL` 均不可用 |
| 真实模型 | 未调用 |
| 依赖安装 | 未执行 |

### 8.2 已执行的零依赖检查

```text
Python AST 编译检查
文件数：270 个 .py
语法错误：0
```

说明：

- 该检查只证明语法可解析，不证明导入、运行时行为、测试通过。
- 270 个文件包含 `app/`、`tests/`、根目录脚本；不包含 `__pycache__`。
- 这是本轮唯一实际执行的“测试类”检查。

### 8.3 测试收集阻断

`backend/tests/manual/` 不存在，但以下 6 个测试模块引用 `tests.manual`：

- `backend/tests/test_cad_acceptance_metrics.py`
- `backend/tests/test_cad_corpus_audit.py`
- `backend/tests/test_cad_product_acceptance_runner.py`
- `backend/tests/test_p12_eval_budget.py`
- `backend/tests/test_recorded_cad_repair_inputs.py`
- `backend/tests/test_user_cad_corpus_runner.py`

后果：

- 全量 `pytest backend/tests` 会在收集阶段失败。
- 不能把历史报告里的 `74 passed`、`118 passed`、`127 passed` 当作本轮结果；它们只是 `historical_report` 证据。

HTTP 测试额外阻断：

- `backend/tests/test_agent_run_api.py`
- `backend/tests/test_cad_manual_review_http.py`
- `backend/tests/test_web_demo.py`

这些使用 `fastapi.testclient`，需要 `httpx`，而 `requirements.txt` 未声明。

### 8.4 推荐环境方案（下一阶段执行，不在本轮安装）

推荐 Python：

- **优先 3.11 或 3.12。**
- 3.13 可用性需要逐包验证，尤其是 `opencv-python-headless`、`scipy`、`scikit-image` 的 wheel 兼容性。

最小安装顺序：

```text
1. 新建独立 venv（不要复用旧恢复仓库的 .venv）
2. pip install -r backend/requirements.txt
3. pip install pytest httpx
4. 可选：pip install -r backend/requirements-native-cad.txt
5. 可选：ROS2 Humble / xline_msgs（仅真实机器人或 ROS 相关测试需要）
```

最短专项测试建议（依赖安装后）：

```text
pytest backend/tests/test_cad_construction.py
pytest backend/tests/test_cad_construction_interpreter.py
pytest backend/tests/test_cad_plan_component_repair.py
pytest backend/tests/test_cad_requirement_contract.py
pytest backend/tests/test_cad_source_acceptance.py
pytest backend/tests/test_cad_semantic_acceptance.py
pytest backend/tests/test_cad_candidate_orchestrator.py
pytest backend/tests/test_cad_construction_commit.py
```

不要在依赖未安装时运行全量测试；不要在未确认预算时运行真实模型脚本。

## 9. D0 可执行评测方案

完整方案见 `backend/evaluations/v1/D0_EVALUATION_PLAN.md`。核心约束：

- 只使用仓库中真实存在的输入。
- A9/S1 冻结输入不改。
- M1 不纳入评分。
- Mock、历史报告、重建 fixture、真实模型严格区分 `evidence_mode`。
- 不计算虚假的整体提升率。
- 不污染真实项目/候选/数据库。
- 不调用真实 DeepSeek。

建议的 D0 目录：

```text
backend/evaluations/v1/
├── D0_可信基线审计报告.md
├── case_registry.json
├── evaluation_schema.json
├── mock_replay_results.json
├── D0_失败根因分类.md
└── R0_GITHUB_ASSET_AUDIT.md
```

本轮的定位：

- `R0_GITHUB_ASSET_AUDIT.md`、`r0_asset_manifest.json`、`D0_EVALUATION_PLAN.md`、`A1_B1_C1_TASK_BREAKDOWN.md` 是本轮产物。
- `case_registry.json`、`evaluation_schema.json`、`mock_replay_results.json`、`D0_失败根因分类.md` 是下一阶段 D0 执行产物，本轮不伪造。

## 10. A1/B1/C1 文件级任务与接口依赖

完整任务书见 `backend/evaluations/v1/A1_B1_C1_TASK_BREAKDOWN.md`。摘要：

### A1：约束继承

- 主改：`backend/app/cad_plan_component_repair.py:40`
- 辅改：`backend/app/agent_service.py:6228` 修复协议
- 验证：`backend/tests/test_cad_plan_component_repair.py`
- 接口：`merge_component_repair(context, payload) -> dict`
- 禁止：修改 H2/H3/H4 验收标准；无脑复制约束到拓扑已改变的步骤。

### B1：精确曲线求交与拓扑安全修复

- 主改：`backend/app/cad_construction.py:1151`、`:1322`
- 可新增：`backend/app/cad_curve_intersection.py`
- 辅改：`backend/app/cad_local_repair.py`
- 验证：`backend/tests/test_cad_construction.py` + 新 `test_cad_curve_intersection.py`
- 接口：`find_bezier_intersections(left, right, tolerance) -> list[CurveIntersection]`
- 禁止：降低 `allow_self_intersection`、关闭采样检查、放宽 P0、修改 A9 冻结输入。

### C1：HTTP 端到端

- 主改：`backend/app/agent_http_service.py:686`、`:1047`、`:1463`
- 路由：`backend/app/routers/agent.py:283`、`backend/app/routers/projects.py:216/242/292/308`
- 候选：`backend/app/cad_candidate_orchestrator.py:218/341`、`backend/app/cad_construction_commit.py:23`
- 验证：`backend/tests/test_agent_run_api.py`、`test_cad_candidate_orchestrator.py`、`test_candidate_save.py`、`test_project_lifecycle.py`、`test_cad_copy_http_identity.py`、`test_cad_manual_review_http.py`
- 接口：`AgentChatRequest`（`backend/app/schemas.py:80`）的 `conversation_id`、`client_id`、`project_id`、`variant_id`
- 禁止：真实模型、真实项目数据污染、跳过候选验收。

## 11. 无法恢复但不影响后续研发的历史资产

| 历史资产 | 是否阻塞当前研发 | 说明 |
|---|---|---|
| A9 历史 `service-step-3.json` | 不阻塞 A1/B1 | 历史诊断报告已保留控制点和段索引；A9 精确回放标记 `unavailable` |
| A9 `model-responses.jsonl` | 不阻塞 A1/B1 | 不能伪造原始响应；D0 只记录历史证据 |
| `evaluations/reports/` | 不阻塞 | 可由 D0 新环境重新生成 |
| 旧 SQLite 数据库 | 不阻塞 | 新环境重新生成 |
| `.local-ai-test/` | 不阻塞 | 旧运行状态不可恢复，不再作为基线 |
| 旧 wheelhouse | 不阻塞 | 重建依赖 |
| 旧 R1 分支代码/bundle | 不阻塞当前 `9bd105f` 基线 | 不是同一仓库；不合并 |
| `tests/manual/` | **部分阻塞测试收集** | 需要重建最小手工语料或加跳过标记 |
| `line2semantic` devkit | 不阻塞 CAD 核心 | 仅图像导入可选能力 |

## 12. 最终判断与准入建议

### 可以确认

- GitHub 基线正确。
- 核心 CAD 后端代码、冻结输入、Benchmark、历史诊断报告均已保留。
- 代码语法可解析。
- A9/S1 冻结状态明确；M1 未冻结。
- A1/B1/C1 的文件级入口和接口依赖可定位。

### 不能确认

- 当前环境不能运行 pytest。
- 全量测试不可收集。
- A9/S1 没有当前端到端通过结果。
- M1 不能评分。
- H2/H3/H4 没有当前端到端联合通过证据。
- 6/55 Benchmark 不能代表端到端成功率。
- 候选保存、第二轮编辑、版本继承没有当前 HTTP 闭环证据。

### 下一阶段准入建议

1. **先确认本审计。**
2. **建立独立新环境**：Python 3.11/3.12 + `requirements.txt` + `pytest` + `httpx`；不依赖旧虚拟环境。
3. **修复测试收集阻断**：补 `tests/manual` 最小语料，或明确标记跳过；不要把“无法收集”伪装成“通过”。
4. **执行 D0**：建立 `case_registry.json`、`evaluation_schema.json`、`mock_replay_results.json`、`D0_失败根因分类.md`。
5. **启动 A1**：先修 `junction_constraints` 继承，风险最低、对 A9/S1 都有价值。
6. **并行/随后 B1**：精确 Bezier 求交 + 全局拓扑安全修复；A1/B1 可并行，但都必须基于 D0 证据入口。
7. **C1 在 D0 后启动**：先验证现有 HTTP 链路，再在 A1/B1 合入后做统一回归。
8. **M1 先冻结再评测**：在用户确认自然语言、单位、折角位置、连接方式、验收字段后，才写入正式冻结文件。

本轮到此停止，不进入 D0 执行、A1/B1 生产代码修改、依赖安装或真实模型调用。
