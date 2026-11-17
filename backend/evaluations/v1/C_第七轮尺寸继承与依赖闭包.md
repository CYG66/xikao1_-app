# C 线第七轮 · 尺寸继承、作用域与依赖闭包诊断报告

- 分支 `v1/c1-integration`；基线 HEAD `aa2330e`（第六轮测试/报告提交）。
- 本轮**以诊断为主**：`backend/app` 零改动（`git diff HEAD -- backend/app` 为空），未达到"可复现失败证据 + 一类通用问题 + 影响面"三条件的项只写诊断结论，不动代码。
- 纪律：零模型调用、零联网；未重跑 A9、未改冻结语料；未改 A/B 文件、解释器、合并器、路由器；`max_repairs=2`、验收与几何等价标准未放宽；不 amend/push/合并。
- 状态标记：**[已查证]** 代码/测试可复现；**[推断]** 基于代码结构；**[unverified]** 缺真实链路/真实判据证据，待组合树或 A 模块落地后复核。

## 0. 本轮产物与复现命令

- 诊断测试：`tests/test_c14_dimension_closure_diagnostic.py`，**8 passed**。
- 复现（`backend/` 目录）：
  - `python -m pytest tests/test_c14_dimension_closure_diagnostic.py -q`
  - `python -m pytest tests/test_c13_m2m3_loop_mock.py tests/test_c14_dimension_closure_diagnostic.py tests/test_cad_generation_recovery.py -q`
- 语料对照引用：冻结 70 例语料（A1–A11 / B1–B19 / C1–C34 / D1–D6），本轮未执行、未改文本；A 侧 V1.1 提案仅作边界参照，不视为已实现成果。

## 1. 尺寸约束在修复前后的继承与作用域

### 1.1 尺寸作用域在数据结构中的落点（[已查证]）

| 层级 | 存放位置 | 代码位置 |
|---|---|---|
| 整体尺寸 | `assertions` 中 `bounds_size`，`target_ref` 缺省为 `None` 表示整图 | `cad_construction.py:524-530`；计划顶层 `units` :601 |
| 部件尺寸 | 步骤字段（圆 `radius`、矩形 `width/height`、椭圆长短轴等），绑定到该 `output_ref` | `cad_construction.py:144-175` |
| 部件来源 | 步骤 `source_requirement_refs`；接点约束内同名来源清单 | `cad_construction.py:265`、:288 |
| 单位 | 计划顶层 `units ∈ {m, mm}`；部件修复合并时禁止改单位 | 合并器 `cad_plan_component_repair.py:14-15` |

### 1.2 三种输入情形（按冻结语料对照）

| 情形 | 语料代表 | 计划层正确形态 | 风险 |
|---|---|---|---|
| 输入只有整体尺寸、无部件尺寸 | A1（宽 4 高 4）、A9（宽 4 高 4 + 中心 (2,3)） | 整体 `bounds_size`（`target_ref=None`）；不得给某部件凭空加半径/宽高 | 若计划给部件造了尺寸约束，属无来源约束；**[unverified]** 现有链路是否拦截此类凭空部件尺寸，需 A 侧需求契约/验收侧证据 |
| 输入有整体尺寸，可能被部件覆盖 | 复合轮廓（如 C16 墙体+屋顶+门、C21 十字臂宽） | 整体宽高留在整图断言；部件各自尺寸留在步骤字段；两者不得互相替换 | 作用域混淆最易出现在阵列/复合类；本轮 C 循环只透传前计划与反馈，不做"整体断言被绑到部件"的独立复核 |
| 两级尺寸同时存在且绑定正确 | C7（矩形 + 四圆，圆半径 0.5）、C29（外/内正方形边长） | 整体/布局尺寸走断言或布局条目；半径/边长走部件步骤字段，按 `output_ref` 归属 | 重编号/重排时部件尺寸串到别的部件，需引用重建后按 `output_ref` 重新绑定；当前绑定证据见 §2 |

