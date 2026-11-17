# C 第四轮前置：生产链路判定与五指标口径预注册（零费用、零改动）

> 冻结时点：在看到任何真实模型结果**之前**定稿。第四轮由 D 独家发起真实模型请求；C 线本轮不实例化模型客户端、不发网络请求、不改 `backend/app`。本文件只冻结"生产链路侧怎么判、五个指标怎么算"；结果回来后只按本口径核算，**不得看到结果后修改定义、阈值、分母或状态归类**。

## 0. 复用依据（只读）

- D 线《D1 统一失败分类口径》：五类顶层 `collection_blocked / environment_blocked / not_run / logic_failure / error_mapping_failure`，`evidence_mode` 枚举，`provider_attempted=false` 不得解读为真实尝试，服务级 Mock 通过数不得换算为生成通过率。
- D0《可执行评测方案》：六维 schema（model / planning / source / geometry / acceptance / version / outcome），`evidence_mode` 可否计入通过率，统计规则（§10）。
- 并行线《考核指标口径》：FSR、CGQ、MES 的原始定义与样本量诚实说明。
- C 线前三轮接入点分析与循环实证：`C1_接入点分析与A1复核报告.md`、`C1.1_GAP复核与两轮组合验证报告.md`、`C1.2_生产循环两轮验证报告.md`、`C1_test_status.json`。

## 1. 链路侧取证边界（零费用）

### 1.1 允许的取证动作

- 只读读取一次运行结束后落库/内存中的**结果记录字段**（见 §3 字段清单），据此判定路由、状态与指标分子分母。
- 复跑既有零费用探针/确定性规则专项（`deterministic_rule` / `rule_parser_zero_cost`）。
- 隔离临时存储（`tmp_path` / `tempfile`），不写真实 `backend/data/`。

### 1.2 禁止动作

- 不实例化模型客户端、不配置 `DEEPSEEK_API_KEY` / `OPENAI_API_KEY` / `ARK_API_KEY` / `MODEL_API_KEY`。
- 不发起任何真实网络模型请求；Mock callback 被调用时按既有零费用守卫直接 `raise AssertionError("unexpected live model call")`。
- 不改 `backend/app` 生产代码、不改冻结输入、不改 D0 资产、不放宽 H2/H3/H4 验收语义。

### 1.3 运行记录必备字段（口径输入）

取自生产结果与 recovery 记录（行号锚点见 §5）：

| 字段 | 来源 | 用途 |
|---|---|---|
| `provider_attempted` | model 记录 | 是否真的尝试 provider；`false` 不得记模型路径 |
| `planning.route` / `route.name` / `route.operation` / `route.decision_source` | 路由记录 | actual_route 判定 |
| `route.clarification_required` / `interpretation.status` | `agent_service.py:626, 6439, 6461, 6739-6740` | 是否澄清态 |
| `request_attempts` | model 记录 | 结构化模型尝试次数 |
| `structured_retry_used` | evaluation 指标 | 是否走结构化模型重试 |
| `deterministic_repairs` / `recovery.repair_count` | `cad_construction_evaluation.py:179`；`agent_service.py:6588` | 是否进入确定性修复循环 |
| `recovery.attempts[]`：`status` / `construction_error.code` / `details.affected_output_refs` / `plan` / `local_repair_scope` / `coordinate_patch` | `agent_service.py:6476-6529, 6587-6588` | 轮次、渠道、refs、前次计划 |
| acceptance `h2/h3/h4.status`、`review_required` | `evaluation_schema.json` acceptance 维 | 三态通过与否、人工复核标记 |
| `candidate_status` / `persisted` / `persisted_candidate_count` | version 维；`agent_service.py:6792-6823` | 候选是否被接纳落库 |
| topology 检出对（contact/intersection pairs）、自交对数、连续性测量 | geometry 维 | Detection / CGQ |

## 2. `expected_route` 与 `actual_route` 判定

### 2.1 `expected_route`（注册表给定，不反推）

取自 `case_registry.json`：`construction_scope`（应进入构造生成）/ `clarify`（应先澄清）/ `unfrozen`（未冻结，不执行）。`freeze_status` 为 `unfrozen` 时 `expected_route=null`。

### 2.2 `actual_route`（运行后按字段判定，互斥，按优先级取首个命中）

