# A 线 · 第四轮 A9（爱心）规划表达层根因分析报告

> 性质：只读诊断，零模型调用、零联网、零真实请求；未改 `backend/app` 生产代码，未重跑 A9，未覆盖历史证据。
> 执行基线：组合树 `f89bf41facfb7032cbb9647250cff6bbdcc6bbb7`（A1.1 `ea8323a` + B1.2 `d7e00bd` + C1.2 `49d48de`）。代码行号均以该基线后端为准；本分支（`v1/a1-constraint-inheritance`）个别文件行号可能漂移，引用时以函数名为准。
> 证据范围：第四轮仅 A9 一个真实案例、两次 `deepseek-flash` 调用；**本报告结论不外推为整体模型或整体链路结论**。
> 关联证据（只读，未改写）：
> - `evaluations/v1/D1_round4_A9真实模型受控评测报告.md`
> - `evaluations/v1/round4/A9_case_record.json`（下称"案例记录"）
> - `evaluations/v1/round4/A9_raw_responses.jsonl`（仅 id/model/finish_reason/usage，不含提示词正文）
> - `evaluations/v1/D1_round4_budget_ledger.json`
> - 本报告配套只读探针：`evaluations/v1/probes/a_round4_a9_geometry_probe.py`

---

## 0. 首段结论

1. **"下方尖点"不是"编码了但模型没遵守"，而是在需求抽取与契约两层就没有被编码为可校验事实**；它只在形状语义模式层被识别为一段自由文本指令，进入首轮提示词，但在计划 schema 中**没有任何字段可以承载**方向极值、尖点或镜像对称约束。后端只能在几何生成之后做事后特征检测，检测本身生效且判定正确。
2. 首轮计划对**闭合、宽高 4、中心 (2,3)** 有计划字段与断言表达；**左右对称与尖点居中均未编码为约束**。尺寸/中心在本轮无落库几何可独立复核，记录中也未出现尺寸不符错误。
3. 第二轮修复上下文中，`lower_tip=false`、失败特征、修复指令、受影响引用与旧计划**都已进入**反馈文本；但反馈只给了布尔特征与自由文本，**没有把缺失结构翻译成可执行的结构规格**，且修复路由被框定为"局部原地修改、禁止重新生成"。
4. 第二轮只改参数区间，是三因素叠加：修复提示词框定原地修改、反馈形态只报布尔不给结构目标、参数曲线 schema 下改区间是合法且最低成本的编辑；进度判定按计划 JSON 不等计进展，不比较几何等价性。
5. 归类：**多类叠加**——主因属"参数曲线语义表达 / 规划约束缺口"（A），次因属"失败反馈不足"（C）；"拓扑规划"（B）不是本轮根因，B 侧检测阈值与归一化覆盖留待交叉验证。

---

## 1. 根因链（分层对照）

### 1.1 分层链路图

```text
用户原文：生成一个左右对称、平滑闭合的爱心，中心在(2,3)，宽4米高4米
   │
   ├─ L1 需求抽取（需求账本 evidence_items）
   │     模式表只识别 数量/尺寸/位置/朝向/连接/单位
   │     ✗ 无"对称"类别  ✗ 无"尖点/凹口/凸瓣"拓扑特征类别
   │     结果：对称、尖点未产出证据项；"爱心"仅作为名词主语留存
   │
   ├─ L2 Requirement Contract（标量事实契约）
   │     只抽取 width/height/radius/… 标量事实
   │     ✗ 无方向极值/尖点/对称事实字段  ✗ 中心坐标未绑定为事实
   │     结果：契约有效事实仅 宽4000mm、高4000mm
   │
   ├─ L3 形状语义模式（semantic_requirements）
   │     ✓ 识别"爱心"并产出自由文本 instruction（含"底部中央尖点"）
   │     ✗ instruction 未转成结构化特征清单（方向/类型/对称轴）
   │     消费点：① 拼进提示词自由文本块；② 仅调整 schema steps.minItems
   │
   ├─ L4 结构化提示词
   │     ✓ 自由文本语义块随 model_text 进入首轮请求
   │     ✗ 提示词主体无对称/尖点的可校验字段指引；来源索引只回链原文
   │
   ├─ L5 计划 schema
   │     断言 union：entity_count / bounds_size / closed / area / radial_pattern / center_distance
   │     约束 union：concentric / parallel / perpendicular / equal_radius / equal_size / center_distance
   │     参数曲线步骤：仅 x_expression / y_expression / t_start / t_end / max_sampling_error / closed
   │     ✗ 无极值/尖点断言  ✗ 无镜像对称约束  ✗ 参数曲线步骤无连接约束/来源引用字段
   │
   └─ L6 后端几何验收（事后测量，非规划约束）
         ✓ 实测四特征：center_notch / left_upper_lobe / right_upper_lobe = true，lower_tip = false
         ✗ 规划期没有任何可对照的尖点/对称约束可供提前拦截
```

