# R-IDENTITY-1 源侧条目标识落码说明（一期）

- 基线：`ee57143`（数量对账已 CLOSED，未改其判据）；分支 `r-identity1`，独立工作树 `worktrees/tmp/r-identity1`。
- 唯一生产文件：结构契约模块 `backend/app/cad_structure_contract.py`。
- 纪律：零真实模型；未触公共 API、Plan v1、执行器、拓扑、候选门禁、解释器（C 负责读取侧）；未新增专用生成器/验收器。

## 1. 条目新增内部字段

| 字段 | 语义 |
| --- | --- |
| `requirement_id` | 本次请求内局部编号 `request-0:object-{i}:{category}`；非稳定来源身份。条目身份由 `evidence_span` 锚定，类别后缀仅作可读提示，类别调整不改变跨度锚定的同一条目 |
| `source_clause_index` | 原文分句索引（审计记录与条目同带） |
| `expected_category` | 复用既有 `disposition` 枚举（`object / primitive_owned / attribute_feature / ambiguous`），审计处置上提为正式条目，未新增类别词表 |
| `evidence_occurrences` | 同文本短语在来源中的全部出现位置列表，供重复短语消歧 |
| `evidence_valid`（审计位） | 原文切片 `source[evidence_span] == evidence` 是否成立 |

## 2. 原文证据校验

- 每条候选短语在记录跨度后即时切片比对；不成立则处置为 `evidence_mismatch`，进入歧义清单 → 契约 `incomplete`，不造数值、不造绑定依据。
- 校验只复用来源文本与既有跨度，不引入模型自报、步骤数或几何外观。

## 3. 未改动项

- 数量提取与三态语义：`quantity` / `measure_word` / `logical_object_count` / `none-complete-incomplete` / `object_inventory` 契约形态保持原样。
- 属性数量反例（12 条棱、8 个齿、长度 20 mm、角度 90 度、3 条平行横线、正五边形、外径 2 米、边长 50 毫米）仍不建条目。
- 未新增形状专用分支；本模块只承载对象名词 + 数量 + 原文证据 + 类别，类型判定归后续 C 侧。

## 4. 自测结果（零模型探针）

- `两个立方体并排，画等轴投影`：`complete`，条目 `requirement_id=request-0:object-1:object`，`expected_category=object`，切片校验通过，`evidence_occurrences` 仅自身跨度。
- `生成两个立方体和两个立方体`：两条目 id 不同，`evidence_occurrences` 各含两处位置 `[[2,7],[8,13]]`，无冲突；`complete`，count=4。
- 八条属性反例：全部 `none`，无条目，count=None。
- `画三个立方体和两个怪东西`：`incomplete`，count=None。

## 5. 数量侧回归

- `test_cad_structure_contract.py`：35 passed。
- `test_cad_requirement_contract.py` + `test_cad_requirement_ledger.py` + `test_cad_construction_interpreter.py`：91 passed。
- 组合追加 / 来源验收 / 语义验收 / 投影 / 重复 / 路径关系 / 笔画 / 最终来源契约共 8 文件：158 passed，2 failed；两项为基线既有语义失败（`test_cad_semantic_acceptance.py` 两项），无新增失败。

## 6. 边界

- 解释器读取侧（条目 ↔ 对象绑定、`unmatched_entries / unmatched_objects / ambiguous_bindings`）由 C 后续接线，本轮未改。
- 多轮逐源 `source_id` 编号为后续衔接项；本期局部 id 仍基于固定 `request-0`。