| actual_route | 判定条件（全部基于记录字段，零费用） |
|---|---|
| `rule` | 未尝试 provider（`provider_attempted=false`），由确定性规则/解析器产出计划；`structured_review_text` 出口未被真实模型占用。 |
| `structured_model` | `provider_attempted=true` 且存在结构化计划哈希；记录到模型 usage/请求或响应引用。 |
| `clarification` | `route.clarification_required=true` 或 `interpretation.status == "clarification_required"`；无有效构造计划。 |
| `blocked_route` | 在路由解析前被 collection / 环境 / provider 不可用 / 超时 / 预算拒绝拦下；没有可判定的构造计划。 |
| `unfrozen` | 案例 `freeze_status=unfrozen`，本轮未执行。 |

### 2.3 路由一致性判定

- `route_match = (actual_route 归一后) == expected_route`；`clarify` 与 `construction_scope` 互不可替代。
- 路由误判记入 D1 `planning_route` / `route_misclassification` 根因，不计入生成通过率分子。
- 同一案例若先 `blocked_route` 后复跑成功，以**最终有效运行**记录为准，但每次运行单独留痕，禁止用补跑覆盖失败原始记录。

## 3. 五个指标：分子、分母、计数单位与阈值来源

> 计数单位统一为"案例（一个 `request_id`）"，不以候选、重试尝试或几何段计数替代。每条聚合必须同时给出分子、分母、证据模式、缺失案例数与失败分布。

### 3.1 FSR（First-pass Success Rate，首轮生成成功率）

- **分子**：首轮计划（同 `request_id` 内未发起第二次模型调用、未进入确定性修复循环、未澄清）同时满足 H2 通过、H3 通过、H4 通过，且候选被接纳（`status=ready` / 验收 `review_required` 非真）的案例数。
- **分母**：本轮实际执行、证据模式计入通过率的 eligible 案例数（见 §6 分层）。`clarified`、`blocked`、`unfrozen`、`not_run` 列入分母外的单列计数，不混入 FSR 分母；其中 `clarified` 计为 FSR 失败单列，不占分子。
- **轮次口径**：链路内部确定性重试（不重新问模型）不算模型重试；结构化模型第二次调用即不算首轮。
- **不允许**"部分通过"折算；H2/H3/H4 任一失败即失败。

### 3.2 Repair Success（修复成功率）

- **分子**：进入有界修复循环（`repair_count≥1` 或 `deterministic_repairs` 非空）后，在轮次上限内达到 H2/H3/H4 全通过的案例数。
- **分母**：所有进入修复循环的案例数（首轮失败且被路由到可修复渠道）；从未进入修复的 `clarified` / `blocked` 案例不进分母。
- **分层报告**：`model_retry`（结构化模型重试）与 `deterministic_repair`（部件/局部确定性修复）两桶分别给分子分母，不合并成一个修复成功率。
- **边界**：修复后仍 `review_required` 或 `unresolved_topology` 不计入分子（见 §4 硬规则）。轮次上限、预算、候选保存条件沿用生产既有值，本指标不放宽。

### 3.3 CGQ（Candidate Geometry Quality，候选几何质量缺陷率，越低越好）

- **分子**：在 **H2 已通过**的案例中，存在下列任一登记缺陷的案例数；并按缺陷类型分别计数分布（不只报总分）。
  1. 非相邻段自相交（`allow_self_intersection=false` 时仍相交）；
  2. 连接点连续性不满足声明 `intent`（如 `smooth` 不足 G1/C1）；
  3. 端点拼接误差超 `connection_tolerance`；
  4. 曲线离散误差超 `max_sampling_error`；
  5. 尺寸/面积断言偏差超出计划 `assertions` 容差。
- **分母**：H2 通过的案例集合，**不是**全部案例；CGQ 与 FSR 分母不同，不可互相替代。
- **阈值来源**：一律取自计划 `assertions` 容差、声明的 `connection_tolerance`、`max_sampling_error`、`allow_self_intersection` 与验收器既有判定；**不得自创阈值**，也不得为通过而调宽容差。

### 3.4 Detection（拓扑接触/相交检出，召回）

- **适用范围**：仅纳入带拓扑真值标注的案例（冻结 fixture 或注册表 `expected_requirements` 中明确标注接触/相交对与应分离对的案例）；一般构造案例不进本指标。
- **分子（TP）**：真值为应检出的接触/相交，分析器在 `details.affected_output_refs` / topology 检出对中正确标出且与真值匹配的案例数。
- **分母**：全部真值为"应检出"的案例（TP + FN）。
- **输出**：Detection = TP/(TP+FN)；FN（漏检）单列。检出位置/对象不匹配记为 FN，不计 TP。

