# A_P0 语义污染定位诊断报告（A 线 · 代码级定位 + 五问答案 · 修订版）

> 任务：定位 A1 / A9 / C10 / C26 四例中"爱心请求被误识别为大写字母 A"的**第一次错误分类层**；C26 作为**正向对照**，同时证明字母 A 规则在 C26 上正确触发。
> 本轮纪律：零模型调用、零联网、零费用；未重跑 A9；未改冻结语料、公共 Schema、`CadConstructionPlan v1` 与生产业务代码；未合并、未推送、未 amend。
> 代码快照：分支 `v1/a1-constraint-inheritance`，组合树基线 HEAD `f89bf41facfb7032cbb9647250cff6bbdcc6bbb7`；验收模块 `cad_semantic_acceptance.py` SHA-256 `423ed2ff4d23d2090921c19542e2e8d9c8dcfecb49b196e3e619eb543c3a1d09`（pre-fix 快照）。
> 探针产物：`evaluations/v1/probes/a_p0_four_cases_semantic_trace.json`；探针脚本：`evaluations/v1/probes/a_p0_semantic_pollution_probe.py`。
> 证据等级：**[已查证]** 代码 / 规则回放可复现；**[推断]** 由代码结构推出；**[待验证]** 证据不足，需 D/B 线或落盘记录交叉。
> 运行性质声明：本报告所有 `semantic_requirements` / `parameterize_design` / 账本 / 分派回放均为**确定性纯函数回放**（无模型、无网络）；回放几何为合成折线，不是真实模型输出。真实模型运行记录仅引用 D 工作树第四轮 A9 与 D 线复盘落盘目录（只读）。

---

## 0. 一句话结论（修订后）

**选类层（`semantic_requirements`）在 pre-fix 快照上分类正确：A1/A9/C10 → `heart_outline_features`，C26 → `straight_capital_a`，未把爱心文本判成字母 A。第一次错误发生在分派 / 验收层：`verify_semantic_requirements` 的结构分派是非穷尽的 `if 房子 … else: 字母 A 检查器`，爱心分支通过后没有提前 return，`heart_outline_features` kind 穿透 `else` 兜底进入字母 A 几何检查器。该穿透已在本快照上用完整分派回放复现（合成爱心折线 → 抛字母 A 上部三角区错误，`observed_triangular_regions=[]`），与 D 线落盘报错签名吻合。运行时逐文件哈希 / 快照版本仍 `unverified`；模型自身输出标签与几何形态不在本轮证据范围内。**

---

## 0.1 对 D 三条异议的逐条表态（commit `8a3658c` 交叉核对）

| D 异议 | 表态 | 证据（本快照代码 + 回放） |
| --- | --- | --- |
| ① `:254` 只分流房子，`:275` 是 `else:` 兜底，心形 kind 会穿透进字母 A 检查器 | **同意** | `cad_semantic_acceptance.py:253` `kind=requirements[0]['kind']`；`:254` `if kind=='triangle_roof_house':`；`:275` `else:` 起为字母 A 三角区 / 双支脚 / 收拢斜笔检查（`:290-294`、`:312-317`、`:318-319`）。`heart_outline_features` 不被 `:254` 拦截，落入 `else`。 |
| ② `:199` 爱心检查通过后没有提前 return，trace 停在 sidecar_shadow 不等于验收可达性已验证 | **同意** | `:199-231` 爱心特征全部通过时仅 `direct_checks.append(...)`，无 `return`；流程继续到 `:232`（仅 `not requirements` 才返回）→ `:236` 类型过滤 → `:253` 分派。初版探针确实未覆盖分派 / 验收可达性，属代码阅读结论，不是回放结论。 |
| ③ L8"爱心不进字母检查器"不能作为证据 | **同意，原结论撤回** | 初版 L8 前半句"爱心文本不进入字母 A 几何检查"与本快照代码矛盾。本轮已补完整分派回放（§3-L8、§8.3）：heart kind 合成折线确实到达字母 A 检查器并抛错。"规则不跨请求继承"一句 D 亦同意，保留。 |

**范围分歧承认**：A 树仓库内确实没有四例语料的持久化运行记录；D 线在其自己的持久化复盘运行目录找到四例完整落盘（请求 / 历史 / 计划标签 / 验收测量 / 用量），其中 A1/A9/C10 带字母 A 上部三角区报错签名。两处证据范围互不覆盖，A 不以"仓库内没有"否定 D 落盘目录里的记录；运行时逐文件哈希在两侧均 `unverified`。

