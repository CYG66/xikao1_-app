# Round8 A-line 绑定接口契约与载荷校验报告

> 角色：A（语义模块维护）。本轮只固化绑定接口契约与模块侧载荷护栏，**未改任何生产调用方文件**。
> 零真实模型请求、零网络、零费用；夹具均为脚本内合成的重建夹具（非历史回放）。

## 1. 结论摘要

- 已发布语义验收目标绑定接口契约（文档 + 机器可读 JSON schema 草案），供 C 接线直接照调。
- 模块侧完成严格载荷校验与安全降级：畸形 / 悬空 / 排除 / 重复 / 空引用 / 归属冲突 / 不唯一归属一律 `unresolved` + `review_required=True`，不得整体 PASS；可信 `geometry_refs` 优先于连通分量证据；接触/重叠不合并、多段不连通不拆分。
- 本提交基于既有补丁 `e7831921ef904deaa893573da8cc793056a9cf41` 之上另建独立提交；`e7831921` 原样保留，未 amend、未 rebase、未 push、未 merge main。
- 语义模块测试：基线 21 项（19 通过 / 2 项既有失败）→ 本轮 38 项（36 通过 / 同 2 项既有失败），新增 17 项全部通过；相邻模块回归 82 项通过（此前一轮相邻集合 148 项通过）。

## 2. 提交与改动范围

| 项 | 值 |
|---|---|
| 基线父节点 | `7567f7bb32d9571048f1d66deb8124df3bcf9d02` |
| 既有 P0 补丁（未改动） | `e7831921ef904deaa893573da8cc793056a9cf41` |
| 分支 | `v1/a-p0-semantic-dispatch`（评审工作树，未推送、未合并） |
| 本提交父节点 | `e7831921ef904deaa893573da8cc793056a9cf41` |
| 本提交 SHA | 提交后由 `git rev-parse HEAD` 回填（见交付回复） |

### 2.1 改动文件（`git diff --numstat`，相对 `e7831921`）

| 文件 | 新增 | 删除 | 性质 |
|---|---:|---:|---|
| `backend/app/cad_semantic_dispatch.py` | 270 | 41 | 模块：绑定校验器 + 诊断 |
| `backend/app/cad_semantic_acceptance.py` | 43 | 6 | 模块：前置载荷护栏 + 爱心通道绑定元数据 |
| `backend/tests/test_cad_semantic_acceptance.py` | 215 | 0 | 模块级零模型测试 |
| `backend/evaluations/v1/round8/A_round8_绑定接口契约.md` | 新增 | — | 接口契约文档 |
| `backend/evaluations/v1/round8/A_round8_binding_contract.schema.json` | 新增 | — | 机器可读 schema 草案 |
| `backend/evaluations/v1/round8/A_round8_绑定接口与载荷校验报告.md` | 新增 | — | 本报告 |

### 2.2 未触碰证明

- 调用方文件（解释器 `cad_construction_interpreter.py`、`agent_service.py`、恢复/回放模块等）本轮**零改动**；`git diff --stat` 仅含上表两个模块、测试与评测资产。
- 未改 H2/H3/H4、`max_repairs`、候选保存授权条件；未改 FEATURE-CONTRACT 公共接口；未改冻结输入。
- 未新增五角星专用验收器、未新增图形专用识别器、未增加专用生成器；分类仍只使用通用轮廓度量。
- 房屋通道与字母 A 通道的既有 `partial + review_required=False` 设计**未改动**；其是否可被未完成语义关系绕过，留 D 走真实入口负向验证、C 单独报门禁缺陷。

## 3. 接口契约要点（详见契约文档与 schema）

入口签名保持不变：

```
verify_semantic_requirements(source, geometries, logical_objects=None, topology=None)
```

### 3.1 身份依据优先级

1. **主要依据**：后端构造结果 `logical_objects[*].geometry_refs` 在本次活动几何中解析到的真实几何集合；
2. **有限辅助证据**：载荷缺失时由后端连通分量分组，`binding_auxiliary=True`，不得作为任意多对象的唯一身份依据；
3. 包围盒仅用于重叠诊断与排序，不是身份判据；
4. 模型自报的 `object_id` / `label` / `assembly_id` 只作声明性记录，`target_ref.model_declared_object_id_trusted_as_identity=False`，不提升为身份。

### 3.2 `logical_objects` 期望形状

| 字段 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `object_id` | string | 建议 | 声明性标识；载荷内非空且不重复；不作身份依据 |
| `assembly_id` / `assembly_label` | string | 可缺省 | 整体归属 |
| `object_type` / `label` | string | 可缺省 | 声明性字段 |
| `geometry_refs` | 正整数数组 | **必需** | 命中本次活动几何 id；非空、对象内不重复；可含多段不连通几何 |
| `bounds` | object | 可缺省 | 仅诊断用 |
| `confirmed` / `confidence` | bool / number | 可缺省 | 后端确认标记与置信度 |

