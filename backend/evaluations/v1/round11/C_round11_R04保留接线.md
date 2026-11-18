# C Round11：R-04 语义保留接线报告（Agent C）

- 性质：最小接线；零真实模型请求、无网络访问；未改冻结输入、未重跑 A9。
- 基准父节点：A 提交 `238a84e44bd4ea01a8c580df6d4b2cdfc411722d`（父 `38b2437`）；本提交独立，父节点为 `238a84e`，不 amend / rebase / push / merge。
- 改动范围：调用端解释器兜底判据 + 调用端测试与本轮产物；A 的两个语义模块未改；三态判定逻辑本身未改，只补兜底输入判据。

## 1. A 侧交付确认（`238a84e`）

A 只改 `cad_semantic_acceptance.py`、`cad_semantic_dispatch.py`，加测试与文档；解释器与门禁文件未改。可供调用端复用的导出：

- `recognized_unverifiable_kinds_from_text(source)`：显式词表扫描（`五角星|五芒星|星形轮廓`）。
- `ambiguous_requirement_kinds_from_text(source)`：歧义词扫描（`五角形|星形|星星|星型`；astroid 语境与显式词已排除）。
- `collect_ambiguous_requirement_kinds(report, source)`：歧义清单收集（A 侧使用）。

A 口径（已随 A 测试固化）：显式词表 → 适用、第三态阻断；歧义词 + 星形几何 → `confirmed_by_geometry`、第三态阻断；歧义词 + 凸五边形 → `resolved_non_star`、第一态放行；歧义词 + 无法判定 → `ambiguous_requirement`、第三态阻断；普通形状放行；astroid 走专用通道不被当星形。

## 2. 三件事的落地与证据

### 2.1 保留门核对/加固（D1）

现行存储门未改：`cad_construction_interpreter.py` 979-981，`status != 'not_checked'` 或 `applicable_requirement_kinds` 非空才写入 `source_acceptance.semantic_acceptance`。

实测（探针 `c_round11_r04_wiring_probe.json`，real_reports 第 1 条）：

- 输入"画一个五角星"：报告 `not_checked`，适用清单 `[star_profile]`，门判定保留（`storage_gate_retained=true`），判定 `unverified_or_partial` / `report_unchecked_applicable`，阻断 PASS。
- 测试 `test_r04_not_checked_applicable_report_is_retained_and_blocks`：断言报告留在 `source_acceptance`、适用清单非空、汇总第三态、`candidate_is_accepted=False`。

歧义未解决报告（歧义词 + 无几何）适用清单为空、歧义清单非空：D1 不保留报告正文，由 2.2 的缺失报告兜底按文本扫描重新阻断；判定结果不丢，仅报告正文证据不保留（见 §4 残留说明）。

### 2.2 兜底缺口修复（缺失/非 dict 报告的识别判据）

**改动函数**：`_source_recognizes_mandatory_kind`（1264-1291）、`_semantic_summary_verdict` 缺失报告兜底（1295-1318）。

**改动前**：兜底只查 `semantic_requirements` 结构化条目；显式 star 词表不产生结构化条目，歧义表达也不产生，导致"报告缺失 + 五角星/五角形"被判 `no_applicable_requirement` 放行（Round11 测绘探针已复现）。

**改动后**：识别谓词在结构化条目之外，**复用 A 导出的两个文本扫描**——显式 `recognized_unverifiable_kinds_from_text`、歧义 `ambiguous_requirement_kinds_from_text`；三者任一命中即视为有信号，缺失报告落第三态：

- 显式命中：`unverified_or_partial`，原因 `report_unavailable`，适用清单回填显式 kind；
- 歧义命中：`unverified_or_partial`，原因 `report_unavailable` + `ambiguous_requirement`，歧义清单回填；
- 无信号：维持原 `no_applicable_requirement` 放行行为。

**红线遵守**：未新建第二套词表；未在调用端读取任何几何 profile；未凭几何外观补适用项。文本扫描全部来自 A 模块导出。

实测（fallback_missing_report）：

| 输入 | 语义状态 | 原因 | 阻断 PASS |
|---|---|---|---|
| 画一个五角星 | `unverified_or_partial` | `report_unavailable` | 是 |
| 画一个五角形 | `unverified_or_partial` | `report_unavailable` + `ambiguous_requirement` | 是 |
| 画一个星星 | `unverified_or_partial` | `report_unavailable` + `ambiguous_requirement` | 是 |
| 画一个圆 | `no_applicable_requirement` | 无 | 否（放行） |
| 画一个矩形 | `no_applicable_requirement` | 无 | 否（放行） |

