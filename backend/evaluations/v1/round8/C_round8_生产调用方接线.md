# Round8 Agent C：生产调用方接线报告（P0 语义分派补丁接线）

- 分支：`v1/c-p0-caller-wiring`
- Worktree：`worktrees/C-wire`
- 基线：`7567f7bb32d9571048f1d66deb8124df3bcf9d02`
- 语义补丁（A，父节点即基线）：`e7831921ef904deaa893573da8cc793056a9cf41`
- **本轮接线提交（独立提交，父节点 `e7831921`）：`3379124aacae5cf755873acaf4cfd7c60b27a34d`**
- 证据快照提交（JSON 探针输出，父节点 `3379124`）：`bc0950b9880f70182c6cfe7c58e04ac025c90579`
- 报告提交：`32eced144b6d57c6f551ba86a8aae47c3735df3c`；其后为两份报告措辞/链记录收尾提交（`22a3ea5ae52593f4c53c737db3a8df9ce6fb06a2`、`d7d293a4214b70594ae34e3871fa68c3310bf312`），不含生产代码变更。
- 提交关系：报告收尾提交 → `32eced1` → `bc0950b` → `3379124` → 父 `e7831921` → 父 `7567f7b`；未 amend、未 rebase、未 push、未合并 main。当前分支 HEAD 以 `git rev-parse HEAD` 为准。
- 零真实模型调用；夹具全部为脚本内合成的**重建夹具（非历史回放）**。

## 1. 修改文件与关键 Diff

| 文件 | 性质 | 说明 |
|---|---|---|
| `backend/app/cad_construction_interpreter.py` | 调用方（C 独占） | 新增绑定解析与包装器；4 处生产调用点接线 |
| `backend/tests/test_c_round8_caller_wiring.py` | 新增回归测试 | 15 项零模型用例（正向/负向/门禁审计） |
| `backend/evaluations/v1/round8/c_round8_wire_probe.py` | 新增离线探针 | 生成机器可读证据 JSON |
| `backend/evaluations/v1/round8/c_round8_wire_results.json` | 证据快照 | 探针输出（含 git 元数据、用例裁决、门禁审计） |

提交 diff 统计（`git show --stat 3379124`）：

```
3379124 round8(C): P0 production caller wiring for backend-resolved semantic object binding
 backend/app/cad_construction_interpreter.py        | 153 +++++++++-
 .../evaluations/v1/round8/c_round8_wire_probe.py   | 326 +++++++++++++++++++++
 backend/tests/test_c_round8_caller_wiring.py       | 268 +++++++++++++++++
 3 files changed, 739 insertions(+), 8 deletions(-)
```

**未触碰的 A 模块**（`git diff --name-only e7831921 HEAD` 确认不在变更集内）：
`backend/app/cad_semantic_acceptance.py`、`backend/app/cad_semantic_dispatch.py`。

### 1.1 新增调用方侧机制（`cad_construction_interpreter.py`）

- `_semantic_backend_binding(result)`：从后端执行结果解析可信逻辑对象绑定。
  - 可信来源限定为 `execute_construction_plan` 产出的 `logical_objects` / `topology`；
  - 先经 `validate_logical_object_graph` 做后端图校验（悬空引用、重复归属、共享边声明、引用类型）；
  - 再做成员完整性核对：活动几何必须全部归属到某个逻辑对象；
  - 模型自报的 `object_id`/标签**不作为身份依据**，身份锚点是后端解析出的 `geometry_refs`；
  - 校验不通过 → `trust=degraded`，不向上传递不可信映射。
- `_verify_semantic_requirements_bound(original_requirement, result)`：
  - 可信绑定：以 `logical_objects` + `topology` 调用语义验收；
  - 降级绑定：退回两参形式（连通分量仅作 A 模块内部有限辅助），结果显式标注 `binding_trust=degraded`、`review_required=True`；若两参回退给出 `passed`，调用方侧降级为 `unverified`，不得整体 PASS；降级路径下 `StructureContractError` 同样转记为 `unverified` 调用方裁决，不产生干净通过。

## 2. 全部 `verify_semantic_requirements` 生产调用位置清单

