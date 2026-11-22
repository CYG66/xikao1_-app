# R-IDENTITY-1 通过分支证据作用域审计（B 方，只读）

- 性质：只读审计；未改代码、未建分支/提交、零模型、零网络。
- 复核对象：分支 `r-identity1`，HEAD `094d2f7`；区间基线 `ee57143..094d2f7`。
- 范围限定：两文件边界（结构契约模块、解释器）；不混入 R-01/R-03/Stroke/Path/QE。
- 结论以代码走读 + blob diff 为准；未端到端复现装配链路（见第 9 节）。

## 0. 结论速览

| 审计项 | 结论 |
|---|---|
| 1. 追溯链（条目 → 对象 → 几何 → 证据） | 测量分支按对象取证据；但 `matched_entries` 未回写 `geometry_ids`，报告内可追溯性止于 `object_id` |
| 2. 通道通过分支整体扫配 | **存在**：通道 `passed` 后把全部未占用对象批量配给条目，配对后不复做类别核对 |
| 3. A 证 B | **测量分支无**；**通道分支有**（全局通道结论被用来为全部扫配对象背书） |
| 4. 共享几何 | 身份门不直接读 `shared_geometries` 声明；归属图校验后按对象 refs 取证据；无借共享跳过身份证据的路径，但共享 owners 一致性由数量门负责 |
| 5. 未分类处理 | 未分类不计入"确定不匹配"；池级比对偏粗（池中已有异类即可能 `failed`），未分类对象被排除后不阻止整体 `passed` |
| 6. 三圆/额外对象 | 第三个对象进 `unmatched_objects`；身份报告不压制数量 `failed/extra_object`，两报告独立挂载 |
| 7. 零改动事实 | 数量函数体零删除行；Plan v1、候选门禁、执行器、拓扑、tooling、语义分发 blob 与基线 SAME |

## 1. 审计项 1：追溯链是否按对象取证据

### 1.1 代码链路

- 基线条目：`_identity_baseline_entries`（解释器 L1734–1814），条目带 `requirement_id / noun / quantity / category / evidence / evidence_span / baseline_channel`。
- 对象侧描述子：`_measured_object_descriptor`（L1704–1731），以 `object_id` 为键在描述子字典中逐对象生成（L1919–1922）：
  - refs 取对象 `geometry_refs`（兼容 `geometry_ids`），L1706；
  - 仅保留归属 refs 与活动几何交集 `owned`，L1707–1708；
  - 类别与 `geometry_ids` 均来自该对象自身归属几何，L1709–1731。
- 测量分支匹配：候选集按"对象未被占用且描述子类别 == 条目类别"过滤（L1955–1958），绑定结果写入 `object_ids`（L1976）。

### 1.2 结论与缺口

- 测量分支**确实按对象取证据**：类别证据挂在 `object_id` 对应的归属几何上，不存在整图测量结果直接挂到条目的路径。
- 缺口：`matched_entries` 条目只回写 `object_ids`，**未回写描述子里的 `geometry_ids`**（L1971–1980 字段表）；报告内追溯链在 `object_id` 之后不直接可见归属几何 id，需回到描述子字典反查。建议后续在匹配记录中补充 `geometry_ids` 作为可审计证据。

## 2. 审计项 2：通道通过分支是否整体扫配

### 2.1 代码位置

- 通道结论获取：`_channel_verdict`（L1927–1939）复用既有 `projection_acceptance` / `semantic_acceptance` 的**全局状态**（`passed/failed`），不按对象拆分。
- 扫配路径：L2030–2042：

  > `object_ids = [object_id for object_id in descriptors if object_id not in used_object_ids]`

  通道 `passed` 后，所有未占用对象整体计入该条目；之后**没有再复做类别核对**（无描述子类别比对、无 per-object 通道证据键）。

### 2.2 结论

- **存在整体扫配**：通道通过 ≠ 每个被扫配对象都通过了同一通道；扫配对象的身份证据级别继承自全局通道结论。
- 若一个条目对应多个非测量类别对象，且后续还有条目，第二个条目只能拿到剩余未占用对象；占用集合 `used_object_ids`（L1941、L1963、L2032）防止同一对象重复填两条，但不保证配对正确。
- 该分支 `justification` 写明"既有适用通道已核验"（L2041），但证据粒度是通道级而非对象级。

## 3. 审计项 3：A 证 B 的可能性

### 3.1 测量分支：无 A 证 B

- 候选集合是 per-object 键集合：`descriptors.items()` 以 `object_id` 为键（L1919–1922）；过滤条件逐对象比较 `desc["category"]`（L1957）。
- 已占用对象通过 `used_object_ids` 排除（L1957）；不存在把对象 A 的测量结果写进对象 B 绑定记录的代码路径。

### 3.2 通道分支：有 A 证 B 风险

- 通道结论是报告级全局布尔/状态（L1930–1938），无 per-object 键；
- 扫配把全局结论背书给集合内**每一个**未占用对象（L2031–2038）；
- 若集合内某对象实际未被通道覆盖，它仍随条目被判 `bound`，即"通道对 A 的结论被用来为 B 作证"。

**明确判断：A 证 B —— 有，位置在通道通过分支 L2030–2042；测量分支（L1955–1980）无此问题。**

