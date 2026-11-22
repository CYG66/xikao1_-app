# D0 可执行评测方案

- 适用基线：`9bd105fed075c717df88774f7abb4cd4e7a21c3a`
- 适用分支：`v1/d0-baseline`
- 当前状态：方案已定义，尚未执行
- 真实模型：禁止调用
- 生产代码：禁止修改
- 冻结输入：禁止修改

## 1. D0 的目标

D0 不是“跑一个总分”，而是建立一套可审计、可复现、不会被历史报告冒充的评测基线，回答四个问题：

1. 当前后端在哪些输入上能确定性完成构造？
2. 哪些失败是模型规划问题，哪些是后端执行/验收问题？
3. 哪些结果来自本轮真实执行，哪些只是历史报告或重建 fixture？
4. A1/B1/C1 改进后，是否在同一入口上产生可比较的变化？

## 2. 目录与文件

D0 执行时在 `backend/evaluations/v1/` 下生成：

```text
D0_可信基线审计报告.md
case_registry.json
evaluation_schema.json
mock_replay_results.json
D0_失败根因分类.md
```

本轮已生成的 R0 产物：

```text
R0_GITHUB_ASSET_AUDIT.md
r0_asset_manifest.json
D0_EVALUATION_PLAN.md
A1_B1_C1_TASK_BREAKDOWN.md
```

## 3. 案例注册表 `case_registry.json`

### 3.1 必填字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `case_id` | string | `A9`、`S1`、`M1` |
| `category` | string | `historical_regression`、`new_unseen_synthetic_case`、`mechanical_cusp` |
| `original_input` | string | 冻结原文；M1 未冻结时为空并标记 |
| `input_sha256` | string | canonical 输入哈希；M1 未冻结时为 `null` |
| `input_hash_scope` | string | `canonical_json(cases)` / `raw_text` / `null` |
| `expected_route` | string | `construction_scope`、`clarify`、`unfrozen` |
| `expected_requirements` | object | 尺寸、端点、锚点、段数、连续性等 |
| `acceptance_rules` | object | 逐条可计算判据 |
| `freeze_status` | string | `frozen` / `unfrozen` |
| `source_file` | string | 冻结文件相对路径 |
| `evidence_mode` | string | 见第 5 节 |
| `notes` | string | 缺失、限制、历史证据说明 |

### 3.2 A9 条目

```json
{
  "case_id": "A9",
  "category": "historical_regression",
  "original_input": "生成一个左右对称、平滑闭合的爱心，中心在(2,3)，宽4米高4米",
  "input_sha256": "726a5da06e2130c9a4f4b905ece27cc1c3fa922e931f079de4e57243183054c3",
  "input_hash_scope": "canonical_json(cases)",
  "case_sha256": "62033ab7da73ad4924421de70f7ec53ae8b694c174364cb103cff34e561e075e",
  "prompt_sha256": "af12df04393e1da42acd9eae6e590f81fa8c66a4720c546c9d292fef89707d5b",
  "expected_route": "construction_scope",
  "expected_requirements": {
    "width_mm": 4000,
    "height_mm": 4000,
    "center_mm": [2000, 3000],
    "closed": true,
    "no_self_intersection": true,
    "semantic_features": ["left_lobe", "right_lobe", "center_notch", "lower_tip"],
    "continuity": "measure_C0_and_C1_without_inventing_point_exemptions"
  },
  "freeze_status": "frozen",
  "source_file": "backend/evaluations/p1.3e_dual_case_frozen.json",
  "evidence_mode": "historical_report",
  "notes": "历史计划 service-step-3.json 未入库，精确回放不可用；不得伪造原始响应。"
}
```

### 3.3 S1 条目

