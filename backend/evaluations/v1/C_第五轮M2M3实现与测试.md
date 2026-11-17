# C 线第五轮 FEATURE-CONTRACT：M3 无进展拦截 + M2 结构重规划接入 · 实现与测试报告

- 分支：`v1/c1-integration`；本轮父提交：`8e3efadce5a2ccd07c196f728c817c2e81a44ac9`
- 范围：C 独占 `agent_service.py`、`cad_generation_recovery.py`；新增测试 `test_c13_m2m3_loop_mock.py`
- 状态标注约定：**[已查证]** 本轮代码/测试可复现；**[推断]** 由代码路径推导、未在线上模型上实证；**[待验证]** 依赖 A/B/D 后续合入或组合树联调。
- 本轮硬边界遵守：零模型调用、零联网；未重跑 A9、未启动其它案例；未改 A/B/D 生产代码与公共 Schema；`max_repairs=2` 不变；H2/H3/H4、自相交、来源授权、候选保存条件未动；无爱心/A9/`lower_tip` 专用分支；未合并、未推送、未 amend。

## 1. 结论摘要

1. **M3 无进展拦截骨架已落地**（[已查证]）：双条件闸门 `evaluate_repair_progress` 同时要求「失败特征向量无改善」与「前后几何在既有容差内确定等价」才判 `block / stalled_equivalent`；任一放行白名单命中即放行；首轮修复始终放行；缺几何快照或缺 evaluator 一律 `undetermined` 放行并记录，不凭计划字符串阻断。
2. **M2 通用修复范围分类已接入生产调用链**（[已查证]）：`classify_feature_failure(details, code)` 产出四类 `repair_class` 与 `requires_structural_replan`；结构重规划通道不传部件修复上下文，绕过 ref 范围合并器整计划重编译；反馈含预期特征、实测特征、差异、结构重规划标记四要素。
3. **B 几何判据以窄适配层接入**（[已查证] 骨架；[待验证] 真实联调）：`evaluate_geometry_progress` 通过可注入 evaluator 调用 B 的 `trajectory_equivalent` 语义；C 树不复制 B 实现、不另造第二套等价判据；真实等价判定待 D 在 A+B+C 组合树完成。
4. **回归计数**（[已查证]）：执行器 37 passed、解释器 74 passed、恢复编排 14 passed、本轮新增 24 passed；恢复 + C1/C1.1/C1.2 Mock 套件 16 passed / 5 failed（5 个为既有 `dep_pending`，依赖 A1.1 `ea8323a` 未合入 C 基线）；相邻模块 52 passed / 1 failed（既有路由计数漂移，非本轮引入，见 §7.3）。
5. **收益口径**（[推断]，未记为已实现收益）：M3 在三调用空转序列中可避免第 3 次模型请求；按「首轮修复始终放行」规则，它**不能**回溯取消 A9 已发生的第 2 次修复请求。A9 模拟节省仅为理论上限，待组合树用真实 B 判据复测。

## 2. M3 无进展拦截落地

### 2.1 判定表（双条件不可拆）

实现位置：`backend/app/cad_generation_recovery.py`
- 特征向量提取：`_feature_vector` :89-103（类别 / code / check / failed_features 集合 / measured 布尔元组；不读计划文本、不读本地化文案）。
- 几何快照：`_geometry_evidence` :106-120（取 `trial_result.geometries`；失败路径无快照时 `available=False`）。
- 几何适配层：`evaluate_geometry_progress` :148-207。
- 闸门主函数：`evaluate_repair_progress` :210-272。

| # | 情形 | 判定 | 实现分支（行号） | 状态 |
|---|---|---|---|---|
| 1 | 几何相同 **且** 失败特征集合/测量值/check/code 均未变 | `block / stalled_equivalent` | :254-258 | [已查证] 单元 + 服务级正例 |
| 2 | 先前失败特征转好（集合差集非空） | `allow / feature_improved` | :231-235 | [已查证] |
| 3 | 出现新失败特征/新部件 | `allow / new_failure` | :236-240 | [已查证] |
| 4 | 几何越出等价证据 | `allow / geometry_changed` | :241-245 | [已查证] |
| 5 | 几何等价 `undetermined`（缺快照 / 缺 evaluator / 评估器异常 / 任一覆盖维度 undetermined） | `allow / undetermined` | :163-180、:246-250 | [已查证] |
| 6 | 几何确定等价但特征向量移动 | `allow / feature_moved` | :259-262 | [已查证] |
| 7 | 首轮修复（`before is None`） | `allow / first_repair` | :213-216 | [已查证] |