### 2.3 测试（零模型）

新文件 `backend/tests/test_c_round11_r04_retention.py`，5 项全部通过：

| 用例 | 覆盖 |
|---|---|
| `test_r04_not_checked_applicable_report_is_retained_and_blocks` | (a) `not_checked` + 非空适用清单保留并进汇总、阻断 |
| `test_r04_missing_report_explicit_star_wording_blocks` | (b) 报告缺失 + 显式 star 词 → 不放行 |
| `test_r04_missing_report_ambiguous_wording_blocks` | (b) 报告缺失 + 歧义词（五角形/星星/星形）→ 不放行，含 `ambiguous_requirement` |
| `test_r04_missing_report_ordinary_shapes_are_released` | (c) 报告缺失 + 圆/矩形 → 仍放行，不误拦 |
| `test_r04_c10_heart_passed_star_not_checked_still_rejected` | (d) C10 爱心 passed + star `not_checked`，整体 `partial`/`review_required=True`/accepted=false |

## 3. 回归结果

- 相邻模块（G1 护栏 + 语义验收 + 解释器 + 编辑解释器）：**142 passed**；2 项失败为 A 侧既有基线失败（`test_structural_counter_schema_preserves_multiple_paths_without_coordinates`、`test_unsupported_styles_and_multiple_objects_are_not_falsely_fully_verified`），改动前基线同两项失败。
- 全量（剔除 8 个收集期环境缺口文件）：**1749 passed / 47 failed / 4 skipped**；失败类别与会话记忆、创意项目、跟进参数、增量编辑、镜像约束、陈旧项目守卫等 DB 状态/套件顺序污染相关，与 Round10 全量基线失败集合一致；无语义/汇总新增失败。
- 收集期缺口 8 文件：acceptance_metrics、corpus_audit、history_replay、product_acceptance_runner、deepseek_flash_budget、p12_eval_budget、recorded_cad_repair_inputs、user_cad_corpus_runner（环境缺文件，非本轮引入）。

## 4. 残留静默放行路径

**仍存在的可达残留**（条件明确）：

1. **未登记近义表达 + 几何星形外观**：请求文本既不命中显式词表，也不命中歧义模式，且无已登记通道解析出强制要求；即便几何是星形轮廓，按合同"用户措辞是强制要求的唯一授权来源"，调用端不得据 profile 补适用项 → 落第一态放行。该残留只能由 A 侧扩词表/补通道关闭；调用端一旦用 profile 判断即违反红线（B 已证 profile 会把 astroid 2/3 票误标 star）。
2. **A 生产者分支不可见残留（UNVERIFIED）**：若 A 返回的 dict 报告在六类收集证据与 reason 上全部为空，D1 会丢弃、兜底按无信号处理；现有 collector 覆盖 requirements / unsupported_kind / coverage / 对象条目 / 自带标记 / 文本兜底，未见遗漏分支，但未对所有生产者分支做形式化穷举。

除上述两类外，本轮接线后：显式/歧义 star 信号在"报告保留"与"报告缺失"两条路径上均阻断；普通形状不误拦；C10 回归保持阻断。

## 5. 隔离声明

- **R-01**：未改逐条 check 复核、未改空 checks 门禁。
- **R-03**：未改候选写入边界、持久化授权、传入汇总复算与几何哈希绑定。
- **R-02**：path/stroke/projection/repetition 四通道存储门未动。
- 未改 H2/H3/H4、`max_repairs`、候选保存授权；未新增专用验收器或生成器；未改 A 的两个模块。

## 6. 交付清单

- `backend/app/cad_construction_interpreter.py`（兜底判据两处 + 第二轮存储门裁定字段条件）
- `backend/tests/test_c_round11_r04_retention.py`（13 用例）
- `backend/evaluations/v1/round11/C_round11_R04保留接线.md`（本报告）
- `backend/evaluations/v1/round11/c_round11_retention_mapping_static.json`（测绘 JSON，标"已接线"）
- `backend/evaluations/v1/round11/c_round11_r04_wiring_probe.py` / `.json`（零费用探针与证据）

## 7. 第二轮对齐（父 `1fc2ad5`）

### 7.1 病灶（D 实测）

M1：歧义词（`五角形`）+ 凸五边形，A 报告层已是 `resolved_non_star`；但报告 `not_checked` 且适用清单为空，被旧存储门丢弃。报告缺失后，第一轮接线的兜底只看文本歧义，又阻断一次 → 合法五边形被过度拦。