### 1.2 逐层证据位置与原文引用

#### L1 需求抽取：对称与拓扑特征无对应抽取类别

- 代码：`backend/app/cad_requirement_ledger.py`，`evidence_items`，模式表 **105–112 行**：

  ```python
  patterns={
      "quantity":r"(?:\d+|[一二两三四五六七八九十]+)\s*(?:个|条|根|片|朵|颗|扇)",
      "dimension":rf"(?:长宽|宽高|宽度|高度|直径|半径|边长|间距|净距|宽|高|长)…",
      "position":r"(?:在左|在右|上方|下方|左上|左下|右上|右下|居中|圆心|中心)",
      "orientation":r"逆时针|顺时针|朝向|向上|向下|向左|向右|旋转…",
      "connection":r"不相交|相交|相连|连接|闭合|开口|相切|同心|平行|垂直",
      "units":rf"(?:坐标)?单位…",
  }
  ```

  六个类别中没有"对称/镜像"，也没有"尖点/凹口/凸瓣/局部极值"等拓扑特征类别。
- 案例记录实测证据项（`A9_case_record.json` 121–185 行）：仅 `quantity`（一个）、`connection`（闭合）、`position`（中心）、`dimension`（宽4米、高4米）；**无对称证据项，无尖点/凹口/凸瓣证据项**。
- 判定：**已查证**。"左右对称"在抽取层未落证据；"爱心"作为形状名词进入主语，但其子结构特征（双瓣、凹口、下尖点）未被抽取。

#### L2 Requirement Contract：只有标量尺寸事实，无对称/尖点/中心坐标事实

- 代码：`backend/app/cad_requirement_contract.py`
  - 支持字段 **29–31 行**：`宽/宽度→width、高/高度→height、半径→radius、外接圆半径、外径/直径、边长、宽高/长宽`；
  - 事实抽取正则 `PATTERN` **32–34 行**，只匹配"字段 + 数值 + 单位"的标量尺寸；
  - 契约覆盖声明 **132–134 行**：`supported_fields` 仅 `circumradius, diameter, height, radius, side_length, width`。
- 案例记录契约事实（199–230 行）：有效事实仅 `width=4000.0mm`、`height=4000.0mm`；中心从句被切为 `"中心在(2"`、`"3)"` 且 `subjects: []`（247–253 行），**未形成中心坐标事实**；无对称事实、无尖点事实。
- 中心坐标另一条路径也未命中：`backend/app/cad_coordinate_requirements.py:5-12` 只判断"控制点/顶点/端点 + 坐标 + 单位"是否齐备；`backend/app/cad_semantic_acceptance.py:82` 的中心实测正则要求 `几何中心|中心点` 后接坐标，A9 原文为"中心在(2,3)"，**不匹配该正则**。
- 判定：**已查证**。契约层不存在承载对称、尖点、中心坐标的事实字段；中心 (2,3) 在本轮是模型自拟布局，不是来源绑定事实。

#### L3 形状语义模式：识别了形状，但只产出自由文本，未结构化

- 代码：`backend/app/cad_semantic_acceptance.py`，`semantic_requirements` **37–59 行**；爱心分支 **42–43 行**：

  ```python
  if re.search(r'爱心|心形',text) and len(local_creation_objects(text)) <= 2:
      return [{'kind':'heart_outline_features','instruction':'爱心必须是单一闭合外轮廓，顶部左右两个凸瓣、中间凹口、底部中央尖点；参数曲线的坐标轴方向要保持该拓扑，不能用椭圆、单瓣曲线或上下颠倒的曲线替代。尺寸和中心由需求契约绑定。'}]
  ```

- 该 instruction 的两处消费：
  1. 拼入模型输入自由文本块：`backend/app/cad_construction_interpreter.py:566-567`：

     ```python
     if semantics:
         model_text+='\n[原文图形的基本结构关系；不指定字体或建筑细节]\n'+json.dumps(semantics,ensure_ascii=False)
     ```

  2. 仅用于收窄 schema 步数量：`backend/app/cad_construction_interpreter.py:1718-1725`（`_request_construction_schema` 中按 `semantics` 的 `representation_contract.minimum_path_count` 调整 `steps.minItems`）。
- 判定：**已查证路径**。语义"被识别"，但特征（双瓣/凹口/下尖点/左右对称）始终停留在自然语言字符串里，没有变成带方向、类型、对称轴的结构化条目；首轮提示词正文未持久化，模型实际读到的文本按上述路径重建（见 §3.3）。

#### L4 结构化提示词：自由文本可被忽略，无字段级约束指引

- 提示词主体：`backend/app/agent_service.py:6021-6132`。通用指引覆盖闭合、尺寸、参数曲线表达式白名单、重复结构等；**没有对称约束或尖点/极值特征的字段级输出要求**。
- 来源索引：`backend/app/cad_construction_interpreter.py:587-590`，只把契约来源原文交给模型供 `source_requirement_refs` 回链；索引条目中不含对称/尖点事实。
- 判定：**已查证**。提示词层唯一携带尖点信息的是 L3 的自由文本块；它不构成可校验约束。

