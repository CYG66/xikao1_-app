# A 线 · 第五轮 FEATURE-CONTRACT 需求与结构化规划接口提案（设计稿，未实施）

> 状态：**纯接口提案**。本轮未改公共 Schema、未改 `backend/app` 生产代码、未调用任何模型、未联网；`real_model_calls=0`。
> 起点：第四轮根因报告 `A_第四轮A9规划根因分析报告.md`（commit `fafab4b`），结论沿用，不重跑 A9。
> 配套机器可读规格：`evaluations/v1/proposals/feature_contract_fields.v1-draft.json`（草案，**未接入**生产 schema）。
> 命名约定：本轮 **M2 = 结构重规划（structural replan）**，与"机械折角 M1"无关，全文不混用。
> 边界：不为任一形状新增专用提示词、专用生成器或专用控制点补丁；五类特征均为通用几何类别。

---

## 0. 结论先行

1. **五类通用特征**（边界极值、尖点、凹口、对称、连续性）按同一套字段落库：意图 + 参数 + 来源追溯 + 后端生成的验收条件；每一类都能由后端在已采样几何上独立测量判定，不依赖模型自证。
2. **来源类型互斥必填**：`user_explicit` / `semantic_derived`，不许留空、不许写"未知"；两者都必须带来源引用、原文证据与推导依据；空引用判不通过。
3. **验收条件由后端生成**：模型只提交特征意图与参数，不提交阈值、期望值或通过判据；防伪造/删除/放宽走机制层（严格模型禁未知字段、后端重算条件、证据重建指纹、复用 H3 来源授权）。
4. **失败分类按通用特征类型映射**到四类修复级别；边界特征缺失与整体拓扑错误才置 `requires_structural_replan`（M2），参数与连接错误走局部修复。
5. **schema 必要性结论：v1 暂不进执行器断言联合类型与约束求解器联合类型**。五类在当前阶段是验收测量对象，不是求解器输入关系；先落在验收层 sidecar，待出现第二个执行器消费方再评估提升。
6. 残缺项不遮掩：连续性在当前 schema 下只能部分表达，对称与尖点测量原语尚缺；降级行为见 §8。

---

## 1. 背景与上一轮结论衔接

第四轮已查证（详见 `fafab4b` 报告 §1、§3、§4）：

- L1 需求账本模式表只有数量/尺寸/位置/朝向/连接/单位，无对称、无极值/尖点/凹口类别；L2 契约只产标量尺寸事实；L3 语义模式只产自由文本指令；L5 计划 schema 的断言/约束联合类型无处承载这些特征。
- 后端检测生效且判定正确，但规划期没有可对照的可校验约束；第二轮修复上下文有诊断布尔值，缺结构规格与分类标记。

本轮提案不重复诊断，只回答接口应当长什么样、哪些先做、哪些暂缓。

---

## 2. 五类通用特征字段设计

### 2.1 公共信封（五类共用）

| 字段 | 类型 | 语义与约束 | 复用现状 |
|---|---|---|---|
| `feature_id` | string | 计划内唯一，1–64 字符 | 复用 `assertion_id` / `constraint_id` 唯一性口径（`cad_plan_references.py:12-20`） |
| `feature_class` | enum | `boundary_extremum` / `cusp` / `notch` / `mirror_symmetry` / `continuity` | 新建类别枚举，不绑定形状名 |
| `target_ref` | string | 必须解析到已存在的步骤输出引用 | 复用现有 `target_ref` 引用校验（`cad_plan_references.py:31-39`） |
| `reference_ref` | string \| null | 成对范围特征（如两段间连续性）的第二目标 | 复用 `reference_ref` 口径，默认 null |
| `provenance` | object | 来源追溯块，见 §3 | 复用 H3 来源索引与校验路径 |
| `parameters` | object | 类内意图与参数；**不含**阈值/期望值 | 模型提交物边界见 §4 |
| `acceptance_condition` | object | 后端验收时生成；模型载荷中不存在 | 见 §4 |

### 2.2 各类参数、测量量与验收口径

