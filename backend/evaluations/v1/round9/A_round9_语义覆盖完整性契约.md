# Round9 A-line 语义覆盖完整性契约（单一判据来源）

- 基线提交：`07bd888f8c888a543d1983d8246f35d5939351e8`（round8 组合树）
- 适用模块：`backend/app/cad_semantic_dispatch.py`（判据与真值函数）、`backend/app/cad_semantic_acceptance.py`（报告适用性标记）
- 纪律：零真实模型请求、零网络；不新增五角星专用验收器、不新增专用图形生成器；不改 H2/H3/H4、不改 `max_repairs`；不改既有终态状态词表。
- 边界：本契约只提供**唯一判据**与**报告字段**。汇总层调用位置、门禁谓词接线由 Agent C 实现；本轮不编辑 `cad_construction_interpreter.py`、`cad_candidate_state.py`。

## 1. 要解决的两个缺陷

### 1.1 BLOCK-01：partial 语义被当成完整验收通过

汇总函数只把 `review_required is True` 或状态属于 `{failed, unverified, review_required}` 的报告计入复核；`partial` 不在复核状态集合内。房屋 / 大写 A 通道既有形态为 `partial + review_required=False`，在 `coverage=complete` 且 `unknown_requirements=[]` 的条件下，汇总会产出 `status=passed / review_required=False`，门禁据此接受候选。

**契约立场**：`partial` 一律视为未完整验证，**不得因 `review_required=False` 而升格**。

### 1.2 疑似同类漏洞：`not_checked` 报告被整体丢弃

解释器在挂接语义报告前判断 `status != 'not_checked'`，整体 `not_checked` 的报告不进入 `source_acceptance`，汇总层既看不到它、也不会为它触发复核。于是两类情形被混为一谈：

1. 请求**根本没有适用的强制语义要求**（如“画一个花瓶”）；
2. 请求**存在强制语义要求**，但对象级全部未验证 / 无验收器（如只请求五角星）。

**探针实测结论：该漏洞可触发。** 证据见 `A_round9_semantic_coverage_probe.json` 的 `drop_guard_audit.star_only_not_checked` 与 `not_checked_distinction`：

- 五角星-only 报告 `status=not_checked`，被守卫丢弃，`semantic_visible_to_summary=false`；
- 在“已有一条通过的基础检查 + `coverage=complete`”的残留轮廓下，汇总产出 `passed / review_required=False`，而契约判定为 `unverified_or_partial`（`guard_would_hide_mandatory_requirement=true`）；
- 对照：无适用要求的花瓶报告同样 `not_checked`，但适用性标记为空，契约判定 `no_applicable_requirement`，语义层不构成阻塞。

## 2. 三状态定义

真值函数：`semantic_requirement_state(report, source=None)`，返回恰好三种状态之一。

| 状态 | 含义 | 语义层是否阻塞汇总 PASS |
|---|---|---|
| `no_applicable_requirement` | 该请求**没有任何适用的强制语义要求**。对象级 `not_checked` 在此状态下不应被判失败，也不应强制复核。 | 不阻塞（`state_allows_summary_passed=true`） |
| `fully_verified` | 存在强制语义要求，且**全部对象级检查通过**；报告自身为 `passed`，无遗留缺口。 | 不阻塞（`true`） |
| `unverified_or_partial` | 存在强制语义要求，但未验证 / 部分验证 / 任一对象 `not_checked` / 未知 kind / 适用报告整体 `not_checked`。 | **阻塞（`false`）**，无论 `review_required` 取值 |

辅助谓词：`state_allows_summary_passed(verdict)`，仅当状态为前两者时返回 `true`；`unverified_or_partial` 永远返回 `false`。

## 3. 判据来源（强制语义要求如何认定）

**唯一判据是识别到的语义 kind 归属注册表，不得从 `coverage` 字段推断，也不得从 `review_required` 推断。** 房屋 / 大写 A 正是 `partial + review_required=False` 的反例：`review_required` 为假不代表要求已完整覆盖。

注册表位于 `cad_semantic_dispatch.py`：

