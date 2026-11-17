# A_P0 语义污染定位诊断报告（A 线 · 代码级定位 + 五问答案）

> 任务：定位 A1 / A9 / C10 / C26 四例中"爱心请求被误识别为大写字母 A"的**第一次错误分类层**；C26 作为**正向对照**，同时证明字母 A 规则在 C26 上正确触发。
> 本轮纪律：零模型调用、零联网、零费用；未重跑 A9；未改冻结语料、公共 Schema、`CadConstructionPlan v1` 与生产业务代码；未合并、未推送、未 amend。
> 代码快照：分支 `v1/a1-constraint-inheritance`，组合树基线 HEAD `f89bf41facfb7032cbb9647250cff6bbdcc6bbb7`。
> 探针产物：`evaluations/v1/probes/a_p0_four_cases_semantic_trace.json`；探针脚本：`evaluations/v1/probes/a_p0_semantic_pollution_probe.py`。
> 证据等级：**[已查证]** 代码 / 规则回放可复现；**[推断]** 由代码结构推出；**[待验证]** 证据不足，需 D/B 线或落盘记录交叉。
> 运行性质声明：本报告所有 `semantic_requirements` / `parameterize_design` / 账本结果均为**确定性规则回放**（纯函数调用，无模型、无网络），不是真实端到端运行；真实模型运行记录仅引用 D 工作树第四轮 A9 一次。

---

## 0. 一句话结论

**在当前后端代码快照上，三个爱心类文本（A1/A9/C10）在规则选类层均被判为爱心轮廓规则，未被误判为大写字母 A；字母 A 规则仅在含 `大写字母A` 关键词的 C26 上正确触发。后端规则链内未找到爱心 → 字母 A 的第一次错误分类层；若语料运行中确有"字母 A 验收"表现，模型侧标签 / 几何形态与未落盘中间态均属 `待验证`，不能归因到后端规则。回放中唯一被实测到的规则层重叠缺陷是 C19 `心形线（cardioid）` 被爱心子串规则先命中（详见 §2-Q3）。**

---

## 1. 四例并排总表（规则回放实测，来自探针 JSON）

输入逐字引用附件二语料，未改写。

| 案例 | 输入原文 | 期望语义 | 实测 `semantic_requirements()` | 参数化器形状 | 账本对象 | 有效事实（作用域） | Sidecar 影子绑定 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A1 | `生成一个闭合爱心轮廓，宽度4米，高度4米` | 爱心；不触发字母 A 验收 | `heart_outline_features` | `heart_outline`，宽 4.0 m × 高 4.0 m | 1：`闭合爱心轮廓` | width 4000 mm（跨度 11–15 `宽度4米`）、height 4000 mm（16–20 `高度4米`），`single_subject` / `effective` | `fc-A1-1` 有效，`explicit` / `mandatory`，绑定 `step-1:outline`，无错误 |
| A9 | `生成一个左右对称、平滑闭合的爱心，中心在(2,3)，宽4米高4米` | 爱心；不触发字母 A 验收 | `heart_outline_features` | `heart_outline`，宽 4.0 m × 高 4.0 m | 1：`左右对称、平滑闭合的爱心` | width 4000 mm（26–29 `宽4米`）、height 4000 mm（29–32 `高4米`），`single_subject` / `effective` | `fc-A9-1` 有效，`explicit` / `mandatory`，绑定 `step-1:outline`，无错误 |
| C10 | `生成一个爱心和一个五角星，爱心在左，五角星在右` | 爱心 + 五角星；不触发字母 A 验收 | `heart_outline_features` | `heart_outline`，尺寸缺失 | 2：`爱心`、`五角星` | 无事实（无尺寸句） | `fc-C10-multi` **无效**：`fc_evidence_missing` + `fc_multi_target_ambiguous`；无绑定记录 |
| C26（正向对照） | `生成一个大写字母A的轮廓，高3米宽2米` | 大写字母 A；**应**触发字母 A 验收 | `straight_capital_a` | `generic_2d_cad`，尺寸未提取（见 §2-Q3 注） | 1：`大写字母A的轮廓` | height 3000 mm（13–16 `高3米`）、width 2000 mm（16–19 `宽2米`），`single_subject` / `effective` | `fc-C26-1` 有效，`explicit` / `mandatory`，绑定 `step-1:outline`，无错误 |

**正向对照判定 [已查证]**：C26 是四例中唯一命中 `straight_capital_a` 的输入；字母 A 规则在 C26 上触发条件成立，规则本身未坏。三个爱心输入均不含 `大写字母\s*A` 正则词面（探针 `regex_matches.capital_a = null`），字母规则对它们不成立。

---

## 2. 五问答案（验收口径）

### Q1 第一次错误发生在哪里（模块 / 函数 / 代码行 + 实际执行行为）