#### L5 计划 schema：无处承载极值/尖点/对称

- 断言类型 union：`backend/app/cad_construction.py:565-571`，成员为 `EntityCountAssertion / BoundsSizeAssertion / ClosedAssertion / AreaAssertion / RadialPatternAssertion / CenterDistanceAssertion`；**无方向极值断言、无尖点断言、无对称断言**。
- 约束类型 union：`backend/app/cad_constraint_solver.py:80-90`，成员为 `concentric / parallel / perpendicular / equal_radius / equal_size / center_distance`；**无镜像/轴对称约束**。
- 参数曲线步骤：`backend/app/cad_construction.py:454-461`，字段仅 `x_expression / y_expression / t_start / t_end / max_sampling_error / closed`；连接约束 `junction_constraints` 只挂在复合路径步骤上（`cad_construction.py:289`，定义 259–275），**参数曲线步骤没有连接约束或来源引用字段**。
- 案例记录两轮计划：`constraints: []`（635、729 行），无 `junction_constraints`，无 `source_requirement_refs`；断言仅 `closed` 与 `bounds_size`（637–651、731–745 行）。
- 判定：**已查证**。即便模型想把"底部中心尖点、左右对称"写成计划约束，现有 schema 也没有对应字段；这是表达层缺口，不是模型遵从度问题。

#### L6 后端几何验收：事后检测生效，但规划期无约束可对照

- 爱心特征实测分支：`backend/app/cad_semantic_acceptance.py:199-225`；特征判据 **211–214 行**：

  ```python
  'center_notch': any(abs(x-.5)<.03 and .5<y<.9 for x,y in normalized),
  'left_upper_lobe': any(x<.45 and y>.85 for x,y in normalized),
  'right_upper_lobe': any(x>.55 and y>.85 for x,y in normalized),
  'lower_tip': any(abs(x-.5)<.1 and y<.01 for x,y in normalized),
  ```

- 案例记录实测（592–600、686–694 行）：`center_notch=true, left_upper_lobe=true, right_upper_lobe=true, lower_tip=false`，`failed_features=["lower_tip"]`。
- 判定：**已查证**。后端检测正确识别了尖点缺失；缺口在规划表达侧，不在检测侧（检测阈值合理性交 B 交叉验证，见 §7）。

---

## 2. 问题二：首轮计划是否满足其余要求（逐项证据）

| 要求 | 计划/断言证据（案例记录） | 后端校验结果 | 判定 |
|---|---|---|---|
| 闭合 | 步骤 `closed=true`（632 行）；断言 `heart.closed`，`kind=closed`（639–642 行） | 参数曲线闭合端点重合检查：`cad_construction.py:669-672`（端点距离 ≤ `max_sampling_error` 即闭合）；记录中无闭合类错误 | **计划层已表达**；几何闭合性无落库几何可独立复核（待验证） |
| 宽 4 | 断言 `bounds_size` `width=4.0, height=4.0, tolerance=0.001`（644–650 行）；布局 `width=4.0`（657–660 行）；契约事实 `width=4000.0mm`（200–214 行） | 布局后尺寸界检查：`cad_construction_interpreter.py:793-806`，偏差 >0.5mm 抛 `source_dimension_mismatch`；记录失败错误为 `structure_requirement_failed`，**未出现尺寸不符错误** | **推断**：post-layout 宽高在 0.5mm 界内；无落库几何，待独立复核 |
| 高 4 | 同上，`height=4.0`；契约事实 `height=4000.0mm`（216–230 行） | 同上 | 同上（推断 + 待复核） |
| 中心 (2,3) | 布局 `free_outline_layout.center={x:2.0, y:3.0}`（664–667 行）；布局平移执行：`cad_construction.py:905-908` | 契约无中心事实（L2）；本轮未对中心偏差做来源绑定复测，`acceptance_summary={}`（88 行） | **模型自拟布局已写入计划**；中心实测偏差待验证（无持久化几何，CGQ 不可计算） |
| 左右对称 | 无对称断言、无对称约束、无对称轴字段；`constraints=[]`（635 行） | 无对称验收项可对照 | **未编码**（已查证） |
| 尖点居中 | 无尖点/极值断言；`lower_tip=false`（596 行） | 后端实测底部中心尖点未检出 | **未编码且几何缺失**（已查证） |