---

## 1. 四例并排总表（选类层规则回放，来自探针 JSON）

输入逐字引用附件二语料，未改写。**本表只覆盖选类层；分派层结论见 §3-L8。**

| 案例 | 输入原文 | 期望语义 | 选类层实测 `semantic_requirements()` | 参数化器形状 | 账本对象 | 有效事实（作用域） | Sidecar 影子绑定 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A1 | `生成一个闭合爱心轮廓，宽度4米，高度4米` | 爱心；不触发字母 A 验收 | `heart_outline_features` | `heart_outline`，宽 4.0 m × 高 4.0 m | 1：`闭合爱心轮廓` | width 4000 mm（11–15 `宽度4米`）、height 4000 mm（16–20 `高度4米`），`single_subject` / `effective` | `fc-A1-1` 有效，`explicit` / `mandatory`，绑定 `step-1:outline`，无错误 |
| A9 | `生成一个左右对称、平滑闭合的爱心，中心在(2,3)，宽4米高4米` | 爱心；不触发字母 A 验收 | `heart_outline_features` | `heart_outline`，宽 4.0 m × 高 4.0 m | 1：`左右对称、平滑闭合的爱心` | width 4000 mm（26–29 `宽4米`）、height 4000 mm（29–32 `高4米`），`single_subject` / `effective` | `fc-A9-1` 有效，`explicit` / `mandatory`，绑定 `step-1:outline`，无错误 |
| C10 | `生成一个爱心和一个五角星，爱心在左，五角星在右` | 爱心 + 五角星；不触发字母 A 验收 | `heart_outline_features`（pre-fix 守卫 ≤2；post-fix 已收紧到 ≤1，D 回放 C10 → `[]`，见 §8.4） | `heart_outline`，尺寸缺失 | 2：`爱心`、`五角星` | 无事实（无尺寸句） | `fc-C10-multi` **无效**：`fc_evidence_missing` + `fc_multi_target_ambiguous`；无绑定记录 |
| C26（正向对照） | `生成一个大写字母A的轮廓，高3米宽2米` | 大写字母 A；**应**触发字母 A 验收 | `straight_capital_a` | `generic_2d_cad`，尺寸未提取（见 §6.3） | 1：`大写字母A的轮廓` | height 3000 mm（13–16 `高3米`）、width 2000 mm（16–19 `宽2米`），`single_subject` / `effective` | `fc-C26-1` 有效，`explicit` / `mandatory`，绑定 `step-1:outline`，无错误 |

**正向对照判定 [已查证]**：C26 是四例中唯一命中 `straight_capital_a` 的输入；字母 A 选类规则在 C26 上触发条件成立，规则本身未坏。问题不在"字母 A 规则失效"，而在分派层把非字母 A 轮廓放进了字母 A 检查器（§3-L8）。

---

## 2. 五问答案（验收口径 · 修订版）

### Q1 第一次错误发生在哪里（模块 / 函数 / 代码行 + 实际执行行为）

**结论 [已查证，回放复现]**：

- **选类层无错误**：`cad_semantic_acceptance.py:37-59` `semantic_requirements` 对四例的分类与期望一致（§1 表）。
- **第一次错误在分派 / 验收层**：同文件 `verify_semantic_requirements`：
  - `:199-231` 爱心特征检查通过后**不返回**，只追加 `direct_checks`；
  - `:253` 取 `kind=requirements[0]['kind']`；
  - `:254` 仅 `if kind=='triangle_roof_house'` 分流房子；
  - `:275 else:` 把**其余所有 kind**（含 `heart_outline_features`）兜底进字母 A 几何检查器（`:276-319`：上部三角 `:290-294`、分离双支脚 `:312-317`、收拢斜笔 `:318-319`）。
- **回放复现**：合成通过爱心四特征的闭合折线（A1 文本）→ 未抛爱心错误，穿透到 `else`，抛 `大写A缺少由两斜笔与横笔围成的上部三角区域`，`observed_triangular_regions=[]`，`required_relation=triangle_tip_above_horizontal_base`（探针 `dispatch_replay.heart_passing_polyline`）。
- 边界条件（同回放）：爱心特征失败的矩形先抛 `heart_bilateral_lobes_notch_and_lower_tip`，不到字母检查器；`spline` 类型在 `:237-238` 返回 `unverified / unsupported_profile_representation`，也不到分派兜底。