| 归类 | 注册表常量 | 认定口径 |
|---|---|---|
| `dispatch_channel` | `DISPATCH_CHANNELS` 的键 | 已登记到语义分派通道表，由对应通道验收器处理 |
| `special_verified` | `SPECIAL_VERIFIED_KINDS` | 识别到要求，由通道表之外的专用验收分支处理；`passed` 即完整验证，其它终态不得 PASS |
| `unverifiable_recognized` | `UNVERIFIABLE_RECOGNIZED_KINDS` | 识别到形状 / 轮廓，但**后端无验收器**；属能力缺口，阻塞 PASS，绝不能静默当作“无要求” |
| 未知 kind | 不在上述任一注册表 | 记为 `recognized_unknown_kinds`，状态 `unverified_or_partial`，原因 `unknown_kind`；终止分派，不进入任何默认检查器 |

`MANDATORY_REQUIREMENT_KINDS` = 前三类并集，是“强制语义要求”的完整集合。

### 3.1 各 kind 归类表

| kind | 归类 | 验收通道 / 分支 | 备注 |
|---|---|---|---|
| `heart_outline_features` | `dispatch_channel` | `heart_outline` | 爱心四特征，按绑定对象独立测量 |
| `straight_capital_a` | `dispatch_channel` | `capital_a` | 上部三角区域、分离支脚等结构关系 |
| `triangle_roof_house` | `dispatch_channel` | `house_outline` | 三角屋顶 + 墙体 + 门结构关系 |
| `house_outline` | `dispatch_channel` | `house_outline` | 房屋轮廓别名 |
| `astroid_identity` | `special_verified` | astroid 专用分支 | 四尖点数学关系 + 最大半径 |
| `nested_square_frames` | `special_verified` | 嵌套框专用分支 | 外框 / 内框边长、居中与包含关系 |
| `regular_polygon` | `special_verified` | 正多边形专用分支 | 边数、外接圆半径、同心孔 |
| `cardioid_identity` | `special_verified` | cardioid 专用分支 | 极坐标身份与尖点朝向 |
| `star_profile` | `unverifiable_recognized` | **无验收器** | 五角星 / 五芒星轮廓；本轮登记为能力缺口，不计 PASS |
| 其它未登记 kind（如 `mystery_contour`） | 未知 | 不进入默认检查器 | 原因 `unknown_kind` + `no_verifier` |

### 3.2 适用性证据来源

报告中适用 kind 的收集顺序（`collect_applicable_requirement_kinds`）：

1. 顶层 `requirements` 条目的 `kind`；
2. 顶层 `unsupported_kind`；
3. 专用分支通过 `coverage` 值反查 kind（`SPECIAL_VERIFIED_COVERAGE_KINDS`，覆盖那些返回前不带 `requirements` 列表的分支）；
4. 对象级 `object_acceptance` 中通用分类器判为 `star` 或原因为 `no_verifier_for_star_profile` 的条目 → `star_profile`；
5. 报告自身的 `applicable_requirement_kinds` 标记（去重合并）；
6. 可选源文本回退：`UNVERIFIABLE_SHAPE_PATTERNS` 中登记的无验收器形状词表（仅作适用性标注，不构成验收识别）。

## 4. 报告新增字段

### 4.1 `applicable_requirement_kinds`（显式适用性标记）

- 类型：`list[str]`，去重、稳定顺序。
- 落点：`verify_semantic_requirements` 返回的每一份语义报告；由公共入口包装层在原始验收结果上统一标注，原始验收器的既有返回结构与状态词不变。
- 关键性质：**报告整体 `not_checked` 但存在强制 kind 时，该标记仍为真**。这正是区分 §1.2 两类情形的依据。
- 无适用要求时为空列表 `[]`；不得用 `null` 省略。

### 4.2 真值函数返回结构

```json
{
  "state": "no_applicable_requirement | fully_verified | unverified_or_partial",
  "applicable_requirement_kinds": ["..."],
  "recognized_unknown_kinds": ["..."],
  "review_required": true,
  "reasons": ["..."],
  "affected": [
    {"object_id": "...", "geometry_ids": [1], "status": "not_checked",
     "reason": "no_verifier_for_star_profile", "profile": "star"}
  ]
}
```

