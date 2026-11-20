# R-IDENTITY-1 修正提交只读复核：三类问题消除情况（B 方）

- 性质：只读复核；未改代码、未建分支/提交、零模型、零网络。
- 复核对象：分支 `r-identity1`，HEAD `e08c168`；增量区间 `094d2f7..e08c168`。
- 增量构成：生产仅解释器一个文件（+180/−53 内身份段重写）；探针脚本与探针 JSON 为非生产材料。
- 结论以代码走读 + blob diff 为准；未端到端复现装配链路（见第 9 节）。

## 0. 结论速览

| 复核项 | 结论 |
|---|---|
| 1. A 证 B 是否消除 | **测量分支：已消除；通道通过分支：已改为 per-object 覆盖，批量扫配路径已删除**。残留：通道 `failed` 仍为全局结论背书；个别通道通过回传缺对象级几何 id 时只能降级 `unverified`（保守，不产生假通过） |
| 2. 追溯链 | `bindings` 逐对象带 `object_id` + 当前 `geometry_ids` + 证据等级 + 测量细节；条目级 `geometry_ids` 与 bindings 同源一致；几何 id 全部来自本次执行归属活动几何 |
| 3. 未分类三态 | `matches/others/unknowns` 划分正确；存在 `unknowns` 先落 `unverified`；仅"无未知 + 其余均为已分类异类"才 `failed`；未知对象不再被静默通过 |
| 4. 共享几何 | 身份门仍不读共享声明；各对象按自身 refs 取证据，无借共享跳过身份证据的路径；共享 owners 一致性仍由数量门负责 |
| 5. 三圆/数量独立 | 第三对象进 `unmatched_objects`；身份报告不压制数量 `failed/extra_object`；两报告独立挂载、无字段互写 |
| 6. 数量/公共面 | 数量函数体、Plan v1、候选门禁、执行器、拓扑、tooling、语义分发、结构契约、投影/语义验收模块 blob 与 `094d2f7` SAME；改动只落在解释器身份辅助段 |
| 7. 新增副作用 | 存在保守降级面：部分语义通道通过回传未带几何 id，对象级覆盖集合为空时合法对象会被降为 `unverified`；不构成假通过，但可能扩大复核面 |

## 1. 复核项 1：A 证 B 是否消除

### 1.1 通道覆盖集合改为对象级

- 新增 `channel_geometry_ids`：从既有通道报告的 `checks[*].geometry_ids` 与 `object_acceptance[*].target_ref.geometry_ids` 收集（解释器 L1948–1959），均为通道已核验几何 id。
- 通过分支改为 `backed` 过滤：未占用对象中，仅当描述子自身 `geometry_ids` 与通道几何 id 集合相交才可绑定（L2081–2085）；不再存在"通道 passed → 全部未占用对象扫配"的旧路径（旧扫配代码已在增量中删除）。
- 覆盖不足时落 `channel_partial_coverage` → `unverified`，并列明 `covered_object_ids` / `uncovered_object_ids`（L2103–2121）；未覆盖对象不建立绑定。

### 1.2 残留观察

- 通道 `failed` 分支（L2122–2137）仍以报告级全局失败结论为准，仅回列相交对象；该路径是失败裁决而非通过背书，不构成 A 证 B 假通过。
- 覆盖集合收集时未按 `object_acceptance` 条目自身状态过滤；当前前提是报告 `passed` 时其条目均为已核验，若后续出现"报告 passed 但条目含 unresolved"的混合回传，需再按条目状态过滤。
- 若通道通过回传未带几何 id（见第 7 节），`backed` 为空 → 降级 `unverified`；方向保守，不会把未覆盖对象判成已绑定。

**判断：A 证 B —— 批量扫配路径已消除；通过分支现按对象级几何相交背书。残留仅为通道失败分支的全局口径与缺 id 时的保守降级。**

## 2. 复核项 2：追溯链

### 2.1 绑定记录形态

- `_bindings` 辅助（L1961–1967）逐对象生成：`object_id`、`geometry_ids`（取自该对象描述子）、`evidence_grade`、`detail`（测量细节）。
- 测量分支与通道分支的 `matched_entries` 均写入 `bindings`，并附条目级 `geometry_ids` 列表（L2005–2007、L2095–2097），与 bindings 同源一致。
- 描述子 `geometry_ids` 来自归属 refs 与活动几何交集（描述子 L1706–1708），即本次执行结果内的几何；未引用本次执行之外的几何 id，也未读模型自报标签。

### 2.2 结论

- 条目 → `object_id` → 归属 `geometry_ids` → 证据等级/细节的链在报告内闭合；较上一版补齐了对象级几何证据回写。
- 残留：条目级 `geometry_ids` 为按对象分组的嵌套列表，未扁平化；不影响证据完整性，仅展示口径问题。

## 3. 复核项 3：未分类三态

### 3.1 划分与裁决顺序

- `matches`：未占用且类别与条目相同（L1976–1979）；
- `others`：未占用、非 matches、且类别已分类（L1980–1984）；
- `unknowns`：未占用且 `unclassified`（L1985–1988）。
- 裁决顺序：
  1. `matches ≥ quantity` → 绑定成功，余量记配对歧义（L1989–2017）；
  2. 否则存在 `unknowns` → `insufficient_evidence` → `unverified`，回列未知对象（L2018–2032）；
  3. 否则存在 `others` → 作用域完整、可证不符 → `category_mismatch` → `failed`（L2033–2049）；
  4. 其余 → 证据不足 `unverified`（L2050–2060）。