双条件合取：只有走到 :254 且 `feature_same` 为真、且几何不是 `undetermined`、不是 `equivalent is False` 时才阻断。特征改善或新结构的分支在几何判定之前即返回，不被几何结论牵连。

### 2.2 覆盖维度（方向 / 端点 / 闭合 / 拓扑，不靠 Hausdorff/包围盒/弧长）

- C 侧不自行计算 Hausdorff、包围盒或弧长作为判据；等价判定委托 B 判据，适配层透传 B 的 `checks` 维度：`geometry / orientation / endpoints / closed / topology / transformation`（:186、:195-197）。
- 覆盖维度兜底：若 `geometry/orientation/endpoints/closed/topology` 任一 check 值为 `undetermined`，适配层整体降级为 `undetermined` 并放行（:199-203）。
- 对称判定不作为唯一拦截依据：适配层不调用 `symmetry_check` 做阻断；B 已知径向剖面漏判（[待验证]，随 B 模块在组合树复测）。

### 2.3 放行白名单逐条落地

- `undetermined`：:246-250；缺快照 :163-166；缺 evaluator :167-171；evaluator 抛异常 :172-180（fail-closed，不阻断）。
- 新结构/新部件：`new_failure` :236-240；结构重规划分类见 §4。
- 任一失败特征改善：`feature_improved` :231-235。
- 几何越出容差：`geometry_changed` :241-245；B relation `different` 映射为 `equivalent=False` :190-194。
- 首轮修复始终放行：:213-216；服务侧闸门仅在 `len(construction_attempts) >= 2` 时进入（`agent_service.py:6483`）。

### 2.4 进度结构化日志（可审计）

- 每轮对子：`recovery_record` 在第 2 次及以后尝试写入 `records[-1]['progress']`（:402-403），并汇总顶层 `progress_log`（:404、:407）。
- 日志字段：`decision / progress / feature_before / feature_after / geometry{equivalent,undetermined,relation,reversed,checks,fail_reasons,source} / reasons`。
- 服务结果组装透出 `progress`：`agent_service.py:6731`。
- 阻断合成尝试**不追加**进 `construction_attempts`（避免 repair_count 被多算一轮）；阻断后 `repair_count` 为实际修复次数。[已查证] 服务正例断言 `repair_count == 1`。

### 2.5 回滚开关

- `M3_PROGRESS_GATE_ENABLED`（env `CAD_C1_M3_PROGRESS_GATE`，默认 ON）；`M2_SCOPE_CLASSIFIER_ENABLED`（env `CAD_C1_M2_SCOPE_CLASSIFIER`，默认 ON）；解析见 `_env_flag` :8-12，开关定义 :19-20。
- 默认 ON 理由（[推断]）：M3 仅在「特征无改善 + 几何确定等价」双证据齐备时阻断；所有缺证据路径都放行，不会误杀首轮或证据不足的修复。置 `off/false/0/no` 即退回本轮之前的旧行为；服务侧开关关闭后走旧分类降级与旧循环，测试 `test_m3_rollback_switch_restores_legacy_behaviour` 验证旧行为恢复（24 例内）。

## 3. B 判据适配层（不复制 B 实现）

### 3.1 接口对齐（照抄 B 契约）

注入点：`set_geometry_evaluator(fn)` :145-151；`fn(spec_a, spec_b, tolerance) -> EquivalenceResult`，字段 `equivalent / undetermined / relation / reversed / checks / fail_reasons / hausdorff / topology / counterexample`。

**等价词汇契约（集中一处，不散落字符串比较）**：`EQUIVALENT_RELATIONS = {'identical', 'equivalent'}` :138；`_NON_EQUIVALENT_RELATIONS = {'same_trajectory_reversed', 'similar_transform', 'compliant_other', 'different'}` :141-143。同轨迹匹配在不同 B 版本下可标注 `identical` 或 `equivalent`，二者都属确定等价；非等价集合内的关系一律不构成停滞。

`relation` 映射（:207-226）：

