# A1 / B1 / C1 文件级任务与接口依赖

- 基线：`9bd105fed075c717df88774f7abb4cd4e7a21c3a`
- 分支：`v1/d0-baseline`
- 本文性质：任务分解，不是执行授权
- 当前阶段：只读审计完成，等待下一阶段指令
- 共同前置：D0 环境与注册表可用；真实模型不可用；生产数据隔离

## 0. 总览

| 任务 | 目标 | 主要文件 | 依赖 | 风险 |
|---|---|---|---|---|
| A1 | 修复 `junction_constraints` 继承丢失 | `cad_plan_component_repair.py`、`agent_service.py` | D0-2 / D0-5 | 中 |
| B1 | 精确曲线求交与全局拓扑安全修复 | `cad_construction.py`、`cad_curve_intersection.py`、`cad_local_repair.py` | D0-2 / D0-3 | 高 |
| C1 | HTTP 端到端创建、候选、二轮编辑、版本继承 | `agent_http_service.py`、`routers/*`、候选编排 | D0 / A1 / B1 | 中高 |

并行原则：

- A1 与 B1 可以并行。
- C1 的只读基线核查可在 D0 后立即开始；最终端到端验收必须在 A1/B1 合入后重跑。
- 三条线都不修改 H2/H3/H4 的验收标准，不修改冻结输入。

## 1. A1：约束继承修复

### 1.1 问题定义

A9 历史链路已经证明：

- 早期模型修复响应含非空 `junction_constraints`；
- 最终模型修复响应主动返回 `[]`；
- 最终计划采用空数组；
- 不是 JSON 解析或 H2/H3 过滤丢失。

代码风险：

- `backend/app/cad_plan_component_repair.py:40` 只保留 `step_id`、`output_ref`、`semantic`、`layer_id`。
- `junction_constraints`、`continuity`、`tangent_tolerance_deg`、`allow_self_intersection` 没有显式保护。
- `backend/app/cad_construction.py:304` 在局部约束缺失时回退到全局 `continuity`，会把“约束丢失”表现成“正常默认”。

### 1.2 文件级任务

#### A1-1 `backend/app/cad_plan_component_repair.py`

修改 `merge_component_repair(context, payload)` 的步骤合并逻辑。

建议保留字段：

```text
step_id
output_ref
semantic
layer_id
continuity
tangent_tolerance_deg
allow_self_intersection
junction_constraints
```

继承策略：

1. 替换步骤显式提供非空 `junction_constraints`：
   - 使用替换值；
   - 后续必须经过 H3 `validate_junction_source_refs`；
   - 记录 `junction_constraints_source=replacement`。
2. 替换步骤缺失或为空，原步骤非空：
   - 继承原值；
   - 记录 `junction_constraints_source=inherited`；
   - 不改变原约束的 `junction_index`、`intent`、`required_continuity`。
3. 原步骤和替换步骤都为空：
   - 保持空；
   - 记录 `junction_constraints_source=absent`。
4. 替换步骤的段数/连接点数量变化，导致原 `junction_index` 越界：
   - 抛出 `ConstraintInheritanceError`；
   - 不允许静默丢弃或截断。
5. 替换步骤显式提供空数组，但原步骤非空：
   - 视为“未提供”；
   - 继承原值；
   - 不允许空数组覆盖已验证约束。

错误信息必须包含：

- `output_ref`
- 原段数 / 新段数
- 越界的 `junction_index`
- 建议：保留原约束或提供完整的新约束集合

#### A1-2 `backend/app/agent_service.py`

修改部件修复提示/协议（`backend/app/agent_service.py:6229-6232` 附近）。

要求：

- 明确写出“不得用空 `junction_constraints` 覆盖已验证约束”。
- 若改变段数/拓扑，必须返回完整的新 `junction_constraints`。
- 若只改坐标，保留原 `junction_constraints`、`continuity`、`tangent_tolerance_deg`。
- 说明 H3 来源校验仍会执行，模型不能凭空发明来源。

不得修改：

- H2 Schema。
- H3 `validate_junction_source_refs` 的语义。
- H4 的几何验收阈值。

#### A1-3 测试