### 3.5 Rejection（无效方案拒识正确率，特异度）

- **分子（TN）**：真值为应拒绝的无效/不安全方案，被正确拦下（`status=invalid` 或未作为 ready 候选接纳/落库）的案例数。
- **分母**：全部真值为"应拒绝"的案例（TN + FP）。
- **FP 定义**：无效方案被当作 ready 接纳或持久化为候选。
- **边界**：`clarification`、`blocked_route`、环境/预算导致的中止**不算产品正确拒绝**，不计 TN；这些进 D1 对应失败分类单列。

### 3.6 MES（多轮编辑成功率，沿用既有口径，本轮不主算）

按《考核指标口径》：第二轮自然语言编辑一次通过（含 H3.3 来源继承、H3.4 局部约束传递）的会话数 / 参与会话数；第三轮及以后不计入。本轮真实案例若未提供二轮会话，MES 记 `not_run`，不借单轮案例折算。

## 4. 状态机九态：判定条件与互斥关系

状态按下列**优先级**自上而下判定，命中即停，案例只归属一态。`review_required` 与 `unresolved_topology` 为**硬失败**：即使几何其余项可接受，也不计入任何通过类分子。

| 序 | 状态 | 判定条件（基于 §1.3 字段） | 通过/失败归类 |
|---|---|---|---|
| 1 | `blocked` | collection 失败 / 环境缺依赖 / provider 不可用 / 超时 / 预算拒绝；无有效计划。对应 D1 `collection_blocked`、`environment_blocked`、`model_provider`、`model_timeout`。 | 非产品失败，单列；不进 FSR/Repair/CGQ/Detection/Rejection 分母 |
| 2 | `not_run` | 未冻结、门控未触发、跳过、`dependency_pending`；本轮未执行。 | 不计通过率；单列计数 |
| 3 | `clarified` | `clarification_required=true` / `status=clarification_required`；无有效构造计划。 | 失败（FSR 失败单列），不进修复分母 |
| 4 | `unresolved_topology` | 拓扑安全存在无法自动消解的歧义/未决相交或连接，安全标记未通过；无 ready 候选。 | **硬失败**；不进任何通过分子 |
| 5 | `failed` | 有界修复上限耗尽后仍 `invalid`，H2/H3/H4 任一未通过；非上述特殊态。 | 失败 |
| 6 | `review_required` | 产出计划/候选，但验收 `review_required=true`（部分覆盖/需人工复核）。 | **硬失败**；不计 FSR/Repair 分子，即使 geometry 可接受 |
| 7 | `first_plan_pass` | 无第二次模型调用、无确定性修复、无澄清；H2/H3/H4 全通过且非 `review_required`。 | 通过（FSR 分子） |
| 8 | `model_retry_pass` | 经结构化模型重试后达到 H2/H3/H4 全通过；未走确定性修复。 | 通过，但不计 FSR；计入 Repair 模型重试桶分子 |
| 9 | `deterministic_repair_pass` | 经部件/局部确定性修复后达到 H2/H3/H4 全通过。 | 通过，但不计 FSR；计入 Repair 确定性修复桶分子 |

### 4.1 互斥与归并规则

- 通过类三态（7/8/9）互斥：按是否重试/修复的实际链路归位；一次运行最多一态。
- 失败类（4/5/6）与通过类互斥；`review_required` 优先于几何可接受性判失败。
- `unresolved_topology` 优先于 `failed`：先判拓扑未决，再判一般失败。
- `blocked` / `not_run` / `clarified` 不与产品失败混算；其计数单列。
- 状态与 D1 顶层分类的映射：`blocked`→collection/environment；`not_run`→not_run(含 dependency_pending)；`clarified`→logic_failure/clarification_required；`failed`→logic_failure 或 error_mapping_failure（按异常类型细分）。

## 5. 生产接入点锚点（只读引用，不改）

