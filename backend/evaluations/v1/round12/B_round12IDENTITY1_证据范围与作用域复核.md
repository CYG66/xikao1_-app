# R-IDENTITY-1 一期落码只读复核：证据范围与作用域（B 方）

- 性质：只读复核；未改生产代码、未建分支/提交、零模型、零网络、未新增生成器。
- 复核区间：`ee57143..094d2f7`（`f12ff2a` 结构契约来源侧标识与溯源；`094d2f7` 解释器身份子报告）。
- 改动判断以 blob diff 为准；工作树相对 HEAD 无已跟踪改动。
- 复核方式：diff 通读 + 跨模块 blob 核对 + 静态走读；未端到端复现候选门禁（见第 11 节）。

## 0. 结论速览

| 复核项 | 结论 |
|---|---|
| 1. 变更范围 | 生产文件仅结构契约模块、解释器两个；执行器/拓扑/候选门禁/语义模块/Stroke/Path 未出现；探针脚本无生产导入 |
| 2. 数量逻辑零改动 | **通过**。计数对账函数体零删除行；库存三态、`logical_object_count`、数量提取未改，仅追加条目标识与溯源字段 |
| 3. 子报告挂载 | `object_identity_acceptance` 挂入既有 `source_acceptance`，经既有 `*_acceptance` 汇总循环进入裁决；阻断复用既有 `_report_blocks_review` 与既有阻断集；**未新增并行候选门禁** |
| 4. 证据等级诚实性 | 测量描述子只从归属活动几何取证据；未分类对象落 `insufficient`，不参与判 `failed`；实际对象 `label/object_type` 未被身份门读取；模板/通道证据复用既有已执行核验结论 |
| 5. 绑定依据 | 每条 `matched_entries` 带 `justification`；不存在仅凭 requirement_ref、顺序、名称相似或 `object_id` 合法即判绑定的路径 |
| 6. 防误伤 | 不因几何类型表达差异或多段判身份错误；同类互换只记集合配对歧义；同一 `object_id` 禁止重复填两条需求 |
| 7. 修复重绑定 | 无跨执行缓存；绑定与描述子每次按本次 `trial_result` 重建 |
| 8. 专用分类器边界 | 无形状专用验收器；类别测量为通用几何测量 + 容差（圆/矩形/线，矩形含四线闭合正交框） |
| 9. 公共契约 | Plan v1、候选状态、拓扑、执行器、几何适配器、语义分发 blob 与基线 SAME；既有公开签名零改动 |
| 10. 新误阻断面 | 身份子报告的 `failed/unverified` 经既有汇总循环进入复核阻断；残余为保守降级与两处粗粒度口径，详见第 10 节 |

**明确判断：不存在把模型标签当身份真值的路径。** 身份门测量与匹配全程未读取实际对象的 `label/object_type/role`；模型自报字段不参与类别判定与绑定成立。

## 1. 复核项 1：变更范围

`git diff --name-only ee57143..094d2f7`：

- 生产（`backend/app/`）：`cad_structure_contract.py`、`cad_construction_interpreter.py`。
- 非生产：round12 评审目录下 A/C 两侧探针脚本、探针输出 JSON、证据核验 MD。

生产导入核查：`backend/app/` 全目录 grep 无探针文件名/标识引用；执行器 `cad_construction.py`、拓扑 `logical_topology.py`、候选状态 `cad_candidate_state.py`、语义分发 `cad_semantic_dispatch.py`、几何适配器 `tooling.py` 均不在区间 diff。

## 2. 复核项 2：数量逻辑零改动

- 计数对账函数 `_logical_object_count_consistency`（解释器 L1306 起）：区间 diff 对该函数**无删除行**；新增身份函数在其之后追加（L1637 起），挂载点在调用方 L1239–1250。
- 库存三态：`none/complete/incomplete` 判定（结构契约 L266–271）、`logical_object_count` 仅 `complete` 求和否则 `None`（L272）保持原样。
- 数量提取：数量词解析、`single_object`、`ambiguous`、`attribute_feature/primitive_owned` 跳过逻辑未改；新增字段为 `requirement_id`、`expected_category`、`source_clause_index`、`evidence_valid`、`evidence_occurrences`。
- 结构契约侧 −2 行为条目记录字段替换（`evidence` 行展开为溯源字段），不改变计数语义。

