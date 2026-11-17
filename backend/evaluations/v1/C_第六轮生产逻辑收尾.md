# C 线第六轮准入 · M2/M3 生产逻辑收尾（词汇对齐 + 目标范围判定 + 保留断言）

- 分支：`v1/c1-integration`；基线 HEAD：`c3bc8bf`（第五轮词汇补丁）；父提交链：`8e3efad` → `23e0653` → `c3bc8bf` → 本轮。
- 本轮只改 `cad_generation_recovery.py` 与 C 自有测试；未动 `agent_service.py`、A/B 文件、公共 Schema、解释器、部件合并器、路由器。
- 纪律：零模型调用、零联网；`max_repairs=2` 不变；未放宽几何等价标准；无 `lower_tip`/爱心/心形/A9 字符串分支；不 amend、不 push、不合并。
- 状态：**[已查证]** 代码/测试可复现；**[待验证]** 真实 B 判据端到端仍由 D 在组合树联调。

## 1. 生产调用链复核（`bounded_repair_available` 真实链路）

### 1.1 调用点（全仓仅一处生产调用）

| 环节 | 文件:行号 | 谁调用谁 | 短路/条件 |
|---|---|---|---|
| 循环入口 | `agent_service.py:6477` | `construction_attempts = [deepcopy(interpretation)]` | 初始 interpretation 入账，attempts 长度 1 |
| 循环谓词 | `agent_service.py:6478-6479` | `while should_repair(interpretation) and bounded_repair_available(construction_attempts, max_repairs=2)` | 先 `should_repair`，再 `bounded_repair_available`；`and` 短路 |
| 可修复判定 | `cad_generation_recovery.py:36-38` | `should_repair(result)` | 要求 `status=invalid` + `provider_attempted` + 类别 ∈ {`model_plan_invalid`, `constraint_conflict`, `sampling_budget`}；其余类别（需求缺参/需求未核验/网络/持久化）直接 False，循环体不进入，M3 闸门不可达 |
| 有界与进展守卫 | `cad_generation_recovery.py:41-67` | `bounded_repair_available(attempts, max_repairs=2)` | ① `repairs=len-1 >= 2` → False（轮次耗尽）；② `len<2` → True（首轮放行）；③ 当前码 ∈ {`low_confidence`, `confidence_only_repair`} → False；④ 签名 `(category, code, message, details JSON)` 不同且计划字典不同 → True，否则 False |
| M3 闸门 | `agent_service.py:6483-6493` | 循环体内 `evaluate_repair_progress(attempts[-2], attempts[-1])` | 仅当 `M3_PROGRESS_GATE_ENABLED` 且 `len(attempts)>=2` 进入；`block` 则转 `invalid/no_progress` 并 `break` |

### 1.2 顺序结论（[已查证]）

- 真实生产路径：初始 interpretation → 入账 attempts(1) → while 谓词先 `should_repair` 后 `bounded_repair_available` → 两个谓词都通过才进循环体 → 循环体顶部 M3 闸门比较 attempts[-2]/[-1]。
- **M3 闸门是循环体内的附加守卫，不替代 `bounded_repair_available`**；两者顺序为：谓词守卫在前，M3 双条件闸门在后。D 上一轮“闸门挂在循环顶部、`bounded_repair_available` 之前”的说法需细化：M3 在 body 顶部、`bounded_repair_available` 当次求值之后；但二者都在发出下一次模型请求之前。
- 进入 M3 闸门的最小前置条件：`len(construction_attempts) >= 2` 且开关开启；首轮修复（attempts 长度 1）在 :51-52 被 `bounded_repair_available` 早返 True，闸门 :6483 的 `len>=2` 不满足，**首轮必然放行**，不存在首轮被 M3 阻断的路径。

### 1.3 可能让闸门被跳过的早退分支（逐条核对）

| 早退 | 位置 | 是否跳过 M3 | 说明 |
|---|---|---|---|
| 不可修复类别 | `should_repair` :36-38 | 是（循环体不进入） | 需求缺参/网络/持久化等本就不该再发修复，属预期退出 |
| 轮次耗尽 | `bounded_repair_available` :48-50 | 是 | `repairs>=2` 不再发请求，`max_repairs=2` 未改 |
| 仅置信度 | :58-59 | 是 | 旧置信度守卫，未改 |
| M3 开关关闭 | `agent_service.py:6483` | 是 | 回滚路径，env `CAD_C1_M3_PROGRESS_GATE=off` |
| 循环前单次重试 | `agent_service.py:6474` | 是（设计内） | while 之外的单次 bounded retry，不经过修复闸门 |
| 评估器异常 | 适配层 :246-250 | 不跳过循环，但降级 undetermined 放行 | 异常被捕获，fail-closed，不阻断 |
| 局部修复越界/仅置信度改写 | `agent_service.py:6547-6559` | 当次尝试入账，下一轮 while 重新求值 | 不绕过闸门 |

