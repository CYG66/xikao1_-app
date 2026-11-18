# Round9 G1 汇总护栏报告（Agent C，生产调用方接线）

- 工作树：`tmp/g1-guard`；父节点 `2989e8c42fff3fed73720d2b2e399046ef966645`（基线 `07bd888f8c888a543d1983d8246f35d5939351e8`）。
- 性质：最小生产接线护栏；零真实模型请求；未合并/推送/amend/rebase。
- 判据来源：A 的 `semantic_requirement_state` / `state_allows_summary_passed` / 注册表，复用未另造；未改 A 两个模块。
- 证据快照：`c_round9_g1_guard_results.json`；探针：`c_round9_g1_guard_probe.py`；单测：`tests/test_c_round9_g1_summary_guard.py`（12 项）。

## 1. 改动文件与关键 Diff

| 文件 | 改动 |
|---|---|
| `app/cad_construction_interpreter.py` | 存储门保留适用报告；汇总层语义报告走 A 三状态判据；覆盖完整性不再以 coverage 字符串为唯一证据；输出可审计字段 |
| `tests/test_c_round8_caller_wiring.py` | 原“残留缺陷”用例改为护栏闭合后的断言（同一形态：partial/review=False + complete 覆盖，现必须不被接受） |
| `tests/test_c_round9_g1_summary_guard.py` | 新增 G1 护栏 12 项零模型用例 |
| `evaluations/v1/round9/c_round9_g1_guard_probe.py` / `.json` | 探针与机器可读真值表 |

### 1.1 存储门（正常构造路径，解释器内）

- 位置：`cad_construction_interpreter.py:973-980`。
- 改前：`if semantic_acceptance['status'] != 'not_checked'` 才挂接；整体 `not_checked` 的适用强制需求（如五角星能力缺口）被整体丢弃，汇总看不到。
- 改后：`applicable_requirement_kinds` 非空即保留；仅当适用性标记为空（等价无适用要求）且状态 `not_checked` 时才丢弃，与旧无操作路径一致。

### 1.2 汇总层判据

- 汇总入口：`construction_acceptance_summary`（`:1286`），新增可选参数 `source`；生产调用点 `:1218` 传入 `source=original_requirement`。
- 辅助函数：
  - `_source_recognizes_mandatory_kind`（`:1248`）：报告缺失时，仅当源文本本身识别到注册表内强制 kind 才保守阻塞；无信号保持旧的不阻塞语义。
  - `_semantic_summary_verdict`（`:1267`）：字典报告直接交 `semantic_requirement_state(report, source)`；缺失报告按“有源信号→`report_unavailable` 阻塞 / 无信号→`no_applicable_requirement` 不阻塞”合成裁决。
- 语义报告隔离（`:1311-1319`）：`semantic_acceptance` 不再进入通用 `report_requires_review` 循环，避免“无适用要求但自带 `review_required=True`”的旧报告把 T1 正例误判失败；阻塞与否只由 `state_allows_summary_passed(verdict)` 决定。
- 覆盖完整性（`:1344-1349`）：`coverage in {complete,full}` 且 `unknown_requirements` 为空之外，还必须 `not semantic_blocks`；语义未闭环时不得记为完整覆盖。
- 审计字段（返回体 `:1364-1367`）：`semantic_requirement_state`、`semantic_applicable_requirement_kinds`、`semantic_incomplete_objects`、`semantic_incomplete_reasons`。

### 1.3 门禁谓词

`candidate_is_accepted` / `authoritative_acceptance_summary`（`cad_candidate_state.py`）**未新增分支、未改候选保存授权**；护栏在汇总层已把阻塞形态置为 `review_required=True`，候选谓词照常消费汇总结论。待复核草稿（`candidate_is_reviewable_draft`）的既有授权条件未动。

## 2. 修改前后真值表（R1–R6 + T1/T2/T8）

每行均带 1 个 passed 基础检查，排除 `verified_checks==0` 兜底。

