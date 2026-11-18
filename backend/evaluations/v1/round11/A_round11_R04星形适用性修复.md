# Round11 R-04：星形适用性最小修复说明

- 工作树：`tmp/r04-fix`（分支 `tmp/r04-fix`，父提交 `38b2437…`）；本文件、探针脚本与 JSON 为未跟踪产物，随本次独立提交一并入库。
- 性质：零真实模型请求、零网络；未重跑 A9；未改冻结输入；未启动 S1。
- 改动范围：仅两个语义模块 + 语义单测 + 本轮评估产物；未改解释器、未改门禁谓词、未新增星形专用生成器或验收器。

## 1. 修复的缺陷与前后触发链对照

### 1.1 修复前（BLOCK-01 在适用性侧的漏放）

请求用未入词表的说法（`五角形` / `星形` / `星星`）表达星形语义并产出星形几何时：

1. `semantic_requirements(source)` 未匹配任何已登记通道，返回空要求清单；
2. 原始报告提前返回 `not_checked / coverage=partial / reason=no_semantic_requirement_matched`，**对象级 profile 扫描未运行**；
3. 适用性标记 `applicable_requirement_kinds` 为空；
4. 三态判 `no_applicable_requirement`；
5. 汇总层当作完整验收通过，门禁 `accepted=true`。

即：已登记但未验证的语义要求被静默丢弃并放行。

### 1.2 修复后

1. 来源文本是强制语义要求的**唯一授权来源**：先区分"明确适用 / 歧义适用 / 不适用"三类；
2. 无已登记通道时，在空要求分支做一次**保守的后端 profile 辅助扫描**；
3. profile 只在来源已有星形信号或歧义信号时用于对象级确认；**单独的几何星形不会新建 `star_profile` 适用项**；
4. 歧义无法被几何排除时，保留在第三态 `unverified_or_partial`，`review_required=True`，不得 PASS；
5. 歧义被凸五边形等非星形几何排除时，记 `resolved_non_star`，正常放行。

## 2. 三类适用性处理矩阵

| 类别 | 来源信号 | 后端 Profile 证据 | 适用清单 | 合同状态 | 子原因 | 可否汇总 PASS |
|---|---|---|---|---|---|---|
| **明确适用** | 命中显式词表 `五角星` / `五芒星` / `星形轮廓`（含 `五角星` 子串变体） | 仅作对象级辅助，不改变授权 | `[star_profile]` | `unverified_or_partial` | `report_unchecked_applicable`；有对象条目时 `no_verifier` + `object_not_checked` | 否 |
| **歧义适用（已确认）** | 命中歧义词 `五角形` / `星形` / `星星` / `星型`，未命中显式词表 | Profile 判为 `star`，佐证歧义指向星形 | `[star_profile]`，歧义清单同步记录 | `unverified_or_partial` | `ambiguous_requirement` + `no_verifier` + `object_not_checked` | 否 |
| **歧义适用（未解决）** | 同上歧义词 | 无活动几何 / 无法判定，既不能确认也不能排除 | 适用清单为空，歧义清单 `[star_profile]` | `unverified_or_partial` | `ambiguous_requirement` | 否 |
| **歧义适用（已排除为非星形）** | 同上歧义词 | 活动几何存在，Profile 为凸五边形等非星形 | 适用清单为空；`ambiguity_resolution=resolved_non_star` | `no_applicable_requirement` | 无 | 是 |
| **不适用** | 无任何星形 / 歧义信号（圆、矩形、正五边形、正六边形等） | 不凭几何外观补造星形要求 | `[]` | `no_applicable_requirement` | 无 | 是 |

关键口径：**歧义必须落在第三态，不得落到第一态**；只有在后端 profile 明确排除为非星形后，歧义才被解除并放行。

## 3. Profile 判据说明（复用既有通用分类器，未新增专用规则）

对象级 Profile 复用 `classify_profile` 的三判据投票，阈值未改动：

- 深谷数 ≥ 4（`STAR_VALLEY_MIN`）；
- 凸包面积比 < 0.72（`STAR_HULL_RATIO_MAX`）；
- 五重旋转对称残差近零（`STAR_FOLD_RESIDUAL_MAX`）。

三项中至少两项同意才判 `star`；否则为 `heart_like` 或 `other`；轮廓退化记 `degenerate`。凸五边形 / 六边形 / 矩形 / 圆均不满足星形投票组合，不会被误判为 star。

### 3.1 几何 Profile 不作为独立授权来源——代码体现

- 授权判定起点是来源文本：`recognized_unverifiable_kinds_from_text`（明确）与 `ambiguous_requirement_kinds_from_text`（歧义）；
- Profile 扫描只在空要求分支内、且围绕来源已有的信号展开：
  - 明确来源：profile 仅补充对象级未验证条目，适用项来自来源授权；
  - 歧义来源：profile 为 `star` 时记 `confirmed_by_geometry`，为非星形时记 `resolved_non_star`；
  - **无来源信号时，即使几何像星形，也不写入 `applicable_requirement_kinds`，不生成 star 适用项**；
- 歧义清单与适用清单分离：`ambiguous_requirement_kinds` 只表示"尚未确定"，不等于"要求已成立"。

## 4. 实测真值表（离线探针，零模型）

探针：`A_round11_R04_scope_fix_probe.py`；证据快照：`A_round11_R04_scope_fix_probe.json`。