| 字段 | 说明 |
|---|---|
| `state` | 三状态之一，见 §2 |
| `applicable_requirement_kinds` | 本次报告识别到的强制 / 无验收器 kind 全集 |
| `recognized_unknown_kinds` | 识别到但不在强制注册表内的 kind |
| `review_required` | 保留报告自身复核标记；状态为 `unverified_or_partial` 时恒为 `true` |
| `reasons` | 子原因码集合，见 §5 |
| `affected` | 被拖累对象清单：`object_id`、`geometry_ids`、对象状态、原因、轮廓分类；通过对象不进入该清单 |

## 5. 子原因码（`reasons`）

| 原因码 | 触发条件 |
|---|---|
| `partial_overall` | 顶层状态为 `partial`（不因 `review_required=False` 升格） |
| `partial_objects` | 至少一个对象级条目未通过 |
| `object_not_checked` | 对象条目状态为 `not_checked` |
| `no_verifier` | 识别到的 kind / 轮廓无后端验收器（含 `unsupported_kind`、`no_verifier_for_kind`、星形对象条目） |
| `unknown_kind` | 解析到 / 不支持的 kind 不在强制注册表内 |
| `report_unverified` | 顶层状态属于 `unverified / unresolved / failed / review_required` |
| `report_unchecked_applicable` | 报告整体 `not_checked`，但携带已识别的强制 kind（§1.2 第二类情形） |
| `object_unresolved` | 对象条目为 `unresolved / unverified` |
| `report_unavailable` | 报告缺失或不是字典；保守判为阻塞，不得当作“无要求” |

## 6. 调用方使用方式（供 Agent C 接线）

1. 汇总层对每份语义报告只调用 `semantic_requirement_state(report, source)`，**不得**自行从 `coverage` / `review_required` / 对象数量反推适用性。
2. 是否允许汇总 PASS 以 `state_allows_summary_passed(verdict)` 为准：
   - `no_applicable_requirement`：语义层不阻塞；其它验收层结论照常参与汇总；
   - `fully_verified`：语义层已完整验证；
   - `unverified_or_partial`：汇总不得记为完整验收通过，复核标记置真。
3. 门禁谓词只消费汇总层收敛后的结论；契约不在门禁模块内重复实现判断，避免两套口径。
4. 诊断与证据账本应保留 `reasons` 与 `affected`（含 `object_id` / `geometry_ids`），便于定位被拖累对象。
5. 报告挂接守卫（`status != 'not_checked'`）的去留由 C 裁决；无论守卫是否保留，汇总层都应能通过适用性标记区分 §1.2 两类情形。

## 7. 真值表（输入 → 状态 → 是否允许汇总 PASS）

| # | 输入报告（真实夹具 / 合成报告） | 适用 kind | 状态 | 主要原因码 | 允许汇总 PASS |
|---|---|---|---|---|---|
| T1 | 无匹配需求（“画一个花瓶”），`not_checked`，标记 `[]` | 无 | `no_applicable_requirement` | — | 是 |
| T2 | 嵌套框 / 正多边形 / astroid / cardioid 专用分支 `passed` | 对应 `special_verified` kind | `fully_verified` | — | 是 |
| T3 | 单爱心，`partial + review_required=True`，对象条目 `passed` | `heart_outline_features` | `unverified_or_partial` | `partial_overall` | 否 |
| T4 | C10 爱心 + 五角星，`partial`；爱心 `passed`，五角星 `not_checked` | `heart_outline_features`, `star_profile` | `unverified_or_partial` | `object_not_checked`, `no_verifier`, `partial_objects`, `partial_overall` | 否 |
| T5 | 房屋通道，`partial + review_required=False` | `triangle_roof_house` | `unverified_or_partial` | `partial_overall` | 否 |
| T6 | 大写 A 通道，`partial + review_required=False` | `straight_capital_a` | `unverified_or_partial` | `partial_overall` | 否 |
| T7 | 未知 kind，`unverified + coverage=unsupported_semantic_kind`，`no_verifier_for_kind` | `mystery_contour`（未知） | `unverified_or_partial` | `unknown_kind`, `no_verifier`, `report_unverified` | 否 |
| T8 | 五角星-only，`not_checked`，标记 `[star_profile]` | `star_profile` | `unverified_or_partial` | `report_unchecked_applicable` | 否 |
| T9 | 报告缺失 / 非字典 | 无 | `unverified_or_partial` | `report_unavailable` | 否 |