```json
{
  "case_id": "S1",
  "category": "new_unseen_synthetic_case",
  "original_input": "新建一条开放式、平滑的 S 形曲线，使用 3 段三次 Bezier 曲线连接。起点为 (0,0) 米，依次经过 (2,1) 米、(4,-1) 米，终点为 (6,0) 米。两处内部连接点必须满足 C1 连续，不允许尖点或自交，曲线不闭合。",
  "input_sha256": "6a9e00fd6013030b69429265091b4afc9e45af8e3b1d9a485e6bafb983ce6b06",
  "input_hash_scope": "canonical_json(case)",
  "case_sha256": "6a9e00fd6013030b69429265091b4afc9e45af8e3b1d9a485e6bafb983ce6b06",
  "prompt_sha256": "5a7cc0fb6444bc85291d74e751c134984e85e772c805127b58f9faed83c047bb",
  "expected_route": "construction_scope",
  "expected_requirements": {
    "open": true,
    "endpoints_m": [[0, 0], [6, 0]],
    "internal_anchors_m": [[2, 1], [4, -1]],
    "bezier_segments": 3,
    "continuity": "C1",
    "tangent_tolerance_deg": 0.01,
    "no_self_intersection": true,
    "no_degenerate_segments": true
  },
  "freeze_status": "frozen",
  "source_file": "backend/evaluations/p1.3e_dual_case_frozen.json",
  "evidence_mode": "reconstructed_fixture",
  "notes": "冻结输入存在；原始模型响应和完整 S1 计划不存在。可由人工构造三段三次 Bezier fixture 做执行器回归，但不能据此声称模型通过。"
}
```

S1 条目的哈希口径必须写清：

- `input_sha256` 使用 `canonical_json(case)`，值为 `6a9e00fd...`。
- `prompt_sha256` 是原始 `prompt` 文本的 SHA256，值为 `5a7cc0fb...`。
- 文件整体的 `frozen_input_sha256=726a5d...` 是整个 `cases` 对象的哈希，不能直接当作 S1 单例哈希，除非把 `input_hash_scope` 写成 `canonical_json(cases)`。
- 三种口径可以在 registry 中并存，但字段名和 scope 必须一一对应，不得混写。

### 3.4 M1 条目

```json
{
  "case_id": "M1",
  "category": "mechanical_cusp",
  "original_input": null,
  "input_sha256": null,
  "input_hash_scope": null,
  "expected_route": "unfrozen",
  "expected_requirements": {},
  "acceptance_rules": {},
  "freeze_status": "unfrozen",
  "source_file": null,
  "evidence_mode": "unavailable",
  "notes": "缺自然语言、单位、折角位置、允许的曲线连接和独立验收字段；不得自行编造，不纳入 D0 评分。"
}
```

## 4. 六维评测 Schema `evaluation_schema.json`

每个案例每次运行记录一个 `run` 对象。

### 4.1 `model`

| 字段 | 说明 |
|---|---|
| `provider` | `deepseek` / `local` / `mock` / `null` |
| `model` | 模型名；未调用时为 `null` |
| `request_id` | 请求 ID；Mock 时可为 `null` |
| `request_sha256` | 发送给模型的结构化请求哈希；未调用为 `null` |
| `response_sha256` | 原始响应哈希；未调用为 `null` |
| `usage` | prompt/completion/total tokens；未调用为 `null` |
| `cost_usd` | 费用；零费用为 `0`，未调用为 `null` |
| `latency_ms` | 延迟；未调用为 `null` |
| `provider_attempted` | 是否真的尝试了 provider |
| `evidence_mode` | 见第 5 节 |

### 4.2 `planning`

| 字段 | 说明 |
|---|---|
| `route` | `rule` / `structured_model` / `clarification` / `unfrozen` |
| `question_key` | 澄清键；无则 `null` |
| `plan_sha256` | 规范化构造计划哈希 |
| `step_count` | 步骤数 |
| `ops` | 操作类型列表 |
| `units` | 单位 |
| `model_attempted` | 是否调用模型 |
| `retry_count` | 结构化重试次数 |

### 4.3 `source`

| 字段 | 说明 |
|---|---|
| `contract_version` | H2 契约版本 |
| `source_index_sha256` | H3 来源索引哈希 |
| `requirement_refs` | 需求来源 ID 列表 |
| `junction_constraints` | 局部连接约束原文 |
| `h3_status` | `pass` / `fail` / `not_run` |
| `h3_failures` | 失败项列表 |

### 4.4 `geometry`

| 字段 | 说明 |
|---|---|
| `geometry_hash` | 几何结果规范化哈希 |
| `bounds_mm` | 包围盒 |
| `closed` | 是否闭合 |
| `segment_count` | 段数 |
| `sample_count` | 采样点数 |
| `self_intersection_count` | 自交数量 |
| `self_intersection_pairs` | 冲突段对 |
| `exact_intersection_pairs` | 精确曲线交点；B1 前为 `null` |
| `degenerate_segments` | 退化段数量 |
| `c0_c1_report` | 连接连续性测量结果 |

### 4.5 `acceptance`