### 1.3 修复轮继承实测（[已查证]，诊断用例 8 例中的 3 例）

- **参数修复**：整图 `bounds_size` 断言原样保留；非目标圆半径 2.0 仍绑在原 `wheel` 步骤；计划单位保持 `m`；修复上下文携带前计划（含步骤来源引用）。用例 `test_dimension_overall_assertion_and_part_radius_survive_parameter_repair`。
- **结构重规划**：目标轮廓表达式重建；非目标 `wheel` 步骤整步保留（半径、身份、来源、接点闭包）；整图断言与单位不变；目标步骤来源 `R1`、非目标来源 `R2` 保留。用例 `test_dimension_part_size_and_non_target_preserved_under_structural_replan`。
- **作用域编码锚点**：整图断言无 `target_ref`；部件尺寸在步骤字段；整体宽高不复制到部件步骤。用例 `test_dimension_scope_is_encoded_by_assertion_target_ref_and_step_field`。

### 1.4 未覆盖 / 混淆可能引入的环节（[unverified]）

- C 修复循环（`agent_service.py:6525-6541`）把前计划 JSON 与失败证据透传给下一次构造；**作用域归属的正确性由构造编译与独立验收侧保证**，不在 C 循环内重复计算。
- "整体宽高被错误绑定到某个部件"的判定依据应是：断言 `target_ref` 与步骤 `output_ref` 归属、来源索引条目是否一致。生产 C 侧未发现把整体尺寸写入部件步骤的代码路径；若存在，引入点更可能在计划编译/模型输出合并阶段（解释器与合并器所属边界，本轮未改）。**[unverified]** 待 A 侧需求契约归属证据与组合树端到端复核。
- 单位/坐标系混用：合并器在部件修复路径拒绝改单位（`cad_plan_component_repair.py:14-15`）；结构重规划路径依赖提示词约束（`agent_service.py:6233`、:6534），未在 C 循环做单位二次校验。

## 2. 结构重规划依赖闭包完整性

### 2.1 四层保留逐项结论

| 层 | 含义 | 当前证据 | 结论 |
|---|---|---|---|
| 受影响部件 | 种子失败 `output_ref`，本轮允许重建 | 分类器输出 `repair_class/requires_structural_replan`；结构通道不传 `repair_context/component_repair_context`，整计划重编译（`agent_service.py:6505-6507, 6538-6541`） | **部分完整**：种子来自失败 details；引用集合由后端解析，不靠模型标签 |
| 上游引用 | 部件依赖谁（来源事实、来源引用） | 步骤 `source_requirement_refs`、接点 `source_requirement_refs`；非目标步骤整步保留；上下文深拷贝前计划 | **完整（整计划重编译路径，Mock 证据）**；部件合并路径下上游引用是否随替换步骤保留，见 §2.3 风险 |
| 下游依赖 | 谁依赖它（断言/约束/布局引用该 ref），改动后是否标记重算 | 仅有悬空引用校验 `cad_plan_references.py:5-51`；**无类型化依赖图、无固定点传播、无 `revalidate`/`editable` 集合** | **不完整**：下游消费者不会被自动标记需重验 |
| 非目标部件 | 原样保留几何、身份、引用 | C1.3 用例断言非目标步整步相等；结构通道提示词禁止无关重建 | **部分完整**：Mock 整计划路径有断言保护；合并器路径保护边界见下 |

### 2.2 闭包计算入口（[已查证]）

- 引用合法性校验：`cad_plan_references.py:5-51` `plan_reference_errors`——检查 `step_id/output_ref/assertion_id/constraint_id` 唯一、`source_ref` 非前向/未知、断言与约束 `target_ref/reference_ref` 存在、布局 `right_of_ref` 先于目标。**它只查悬空引用，不算下游闭包集合。**
- 接点约束校验：`cad_construction.py:290-299`（段索引邻接、连续性意图）。
- 来源索引/连接来源验证入口：`cad_requirement_contract.py:155`（`source_requirement_refs` 清单读取）。
- 修复上下文入口：`agent_service.py:6538-6541`（局部 `repair_context` / 部件 `component_repair_context` / 结构通道空上下文）。
- 合并器：`cad_plan_component_repair.py:5-60`；替换受影响步时保留字段仅 `step_id/output_ref/semantic/layer_id`（:40-42）。