| B relation | C 几何结论 | 处置 | 依据 |
|---|---|---|---|
| `identical` / `equivalent` | `equivalent=True`（B `equivalent` 为准） | 仅当特征也无改善才可能阻断 | 同轨迹同方向，等价词汇集合 |
| `same_trajectory_reversed` | `equivalent=False`，`reversed=True` | 放行；方向维失败不计入进展 | B 坑 1：反向不是改善 |
| `similar_transform` | `equivalent=False` | 放行；合规刚性/尺度/反射调整 | B 坑 2：不等价 ≠ 失败 |
| `compliant_other` | `equivalent=False` | 放行；拓扑保持的形状调整 | B 坑 2 |
| `different` | `equivalent=False` | 放行 | 几何已变 |
| 契约外未知字符串 | `undetermined=True`、`equivalent=None` | **fail-safe 放行**，`fail_reasons` 记 `unknown geometry relation: <值>`（:217-224） | 词汇漂移不得误拦或漏拦 |
| `undetermined=true` | `equivalent=None` | 放行并记录 | B 坑 2：fail-closed |

**相似变换通道决策（已写明，不留模糊状态）**：C 不单独调用 B 的 `similarity_transform`。刚性/尺度/反射或拓扑保持调整会使采样点越出原始等价容差，B 因此标注 `similar_transform`/`compliant_other`（落入非等价集合）而不是等价关系；该判定由适配层放行（`geometry_changed`），不会被误判为停滞。只有落入 `EQUIVALENT_RELATIONS` 的结论才有资格参与阻断。注释见 :226-231。

> 第五轮补丁（D 联调发现）：初版只把 `identical` 当等价，真实 B 返回 `relation="equivalent"` 时停滞用例被误放；已改为集合判定，并补未知值 fail-safe。生产契约内完成词汇对齐，harness 不再做 `equivalent→identical` 映射。

### 3.2 必填输入与缺项降级

- spec 组装：`_geometry_spec` :143-145（geometries + plan；参数区间/控制点/段类型/闭合标志由 plan 与 geometries 携带，采样密度与既有容差经 `tolerance` 透传）。
- 任一快照缺失 → `relation=unavailable`、`undetermined=True`（:163-166）。
- evaluator 未注入 → `relation=evaluator_unavailable`、`undetermined=True`（:167-171）。当前 C 树默认无 evaluator，因此**默认几何判定恒为 undetermined 放行**；不能用指纹哈希冒充等价判据（指纹仅作证据留痕，不参与等价结论）。

### 3.3 待组合树联调声明 [待验证]

- 真实 B 模块在 B 分支（commit `5333826`），C 树不可见；本轮测试使用与 B 语义一致的**测试替身** `_stub_evaluator`，文件内明确标注「非真实 B 判据」。
- 词汇对齐已在生产契约内完成：D 组合树复验时注入**不做任何映射**的适配器；`identical`/`equivalent` 均由 `EQUIVALENT_RELATIONS` 判定，未知值 fail-safe。
- 端到端等价判定、`similarity_transform` 标注、对称漏判复核，由 D 在 A+B+C 临时组合树完成；C 侧仅保证适配层可替换、测试不写死依赖。

## 4. M2 通用修复范围分类与结构重规划接入

### 4.1 分类契约（对齐 A 提案 `45090f6`）

签名：`classify_feature_failure(details, code='') -> {repair_class, requires_structural_replan, reason, missing_fields, preserve}`（:299-371）。输入只取结构化字段 `feature_class / failure_subtype / measured(measured_*) / geometry_scope / code`；不读本地化文案、不做特征名字符串匹配。

| repair_class | requires_structural_replan | 触发条件 | 推导依据 | 实现行号 |
|---|---|---|---|---|
| `parameter_repair` | false | 标量参数/区间/比例/偏移错，特征与连接完整 | 只有标量取值失败，拓扑可保留 | :349-351、降级 :359-362 |
| `connection_repair` | false | 两段之间连续性/连接失败 | 局部成对关系，特征清单不变 | :331-333、:346-348 |
| `feature_replan` | true | 极值/尖点/凹口/对称缺失或错位 | 缺边界元素，改参数无法新增拓扑元素 | :338-340、:352-355 |
| `topology_replan` | true | 数量/闭合/自交/包含/连通分量整体错 | 特征清单或组成关系错，需重排结构 | :334-337、:341-345、:356-358 |