| 字段 | 说明 |
|---|---|
| `h2_status` | `pass` / `fail` / `not_run` |
| `h3_status` | `pass` / `fail` / `not_run` |
| `h4_status` | `pass` / `fail` / `not_run` |
| `source_status` | 来源验收 |
| `semantic_status` | 语义验收 |
| `failed_checks` | 失败项及原因 |
| `review_required` | 是否需人工复核 |

### 4.6 `version`

| 字段 | 说明 |
|---|---|
| `project_id` | 项目 ID；无则 `null` |
| `variant_id` | 候选 ID；无则 `null` |
| `parent_variant_id` | 父版本 ID；无则 `null` |
| `run_id` | Agent run ID；无则 `null` |
| `conversation_id` | 会话 ID；无则 `null` |
| `candidate_status` | `prepared` / `persisted` / `selected` / `rejected` / `not_run` |
| `persisted` | 是否落库 |

### 4.7 `outcome`

| 字段 | 说明 |
|---|---|
| `status` | `pass` / `fail` / `not_run` / `unknown` / `blocked` |
| `failure_class` | 第 6 节分类 |
| `evidence_completeness` | `complete` / `partial` / `missing` |
| `unknown_fields` | 未取得字段列表 |

## 5. `evidence_mode` 定义

| 值 | 含义 | 可否算通过 |
|---|---|---|
| `live_model` | 本轮真实模型调用 | 可以，但必须记录费用/请求/响应 |
| `historical_report` | 仓库内历史报告的描述 | **不可以**；只能作为背景证据 |
| `historical_artifact` | 仓库内真实存在的历史文件（如冻结 JSON） | 只能证明输入存在，不证明执行通过 |
| `reconstructed_fixture` | 依据冻结输入人工重建的计划/几何 | 只能证明执行器行为，不证明模型能力 |
| `mock` | 明确的 Mock callback 或假 provider | 只能证明链路/契约，不证明模型能力 |
| `deterministic_rule` | 不调用模型的规则解析/执行 | 可以证明规则路径，不证明模型路径 |
| `unavailable` | 原始响应或计划缺失 | 不可算通过 |

规则：

- 同一案例的不同维度可以使用不同 `evidence_mode`，但必须逐维度标注。
- `historical_report` 中的 `74 passed`、`118 passed`、`127 passed` 只能写进 `historical_evidence`，不能写进本轮 `outcome`。
- 没有原始模型响应的案例，`model.response_sha256` 必须为 `null`，不能填一个“重建响应”的哈希冒充原始响应。
- 任何 `reconstructed_fixture` 必须在 `notes` 中写明“非原始模型输出”。

## 6. 失败根因分类

| `failure_class` | 含义 | 典型位置 |
|---|---|---|
| `environment_blocked` | 依赖/Python/测试环境不足 | pytest/import |
| `missing_artifact` | 冻结计划、原始响应、手工语料缺失 | `tests/manual`、A9 历史计划 |
| `model_provider` | 无 Key、provider 不可用、预算拒绝 | `agent_service.configured` |
| `model_timeout` | 模型超时/限流 | transport |
| `model_schema` | 模型输出不符合结构化 Schema | interpreter |
| `planning_route` | 错误澄清/错误路由 | `clarify_construction_request` |
| `planning_topology` | 全局拓扑错误、闭合回穿 | A9 段 0/5 |
| `constraint_inheritance` | 修复链丢失 `junction_constraints` | `cad_plan_component_repair` |
| `source_provenance` | H3 来源缺失/不匹配 | `validate_junction_source_refs` |
| `geometry_execution` | 执行器拒绝/几何失败 | `execute_construction_plan` |
| `self_intersection` | 自交拒绝 | `_validate_composite_path_quality` |
| `continuity` | C0/C1/G1 失败 | `_validate_composite_path_quality` |
| `acceptance_source` | 来源验收失败 | `verify_final_source_contract` |
| `acceptance_semantic` | 语义验收失败 | `verify_semantic_requirements` |
| `candidate_persistence` | 候选保存失败 | `persist_prepared_candidate` |
| `version_binding` | 父版本/会话绑定错误 | `effective_parent_variant` / HTTP |
| `http_contract` | 请求/响应契约错误 | `agent_http_service` |
| `test_harness` | 测试本身不可收集/不可复现 | `tests/manual` |
| `unclassified` | 无法归类 | 需人工复核 |