### Q2 为什么发生（主因 / 次因分类 + 排除依据）

| 候选成因 | 判定 | 判别依据 |
| --- | --- | --- |
| **分派非穷尽 + 位置穿透（主因）** | **[已查证]** | `:254` 单一 `if` + `:275 else` 兜底；无 `elif kind=='straight_capital_a'` 显式分支；未知 / 未覆盖 kind 没有独立默认返回。爱心 kind 因无提前 return 落入兜底。回放复现字母 A 报错签名。 |
| 匹配范围过宽 / 首命中终局（次因，选类层隐患） | **[已查证存在机制]** | 爱心正则子串 `心形` 可命中 `心形线`（C19 回放）；规则首个命中即 `return`，不返回候选集。该隐患在 P0 四例选类层未造成误判，但与分派兜底叠加会放大串扰。 |
| 上下文 / 多轮污染 | **排除 [已查证]** | 语义每轮重算；混合两轮回放双向均按当前文本命中；记忆按会话 id 隔离；D 落盘扫描 143 个唯一请求 ID，`contamination=[]`、`blocked=false`，编号仅在 `conversation_id` 元数据，未进正文。 |
| 对象绑定错误 | **排除（四例）[已查证]** | A1/A9/C26 单对象 `single_subject`；C10 两对象无尺寸事实，Sidecar 多目标歧义拒绝而非错绑。 |
| 验收规则跨请求继承错误 | **排除 [已查证]** | 验收 kind 来自当前请求 `semantics`；`agent_service.py:6870,6888-6897` 形状由当前消息重新参数化；未发现旧会话规则复用路径。 |
| 模型侧标签 / 几何形态 | **待验证 [unverified]** | 本轮零模型调用；分派层兜底已能独立解释落盘报错签名，但模型计划几何是否加剧失败仍需 D/B 线核对，不据最终报错反推中间过程。 |

### Q3 影响范围（候选语义类别与案例清单）

规则表六类（`semantic_requirements:40-57`）：astroid 星形线、heart 爱心轮廓、nested 嵌套方框、regular polygon 正多边形、straight capital A 字母 A、triangle-roof house 房子。

**分派兜底的影响面 [推断，基于代码结构]**：除房子与已在更早分支 `return` / `raise` 的 astroid / nested / polygon / cardioid 外，**其余落到 `:236` 之后的 kind 都会被 `else` 送进字母 A 检查器**；当前选类层能产生、但未在分派层显式分流的主要是 `heart_outline_features`。

| 语义类别 | 规则位置 | 语料候选案例 | 选类回放结果 | 状态 |
| --- | --- | --- | --- | --- |
| 爱心轮廓 `heart_outline_features` | `:42-43` | A1、A9、C10；B1/B2/B4/B7/B9/B12/B19（文修爱心，未逐条回放） | A1/A9/C10 → `heart_outline_features` | 选类已证实；分派穿透已回放证实；B 系列待验证 |
| 心形线 cardioid | 验收 `:173-198`；选类层无独立 kind | C19 `生成一个心形线（cardioid）…` | 选类 → `heart_outline_features`（子串 `心形` 先命中） | 选类重叠已证实；cardioid 分支在 `:196` 提前 return 可拦截；未拦截时同样会落入 `else` 兜底，待验证（U6） |
| 字母 A `straight_capital_a` | `:50-55` | C26 | C26 → `straight_capital_a` | 正向对照已证实；语料内无第二例字母 |
| 星形线 `astroid_identity` | `:40-41` / 验收 `:101-114` | C18 | C18 → `astroid_identity`；验收分支提前 return | 已证实，不到 `else` |
| 房子 `triangle_roof_house` | `:56-57` / 验收 `:254-274` | C16 | C16 → `triangle_roof_house` | 已证实，显式分流 |
| 嵌套方框 `nested_square_frames` | `:44` / 验收 `:115-151` | C29 回字形；C15 圆环 | C29 → `nested_square_frames`（提前 return）；C15 → `[]` | C29 已证实；C15 规则未覆盖（非污染） |
| 正多边形 `regular_polygon` | `:46-47` / 验收 `:152-172` | C5、C13、C32、C4 | C5/C32 → `regular_polygon`；C13/C4 → `[]` | 部分命中已证实；未命中属覆盖缺口，待验证 |
| 多对象守卫 | `:49` | C7、C10、C11 等 | 守卫对象数 ≠1 或多对象关键词时返回 `[]` | 待验证（本轮仅回放 C10） |