补充探针事实（`a_round4_a9_geometry_probe.py`，均匀采样估计，非生产自适应弦采样）：
- 首轮表达式采样边界宽 4.000m；最低极值点归一化 x ≈ **0.702**（第二轮区间 ≈ **0.298**，镜像两侧），均在尖点中心带 `|x-0.5|<0.1` 之外；复现 `lower_tip=false`。
- 两个参数区间 `[0,2π]` 与 `[-π,π]` 的边界、宽高、中心、特征布尔完全一致：**改区间不改变闭曲线点集**，与记录 `step_diff.comparison=exact_plan_steps_not_geometric_equivalence`（776 行）一致。
- 探针为均匀网格估计，与生产 `cad_parametric.sample_curve`（98–138 行）自适应弦采样可能存在判定差异，交 B 复核。

---

## 3. 问题三：`lower_tip=false` 是否完整进入第二轮修复上下文

### 3.1 组装与序列化路径（已查证）

1. **诊断抛出**：`cad_semantic_acceptance.py:217-225` 抛 `StructureContractError`，details 含 `authority / check / geometry_id / measured_features / failed_features / normalization / repair_instruction`（此时尚无 `affected_output_refs`）。
2. **解释器捕获并补受影响引用**：`cad_construction_interpreter.py:857-883`：
   - 860–874 行：由 `geometry_id` 经符号表反查 `affected_output_refs`；
   - 880–882 行：除非 `requires_structural_replan` 置位，否则构建局部修复范围 `local_repair_scope`；
   - 883 行：包装为 `ConstructionPlanError("structure_requirement_failed", …, details=exc.details)`。
3. **错误序列化**：`cad_construction.py:54-63` `ConstructionPlanError.as_dict()` 输出 `schema/code/message/details`；挂到解释器结果：`cad_construction_interpreter.py:1049-1057`（`"construction_error": exc.as_dict()`）。
4. **修复轮回挂**：`backend/app/agent_service.py:6479-6512`：
   - 6488 行：`feedback` 取错误消息；
   - 6489–6492 行：追加 `"结构化验证证据："` + 完整 `construction_error` JSON；
   - 6495–6500 行：`rejected_plan` / `previous_plan` 序列化回挂；
   - 6508–6511 行：按 `local_repair_scope` / `affected_output_refs` 路由到局部修复或部件修复上下文。
5. **部件修复包装**：`agent_service.py:6223-6241`，把 `affected_output_refs` 与 `required_units` 注入回调输入；合并器 `cad_plan_component_repair.py:304-375`。

### 3.2 哪些信息进入了第二轮（已查证路径 + 案例记录存档）

| 上下文要素 | 是否进入第二轮 | 来源/位置 |
|---|---|---|
| 失败消息"爱心缺少双侧上凸、中央凹口或下方尖点" | 是 | 记录 587、681 行；回挂 6488 行 |
| `measured_features` 四特征布尔 | 是 | 记录 592–597；JSON 序列化 6489–6492 |
| `failed_features=["lower_tip"]` | 是 | 记录 598–600 |
| `repair_instruction`（含"下方中心尖点""仅改变参数区间不会改变完整周期的几何形态"） | 是 | 记录 602、696 行 |
| `affected_output_refs=["heart.outline"]` | 是 | 记录 603–605；路由 6510–6511、包装 6236–6237 |
| 前次完整计划（表达式/区间/断言/布局） | 是 | 6495–6500；记录 608–671 |
| 缺失特征的**结构规格**（方向、极值类型、所在轴、应测量的量与实测偏差） | **否** | 本轮命中的语义验收分支 details 中无对应字段；并行结构契约分支（`cad_structure_contract.py:352-356`）虽带自由文本 `required_features` 字典，但既未被本轮触发，也仍是自然语言描述，非可测量规格 |
| 结构/拓扑缺失分类标记（`requires_structural_replan`） | **否** | 爱心分支未置位；见 §4.1 |
| 对称约束回链要求 | **否** | 计划与诊断均无对称条目 |

### 3.3 第二轮模型实际看到的反馈片段（按代码路径重建，非持久化原文）

> 说明：`A9_raw_responses.jsonl` 仅留存 `id/model/finish_reason/usage`，**第二轮提示词正文未持久化**。以下片段依据 §3.1 代码路径与案例记录存档的 `construction_error` / 旧计划重建；字段值逐字取自记录，拼接顺序按代码，**未伪造未存档的内容**。

```text
后端试算反馈：前一次计划未通过验证：爱心缺少双侧上凸、中央凹口或下方尖点。
结构化验证证据：{"schema":"cad.construction-error.v1","code":"structure_requirement_failed",
"message":"爱心缺少双侧上凸、中央凹口或下方尖点",
"details":{"authority":"backend_measured_geometry",
"check":"heart_bilateral_lobes_notch_and_lower_tip","geometry_id":1,
"measured_features":{"center_notch":true,"left_upper_lobe":true,
"right_upper_lobe":true,"lower_tip":false},
"failed_features":["lower_tip"],
"normalization":"x/y normalized independently to measured bounds [0,1]",
"repair_instruction":"修复失败的上方双峰、中央凹口或下方中心尖点；仅改变曲线参数区间不会改变完整周期的几何形态。保留尺寸与中心布局。",
"affected_output_refs":["heart.outline"]}}
。请修正具体错误，不要无关重建；保留原始尺寸、数量和闭合要求。不能只提高confidence或修改断言来绕过检查。
若确有缺少的必要参数，请返回具体缺参澄清。
前次未通过的计划（仅供修正，禁止当成用户要求）：{…尝试1完整计划 JSON…}
```