文件：`backend/tests/test_cad_plan_component_repair.py`

新增用例：

1. `test_component_repair_preserves_non_empty_junction_constraints_when_model_returns_empty`
   - 构造原计划含 `junction_constraints`；
   - 修复返回 `[]`；
   - 断言合并后仍为原约束；
   - 断言 `junction_constraints_source=inherited`。
2. `test_component_repair_accepts_new_validated_junction_set`
   - 修复返回新的非空集合；
   - 断言使用新集合；
   - 断言后续 H3 校验被调用。
3. `test_component_repair_rejects_junction_index_out_of_range`
   - 修复改变段数，原 `junction_index` 越界；
   - 断言 `ConstraintInheritanceError`。
4. `test_component_repair_preserves_continuity_and_tolerance`
   - 修复只改坐标；
   - 断言 `continuity`、`tangent_tolerance_deg`、`allow_self_intersection` 不变。
5. `test_component_repair_does_not_override_explicit_new_empty_when_original_absent`
   - 原计划无约束，修复返回空；
   - 断言不报错，状态 `absent`。

补充：

- `backend/tests/test_cad_construction_interpreter.py` 增加“修复链保留约束”的端到端解释测试。
- `backend/tests/test_cad_requirement_contract.py` 增加“继承约束仍能通过 H3 来源校验”的测试。

### 1.3 接口契约

```text
merge_component_repair(context: dict, payload: dict) -> dict
```

返回：

- `plan`：合并后的计划；
- `merge_provenance`：可选字段，记录每个受影响 `output_ref` 的 `junction_constraints_source`；
- 不改变 `CadConstructionPlan` 的既有 Schema。

不变量：

- 只合并 `affected_output_refs` 指定的步骤。
- 不改未受影响步骤。
- 不改单位。
- 不降低断言。
- 不丢弃失败断言之外的断言。

### 1.4 验收标准

- A9 风格的“非空约束 → 修复返回空”不再丢失。
- 改变拓扑时不会静默继承不匹配的约束。
- H3 来源校验仍能拒绝无来源的 `cusp/corner`。
- 未修改 H2/H3/H4 文件。
- 新增测试在本轮环境可运行。

### 1.5 禁止事项

- 不把 `junction_constraints` 无条件复制到任何新步骤。
- 不把空数组视为“用户明确要求取消约束”。
- 不绕过 H3 来源校验。
- 不修改 A9 冻结输入。
- 不为了让测试通过而放宽 `validate_junction_source_refs`。

## 2. B1：精确曲线求交与拓扑安全修复

### 2.1 问题定义

现有代码：

- `backend/app/cad_construction.py:1322` `_self_intersection_count`
- `backend/app/cad_construction.py:1343` `_segments_intersect_with_tolerance`
- `backend/app/cad_construction.py:1187` `allow_self_intersection=false` 拒绝

现状：

- 仅对采样折线求交。
- 没有 Bezier-Bezier 精确求交。
- 没有曲线参数 `t_left/t_right`。
- 采样密度不足可能漏检；近切线可能误判。
- 不能在规划阶段保证全局非相交拓扑。

A9 历史证据：

- 段 0 控制点：`[(2.0,3.1),(2.15,3.9),(1.45,4.55),(0.65,4.55)]`
- 段 5 控制点：`[(3.35,4.55),(2.55,4.55),(1.85,3.9),(2.0,3.1)]`
- 近似参数：段 0 `t≈0.1865842491`，段 5 `t≈0.8134157509`
- 交点约 `(2.0, 3.5288683322)` m

### 2.2 文件级任务

#### B1-1 新增 `backend/app/cad_curve_intersection.py`

建议接口：

```python
@dataclass(frozen=True)
class CurveIntersection:
    left_index: int
    right_index: int
    left_t: float
    right_t: float
    point: tuple[float, float]
    kind: str  # cross | touch | endpoint | overlap
    error_bound: float

def find_bezier_intersections(
    left: Sequence[tuple[float, float]],
    right: Sequence[tuple[float, float]],
    *,
    left_index: int,
    right_index: int,
    tolerance: float = 1e-9,
    max_depth: int = 40,
) -> list[CurveIntersection]:
    ...
```

算法要求：