| 环节 | 文件:行号（C 基线） | 口径用途 |
|---|---|---|
| 构造入口路由守卫 | `agent_service.py:6363`（`name=='drawing_design'` 且 `operation=='create'`） | 判定是否进入构造生成链路 |
| 澄清前置 | `agent_service.py:626, 6439, 6461, 6739-6740` | `clarified` 态判定 |
| 首轮解释 | `agent_service.py:6438` | 首轮计划取证 |
| 修复循环 | `agent_service.py:6476-6478`：`construction_attempts` 入账；`while should_repair(...) and bounded_repair_available(..., max_repairs=2)` | 是否进入修复、轮次上限 |
| 失败 refs/前次计划 | `agent_service.py:6479-6498` | 失败上下文、refs、前次计划回挂 |
| 上下文路由 | `agent_service.py:6506-6509` | 部件修复 / 局部补丁 / 空上下文渠道判定 |
| 越界与仅置信度拦截 | `agent_service.py:6511-6527` | 不计候选、不放宽保存条件 |
| recovery 记录 | `agent_service.py:6587-6588, 6840-6847` | 轮次计数、attempts、终态取证 |
| 候选落库 | `agent_service.py:6792-6823` | 候选接纳/持久化计数 |
| 恢复策略 | `cad_generation_recovery.py:20-25, 49-51, 57-60` | should_repair 类别、前后计划比对、低置信度判定 |
| 评估既有指标 | `cad_construction_evaluation.py:173-183, 197-224` | schema_valid / trial_executed / retry / repair 计数对照 |

## 6. 真实模型运行与 D0 Mock 结果不可混算

### 6.1 证据模式分桶（沿用 D0 §5 / D1 §3）

| 桶 | evidence_mode | 可否进生成通过率 |
|---|---|---|
| 真实模型 | `live_model` | 可；须记 provider/model/请求响应哈希/usage/费用/延迟/`provider_attempted=true` |
| 确定性规则 | `deterministic_rule` / `rule_parser_zero_cost` | 可进规则路径通过率，**不可**进模型生成通过率 |
| 服务级 Mock | `service_mock` / `mock` | 仅证明链路/契约；**不得**换算为 CAD 生成通过率 |
| 重建夹具 | `reconstructed_fixture` | 仅证明执行器/验收器行为，不证明模型能力 |
| 历史 | `historical_report` / `historical_artifact` | 仅背景/输入存在性证据，不进本轮 outcome 分子 |
| 缺失 | `unavailable` | 不可算通过 |

### 6.2 统计硬规则

- 分子分母按桶分别计算；`live_model` 桶与规则/Mock 桶的通过率**不得合并**成一个总通过率。
- 服务级 Mock 通过数、既有历史报告中的 `N passed` 一律不进入本轮模型通过率分子/分母。
- 缺失/未执行案例数必须与分母并列写出；`provider_attempted=false` 的占位 `True` 校验位不构成联网证据。
- 样本量 `<5` 时只报逐案例三态矩阵（通过/失败）与缺陷计数，**不报百分比提升、不写"提升 X%"**（沿用《考核指标口径》诚实说明）。
- 任何聚合同时给出：分子、分母、证据模式、缺失案例数、失败/缺陷分布；不允许只报一个百分比。

## 7. 真实模型最可能返回 `blocked` / `clarified` 的环节（预判，非结果）

### 7.1 `clarified` 高易发点

- 尺寸/锚点/单位缺失或歧义（宽高、坐标基准、开放还是闭合未说明）；
- 连接约束容差或连续性等级未声明，路由器判 `ambiguous` 后进入 `model_clarification`；
- 多对象布局缺排布关系（间距、对齐、数量）；
- 编辑对象身份不明确（未选中既有图元/候选）。

### 7.2 `blocked` 高易发点

- provider 未配置 / 无 Key / `configured=false`（本地守卫拦下，非产品失败）；
- 网络超时、限流、连接被拒；
- 预算/轮次上限拒绝（`bounded_repair_available` 耗尽或预算守卫）；
- 模型输出无法解析为结构化 Schema（`model_schema`，若运行期异常归 environment/error_mapping 按 D1 细分）；
- 候选持久化失败（`candidate_persistence_failed`，按 D1 环境/件级错误单列，不算几何失败）。

> 以上为链路结构预判；实际归类以运行记录字段为准，禁止在看到结果后把 `blocked` 改判为产品失败以抬高通过率，或反之。

## 8. 本轮产出与纪律自检

- 本目录仅新增口径文档（Markdown + 机器可读 JSON 规格）；未实例化客户端、未联网、未改 `backend/app`。
- 第四轮拿到 D 案例记录后，按 §2 路由、§3 指标、§4 九态、§6 分层核算；口径冻结项（定义/阈值来源/分母/互斥优先级）不得回改。
- 若运行暴露接入缺陷：记录异常类型、行号、期望-实际证据，按线转交；不在 C 侧放宽断言或缩短循环。