| 类别 | 声明参数（模型提交） | 后端测量量 | 归一化 / 量纲 | 容差来源（既有族，不为本提案新设阈值） |
|---|---|---|---|---|
| **边界极值** `boundary_extremum` | `direction` ∈ {-x,+x,-y,+y}；`extremum_kind` ∈ {local_min, local_max}；`location_axis` ∈ {none, vertical_center, horizontal_center} | 方向极值存在性；极值归一化坐标；偏离中心轴距离 | 位置按实测外接框独立归一化到 [0,1]；距离按计划单位 | 归一化位置带复用现有特征检测带宽；轴向距离复用 `center_distance` 默认 0.001 距离族（`cad_constraint_solver.py:44,77`） |
| **尖点** `cusp` | `parent_ref`（关联极值/连接点）；`cusp_type=sharp_turning_point`；`continuity_required=C0` | 两侧相邻段弦线切线夹角；G1 是否连续；曲率符号变化（可空） | 角度单位度；位置归一化 [0,1] | 切线角度复用既有切线容差族（`tangent_tolerance_deg`；平行/垂直角度容差 `cad_constraint_solver.py:59,64`）；弦线夹角辅助函数 `cad_topology_safety.py:_chord_angle_deg`；连续级别沿用现有连接意图词表 smooth / intentional_cusp / intentional_corner（`cad_construction.py:262`） |
| **凹口** `notch` | `opening_direction` ∈ {-x,+x,-y,+y}；`position_axis` ∈ {none, vertical_center, horizontal_center} | 内凹极值存在性；谷值归一化坐标；两侧是否各有一个外凸极值；轴向偏离 | 归一化 [0,1] | 同边界极值；不新设形状专用阈值 |
| **对称** `mirror_symmetry` | `axis` ∈ {x,y}；`scope` ∈ {whole_outline, between_targets}；`reference_ref`（成对范围时必填） | 镜像对应点对最大残差、平均残差；对应方式 | 距离按计划单位 | 点对距离复用 `center_distance` 0.001 距离族；对应方式由后端按几何类型选择（最近点 / 参数对应） |
| **连续性** `continuity` | `level` ∈ {G0_position, G1_tangent, G2_curvature}；`scope` ∈ {segment_pair, whole_outline}；`reference_ref`（段对时必填） | 端点位置间隙；切线夹角失配；曲率不连续（可空） | 距离按计划单位；角度度 | 复用现有连接/连续性检查与容差字段；残缺与降级见 §8 |

### 2.2.1 三性自检口径

- **可测量**：每类都写清测量量与归一化/量纲（上表第三、四列）；测量在后端已采样轮廓点序列上进行（参数曲线采样 `cad_parametric.sample_curve` → 多段线顶点），不读模型自报分数。
- **可追溯**：每个特征挂 §3 的 provenance 块，引用可回查到账本/契约条目与原文片段。
- **可验收**：后端按特征类型生成验收条件并独立判定；模型不提交通过判据。

---

## 3. 来源追溯：`user_explicit` 与 `semantic_derived`

### 3.1 字段方案

`provenance` 块（五类必填）：

| 字段 | 取值 / 规则 |
|---|---|
| `origin` | 枚举 `user_explicit` / `semantic_derived`；**互斥、必填、禁空、禁 `unknown`** |
| `source_requirement_refs` | 指向需求账本/契约条目的引用列表，≤20；**非空**；必须解析到当前不可变来源索引中的有效条目 |
| `evidence_text` | 从不可变原文逐字抄录的用户原话或抽取片段；不得由模型改写。派生特征填**触发词所在从句**，不填派生出来的特征名 |
| `basis` | 两类必填：`rule_id` / `rule_version` / `note`。`user_explicit` 记命中的显式词法模式；`semantic_derived` 记所应用的形状语义规则。写清从原文到该特征用了哪条规则 |
| `derivation` | 仅 `semantic_derived` 必填：`input_refs` + `inference_steps`（从触发从句到派生特征的有序推理步骤）；`user_explicit` 禁止带该块 |
| `authorization` | 枚举 `none` / `source_boundary`；沿用 `validate_junction_source_refs` 的授权结果词表 |

### 3.2 现有可复用机制（已查证）

- 来源索引构建与不可变绑定：`cad_requirement_contract.py:137-148`；跨轮继承与陈旧引用剔除：`178-197`。
- 来源引用校验（模型不能新建/升级来源）：`cad_requirement_contract.py:151-175`；尖点/折角意图要求 explicit 或 trusted_semantic 来源：`165-166`。
- 派生语义已有先例：`cad_semantic_acceptance.py:52、57` 已带 `origin: derived_semantic_requirement` 与 `source_evidence`；本提案把这一先例提升为结构化、可校验的字段。

### 3.3 伪装 / 伪造 / 自造验收条件的机制防护（不靠提示词喊话）