## 3. 复核项 3：子报告挂载与阻断复用

- 挂载：解释器 L1239–1246 调用 `_object_identity_consistency`，结果写入 `source_acceptance['object_identity_acceptance']`（L1247）；其 `unknown_requirements` 合并进顶层 `source_acceptance.unknown_requirements`（L1248–1250），与既有数量报告同一挂接方式。
- 汇总：既有汇总循环按 `*_acceptance` 后缀收集子报告（L2190–2193），身份报告自然进入；阻断判定复用既有 `_report_blocks_review`（L1299–1303）与既有阻断集 `{failed, unverified, review_required, partial}`（L1296）。
- 未新增独立候选门禁、未新增并行通过/失败通道；身份报告状态由内部 `_finalize` 写入既有 schema 字段。

## 4. 复核项 4：证据等级诚实性

### 4.1 测量描述子（`_measured_object_descriptor`，L1704–1731）

- 归属口径：refs 取对象 `geometry_refs`（兼容 `geometry_ids`），仅保留 `active_ids` 内的活动几何（L1706–1708）；不读平面几何总数，不读模型标签。
- 类别判定顺序：
  1. 归属几何含 `circle` → `circle`，等级 `measured_geometry`；
  2. 既有 `_frame` 命中闭合矩形框 → `rectangle`；
  3. 线段构成闭合正交四边形（`_closed_loop_rectangle_frame`）→ `rectangle`；
  4. 全部为线段 → `line`；
  5. 其余 → `unclassified`，等级 `insufficient`。
- 未分类对象不参与 `failed` 判定：匹配段对 `unclassified` 不计入可证不符（L1987–2013），缺证据落 `insufficient_evidence`。

### 4.2 模型自报字段使用情况

- 身份门函数区间（L1637–2091）内未读取实际对象 `label`、`object_type`、`role`；grep 命中仅为注释与来源侧参考库名称（L1802，基线名词，非实际对象标签）。
- 类别来源：测量几何类别（L4.1）或既有已执行通道结论（投影/语义报告状态，L1927–1939）；不存在"模型填写模板名即成立"的路径。
- 通道证据：`_channel_verdict` 只复用既有 `projection_acceptance` / `semantic_acceptance` 的已核验状态，不重跑模型、不读模型自报模板名。

### 4.3 溯源校验（结构契约 L207–214）

- `evidence_valid`：记录区间切片必须等于捕获短语；漂移则 `evidence_mismatch` → 计入 `ambiguous` → `incomplete`，不在漂移位置上建立绑定依据。

## 5. 复核项 5：绑定依据

- 每条 `matched_entries` 均带 `justification`：测量类别匹配（L1964–1968）或既有通道核验（L2041），并记录 `object_ids`、`evidence`、`evidence_grade`。
- 测量分支候选集要求 `desc.category == entry.category` 且对象未被占用（L1955–1958）；不存在仅凭 `requirement_id`、计划顺序、名称子串相似或 `object_id` 合法即判 `bound` 的分支。
- 基线条目来源仅限既有结构化通道：库存条目、legacy 组成 `counts/names`、参考库组件（L1748–1812）；模型自报、计划步骤顺序、平面几何实例数不作为基线。

## 6. 复核项 6：防误伤规则

| 规则 | 实现位置 | 结论 |
|---|---|---|
| 不因几何类型表达差异判错 | 四线闭合正交框同样归 `rectangle`（L1720–1724）；未分类只记证据不足 | 通过 |
| 多段表达不增/不错误判 | 描述子按对象归属 refs 折叠，段数不进入类别与绑定判定 | 通过 |
| 同类互换只记配对歧义 | 候选数 > 需求数时记 `ambiguous_bindings`，说明集合匹配成立、个体顺序不唯一，不额外阻断（L1981–1986） | 通过 |
| 同一对象禁止填两条需求 | `used_object_ids` 占用集合，已绑定对象从后续候选排除（L1963、L2032、L2070） | 通过 |
| 可证不符才 `failed` | `provable_mismatch` 要求存在已分类对象且类别集合不含需求类别（L1991）；纯未分类不判错 | 通过 |