### 2.3 下游漏算用例与前后对照（诊断）

用例 `test_closure_downstream_dependency_is_listed_but_not_marked_revalidated`：

- 种子 `REF`（轮廓）；下游消费者 `wheel`，经 `center_distance` 断言 `reference_ref=REF, target_ref=wheel` 引用。
- 诊断收集器（仅测试内，非生产代码）算出下游 `{REF → wheel}`。
- 分类器输出 `{repair_class, requires_structural_replan, reason, missing_fields, preserve}`，**不含 `revalidate_refs` / `downstream_refs`**。
- 前后对照：上游来源 `R1/R2` 保留；非目标 `wheel` 步骤保留；下游断言仍在计划中，但**没有被标记为需要随轮廓重建而重算**。

**最危险形态**：轮廓被重建后，引用它的距离/连接关系几何不自洽，但下一轮独立验收若只查各部件自身特征、未复跑该跨部件关系，可能放行。本轮证据为代码结构推断；**[unverified]** 真实验收是否覆盖该跨部件关系，待组合树端到端。

### 2.4 合并器边界风险（[已查证] 代码事实，未改合并器）

- 部件修复合并：非受影响步原样保留；受影响步由替换步覆盖。保留字段清单（`cad_plan_component_repair.py:40-42`）**不含** `junction_constraints` 与 `source_requirement_refs`；即替换步骤的接点闭包与来源以模型返回为准，合并器不强制从原步骤继承这两类字段。
- 失败断言可在受影响范围内修正（:44-57），其余断言与用户原始要求不动。
- 该文件属本轮红线边界，未修改；列为待批准建议 §6。

### 2.5 明确判断：M2 依赖闭包 **部分完整**

- 已具备：种子引用、上游来源随非目标步保留、非目标部件在整计划重编译路径的保留断言、单位与非目标步骤保护。
- 不具备：下游依赖类型化闭包与固定点传播、下游重算标记、合并路径下接点/来源字段的强制继承、闭包集合前后对照审计字段。
- 不判"完整"：下游漏算通道存在；不判"不完整"：上游与非目标保留在当前 Mock 链路有可复现证据。

## 3. 拦截误杀复核（必须放行项）

C1.3 已覆盖服务级与单元级用例；本轮 C1.4 单元级复跑（`test_whitelist_releases_round7_recheck`）：

| 情形 | 结论 | 依据 |
|---|---|---|
| 首轮修复 | `allow / first_repair` | `evaluate_repair_progress(None, after)` :305-308；服务侧 `len(attempts)<2` 不进闸门 |
| `similar` / `similar_transform` | `allow / undetermined` | `_SIMILAR_UNDETERMINED_RELATIONS` :147，分支 :264-269 |
| 契约外 `unknown` | `allow / undetermined`，记 unknown relation | :274-280 |
| 缺几何快照 | `allow / unavailable` | :218-223 |
| 比较不确定（评估器 undetermined / 覆盖维度不确定） | `allow / undetermined` | :233-244、:255-258、:338-342 |
| 失败特征改善 | `allow / feature_improved` | :323-327 |
| 新增失败 | `allow / new_failure` | :328-332 |
| 目标无进展 + 无关部件移动 | **判无有效修复 `block / stalled_equivalent`** | 目标子集比较，C1.3 :416-445；本轮依赖/尺寸用例未推翻该结论 |

无证据表明上述放行项被误杀；`max_repairs=2` 未变，闸门只在双条件同时满足时拦截。

## 4. 候选确认与恢复上下文携带（字段级证据）

### 4.1 恢复轮携带了什么