| # | 输入 | 几何 | 报告状态 | 适用清单 | 歧义清单 | 合同状态 | 阻断 PASS |
|---|---|---|---|---|---|---|---|
| 1 | 画一个五角星 | 无 | `not_checked` | `[star_profile]` | `[]` | `unverified_or_partial` | 是 |
| 2 | 画一个五芒星 | 无 | `not_checked` | `[star_profile]` | `[]` | `unverified_or_partial` | 是 |
| 3 | 画一个星形轮廓 | 无 | `not_checked` | `[star_profile]` | `[]` | `unverified_or_partial` | 是 |
| 4 | 画一个五角形 | 星形轮廓 | `not_checked` | `[star_profile]` | `[star_profile]` | `unverified_or_partial`（`confirmed_by_geometry`） | 是 |
| 5 | 画一个五角形 | 凸五边形 | `not_checked` | `[]` | `[star_profile]` | `no_applicable_requirement`（`resolved_non_star`） | 否 |
| 6 | 画一个星星 | 无 | `not_checked` | `[]` | `[star_profile]` | `unverified_or_partial`（未解决） | 是 |
| 7 | 画一个星形 | 无 | `not_checked` | `[]` | `[star_profile]` | `unverified_or_partial`（未解决） | 是 |
| 8 | 画一个六边形 | 凸六边形 | `not_checked` | `[]` | `[]` | `no_applicable_requirement` | 否 |
| 9 | 画一个圆 | 圆 | `not_checked` | `[]` | `[]` | `no_applicable_requirement` | 否 |
| 10 | 画一个矩形 | 矩形 | `not_checked` | `[]` | `[]` | `no_applicable_requirement` | 否 |
| 11 | 画一个五边形 | 凸五边形 | `not_checked` | `[]` | `[]` | `no_applicable_requirement` | 否 |
| 12 | 星形线 astroid 四尖点 | — | 走既有 astroid 专用通道 | `[]` | `[]` | astroid 原行为保持 | — |
| 13 | C10：爱心 + 五角星 | 爱心 + 星形 | `partial / partial_with_unverified_objects`，`review_required=True` | `[heart_outline_features, star_profile]` | `[]` | `unverified_or_partial` | 是 |

C10 对象级状态：爱心对象 `passed / heart_features_measured`；五角星对象 `not_checked / no_verifier_for_star_profile`，profile=`star`。

### 4.1 文本层扫描结果

- 显式命中：`五角星`、`五芒星`、`星形轮廓`、`五角星形`（子串）；
- 歧义命中：`五角形`、`星形`、`星星`、`星型`；
- 均不命中：`星形线`（astroid 守卫排除）、`star`、`five-pointed star`；
- 显式命中的文本不会再进入歧义清单；astroid 文本对两类清单都不命中。

## 5. 测试计数与回归

- 语义单测文件：**55 passed / 2 failed**；两项失败为基线既有失败（`test_structural_counter_schema_preserves_multiple_paths_without_coordinates`、`test_unsupported_styles_and_multiple_objects_are_not_falsely_fully_verified`），同名同因，非本轮引入。
- 定向回归（语义 / 解释器 / 结构契约 / 需求契约 / 源验收 / 拓扑 / P0 边界 / round8 接线 / round9 G1、G1b、G2 路径）：**271 passed / 2 failed**，失败项同上。
- 本轮新增单测 12 例：显式词表 ×3、歧义+星形几何、歧义+凸五边形放行、歧义+无几何未解决、普通形状 ×4（六边形 / 圆 / 矩形 / 五边形）、astroid 守卫、C10 混合对象。

## 6. 与 R-01 / R-03 的关系（无关证明）

- R-01（绑定载荷 / 后端对象身份）：本轮未改动绑定解析、目标校验、拓扑图校验任何规则；Profile 扫描复用既有 `validate_target_binding` 目标分组，未放宽成员归属或共享声明口径。
- R-03（汇总门禁谓词 / 候选状态）：本轮未改 `cad_candidate_state.py`，未改解释器汇总函数；第三态阻断仍由既有 `state_allows_summary_passed` 口径消费，接线侧无需配合改动。
- 本轮只动适用性识别与歧义保留：词表分类、歧义清单字段、空要求分支的保守 profile 辅助扫描、三态子原因 `ambiguous_requirement`。

## 7. 边界与禁区核对

- 未新增五角星专用验收器；未新增专用图形生成器；复用既有 profile 分类与三态判据；
- 未改动既有终态词表：`not_checked` / `unverified` / `partial` / `coverage=unsupported_semantic_kind` 含义不变；
- 未改动 H2/H3/H4、`max_repairs`；未缩小既有检查范围、未删除断言、未放宽阈值；
- 未编辑解释器与门禁谓词文件（以 `git diff --name-only` 为准）；
- 星形仍是**已识别但无完整验收器的能力缺口**：本轮只修复"适用性被静默丢弃并放行"，不构成星形验收能力已解决；`no_verifier_for_star_profile` 仍表示未验证，不得计为通过。

## 8. 本轮新增字段与函数

- 报告字段：`applicable_requirement_kinds`（既有，适用强制要求）、`ambiguous_requirement_kinds`（新增，未解决歧义信号）、`ambiguity_resolution`（新增，`confirmed_by_geometry` / `resolved_non_star`）。
- 调度模块新增：`AMBIGUOUS_SHAPE_PATTERNS`、`ambiguous_requirement_kinds_from_text`、`collect_ambiguous_requirement_kinds`；三态判据返回 `ambiguous_requirement_kinds` 与子原因 `ambiguous_requirement`。
- 验收模块新增：空要求分支辅助扫描 `_generic_profile_targets` / `_verify_no_recognized_requirement`；包装层同步标注歧义清单。