全仓 `grep verify_semantic_requirements`（`backend/app`）：除 A 模块定义与本包装器外，生产调用点共 **4 处**，全部位于 `interpret_construction_request`。

| # | 文件 | 函数 | 行号 | 路径类别 | 接线前实参 | 接线后实参 | 可信绑定来源（行号） | 能否拿到可信映射 |
|---|---|---|---|---|---|---|---|---|
| 1 | `cad_construction_interpreter.py` | `interpret_construction_request` | 973 | 正常构造（执行后验收） | `verify_semantic_requirements(original_requirement, result['geometries'])` | `_verify_semantic_requirements_bound(original_requirement, result)` | `result = execute_construction_plan(plan)`（:911），含 `logical_objects`、`topology` | 是 |
| 2 | 同上 | 同上 | 1022 | 诊断回放（`assertion_failed` 去断言诊断试算） | `verify_semantic_requirements(original_requirement, diagnostic_trial['geometries'])`；返回值丢弃，仅捕 `StructureContractError` | `_verify_semantic_requirements_bound(original_requirement, diagnostic_trial)`；成功分支记录 `status/review_required/reason/coverage/binding`，异常分支补记 `status=failed/review_required=True` | `diagnostic_trial=execute_construction_plan(diagnostic_plan)`（:1020） | 是 |
| 3 | 同上 | 同上 | 1079 | 修复试算（astroid 平滑性断言移除） | `verify_semantic_requirements(original_requirement, trial['geometries'])` | `_verify_semantic_requirements_bound(original_requirement, trial)` | `trial=execute_construction_plan(corrected)`（:1078） | 是 |
| 4 | 同上 | 同上 | 1112 | 修复试算（regular polygon 边界断言移除） | `verify_semantic_requirements(original_requirement, trial['geometries'])` | `_verify_semantic_requirements_bound(original_requirement, trial)` | `trial=execute_construction_plan(corrected)`（:1107） | 是 |

其它相关位置（**不**直接调用语义验收，已逐一核对）：

- :1179 `execute_construction_plan(trial_plan)`：可行性试算，不做语义验收；
- :2630 `_trial_plan_without_assertions`：去断言可行性探测，不做语义验收；
- `agent_service` 正常构造（:6243）、修复试算循环（:6595）、`cad_construction_evaluation`（:47）均汇入解释器，语义验收只在上述 4 处发生；
- 跟进刷新路径（`agent_service` :6468）无回调、仅规则层，不触发语义验收。

四类路径覆盖：正常构造（#1）、诊断回放（#2）、修复试算（#3、#4）、其它（无独立语义验收调用）。

## 3. `logical_objects` 可信来源与验证规则

**来源**：仅接受 `execute_construction_plan` 后端构造/执行结果中的 `logical_objects` 与 `topology`。执行器在产出前已按步骤语义生成对象、解析 `geometry_refs` 为当前几何 id，并经 `validate_logical_object_graph` 校验。

**调用方侧校验矩阵**（探针 `negative_binding_matrix`，证据见 JSON）：

| 校验项 | 规则 | 不通过裁决 |
|---|---|---|
| 来源可信 | 对象清单必须来自后端执行结果；模型自报字段不作为身份 | 缺清单 → `degraded / logical_objects_missing` |
| 成员完整 | 活动几何（`active_geometries`）必须全部被对象引用覆盖 | 存在未归属活动几何 → `degraded / incomplete_membership` |
| 引用一致 | `geometry_refs` 与本次真实几何 id 一一对应 | 悬空/错误 id → `degraded / dangling_geometry_refs` |
| 无重复 | 对象内/跨对象引用重复按图校验拒绝 | 重复引用 → `degraded / invalid_geometry_refs` |
| 无缺失 | 对象必须带有效 `geometry_refs` | 仅模型自报 id、无 refs → `degraded / missing_geometry_refs` |
| 无过期绑定 | 引用不得指向已移除几何 | 过期引用 → `degraded / dangling_geometry_refs` |
| 身份锚点 | 身份以后端解析的几何引用为准；`object_id` 标签不提升为身份 | `model_declared_object_id_trusted=false` 写入 `binding` |