### Q4 能否通用修复（不含任何图形专用分支）

方向（本轮不改生产，待主控批准）：

1. **分派穷尽化 + 显式默认兜底**：每个已知 kind 走显式 `elif` 分支；未识别 / 未覆盖 kind 进入独立默认分支，返回 `unverified` / `partial` 并记录未知 kind，**不得继承上一分支或任何既有检查器**。检查器之间不得靠代码位置 `else` 穿透。
2. **规则返回候选集而非首命中终局**：`semantic_requirements` 返回所有命中规则及证据（规则 ID、版本、词面跨度），由下游按显式优先级裁决；消除"先写在前的规则永久挡住后面规则"的顺序耦合。
3. **匹配锚定到 Contract 主体**：规则关键词必须落在 `requirement_contract` 抽出的 subject 别名内；修饰语、括号注释、follow-up 限定语中的关键词不单独定类（如 `心形线` 作为独立主体别名参与匹配，不被 `心形` 子串截取）。
4. **对象锚点与基数校验**：规则携带期望对象基数；多对象文本不把单对象轮廓规则套到全图；切分器与守卫阈值口径统一。
5. **版本化规则注册表**：规则 ID / 版本 / 适用域进证据；与第六轮 Sidecar 的来源 / 版本授权机制对接。

**为什么能从根本上避免互相污染**：现有串扰有两个前提——选类层子串独占解释、分派层用位置兜底代替显式匹配。上述机制把"一段文本 → 单一规则"拆成"账本主体 → 候选规则集 → 显式 kind 分派 + 未知默认兜底"三层；任何关键词都需在被声明对象上落地、在分派层被显式匹配才进入对应检查器。新增形状类别只需注册规则与分派分支，不需要为某图形写专用补丁。

### Q5 如何验证修复（正向 / 反向 / 回归 / 前后对照）

**正向案例：**

| 输入 | 预期修复后结果 | 当前 pre-fix 回放基线 |
| --- | --- | --- |
| C26 `生成一个大写字母A的轮廓，高3米宽2米` | `straight_capital_a`；进入字母 A 结构验收 | 选类已证实命中 |

**反向案例：**

| 输入 | 预期修复后结果 | 当前 pre-fix 回放基线 |
| --- | --- | --- |
| A1 `生成一个闭合爱心轮廓，宽度4米，高度4米` | `heart_outline_features`；分派进爱心检查器；字母 A 候选与检查器均不触发 | 选类正确；分派穿透已回放证实（缺陷） |
| A9 `生成一个左右对称、平滑闭合的爱心，中心在(2,3)，宽4米高4米` | 同上 | 同上 |
| C10 `生成一个爱心和一个五角星，爱心在左，五角星在右` | 多对象裁决；不产生单对象爱心 / 字母 A 强制门禁；绑定歧义 `unresolved` | 选类 heart（pre-fix）；Sidecar 歧义拒绝 |

**分派穿透专项回放（本轮已做，修复后必须不再复现）：**

| 合成输入 / 几何 | pre-fix 实测 | 修复后预期 |
| --- | --- | --- |
| A1 文本 + 通过爱心四特征的闭合折线 | 抛字母 A 上部三角区错误，`observed_triangular_regions=[]` | 走爱心检查器并通过 / 抛爱心专属错误；字母 A 检查器不被调用 |
| A1 文本 + 矩形（爱心特征失败） | 抛爱心特征错误 | 行为不变 |
| A1 文本 + `spline` 类型 | `unverified / unsupported_profile_representation` | 行为不变 |

**重叠修复专项：**

| 输入 | 预期修复后结果 | 当前回放基线 |
| --- | --- | --- |
| C19 `生成一个心形线（cardioid），尖点朝下，最大宽度3米` | 主体 `心形线 / cardioid` 独立成类，不被 `心形` 子串截为爱心轮廓 | 当前 → `heart_outline_features`（重叠已证实） |

**既有回归清单（修复后必须全绿；本轮未改生产，基线 125 passed）：**

- `tests/test_cad_construction.py`（37）
- `tests/test_cad_construction_interpreter.py`（74）
- `tests/test_cad_generation_recovery.py`（14）
- 追加：`tests/test_cad_semantic_acceptance.py`、`tests/test_cad_requirement_contract.py`、`tests/test_cad_local_repair.py`、`tests/test_cad_feature_contract.py`