- 支持二次/三次 Bezier（控制点 3 或 4 个）。
- 递归细分 + 包围盒剪枝。
- 对候选区间做 Newton 或二分精化。
- 端点共享、闭合接缝、相邻段必须可排除。
- 近切线接触返回 `touch`，不误报为 `cross`。
- 重叠段返回 `overlap`，不静默吞掉。
- 深度上限和容差可配置；不得无限递归。
- 返回交点按 `left_t` 排序，稳定可复现。

#### B1-2 `backend/app/cad_construction.py`

修改 `_validate_composite_path_quality()`：

1. 对复合路径中的 Bezier 段两两检查：
   - 跳过相邻段；
   - 跳过闭合接缝；
   - 调用 `find_bezier_intersections`。
2. 非 Bezier 段继续使用现有采样求交。
3. 保留现有 `_self_intersection_count` 作为兜底，不删除。
4. `details` 增加：
   - `exact_intersection_pairs`
   - `left_segment_index`
   - `right_segment_index`
   - `left_t`
   - `right_t`
   - `intersection_kind`
   - `error_bound`
5. `allow_self_intersection=false` 时：
   - 精确求交发现 `cross`/`overlap` → 拒绝；
   - `endpoint`/正常相邻接触不拒绝；
   - `touch` 需按容差判定，不能一律拒绝。
6. 不改变现有错误码 `self_intersecting_composite_path` 的外部语义；新增字段向后兼容。

#### B1-3 `backend/app/cad_local_repair.py`

修改：

- `build_local_repair_scope` 纳入 `exact_intersection_pairs`。
- `validate_local_repair` 检查：
  - 修复后没有新增精确交点；
  - 未受影响的连接约束未改变；
  - 修复没有改变段数/闭合性/对称性（若原计划声明）。
- 若修复无法满足，返回明确拒绝，不做“尽量通过”。

#### B1-4 拓扑安全修复策略

B1 的修复不是“把交点挪开”这么简单。建议顺序：

1. **全局拓扑规划检查**：闭合路径的首尾段、凹口段、对称段优先检查。
2. **精确交点定位**：给出段索引和参数区间。
3. **局部控制点优化**：只调整冲突段控制点，保持：
   - 端点/锚点；
   - 对称关系；
   - 闭合关系；
   - 其他段的 C0/C1；
   - 原有尖点/局部约束。
4. **重新执行全路径验收**：不是只检查冲突段。
5. **失败则拒绝**：不降低 `allow_self_intersection`，不放宽 P0。

### 2.3 测试

新增 `backend/tests/test_cad_curve_intersection.py`：

1. `test_a9_segment_pair_intersection_is_detected`
   - 使用历史控制点；
   - 断言检测到 `cross`；
   - 断言 `left_t` 接近 0.1866，`right_t` 接近 0.8134；
   - 断言交点接近 `(2.0, 3.5289)`；
   - 标记 `historical_diagnostic_fixture`。
2. `test_adjacent_segments_at_shared_endpoint_are_not_reported`
3. `test_closed_path_seam_is_not_reported`
4. `test_near_tangent_touch_is_classified_as_touch`
5. `test_disjoint_curves_return_empty`
6. `test_overlapping_segments_are_reported_as_overlap`
7. `test_multiple_intersections_are_sorted_and_stable`
8. `test_recursion_depth_limit_is_enforced`

扩展 `backend/tests/test_cad_construction.py`：

- 现有 `test_composite_path_rejects_self_intersection` 保持。
- 现有 C1 测试保持。
- 增加“精确交点字段存在”的断言。
- 增加“相邻段不误报”的复合路径测试。

扩展 `backend/tests/test_cad_local_repair.py`：

- 修复后仍有交点 → 拒绝。
- 修复改变未受影响约束 → 拒绝。
- 修复成功但破坏对称/闭合 → 拒绝。

### 2.4 接口契约

```text
find_bezier_intersections(left, right, left_index, right_index, tolerance, max_depth)
  -> list[CurveIntersection]
```

不变量：

- 不修改 `CadConstructionPlan` 的公开字段。
- 不改变 `allow_self_intersection` 默认值。
- 不删除采样检查。
- 不把 `touch` 当作 `cross` 或反之。
- 不修改 A9 冻结输入。