**归属规则落实**：

- 优先使用可信对象映射；连通分量只在 A 模块内部作有限回退，不作为任意多对象的唯一身份依据；
- 两对象接触/共享边/重叠：映射保持各自独立目标，不合并（见 §5 重叠用例）；
- 一个逻辑对象含多段不连通几何：保持单一目标、多 refs，不拆分（见 §5 多段用例）；
- 绑定不确定 → `unverified` / `review_required=True`，不得整体 PASS。

## 4. 正向用例证据（真实执行器结果 + 生产包装器）

| 用例 | 语义状态 | review_required | 覆盖 | 对象级裁决 | 绑定 |
|---|---|---|---|---|---|
| A1 单爱心 | `partial` | True | `heart_outline_measured_features` | 几何 [1] `passed`（`heart_features_measured`） | trusted |
| A9 重建夹具（非历史回放） | `partial` | True | `heart_outline_measured_features` | 几何 [1] `passed` | trusted |
| C10 爱心 + 五角星 | `partial` | True | `heart_outline_measured_features`，`partial_with_unverified_objects` | [1] `passed`（爱心）；[2] `not_checked`（`no_verifier_for_star_profile`，profile=star） | trusted |
| C26 大写 A | `partial` | False（继承 423E） | `straight_capital_a_structural_relations_only` | 字母 A 通道既有结构关系检查 | trusted |
| 未知 kind（“画一个花瓶”） | `not_checked` | True | `partial`，`no_semantic_requirement_matched` | 无通过对象；未计入字母 A | trusted |

### 4.1 C10 生产入口对象级验收证据

- 执行器产出 2 个逻辑对象：`heart → [1]`、`star → [2]`；
- 对象级验收：[1] 爱心 `passed`；[2] 五角星 `not_checked`，`unsupported_objects=[[2]]`；
- 整体 `partial + review_required=True`；五角星本轮无完整语义验收器，按能力缺口登记，不计 PASS。

## 5. 负向与归属测试结果

| 用例 | 绑定信任 | 结果/目标分组 | 结论 |
|---|---|---|---|
| 缺失 `logical_objects` | degraded | `logical_objects_missing`；验收 `unverified / review_required=True`，不可 PASS | 不确定不转正 |
| `geometry_refs` 错误 id（999） | degraded | `dangling_geometry_refs` | 错误引用被拦截 |
| 重复引用 `[1,1]` | degraded | `invalid_geometry_refs` | 重复绑定被拦截 |
| 过期引用（几何 2 已移除） | degraded | `dangling_geometry_refs` | 过期绑定被拦截 |
| 仅模型自报 id、无 refs | degraded | `missing_geometry_refs` | 模型自报身份未被采信 |
| 存在未归属活动几何 [2] | degraded | `incomplete_membership` | 清单不完整即降级 |
| 两对象重叠（bbox 相交） | trusted | 目标分组 `[1]`、`[2]` 各自独立 | 重叠不并对象 |
| 一对象两段不连通几何 | trusted | 单一目标 `[1,3]` | 不连通段不拆对象 |

## 6. `partial` 状态汇总与候选门禁审计

### 6.1 真实生产入口（解释器 + 汇总 + 候选谓词）

- **C10**：语义 `partial / review_required=True` → 汇总 `review_required=True`；`candidate_is_accepted=False`。对象级 partial 不会被提升为完整验收通过。
- **大写 A（C26）**：解释器真实入口 `status=ready`，语义报告 `partial / review_required=False`（继承 423E）；`source_acceptance.coverage=partial`，汇总 `review_required=True`、`requirement_coverage=unknown`；`candidate_is_accepted=False`。
- **房屋**：解释器真实入口 `status=ready`，语义报告 `partial / review_required=False`（继承 423E）；汇总 `review_required=True`；`candidate_is_accepted=False`。

### 6.2 “草稿可保存”与“已完整验收”区分