**修复前后同一输入对照实验设计：**

- 固定条件：同一批输入（四例 + C19 + 混合两轮 + 三对象 + 三条分派回放几何）、同一上下文快照、同一账本、无模型调用；只改分派 / 裁决函数一处。
- 记录项：规则候选集、命中词面跨度、选中主规则、分派分支、对象基数、Contract 主体、最终验收 kind、被调用的检查器。
- 预期差异：四例选类主规则与基线不变；分派层 heart kind 不再进入字母 A 检查器；未知 kind 走默认兜底返回 `unverified`；字母 A 候选在三爱心输入上恒为空。
- 判定：任一正向 / 反向案例主规则改变，或爱心 kind 再次到达字母 A 检查器，修复驳回。

---

## 3. 八层逐层证据明细

### L1 输入改写 / 截断 / 归一

- `cad_construction_interpreter.py:358`：`text = source_text.strip()`；`:361` 切旧反馈段。
- 快照分支 `:367-380`：规则文本取不可变 `original_prompt`，模型输入保留完整快照。
- `cad_semantic_acceptance.py:39`：规则文本由 `source_texts` 拼接，未 lower。
- 全仓 `.lower()` 排查：`agent_service.py` 多处 `.lower()` 仅用于独立关键词分类副本；构造解释器入口 `:6344` 取 `message.strip()`，折叠文本不回流规则链。
- 探针 `entry_normalization`：`trim_only=false`、`lowercase_applied_to_rule_text=false`、`prefix_or_suffix_added=false`。

### L2 case_id 是否进入上下文

已排查位置：生产聊天入口、基准运行器 `cad_construction_evaluation.py:89-96`、参考案例 `agent_evaluation.py:78,90-94`、冻结快照 `p1.3e_dual_case_frozen.json`、注册表 `evaluations/v1/case_registry.json`、审计探针 `probes/d0_validate_assets.py:57-63`；D 线落盘 `request-N.json` 正文编号串扫描亦为空。

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

### L4 规则命中与跨度（选类层）

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
- 几何判据在验收侧 `:275-319`，仅对分派到该检查器的几何执行：上部三角 `:290-294`、分离双支脚 `:312-317`、收拢斜笔 `:318-319`。
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

### L8 分派 / 验收规则选择（修订：原"爱心不进字母检查器"结论撤回）

**代码结构 [已查证]**：

- 提前返回的分支：astroid `:112-114`、嵌套 `:148-151`、正多边形 `:171-172`、cardioid `:196-198`；这些 kind 不到达 `:253` 分派。
- 爱心分支 `:199-231`：通过后不返回；`direct_checks` 追加后继续。
- `:232-235`：`not requirements` 才返回 partial / not_checked。
- `:236-238`：几何类型非 line / polyline → `unverified / unsupported_profile_representation`。
- `:253-275`：`kind` 分派；仅房子显式分流，`else` 兜底字母 A 检查器。

**完整分派回放 [已查证，合成几何，非真实模型输出]**（探针 `dispatch_replay`）：

| 回放键 | 文本 | 几何类型 | 结果 | 检查 / 测量签名 |
| --- | --- | --- | --- | --- |
| `heart_passing_polyline` | A1 | 闭合折线，通过爱心四特征 | 穿透 `else` 抛错 | `大写A缺少由两斜笔与横笔围成的上部三角区域`；`observed_triangular_regions=[]`；`required_relation=triangle_tip_above_horizontal_base` |
| `rectangle_fails_heart_features` | A1 | 矩形折线 | 爱心分支先抛错 | `heart_bilateral_lobes_notch_and_lower_tip` |
| `spline_unsupported_type` | A1 | spline | `:237-238` 返回 | `unverified / unsupported_profile_representation` |

**与落盘签名的对照 [推断，高置信；运行时哈希 unverified]**：D 线落盘 A1/C10 报错 `required_relation=triangle_tip_above_horizontal_base`、`observed_triangular_regions=[]`，与本快照 `else` 兜底行为及回放签名一致；但保留的 pre-fix 副本是否与运行时模块逐字节相同无法证实（§7-U2）。

**跨请求继承 [已查证，保留初版结论]**：验收 kind 来自当前请求 `semantics`；`agent_service.py:6870` 重新参数化，`:6888-6897` 兜底形状仅在推断为空且非抽象词时使用；未发现旧会话规则复用。