**对 P0 四例：后端规则链内未定位到第一次错误层 [已查证]。** 逐层回放结果：

| 层 | 模块 / 函数 / 行号 | 实际执行行为 | 是否偏离 |
| --- | --- | --- | --- |
| L1 入口归一 | `cad_construction_interpreter.py:358` `interpret_construction_request` | `text = source_text.strip()`；`:361` 仅切去 `"\n后端试算反馈："` 之后的旧反馈；无大小写折叠、无截断、无前后缀拼接 | 否 |
| L2 case_id 注入 | `cad_construction_evaluation.py:89-96` 运行器；`agent_evaluation.py:78,90-94` | 传给解释器的只有 `case["command"]`；case id 仅进报告字段与 `evaluation:{case_id}` 存储键，不拼进消息 | 否 |
| L3 多轮 / 缓存 | `cad_construction_interpreter.py:395,417-419`；`agent_service.py:1102-1117`；`conversation_memory.py:98-102,145-146,320-329` | 语义标签每轮由当前累积文本重算；记忆按会话 id 隔离；无全局形状标签缓存 | 否 |
| L4 规则选类 | `cad_semantic_acceptance.py:37-59` `semantic_requirements` | 顺序首个命中即 `return`；A1/A9/C10 在 `:42-43` 命中爱心规则；C26 在 `:50-55` 命中字母 A 规则 | 否（四例取值与期望一致） |
| L5 选类判据 | `cad_semantic_acceptance.py:50` | 字母 A 判据为纯正则 `大写字母\s*A`（`re.I`）；不读宽高比、几何结构或包围盒 | 否（对 C26 成立，对三爱心不成立） |
| L6 账本 / 作用域 | `cad_requirement_contract.py`；`cad_source_acceptance.py:25-52` | 三单对象事实 `single_subject`；C10 两对象无事实；无整体尺寸错绑部件 | 否 |
| L7 特征绑定 | `cad_feature_contract.py:207-210,289-326` | 单对象唯一绑定；C10 多目标歧义拒绝、不出 Binding | 否 |
| L8 验收分派 | `cad_semantic_acceptance.py:199-225,253,275-319` | 按当前 `requirements[0]['kind']` 分派；爱心文本不进入字母 A 几何检查；规则不跨请求继承 | 否 |

**规则回放实测到的唯一代码级重叠缺陷 [已查证，非 P0 四例]**：C19 `生成一个心形线（cardioid），尖点朝下，最大宽度3米` 在 `:42` 被爱心子串正则 `爱心|心形` 先命中，返回 `heart_outline_features`；而验收层 `:173` 另有 `cardioid|心形线` 分支。即"子串关键词先命中即终局"在 `心形线` 上存在规则竞争，是否造成错误验收结论属 **[待验证]**（需几何回放 / D 线核对）。

**若语料运行确有字母 A 表现 [待验证]**：模型自身输出标签、对象命名或计划几何被后端读取的环节，本轮零模型调用无法复现；仓库内也无四例语料的运行原始响应可供回溯（见 §5、§7）。

### Q2 为什么发生（主因 / 次因分类 + 排除依据）

**分类结论：**

| 候选成因 | 判定 | 判别依据 |
| --- | --- | --- |
| 匹配范围过宽（子串关键词 + 首命中终局） | **次因 / 通用隐患 [已查证存在机制]** | `:42` 爱心正则用子串 `心形`，可命中 `心形线`；`:50` 字母规则纯关键词；函数体首个命中即返回，不返回候选集（`semantic_requirements` 全程 `return` 单列表）。该机制是否在 P0 四例上造成误判：否。 |
| 上下文 / 多轮污染 | **排除 [已查证]** | L3 实测：语义每轮重算；混合两轮文本回放 `heart_then_A`、`A_then_heart` 均按当前文本命中；记忆按会话 id 隔离；未发现持久化旧标签复用路径。 |
| 对象绑定错误 | **排除（四例）[已查证]** | L6/L7：A1/A9/C26 单对象 `single_subject`；C10 两对象无尺寸事实，Sidecar 多目标歧义被拒绝而非错绑。 |
| 验收规则跨请求继承错误 | **排除 [已查证]** | L8：验收 kind 来自当前请求 `semantics`；`agent_service.py:6870,6888-6897` 形状由当前消息重新参数化，未读取旧会话规则。 |
| 模型侧标签 / 几何形态 | **待验证 [unverified]** | 无本轮模型输出证据；不能据最终报错反推中间过程。 |

**主因口径**：对"爱心被误识别为大写 A"这一具体现象，现有证据不支持后端任一成因；在拿到模型原始响应前，主因**暂不归因**。已定位的通用隐患（子串过宽 + 首命中终局）是次因，证据来自 C19 回放，不代表 P0 四例根因。