- 既有草稿保存授权条件未改；可保存待复核草稿的行为保留。
- 审计结论：当前真实生产者链路下，房屋/字母 A 的 `partial` 结果不会被标记为“已完整验收”的正式候选；未观测到草稿被提升为正式通过。
- 备注：在当前生产者状态下，房屋/字母 A 结果同时不满足 `candidate_is_reviewable_draft`（语义报告自身 `review_required=False`），这是 423E 既有表现，本轮未扩改。

### 6.3 生产门禁缺陷报告（条件性残留，未擅自修复）

**缺陷类别**：汇总门禁对 `partial` 状态的复核过滤存在条件性缺口。

- **位置**：`construction_acceptance_summary`（`cad_construction_interpreter.py`）`report_requires_review` 只把 `review_required is True` 或状态 `failed/unverified/review_required` 计入复核；`partial` 不在复核状态集合内。
- **触发条件**：若某 `source_acceptance` 生产者输出 `coverage=complete` 且 `unknown_requirements=[]`，同时语义报告为 `partial + review_required=False`（房屋/字母 A 通道的继承形态），汇总会得到 `status=passed / review_required=False`，`candidate_is_accepted=True`。
- **实测残留条件**（探针 `gate_audit.residual_condition_complete_coverage`）：汇总 `passed`、`review_required=False`、`candidate_accepted=True`、`candidate_reviewable_draft=False`。
- **当前可达性**：现有 `verify_final_source_contract` / `verify_scoped_primitives` 只产出 `partial`/`not_checked` 覆盖；`coverage=complete` 仅在 Bezier 匹配分支出现，与房屋/字母 A 通道不共存。**故当前生产路径不可达**，属潜在条件性缺陷。
- **可观测后果**：未来若新增生产者在语义未全验时给出 `complete` 覆盖证据，未完成的强制语义验收可能被正式接受为候选。
- **处置**：按裁决要求单独上报，本轮不扩大补丁、不修改汇总门禁与候选保存授权。

## 7. 回归与适用性核对

环境：Python `xikao` 环境；`PYTHONPATH=backend`；`XLINE_AGENT_PROVIDER=local`；无 `DEEPSEEK_API_KEY`；零真实模型。

| 套件 | 基线（`e7831921`） | 本轮（`3379124`） | 结论 |
|---|---|---|---|
| 12 模块组合回归（d1_combo4 同清单） | 184 passed / 0 failed | 184 passed / 0 failed | 无回归 |
| 新增 C 接线测试 `test_c_round8_caller_wiring.py` | — | 15 passed / 0 failed | 新增覆盖 |
| 12 模块 + 新增 C 模块合计 | 184 passed | 199 passed / 0 failed | 184 + 15 |
| `test_cad_semantic_acceptance.py`（A 模块） | 19 passed / 2 failed | 19 passed / 2 failed（同名两项） | 失败为 A 模块既有，未因接线变化 |
| 相关套件（拓扑/恢复/提交/候选/对象约束/关系验收/构造评估等 13 文件） | 未在基线单独计数 | 170 passed / 2 failed（即上述 A 模块既有两项） | 无新增失败 |
| 相邻验收套件（编辑关系/路径关系/笔画/投影/重复/边界/P0 信任边界） | — | 75 passed / 0 failed | 无回归 |

A 模块既有失败（基线与本轮一致，属 A 侧待办，C 未改动其文件）：

- `test_structural_counter_schema_preserves_multiple_paths_without_coordinates`
- `test_unsupported_styles_and_multiple_objects_are_not_falsely_fully_verified`

**收集期环境缺口（与本轮改动无关，基线即存在）**：`test_cad_history_replay.py`、`test_cad_acceptance_metrics.py` 依赖未纳入版本管理的 `tests.manual` 包，本地收集即报 `ModuleNotFoundError / FileNotFoundError`；`git ls-files backend/tests/manual` 为空。

### 7.1 验收覆盖是否缩小

未缩小。语义验收仍保留原有全部通道；接线只是把后端已验证的对象映射与拓扑传入验收，两参兼容形式仅在绑定降级时作为回退。未删除任何检查器、未下调任何断言。

## 8. `unverified` / `not_checked` 清单