---

## 4. 错误传播链（修订）

```text
用户原文
  → source_texts 切分（cad_source_acceptance.py:16-22）
  → requirement_contract 账本 / 作用域（cad_requirement_contract.py）
  → semantic_requirements 选类（cad_semantic_acceptance.py:37-59）  ← 选类正确
  → semantics 注入模型提示词（cad_construction_interpreter.py:566-567）
  → schema minItems 收窄（:1718-1725）
  → 模型计划（本轮不调用）
  → verify_semantic_requirements 分派（:199 爱心 → :253 kind → :254 房子 / :275 else 字母 A）
      ├─ 已知显式分支：房子
      ├─ 提前返回分支：astroid / 嵌套 / 多边形 / cardioid
      └─ 其余 kind（含 heart）→ else 字母 A 检查器  ← 第一次错误点（分派穿透）
```

透传环节：提示词注入与 schema 收窄不改变 kind；后端在对应检查器内失败，不反向改写文本 kind。Sidecar 影子链：真实账本 → 来源索引复用 → 声明校验 → 绑定（歧义拒绝）→ 影子测量（`undetermined`，不参与候选通过条件）。

**几何重叠提示 [推断，待 B 线验证]**：缺下方尖点、保留双侧上凸与中央凹口的轮廓，在形态上可能与"双斜笔 + 横笔上部三角"局部相似；文本规则不做此类几何猜测。本报告定位的是分派穿透机制，几何层面相似性归属 B 线测量核查。

---

## 5. 两条 A9 记录永久分开

| 维度 | 独立真实评测 A9（D 工作树，只读引用） | 70 例语料 A9（D 线复盘落盘 + 本快照回放） |
| --- | --- | --- |
| 记录性质 | 第四轮受控真实模型运行 | D 线持久化复盘运行目录四例之一；本报告另做纯函数规则 / 分派回放 |
| 输入原文 | `生成一个左右对称、平滑闭合的爱心，中心在(2,3)，宽4米高4米` | 同左（附件二第 19 行） |
| 输入 SHA-256 | `af12df04393e1da42acd9eae6e590f81fa8c66a4720c546c9d292fef89707d5b` | 同左（注册表 `input_sha256` 一致；D 复盘记录同哈希） |
| 代码快照 / 哈希 | 组合树基线 `f89bf41facfb7032cbb9647250cff6bbdcc6bbb7`；规则文件前 16 位 `423ed2ff4d23d209`（与本快照一致） | 本工作树 pre-fix 规则文件 `423ed2ff…`（完整值 §8.1）；D 复盘聚合 digest `08eae81a…e8e73`，逐文件哈希 `unverified`；保留 pre-fix 副本 `423ED2FF…A1D09`，与运行时是否逐字节相同未证实 |
| 请求记录 | `round4/A9_case_record.json`、`round4/A9_raw_responses.jsonl`；2 次 `deepseek-flash`（request_id `1df31f91…`、`6bda0ebb…`） | D 线 `run/A9/` 请求 / 步骤 / 用量落盘（只读引用，未由 A 树复核逐字段）；结构化调用 3 次、6 条 usage，费用归第七轮账本 |
| 运行环境 | 隔离评测进程，`deepseek-flash`（DeepSeek-V4.1-Flash-1017），peak 价；usage 输入 31554（命中 15872 / 未命中 15682）、输出 804；费用 0.005764632 USD | harness 经启动器执行；Python 版本 `unverified`；本报告回放环境 Python 3.11.18 / pytest 9.2.0，无模型无网络 |
| 语义规则版本 | 同快照规则文件；无独立版本号，以文件哈希 + 行区间标识 | 同左；模块内无规则版本常量，`unverified` |
| 结论 / 失败特征 | `failed`；`center_notch / left_upper_lobe / right_upper_lobe = true`、`lower_tip=false`；失败检查 `heart_bilateral_lobes_notch_and_lower_tip`；类别 `model_plan_invalid`；未持久化候选 | 选类回放 `heart_outline_features`；D 落盘 attempt 1 表达式非法，attempt 2/3 命中字母 A 上部三角区检查（`observed_triangular_regions=[]`）；分派穿透为本快照代码 + 回放可解释，运行时版本 `unverified` |
| 缺失证据 | — | 运行时逐文件哈希、`verify_semantic_requirements` 当次 requirements 列表、system 提示词全文、Feature Contract 绑定：`unverified` |