### Q3 影响范围（候选语义类别与案例清单）

规则表覆盖的语义类别（`semantic_requirements:40-57`）：astroid 星形线、heart 爱心轮廓、nested 嵌套方框、regular polygon 正多边形、straight capital A 字母 A、triangle-roof house 房子。

| 语义类别 | 规则位置 | 语料候选案例 | 回放命中结果 | 状态 |
| --- | --- | --- | --- | --- |
| 爱心轮廓 `heart_outline_features` | `:42-43` | A1、A9、C10；B1/B2/B4/B7/B9/B12/B19（文修爱心，本轮未逐条回放） | A1/A9/C10 → `heart_outline_features` | 四例已证实；B 系列待验证 |
| 心形线 cardioid | 验收 `:173-198`；选类层无独立 kind | C19 `生成一个心形线（cardioid）…` | 选类回放 → `heart_outline_features`（子串 `心形` 先命中） | **重叠已证实；是否误验收待验证** |
| 字母 A `straight_capital_a` | `:50-55` | C26 | C26 → `straight_capital_a` | 正向对照已证实；语料内无第二例字母 |
| 星形线 `astroid_identity` | `:40-41` | C18 `生成一个星形线（内凹四角星）…` | C18 → `astroid_identity` | 已证实 |
| 房子 `triangle_roof_house` | `:56-57` | C16 `生成一个房子轮廓…屋顶是三角形…门` | C16 → `triangle_roof_house` | 已证实 |
| 嵌套方框 `nested_square_frames` | `:44` | C29 回字形；C15 圆环 | C29 → `nested_square_frames`；C15 → `[]` | C29 已证实；C15 规则未覆盖（非污染） |
| 正多边形 `regular_polygon` | `:46-47` | C5 正五边形、C13 正六边形、C32 六角螺母、C4 三角形 | C5/C32 → `regular_polygon`；C13/C4 → `[]` | 部分命中已证实；未命中属规则覆盖缺口，待验证是否应补 |
| 多对象守卫 | `:49` | C7 矩形+四角圆、C10 爱心+五角星、C11 波浪线等 | 守卫对象数 ≠1 或多对象关键词时返回 `[]` | 待验证（本轮仅回放 C10） |

**范围结论 [推断]**：首命中终局 + 子串匹配的隐患影响所有"同一文本含两个形状关键词"的案例；当前语料中实测重叠点为 C19。其余类别未见爱心 ↔ 字母 A 互相污染的回放证据。

### Q4 能否通用修复（不含任何图形专用分支）

方向（本轮不改生产，待主控批准）：

1. **规则返回候选集，而非首命中终局**：`semantic_requirements` 改为返回所有命中规则及匹配证据（规则 ID、版本、词面跨度），由下游按裁决顺序选主规则；消除"先写在前面的规则永久挡住后面规则"的顺序耦合。
2. **匹配锚定到 Contract 主体，不匹配拼接原始文本**：规则关键词必须落在 `requirement_contract` 抽出的 subject 别名内；出现在修饰语、括号注释或 follow-up 限定语里的关键词不单独定类。例如 `心形线` 应作为独立主体别名参与匹配，而不是被 `心形` 子串截取。
3. **对象锚点与基数校验**：规则携带期望对象基数；多对象文本（如 C10）不把单对象轮廓规则套到全图；与既有 `local_creation_objects` 计数口径统一（修复顿号 / 连词切分与守卫阈值不一致，见 §6.2）。
4. **版本化规则注册表 + 互斥优先级表**：每条规则带 ID / 版本 / 适用域；互斥类别（单轮廓 vs 字母笔画网络 vs 组合对象）按显式优先级裁决，证据写入 Sidecar；与第六轮 `cad_feature_contract.py` 的来源 / 版本授权机制对接。
5. **形状类别由账本主体推导，尺寸 / 中心继续走既有 Contract 事实**：不在规则层重新解析原始散文中的数值。

**为什么能从根本上避免互相污染**：污染的前提是"一段原始文本被单个子串规则独占解释"。上述机制把解释权拆成"账本主体 → 候选规则集 → 锚点 / 基数 / 优先级裁决"三层，任何关键词都需要在被声明的对象上落地才能定类；新增形状类别只需注册规则与适用域，不需要为某图形写专用分支或补丁。

### Q5 如何验证修复（正向 / 反向 / 回归 / 前后对照）

**正向案例（必须保持通过）：**

| 输入 | 预期修复后结果 | 当前回放基线 |
| --- | --- | --- |
| C26 `生成一个大写字母A的轮廓，高3米宽2米` | `straight_capital_a`；进入字母 A 结构验收（上部三角、双支脚、收拢斜笔） | 已证实命中 |

**反向案例（必须不触发字母 A）：**