| 字段 | 存储位置 | 下一轮读取位置 | 证据 |
|---|---|---|---|
| 失败候选（当次 interpretation） | `construction_attempts` 深拷贝入账 | 循环内 `failed_attempt=deepcopy(interpretation)` | `agent_service.py:6477, 6494` |
| 被拒绝计划 | `plan` 或 `rejected_plan`；写入提示词"前次未通过的计划"JSON | 下一次构造输入文本；部件/局部上下文深拷贝 | `agent_service.py:6525-6530, 6538-6541` |
| 失败错误与 details | 上下文 `construction_error/error`；恢复记录 `error` | 分类器与反馈四要素读取 | `agent_service.py:6495-6500, 6510-6524`；`recovery_record` `cad_generation_recovery.py:466-474` |
| 来源引用 | 随前计划步骤 `source_requirement_refs` 携带，无独立来源通道 | 上下文计划步骤；提示词前计划 JSON | `cad_construction.py:265`；C1.4 用例上下文断言 `R1/R2` 在场 |
| 进度审计 | 每轮 `progress` + 顶层 `progress_log` | 恢复记录透出 | `cad_generation_recovery.py:479-500`；服务 `agent_service.py:6619-6620` |

### 4.2 来源引用是否会在修复轮丢失（诊断结论）

- **整计划重编译/部件上下文路径**：来源引用随计划深拷贝进入上下文与提示词；本轮 Mock 证据显示目标与非目标步骤的 `source_requirement_refs` 在下一轮输入中在场。**[已查证] Mock 链路**。
- **缺口**：C 循环没有独立的 `source_refs` 账本字段；来源是否被模型在新计划中沿用，依赖下一轮计划自身与来源索引校验；上下文里的前计划来源不等于新计划已绑定来源。**[unverified]** 修复轮是否可能丢失来源追溯，需 A 侧来源索引在组合树复核。
- 失败路径不保存成功候选；候选保存条件本轮未动。就绪成功信封持久化候选，恢复记录挂在 interpretation 上（失败路径投影到 `construction_interpretation.recovery`；就绪路径不重复透出该审计块）。

## 5. "编辑器自身失败" vs "前置版本未验收阻塞"的口径

### 5.1 判定口径（[已查证]）

| 类别 | 判定依据 | 生产码/类别 |
|---|---|---|
| 本次构造/执行真失败 | `status=invalid` + `provider_attempted`，类别 ∈ 可修复集合 `model_plan_invalid / constraint_conflict / sampling_budget` | `should_repair` `cad_generation_recovery.py:36-38`；类别 `:23-33` |
| 不可修复/外部失败 | 需求缺参、需求未核验、网络/传输、持久化失败、仅置信度 | `requirements_missing/requirements_unverified/network_failure/persistence_failure`；`low_confidence/confidence_only_repair` |
| 前置版本未验收阻塞 | **测试状态标签** `failed_dep_pending`：严格断言等待未合入的 A1.1/B1.2 契约；不是生产错误码 | 仅存在于测试与测试状态 JSON，生产 `recovery_category` 不产出该码 |

### 5.2 混淆位置排查

- 生产统计/错误码集合中未出现 `dep_pending` / `failed_dep_pending`（用例 `test_dep_pending_is_not_a_production_error_code` 断言恢复记录错误码不含二者）。
- 5 个既有失败用例的标签与依赖提交记录在 `evaluations/v1/C1_test_status.json` 与 C1/C1.1 报告中；它们是**基线契约未合入**导致的待补测试，不计入编辑器缺陷率。
- **[unverified]** 若其它汇总脚本把 `failed_dep_pending` 与真实 `candidate_generation_failed/structure_requirement_failed` 混算进同一失败率，应在统计侧拆分；本轮未发现 C 线生产分类器做此合并。

## 6. 未提交补丁清单（只描述不落码）