未发现配置开关或异常分支能在应进入闸门时静默跳过它；唯一“不进闸门”的早退都是谓词层的合法退出或回滚开关。

## 2. 词汇映射表（生产代码写死，harness 不做转换）

落点：`cad_generation_recovery.py`

| 常量 | 行号 | 取值 |
|---|---|---|
| `EQUIVALENT_RELATIONS` | :138 | `{'identical', 'equivalent'}` —— 满足双条件才可能拦截 |
| `_CHANGED_RELEASE_RELATIONS` | :141-143 | `{'same_trajectory_reversed', 'compliant_other', 'different'}` —— 确定非等价，`equivalent=False`，放行 |
| `_SIMILAR_UNDETERMINED_RELATIONS` | :147 | `{'similar_transform', 'similar'}` —— 显式映射 undetermined 放行 |

判定分支（`evaluate_geometry_progress` :203-289）：

| B/生产 relation | 映射结论 | 处置 | 行号 |
|---|---|---|---|
| `identical` / `equivalent` | `equivalent=True` | 特征也无改善时 `block / stalled_equivalent` | :261-263 |
| `similar_transform` / `similar` | `undetermined=True`, `equivalent=None` | **显式分支**放行，记 `similar transform is not equivalence; released as undetermined` | :264-269 |
| `same_trajectory_reversed` | `equivalent=False`, `reversed=True` | 放行（方向维不构成改善） | :270-272 |
| `compliant_other` / `different` | `equivalent=False` | 放行 `geometry_changed` | :270-272 |
| 契约外未知字符串 | `undetermined=True`, `equivalent=None` | 单独路径放行，记 `unknown geometry relation: <值>` | :276-281 |
| 缺几何快照 | `undetermined=True` | 放行 | :218-223 |
| 目标作用域不可解析 | `undetermined=True`, `relation=scope_unresolved` | 放行，不回退整体比较 | :227-232 |

- 适配层 `set_geometry_evaluator` :153-158 原样接收 B 的 `relation` 字符串；除上述集合映射外，代码中没有其它词汇改写。
- 相似通道决策（写明理由）：C 不单独调用 B 的 `similarity_transform`。刚性/尺度/反射或拓扑保持调整会使采样点越出原始等价容差，B 据此标注 `similar_transform` 而非等价关系；相似不等于等价，目标几何可能真的变了，因此映射 undetermined 放行，**不会误拦**，也**不能**当作等价停滞拦截。

## 3. 目标部件范围判定（误判边界）

### 3.1 问题

旧实现按整体几何比较：失败目标部件无进展、无关部件被小幅移动时，整体几何变化会触发 `geometry_changed` 放行，漏掉目标停滞。

### 3.2 改法（[已查证]）

- 目标引用提取：`_target_refs` :159-162（取 details.`affected_output_refs`）。
- 范围几何提取：`_scoped_geometries` :165-193。ref → geometry id 经 `trial_result.symbol_table` 绑定；只把目标 ref 绑定到的几何交给判据。
  - refs 为空：无可声明目标，回退整体快照比较（`scope_resolvable=True`）。
  - refs 已声明但缺 `symbol_table` 或映射不到几何：`scope_resolvable=False`，**不回退整体比较**，放行并记 `scope_unresolved`。
- spec 字段：`_geometry_spec` :196-200（`geometries` 目标子集、`scope_refs`、`scope_resolvable`、`plan`）。

### 3.3 用例结果

- `test_m3_target_stall_unrelated_part_moved_blocks` :416-445：目标 `g1` 前后一致，无关 `g2` 被小幅移动；录制替身确认两侧 spec 仅含 `g1`、`scope_refs=[REF]`；特征向量不变 → **`block / stalled_equivalent`**。
- `test_m3_unresolved_target_scope_releases` :447-459：声明了目标 ref 但缺绑定表 → **allow / undetermined / `scope_unresolved`**。

## 4. 六类词汇 + 快照用例（真实词汇，harness 无手工映射）

套件 `tests/test_c13_m2m3_loop_mock.py`，命令 `pytest tests/test_c13_m2m3_loop_mock.py -q` → **30 passed in 1.17s**。