判定顺序（:316-362）：显式 `feature_class` → `failure_subtype`（连接 / 拓扑 / 特征）→ 拓扑证据字段或数量错配 → 连接引用 → 数值参数证据 → 特征缺失标记/缺 id → 代码 token → 降级默认。

**防误伤规则**（[已查证]）：
- 缺字段默认降级 `parameter_repair`，**不得**判 `requires_structural_replan`（:359-362；测试 `test_m2_degraded_default_never_escalates_to_structural`）。
- 数值参数证据（`measured_center_mm / expected_center_mm / error_mm / tolerance_mm / ...` :282-286）优先于特征缺失标记，防止中心偏移类参数修复被误升级为重规划（:349-351 先于 :352-355）。
- `missing_fields` 记录 `feature_class/failure_subtype/measured/geometry_scope` 中缺失项（:313-314）。

### 4.2 生产调用链接入

服务侧 `agent_service.py`：
- 分类接入：:6499-6504；开关关闭时降级 `unspecified` 且保留旧 `requires_structural_replan` 标志。
- 通道合并：`legacy_replan`（旧 details 标志 + ref 子集守卫）与分类器重规划取或（:6505-6507）。**子集守卫只作用于 legacy 路径**；分类器判出的结构重规划不受旧 `plan_refs.issubset(failed_refs)` 限制，避免多部件重规划被错挡。
- 四要素反馈：:6517-6524，JSON 块含 `repair_class / requires_structural_replan / expected_feature / measured_feature / difference`；expected 取 `required_features` 或 `expected_*`，measured 取 `measured_features/measurements/measured_center_mm`，difference 取 `failed_features`。
- 通道路由：:6538-6541 — `structural_replan=true` 时不传 `repair_context`/`component_repair_context`（`{}`），整计划重编译；否则按既有局部/部件上下文传入。
- 保留约束：重规划提示语要求保留原始用户尺寸、数量和连接要求，独立验收不变（:6533）；分类器 `preserve` 清单：用户尺寸、来源需求引用、部件数量、非目标部件（:369-370）。

### 4.3 与部件合并器的边界

合并器 `cad_plan_component_repair.py`（C 基线 60 行）：
- 单位锁 :14-15；失败部件原引用必须保留 :19-24；非受影响部件原样保留 :36-43；失败断言仅按 `assertion_id + target_ref` 局部替换 :44-57。
- M2 结构重规划路径**绕过**该合并器（上下文为空），因此结构变更不会被 ref 全等守卫拦掉；合并器仍只服务参数/连接类局部修复。[已查证] 服务级用例断言结构通道 `component_repair_context`/`repair_context` 均不在 kwargs。
- 局部修复守卫：`cad_local_repair.py:177-201`（源计划指纹、全局字段、步骤身份与顺序、受保护几何指纹）继续有效，重规划通道不绕过这些验收。

### 4.4 生产链级 Mock 验证（真实 `_formal_cad_construction` 入口，仅 Mock 模型文本出口）

测试文件：`backend/tests/test_c13_m2m3_loop_mock.py`
- 四类分类逐条 + 降级不误判：`test_m2_classifier_four_channels` :145-150、`test_m2_degraded_default_never_escalates_to_structural` :153-157。
- 反馈四要素 + 通道路由：`test_m2_loop_feedback_four_elements_and_channel` :189-215（参数/连接走 `component_repair_context`，特征/拓扑重规划无上下文）。
- 保留尺寸/数量/非目标部件：`test_m2_replan_preserves_dimensions_count_and_other_part` :218-241（非目标 `keep` 部件与断言集合保留）。
- 无 `lower_tip` 字符串分支：grep 证据见 §7.4。

### 4.5 待 A 模块落地后的替换点 [待验证]

待 A 的 `cad_feature_acceptance.py` 落地后，把 `classify_feature_failure` 替换为「调用 A 模块、保留同签名与同输出字段」；当前 C 独占实现不与之重复造两套。v1 不把特征进执行器断言联合类型/约束求解器，先做验收层 sidecar（遵循 A 提案）。

## 5. 正反例与调用次数证据（max_repairs=2 实际模拟）

### 5.1 正例（应拦截）— 单元 + 服务级