### 7.2 存储门条件（新旧对比）

- **旧**：`status != 'not_checked'` 或 `applicable_requirement_kinds` 非空，才写入 `source_acceptance.semantic_acceptance`。
- **新**：`status != 'not_checked'` 或适用清单非空，**或** `applicability_decision` 属于 A 导出的 `DECISION_TERMS`（`applicable` / `ambiguous_unresolved` / `resolved_non_star` / `no_signal`）。

`resolved_non_star` 与 `no_signal` 都必须保留：汇总需要看到这份"已明确裁定"的证据，缺失报告兜底才不会二次猜测。

### 7.3 显式裁定不被兜底覆盖

- dict 报告在 `_semantic_summary_verdict` 中**先委托** A 的 `semantic_requirement_state`；文本兜底只在报告缺失/非 dict 时触发。
- 报告裁定为 `resolved_non_star` / `no_signal` 时，调用端不得再用文本歧义扫描把它拦回第三态。
- 缺失报告路径维持第一轮口径：复用 A 导出的 `recognized_unverifiable_kinds_from_text`、`ambiguous_requirement_kinds_from_text`；显式 → 阻断，歧义 → 阻断，无信号（圆/矩形等）→ 放行。
- 调用端不重新推导裁定字段、不读几何 profile、不新建词表；裁定推导完全归 A 的 `derive_applicability_decision`。

### 7.4 (a)–(g) 零费用实测

探针 `c_round11_r04_wiring_probe.json`（attached_report_cases / fallback_missing_report_cases）：

| 编号 | 场景 | 裁定 | 三态 | accepted |
|---|---|---|---|---|
| (a) M1 | `五角形` + 凸五边形 | `resolved_non_star` | `no_applicable_requirement` | **true** |
| (b) M1b | `五角形` + 星形几何 | `applicable` | `unverified_or_partial` | **false** |
| (c) W1 | `圆和矩形` + 星形几何（无文本信号） | `no_signal` | `no_applicable_requirement` | **true** |
| (d) | `五角星`（显式词表，无几何） | `applicable` | `unverified_or_partial` | **false** |
| (e) | 圆 / 矩形 / 正五边形 / 正六边形 | `no_signal` | `no_applicable_requirement` | **true**（4/4） |
| (f) C10 | 爱心 passed + 五角星 `not_checked` | `applicable` | `unverified_or_partial`，整体 `partial`/`review_required=True` | **false** |
| (g) | 报告缺失：`五角星` / `五角形` | — | `unverified_or_partial` | **false**（2/2）；报告缺失：圆 → `no_applicable_requirement`，**true** |

### 7.5 回归计数

- 相邻模块（C 保留测试 + G1 护栏 + 语义验收 + 解释器）：164 passed；2 项失败为 A 侧既有基线（改动前同两项）。
- 全量（剔 8 个收集期环境缺口文件）：**1749 passed / 47 failed / 4 skipped**，与第一轮接线后全量计数一致；失败类别为会话记忆、创意项目、跟进参数、增量编辑、镜像约束、陈旧守卫等 DB 状态/套件顺序污染，无语义/汇总新增失败。

### 7.6 残留判定

- **合法非星被过度阻断**：M1 路径已关闭；`resolved_non_star` / `no_signal` 裁定随报告保留并被汇总采信。
- **适用要求被静默丢弃**：除 §4 既有两类残留外无新增：
  1. 文本既不命中显式词表也不命中歧义模式、且无已登记通道解析，即便几何像星形，按"措辞唯一授权"合同放行——只能由 A 侧扩词表/补通道关闭；
  2. A 生产者分支在所有收集证据与 reason 上全空的情形仍为 UNVERIFIED（既有范围，未做形式化穷举）。

## 8. 第三轮：语族来源边界保留（父 `e2f3437`）

详见同目录 `C_round11_来源边界保留接线.md`。要点：A 新增 `four_pointed_star` / `six_pointed_star` / `asterisk` / `star_family_generic` 四类语族 kind；调用端兜底复用 A 的 `recognized_star_family_unsupported_kinds_from_text`，报告缺失时语族措辞落第三态阻断（`report_unavailable` + `unsupported_semantic_kind`），不退化为 `no_signal` 放行；正常报告路径 `unverified` 经既有 status 子句保留；astroid 回归不受影响。R-01/R-02/R-03 边界未触碰。