`review_required` 是独立状态，不是失败分类。

## 7. 零费用与隔离约束

D0 执行时必须满足：

1. `XLINE_AGENT_PROVIDER=local`，或确保 `configured=False`。
2. 不设置 `DEEPSEEK_API_KEY`。
3. 不运行 `run_cad_construction_benchmark.py` / `run_extended_deepseek_benchmark.py`。
4. Mock callback 中若被调用，直接 `raise AssertionError("unexpected live model call")`。
5. `provider_attempted` 必须为 `false`；若为 `true`，该次运行作废。
6. 所有 store 路径指向临时目录：
   - `XLINE_DATABASE_PATH`
   - `XLINE_AGENT_RUN_STORE`
   - `XLINE_AGENT_PLAN_STORE`
   - `XLINE_AGENT_MEMORY_STORE`
   - `XLINE_AGENT_TASK_STORE`
   - `XLINE_AGENT_AUDIT_STORE`
   - `XLINE_CREATIVE_PROJECT_STORE`
   - `XLINE_DRAWING_VERSION_STORE`
7. 不写真实 `backend/data/`、不写用户配置、不写真实附件目录。
8. 任何写入型测试必须在 `tmp_path` 或 `tempfile.mkdtemp()` 下运行。

## 8. 执行阶段

### D0-0 环境准入

前置条件：

- 独立 venv。
- `requirements.txt` 安装完成。
- `pytest`、`httpx` 安装完成。
- `python -m pytest --version` 成功。
- `python -c "import fastapi, pydantic, shapely, ezdxf"` 成功。

任一失败：D0 整体标记 `blocked`，不得用历史报告代替。

### D0-1 注册表冻结

- 写入 A9/S1/M1 三条记录。
- A9/S1 校验冻结文件哈希：
  - 文件 SHA256 `35932E...`
  - canonical `cases` SHA256 `726a5d...`
- M1 保持 `unfrozen`，不执行。

产物：`case_registry.json`、`evaluation_schema.json`。

### D0-2 确定性规则基线

目标：只跑不调用模型的路径。

- 运行 `pytest backend/tests/test_cad_construction.py`
- 运行 `pytest backend/tests/test_cad_construction_interpreter.py`
- 运行 `pytest backend/tests/test_cad_plan_component_repair.py`
- 运行 `pytest backend/tests/test_cad_requirement_contract.py`
- 运行 `pytest backend/tests/test_cad_source_acceptance.py`
- 运行 `pytest backend/tests/test_cad_semantic_acceptance.py`

记录：

- 收集数、通过数、失败数、跳过数。
- 失败堆栈原文。
- 测试命令与 Python/包版本。

不要声称“全量通过”；只记录所跑文件。

### D0-3 A9 历史诊断 fixture

只能做两件事：

1. 记录历史报告中的 A9 失败证据：
   - 段 0/5 交叉；
   - 采样边 `[5,186]`；
   - 交点约 `(2.0, 3.5289)` m；
   - 根因是模型控制点回穿。
2. 用历史报告中的两段控制点建立**局部诊断 fixture**：
   - 段 0：`[(2.0,3.1),(2.15,3.9),(1.45,4.55),(0.65,4.55)]`
   - 段 5：`[(3.35,4.55),(2.55,4.55),(1.85,3.9),(2.0,3.1)]`
   - 只验证“这两段三次 Bezier 是否相交”，不验证完整爱心，不冒充 A9 端到端。

记录：

- `evidence_mode=historical_report` 或 `reconstructed_fixture`。
- `outcome=unknown` 对于 A9 端到端；局部 fixture 可以 `pass`（成功检测到交叉），但不得写成 A9 通过。

### D0-4 S1 重建 fixture

S1 原始模型响应不存在。允许人工构造一个满足冻结约束的三段三次 Bezier 计划，用于执行器回归：

- 起点 `(0,0)`，内部锚点 `(2,1)`、`(4,-1)`，终点 `(6,0)`。
- 3 段三次 Bezier。
- 两个内部连接点 C1，切线角误差 ≤ 0.01°。
- 开放、无自交、无退化段。

要求：

- `evidence_mode=reconstructed_fixture`。
- 记录控制点、参数范围、切线角、几何哈希。
- 只证明执行器和验收器能处理满足约束的计划。
- 不证明模型能生成 S1。
- 不写成“S1 通过”。

### D0-5 Mock 重放