| 行 | 输入 | 改前汇总/accepted | 改后汇总/accepted | 改后状态 | 主要原因码 |
|---|---|---|---|---|---|
| R1 | complete 覆盖；`partial` / `review_required=False`；heart kind | **passed / True** | review_required / **False** | `unverified_or_partial` | `partial_overall` |
| R2 | complete；`partial` / `review_required=True` | review_required / False | review_required / False | `unverified_or_partial` | `partial_overall` |
| R3 | complete；`unverified` | review_required / False | review_required / False | `unverified_or_partial` | `report_unverified` |
| R4 | complete；无语义报告（花瓶，无适用要求） | passed / True | passed / **True** | `no_applicable_requirement` | — |
| R5 | complete；`not_checked` / `review_required=True`；适用性为空 | review_required / False | passed / True | `no_applicable_requirement` | —（隔离后不再被杂散标志误杀，见 §5 说明） |
| R6 | partial 覆盖；`partial` / `review_required=False` | review_required / False | review_required / False | `unverified_or_partial` | `partial_overall` |
| T1 | 无适用要求；`not_checked` + 空标记（杂散 `review_required=True`） | 旧通用循环会误判复核 | passed / **True** | `no_applicable_requirement` | — |
| T2 | 专用分支 `passed`；`regular_polygon`；对象 passed | — | passed / **True** | `fully_verified` | — |
| T8 | 五角星-only；`not_checked` + `[star_profile]` | 报告被丢弃，汇总不可见 | review_required / **False** | `unverified_or_partial` | `report_unchecked_applicable` |

## 3. 真实生产入口证据（本地 Mock，零模型）

### 3.1 单五角星（T8 入口形态）

- 请求：“生成一个五角星，外接圆半径2米”；解释器 `ready`，未被前置拦截。
- 语义报告**已保留**：`status=not_checked`、`review_required=True`、`applicable_requirement_kinds=[star_profile]`；旧守卫在此处会丢弃。
- 入口汇总：`review_required=True`、`semantic_requirement_state=unverified_or_partial`、原因 `report_unchecked_applicable`；`candidate_is_accepted=False`。
- 本次入口 `verified_checks=0`、`coverage=partial` 仍为既有兜底；语义护栏独立给出阻塞裁决并登记缺口。

### 3.2 既有通道回归（真实入口/执行器夹具）

- C10 爱心+五角星：爱心对象 `passed`、五角星 `not_checked`；汇总 `unverified_or_partial`，原因含 `object_not_checked` / `no_verifier`，受拖累对象几何 `[2]` 入 `semantic_incomplete_objects`，不接受。
- C26 大写 A：继承 `partial + review_required=False`；汇总 `unverified_or_partial`（`partial_overall`），不接受。
- 房屋：真实入口 `partial + review_required=False`；汇总阻塞，不接受。
- A1 / A9 重建夹具：爱心通道阻塞，不接受；夹具明确为本模块本地重建，非历史回放。
- 未知 kind：`unverified + no_verifier_for_kind`；原因 `unknown_kind` / `no_verifier`，不接受。
- 缺失报告：源文本识别到强制 kind → `report_unavailable` 阻塞；无信号源（花瓶）→ 不阻塞，保持旧通过语义。

## 4. 回归计数（前后对比）

| 套件 | 改前 | 改后 | 说明 |
|---|---|---|---|
| 语义套件 `test_cad_semantic_acceptance.py` | 19 passed / 2 failed | 19 passed / 2 failed | 两项失败为 A 模块既有，基线即存在，非本轮引入 |
| 12 模块组合回归 | 184 passed / 0 failed | 184 passed / 0 failed | 清单同 Round8 d1_combo4 |
| 12 模块组合 + Round8 接线套件 + 本轮 G1 套件 | — | 211 passed / 0 failed | 184 + 15 + 12 |
| 相邻套件（候选保存/可见性门/编辑门/关系验收/对象约束/构造评估/最终源契约/恢复/提交/权威证据/项目候选/需求台账/路径/描边/投影/重复 16 文件） | 未在基线单独计数 | 162 passed / 0 failed | 无新增失败；草稿可保存授权未变 |