| 输入 | 预期修复后结果 | 当前回放基线 |
| --- | --- | --- |
| A1 `生成一个闭合爱心轮廓，宽度4米，高度4米` | `heart_outline_features`；字母规则候选集为空 | 已证实 |
| A9 `生成一个左右对称、平滑闭合的爱心，中心在(2,3)，宽4米高4米` | `heart_outline_features`；字母规则候选集为空 | 已证实 |
| C10 `生成一个爱心和一个五角星，爱心在左，五角星在右` | 多对象裁决；不产生单对象爱心 / 字母 A 强制门禁；绑定歧义记 `unresolved` | 已证实爱心命中、Sidecar 歧义拒绝 |

**重叠修复专项回放：**

| 输入 | 预期修复后结果 | 当前回放基线 |
| --- | --- | --- |
| C19 `生成一个心形线（cardioid），尖点朝下，最大宽度3米` | 主体 `心形线 / cardioid` 独立成类，不被 `心形` 子串截为爱心轮廓 | 当前 → `heart_outline_features`（重叠已证实） |

**既有回归清单（修复后必须全绿，本轮未改动生产，基线 125 passed）：**

- `tests/test_cad_construction.py`（37）
- `tests/test_cad_construction_interpreter.py`（74）
- `tests/test_cad_generation_recovery.py`（14）
- 追加：`tests/test_cad_semantic_acceptance.py`、`tests/test_cad_requirement_contract.py`、`tests/test_cad_local_repair.py`、`tests/test_cad_feature_contract.py`

**修复前后同一输入对照实验设计：**

- 固定条件：同一批输入（四例 + C19 + 混合两轮 + 三对象）、同一上下文快照、同一账本、无模型调用；只改规则裁决函数一处。
- 记录项：每条规则候选集、命中词面跨度、选中主规则、对象基数、Contract 主体、最终验收 kind。
- 预期差异：四例主规则与当前基线**完全不变**（无行为回归）；C19 主规则由 `heart_outline_features` 变为 cardioid 对应类别；候选集从单条变为带证据的多条；字母 A 候选在三爱心输入上恒为空。
- 判定：若任一正向 / 反向案例主规则改变或字母候选出现在爱心输入上，修复驳回。

---

## 3. 八层逐层证据明细

### L1 输入改写 / 截断 / 归一

- `cad_construction_interpreter.py:358`：`text = source_text.strip()`；`:361` 切旧反馈段。
- 快照分支 `:367-380`：规则文本取不可变 `original_prompt`，模型输入保留完整快照。
- `cad_semantic_acceptance.py:39`：规则文本由 `source_texts` 拼接，未 lower。
- 全仓 `.lower()` 排查：`agent_service.py` 多处 `.lower()` 仅用于独立关键词分类副本；构造解释器入口 `:6344` 取 `message.strip()`，折叠文本不回流规则链。
- 探针 `entry_normalization`：`trim_only=false`、`lowercase_applied_to_rule_text=false`、`prefix_or_suffix_added=false`。

### L2 case_id 是否进入上下文

已排查位置：生产聊天入口、基准运行器 `cad_construction_evaluation.py:89-96`、参考案例 `agent_evaluation.py:78,90-94`、冻结快照 `p1.3e_dual_case_frozen.json`、注册表 `evaluations/v1/case_registry.json`、审计探针 `probes/d0_validate_assets.py:57-63`。

- 运行器只传 `case["command"]`；id 进报告 / 存储键。
- 基准案例 id 为语义 slug，非 `A1/A9/C10/C26` 前缀；三个基准 JSON 扫描无爱心 / 字母 A 条目。
- 注册表 A9 的 `case_id` 与 `original_input` 并列；`backend/app` 内无代码读取 `case_registry` / `original_input`（grep 零命中）。
- 冻结 A9 `prompt` 实测纯原文，`'A9' in prompt = False`；校验探针只做哈希比对，不拼 id。

### L3 多轮历史与跨会话缓存

- `cad_construction_interpreter.py:395` 累积 sources；`:398-399` 建账本；`:417-419` 每轮重算 `semantics`。
- `agent_service.py:1102-1117` followups 去重追加；`:1121-1132` 形状由当前 / 原始文本重新参数化。
- `conversation_memory.py:98-102,145-146,320-329` 按 `conversation_id` 键存取；评测会话 id `evaluation:{case_id}`。
- 静态表排查：`TOOL_REGISTRY` 为工具规格表，不含形状标签；`cad_project_candidates.py:173-184,857-867` 形状枚举与爱心生成器中无字母 A 生成器。
- 混合回放（探针 `mixed_turn_traces`）：先爱心后 A、先 A 后爱心均命中爱心；三对象切分为 `['爱心、一个五角星', '圆形']` 后命中爱心。

### L4 规则命中与跨度