- 单元：`test_m3_blocks_identical_geometry_and_unchanged_failure_vector` :260-278；替身 evaluator 返回 `identical / equivalent=True`；特征向量前后一致 → `block / stalled_equivalent`。
- 服务级：`test_m3_loop_blocks_proven_stall_after_second_request` :320-344。
  - 序列：请求 1 首轮计划 → 请求 2 首轮修复；闸门在 attempts 1→2 之间判定证明停滞，**第 3 次模型调用不发出**。
  - 调用次数证据：`len(calls) == 2`；`error.code == no_progress`；`progress.progress == stalled_equivalent`；无候选落库；`repair_count == 1`；`progress_log[-1].decision == block`。

### 5.2 反例（不得拦截）— 均放行到第 3 次请求

| 反例 | 用例 | 调用次数 | 放行理由 |
|---|---|---|---|
| 几何快照缺失 | `test_m3_loop_releases_when_geometry_snapshot_is_missing` :347-364 | `calls == 3`，`undetermined` | 缺快照不得凭计划字符串阻断 |
| 几何真改 | `test_m3_loop_releases_on_geometry_change` :367-380 | `calls == 3`，`geometry_changed` | 几何越出等价证据 |
| 新失败/新部件 | 单元 `new_failure` :236-240 | 单元放行 | 特征清单变化 |
| 方向/端点/闭合/拓扑任一变化 | 单元 B relation 用例 :293-303（`same_trajectory_reversed / different`） | 单元放行 | 覆盖维度不一致 |
| 判据 undetermined | `test_m3_undetermined_evaluator_releases` :305-316 | 单元放行 | fail-closed |
| 回滚开关关闭 | `test_m3_rollback_switch_restores_legacy_behaviour` :383-394 | `calls == 3` | 退回旧行为 |

### 5.3 A9 案例口径（不得把理论节省当已实现收益）

- A9 事实（沿用第四轮证据，未重跑）：2 次 `deepseek-flash` 请求，输入 31,554 / 输出 804 tokens，费用 0.005764632 USD；修复轮表达式逐字未变、仅参数区间平移，`lower_tip=false` 持续。
- [推断] M3 在 A9 同形三调用空转序列里，可避免的是**假想的第 3 次**重复请求（量级参照第 2 次修复：约 16,172 输入 / 450 输出 tokens、$0.001026288、约 8s）。
- **不能**回溯取消 A9 已发生的第 2 次修复：按「首轮修复始终放行」规则，闸门在 attempts 仅 1 轮时不进入；第 2 次请求属第一次修复，本轮规则下必须放行。
- [待验证] 真实收益须由 D 在组合树用真实 B 判据 + 真实评测复测；替身结果不计入真实模型通过率。

## 6. 第 5 问：候选保存与独立验收链路上的「看似变化、实际等价」漏洞清单

等级：高 = 可空转消耗请求或绕过验收；中 = 留痕但可被噪声掩盖；低 = 已有守卫覆盖，仅残余缺口。