| 风险 | 机制层防护 |
|---|---|
| 把模型推测伪装成用户明确要求 | `origin` 互斥必填；派生条目必须带 `derivation`；下游报告/界面必须保留来源标签，派生条目不得在呈现层改写为用户明说；校验函数对"derived 条目引用的从句不含触发关键词"判无效 |
| 伪造来源引用 | 引用必须解析到当前不可变来源索引的有效条目；索引外引用、上一轮陈旧引用一律拒绝（复用继承/陈旧剔除路径）；模型不能新建或重命名来源 |
| 模型删除/篡改/自造验收条件 | ① 严格模型 `extra="forbid"`，模型载荷出现 `tolerance/expected_value/expected_band/pass_predicate/acceptance_condition/feature_score` 即拒绝；② 验收条件由后端按特征类型 + 契约事实重算，模型提交的阈值不被采纳；③ 验收证据后端重建并做指纹比对，模型编辑过的证据报告不能通过校验（复用 `cad_assertions.py:16-20、151-166` 的指纹口径）；④ H3 来源授权校验复用现有路径，引用不能引入契约中不存在的事实；⑤ 既有候选保存门槛与持久化条件不放宽 |

### 3.4 反例（什么写法算伪装，判不通过）

1. 形状名词触发的派生特征标 `user_explicit`，且无对应明确措辞从句。
2. 引用上一轮对话中已不在当前契约索引里的旧条目。
3. `evidence_text` 写的是派生特征名（如"底部尖点"），而原文从句里没有该措辞。
4. 派生尖点意图按 explicit 口径主张强制授权，绕过现有 `165-166` 的来源类型要求。
5. 模型在特征声明里夹带 `tolerance` 或 `expected_band`，试图自定通过线。

---

## 4. 后端独立生成验收条件的机制

### 4.1 提交边界

**模型可以提交**：`feature_class`、类内 `parameters`、`target_ref`、`reference_ref`、`provenance`（含来源引用与证据片段）。

**模型不能提交**：容差、期望值、期望带、通过判据、验收条件本体、特征得分；也不能提交"已通过/已满足"的自证结论。

### 4.2 生成流程（后端）

1. 按 `feature_class` 选定测量原语与归一化口径（§2.2 表）。
2. 从既有容差族选取容差（距离 / 角度 / 归一化带 / 采样误差），不从模型载荷取数。
3. 在已采样几何上测量，产出实测值与判定；验收条件与实测值一并写入后端证据记录，与模型载荷分离存储。
4. 证据重建指纹；候选保存仍走既有阻塞门槛，特征验收失败不豁免任何既有条件。

### 4.3 与现有验收器的挂载关系（基线 f89bf41 / A 分支现行代码）

| 职责 | 现有挂载点 | 提案方向 |
|---|---|---|
| 特征几何验收 | `cad_semantic_acceptance.verify_semantic_requirements`（75 起）；`cad_structure_contract.validate_structure` 爱心/多边形分支 | 硬编码形状分支退化为通用测量原语的配置实例；通用条件由新验收模块生成 |
| 计划引用校验 | `cad_plan_references.plan_reference_errors`（5-51） | 新成员沿用 `getattr` 通用遍历，无需特判 |
| 约束求解 | `cad_constraint_solver.solve_geometric_constraints`（117 起） | v1 不接新成员；对称/极值不作为求解输入 |

---

## 5. 失败 → `requires_structural_replan` 通用映射

### 5.1 分类函数签名（提案）

```text
classify_feature_failure(details: dict[str, Any]) -> FeatureFailureClass
输入字段：
  details.feature_class        # 五类枚举之一
  details.failure_subtype       # 失败子类（参数 / 连接 / 边界特征 / 整体拓扑）
  details.measured             # 后端实测值与残差
  details.geometry_scope        # single_outline | multi_part | component
  既有 error code              # 兼容现有 recovery_category 口径
输出：
  {
    "repair_class": "parameter_repair" | "connection_repair" | "feature_replan" | "topology_replan",
    "requires_structural_replan": bool,
    "reason": str
  }
```

### 5.2 映射表（按特征类型与范围，不按失败字符串）

| 修复级别 | `requires_structural_replan` | 触发情形 | 通用推导依据 |
|---|---|---|---|
| `parameter_repair` | false | 标量参数、区间、比例、偏移错误；特征集合与连接关系仍完整 | 失败只涉及标量取值，原计划拓扑与特征清单可保留，局部改参数即可 |
| `connection_repair` | false | 两段之间连续性/连接关系失败 | 局部成对关系错误，整体特征清单不变 |
| `feature_replan`（M2） | **true** | 边界极值 / 尖点 / 凹口 / 对称在实测几何中缺失或错位 | 计划未产出该边界元素；改标量参数无法新增一个拓扑元素（第四轮已验证：仅改区间不改变完整周期几何） |
| `topology_replan`（M2） | **true** | 组成数量、闭合性、自相交、包含关系、连通分量整体错误 | 特征清单本身或组成关系错误，需重排整体结构 |

