# Round9 G1b 子报告可接受状态集泛化报告（Agent C）

- 工作树：`tmp/g1-guard`；父节点 `fe63db32249205abcdb8d0677067dd597ddcbc26`（G1 护栏提交）。
- 性质：最小泛化提交；零真实模型请求；独立提交，未 amend/rebase/push/merge。
- 背景：D 对 G1 判 PARTIAL——语义通道已闭合，但同类残留在**非语义子报告**：`stroke_acceptance` / `path_relation_acceptance` / `repetition_acceptance`（及同循环的 `projection_acceptance`）在 `status='partial'`、`review_required=False`、顶层 `coverage=complete` 时仍被汇总成 `passed`、`accepted=True`。当前生产者矩阵下休眠，代码路径未排除。

## 1. 改动点（仅汇总层一处抽象）

| 位置 | 改动 |
|---|---|
| `cad_construction_interpreter.py:1254` | 新增模块级常量 `REVIEW_BLOCKING_REPORT_STATUSES = frozenset({"failed", "unverified", "review_required", "partial"})` |
| `cad_construction_interpreter.py:1257-1261` | 新增共享谓词 `_report_blocks_review(report)`：`review_required is True` 或状态落入阻断集即阻塞 |
| `cad_construction_interpreter.py:1336` | 通用汇总循环改为 `any(_report_blocks_review(report) for report in reports)`，不再内联散落状态集合 |

口径约束（按 D 的验收口径）：

- `partial` **一律**不得视为完整，不因 `review_required=False` 升格；
- 保留既有阻断集合 `{failed, unverified, review_required}` 与 `review_required is True` 标志位；
- **`not_checked` 未加入阻断集**：无适用要求的通道保持不阻塞；语义报告的适用性仍只由 A 的三态判据决定；
- 未改 `coverage` 字段本身语义，只是它不能再单独决定通过；
- 语义子报告仍只走 A 的三态判据，未退回通用循环二次判定；
- 候选保存授权、草稿可保存行为未动。

## 2. 四条反例证书（partial + review_required=False + coverage=complete）

离线构造 `source_acceptance`（含 1 个 passed 基础检查，排除 `verified_checks==0` 兜底），source 取无适用语义要求的花瓶文本。

| 通道 | 改前（父 `fe63db32` 实测） | 改后汇总 / accepted | 改后语义状态 |
|---|---|---|---|
| `stroke_acceptance` | passed / review=False / **accepted=True** | review_required / **False** | `no_applicable_requirement` |
| `path_relation_acceptance` | passed / review=False / **accepted=True** | review_required / **False** | `no_applicable_requirement` |
| `repetition_acceptance` | passed / review=False / **accepted=True** | review_required / **False** | `no_applicable_requirement` |
| `projection_acceptance` | passed / review=False / **accepted=True** | review_required / **False** | `no_applicable_requirement` |

机器可读快照：`c_round9_g1b_subreport_results.json`（`generic_partial_rows`，含 before/after）；探针：`c_round9_g1b_subreport_probe.py`；单测：`tests/test_c_round9_g1b_subreport_gate.py`（7 项）。

## 3. 正例与语义侧保持证据

| 用例 | 形态 | 改后汇总 / accepted | 语义状态 |
|---|---|---|---|
| R4 | 无语义报告（花瓶，无适用要求） | passed / **True** | `no_applicable_requirement` |
| R5 | `not_checked` + 空适用性标记 + 杂散 review=True | passed / **True** | `no_applicable_requirement` |
| T1 | 同 R5 形态（契约正例） | passed / **True** | `no_applicable_requirement` |
| T2 | 专用分支 `passed` + `regular_polygon` 对象 passed | passed / **True** | `fully_verified` |
| R1 | 语义 `partial` / review=False + heart kind | review_required / **False** | `unverified_or_partial`（`partial_overall`） |
| T8 | 五角星-only `not_checked` + `[star_profile]`（真实入口） | review_required / **False** | `unverified_or_partial`（`report_unchecked_applicable`） |
| C10 | 爱心 passed + 五角星 `not_checked` | review_required / **False** | `unverified_or_partial`（`object_not_checked` / `no_verifier`） |

G1 原探针快照已在改后重跑刷新：R1–R6 / T1 / T2 / T8 判定与 G1 提交时一致，无回退。

## 4. 回归计数对照（与父 `fe63db32` 基线）