| # | 漏洞形态 | 证据位置（文件:行号） | 现状守卫 | 危害 | B 判据可否覆盖 | 备注 |
|---|---|---|---|---|---|---|
| L1 | 只改参数区间/参数域，轨迹不变（A9 同形） | 第四轮根因：`changed_plan_fields`/`step_diff` 仅比计划字典；本轮 M3 特征向量 :89-103 + 几何适配 :148-207 | 有几何快照 + B 等价判据时可拦；缺快照放行 | 高 | **可覆盖**（轨迹等价 + 方向/端点/闭合/拓扑一致时） | 失败路径当前不带几何快照（`cad_construction_interpreter.py:1035-1043` 既有事实），快照补齐前默认 undetermined |
| L2 | 只改断言文字/阈值，几何未变 | 合并器断言局部替换 `cad_plan_component_repair.py:44-57`；提示语禁止只改断言 `agent_service.py:6534` | 失败断言按 id 替换，无关断言保留；来源几何验收在合并后仍跑 | 中 | 部分覆盖（几何轨迹等价可识别）；断言本身是否放松属 A/验收层职责 | 本轮未放宽断言保存条件 |
| L3 | 只改部件标签/semantic 文案，几何未变 | 局部修复身份校验 `cad_local_repair.py:181-186`；identity 修复 :26-33 | 非可编辑字段不得改；object_id 必须明确 | 中 | 部分覆盖（几何等价）；标签语义等价性不在 B 几何判据范围 | 留待 A 语义验收 |
| L4 | 只改容差/比例数值但不触及拓扑 | 分类器数值参数证据 :349-351；验收阈值 H2/H3/H4 为后端固定 | 模型不能放松后端验收阈值；参数错归 `parameter_repair` | 低 | 不覆盖（本就是参数修复，应放行） | 非漏洞，属预期通道 |
| L5 | 只重排段序，轨迹点集不变 | `step_diff` 按 ref 比较 `cad_generation_recovery.py:392-401`；局部修复顺序守卫 `cad_local_repair.py:181` | 局部通道锁步骤顺序；整计划重规划通道不在此列 | 中 | **可覆盖**（轨迹/拓扑等价）；段序作为拓扑关系纳入 B checks | 整计划通道需独立验收兜底 |
| L6 | 只改失败反馈文案/消息，计划与几何未变 | 旧 `bounded_repair_available` 签名含 message `cad_generation_recovery.py:60-64`；M3 特征向量不含 message :89-103 | M3 不拿 message 当进展；旧循环仍按消息签名判不同 | 中 | 不依赖文案；几何/特征向量判定 | 旧签名把文案变化记为不同，是第四轮根因之一，M3 侧已不采用 |
| L7 | 只提高 confidence，未改计划或几何 | `confidence_only_repair` :70-75；服务拦截 :6553-6559 | 既有守卫，本轮未动 | 低 | 不适用 | 已覆盖 |
| L8 | 只改包围盒/尺寸标注，实际轮廓未变 | 特征向量 measured 布尔 :94-102；几何快照 :106-120 | 有快照时由 B 轨迹判据覆盖 | 中 | 可覆盖 | 缺快照时放行 |

## 7. 测试与回归原始计数

### 7.1 本轮新增（`test_c13_m2m3_loop_mock.py`，27 例）

命令：`pytest tests/test_c13_m2m3_loop_mock.py -q` → **27 passed in 1.22s**。
覆盖：M2 四类参数化 4 + 降级 1；M2 反馈四要素与通道 4 参数化 + 保留 1；M3 首轮放行 1、等价词汇阻断参数化 2（`identical`/`equivalent`）、白名单参数化 3、B relation 参数化 4（含反向 `reversed` 标记断言）、未知关系 fail-safe 放行 1、undetermined 1、服务阻断 1、缺快照 1、几何改变 1、回滚 1。

第五轮补丁新增用例（真实 B 词汇，harness 不做映射）：
- `test_m3_equivalence_vocabulary_blocks_stall`：`relation="equivalent"` + 特征向量不变 → `block / stalled_equivalent`。
- `test_m3_unknown_relation_fails_safe_release`：契约外 `bogus_future_relation` → `allow`、`undetermined=True`、`equivalent=None`，`fail_reasons` 记录 `unknown geometry relation`。
- `same_trajectory_reversed`：在 B relation 参数化内断言 `reversed=True` 且放行，不计进展。

### 7.2 既有基线（本轮复跑通过）

| 套件 | 命令 | 结果 |
|---|---|---|
| 执行器 | `pytest tests/test_cad_construction.py -q` | **37 passed** in 7.09s |
| 解释器 | `pytest tests/test_cad_construction_interpreter.py -q` | **74 passed** in 16.08s |
| 恢复编排 | `pytest tests/test_cad_generation_recovery.py -q` | **14 passed** in 3.17s |
| 恢复 + C1/C1.1/C1.2 Mock | `pytest tests/test_cad_generation_recovery.py tests/test_c1_integration_mock.py tests/test_c11_service_two_round_mock.py tests/test_c12_production_loop_mock.py -q` | **16 passed, 5 failed** |

5 个失败（既有 `failed_dep_pending`，依赖 A1.1 `ea8323a230f1cd53cf80f4fd4398328e836962b2` 未合入 C 基线）：
- `test_c1_integration_mock` 3 例；`test_c11_service_two_round_mock` 2 例。
- 非本轮改动引入；未为变绿放宽断言。

### 7.3 相邻模块回归