### 5.3 为什么能从通用特征类型推导

修复级别由"失败对象是什么"决定：标量值 → 参数修复；成对关系 → 连接修复；单一边界元素 → 特征重规划；整体不变量 → 拓扑重规划。映射键取 `feature_class` 与 `geometry_scope`，**不取本地化失败文案**。现有先例：缺失数量/拓扑场景已置 `requires_structural_replan`（`cad_path_relation_acceptance.py:37、207`；`cad_semantic_acceptance.py:119、169`）；本轮只是把该判断从散点分支收敛为通用分类函数。

> 路由执行（选 replan 还是局部修复、上下文如何回挂）归 C 线独占；A 线只提案分类输出字段，不改编排。

---

## 6. Schema 必要性论证：进，还是不进联合类型

### 6.1 两条路径

- **路径甲（验收层 sidecar，不改公共 schema）**：特征意图作为解释器/证据记录上的附属清单，由独立验收模块测量；严格计划模型（`CadConstructionPlan`）不变。
- **路径乙（进执行器断言联合类型 / 约束求解器联合类型）**：`BoundaryExtremumAssertion` 进入 `ConstructionAssertion` union，`MirrorSymmetryConstraint` 进入 `ConstructionConstraint` union，由执行器图与求解器消费。

### 6.2 现状事实（已查证）

- 现有求解器只处理二元几何关系：同心、平行、垂直、等半径、等尺寸、中心距离（`cad_constraint_solver.py:53-88`）；对称在当前代码中只是编辑操作（`cad_composition_addition.py`），不是可解约束。
- 极值、尖点、凹口是**验收测量结果**，不是求解器输入；现有断言也由验收解释器核对，不由执行器图求解。
- 计划模型为严格模型：`extra="forbid"` + 判别联合；计划经 `CadConstructionPlan.model_validate` 重新校验（`cad_construction.py:632、1321`）；计划 JSON schema 直接导出给模型提示词（`cad_construction.py:847-849`）。

### 6.3 进入 schema 的收益与代价

| 维度 | 收益 | 代价 / 风险 |
|---|---|---|
| 单一事实源 | 特征声明与计划同构，回放/候选可见 | 严格模型与判别联合下，旧载荷遇新 `kind` 可能校验失败 |
| 引用校验 | 复用 `plan_reference_errors` 通用遍历 | 无新增校验代码，但联合类型面扩大 |
| 序列化 | 计划 JSON 一处携带 | `construction_plan_json_schema` 导出面扩大，模型提示词与 Mock 夹具需同步 |
| 历史数据 | — | 已持久化候选/历史回放若按新严格模型重载，需要兼容性确认；新成员名称后续变更会触发迁移 |
| Mock 夹具 | — | 现有构造计划/求解器/解释器测试按既有断言与约束形状编写，联合类型变化会波及夹具 |
| 迁移成本 | 增量联合成员对读方向向后兼容 | 旧写方不能产出新成员；若后续提升，需评估旧计划回填与回放 |

### 6.4 结论

**v1 不进执行器断言联合类型，也不进约束求解器联合类型。** 五类当前是验收测量对象，没有第二个执行器消费方要求它们进入计划模型；先做验收层 sidecar 与通用测量原语。提升到公共联合类型的触发条件：

1. 出现求解器/执行器需要把特征声明作为输入消费的场景（例如按对称约束驱动几何生成）；
2. 某求解后端声明支持镜像类约束；
3. 验收层运行数据证明 sidecar 清单与计划不一致成为系统性问题。

满足任一条件后再单独立项评审联合类型扩展；本轮不为加字段而加字段。

---

## 7. 两个追溯样例（全链条可点开确认）

> 样例沿用第四轮冻结输入原文；特征走通用机制自然产出，未写任何形状专用分支。当前代码尚未实现本提案，样例描述的是**目标接口形态**，标注为提案设计，不冒充现状行为。

### 7.1 样例 A：`user_explicit` —— 左右对称