两条记录不得合并为一个失败案例：记录①是爱心尖点几何问题，记录②是分派 / 验收串扰线索，两类独立缺陷。

---

## 6. 候选通用观察（本轮不改生产）

### 6.1 分派非穷尽 + 位置穿透（主因）

- 证据：`cad_semantic_acceptance.py:253-275`；回放 §3-L8。
- 通用性：分派表缺少"未知 kind 默认兜底"与显式 `elif` 匹配，是所有 profile 规则的公共结构问题，不针对爱心 / 字母 A。
- 影响面：所有能到达 `:236` 之后、且未被显式分支或提前返回覆盖的 kind。
- 回归范围：`test_cad_semantic_acceptance.py`、`test_cad_construction_interpreter.py`。
- 回滚点：分派函数纯函数；默认兜底分支可独立摘除，不影响既有显式分支。

### 6.2 首命中终局、规则结果无版本化来源标注

- 证据：`cad_semantic_acceptance.py:42-55`；规则结果不带规则 ID / 版本 / 跨度。
- 通用性：任意关键词规则表均有顺序耦合风险；对接第六轮 Sidecar 来源可追溯与规则版本授权。
- 回归范围：语义验收与解释器既有案例。
- 回滚点：Sidecar 影子模块可整模块摘除；公共 Schema 与既有门禁不受影响。

### 6.3 对象计数口径不一致

- 证据：`cad_creation_intent.py:50-51` 只按 `和|与|及` 拆（顿号不拆）；守卫 `cad_semantic_acceptance.py:42,49` 用对象数 ≤2 / ==1。
- 通用性：对象计数是所有多对象 / 组合规则的公共前置，属解析口径问题。
- 影响面：阵列、并排、左右布局等多对象案例；需先补顿号 / 逗号并列切分对照测试。
- 回滚点：切分函数为纯函数，可恢复旧拆分正则，守卫阈值不变。

### 6.4 自由轮廓尺寸未对齐账本（单列，与分派缺陷无关）

- 证据：探针 C26 账本已抽 height 3000 / width 2000 mm，参数化器仍 `dimensions={}`、`generic_2d_cad`；`agent_skills.py:1886-1887`。
- 通用性：参数化器与需求账本两套尺寸提取口径未对齐；不改变语义分类。
- 回归范围：矩形 / 圆 / 拱门等既有尺寸案例。
- 回滚点：参数化器独立纯函数，可回退旧提取路径；账本事实不改动。

### 6.5 本轮明确不做

不为任何图形新增专用生成器 / 控制点 / 提示词；不把 legacy 区域布尔升级为数学门禁；不放宽 H2/H3/H4、自相交、来源授权、候选保存条件，不增加 `max_repairs`；不改公共 Schema 与 `CadConstructionPlan v1`。

---

## 7. 不确定项清单（`unverified`）

| # | 事项 | 缺哪份证据 | 交叉方 |
| --- | --- | --- | --- |
| U1 | 模型自身输出标签 / 对象命名 / 计划几何是否加剧门禁失败 | 四例语料运行的模型原始响应与落盘计划；本轮零模型调用 | D 线历史响应 / 计划记录 |
| U2 | 复盘运行时模块与保留 pre-fix 副本是否逐字节相同 | 运行时逐文件 SHA-256 未留存，清单仅聚合 digest；分派穿透在本快照代码与回放中成立，运行时版本为高置信推断 | D 线快照审计 |
| U3 | 语料运行时实际传入模型的文本、当次 `requirements` 列表与中间态 | 落盘材料未记录当次验收输入列表；不能据最终报错反推 | 后续运行落盘请求文本、semantics、计划、验收快照 |
| U4 | 运行时仓库外进程 / 跨会话状态是否残留规则表外标签 | 代码路径内未见全局缓存；无法排除外部环境 | 复现时先隔离会话 / 新存储键重放对照 |
| U5 | 多对象后补部件尺寸句的作用域判定 | 本四例无此组合；既有测试仅覆盖部分场景 | B/C 线真实多对象计划复核 |
| U6 | C19 选类重叠是否造成错误几何验收 | 仅有选类层回放；cardioid `:173` 先行拦截是否覆盖全部败态未跑几何回放 | D 线核对 cardioid 与 heart 分支实际分派 |
| U7 | B 系列文修爱心案例是否触发同一分派穿透 | 本轮未逐条回放 | 回归阶段补充 |

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