部件修复回调另加包装（`agent_service.py:6229-6237`，重建）：

```text
后端部件合并协议：本次仅输出 affected_output_refs 对应的步骤，其他部件、布局和断言由后端保留，
禁止重新生成；不要添加辅助占位图形。保留失败步骤原有的 junction_constraints、continuity、
tangent_tolerance_deg 等有效约束，不得清空或放宽；若改变段结构，必须输出与新段结构匹配的完整连接约束集合。
plan.units必须保持原单位。此精简计划仅用于合并，合并后仍执行全部验收。
{"affected_output_refs":["heart.outline"],"required_units":"m"}
```

### 3.4 完整性判定

- **诊断数据本身完整进入**：布尔特征、失败特征、修复指令、受影响引用、旧计划均在第二轮上下文中，无字段在序列化链路中丢失。
- **诊断语义不完整**：反馈把"缺尖点"表达为一个布尔 `false` + 一句自然语言修复提示；没有告诉模型缺失的是哪一类结构元素（底部 -y 方向中心极值/尖点）、应在哪个表达式部位构造、用什么几何量判定。模型拿到的是"哪项没过"，而不是"缺什么结构、怎么算补上"。

---

## 4. 问题四：第二轮为何只改参数区间、没有重新规划几何

### 4.1 提示词约束：被框定为原地局部修复，禁止重新生成

- 修复分支判定：`agent_service.py:6485-6486`，`structural_replan` 要求 details 显式带 `requires_structural_replan` 且计划引用全部落在失败引用内。爱心诊断 details **未置位该标记**（对照置位样例：`cad_path_relation_acceptance.py:37、207`，`cad_semantic_acceptance.py:119、169`）。
- 非重规划分支文案：`agent_service.py:6503-6504`："请修正具体错误，不要无关重建；保留原始尺寸、数量和闭合要求。"
- 部件修复包装：`agent_service.py:6229-6234`："本次仅输出 affected_output_refs 对应的步骤，其他部件、布局和断言由后端保留，**禁止重新生成**"。
- 合并器侧约束：`cad_plan_component_repair.py:343-353`，更换构造操作且原步骤带连接语义时直接拒绝（`component_repair_op_change_requires_replan`）；策略字段不得放宽（218–250 行）。

### 4.2 反馈形态：只报布尔与自然语言，未给结构目标

- 反馈可执行信息集中在 `repair_instruction` 自由文本（记录 602 行）；它甚至提示了"仅改变曲线参数区间不会改变完整周期的几何形态"，但**没有把尖点翻译成结构规格**：例如"在 -y 方向中心轴上构造一个局部极值尖点；该点两侧切线不连续（C0 尖点），而非平滑极小值"。
- `measured_features` 只有四项布尔；没有实测极值点位置、偏离中心带距离、两侧切线夹角等可供模型定位结构缺陷的量。
- 结果：模型无法从反馈区分"表达式结构缺尖点"与"参数周期/区间不对"；在禁止重建的框定下，改区间是阻力最小的选择。

### 4.3 schema 合法性：改区间是参数曲线步骤下的合法编辑

- `AddParametricCurveStep`（`cad_construction.py:454-461`）允许编辑 `x_expression / y_expression / t_start / t_end`；改 `t_start/t_end` 不触碰任何受保护策略字段，合并器不拦截。
- 该步骤类型**没有**承载尖点/对称/连接约束的字段（见 §1.2 L5）；模型即便想声明"底部中心尖点"，也无字段可写。
- 进度判定不比较几何等价性：`cad_generation_recovery.py:44-51`，`bounded_repair_available` 比较错误签名与计划 JSON 是否不等；区间改动使计划 JSON 变化，即被计为"有变化"。记录 `changed_plan_fields=["steps"]`、`step_diff.comparison="exact_plan_steps_not_geometric_equivalence"`（766–777 行）——**进度闸门识别了计划字段不同，但不识别几何等价**。

### 4.4 综合判定

第二轮只改区间，是"局部修复框定（4.1）+ 反馈缺结构规格（4.2）+ schema 无结构字段且区间编辑合法（4.3）"三因素叠加；其中 4.1 与 4.3 属规划表达/链路机制，4.2 属反馈结构化不足。模型动机本身无自述日志，本节对"为何选区间"的判断为**推断**，依据是提示词框定、schema 字段与反馈形态，不代表模型内部决策过程。

---

## 5. 问题五：归类