`pytest tests/test_cad_local_repair.py tests/test_cad_plan_component_repair.py tests/test_agent_service_boundaries.py tests/test_agent_plan_recovery.py -q` → **52 passed, 1 failed**。
唯一失败 `test_agent_management_routes_are_registered_once`：断言期望 26 条路由，实际 30 条。已查证 `backend/app/routers/agent.py` 在父提交 HEAD 与工作树均为 30 条装饰器、本轮 diff 未触路由器目录；属基线既有路由计数漂移，归属路由测试维护方，不在本轮 C 范围。

### 7.4 无 `lower_tip` / 爱心 / A9 专用分支 grep 证据

- `backend/app/cad_generation_recovery.py`：`lower_tip|爱心|心形|A9|S1` → **0 匹配**。
- `backend/app/agent_service.py`：`lower_tip` → **0 匹配**。
- `backend/tests/test_c13_m2m3_loop_mock.py`：`lower_tip|爱心|心形|A9|case_id` → **0 匹配**。
- 分类依据为 `feature_class / failure_subtype / measured / geometry_scope / code` 等结构化字段；测试特征名使用通用 `cusp/center/inner/closed_region`。

## 8. B 判据接入点（接口说明）

- **接入层级**：修复循环内（`agent_service.py` 有界循环 :6483-6492），判定对象是连续两轮 attempt；恢复编排 `cad_generation_recovery.py` 提供纯函数判定。未在 `cad_generation_recovery.py` 之外另设恢复策略层拦截。
- **输入**：默认取执行后几何快照（`trial_result.geometries`）+ 计划（区间/表达式/闭合标志）；若失败路径不带快照，则几何侧降级为 `undetermined`，判定退化到「仅特征向量可证子集」，且该子集只能在特征完全未变时结合几何证据阻断；缺几何证据时不阻断。
- **输出进入判定**：`evaluate_repair_progress` 返回 `decision=block/allow`；block 时服务把 interpretation 转为 `status=invalid`、`error.code=no_progress` 并 break。不是先写 `no_progress` 再走 `bounded_repair_available`；闸门在循环顶部、`bounded_repair_available` 之前评估。
- **安全终止**：`max_repairs=2` 不变；阻断只发生在双证据齐备时；首轮放行；任何 undetermined/缺证据/新结构/特征改善/几何改变都放行。误杀风险兜底：env 开关一键回退旧行为；阻断结果写入 `progress_log` 可审计；分类降级默认不升级重规划。

## 9. 最小修改建议（待批准，本轮未实施生产改造）

> 本节为后续候选改动，均标注待批准；本轮生产代码仅含 §1 已落地范围。

1. **失败路径补执行几何快照**（建议归属解释器/A 线，非 C 独占）
   - 最小修改：invalid 结果携带轻量几何指纹/采样引用，使 M3 几何侧可在组合树接入 B 判据。
   - 回归范围：解释器 74 例、候选状态、局部修复几何指纹。
   - 回滚点：快照字段为空时 M3 自动回退 `undetermined` 放行，不阻断旧路径。
2. **接入真实 B evaluator**（组合树阶段）
   - 最小修改：合并后在装配层调用 `set_geometry_evaluator(b_trajectory_equivalent)`；C 侧签名不变。
   - 回归范围：M3 24 例替身替换为真实判据快照；组合树端到端。
   - 回滚点：`set_geometry_evaluator(None)` 即回到缺 evaluator 放行行为。
3. **分类字段缺项补齐**（待 A 特征验收模块）
   - 最小修改：details 补 `feature_class/failure_subtype/measured/geometry_scope`；C 分类函数同签名替换为调用 A 模块。
   - 回归范围：M2 四类用例、服务级反馈四要素。
   - 回滚点：分类器开关 `off` 退回旧 details 标志路径。

## 10. 待办与未决事项

- [待验证] B 真实几何判据端到端：D 在 A+B+C 组合树跑轨迹等价/反向/合规变换/拓扑保持调整四类样本。
- [待验证] A1.1 `ea8323a` 合入后消除 5 个 `dep_pending` 失败；本轮未改其断言。
- [待验证] 路由计数漂移（26 vs 30）归属路由测试维护方核对。
- [遗留] `alternative_selection` 多候选试算分支本轮未触发；ComponentRepairError 仅在修复轮合并器内抛出；隔离库重定向缺口属 D 线职责。
- [偏好同步] 本地代码修改后应同步更新后端最终同步清单（该偏好路径在本环境不存在，沿前三轮状态记为残余）。