- 收集期既有环境缺口（基线即存在）：`test_cad_history_replay.py`、`test_cad_acceptance_metrics.py` 依赖未入库的 `tests.manual` 包，本地收集报错，未纳入本轮计数。
- A 模块既有失败两项：`test_structural_counter_schema_preserves_multiple_paths_without_coordinates`、`test_unsupported_styles_and_multiple_objects_are_not_falsely_fully_verified`，归属 A 侧，未触碰其文件。

## 5. 口径与边界说明

- R5/T1 行为变化：语义报告从通用复核循环移出后，适用性为空的 `not_checked` 报告不再因杂散 `review_required=True` 被误判失败；这是契约 T1 正例要求的隔离，不影响真实适用需求的阻塞。
- `coverage` 不再是唯一证据：即使生产者输出 `complete` 覆盖且无 unknown，适用但未闭环的语义通道仍阻塞完整验收。
- 未把所有 `not_checked` 一律判失败：仅“适用强制 kind 未闭环”阻塞；`no_applicable_requirement` 放行。
- 未放宽 H2/H3/H4；未改 `max_repairs`；未改候选保存授权条件；未新增五角星专用验收器/专用生成器；未改 FEATURE-CONTRACT 公共接口；未改冻结输入；未重跑 A9；未启动 S1。
- A 模块文件（`cad_semantic_dispatch.py`、`cad_semantic_acceptance.py`）不在本轮变更集内。

## 6. 仍存在的不可达/条件性错误接受条件（审计）

1. **缺失报告的源信号盲区**：缺失报告分支依赖 `semantic_requirements(source)` 识别强制 kind；`star_profile` 仅在报告对象分类器/适用性标记中识别，不在源文本要求列表内。若未来某路径在包装器产出报告前就把语义结果丢弃，源信号探测不到星形，缺失报告护栏不会从源侧阻塞。当前生产流程包装器总是先产出报告，且保留门已按适用性标记留存，此路径当前不可达；属待观察残留。
2. **其余 `*_acceptance` 子报告**：路径关系/描边/投影/重复四个子报告仍走通用状态集合与标志位判定，本轮未接 A 三状态判据；其 `partial` 形态口径维持原状，后续轮次按需评估。
3. **候选谓词未重复实现判断**：门禁只消费汇总收敛结论；若汇总层被绕过直接构造候选，现有谓词不做语义复核。属架构边界，非本轮补丁范围。

## 7. `unverified` / 未完成项清单

| 项 | 状态 | 处置口径 |
|---|---|---|
| 五角星（star_profile） | 无后端验收器；报告 `not_checked` + `report_unchecked_applicable` | 能力缺口，阻塞 PASS；未新增专用验收器 |
| C10 五角星对象 | 对象级 `not_checked`，`no_verifier_for_star_profile` | 登记缺口，不计 PASS |
| 房屋 / 大写 A | 继承 `partial + review_required=False` | 护栏判 `unverified_or_partial`，不得升格；通道本身的完整语义关系验收留待后续 |
| 单爱心 | `partial + review_required=True` | 部分特征口径，阻塞 PASS |
| 未知 kind | `unverified / unsupported_semantic_kind` | `unknown_kind` + `no_verifier`，不计 PASS |

## 8. 提交与复现

- 一个独立提交，父节点 `2989e8c4…`；未 amend/rebase/push/merge。
- 复现（`backend/` 目录）：
  - `python evaluations/v1/round9/c_round9_g1_guard_probe.py --out evaluations/v1/round9/c_round9_g1_guard_results.json`
  - `python -m pytest tests/test_c_round9_g1_summary_guard.py tests/test_c_round8_caller_wiring.py -q`