| 候选类别 | 是否主因 | 理由（证据） |
|---|---|---|
| 参数曲线语义表达 / 规划约束缺口（A） | **主因** | 尖点与对称在 L1/L2 未编码为事实，L5 schema 无字段承载（§1.2）；模型首轮即未规划出尖点结构，且无约束可对照 |
| 失败反馈不足（C） | **次因，叠加** | 诊断数据完整回挂，但缺结构规格与分类标记；修复上下文被框定为局部原地修改（§3.4、§4.1–4.2） |
| 拓扑规划（B） | **非本轮根因** | 后端特征检测正确检出 `lower_tip=false`；未检出自相交。B 侧待验证的是检测阈值/归一化对参数曲线轮廓的覆盖充分性，而非规划缺陷本身 |

对照 D1 统一失败分类口径：本轮顶层属 `logic_failure / geometry_acceptance_mismatch`；子层根因为"规划约束缺口 + 反馈结构化不足"，检测链路本身有效。

---

## 6. 可测量的通用几何特征约束设计（与 B/C 对接的第一环）

> 本节面向通用几何类别，**不为爱心新增专用提示词、专用生成器或专用控制点补丁**；现有爱心/星形线/cardioid/对称分支等场景应复用同一套测量原语。

### 6.1 需求层语义类别（通用归类，不绑定形状名）

| 通用类别 | 语义定义 | 典型来源措辞（示例，非枚举） |
|---|---|---|
| 方向边界极值 `boundary_extremum` | 轮廓在指定法向（-x/+x/-y/+y）上存在局部或全局极值点 | 下方尖点、上方凸峰、外侧突出 |
| 尖点 `cusp` | 极值点处两段切线不连续（C0 转折），区别于 G1/C1 平滑过渡；可用两侧切线夹角或曲率符号突变判定 | 尖点、尖角、尖端 |
| 镜面对称 `mirror_symmetry` | 轮廓关于给定轴（竖直/水平）镜像后重合 | 左右对称、上下对称 |
| 对称轴定位 `on_axis` | 目标极值点落在中心对称轴上 | 尖点居中、凸峰居中 |

### 6.2 Contract / 计划 schema 落点（建议字段、类型、取值语义）

**建议新增断言**（挂现有 `ConstructionAssertion` union，`cad_construction.py:565-571`；模型类仿 `BoundsSizeAssertion` 525–531 行）：

```text
BoundaryExtremumAssertion
  assertion_id: str
  target_ref: str
  direction:   Literal["-x", "+x", "-y", "+y"]      # 极值所在法向
  extremum_type: Literal["local_min", "local_max", "cusp"]
  axis:        Literal["none", "vertical_center", "horizontal_center"] | None
  tolerance:   float                                  # 复用既有距离/角度容差口径，不新造阈值
```

**建议新增约束**（挂现有 `ConstructionConstraint` union，`cad_constraint_solver.py:80-90`；仿 `CenterDistanceConstraint` 75–77 行）：

```text
MirrorSymmetryConstraint
  constraint_id: str
  target_ref: str
  axis:      Literal["x", "y"]                        # 对称轴
  tolerance: float                                     # 复用既有距离容差默认值
```

**来源授权（H3 不变）**：新断言/约束复用现有 `source_requirement_refs` 机制与校验（`cad_requirement_contract.py:151-175`），不为尖点或对称新开授权通道；无有效来源回链的条目按现有规则拒绝。

### 6.3 谁来测、测什么量、容差从哪来

| 测量项 | 测量方 | 测量量 | 容差/口径来源（既有，不为通过爱心新设） |
|---|---|---|---|
| 方向极值存在性 | 后端验收，不依赖模型自报；复用已采样轮廓点序列（参数曲线采样 `cad_parametric.sample_curve:98-138` → 多段线顶点） | 沿 `direction` 求归一化边界坐标的极值点及其归一化位置 | 归一化口径复用现有 `"x/y normalized independently to measured bounds [0,1]"`（记录 normalization 字段；`cad_semantic_acceptance.py:211-214`） |
| 尖点判定 | 后端验收 | 极值点两侧相邻采样段弦线夹角；或曲率符号突变/二阶差分 | 切线角度口径复用 `cad_topology_safety.py` `_chord_angle_deg`（406 行）与 `CONTACT_TANGENT`（75 行）；角度容差复用 `tangent_tolerance_deg`（`cad_construction.py:265、284`，默认 1.0） |
| 镜面对称 | 后端验收 / 约束求解器 | 镜像对应点对距离 | 距离容差复用 `center_distance` 口径（`cad_constraint_solver.py:44、553`，默认 0.001） |
| 极值点居中 | 后端验收 | 极值点归一化坐标与中心轴的偏离量 | 位置带复用现有特征检测带宽（`|x-.5|<.1`、`y<.01` 等，`cad_semantic_acceptance.py:211-214`），但参数化为通用归一化边界带，不写死爱心常量 |

