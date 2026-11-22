# C Round11：R-04 第三轮 语族来源边界保留接线（Agent C）

- 性质：最小接线；零真实模型请求、无网络访问；未改冻结输入、未重跑 A9。
- 基准父节点：A 第三轮提交 `e2f343775af15466d612a974006c51a404aa552a`（父 `7c25d15…`）；本提交独立，父节点为 `e2f3437`，不 amend / rebase / push / merge。
- 改动范围：调用端缺失报告兜底判据一处 + 调用端测试与本轮产物；A 的两个语义模块未改；三态判定逻辑与四值裁定取值未改。

## 1. A 第三轮交付确认（`e2f3437`）

A 只改 `cad_semantic_acceptance.py`、`cad_semantic_dispatch.py`，加测试与文档；解释器与门禁未改。新增四类"已识别但无验收器"星形语族 kind：

| kind | 触发措辞（A 词表） |
|---|---|
| `four_pointed_star` | `四角星` / `四角星形` |
| `six_pointed_star` | `六角星` / `六角星形` / `六芒星` |
| `asterisk` | `星号` / `asterisk` |
| `star_family_generic` | `draw a star` / `five-pointed star` / 独立 `star` 词 |

语族报告形态（A 侧产出，调用端只消费）：`status=unverified`、`coverage=unsupported_semantic_kind`、`review_required=True`、`unsupported_kind=family[0]`、`requirements` 带 kind、`applicability_decision=applicable`，**不绑定 `star_profile`**。四值裁定未新增取值。

调用端复用的 A 导出：`recognized_star_family_unsupported_kinds_from_text(source)`（语族文本扫描；astroid 语境与显式五角星已排除），连同既有 `recognized_unverifiable_kinds_from_text`、`ambiguous_requirement_kinds_from_text`、`DECISION_TERMS`、`semantic_requirement_state`、`state_allows_summary_passed`。

## 2. 三件事的落地与证据

### 2.1 保留门覆盖新语族（D1，实测断言，不推断）

存储门（`cad_construction_interpreter.py` 981-987）条件维持第二轮口径：`status != 'not_checked'` 或适用清单非空，或裁定字段属于 `DECISION_TERMS`。

语族报告 `status=unverified`（≠ `not_checked`），经既有 status 子句即被保留进 `source_acceptance.semantic_acceptance`。本轮测试 `test_r04_round3_family_report_retained_and_blocked`（四例参数化）实测断言：报告留在 `source_acceptance`、`review_required=True`、汇总 `semantic_requirement_state=unverified_or_partial`、`candidate_is_accepted=False`。

### 2.2 兜底补齐：语族扫描接入缺失报告路径（本轮关键改动）

**改动函数**：`_source_recognizes_mandatory_kind`（识别谓词）、`_semantic_summary_verdict` 缺失报告兜底。

**改动前**：缺失/非 dict 报告兜底只复用 A 的显式扫描 + 歧义扫描；语族措辞在报告缺失时两类扫描都不命中，谓词判无信号 → 落 `no_applicable_requirement` 放行（退化路径）。

**改动后**：识别谓词在结构化条目、显式、歧义之外，一并复用 A 的 `recognized_star_family_unsupported_kinds_from_text`；命中即视为有信号。兜底返回：

- 状态：`unverified_or_partial`，`review_required=True`；
- 原因：`report_unavailable`；语族追加 `unsupported_semantic_kind`（歧义仍追加 `ambiguous_requirement`）；
- 适用清单：显式 kind + 去重后的语族 kind；
- 无信号（圆/矩形/五边形/六边形）：维持 `no_applicable_requirement` 放行。

调用端不新建词表、不读几何 profile、不推断"这个图形看起来像什么"；语族判定完全来自 A 的文本扫描。

### 2.3 汇总透传