> 边界交集：`not_checked` 只在“该请求无适用强制语义要求”（T1）时允许不被判失败；存在强制 kind 的 `not_checked`（T8）一律落入状态 3。`partial` 无论 `review_required` 取值（T3–T6）都不得升格为完整验证。

## 8. `unverified` / 未完成项清单

| 项 | 状态 | 原因 / 覆盖 | 处置口径 |
|---|---|---|---|
| C10 五角星（几何 [2]） | 对象级 `not_checked` | `no_verifier_for_star_profile`，本轮无五角星验收器 | 登记能力缺口，不计 PASS；未新增专用验收器 / 生成器 |
| 五角星-only 请求 | 报告级 `not_checked` + `report_unchecked_applicable` | 无验收器；旧守卫会丢弃报告 | 契约判状态 3；汇总层不得 PASS；验收器缺口留待后续轮次 |
| 未知 kind（花瓶等无匹配需求之外的未登记轮廓） | `unverified / unsupported_semantic_kind` | `no_verifier_for_kind` | 终止分派，不进默认检查器，不计 PASS |
| 房屋、大写 A | `partial`（继承 423E，报告 `review_required=False`） | 仅结构关系子集覆盖 | 契约判状态 3；不得因 `review_required=False` 升格 |
| 单爱心 | `partial + review_required=True` | 特征覆盖为部分口径 | 契约判状态 3 |
| 绑定缺失 / 畸形 / 归属不唯一 | `unresolved` | 绑定护栏既有口径 | 契约判状态 3，`object_unresolved` / `report_unverified` |

## 9. 既有终态口径（本轮不动）

- `unverified + coverage=unsupported_semantic_kind`：识别到需求但无法可靠完成语义验收；
- `not_checked`：该对象未执行相应检查；
- `partial + review_required=True`：部分对象完成检查，整体需求尚未全部验证；
- 任何包含未完成强制语义验收的组合对象，不能因其它对象通过而整体 PASS；五角星本轮无完整验收器，登记为能力缺口，不计 PASS。

状态词表 `partial / not_checked / unverified / unsupported_semantic_kind` 的既有含义未改。

## 10. 禁区与执行限制核对

| 限制项 | 核对结果 |
|---|---|
| 不编辑 `cad_construction_interpreter.py` | 未改（`git diff --name-only` 不含） |
| 不编辑 `cad_candidate_state.py` | 未改（`git diff --name-only` 不含） |
| 不新增五角星专用验收器 | 未新增；`star_profile` 仅为适用性标注 |
| 不新增专用图形生成器 | 未新增 |
| 不改 H2/H3/H4 | 未改 |
| 不改 `max_repairs` | 未改 |
| 不改候选保存授权条件 | 未改（仅读取谓词做审计） |
| 状态词表含义不变 | 未改 |
| 零真实模型请求 / 零网络 | 探针与单测全部离线合成夹具 |
| 不重跑 A9、不启动 S1、不改冻结输入 | 未执行 |
| 不 amend / 不 rebase / 不 push / 不 merge | 独立提交，父节点为基线 `07bd888f` |

## 11. 测试与复现

环境：Python `xikao` 环境；`PYTHONPATH=backend`；无模型密钥注入。

- 单测文件：`backend/tests/test_cad_semantic_acceptance.py`（Round9 契约用例 7 项）。
- 探针：`backend/evaluations/v1/round9/A_round9_semantic_coverage_probe.py`
- 证据快照：`backend/evaluations/v1/round9/A_round9_semantic_coverage_probe.json`

复现命令（`backend/` 目录下）：

```
python evaluations/v1/round9/A_round9_semantic_coverage_probe.py --out evaluations/v1/round9/A_round9_semantic_coverage_probe.json
python -m pytest tests/test_cad_semantic_acceptance.py tests/test_c_round8_caller_wiring.py -q
```

## 12. 遗留事项

- 既定的《后端最终同步清单.md》在本机环境未找到对应路径，本轮无法写入同步范围；待路径可用后补登本次改动范围（`cad_semantic_dispatch.py`、`cad_semantic_acceptance.py`、语义单测、round9 探针与证据）。
- 五角星验收器缺口、房屋 / 大写 A 通道 `review_required=False` 的继承口径，留待后续轮次与 C/D 线裁决；本轮只提供判据与报告字段。