## 4. 审计项 4：共享几何

### 4.1 身份门读取情况

- 身份主函数未读取 `topology.shared_geometries`；`_semantic_backend_binding` 返回的 `topology` 字段在身份主流程中未被消费。
- 共享 owners 声明的对账（声明 owners 缺失/不在台账 → 降级）位于数量对账函数（L1494–1514），属于既有数量门职责。

### 4.2 证据取值

- 描述子按各对象自身 refs 与活动几何交集取证据（L1706–1708）；共享同一几何的两个 owners，各自描述子会列出相同几何 id，但类别判断仍基于归属 refs，不存在"借共享几何直接跳过身份证据"的分支。
- 风险边界：身份门不校验共享声明本身；若共享 owners 台账错误，身份门只能依赖绑定图校验结果（`validate_logical_object_graph`，L379–391），未通过则 `degraded` → `unverified`。

## 5. 审计项 5：未分类处理

### 5.1 池判断代码

- `pool_categories`：全部描述子类别（L1945）；`classified_pool`：剔除 `unclassified` 后的集合（L1946）。
- 可证不符条件：`provable_mismatch = bool(classified_pool) and category not in classified_pool`（L1991）。

### 5.2 结论

- **未分类未被当成"确定不匹配"**：`unclassified` 不进入 `classified_pool`，不会单独触发 `category_mismatch`；证据不足时落 `insufficient_evidence` → `unverified`（L2003–2013）。
- 残余粗粒度：池级判断不区分"缺失目标类别"与"混入异类"；只要池中存在任一已分类异类、且需求类别不在池中，即 `failed`（L1992–2002），即使还有未分类对象可能属于目标类别。
- 未分类/未占用对象进入 `unmatched_objects`（L2066–2071）；最终通过条件只看 `any_failed / any_unverified / unmatched_entries`（L2083–2090），**不把 `unmatched_objects` 计入阻断**——即多余或未分类对象不会在身份门内被单独判错，额外对象由数量门对账。

**明确判断：未分类被当确定不匹配 —— 无；但池级比对偏粗，且未分类对象本身不阻断身份通过。**

## 6. 审计项 6：三圆场景与数量结论压制

### 6.1 第三个对象去向

- 需求 2 圆、实际 3 圆：测量分支候选 3 ≥ 2，取前 2 个绑定；第三个未占用对象进入 `unmatched_objects`（L2066–2071），身份条目本身可 `passed`。

### 6.2 是否压制数量结论

- 数量报告独立挂载：L1227–1237 生成 `object_count_consistency_acceptance`；身份报告独立挂载：L1239–1250 生成 `object_identity_acceptance`。
- 两报告之间无字段互写；仅 `unknown_requirements` 合并进顶层列表（L1235–1237、L1248–1250），不覆盖对方状态。
- 汇总层按既有循环收集两个子报告，分别经 `_report_blocks_review` 判定阻断（L2189–2197）；身份报告不能改写数量报告的 `failed/extra_object` 结论。

**明确判断：身份覆盖数量 —— 无。** 额外对象的检出责任在数量门；身份门的 `unmatched_objects` 是观察项，不是数量裁决。

## 7. 审计项 7：零改动事实复核

- 解释器区间 diff 仅两个 hunk：挂载点追加（L1236）、计数函数之后追加身份函数（L1604 起）；**代码删除行为 0**（仅 diff 文件头）。
- blob 比对 `ee57143` ↔ `094d2f7`：

  | 模块 | 结论 |
  |---|---|
  | 候选状态 `cad_candidate_state.py` | SAME |
  | Plan v1 `agent_plan_models.py` | SAME |
  | 拓扑 `logical_topology.py` | SAME |
  | 执行器 `cad_construction.py` | SAME |
  | 几何适配器 `tooling.py` | SAME |
  | 语义分发 `cad_semantic_dispatch.py` | SAME |

- 数量对账函数体 `_logical_object_count_consistency`（L1306 起）未被改动；库存三态、`logical_object_count`、归属展开与共享 owners 对账保持基线行为。

## 8. 三类问题明确判断

| 问题 | 有/无 | 具体位置与说明 |
|---|---|---|
| A 证 B | **有（仅限通道分支）** | L2030–2042：全局通道 `passed` 后整体扫配未占用对象，无 per-object 通道证据键、无复核对；测量分支 L1955–1980 逐对象比对，无此问题 |
| 未分类被当确定不匹配 | **无** | L1946 已剔除 `unclassified`；L1991 可证不符只看 `classified_pool`；未分类走 `insufficient_evidence` 降级。残留：池级异类即 `failed` 的粗粒度口径（L1991–2002） |
| 身份覆盖数量 | **无** | 数量/身份两报告独立挂载（L1227–1250），无字段互写；汇总分别阻断（L2189–2197）；额外对象由数量门检出 |

## 9. 边界与未实测声明

- 未端到端执行计划装配与候选门禁；通道分支扫配、池级比对的实际触发面基于静态走读。
- 未跑回归用例、未调用真实模型；探针脚本为非生产材料，未被生产代码导入。
- 身份门不校验共享 owners 声明，也不检测额外对象；这两项归属既有数量门，本轮未改其逻辑。
- 工作树无已跟踪改动；本报告为新增只读评审材料。