| 项 | 状态 | 原因/覆盖 | 处置口径 |
|---|---|---|---|
| C10 五角星（几何 [2]） | `not_checked` | `no_verifier_for_star_profile`，本轮无五角星专用验收器 | 登记能力缺口，不计 PASS；未新增专用生成器/验收器 |
| 未知 kind（花瓶等无匹配需求） | `not_checked` | `no_semantic_requirement_matched`，`review_required=True` | 不静默成功，未并入字母 A |
| 缺失 `logical_objects` | `unverified`（调用方降级） | `logical_objects_missing` | 不得整体 PASS |
| 错误/重复/过期/无 refs/未归属绑定 | `unverified`（调用方降级） | 图校验或成员完整性失败 | 不得整体 PASS |
| 房屋、大写 A | `partial`（继承 423E，语义报告 `review_required=False`） | 仅结构关系子集覆盖 | 汇总层 `review_required=True`；条件性门禁缺陷见 §6.3 |

## 9. 禁区与执行限制核对

| 限制项 | 核对结果 |
|---|---|
| 不改 A 语义模块（`cad_semantic_acceptance.py` / `cad_semantic_dispatch.py`） | 未改（diff 名称清单不含） |
| 不改 H2/H3/H4 门 | 未改（diff 无对应代码） |
| 不改 `max_repairs` | 未改（diff 无匹配） |
| 不改候选保存授权条件 | 未改（仅读取候选谓词做审计） |
| 不改 FEATURE-CONTRACT 公共接口 | 未改 |
| 不新增图形专用生成器/五角星专用验收器 | 未新增 |
| 不扩到 M3 几何快照 | 未涉及 |
| 零真实模型请求 | 全程本地执行器/夹具，探针标记 `zero_model=true` |
| 不重跑 A9、不启动 S1、不改冻结输入 | 未执行 |
| 不合并 / 不推送 / 不 amend / 不 rebase | 提交在独立 worktree 分支，未 push、未 merge main |
| 不采用来源未知的 164A | 未引用 |

## 10. 是否具备正式集成条件

**尚不具备最终集成分支合并条件**（与主控裁决一致：仅批准独立评审工作树上的最小生产接线，不批准合并）。

- 接线本身在独立提交 `3379124` 上通过既有组合回归与新增负向用例；
- 待主控验收项：A 兄弟载荷校验提交落地后的接口兼容性复核；§6.3 条件性门禁缺陷的裁决；A 模块两项既有失败的归属处理；`tests.manual` 收集缺口补齐后重跑历史回放/指标套件。

## 11. 复现命令与证据位置

```
# 工作树
git -C <repo> worktree list
# 补丁祖先核对
git show --stat e7831921ef904deaa893573da8cc793056a9cf41
git log --pretty="%H %P" -1 e7831921ef904deaa893573da8cc793056a9cf41
# 接线提交
git show --stat 3379124aacae5cf755873acaf4cfd7c60b27a34d
# 探针（backend/ 目录下）
python evaluations/v1/round8/c_round8_wire_probe.py --out evaluations/v1/round8/c_round8_wire_results.json
# 回归（12 模块 + 新增 C 模块）
python -m pytest tests/test_cad_requirement_contract.py tests/test_cad_plan_component_repair.py tests/test_cad_final_source_contract.py tests/test_cad_construction_interpreter.py tests/test_candidate_visibility_gate.py tests/test_cad_construction.py tests/test_cad_topology_safety_b1.py tests/test_cad_topology_safety_b11.py tests/test_cad_topology_safety_b12.py tests/test_c1_integration_mock.py tests/test_c11_service_two_round_mock.py tests/test_c12_production_loop_mock.py tests/test_c_round8_caller_wiring.py -q
```

证据快照：`backend/evaluations/v1/round8/c_round8_wire_results.json`（git 元数据、调用点清单、用例裁决、负向矩阵、门禁审计）。

## 12. 遗留事项

- 既定的《后端最终同步清单.md》在本机环境未找到对应文件，本轮无法写入同步范围；待路径可用后补登本次接线范围。
- §6.3 门禁缺陷按要求仅上报，未修复。