规则顺序（`cad_semantic_acceptance.py:37-59`）：astroid `:40-41` → 爱心 `:42-43`（守卫对象数 ≤2）→ 嵌套 `:44` → 正多边形 `:46-47` → 守卫 `:49` → 字母 A `:50-55` → 房子 `:56-57`。

| 案例 | 爱心正则 `爱心|心形` | 字母正则 `大写字母\s*A`（`re.I`） |
| --- | --- | --- |
| A1 | 6–8 `爱心`，1 次 | 未命中 |
| A9 | 14–16 `爱心`，1 次 | 未命中 |
| C10 | 4–6 `爱心`，2 次 | 未命中 |
| C26 | 未命中 | 4–9 `大写字母A`，1 次 |

证据缺口 [已查证]：字母规则 `:52` 的 `source_evidence` 只存匹配文本、不存偏移；爱心分支 `:43` 未填 `source_evidence`。探针跨度为调用方用同一正则在原文现算。

### L5 选类判据宽窄

- `:50` 字母 A：纯关键词正则，不读宽高比、包围盒、线段夹角或顶点结构。
- 几何判据在验收侧 `:275-319`，仅对已归类 `straight_capital_a` 的几何执行：上部三角 `:290-294`、分离双支脚 `:312-317`、收拢斜笔 `:318-319`。
- 全仓未发现把几何组合（上宽下窄 / 双侧对称 + 顶部凹口）反推为字母 A 标签的文本规则；参数化器 `agent_skills.py:1761-1788` 无字母 A 分支，C26 落 `:1886-1887` 自由轮廓兜底。

### L6 账本事实 / 对象 / 作用域

- 对象切分：`cad_creation_intent.py:24-51`，顶层标点断句、`和|与|及` 拆对象、剥量词；无字母归一化。
- 作用域：`cad_source_acceptance.py:25-52`，非单对象 / 非 `single_subject` 按对象名匹配，匹配不上记 `unresolved`。
- 既有回归：`tests/test_cad_requirement_contract.py:29` `test_unscoped_and_nested_dimensions_never_become_global`；`tests/test_cad_local_repair.py:56` `test_unscoped_failure_does_not_claim_to_lock_parts`。
- 主体别名：`cad_requirement_contract.py:78` 仅剥 `大写|小写` 前缀与 `轮廓` 后缀，不改对象身份。

### L7 Sidecar 影子绑定

- A1/A9/C26：记录有效，`explicit` / `mandatory`，`source_refs=['user-1']` 解析进真实 `source_index`；Binding `cad.feature-binding.v1` → `step-1:outline`。
- C10：`fc_multi_target_ambiguous`（`cad_feature_contract.py:207-210`）+ `fc_evidence_missing`；`bindings=[]`。
- 测量字段当前全 `undetermined`，影子阶段不阻断 / 放行候选。

### L8 验收规则选择与继承

- 提示词注入：`cad_construction_interpreter.py:566-567`。
- Schema 收窄：`:1718-1725`，仅调 `steps.minItems`，不做生成器路由。
- 验收分派：`:199-225` 爱心检查；`:253` kind 分派；`:275` 起字母 A 检查；不含 `爱心|心形` 文本不进入 `:199`。
- 无跨请求继承：`agent_service.py:6870` 重新参数化；`:6888-6897` 兜底形状仅在推断为空且非抽象词时使用。

---

## 4. 错误传播链

```text
用户原文
  → source_texts 切分（cad_source_acceptance.py:16-22）
  → requirement_contract 账本 / 作用域（cad_requirement_contract.py）
  → semantic_requirements 规则选类（cad_semantic_acceptance.py:37-59）
  → semantics 注入模型提示词（cad_construction_interpreter.py:566-567）
  → schema minItems 收窄（:1718-1725）
  → 模型计划（本轮不调用）
  → 后端按 kind 分派几何验收（:199 爱心 / :275 字母 A）
```

透传环节：提示词注入与 schema 收窄不改变 kind；后端只在对应几何检查内失败，不反向改写文本 kind。Sidecar 影子链：真实账本 → 来源索引复用 → 声明校验 → 绑定（歧义拒绝）→ 影子测量（`undetermined`，不参与候选通过条件）。

**几何重叠提示 [推断，待 B 线验证]**：缺下方尖点、保留双侧上凸与中央凹口的轮廓，在形态上可能与"双斜笔 + 横笔上部三角"局部相似；文本规则不做此类几何猜测，该层面归属 B 线测量与验收分派核查。

---

## 5. 两条 A9 记录永久分开