| 环节 | 内容 |
|---|---|
| 原文 | "生成一个**左右对称**、平滑闭合的爱心，中心在(2,3)，宽4米高4米" |
| 证据项（账本目标形态） | 新保守词类 `symmetry` 抽取：`evidence.text="左右对称"`，`clause="左右对称、平滑闭合的爱心"`，`requirement_id=req-sym-1` |
| 字段 | `feature_class=mirror_symmetry`；`parameters={axis:"y", scope:"whole_outline"}`；`origin=user_explicit`；`source_requirement_refs=["req-sym-1"]`；`evidence_text="左右对称"`；`basis={rule_id:"lexical_symmetry.v1", rule_version:1, note:"原文从句直接命中对称词法模式，无需语义推导"}`；无 `derivation` 块 |
| 后端生成的验收条件 | 关于 y 轴镜像对应点对最大/平均残差 ≤ 既有距离容差（`center_distance` 0.001，按计划单位缩放）；在后端采样轮廓上测量，模型不提交容差 |
| 授权校验 | 引用解析到当前索引有效条目；原文从句含对称关键词，H3 校验通过（复用 `validate_junction_source_refs` 路径） |

### 7.2 样例 B：`semantic_derived` —— 底部方向极值尖点

| 环节 | 内容 |
|---|---|
| 原文 / 语义触发 | 原文形状名词"**爱心**"；未出现"尖点/底部极值"措辞 |
| 推导规则 | `basis={rule_id:"shape_outline_features.v1", rule_version:1, note:"形状名词触发通用轮廓特征规则"}`；`derivation={input_refs:["req-noun-1"], inference_steps:["识别形状名词","按规则展开双侧外凸极值、顶部凹口、底部 -y 方向中心极值尖点","特征词来自规则，不来自原文"]}` |
| 字段 | 本条目 `feature_class=boundary_extremum`；`parameters={direction:"-y", extremum_kind:"local_min", location_axis:"vertical_center"}`；`origin=semantic_derived`；`source_requirement_refs=["req-noun-1"]`；`evidence_text="爱心"`（触发词从句，非特征名）；`basis` 与 `derivation` 如上。"是否为尖点"由关联的同级 `cusp` 特征承担（`parent_ref` 指向本极值条目），不在极值条目内混入切线判定 |
| 后端生成的验收条件 | 在 -y 方向归一化边界带内、垂直中心轴上检测局部极值；尖点子类用两侧切线夹角判定；位置带与角度容差分别复用既有归一化带宽与切线容差族；后端独立判定 |
| 标注义务 | 该特征在任何报告/界面标注为**系统推导，不是用户明说**；不得改写为"用户要求底部尖点"；派生尖点的授权边界按 §3.4 第 4 条处理 |

---

## 8. 残缺项与降级行为（不虚报覆盖面）

| 类别 | 当前 schema 表达状态 | 残缺项 | 降级行为 |
|---|---|---|---|
| 连续性 `continuity` | **部分可表达** | ① 整轮廓 G1/G2 连续性无现有断言/约束成员；② 参数曲线步骤无连接约束字段；③ G2 曲率在现有验收套件中无可复用曲率估计器 | 无法挂到当前步骤类型的连续性声明记 `not_applicable_to_current_op`，既有连接检查仍是阻塞门槛，不给静默通过；G2 缺估计器时证据记 `null` + `review_required`，不记 `verified` |
| 对称 `mirror_symmetry` | 仅验收层可测 | ① 无求解器成员把对称作用于计划；② 自由轮廓对应点匹配依赖最近点，任意曲线的参数对应未建立 | 只做验收层残差测量，不承诺求解调整；对应关系模糊时判 `review_required`，不判 `verified` |
| 尖点 `cusp` | 仅验收层可测 | ① 单条闭合参数轮廓的尖点检测当前靠位置带宽，缺专用切线/转折原语；② 曲率符号变化为可选项，无估计器时不可用 | 缺切线估计器时回退现有位置带宽证据，角度测量记 `null`；带宽命中不升级为已验证尖点 |
| 边界极值 / 凹口 | 验收层可测，schema 无字段 | 同 §6：v1 不落计划模型联合类型 | 以 sidecar 清单 + 后端验收存在；计划 JSON 内不可见，回放时以证据记录为准 |

---

## 9. 兼容性、迁移与回滚

### 9.1 兼容性影响（v1 验收层方案）

- **既有计划**：无结构变化；特征清单为可选 sidecar，缺省为空列表，旧计划照常通过既有校验。
- **历史候选 / 回放**：不按新严格成员重载；现有回放夹具不受 schema 形状影响。
- **Mock 夹具**：不改动既有断言/约束形状；新增测量原语与分类函数配独立单测。
- **提示词面**：v1 不扩大 `construction_plan_json_schema` 导出面。