| 套件 | 基线（fe63db32） | G1b 改后 | 说明 |
|---|---|---|---|
| 12 模块组合 | 184 passed / 0 failed | 184 passed / 0 failed | 同 Round8 d1_combo4 清单 |
| Round8 接线套件 | 15 passed / 0 failed | 15 passed / 0 failed | 无断言改动 |
| G1 新增护栏套件 | 12 passed / 0 failed | 12 passed / 0 failed | 既有断言未改 |
| G1b 新增套件 | — | 7 passed / 0 failed | 本轮新增 |
| G2 三路径套件 | 6 passed / 0 failed（g2-dynamic 提交） | 6 passed / 0 failed | 跨树只读加载 g2 测试/夹具，以本树 `backend` 代码运行；三路径汇总本就 `review_required` |
| 语义套件 `test_cad_semantic_acceptance.py` | 2 项 A 侧既有失败 | 43 passed / **2 failed** | 失败项同基线：`test_structural_counter_schema_preserves_multiple_paths_without_coordinates`、`test_unsupported_styles_and_multiple_objects_are_not_falsely_fully_verified`，归属 A 侧，未触碰其模块 |
| 相邻 16 套件（候选保存/可见性门/编辑门/关系验收/对象约束/构造评估/最终源契约/恢复/提交/权威证据/项目候选/需求台账/路径/描边/投影/重复） | 162 passed / 0 failed | 162 passed / 0 failed | 草稿保存授权未变 |
| 其余验收相关 cad 文件（源验收/结构契约/组合/编辑关系/断言批次/断言/特征契约/反事实守卫/创建身份/候选编排/选定操作/草图图/参数化/计划校验/计划恢复/本地修复/模板计划/人工复核/对象约束） | 未在基线逐文件计数 | 257 passed / **3 failed** | 3 项失败已在基线提交上复跑确认存在（见下条），为持久化/数据库状态相关既有失败，非本轮引入 |

- 已在基线提交上 `stash` 本轮改动复跑确认：`test_cad_counterfactual_guard.py` 两项、`test_cad_template_plan.py::test_template_chat_and_toolbar_commit_same_project_once` 基线即失败。
- 收集期既有环境缺口（基线即存在，未纳入计数）：历史回放、验收指标、语料审计、产品验收运行器、flash 预算、p12 预算、记录修复输入、用户语料运行器——依赖未入库 `tests.manual` 包或缺失数据文件。

## 5. 仍存在的"不可达但可复现"错误接受形态（审计）

1. **报告级 `passed` 但内部检查未闭环**：本门禁只读报告顶层 `status` 与 `review_required`；若生产者把内含 failed/partial 检查项的子报告标成顶层 `passed`，汇总不会逐条复核 checks 状态。触发条件：通道验收器返回 `status='passed'` 而 `checks` 中存在非 passed 条目。当前各通道验收器未观察到该形态。
2. **非语义通道 `not_checked` 适用性盲区**：stroke/path_relation/repetition/projection 的存储门仍按 `status != 'not_checked'` 决定是否挂接（解释器 `:967/:971/:984/:988`），这些通道没有适用性标记字段；若某通道在源文本存在适用要求时仍返回 `not_checked`，报告不进汇总，门禁看不到。触发条件：通道 verifier 对适用需求输出 `not_checked` 且未抛结构契约错误。语义侧同款盲区已由 G1 适用性标记关闭，非语义侧尚无对应标记。
3. **候选谓词不重复实现判断**：门禁只消费汇总收敛结论；绕过汇总直接构造候选时，谓词不做语义/子报告复核。架构边界，继承自 G1 §6。
4. **源侧星形词表识别缺口（D 登记，本轮未改词表）**：源侧仅识别『五角星｜五芒星｜星形轮廓』，『星形／五角形／星星』不进入适用性标记，仅靠几何 profile 兜底。已登记为已知缺口，留待后续轮次。

## 6. 边界与未决

- 未放宽 H2/H3/H4；未改 `max_repairs`；未改候选保存/草稿授权；未加五角星验收器/生成器；未改 A 两个模块；未改上一提交既有断言（仅新增测试与探针）。
- 未改冻结输入；未重跑 A9；S1 冻结；全程 0 真实模型请求。
- G1 探针结果 JSON 为本轮改后重跑刷新（时间戳与提交 SHA 更新，判定值无变化）。

## 7. 复现命令（`backend/` 目录）

- G1b 探针：`python evaluations/v1/round9/c_round9_g1b_subreport_probe.py --out evaluations/v1/round9/c_round9_g1b_subreport_results.json`
- G1b 单测：`python -m pytest tests/test_c_round9_g1b_subreport_gate.py -q`
- 组合回归：`python -m pytest tests/test_cad_requirement_contract.py tests/test_cad_plan_component_repair.py tests/test_cad_final_source_contract.py tests/test_cad_construction_interpreter.py tests/test_candidate_visibility_gate.py tests/test_cad_construction.py tests/test_cad_topology_safety_b1.py tests/test_cad_topology_safety_b11.py tests/test_cad_topology_safety_b12.py tests/test_c1_integration_mock.py tests/test_c11_service_two_round_mock.py tests/test_c12_production_loop_mock.py tests/test_c_round8_caller_wiring.py tests/test_c_round9_g1_summary_guard.py tests/test_c_round9_g1b_subreport_gate.py -q`