| 维度 | 独立真实评测 A9（D 工作树，只读引用） | 70 例语料 A9（本快照规则回放） |
| --- | --- | --- |
| 记录性质 | 第四轮受控真实模型运行 | 手工测试清单条目；仓库内**无**该次运行记录 |
| 输入原文 | `生成一个左右对称、平滑闭合的爱心，中心在(2,3)，宽4米高4米` | 同左（附件二第 19 行） |
| 输入 SHA-256 | `af12df04393e1da42acd9eae6e590f81fa8c66a4720c546c9d292fef89707d5b` | 同左（注册表 `input_sha256` 一致） |
| 代码快照 / 哈希 | 组合树基线 `f89bf41facfb7032cbb9647250cff6bbdcc6bbb7`；规则文件 `cad_semantic_acceptance.py` SHA-256 前 16 位 `423ed2ff4d23d209`（与本快照一致） | 本工作树 `v1/a1-constraint-inheritance`；同一规则文件哈希 `423ed2ff…`（完整值见 §8） |
| 请求记录 | `round4/A9_case_record.json`、`round4/A9_raw_responses.jsonl`；2 次 `deepseek-flash` 请求（request_id `1df31f91…`、`6bda0ebb…`） | 无请求记录；注册表 `current_evidence_status=not_run_exact_replay`，`historical_plan_status=unavailable` |
| 运行环境 | 隔离评测进程，`deepseek-flash`（DeepSeek-V4.1-Flash-1017），peak 价；usage 输入 31554（命中 15872 / 未命中 15682）、输出 804；费用 0.005764632 USD | 纯函数规则回放，Python 3.11.18 / pytest 9.2.0 环境，无模型、无网络 |
| 语义规则版本 | 同快照规则文件；无独立版本号，以文件哈希 + 行区间标识 | 同左 |
| 结论 / 失败特征 | `failed`；后端 `center_notch / left_upper_lobe / right_upper_lobe = true`、`lower_tip=false`；失败检查 `heart_bilateral_lobes_notch_and_lower_tip`；类别 `model_plan_invalid`；未持久化候选 | 规则回放 `heart_outline_features`；**是否在某次语料运行中进入字母 A 验收：`unverified`** |
| 缺失证据 | — | 缺：运行日志、模型原始响应、最终验收 kind 与几何快照；无法确认"大写 A 语义验收错误"是否发生过 |

两条记录不得合并为一个失败案例，不得用一个根因互相解释：真实评测 A9 的问题是"爱心几何缺下方尖点"，语料 A9 的"字母 A"线索在本快照内无证据成立。

---

## 6. 候选通用观察（本轮不改生产）

### 6.1 首命中终局、规则结果无版本化来源标注

- 证据：`cad_semantic_acceptance.py:42-55`；规则结果不带规则 ID / 版本 / 跨度。
- 通用性：任意关键词规则表均有顺序耦合风险；对接第六轮 Sidecar 的来源可追溯与规则版本授权。
- 影响面：提示词注入、schema 收窄、几何验收分派全部依赖 `semantic_requirements` 输出。
- 回归范围：`test_cad_semantic_acceptance.py`、`test_cad_construction_interpreter.py`。
- 回滚点：Sidecar 影子模块可整模块摘除；公共 Schema 与既有门禁不受影响。

### 6.2 对象计数口径不一致

- 证据：`cad_creation_intent.py:50-51` 只按 `和|与|及` 拆（顿号不拆）；守卫 `cad_semantic_acceptance.py:42,49` 用对象数 ≤2 / ==1。
- 通用性：对象计数是所有多对象 / 组合规则的公共前置，属解析口径问题。
- 影响面：阵列、并排、左右布局等多对象案例；需先补顿号 / 逗号并列切分对照测试。
- 回滚点：切分函数为纯函数，可恢复旧拆分正则，守卫阈值不变。

### 6.3 自由轮廓尺寸未对齐账本（单列，与 A/heart 分类无关）

- 证据：探针 C26 账本已抽 height 3000 / width 2000 mm，参数化器仍 `dimensions={}`、`generic_2d_cad`；`agent_skills.py:1886-1887`。
- 通用性：参数化器与需求账本两套尺寸提取口径未对齐；不改变语义分类。
- 回归范围：矩形 / 圆 / 拱门等既有尺寸案例。
- 回滚点：参数化器独立纯函数，可回退旧提取路径；账本事实不改动。

### 6.4 本轮明确不做

不为任何图形新增专用生成器 / 控制点 / 提示词；不把 legacy 区域布尔升级为数学门禁；不放宽 H2/H3/H4、自相交、来源授权、候选保存条件，不增加 `max_repairs`；不改公共 Schema 与 `CadConstructionPlan v1`。

---

## 7. 不确定项清单（`unverified`）