兼容旧字段 `geometry_ids`（作为 `geometry_refs` 别名读取）；新接线统一使用 `geometry_refs`。

### 3.3 `topology` 期望形状

- `shared_geometries`: `[{geometry_id, object_ids:[...]}]`，多对象共用几何必须在此声明且归属一致；
- `relations`: `[{source_object_id, target_object_id, relation}]`，语义层仅信息性消费；
- `schema_version` 可缺省。

### 3.4 校验规则（模块侧强制）

1. `geometry_refs` 必须在本次活动几何（`selected != false` 且角色不属于 `annotation/reference/ignored`）中一一命中；悬空 id 直接拒绝，不做近似模糊匹配。
2. 引用列表非空、元素可解析为正整数、对象内不重复；`object_id` 缺失/空白/重复按缺陷处理。
3. 跨对象共用几何须与 `topology.shared_geometries` 声明一致；未声明或归属不一致即拒绝。
4. 活动几何未被任何对象引用 → 登记 `unowned_geometry_ids`，不静默并入相邻对象。
5. 被角色/选中状态排除的几何进入 `excluded_geometry_ids` / `excluded_geometries`（含角色与选中状态）；引用这类几何判 `excluded_geometry_ref`，与"从未生成"区分。
6. 一个逻辑对象的多段不连通几何保持为一个验收对象，记 `disconnected_members` 警告，不按连通性拆分。
7. 两个逻辑对象接触/重叠/共享结点或边，保持两个独立对象，仅记 `contact_or_overlap_between_distinct_objects` 警告，不合并。

### 3.5 降级规则与终态口径

- 载荷缺失（`null`/`[]`）：回退连通分量辅助证据，`binding_source=connected_components`、`binding_auxiliary=true`，结果不得整体 PASS。
- 载荷畸形 / 引用对不上 / 归属不唯一：`status=unresolved`、`coverage=target_unresolved`、`review_required=True`，携带机器可读错误码与明细。
- 既有终态词汇（主控已正式接受，未改词）：
  - `unverified + coverage=unsupported_semantic_kind`：识别到需求但无法可靠完成；
  - `not_checked`：该对象未执行相应检查；
  - `partial + review_required=True`：部分对象完成、整体未全验；
  - 含未完成强制语义验收的组合对象，不能因其他对象通过而整体 PASS；五角星本轮无完整验收器，登记为能力缺口，不计 PASS。

### 3.6 机器可读错误码 / 警告码

| 错误码 | 触发条件 |
|---|---|
| `invalid_logical_objects_payload` | `logical_objects` 不是列表 |
| `invalid_logical_object_entry` | 数组条目不是字典 |
| `invalid_object_id` | `object_id` 缺失或空白 |
| `duplicate_object_id` | `object_id` 载荷内重复 |
| `missing_geometry_refs` | 引用列表缺失、非列表或为空 |
| `invalid_geometry_refs` | 引用含非正整数 |
| `duplicate_geometry_refs` | 同一对象内引用重复 |
| `dangling_geometry_refs` | 引用本次列表中不存在的几何 id |
| `excluded_geometry_ref` | 引用的几何存在但被角色/选中状态排除 |
| `undeclared_shared_geometry` | 多对象共用几何但拓扑未声明共享 |
| `shared_ownership_mismatch` | 共享拓扑声明归属与引用不一致 |

| 警告码 | 含义 |
|---|---|
| `binding_fallback_components` | 载荷缺失，身份回退连通分量辅助证据 |
| `contact_or_overlap_between_distinct_objects` | 不同绑定对象接触/重叠/共享结点；保持独立未合并，附 `relation` |
| `disconnected_members` | 同一对象含多段不连通几何；保持一个对象，附 `component_count` |

## 4. 模块加固说明

### 4.1 `cad_semantic_dispatch.py`

- 新增 `validate_target_binding(geometries, logical_objects, topology)`：返回 `status / binding_source / auxiliary / targets / errors / warnings / unowned_geometry_ids / shared_geometry_owners / excluded_geometry_ids / excluded_geometries`。
- 新增辅助：`_positive_int_ref`（正整数规范化）、`_declared_shared_map`（拓扑共享声明对账）、`_spatial_contact`（接触/重叠/包围盒重叠诊断，不改变归属）。
- `bind_targets(...)` 保留原签名与返回结构，作为校验器 `targets` 的向后兼容封装，供既有探针与调用方过渡使用。
- refs 主路径：成员几何整体归入一个目标，不做连通性拆分；跨对象接触/重叠只进警告。
- 回退路径：仅在载荷缺失时启用连通分量，目标 `object_id=component:n`、`binding_auxiliary=True`，全部活动几何记入 `unowned_geometry_ids`。