- 回放解释器：miniconda `xikao` 环境，Python 3.11.18，pytest 9.2.0；探针仅用标准库 + 既有只读后端函数。
- 规则版本口径：代码内无独立规则版本号；以源码文件 SHA-256 + 行区间标识（选类 `:37-59`；分派 `:199-319`）。
- 真实评测环境见 §5 记录①；本轮未产生新的模型调用。

### 8.3 每条结论的证据要素对照

| 结论 | 原始输入 | case_id | 历史上下文 | 语义输入 / 输出 | 规则 ID / 版本 | Contract 事实 / 对象 / 作用域 | Feature Binding | 最终验收规则 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A1 选类为爱心、分派穿透字母检查器 | 探针 JSON `cases.A1.input` + `dispatch_replay.heart_passing_polyline` | A1 | 无多轮 | 原文 → `heart_outline_features`；合成折线到达 `else` | heart 选类 :42-43；分派 :253/:275，版本 = 文件哈希 | 1 对象，width/height `single_subject` | `fc-A1-1` 绑定 `step-1:outline` | 字母 A 检查 :275-319（穿透到达） |
| A9 选类为爱心 | 探针 JSON `cases.A9.input` | A9 | 语料记录无多轮证据 | 原文 → `heart_outline_features` | heart 规则 :42-43 | 1 对象，width/height `single_subject` | `fc-A9-1` 绑定 `step-1:outline` | 分派穿透机制同 A1；几何回放未单独构造 |
| C10 多对象未误入字母选类 | 探针 JSON `cases.C10.input` | C10 | 无多轮 | 原文 → `heart_outline_features`（pre-fix） | heart 规则 :42-43 | 2 对象，无事实 | `fc-C10-multi` 歧义拒绝，无 Binding | 双对象跳过 `:199` 单对象爱心分支，直达 `else`（机制推断，未单独回放） |
| C26 字母 A 正确触发（正向） | 探针 JSON `cases.C26.input` | C26 | 无多轮 | 原文 → `straight_capital_a` | letter 规则 :50-55 | 1 对象，height/width `single_subject` | `fc-C26-1` 绑定 `step-1:outline` | 字母 A 检查 :275-319 |
| C19 子串重叠 | 探针 JSON `replay_cases.C19` | C19 | 无多轮 | 原文 → `heart_outline_features`（回放） | heart 选类 :42；cardioid 验收 :173 | 未在本轮展开账本 | 未构造 | 分派待验证（U6） |

### 8.4 两套快照选类回放对照（D 交叉核对，本地回放非真实运行）

| case_id | 期望语义 | pre-fix（`423ed2ff…`，本快照） | post-fix（D 记录 `164a7d89…`，未在 A 树复核） | 说明 |
| --- | --- | --- | --- | --- |
| A1 | heart | `heart_outline_features` | `heart_outline_features` | 选类一致 |
| A9 | heart | `heart_outline_features` | `heart_outline_features` | 选类一致 |
| C10 | heart + star 双对象 | `heart_outline_features` | `[]` | post-fix 守卫收紧到 ≤1；本报告 C10 取值为 pre-fix 行为，不外推 post-fix |
| C26 | 大写字母 A | `straight_capital_a` | `straight_capital_a` | 正向对照 |
| C19 | cardioid | `heart_outline_features` | `heart_outline_features` | 子串重叠两套快照均复现 |

### 8.5 与 Codex V1.1 提案对照（参照件，非已实现成果）

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

**附件使用边界**：§8.5 中提案条款编号与定义来自附件一文本；§1–§5、§8.1–8.4 的实测取值来自本工作树代码快照与探针回放；未把提案测试设计当作已通过回归。

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
python -m pytest tests/test_cad_feature_contract.py
# 12 passed
```

### 9.3 本轮文件

| 文件 | 性质 |
| --- | --- |
| `evaluations/v1/A_P0_语义污染定位.md` | 本报告（修订版） |
| `evaluations/v1/probes/a_p0_semantic_pollution_probe.py` | 只读规则 / 分派回放探针 |
| `evaluations/v1/probes/a_p0_four_cases_semantic_trace.json` | 四例 + 混合轮次 + 重叠案例 + 分派回放产物 |

未改动：`backend/app` 生产代码、公共 Schema、冻结语料、D 工作树历史证据；未新增生产图形规则或生成器。