| # | 事项 | 缺哪份证据 | 交叉方 |
| --- | --- | --- | --- |
| U1 | 模型自身输出标签 / 对象命名 / 计划几何是否被读成字母 A | 四例语料运行的原始响应与落盘计划；本轮零模型调用 | D 线历史响应 JSONL / 计划记录 |
| U2 | 缺尖点爱心轮廓与 A 形结构检查是否存在几何局部相似 | 几何测量内核与验收分派未在本轮计算 | B 线双向点距 / 上部三角 / 支脚分离测量 |
| U3 | 语料运行时实际传入模型的文本与后端收到的计划中间态 | 未见对应落盘记录，不能据最终报错反推 | 后续运行需落盘请求文本、semantics、计划、验收快照 |
| U4 | 运行时仓库外进程 / 跨会话状态是否残留规则表外标签 | 代码路径内未见全局缓存；无法排除外部环境 | 复现时先隔离会话 / 新存储键重放对照 |
| U5 | 多对象后补部件尺寸句的作用域判定 | 本四例无此组合；既有测试仅覆盖部分场景 | B/C 线真实多对象计划复核 |
| U6 | C19 选类重叠是否导致错误几何验收 | 仅有选类层回放；未跑几何验收 | D 线核对 `:173` cardioid 分支与 `:199` 爱心分支实际分派 |

---

## 8. 证据完整性附录

### 8.1 相关源码 SHA-256（本工作树快照）

| 文件 | SHA-256 |
| --- | --- |
| `app/cad_semantic_acceptance.py` | `423ed2ff4d23d2090921c19542e2e8d9c8dcfecb49b196e3e619eb543c3a1d09` |
| `app/cad_creation_intent.py` | `5a3d2f723ed435ec27eec45d9c8006646ef6da7c6d568f37224a72e8d50e5ece` |
| `app/cad_source_acceptance.py` | `3f9f559fabecf476bf862934332f0b845f56f08bfe6d522ef08d725410618f5e` |
| `app/cad_requirement_contract.py` | `16017f60e0e4acb70864152623a7f810a6fc09f45174234f8f85306578055770` |
| `app/cad_construction_interpreter.py` | `e1a123357a5adbd4fc804fca7d279a29d490b6c2cf33d3ed8643d12ed249566c` |
| `app/agent_service.py` | `3a181ef7a457e7ad409db914982a50664bcaddfd4de4afc415f5067ff43144bf` |
| `app/agent_skills.py` | `76d41eced2c3ca5047e31f656a9fcca417e69abb36e843d09242f5611577e9b9` |
| `app/conversation_memory.py` | `29e5569ec218acdc0522dfaa8862b801f0b60f149ca04d8cc8995e0f1163dcbc` |
| `app/cad_feature_contract.py` | `6cb036f780bb6fb99106fbab235247d540d08b184425fec84b9f7c3152a1f3be` |

### 8.2 运行环境与规则版本

- 解释器：miniconda `xikao` 环境，Python 3.11.18，pytest 9.2.0；探针仅用标准库 + 既有只读后端函数。
- 规则版本口径：代码内无独立规则版本号；以源码文件 SHA-256 + 行区间（`semantic_requirements` :37-59，验收分派 :199-319）标识。
- 真实评测环境见 §5 第二行；本轮未产生新的模型调用。

### 8.3 每条结论的证据要素对照

| 结论 | 原始输入 | case_id | 历史上下文 | 语义输入 / 输出 | 规则 ID / 版本 | Contract 事实 / 对象 / 作用域 | Feature Binding | 最终验收规则 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A1 爱心未误入字母 A | 探针 JSON `cases.A1.input` | A1 | 无多轮 | 原文 → `heart_outline_features` | heart 规则 :42-43，版本 = 文件哈希 | 1 对象，width/height `single_subject` | `fc-A1-1` 绑定 `step-1:outline` | 爱心检查 :199-225 |
| A9 爱心未误入字母 A | 探针 JSON `cases.A9.input` | A9 | 无多轮（语料记录） | 原文 → `heart_outline_features` | heart 规则 :42-43 | 1 对象，width/height `single_subject` | `fc-A9-1` 绑定 `step-1:outline` | 爱心检查 :199-225 |
| C10 多对象未误入字母 A | 探针 JSON `cases.C10.input` | C10 | 无多轮 | 原文 → `heart_outline_features` | heart 规则 :42-43 | 2 对象，无事实 | `fc-C10-multi` 歧义拒绝，无 Binding | 单对象爱心检查不适用 |
| C26 字母 A 正确触发（正向） | 探针 JSON `cases.C26.input` | C26 | 无多轮 | 原文 → `straight_capital_a` | letter 规则 :50-55 | 1 对象，height/width `single_subject` | `fc-C26-1` 绑定 `step-1:outline` | 字母 A 检查 :275-319 |
| C19 子串重叠 | 探针 JSON `replay_cases.C19` | C19 | 无多轮 | 原文 → `heart_outline_features`（回放） | heart 规则 :42；cardioid 验收 :173 | 未在本轮展开账本 | 未构造 | 分派待验证（U6） |