汇总 `construction_acceptance_summary` 对语义报告的处理未改：dict 报告委托 A 的 `semantic_requirement_state`；兜底 verdict 由调用端构造后复制 state / kinds / affected / reasons 进汇总输出。语族报告的 `review_required` 与第三态沿既有通道透传，不被压成"无适用要求"。本轮以断言证据覆盖，未改三态判定函数。

## 3. 零模型测试矩阵（`test_c_round11_r04_retention.py`，26 passed）

| 编号 | 场景 | 路径 | 预期 | 实测 |
|---|---|---|---|---|
| (a) | `四角星` / `六角星` / `星号` / `draw a star` | 正常报告 | 保留 + `unverified_or_partial` + `review_required=True` + accepted=false | **4/4 阻断** |
| (b) | 同上四例，报告缺失 | 兜底 | 阻断，原因 `report_unavailable` + `unsupported_semantic_kind` | **4/4 阻断** |
| (c) | `圆` / `矩形` / `正五边形` / `正六边形`，报告缺失 | 兜底 | 放行，`no_applicable_requirement`，无原因 | **4/4 放行** |
| (d) | `五角星` / `五角形`（显式 / 歧义） | 既有行为 | 显式阻断、歧义阻断；不变 | **通过**（既有 13 用例回归） |
| (e) | C10 爱心 passed + 五角星 `not_checked` | 既有行为 | `partial` / `review_required=True` / accepted=false | **通过** |
| (f) | `星形线 astroid 具有四个内禀尖点` | 专用通道 | 语族扫描为空，结构化 kind 为 `astroid_identity`，不被当语族/星形阻断 | **通过** |

探针证据：`c_round11_r04_wiring_probe.json`（`attached_report_cases` 含 4 条 FAMILY；`fallback_missing_report_cases` 含 4 条 MISSING_family + 4 条 MISSING_ordinary；`astroid_scan` 记录空语族清单与 `astroid_identity`）。

## 4. 隔离与红线

- 未改三态函数与四值裁定取值；未改 A 的两个模块。
- 未碰 R-01（checks 逐条复核）、R-02（path/stroke/projection/repetition 四通道门）、R-03（候选写入边界/复算/哈希绑定）。
- 未改 H2/H3/H4、`max_repairs`、候选保存授权；未新增专用验收器/生成器。
- 调用端无任何几何 profile 判断：语族适用标记全部来自 A 的来源措辞扫描；几何外观不反向编造需求。

## 5. 回归计数

- 相邻模块（C 保留测试 + 语义验收 + 解释器 + 编辑解释器）：190 passed；2 项失败为 A 侧既有基线（`test_structural_counter_schema_preserves_multiple_paths_without_coordinates`、`test_unsupported_styles_and_multiple_objects_are_not_falsely_fully_verified`，改动前同两项）。
- 全量（剔 8 个收集期环境缺口文件）：第二次干净重跑 **1809 passed / 47 failed / 4 skipped**；首次跑 1808/48/4，多出的 1 项为套件顺序 flake，复跑消失。47 项失败均为 DB 状态/套件顺序污染（agent_drawings、agent_run_api、clarification_grounding、copy_http_identity、counterfactual_guard、template_plan、write_receipt、composite_templates、conversation_memory、creative_projects、design_followup、geometry_catalog、incremental_cad、mirror_offset、stale_project_guard）；语义侧仅上述 2 项既有基线失败，无新增语义/汇总失败。

## 6. 残留判定

- **已识别/待澄清被退化为 `no_applicable_requirement`**：本轮语族四例在正常报告路径与缺失报告路径均阻断，退化路径在该词表覆盖范围内已清零。
- 既有残留（非本轮新增，沿第二轮结论）：
  1. 文本既不命中显式/歧义/语族扫描、又无已登记通道解析，即便几何像星形，按"措辞唯一授权"合同放行；只能由 A 侧扩词表/补通道关闭，调用端不得凭 profile 补判。
  2. A 生产者分支在所有收集证据与 reason 全空的情形仍为 UNVERIFIED（既有范围，未形式化穷举）。