原则：**所有判定阈值只引用既有容差族**（采样误差、切线角度容差、距离容差、归一化边界带）；新几何类别只新增测量原语，不为让某一形状通过而调阈值。

### 6.4 现有验证器最接近的挂载点

| 职责 | 挂载点（基线 f89bf41） | 通用化方向 |
|---|---|---|
| 计划 schema 与引用校验 | `CadConstructionPlan.validate_plan_graph`（`cad_construction.py:612-622`）；引用校验 `cad_plan_references.py` | 新断言/约束纳入现有图与引用校验 |
| 几何特征验收 | `verify_semantic_requirements`（`cad_semantic_acceptance.py:75` 起，爱心分支 199–225）；结构契约爱心分支（`cad_structure_contract.py:335-357`） | 把硬编码四特征字典改为消费计划断言/通用特征清单；现有爱心分支退化为通用检查的一个配置实例 |
| 约束求解 | `solve_geometric_constraints`（`cad_constraint_solver.py:117`） | 新对称约束进入现有求解/校验分发 |

### 6.5 有了这条约束后，第二轮反馈应当包含什么（交 C）

1. **缺失特征规格**：方向、极值类型、所在轴，以及实测量——极值点归一化坐标、偏离中心带距离、两侧切线夹角（或曲率判定结果），而不是单个布尔。
2. **失败分类标记**：区分"结构/拓扑缺失"与"参数/表达式微调"；结构类置位 `requires_structural_replan`（现有标记位用法：`cad_path_relation_acceptance.py:37、207`；`cad_semantic_acceptance.py:119、169`），修复轮相应解除"禁止重新生成"的局部框定（`agent_service.py:6503-6504、6229-6234`）。
3. **可判断性**：模型据此能区分"缺底部中心尖点结构"与"参数区间不对"；现有修复提示虽已警告改区间无效，但未给出结构目标，反馈结构化后应直接指向缺失类别与判定量。

---

## 7. 下一轮最小修改建议（三件套：改动 + 回归范围 + 回滚点）

> 本轮不改生产代码；以下为供主控批准的建议。所有改动保持纯增量，不放宽 H2/H3/H4、自相交、来源授权、候选保存条件，不增加 `max_repairs`。

### M1（A 线，优先级 1）：通用极值/尖点断言与镜像对称约束进入计划链路

- **改哪个文件 / 函数**：
  1. `backend/app/cad_construction.py`：`ConstructionAssertion` union（565–571）新增 `BoundaryExtremumAssertion`；
  2. `backend/app/cad_constraint_solver.py`：`ConstructionConstraint` union（80–90）新增 `MirrorSymmetryConstraint`；
  3. `backend/app/cad_semantic_acceptance.py`：`semantic_requirements`（37–59）把现有自由文本 instruction 同步产出结构化特征清单（方向/类型/轴），不新增爱心专用措辞；
  4. `backend/app/cad_construction_interpreter.py`：计划绑定处（仿 `bind_outline_requirements` 1490–1509）把特征清单写入计划断言/约束；
  5. 验收侧 `verify_semantic_requirements`（75）按 §6.3 通用测量原语核对断言。
- **改什么语义**：需求语义先归类为通用几何类别（方向极值/尖点/镜像对称/轴上定位），再落 schema 字段；后端按同一套测量量独立验收；H3 来源回链复用现有机制。
- **为什么是通用的**：字段面向任意方向极值、尖点与镜像对称，不绑定爱心；星形线四尖点、cardioid 尖点、对称分支等场景可复用同一测量原语。
- **回归范围**：现有 Mock 回放套件、A1.1/B1.2/C1.2 组合回归、语义验收与计划引用校验单测；空断言/空约束向后兼容，既有计划结构不变。
- **回滚点**：纯增量模型类与消费分支；回滚 = 删除新增 union 成员及对应绑定/验收分支。提交于 `v1/a1-constraint-inheritance`，不合并、不推送、不 amend。

### M2（C 线）：失败诊断结构化 + 结构类失败放行重规划

- **改哪个文件 / 函数**：`cad_construction_interpreter.py:857-883`（details 增特征规格与分类标记）；`agent_service.py:6485-6511`（按标记选择重规划/局部修复路由）。
- **改什么语义**：诊断携带缺失特征规格与实测量；结构类失败置 `requires_structural_replan`，解除局部重生成框定；参数/表达式微调类仍走现有局部修复。
- **回归范围**：有界修复循环、局部修复校验、部件合并测试、进度判定测试。
- **回滚点**：分类标记缺省 `False`；回滚即恢复现有局部修复路由与文案。

### M3（B 线，待交叉验证，本轮不改）

- 参数方程轮廓特征检测的归一化与阈值覆盖；尖点应否以切线夹角/曲率二阶差分判定；均匀网格探针与生产自适应弦采样的判定一致性。

---

## 8. 已查证 / 推断 / 待验证清单