### 2.5 验收标准

- A9 段 0/5 控制点 fixture 能稳定检测到交叉。
- 相邻段/闭合接缝不误报。
- 多交点排序稳定。
- 现有自相交拒绝测试仍通过。
- 修复后必须重新执行全路径验收。
- 不降低任何 P0/自相交断言。

### 2.6 禁止事项

- 不放宽 `allow_self_intersection`。
- 不关闭采样检查。
- 不把 A9 的失败归因于“检测器误报”。
- 不修改 H2/H3/H4。
- 不用“移动交点”掩盖拓扑错误。
- 不修改 `AddBezierStep` 的落库类型作为 B1 的副作用；`AddBezierStep` provenance 另立任务。

## 3. C1：HTTP 端到端集成

### 3.1 目标

验证以下闭环：

```text
HTTP 创建
  → Agent run
  → 构造解释
  → 几何执行
  → H2/H3/H4 验收
  → 候选预检
  → 候选保存
  → 版本选择
  → 第二轮编辑
  → 父版本/来源继承
```

### 3.2 文件级任务

#### C1-1 `backend/app/agent_http_service.py`

重点函数：

- `agent_chat`：`backend/app/agent_http_service.py:686`
- `_prepare_agent_chat_context`：`:1047`
- `_agent_chat`：`:1463`
- `agent_chat_stream`：`:1564`
- `_record_agent_run_result`：`:888`
- `_bind_and_filter_candidate_visibility`：`:162`

任务：

1. 确认 `conversation_id`、`client_id`、`project_id`、`variant_id` 的绑定顺序。
2. 确认 run 记录在成功/失败/取消时状态一致。
3. 确认候选可见性过滤不会把当前用户候选过滤掉。
4. 确认第二轮编辑使用 `variant_id` 作为父版本候选。
5. 确认错误响应包含可分类的 `failure_class`，不返回伪成功。

#### C1-2 `backend/app/routers/agent.py`

路由：

- `/api/agent/chat`：`:283`
- `/api/agent/runs`：`:288`
- `/api/agent/confirm`：`:316`
- `/api/agent/chat/stream`：`:308`

任务：

- 校验 `AgentChatRequest` 的 `extra="forbid"` 不会被前端额外字段破坏。
- 校验 run 列表/详情/取消/恢复的 `client_id` 绑定。
- 校验确认动作只作用于当前 run/候选。

#### C1-3 `backend/app/routers/projects.py`

路由：

- 生成候选：`:216`
- 保存候选图纸：`:242`
- 选择版本：`:292`
- 开始迭代：`:308`
- 确认实例组：`:330`

任务：

1. 候选生成后返回 `variant_id`、`project_id`、`preview_paths`。
2. 保存图纸在 `overwrite`/`file_name` 语义下不覆盖旧版本。
3. 选择版本后当前版本指针正确。
4. 开始迭代创建新候选，父版本正确。
5. 所有路由都做项目/客户端绑定校验。

#### C1-4 `backend/app/cad_candidate_orchestrator.py`

函数：

- `prepare_new_candidate`：`:218`
- `persist_prepared_candidate`：`:341`
- `persist_candidate_variant`：`:27`
- `candidate_preflight`：`:125`
- `restore_existing_candidate`：`:159`

任务：

- 候选预检必须在持久化前完成。
- 候选持久化只写临时/项目 store。
- 第二轮编辑的 `parent_variant_id` 必须来自当前 `variant_id`。
- 候选失败时不能留下半成品。

#### C1-5 `backend/app/cad_construction_commit.py`

函数：`commit_construction_interpretation`：`:23`

任务：

- 确认提交只在验收通过后发生。
- 确认提交返回的 `project_id`、`variant_id`、`run_id` 与 HTTP 层一致。
- 确认失败时不写项目。

#### C1-6 H3.3 会话/版本继承缺口

涉及：

- `backend/app/cad_requirement_contract.py:178` `inherit_requirement_source_index`
- `backend/app/agent_service.py` 会话上下文构造
- `backend/app/agent_http_service.py:1047` `_prepare_agent_chat_context`

