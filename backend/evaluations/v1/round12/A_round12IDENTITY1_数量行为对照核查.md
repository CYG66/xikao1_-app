# R-IDENTITY-1 源侧新字段数量行为对照核查（只读）

- 基线：`ee57143`（数量对账 CLOSED 冻结）；对照树 `r02-objcount-fix`，当前树 HEAD `094d2f7`。
- 纪律：零模型；未改生产代码、未建分支/提交、未合并/推送/amend。
- 范围：只核查源侧标识字段是否改变已验收数量行为；解释器身份子报告属 C 侧，不在本次判据内。

## 1. 代码事实

### 1.1 结构契约模块相对基线的改动面

`backend/app/cad_structure_contract.py` 相对 `ee57143` 仅两处 hunk，全部位于 `_object_requirement_inventory`：

- 审计记录增加 `source_clause_index`、`evidence_valid`；
- 条目增加 `requirement_id`、`expected_category`、`source_clause_index`、`evidence_occurrences`；
- 句末按证据文本回填全部出现位置。

以下数量相关形态**未改动**（无对应 hunk）：

| 项 | 状态 |
| --- | --- |
| `quantity` / `measure_word` 提取与归一化 | 未改 |
| `logical_object_count = Σ quantity`、三态 `none / complete / incomplete` | 未改 |
| `object_inventory` 契约形态、`explicit_composition` 遗留语法 | 未改 |
| `object_inventory_sidecar`（`none` 返回 None，其余整单透出） | 未改 |
| `legacy_composition_contract` 剥离清单（四个库存顶层字段） | 未改 |
| 顶层契约键 | 未新增；新字段均在 `object_requirements[]` 条目内部 |

### 1.2 数量对账 helper 逐字核对

解释器 `_logical_object_count_consistency` 基线与当前 HEAD 函数体 314 行前缀逐字一致（仅函数定义行因整体行号偏移不同）。数量判定顺序未变：

1. `incomplete` → `unverified`，不造数量结论；
2. `complete` → 取 `logical_object_count` 与归属分组 N_obj 对账；
3. 遗留 T1 基线 / 参考结构 / 轮廓基线依次兜底；
4. 无基线 → 多主体弱信号 `unverified`，否则 `not_checked`；
5. 归属台账不可判 → `unverified`；
6. 数量相等 `passed`；不等 `failed`，`missing_object` / `extra_object`。

### 1.3 新字段的消费点

- 数量 helper 仅读取 `object_requirements_state`、`object_requirements`（条目内 `object_noun` / `measure_word` / `evidence`，并整体 deepcopy 透出）、`logical_object_count`。
- `requirement_id`、`expected_category`、`source_clause_index`、`evidence_occurrences`、`evidence_valid` 不进入数量比对，不参与 `counts` / `names` / `rows` / `columns` / `kind` 判断。
- 条目级新字段随 `object_requirements` 顶层键被 `legacy_composition_contract` 整体剥离，遗留门禁不可见。
- 解释器身份子报告读取 `requirement_id` 属 C 侧独立报告，不回写数量 `object-count-consistency` 判据。

### 1.4 `evidence_valid` 降级条件

仅当 `source[evidence_span] != evidence` 时，条目置 `evidence_mismatch` → 歧义清单 → `incomplete` → 对账 `unverified`，不造数值、不造绑定依据。现有正则与分句偏移为确定性算术，探针与回归语料中已捕获短语 `evidence_valid` 均为 `true`；未发现基线已通过用例被该规则降级。

## 2. 双树逐例对照（15 例，零模型同口径探针）

| 案例 | 基线状态 | 基线实际/期望/失配 | 当前树状态 | 当前树实际/期望/失配 | 一致 |
| --- | --- | --- | --- | --- | --- |
| 库存 2 缺 1（两个立方体…） | failed | 1 / 2 / missing_object | failed | 1 / 2 / missing_object | 是 |
| 库存 2 对 2 | passed | 2 / 2 / — | passed | 2 / 2 / — | 是 |
| 遗留两圆 2/2 | passed | 2 / 2 / — | passed | 2 / 2 / — | 是 |
| 要求 2 实际 3 圆 | failed | 3 / 2 / extra_object | failed | 3 / 2 / extra_object | 是 |
| 单对象四段轮廓 | not_checked | 1 / 无基线 / — | not_checked | 1 / 无基线 / — | 是 |
| 共享几何两归属 | passed | 2 / 2 / — | passed | 2 / 2 / — | 是 |
| 12 条棱 | not_checked | 无基线 | not_checked | 无基线 | 是 |
| 8 个齿 | not_checked | 无基线 | not_checked | 无基线 | 是 |
| 长度 20 mm | not_checked | 无基线 | not_checked | 无基线 | 是 |
| 角度 90 度 | not_checked | 无基线 | not_checked | 无基线 | 是 |
| 3 条平行横线 | not_checked | 无基线 | not_checked | 无基线 | 是 |
| 正五边形 | not_checked | 无基线 | not_checked | 无基线 | 是 |
| 外径 2 米 | not_checked | 无基线 | not_checked | 无基线 | 是 |
| 边长 50 毫米 | not_checked | 无基线 | not_checked | 无基线 | 是 |
| 重复短语（两个立方体×2） | passed | 4 / 4 / — | passed | 4 / 4 / — | 是 |

库存三态与归一化数量在双树一致：正例 `complete`/2；重复例 `complete`/4；属性反例 `none`/无条目。R1 边界短语“两个相同的圆”双树同为 `none`（未被新规则升格）。

## 3. 回归计数（当前 HEAD）

- 结构契约 + 需求契约 + 台账 + 解释器：**126 passed**。
- 组合追加 / 来源验收 / 语义验收 / 投影 / 重复 / 路径关系 / 笔画 / 最终来源契约 8 文件：**158 passed，2 failed**；两项为基线既有语义失败（`test_cad_semantic_acceptance.py` 的 `test_structural_counter_schema_preserves_multiple_paths_without_coordinates`、`test_unsupported_styles_and_multiple_objects_are_not_falsely_fully_verified`），无新增失败。

## 4. 结论与处置

- 源侧新字段**未改变**已验收数量行为：数量提取、三态、计数判据、遗留门禁与对账 helper 均保持基线口径；15 例双树零差异。
- 无需在结构契约模块内修正；**本轮未追加提交**。分支提交链：`ee57143` → `f12ff2a` → `094d2f7`（`094d2f7` 为 C 侧身份子报告提交）。
- 未触公共 API、Plan v1、执行器、拓扑、候选门禁、Projection/Repetition、R-04、H2/H3/H4、`max_repairs`。