### 9.2 迁移方案

- v1 无数据迁移：sidecar 清单只在新解释流程产出，不回填历史候选。
- 若后续提升到联合类型（§6.4 触发条件满足后）：增量加联合成员；读方向向后兼容；旧写方不能产出新成员；旧持久化计划保持可读；届时再评估回放夹具与历史候选校验口径。

### 9.3 回滚方案

- 验收层方案回滚：移除 sidecar 清单的生产者与消费方即可；无持久化 schema 变更需要撤销。
- 分类函数回滚：`repair_class` 缺省回退现有 `recovery_category` 口径；`requires_structural_replan` 缺省 `false`，恢复现有局部修复路由。

---

## 10. 最小实施范围（提案预估，未实施）

| 序号 | 文件 / 模块 | 函数 / 位置 | 改动性质 | 预估面 |
|---|---|---|---|---|
| 1 | `cad_requirement_ledger.py` | `evidence_items`（90-125） | 增量保守词类：对称 / 尖点 / 凹口 / 极值关键词；只抽取不推断 | 小，纯增量模式表 |
| 2 | `cad_requirement_contract.py` | 契约特征清单；新增来源追溯校验（仿 `validate_junction_source_refs` 151-175）；复用索引构建 137-148 与继承 178-197 | 增量字段与校验函数 | 中，不改既有事实抽取 |
| 3 | `cad_semantic_acceptance.py` | `semantic_requirements`（37-59） | 自由文本指令旁产出结构化特征意图；指令文本保留为回退 | 小到中 |
| 4 | 新模块 `cad_feature_acceptance.py`（提案名） | 测量原语、验收条件生成器、`classify_feature_failure` | 新建；纯验收层 | 约 300–500 行，含独立单测 |
| 5 | `cad_construction_interpreter.py` | 解释结果挂接 sidecar 清单；失败 details 附带特征分类 | 增量挂接，不改既有步骤模型 | 小 |
| 6 | `cad_generation_recovery.py`（消费侧，路由归 C） | 读取 `repair_class` 选择路由；A 只提供分类输出口径 | 接口对接，编排不改 | 小，跨线评审 |

**明确不在 v1 范围**：不改 `ConstructionAssertion` / `ConstructionConstraint` 联合类型；不进求解器；不增 `max_repairs`；不放宽 H2/H3/H4、自相交、来源授权与候选保存条件；不为任一形状写专用生成器/控制点/提示词。

---

## 11. 评审必须拍板的三个决策点

1. **分层归属**：v1 特征意图走验收层 sidecar（推荐），还是直接进入公共断言/约束联合类型？后者需要同时接受 §6.3 的序列化、历史数据与夹具代价。
2. **测量口径**：对称与极值的对应点方式取最近点还是参数对应；容差全部取自既有距离/角度/归一化带族，还是允许为某类测量另立归一化口径。
3. **派生特征授权边界**：`semantic_derived` 特征能否参与 H3 强制授权（如尖点/连接意图的来源类型要求），还是仅作为验收提示、不触发约束级绑定。

---

## 12. 证据等级与待验证项

### 12.1 已查证（现行代码 + 第四轮记录）

- 现有断言/约束联合类型成员、严格模型与判别联合、计划校验与 schema 导出路径（§6.2 引用位置）。
- 来源索引构建/继承/校验路径与既有派生语义先例（§3.2）。
- 现有 `requires_structural_replan` 置位先例与恢复分类口径（§5.3）。
- 第四轮 A9 两轮计划、实测特征、反馈回挂与进度判定事实（`fafab4b` 报告）。

### 12.2 推断 / 设计判断

- 五类特征在验收层 sidecar 落库不影响既有计划兼容性；具体影响面待实施前以现有回放夹具实测确认。
- 容差复用清单在真实几何上的松紧程度未标定，属设计建议，不是验收结论。

### 12.3 待验证（交后续轮次 / B、C 交叉）

- 对称最近点残差与参数对应残差在自由轮廓上的可比性。
- 尖点切线夹角估计器在参数曲线采样点上的稳定性；G2 曲率估计器是否需要新建。
- 特征重规划路由与现有有界修复进度闸门（计划 JSON 不等 vs 几何等价）的对接口径（C 线）。
- 本提案单案例背景下形成，不外推为全部形状场景的覆盖结论。