**本轮无未提交的生产补丁**：`backend/app` 工作树为空改动；以下 R7-1 ~ R7-4 仅为诊断建议，未写入任何生产代码，不构成 P0 语义规则或匹配词表修改。三条件（可复现证据 / 一类通用问题 / 影响面与回归范围）尚未全部满足，标 **待批准**，不在本轮提交。已有生产提交（保留不回滚）：`23e0653`（第五轮 M3 闸门 + M2 分类器）、`c3bc8bf`（词汇补丁）、`813923d`（第六轮目标范围比较 + similar/unknown 分支）、`aa2330e`（第六轮测试与报告）。

| 编号 | 最小修改建议 | 解决的通用问题 | 回归范围 | 回滚点 |
|---|---|---|---|---|
| R7-1 | 在恢复层增加只读下游闭包收集器：按断言/约束/布局引用反查种子 ref 的消费者集合，随反馈输出 `revalidate_refs`；不自动扩大重规划范围 | 跨部件关系在目标重建后漏算重验（一类：任何被引用部件重规划） | C13/C14、恢复 14、部件合并相关既有 Mock；不接触验收门禁 | 移除收集器与反馈字段，回到当前仅种子 ref 通道 |
| R7-2 | 部件合并器继承受影响步的 `junction_constraints/source_requirement_refs`（与 `step_id/output_ref/semantic/layer_id` 同清单），或在缺失时拒绝合并 | 合并路径下接点闭包/来源被替换步丢弃 | 合并器既有测试 + C1/C11 两轮 Mock；属合并器边界，需其维护方批准 | 恢复当前仅身份四字段保留的合并语义 |
| R7-3 | 分类器增加证据强度门：仅区域存在性布尔（legacy region presence）不直接升级数学 `feature_replan`，标注 `legacy_evidence` 降级或待测量方法字段 | 旧布尔冒充数学尖点/凹口证据的分类过度 | 四类分类用例 + 降级默认用例；待 A `cad_feature_acceptance.py` 测量方法字段落地后对接 | 移除证据门，回到当前 subtype 直映分类 |
| R7-4 | 失败路径补执行后几何快照（解释器边界），让 M3 几何维度在失败轮可判定 | 无快照恒 undetermined 放行 | 解释器 74 + C13/C14；非 C 独占文件，需解释器维护方批准 | 不附快照字段，回退当前 `unavailable` 放行路径 |

## 7. 回归原始计数

| 套件 | 结果 |
|---|---|
| `test_c14_dimension_closure_diagnostic.py`（本轮新增） | **8 passed** |
| `test_c13_m2m3_loop_mock.py` | **30 passed** |
| `test_cad_generation_recovery.py` | **14 passed** |
| 以上合计 | **52 passed** in 3.18s |
| `test_cad_construction.py`（执行器） | **37 passed** |
| `test_cad_construction_interpreter.py`（解释器） | **74 passed** |
| 执行器+解释器 | **111 passed** in 23.09s |
| 既有 C1/C1.1/C1.2 Mock | **2 passed / 5 failed**，5 个 `dep_pending`（依赖 A1.1 `ea8323a`、B1.2 未合入），断言未放宽 |
| 本轮 app 改动 | **0 文件**（诊断测试与报告除外） |

## 8. unverified 清单

1. 真实 B 几何判据端到端（目标闭包等价、相似/反向/合规变换语义）仍待 D 组合树不映射适配器复验。
2. 失败路径执行后几何快照未补；无快照场景恒 undetermined 放行。
3. 整体/部件尺寸归属是否在编译与验收侧被正确约束，缺 A 侧需求契约归属证据。
4. 下游跨部件关系在目标重建后是否被独立验收复跑，缺真实链路证据。
5. 部件合并路径下接点约束/来源字段的保留行为，本轮未构造合并器侧可复现失败用例。
6. 修复轮新计划是否沿用来源引用，待 A 来源索引在组合树复核。
7. `dep_pending` 是否在其它统计脚本中被并入真实失败率，未跨模块排查。
8. A1.1 `ea8323a`、B1.2 合入前 5 个待补测试保持原状态；路由计数漂移归路由测试维护方。