## 7. 复核项 7：修复重绑定

- 绑定来自 `_semantic_backend_binding(trial_result)`（L1846），该函数每次按本次结果重跑图校验与归属核查（L345–420），对象台账深拷贝返回；无模块级跨执行缓存。
- 描述子字典在函数内按本次对象清单重建（L1919–1922）；条目与候选占用集均为本次调用局部状态。
- 未发现跨执行复用旧绑定、旧类别或旧候选的路径。

## 8. 复核项 8：专用分类器边界

- 新增测量辅助：`_identity_category_for_noun`（名词→类别映射，L1637–1644）、`_closed_loop_rectangle_frame`（端点邻接 + 正交 + 闭合四边形测量，L1647–1701）。
- 类别覆盖仅 `circle / rectangle / line`；`box_projection` 转既有投影通道，`named_subject / solid_entity` 落证据不足或三维缺口。
- 未新增立方体/五角星/齿形等形状专用验收器；矩形测量复用既有投影通道的端点邻接思路与既有 `_frame` 辅助，容差为几何测量容差，不引入专用形状规则。

## 9. 复核项 9：公共契约核对

blob 比对 `ee57143` ↔ `094d2f7`：

| 模块 | 结论 |
|---|---|
| `agent_plan_models.py`（Plan v1） | SAME |
| `cad_candidate_state.py`（候选门禁状态） | SAME |
| `logical_topology.py`（拓扑校验） | SAME |
| `cad_construction.py`（执行器） | SAME |
| `tooling.py`（几何适配器） | SAME |
| `cad_semantic_dispatch.py`（语义分发） | SAME |

既有公开函数签名未变；新增函数均为 `_` 前缀内部辅助；身份报告 schema `cad.object-identity-acceptance.v1` 为子报告内部结构，未改动 Plan v1 字段与候选门禁接口。

## 10. 复核项 10：新误阻断面与残余风险

### 10.1 新增阻断路径（经既有汇总循环）

- 身份门 `failed`：存在测量/通道可证不符；`unverified`：证据不足、对应未定、三维缺口、归属降级。两者经既有 `_report_blocks_review` 进入复核阻断，与既有子报告同口径。
- `incomplete` 库存与多主体弱信号沿用既有保守降级，不产生伪造类别结论（L1887–1906）。

### 10.2 残余观察（非越界，建议后续收敛）

1. **池级类别比对偏粗**：可证不符以全局 `classified_pool` 为准（L1945–1946、L1991）；当池中存在一个已分类异类、同时需求对象缺失时，条目记 `category_mismatch`，未区分"缺失"与"混入异类"。建议后续按条目候选集细化。
2. **通道通过分支整体扫配**：既有通道 `passed` 时，未占用对象整体计入该条目绑定（L2031–2032），未在该分支复做类别核对；多非测量条目共用通道结论时，存在过绑定可能。
3. **三维触发词偏宽**：来源含"三维/实体/可操作"即把非测量条目改标 `solid_entity`（L1854–1857）；后果仅为 `missing_3d_channel` 降级 `unverified`，不判 `failed`，但可能扩大复核面。
4. **参考库组件一律 `named_subject`**：无测量类别时落通道/证据不足；参考名称不作为类别真值。
5. **纯矩形/无线条基线入口**：无结构化身份条目时落 `not_checked`（L1896–1906），不新增拦截；四线矩形由通用闭合框测量识别，未被编译阶段拒绝（该阶段行为属既有执行链，本轮未改）。

## 11. 未实测与边界声明

- 未端到端执行计划装配与候选门禁；绑定、类别比对与阻断结论基于代码走读与 blob 核对，未实跑探针场景的生产链路。
- 未重跑全量回归；本轮无真实模型调用、无网络访问；工作树无已跟踪改动。
- 本复核不覆盖来源侧 A 与计划侧 C 的设计结论；Stroke/Path、R-01/R-03、QE 议题不在本轮范围。
