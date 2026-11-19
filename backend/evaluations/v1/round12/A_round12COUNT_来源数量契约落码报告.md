# R-02-COUNT 来源数量契约最小方案（源侧）落码报告

## 1. 范围与基线

- 基线提交：`e801f25`（ownership-based object count consistency backstop）
- 分支：`r02-objcount-fix`；独立工作树 `worktrees/tmp/r02-objcount-fix`
- 唯一生产改动：结构契约模块 `backend/app/cad_structure_contract.py`
- 探针（零模型、无网络）：`backend/evaluations/v1/round12/A_round12_objcount_probe.py`
- 未触碰：解释器、解析器、执行器、拓扑、候选门禁、Projection/Repetition 生产者、R-04 语义两模块、H2/H3/H4、`max_repairs`、FEATURE-CONTRACT 公共接口、Plan v1 schema、参考数据库。
- G1（`validate_plan_structure`）本轮完全不读新字段，不把对象数量与计划步骤数直接比较；执行后归属对账仍由解释器侧既有 helper 做最终判定。

## 2. 契约内部字段（内部结构，未扩公共 API / Plan v1）

在组成契约内部挂载以下字段；状态为 `none` 时既有契约与其 `None` 回落保持原样，不注入空字段。

| 字段 | 类型 | 语义 |
| --- | --- | --- |
| `object_requirements` | `list[dict]` | 来源侧逻辑对象数量要求条目；每条含 `object_noun`、`quantity`（归一化正整数）、`measure_word`、`evidence`（原文片段）、`evidence_span`（来源位置 `[start, end]`）、`source_id`（`request-0`） |
| `object_requirements_state` | `"none" \| "complete" \| "incomplete"` | 三态完整性：无对象数量要求 / 全部可识别 / 存在未捕获或歧义短语 |
| `logical_object_count` | `int \| None` | 仅 `complete` 时给出 `Σ quantity`；`incomplete`、`none` 一律为 `None` |
| `object_requirements_audit` | `list[dict]` | 内部可审计清单：每条带原文片段、原始数量词、量词、归一化名词、处置结论与位置，供复核“为什么是 complete / incomplete” |

### 三态判定（全或无）

- `none`：原文确实没有对象数量要求——无数量词；数量词只修饰属性/重复特征；或数量短语归属于既有原语类型（矩形、圆、线段、圆弧、多边形等）。既有契约与 `None` 回落不变。
- `complete`：所有可检测到的对象数量短语都绑定到既有对象名词位，无歧义、无遗漏；`logical_object_count` 为各条目数量之和。
- `incomplete`：存在未捕获或歧义的数量短语（含“只识别出一部分对象”的情形）；全或无，`logical_object_count=None`，已识别条目可留在 `object_requirements` 供审计，但不据此产生数值。

## 3. 提取规则（复用既有语法位与分类，不扩词表、不建专用解析器）

- 数量必须落在“创建动词位 + 量词 + 对象名词”结构内；创建动词位取自既有动词集合（生成 / 创建 / 新建 / 绘制 / 画出 / 画 / 设计），允许位为动词所在句及其前后相邻句。量词（个 / 块 / 张 / 朵 / 颗 / 幅 / 组）仅作旁证。
- 对象名词复用既有分类：盒体名词（立方体、正方体）为对象位；既有原语类型（矩形、长方形、正方形、圆、线段、直线、圆弧、三角形、多边形、五角星、六边形、五边形、四边形、椭圆、圆孔、圆点、孔等）归 `primitive_owned`，不另立对象条目；属性/特征词（棱、边、面、顶点、齿、瓣、段、单元、分支、支臂、臂、横线、条带、网格、齿顶、齿根、角等）归 `attribute_feature`，不得进入对象名空间；其余名词归 `ambiguous`。
- 数量归一化：阿拉伯数字与中文数字（一/二/两/三…十）映射为整数；`quantity < 2` 记为 `single_object`，不立对象条目，也不把歧义单数短语升级为 `incomplete`。
- 数量只来自原文证据：计划步骤数、计划语义身份、阵列行列、模板 `quantity`、`EntityCountAssertion.equals`、扁平实例数、几何外观一律不得升格为用户契约。
- 无法判断是对象还是属性时：不生成条目，状态置 `incomplete`（不造数值）。