| 词汇/情形 | 用例 | 结论 |
|---|---|---|
| `identical` + 双条件 | `test_m3_equivalence_vocabulary_blocks_stall`（参数化 identical/equivalent） | block |
| `equivalent` + 双条件 | 同上 | block |
| `similar`（`similar_transform`/`similar`） | `test_m3_similar_relation_maps_to_undetermined_release` :369-384 | allow / undetermined |
| `unknown` | `test_m3_unknown_relation_fails_safe_release` :321-330 | allow，记 unknown relation |
| `different` | `test_m3_changed_relations_release` :352-367 | allow / geometry_changed |
| 缺快照 | `test_m3_loop_releases_when_geometry_snapshot_is_missing` :495-513 | allow / undetermined，第 3 次请求发出 |
| `same_trajectory_reversed` | `test_m3_changed_relations_release` | allow，`reversed=True`，不计进展 |
| `compliant_other` | 同上 | allow / geometry_changed |

补充白名单：特征改善、新失败、判据 undetermined、首轮放行、回滚关闭均有用例覆盖（:284-318、:342-350、:386-394、:533-544）。

## 5. M2 完整性：四项保留断言 + 结构通道字段对照

### 5.1 四项逐项断言

用例 `test_m2_replan_preserves_source_dimensions_part_and_closure` :235-281。结构重规划通道（`structural_replan=true`）不传 `repair_context`/`component_repair_context`（`agent_service.py:6538-6541`），整计划重编译；保留项断言：

| 保留项 | 断言证据 |
|---|---|
| 来源引用 | 目标步 `source_requirement_refs==["R1"]`；非目标步 `source_requirement_refs==["R2"]` |
| 用户尺寸 | `outline.assertions == replan.assertions`；非目标步 `start/end` 坐标前后一致 |
| 非目标部件 | `after_steps["keep"] == before_steps["keep"]`（身份、坐标、语义整体保留）；部件集合仍为 `{REF, "keep"}` |
| 依赖闭包 | 目标步与非目标步 `junction_constraints`（含其 `source_requirement_refs`）前后一致 |

### 5.2 结构通道前后字段对照（生产调用链）

| 字段 | 首轮失败计划 | 重规划返回计划 | 通道证据 |
|---|---|---|---|
| 受影响部件 | 仅 `REF` 进 `affected_output_refs` | `REF` 表达式重建 | 无 `component_repair_context`、无 `repair_context`（:6538-6541） |
| 来源引用 | 两步 `source_requirement_refs` | 两步原样保留 | 用例 :264-266 |
| 尺寸断言 | `bounds_size` width/height | 断言集合不变 | 用例 :268 |
| 非目标部件 | `keep` 步 | 深比较相等 | 用例 :263、:267 |
| 连接/依赖闭包 | `junction_constraints` | 原样保留 | 用例 :270-271 |
| 验收条件 | 后端独立验收 | 未降低 | 重规划提示语 :6533 要求保留原始尺寸、数量、连接要求，独立验收不变 |

分类器 `preserve` 清单（`classify_feature_failure` 返回 :461-462）：用户尺寸、来源需求引用、部件数量、非目标部件。

## 6. 回归原始计数

| 套件 | 结果 |
|---|---|
| `test_cad_generation_recovery.py` | **14 passed** |
| `test_cad_construction.py`（执行器） | **37 passed** |
| `test_cad_construction_interpreter.py`（解释器） | **74 passed** |
| 三套件合计 | **125 passed** in 25.60s |
| `test_c13_m2m3_loop_mock.py`（本轮 C1.3） | **30 passed** in 1.17s |
| 恢复 + C1/C1.1/C1.2 Mock | **16 passed, 5 failed**（5 个既有 `dep_pending`，依赖 A1.1 `ea8323a`，非本轮引入） |

- grep 证据：`cad_generation_recovery.py`、`agent_service.py`、`test_c13_m2m3_loop_mock.py` 中 `lower_tip/爱心/心形/A9/case_id` **0 匹配**。
- 本补丁 app 改动仅 `cad_generation_recovery.py`（+77/-21）；`agent_service.py` 相对第五轮 commit 无改动。

## 7. 尚未做到 / 待验证

1. **[待验证]** 真实 B 判据端到端：目标范围几何等价、`similar`/`compliant_other`/`reversed` 真实语义由 D 在 A+B+C 组合树注入不做映射的适配器复验；本轮替身不冒充真实判据。
2. **[待验证]** 失败路径仍不带执行后几何快照（解释器既有事实）；快照补齐前，无快照场景恒 undetermined 放行。
3. **[待验证]** A1.1 `ea8323a` 合入前 5 个 `dep_pending` 失败保持原状态，未放宽断言。
4. **[未覆盖]** `alternative_selection` 多候选试算分支本轮未触发；隔离库重定向缺口属 D 线职责。
5. **[待 A]** `cad_feature_acceptance.py` 落地后，分类函数替换为调用 A 模块、保留同签名；当前 C 独占实现不与之重复造两套。
6. 路由计数既有漂移（26 vs 30）仍归路由测试维护方，不在本轮 C 范围。