### 4.2 `cad_semantic_acceptance.py`

- 前置护栏：调用方显式传入 `logical_objects` 时，先跑 `validate_target_binding`；`unresolved` 直接返回 `target_unresolved` + `review_required=True`，携带 `binding_validation`（错误、警告、未归属、排除明细），不进入任何图形检查器。
- 爱心通道：改用校验器结果；`unresolved` 携带绑定诊断；正常返回中附带 `binding_source / binding_auxiliary / unowned_geometry_ids / excluded_geometry_ids / excluded_geometries / binding_warnings`。
- 房屋、字母 A、嵌套框、正多边形、astroid、cardioid 等既有通道逻辑与终态口径未改。

## 5. 校验矩阵（输入 → 判定 → 终态，模块级零模型）

| 输入场景 | 绑定判定 | 终态 / review_required | 不整体 PASS | 对应测试 |
|---|---|---|---|---|
| 单对象 refs 命中 | `bound`，refs 来源 | 爱心 `partial / True` | 是 | `test_bound_single_object_uses_backend_resolved_refs` |
| 多对象 refs 分别命中 | `bound`，两组独立 | `partial / True`，无验收器对象 `not_checked` | 是 | `test_bound_two_objects_are_kept_separate` |
| 引用不存在 id 999 | `unresolved`，`dangling_geometry_refs` | `unresolved / True` | 是 | `test_dangling_geometry_ref_rejected_without_fuzzy_match` |
| 对象内重复引用 | `unresolved`，`duplicate_geometry_refs` | `unresolved / True` | 是 | `test_duplicate_refs_within_one_object_rejected` |
| 空引用列表 | `unresolved`，`missing_geometry_refs` | `unresolved / True` | 是 | `test_empty_ref_list_rejected` |
| 引用非正整数 | `unresolved`，`invalid_geometry_refs` | `unresolved / True` | 是 | 校验器分支（`_positive_int_ref` 拒绝） |
| `logical_objects` 非列表 | `unresolved`，`invalid_logical_objects_payload` | `unresolved / True` | 是 | `test_non_list_logical_objects_payload_rejected` |
| 重复 `object_id` | `unresolved`，`duplicate_object_id` | `unresolved / True` | 是 | `test_duplicate_object_id_rejected` |
| 一对象多段不连通 | `bound`，单目标含全部段，`disconnected_members` 警告 | 按一个对象验收 | 是 | `test_one_object_with_multiple_disconnected_geometries_stays_one_target`、`test_disconnected_members_are_warned_but_not_split` |
| 两对象接触/共享顶点 | `bound`，两组独立，接触警告 | 不合并 | 是 | `test_touching_distinct_objects_are_not_merged` |
| 两对象重叠 | `bound`，两组独立，重叠警告 | 不合并 | 是 | `test_overlapping_distinct_objects_are_not_merged` |
| 载荷缺失 | 回退分量，`auxiliary=True`，`binding_fallback_components` 警告 | `partial/unresolved / True` | 是 | `test_missing_logical_objects_falls_back_to_auxiliary_components_only` |
| 活动几何未被引用 | `bound`，登记 `unowned_geometry_ids` | 未归属对象 `unresolved` | 是 | `test_unowned_active_geometry_is_reported_not_silently_bound` |
| 模型自报标签/对象 id | 身份取后端 refs，声明字段仅记录 | 不信任标记为 False | 是 | `test_model_declared_label_does_not_promote_to_identity` |
| 引用被角色排除几何 | `unresolved`，`excluded_geometry_ref`，附排除角色 | `unresolved / True` | 是 | `test_ref_to_role_excluded_geometry_is_rejected_and_diagnosed` |
| 共享几何未声明拓扑 | `unresolved`，`undeclared_shared_geometry` | `unresolved / True` | 是 | `test_shared_geometry_without_topology_declaration_rejected` |
| 共享几何声明一致 | `bound`，双归属记入 `shared_geometry_owners` | 分别登记 | 是 | `test_shared_geometry_matching_topology_declaration_is_bound` |

## 6. 测试证据

### 6.1 计数前后对比（`backend/tests/test_cad_semantic_acceptance.py`）

| 阶段 | 收集数 | 通过 | 失败 | 说明 |
|---|---:|---:|---:|---|
| 基线 `e7831921` | 21 | 19 | 2 | 2 项为既有失败，本轮未改动其对应逻辑 |
| 本轮提交后 | 38 | 36 | 2 | 新增 17 项全部通过；失败项与基线完全相同 |

既有失败（非本轮引入，留 D 复核）：