### 8.1 已查证（代码路径 + 案例记录原文）

- 两轮计划字段、表达式、参数区间、断言、布局（记录 608–671、702–763）。
- 后端实测四特征布尔与失败特征（记录 592–600、686–694）。
- 真实 usage 与费用：输入 31554（命中 15872 / 未命中 15682）、输出 804、0.005764632 USD（记录 314–319；账本 70–75、135–142）。
- 各层字段有无、修复分支路由、错误组装与序列化链路（基线 f89bf41 源码，行号见 §1、§3、§4）。
- 探针复现 `lower_tip=false`；两参数区间几何等价（采样估计）。

### 8.2 推断（有证据支撑，但非直接观测）

- 尺寸界检查未报错 → post-layout 宽高在 0.5mm 容差内；记录无 `source_dimension_mismatch`，但无落库几何复核。
- 模型第二轮选择只改区间的动机：由提示词框定、schema 合法性、反馈形态三方推断；无模型自述日志。
- 首轮提示词确实携带爱心语义块：按解释器组装路径推断；提示词正文未持久化，未逐字存档。

### 8.3 待验证（交 B/C 或下一轮受控评测）

- 中心 (2,3) 在 post-layout 几何上的实测偏差；本轮无持久化几何，CGQ 不可计算。
- 探针均匀网格与生产自适应弦采样在尖点判定上的一致性；尖点切线夹角/曲率口径是否替代单点位置带宽。
- 对称约束缺口对其他形状案例的影响范围；**单案例结论不外推**。
- 确定性爱心模板（`agent_skills.py:1672-1682` `heart_outline_geometry`）为何未被本轮规划路由选用（模板识别与路由条件），留待路由侧核查。

---

## 9. 最需要 B / C 交叉验证的两点

1. **交 B（几何检测）**：现有 `lower_tip` 检测带宽（`|x-.5|<.1`、`y<.01`）与独立归一化方式，对参数方程轮廓是否充分；尖点判定应否引入两侧切线夹角或曲率二阶差分，而非仅看单点位置；均匀采样与生产自适应弦采样的判定一致性。
2. **交 C（修复链路）**：结构类失败如何在不放宽局部修复保护（H2/H3、候选保存条件）的前提下放行重规划；`requires_structural_replan` 的判定条件与修复轮上下文（旧计划、受影响引用）保留方式；进度判定应补充几何等价性比较，避免"只改参数区间"被计为实质进展（现状：`cad_generation_recovery.py:44-51` 按计划 JSON 不等计进展）。

---

## 10. 附录：证据文件与代码索引

| 编号 | 文件 / 位置 | 用途 |
|---|---|---|
| E1 | `evaluations/v1/round4/A9_case_record.json` | 两轮计划、诊断详情、契约事实、恢复记录 |
| E2 | `evaluations/v1/round4/A9_raw_responses.jsonl` | 两次请求脱敏元数据（usage），无提示词正文 |
| E3 | `evaluations/v1/D1_round4_budget_ledger.json` | 逐请求 usage、缓存拆分、费用与限额消耗 |
| E4 | `evaluations/v1/D1_round4_A9真实模型受控评测报告.md` | 首轮受控评测结论与六项预检留证 |
| C1 | `backend/app/cad_requirement_ledger.py:90-125` | 需求证据抽取模式表 |
| C2 | `backend/app/cad_requirement_contract.py:29-34,64-134,151-175` | 标量事实契约、来源引用校验 |
| C3 | `backend/app/cad_semantic_acceptance.py:37-59,75-100,199-225` | 语义指令识别、中心实测、爱心特征验收 |
| C4 | `backend/app/cad_construction_interpreter.py:539-594,857-883,1049-1057,1463-1509,1702-1725` | 模型输入组装、错误捕获挂接、轮廓要求绑定、schema 收窄 |
| C5 | `backend/app/cad_construction.py:54-63,259-289,454-461,565-571,579-622,669-672,867-908` | 错误序列化、连接约束、参数曲线步骤、断言/布局模型、闭合检查、布局平移 |
| C6 | `backend/app/cad_constraint_solver.py:44,75-90,117` | 约束类型 union、距离容差、求解入口 |
| C7 | `backend/app/agent_service.py:6021-6132,6223-6241,6313-6335,6479-6512` | 规划提示词、部件修复包装、输入快照、修复循环与回挂 |
| C8 | `backend/app/cad_plan_component_repair.py:218-250,304-375` | 策略字段保留、部件合并与操作变更拦截 |
| C9 | `backend/app/cad_generation_recovery.py:7-22,25-51,76-90` | 失败分类、有界修复进展判定、计划差异记录 |
| C10 | `backend/app/cad_parametric.py:98-138` | 参数曲线自适应采样 |
| P1 | `evaluations/v1/probes/a_round4_a9_geometry_probe.py` | 本轮只读几何探针（纯标准库，零网络零模型） |