### 3.2 结论

- 未知对象优先于异类对象进入降级分支，未分类不会被当成确定不匹配；也不会被静默通过。
- `failed` 仅在"无未知对象、剩余全部为已分类异类"时成立，口径较上一版池级判断更严格、更诚实。
- 残留：`unknowns` 与 `others` 并存时整体落 `unverified`（保守），未区分"部分异类 + 部分未知"；不产生假失败。

## 4. 复核项 4：共享几何

- 身份主流程未读取 `topology.shared_geometries`；绑定图校验仍由 `_semantic_backend_binding` 完成（既有逻辑，未改）。
- 描述子按各对象自身 refs 取归属几何；共享同一几何的两个 owners 各自描述子独立生成，证据不互相借用。
- 仅共享声明、对象自身无归属活动几何时：描述子几何 id 为空，测量类别落 `unclassified` → 进入 `unknowns` 降级；通道分支因无相交几何 id 不能被 `backed`。不存在"借共享直接跳过身份证据"的分支。
- 共享 owners 声明一致性（未知 owner、台账归属）仍在数量对账函数内校验，本轮未改动其口径。

## 5. 复核项 5：三圆与数量结论独立性

- 第三对象（未占用）进入 `unmatched_objects`（L2150–2155），带测量类别与证据等级。
- 数量报告在 L1227–1237 独立挂载；身份报告在 L1239–1250 独立挂载；两者之间无字段互写，仅各自 `unknown_requirements` 合并进顶层列表。
- 汇总层分别收集、分别经既有 `_report_blocks_review` 判定；身份报告不能改写数量报告的 `failed/extra_object` 结论。

## 6. 复核项 6：数量与公共面零改动

- 增量 hunk 全部位于身份函数段（L1942 起）；解释器内删除行均为旧身份分支代码（旧池级判断、旧扫配分支），数量对账函数体无删除行。
- blob 比对 `094d2f7` ↔ `e08c168`：

  | 模块 | 结论 |
  |---|---|
  | 候选状态 `cad_candidate_state.py` | SAME |
  | Plan v1 `agent_plan_models.py` | SAME |
  | 拓扑 `logical_topology.py` | SAME |
  | 执行器 `cad_construction.py` | SAME |
  | 几何适配器 `tooling.py` | SAME |
  | 语义分发 `cad_semantic_dispatch.py` | SAME |
  | 结构契约 `cad_structure_contract.py` | SAME |
  | 投影验收 `cad_projection_acceptance.py` | SAME |
  | 语义验收 `cad_semantic_acceptance.py` | SAME |

- 新增逻辑只落在解释器身份辅助段，未新增专用分类器、未新增并行门禁。

## 7. 复核项 7：新增副作用与误阻断面

### 7.1 通道回传缺几何 id 导致保守降级

- 身份门对象级覆盖依赖通道回传的几何 id。既有语义验收中，部分 `passed` 回传的 `checks` 未带 `geometry_ids`，也未挂 `object_acceptance`：
  - 星形线通过回传（语义验收 L231–233）；
  - 正多边形/同心孔通过回传（L290–291）；
  - 心形线通过回传（L315–317）。
- 这些场景下 `channel_geometry_ids` 对相应对象为空，`backed` 不足 → `channel_partial_coverage` → `unverified`。方向是保守降级（不判假通过），但属于新增复核面：合法结构可能从"通道通过"变为"身份待复核"。
- 对照：投影通过回传带全部棱线 id（投影验收 L87–89）；心形轮廓路径经 `object_acceptance.target_ref.geometry_ids` 回传（语义验收 L402–404），这两类可被对象级覆盖命中。

### 7.2 其他观察

- 通道覆盖集合未按条目状态过滤（见 1.2）；当前报告 passed 前提下列表可信，后续混合回传需补过滤。
- 测量类别仍只覆盖圆/矩形/线；盒体与非测量类别继续走既有通道或降级，未扩大类别覆盖。

## 8. 明确判断

| 问题 | 判断 | 依据位置 |
|---|---|---|
| A 证 B 是否已消除 | **是（通过分支）**；旧批量扫配已删除，改为几何 id 相交的 per-object 背书（L2081–2102）。残留：通道失败分支仍为全局口径；缺 id 回传时保守降级 | L1948–1959、L2077–2121 |
| 未分类是否不再静默通过 | **是**；`unknowns` 优先落 `unverified`，`failed` 仅在无未知且全为已分类异类时成立（L2018–2049） | L1976–2049 |
| 身份是否覆盖数量 | **否**；两报告独立挂载、无互写，额外对象由数量门检出（L1227–1250、L2150–2155） | — |

## 9. 边界与未实测声明

- 未端到端执行计划装配与候选门禁；对象级覆盖命中情况基于通道回传字段结构走读，未跑真实样例。
- 未调用真实模型、未跑全量回归；探针脚本与探针 JSON 为非生产材料，未被生产代码导入。
- 本复核不覆盖 R-01/R-03、Stroke/Path、QE 议题；共享 owners 与额外对象的裁决口径归属既有数量门。
- 工作树无已跟踪改动；本报告为新增只读评审材料。