### 既有门消费方式（零重复门）

- 既有类型计数门 `validate_explicit_composition` 对新 kind `object_inventory` 早退：该 kind 只承载逻辑对象数量要求，不进既有图元类型计数比对；类型库存门继续管原语，执行后归属对账做最终对象数量判定。
- 未新增第二个数量门，未改公共接口；既有 `component_count` / `rectangular_array` / `corner_placement` / `line_inventory` / `named_components` 路径在 `none` 状态下行为不变。

## 4. 探针实测（零模型）

### 4.1 必须生成（complete）

| 输入 | 结果 |
| --- | --- |
| 两个立方体并排，画等轴投影 | kind=`object_inventory`，state=`complete`，条目 `{object_noun: 立方体, quantity: 2, measure_word: 个, evidence: 两个立方体并排, evidence_span: [0,7], source_id: request-0}`，`logical_object_count=2`，`counts={}` |

### 4.2 必须不生成（none，无条目，count=None）

| 输入 | 归属 |
| --- | --- |
| 一个立方体有 12 条棱 | 单数对象 + 属性词“棱” |
| 8 个齿的齿轮轮廓 | 属性/特征词“齿” |
| 长度 20 mm | 标量属性，无对象量词结构 |
| 角度 90 度 | 标量属性 |
| 3 条平行横线 | 重复特征“横线”，量词“条”不在对象量词位 |
| 正五边形 | 单原语，无数量要求 |
| 外径 2 米 | 标量属性 |
| 边长 50 毫米 | 标量属性 |

### 4.3 部分解析（incomplete）

| 输入 | 结果 |
| --- | --- |
| 画三个立方体和两个怪东西 | state=`incomplete`，`logical_object_count=None`；审计清单保留已识别条目“立方体 ×3”与歧义条目“怪东西”；既有 `named_components` 结构未被破坏 |

### 4.4 既有原语对照

| 输入 | 既有契约 | 库存状态 |
| --- | --- | --- |
| 生成两个相交圆组成的轮廓 | `component_count`，`counts.circle=2` | state=`none`，圆归 `primitive_owned`，不另立对象条目 |

探针退出码 0，`failures: []`。

## 5. 既有测试回归

- `test_cad_structure_contract.py`：35 passed。
- `test_cad_requirement_contract.py`、`test_cad_requirement_ledger.py`、`test_cad_construction_interpreter.py`：91 passed。
- 组合追加、来源验收、语义验收、投影/重复/路径关系/笔画验收、最终来源契约共 8 个相关文件：158 passed，2 failed。
- 两项失败均为基线既有语义失败（`test_cad_semantic_acceptance.py`：`test_structural_counter_schema_preserves_multiple_paths_without_coordinates`、`test_unsupported_styles_and_multiple_objects_are_not_falsely_fully_verified`），与本补丁无关，无新增失败。

## 6. 合法场景不误伤判据

- 两个对象正常生成：来源对象名词位 + 数量 ≥2 且可识别 → `complete`，条目与数量进契约，交由既有门与执行后对账消费。
- 单对象：`quantity < 2` → `single_object`，不立条目；普通单原语/单轮廓保持既有 `none` 与 `None` 回落。
- 多段单对象（同归属多图元）：不按图元实例数推断对象数；库存只看来源数量短语。
- 显式共享 N:1：复用既有布局/共享尺寸语义，本补丁不新增对象计数拦截。
- 无数量要求：`none`，不制造额外阻断。

## 7. 落码边界核对

- 生产文件清单：仅结构契约模块 1 个；探针为零模型辅助脚本，不计生产改动。
- 未改解释器读取侧：`object_requirements` 字段已在契约内承载；解释器侧对账 helper 的读取适配由后续 C 环节配合，本轮不越界。
- 未新增 NLP 词表、未新增专用解析器；未触碰 Plan v1 schema 与 FEATURE-CONTRACT 公共接口。