Mock 的目标是验证链路，不是验证模型能力。

Mock A：结构化解释回调

- 固定 callback 返回一个合法 `CadConstructionPlan`。
- 断言 `provider_attempted=False`。
- 断言 `persisted=False`、`project_persistence=False`。
- 记录 `plan_sha256`、`geometry_hash`、验收结果。

Mock B：空计划/非法计划

- 返回缺字段、错单位、错步骤的计划。
- 断言解释器拒绝，错误分类为 `model_schema` 或 `geometry_execution`。
- 不降低断言。

Mock C：修复链

- 输入一个含非空 `junction_constraints` 的计划。
- 模拟部件修复返回空数组。
- 断言 A1 修复前：约束丢失；A1 修复后：约束保留。
- 该测试在 A1 前记录为 `fail`，A1 后重跑为 `pass`。

产物：`mock_replay_results.json`，每条包含 `case_id`、`mock_id`、`evidence_mode`、`outcome`、`failure_class`、`plan_sha256`、`geometry_hash`、`assertions`。

### D0-6 HTTP 端到端（可选，需单独准入）

前置条件：

- 依赖安装完成。
- `httpx` 可用。
- 临时 store 配置完成。
- Mock provider 可用，真实 provider 不可用。
- 用户明确同意运行 HTTP 测试。

流程：

1. `POST /api/agent/chat`，`mode=advanced` 或 `work`，带 `conversation_id`、`client_id`。
2. 断言返回 `agent_run_id`，run 状态 `completed`。
3. 若产生候选，读取项目/版本。
4. `POST` 保存候选图纸。
5. 选择版本。
6. 带同一 `conversation_id` + `variant_id` 发起第二轮编辑。
7. 断言父版本、需求来源索引、候选状态。
8. 断言全程 `provider_attempted=False`。

若依赖不满足，HTTP 维度标记 `blocked`，不得用单元测试替代。

### D0-7 报告

`D0_可信基线审计报告.md` 必须逐案例给出：

```text
case_id
freeze_status
evidence_mode
model / planning / source / geometry / acceptance / version
outcome
failure_class
unknown_fields
```

并明确：

- 哪些结果是本轮执行。
- 哪些是历史报告。
- 哪些是重建 fixture。
- 哪些没有执行。
- 哪些字段 `unknown` 或 `not_checked`。

## 9. A9/S1/M1 的 D0 预期状态

| 案例 | 预期状态 | 说明 |
|---|---|---|
| A9 | `unknown` | 历史失败已知；精确计划缺失；本轮未执行 |
| S1 | `unknown` | 路由已修复；无原始模型响应；几何未验证 |
| M1 | `not_run` | 未冻结；不纳入评分 |

不得为了让表格好看而把 `unknown` 改成 `pass`。

## 10. 统计规则

- 只有 `evidence_mode=live_model` 或 `deterministic_rule` 的本轮执行结果可以进入通过率分子/分母。
- `historical_report`、`historical_artifact`、`reconstructed_fixture`、`mock` 不计入模型成功率。
- 样本数 < 3 时，不计算“整体提升率”。
- 任何聚合指标必须同时给出：
  - 分子、分母；
  - 证据模式；
  - 缺失案例数；
  - 失败分类分布。
- 不允许只报一个百分比。

## 11. D0 完成判定

D0 完成的最低条件：

1. `case_registry.json` 存在且 A9/S1 哈希校验通过。
2. `evaluation_schema.json` 覆盖六维和 `outcome`。
3. 至少完成以下之一：
   - 确定性规则专项测试；
   - Mock 重放；
   - 历史证据入库。
4. `mock_replay_results.json` 每条都有 `evidence_mode` 和 `outcome`。
5. `D0_失败根因分类.md` 至少覆盖本轮实际出现的失败。
6. `D0_可信基线审计报告.md` 明确列出 `unknown` / `not_run` / `blocked`。
7. 未调用真实模型，未污染生产数据。

不满足以上条件，不得宣布 D0 完成。

## 12. 下一步

D0 执行完成后，按以下顺序进入：

```text
A1 约束继承
B1 精确曲线求交与拓扑安全修复
C1 HTTP 端到端
D1 统一回归
```

A1/B1 可以并行，但必须共用本 D0 的 `case_registry.json` 和 `evaluation_schema.json`；C1 在 D0 完成后启动，最终在 A1/B1 合入后做一次统一回归。