### 8.4 与 Codex V1.1 提案对照（参照件，非已实现成果）

附件一为独立仓库待审设计文档（基线 `9bd105f`，提案提交 `bd8e43c`），未改生产代码、未跑业务测试；本节仅方案对照，不视为对方成果已实现，不合并分支、不复用其工作树 / 存储。

**结构标识**：Contract `cad.feature-contract.v1`、Binding `cad.feature-binding.v1`、Measurement `cad.feature-measurement.v1` 三方一致（提案 §2.1/§2.2/§4；我方 `cad_feature_contract.py:58-60`）。

**七类 Predicate 覆盖**：

| Predicate | 我方 Sidecar | 判定与理由 |
| --- | --- | --- |
| `boundary_extremum` | 已入类集，仅声明，测量 `undetermined` | 采纳；测量内核归 B 线 |
| `local_extremum` | 未实现 | 本轮不做：需邻域半径 / prominence 参数口径与有界测量证据，参数形态待 B 内核定型 |
| `cusp` | 类名保留，无测量；不接 legacy 布尔 | 采纳严格定义；禁止用 `lower_tip` 区域布尔或折线角点填充 |
| `notch` | 已入类集，仅声明 | 采纳；双证据测量归 B 线 |
| `mirror_symmetry` | 已入类集，仅声明 | 采纳；双向对应测量归 B 线 |
| `continuity` | 已入类集，仅声明 | 采纳；复用既有 JunctionConstraint 语义 |
| `connection` | 未实现 | 本轮不做：绑定两段引用、依赖编排与恢复合并路径（C 线独占文件） |

**来源三类与授权**：`explicit / derived_semantic / model_assumption` 命名与范围边界一致；我方 `_ALLOWED_SCOPES`（`:44-48`）封死升级路径，derived 不可 mandatory，assumption 仅 advisory；规则注册表 `AUTHORIZED_DERIVATION_RULES`（`:52-56`）带版本。

**五条边界条款**：

| 条款 | 判定 | 理由 / 现状 |
| --- | --- | --- |
| ① `lower_tip` 布尔不得冒充数学 cusp | 采纳 | 旧布尔留在既有验收；Sidecar cusp 测量 `undetermined`，无转写路径 |
| ② 旧检查先 legacy parity，不自动升级强制门禁 | 采纳 | 纯 Shadow Measurement，不改变候选通过条件；H2/H3/H4 等既有门禁未动 |
| ③ 未授权语义不进强制集合 | 采纳 | 按来源类封死 scope；无规则版本 / 未授权 derived fail-closed |
| ④ 绑定不确定不能验收成功 | 采纳（设计口径），本轮影子不消费 | 多目标歧义拒绝；无可靠归属不出 Binding；正式门禁接入待审批 |
| ⑤ M3 双条件才 stalled | 采纳为后续协议，未实现 | M2/M3 属 C 线恢复编排；Sidecar 不产生 stalled 结论 |

**实质性冲突**：未发现需自行折中的口径冲突。单列注意：后续 cusp 测量必须按半三次尖点解析口径（或主控批准的等价口径），不得用 legacy 区域布尔。

**我方缺口**（供评审，本轮不补）：编译期 selector 与执行后 Binding 两阶段分离；稳定 `requirement_id` 哈希；Measurement 误差区间 / 采样分辨率 / plan_hash-geometry_hash 五元组；derived 父来源链；explicit/derived 冲突当前为"explicit 胜出、derived 降级 advisory"，与提案"记录双方并请求澄清"的口径差异需评审拍板。

**附件使用边界**：§8.4 中提案条款编号与定义来自附件一文本；§1–§5、§8.1–8.3 的实测取值来自本工作树代码快照与探针回放；未把提案测试设计当作已通过回归。

---

## 9. 复跑命令与文件清单

### 9.1 探针复跑（`backend/` 目录下，零模型、零网络）

```powershell
python evaluations/v1/probes/a_p0_semantic_pollution_probe.py
```

### 9.2 既有回归基线（本轮未改生产代码）

```powershell
python -m pytest tests/test_cad_construction.py tests/test_cad_construction_interpreter.py tests/test_cad_generation_recovery.py
# 基线：37 + 74 + 14 = 125 passed
```

### 9.3 本轮文件

| 文件 | 性质 |
| --- | --- |
| `evaluations/v1/A_P0_语义污染定位.md` | 本报告 |
| `evaluations/v1/probes/a_p0_semantic_pollution_probe.py` | 只读规则回放探针 |
| `evaluations/v1/probes/a_p0_four_cases_semantic_trace.json` | 四例 + 混合轮次 + 重叠案例回放产物 |

未改动：`backend/app` 生产代码、公共 Schema、冻结语料、D 工作树历史证据；未新增生产图形规则或生成器。