任务：

- 明确 `conversation_id` 与 `project_id` / `variant_id` 的优先级。
- 旧来源只在与当前原文完全一致时继承。
- 旧来源不能单独授权当前 `junction`。
- 切换项目/版本时旧来源进入 `stale_previous_refs`。
- 第二轮编辑的需求来源索引必须可追溯到当前项目和当前父版本。

### 3.3 测试

HTTP 测试前置：

- `pytest`、`httpx` 已安装。
- 临时 store 路径。
- Mock provider，真实 provider 不可用。

测试文件：

- `backend/tests/test_agent_run_api.py`
- `backend/tests/test_cad_candidate_orchestrator.py`
- `backend/tests/test_candidate_save.py`
- `backend/tests/test_project_lifecycle.py`
- `backend/tests/test_cad_copy_http_identity.py`
- `backend/tests/test_cad_manual_review_http.py`
- `backend/tests/test_agent_orchestration_contract.py`
- `backend/tests/test_design_requirement_followup.py`

核心用例：

1. `test_http_chat_returns_run_id_and_completed_state`
2. `test_http_chat_does_not_call_live_provider`
3. `test_http_candidate_generate_and_save`
4. `test_http_select_variant_and_start_iteration`
5. `test_second_turn_uses_explicit_variant_id_as_parent`
6. `test_second_turn_preserves_requirement_source_index`
7. `test_cross_project_variant_is_rejected`
8. `test_cross_client_run_is_rejected`
9. `test_candidate_preflight_failure_does_not_persist`
10. `test_stream_chat_matches_non_stream_contract`

### 3.4 接口契约

`AgentChatRequest`（`backend/app/schemas.py:80`）：

```text
message
history
attachments
mode
conversation_id
client_id
project_id
variant_id
drawing_selection
```

不变量：

- `extra="forbid"` 保持不变。
- `conversation_id`、`client_id` 的 pattern 不放宽。
- `variant_id` 是显式父版本，不用“最近一次候选”隐式替代。
- 第二轮编辑必须带 `conversation_id` + `variant_id`。
- 所有写入使用临时 store，不碰真实项目数据。

### 3.5 验收标准

- HTTP 创建返回 `agent_run_id`，run 状态正确。
- 候选生成/保存/选择/迭代全链路可重复。
- 第二轮编辑父版本正确。
- 需求来源索引可追溯。
- 跨项目/跨客户端访问被拒绝。
- 失败不产生半成品。
- 全程 `provider_attempted=False`（Mock 模式）。

### 3.6 禁止事项

- 不调用真实 DeepSeek。
- 不写真实数据库/项目目录。
- 不用“最近候选”替代显式 `variant_id`。
- 不绕过候选预检。
- 不修改 H2/H3/H4 验收标准。
- 不把单元测试通过当作 HTTP 端到端通过。

## 4. 依赖顺序

```text
R0 审计（本轮）
  ↓
D0 环境 + 注册表 + Mock
  ↓
A1 ──┬── B1
     │
     └── C1 基线核查
           ↓
     A1/B1 合入后 C1 最终端到端
           ↓
          D1 统一回归
```

规则：

- D0 未完成，A1/B1 不应开始生产修改。
- A1/B1 未完成，C1 可以只做只读基线核查，不做最终通过结论。
- A1 与 B1 互不阻塞。
- 任何一条线都不能修改 H2/H3/H4 或冻结输入。

## 5. 统一证据要求

每条任务完成时必须提交：

1. 修改文件列表与 diff 摘要。
2. 新增/修改测试列表。
3. 运行命令与 Python/依赖版本。
4. 测试输出原文或机器可读报告。
5. 失败项分类。
6. 未覆盖项/unknown 字段。
7. 是否调用真实模型、是否写真实数据。
8. 与 D0 基线的对比，不用历史报告冒充本轮。

## 6. 当前准入建议

1. 先确认 R0 审计。
2. 建立新环境，修复 `tests/manual` 收集阻断。
3. 执行 D0。
4. 启动 A1。
5. A1 稳定后并行 B1。
6. A1/B1 合入后启动 C1 最终端到端。
7. M1 先冻结，再纳入 D1。