- `test_structural_counter_schema_preserves_multiple_paths_without_coordinates`：断言平滑爱心 `steps.maxItems==1`，实际为 100；属解释器 schema 既有行为，本轮未触碰。
- `test_unsupported_styles_and_multiple_objects_are_not_falsely_fully_verified`：`semantic_requirements('生成一个爱心和一个大写字母A')` 仍命中爱心通道；属既有需求分派口径，本轮未改 `semantic_requirements`。

### 6.2 相邻模块回归

- `test_logical_topology.py`、`test_drawing_selection.py`、`test_cad_source_acceptance.py`：82 passed。
- 此前一轮相邻集合（拓扑、归属、来源验收、信任边界、目标解析、对象约束、路径关系）：148 passed。
- 本轮未重跑 A9、未启动 S1、未调用真实模型。

### 6.3 复现命令

```
PYTHONPATH=<worktree>\backend
python -m pytest backend/tests/test_cad_semantic_acceptance.py -q
```

## 7. `logical_objects` 可信来源与验证规则

- 来源：后端构造出口生成 `geometries / logical_objects / topology`，并经 `validate_logical_object_graph` 校验（悬空、对象内重复、未声明共享、归属对账等）。
- 语义层二次校验：只认 `geometry_refs` 在本次活动几何中的解析结果；模型自报 `object_id/label` 不作为身份；引用对不上、归属冲突、成员不完整一律 `unresolved`。
- 未归属活动几何、被排除几何、共享归属、不连通成员、接触/重叠均进入诊断字段，供证据账本审计。

## 8. 生产调用位置现状（只读记录，接线属 C 范围）

据 B 线只读走读，`verify_semantic_requirements` 当前生产调用点均为两参形态，尚未转发 `logical_objects/topology`：

| # | 文件 | 场景 | 当前实参 |
|---|---|---|---|
| 1 | `cad_construction_interpreter.py` | 正常执行 | `(original_requirement, result['geometries'])` |
| 2 | 同上 | 诊断回放（断言失败隔离） | `(original_requirement, diagnostic_trial['geometries'])` |
| 3 | 同上 | 修复重试回放（astroid 断言替换） | `(original_requirement, trial['geometries'])` |
| 4 | 同上 | 修复重试回放（radial/bounds 断言替换） | `(original_requirement, trial['geometries'])` |

具体行号、参数传递证据与接线后行为核对属 C 本轮交付；A 侧未改这些文件。

## 9. 能力缺口与 `unverified` 清单

1. **五角星无完整语义验收器**：C10 类组合中五角星记 `not_checked` / 能力缺口，不计 PASS；本轮未新增专用验收器。
2. **房屋 / 字母 A 通道 `review_required=False`**：既有 423E 设计，本轮未改；是否存在"必要语义关系未完整验收却凭 `review_required=False` 正式接受"的绕过，由 D 走真实生产入口零费用 Mock 补负向测试；若证实可绕过，由 C 单独报生产级门禁缺陷。
3. **回退连通分量路径的接触/重叠合并风险**：载荷缺失时，接触（≤0.5mm）或重叠的不同对象会被并入同一分量；该路径已标 `binding_auxiliary=True`，不得作为任意多对象唯一身份依据；refs 主路径不受此合并语义影响。
4. **未归属几何的对象级条目**：refs 路径下未归属活动几何列入 `unowned_geometry_ids`，但爱心通道 `object_acceptance` 仅遍历已绑定目标；下游若只读 `object_acceptance/status` 可能漏看，属观察缺口，未擅自扩大修复。
5. **混合曲线轮廓（line + arc/spline）**：轮廓点提取仅识别 line/polyline，白名单外类型在入口闸门判 `unverified`；混合曲线轮廓统一登记为能力缺口，不降级为部分通过。
6. **184 项组合回归适用性核对**：属 D 回归范围，A 本轮未执行全量组合套件。
7. **真实生产入口接线后的端到端行为**：调用方转发 `logical_objects/topology` 后的实际结果，属 C/D 范围。

## 10. 纪律自查

- 真实模型请求：0；网络请求：0；费用：0。
- 未重跑 A9；未启动 S1；未改冻结输入；未改 FEATURE-CONTRACT 公共接口；未改 `max_repairs`。
- 未新增专用生成器；未扩大到 M3 几何快照；未开展无关功能开发。
- 未合并、未推送、未 amend、未 rebase；`e7831921` 提交对象保持原样。
- 本工作树内 B 线只读产物未纳入本提交。

## 11. 提交级核对命令（供 D 复核）

```
git rev-parse e7831921ef904deaa893573da8cc793056a9cf41^
# 期望: 7567f7bb32d9571048f1d66deb8124df3bcf9d02
git show --stat <本提交 SHA>
git diff --stat e7831921ef904deaa893573da8cc793056a9cf41 <本提交 SHA>
```
