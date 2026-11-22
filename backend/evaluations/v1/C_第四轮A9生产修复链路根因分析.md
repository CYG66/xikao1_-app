# C 第四轮 · A9 生产修复链路根因分析（只读、零费用、零真实请求）

> 分析对象：第四轮真实模型 `deepseek-flash` 跑 A9（爱心）的已落盘证据，**不重跑、不改证据**。
> 证据来源（只读）：`D 工作树/backend/evaluations/v1/round4/A9_case_record.json`、`round4/A9_raw_responses.jsonl`、`D1_round4_A9真实模型受控评测报告.md`。
> 本轮纪律：未实例化模型客户端、未联网；未改 `backend/app`；未提高 `max_repairs`；未放宽 H2/H3/H4、自相交、来源授权与候选保存条件；未为爱心加专用逻辑；未合并/推送/amend。
> 证据等级：**已查证**（代码行号 + 记录字段可复核）／**推断**（由代码路径推得，记录未直接留痕）／**待验证**（需后续受控运行或探针确认）。
> 预注册口径沿用 `C_第四轮指标口径_生产链路与五指标预注册.md`，本轮不回改定义。

## 0. 事实快照（已查证，摘自 A9_case_record.json）

- 九态：`failed`；`variants=[]`；`error_code=candidate_generation_failed`；`provider_attempted=true`；`request_count=2`。
- 尝试 1（`plan_sha256=7295796f…d391`，记录 :580-671）：单步 `add_parametric_curve`，ref `heart.outline`；
  - `x_expression=2+2*sin(t)`，`y_expression=3+2*cos(t)+2*sqrt(abs(sin(t)))*cos(t)`，`t_start=0`，`t_end=2*pi`（:627-630）；
  - 特征实测 `center_notch=true / left_upper_lobe=true / right_upper_lobe=true / lower_tip=false`，`failed_features=[lower_tip]`（:592-600）；`affected_output_refs=[heart.outline]`（:603-605）；码 `structure_requirement_failed`，类别 `model_plan_invalid`。
- 尝试 2（`plan_sha256=ecefd233…ac6cba`，记录 :673-778）：表达式逐字相同，仅 `t_start=-pi`、`t_end=pi`（:721-724）；特征复测不变，`lower_tip` 仍 `false`（:686-694）。
- 记录自陈：`changed_plan_fields=["steps"]`（:766-768）；`step_diff.comparison="exact_plan_steps_not_geometric_equivalence"`，`modified_refs=[heart.outline]`（:769-777）。
- 用量：请求 2 输入 16172 / 输出 450 tokens，费用 0.001026288 USD（报告 §3.2）；本轮合计 2 请求、输入 31554 / 输出 804、0.005764632 USD。

## 1. 第二轮为什么被当作"有效进展"——逐函数拆解

### 1.1 判定链路与各函数输入/比较/结论

| 函数（文件·行号） | 输入 | 实际比较了什么 | 对"表达式不变、仅参数域变"给出的结论 | 漏判点 |
|---|---|---|---|---|
| `should_repair`（`cad_generation_recovery.py:20-22`） | 单次尝试结果 `status / provider_attempted / construction_error.code`（`error.code`） | 仅判：`status=='invalid'` 且 `provider_attempted` 真且类别 ∈ {`model_plan_invalid`,`constraint_conflict`,`sampling_budget`} | A9 两轮均 `invalid` + 类别 `model_plan_invalid` → **允许进入修复**。完全不比较前后计划或几何 | 不具备任何"进展"语义；是否可修只看错误类别 |
| `bounded_repair_available`（`cad_generation_recovery.py:25-51`） | `construction_attempts` 列表、`max_repairs=2` | ① 轮次上限 `repairs>=max_repairs`（:32-34）；② `len(attempts)<2` 直接 `True`（:35-36）；③ 两轮以上才比较 `signature=(recovery_category, code, message, details JSON)`（:44-48）与 `before != after` 计划字典（:49-51） | **第二轮放行的直接原因**：决定是否发第二次请求时，`attempts` 只有 1 条，命中 :35-36 早返 `True`；前后计划/几何比对根本没参与这一次放行 | 进展比对只在"决定第三轮"时才运行；第二轮是在无前后对照下放行的 |
| `confidence_only_repair`（`cad_generation_recovery.py:54-60`） | `before / after` 两次结果 | 仅判窄形状：`before.diagnostic_trial_passed is True` 且 `before.error.code=='low_confidence'` 且 `after.status=='ready'` 且 `before.rejected_plan==after.plan` | A9 错误码是 `structure_requirement_failed`（非 `low_confidence`），`after` 仍 `invalid` → 不命中；该守卫不适用 | 覆盖范围仅限"只提置信度、原样复用被拒计划"这一种空转；不覆盖"几何等价但换参数域/换表达式外形"的空转 |
| `changed_plan_fields`（`cad_generation_recovery.py:77-79`，`recovery_record` 内） | 前后计划字典 | 顶层字段名集合差集：`before[k]!=after[k]` 即记为变更字段 | A9 计划字典里 `steps` 内 `t_start/t_end` 字符串不同 → 顶层判 `steps` 变更 | 字典不等 ≠ 几何改变；无几何等价比对 |
| `step_diff`（`cad_generation_recovery.py:80-90`） | 前后 `steps`，按 `output_ref` 配对 | 逐步**字典精确相等**：`old[k]!=new[k]` 记 `modified_refs`；标签自陈 `exact_plan_steps_not_geometric_equivalence`（:90） | 参数域字符串不同 → `heart.outline` 进 `modified_refs`，被记为"有步骤改动" | 比较的是计划文本字典，不是执行后轨迹；周期域平移在数学上轨迹等价，字典比对识别不出 |

### 1.2 漏判发生在哪一步（结论）

1. **放行第二步（主漏判）**：`agent_service.py:6477-6478` 的循环条件 = `should_repair(...) and bounded_repair_available(...)`。第二次请求前 `attempts` 仅 1 条，`bounded_repair_available` 走 `:35-36` 早返 `True`；**不存在任何前后几何/特征对照**。
2. **进展度量退化到计划文本**：即便进入两轮以上的比对，`before != after`（`recovery.py:49-51`）与 `step_diff`（:88）都是计划字典/字段级比较；参数域、变量名、等价表达式都会让字典不等，被记为进展。
3. **错误签名比对被 AND 短路且未参与第二轮**：`signature` 比较（:46-48）能识别"同一错误原样复现"，但它与 `before!=after` 是 AND（:51）；且本轮第二轮放行时该分支未触发。
4. 服务循环内的进展标记缺失：`agent_service.py:6521-6527` 只对 `confidence_only_repair` 做拦截并转 `invalid`；没有"几何无进展"对应分类。

## 2. 失败反馈是否真的到模型手里

### 2.1 组装与序列化路径（已查证）

- 反馈拼装：`agent_service.py:6480` 取 `construction_error.details`；`:6481` 收集 `affected_output_refs`；`:6486` `feedback=error.message`；`:6487-6490` 追加"结构化验证证据：" + 完整 `construction_error` JSON 序列化（`json.dumps(..., ensure_ascii=False)`）。
- 前次计划回挂：`:6493-6498` `rejected_plan = plan or rejected_plan`，序列化为"前次未通过的计划…"文本拼进 `model_input`。
- 第二次调用：`:6499-6510` 把反馈文本 + 前次计划 + 修复指令一起送入 `_interpret_cad_construction_plan`；无 `local_repair_scope` 但有 `affected_output_refs` → 走 `component_repair_context` 分支（`:6506-6509`）。
- 部件上下文包装：`agent_service.py:6224-6235` 从上下文取 `plan/rejected_plan`、`affected_output_refs`、`assertion_id`、`identity_only_repair`，向模型源文本追加合并协议文本 + `{affected_output_refs, required_units}` JSON；`:6239` 交 `merge_component_repair`。

### 2.2 模型实际可见 / 不可见字段对照

| 字段 | 是否进入模型可见文本 | 证据 |
|---|---|---|
| 错误 message（"爱心缺少…尖点"） | 是 | `:6486` |
| `measured_features`（`center_notch/left/right/lower_tip` 布尔） | 是，随完整 `construction_error` JSON | `:6488-6490`；记录 :592-597 |
| `failed_features=[lower_tip]` | 是 | 同上；记录 :598-600 |
| `check`、`authority`、`normalization`、`repair_instruction` | 是 | 同上；记录 :589-602 |
| `affected_output_refs=[heart.outline]` | 是（反馈 JSON + 部件上下文 JSON 两处） | `:6481, 6225, 6234` |
| 前次计划完整 JSON | 是 | `:6495-6497` |
| `assertion_id` | **未取得**：本轮是结构特征检查，错误顶层无 `assertion_id` | `:6226` 取不到；记录 :584-606 无该字段 |
| 失败特征的**目标几何量**（如尖点应落在的归一化 y 带、坐标阈值） | **未提供**：只有布尔特征与归一化说明，没有目标坐标/带宽 | 记录 :592-602；语义验收阈值见 `cad_semantic_acceptance.py:211-214` |
| 前后计划/几何差异对照 | **未提供**：只给前次计划，没有"上一轮哪项没动"的差异摘要 | `:6493-6498` |
| 上下文对象 `failed_attempt` 全量 | 服务端持有（供合并/校验），未整体序列化进提示词；仅 refs/units/身份位透出 | `:6508, 6224-6239` |

### 2.3 待验证项

- 第二次请求的**提示词正文未在记录中落盘**（`A9_raw_responses.jsonl` 仅 `id/model/finish_reason/usage`）；因此"模型是否解析并利用了 `lower_tip=false` 反馈"属 **待验证**，本分析只证明反馈字段在组装路径上进入了源文本。
- 顶层 `rejected_plan` 别名：本场景前次计划经 `plan` 回挂（`:6493`），未走 A1.1 `ComponentRepairError` 顶层 `rejected_plan` 形状。

## 3. 为什么缺少通用"几何无进展"识别

### 3.1 现有判据的边界

- 进展判定的输入只有**计划字典**与**错误签名**，没有执行后几何：
  - 失败路径返回形状不含 `trial_result/geometries`：`cad_construction_interpreter.py:1035-1043`（仅 `plan / construction_error / deterministic_repairs / confidence`）；几何附件只在 ready 路径出现（`:1062-1087` 的 `trial_result=result`）。
  - `recovery_record`（`cad_generation_recovery.py:63-71`）落库的尝试记录只存 `plan / error / confidence / plan_sha256`，不存几何指纹或采样点。
- `confidence_only_repair` 边界（见 §1.1）只拦截"低置信度 + 原样复用计划 + 转 ready"；对 `structure_requirement_failed` 下"轨迹等价、仅换参数域/外形"的空转没有判据。
- 语义验收阈值（`cad_semantic_acceptance.py:211-214`：归一化带 `.03/.45/.85/.1/.01`）只用于**当轮验收判定**，未被复用到**轮间进展比对**。

### 3.2 本案例为何漏网（已查证 + 推断）

- 已查证：表达式逐字相同；仅周期域 `[0,2π]→[-π,π]`；两轮特征布尔完全一致；步骤字典因域字符串不同被记 `modified`。
- 推断：对周期参数曲线，整周期域平移不改轨迹采样集合；计划字典不等被误当进展，特征向量未参与轮间比对，故第二次请求被判为"可继续修"。

## 4. B 判据接入点（C 与 B 的接口）

### 4.1 接入层建议

| 选项 | 层 | 输入 | 利弊 |
|---|---|---|---|
| **首选：恢复策略层** | `cad_generation_recovery.py::bounded_repair_available`（与既有轮次/置信度守卫同位） | 轮间尝试记录（计划 + 错误 details + 可选几何指纹） | 判定集中在"是否再发一次修复"，服务循环无需改路由；复用既有 `return False` 语义 |
| 备选：服务循环层 | `agent_service.py:6479-6510` 第二次调用前 | 活的 `failed_attempt` 与当前 `interpretation`（字段最全） | 能直接拿到上下文对象，但判定散在服务循环；与 `confidence_only_repair` 拦截点 `:6521-6527` 同位可仿 |

### 4.2 输入：计划还是执行后几何

- **最优输入**：修复前后执行几何采样（`trial_result.geometries`），用既有 `geometry_evidence_hash`（`cad_candidate_state.py:7-10`）、`geometry_fingerprint`（`cad_edit_gate.py:13-17`）或 `build_geometry_diff`（`geometry_diff.py:26-69`）做等价比对。
- **退化情形（当前失败路径拿不到几何）**：只能用计划字典 + 错误签名 + `details.measured_features` 布尔向量。此时：
  - 特征向量比对**能**覆盖 A9 这类"失败特征集合不变"的空转；
  - 计划文本比对**不能**证明几何等价（参数域、变量名、等价表达式都会制造字典差）；
  - 若要做几何级等价比对，需先让失败路径附带轻量几何快照（见 §7 建议 2）。

### 4.3 输出如何进入判定

- 不新增异常、不打断既有准备流程；先产出**进展分类**：`changed_geometry`（有实质几何移动）/ `stalled_equivalent`（几何或特征无进展）/ `confidence_only`（既有）。
- `stalled_equivalent` 走既有 `bounded_repair_available` 关闭语义：不再发下一次修复请求，保留当前 `invalid` 结果，recovery 记录追加 `progress` 字段；不持久化候选。
- 与现有拦截同形：仿 `agent_service.py:6521-6527` 的 `confidence_only_repair` 转 `invalid` 做法，给一个独立错误码（建议 `no_progress`，待批准），`next_action` 仍交人工/后续重试，不自动放宽。

### 4.4 安全终止与误杀兜底（`max_repairs=2` 不变、验收不降）

- 触发条件**双窄**：失败特征集合未变 **且** 几何证据等价（在**既有**容差内：计划 `assertions.tolerance`、`max_sampling_error`、`connection_tolerance`；不自创阈值）。
- 放行条件（任一成立即不算无进展）：① 任一先前失败特征转为通过；② 几何移动超出既有容差；③ 出现新的独立失败特征或新部件；④ 走 `structural_replan` 整体重编译分支（`agent_service.py:6483-6484, 6501`）。
- 第一轮修复始终放行（保留 `len(attempts)<2` 早返），不压缩既有一次修复机会。
- 误杀控制：几何等价判定只作为"不再自动发同渠道修复"的依据，不把案例判成产品通过；被终止案例仍记 `failed`，可由用户/下一轮重新生成；证据（前后指纹、特征向量、容差）入账本备查。

### 4.5 能否拦住 A9 这一轮，以及收益

- **特征向量 + 几何等价方案：能拦住**。两轮 `measured_features` 完全一致、`failed_features=[lower_tip]` 不变、表达式相同、轨迹等价；在第二次请求前即可判 `stalled_equivalent` 终止。
- **纯计划文本方案：拦不住**。参数域字符串不同会被记 `modified`，与本轮 `step_diff` 结果一致。
- 拦截面收益（按本轮实测，已查证用量）：省下第二次请求 16172 输入 / 450 输出 tokens、0.001026288 USD 与约 8 秒墙钟；不影响首轮诊断与最终 `failed` 结论，也不改变候选保存判定（本就未持久化）。
- 残余：若模型改了表达式但轨迹仍代数等价，需几何采样比对才能识别；计划层方案对此仍有漏检（待验证）。

## 5. 同类"看似变化、实际等价"漏洞清单

危害等级：**高**（可白花一次以上请求/绕过验收）／**中**（特定渠道可绕过或掩盖）／**低**（现有保护基本在位）。B 覆盖列：几何判据可否在执行几何层拦截。

| # | 漏洞情形 | 证据位置（文件·行号） | 危害 | B 几何判据可否覆盖 | 备注 |
|---|---|---|---|---|---|
| 1 | 周期参数曲线只改参数域，轨迹不变（A9 实发） | `recovery.py:49-51, 80-90`；记录 :721-724 vs :627-630 | **高** | 可：几何指纹/采样点云等价比对可覆盖；计划层不可 | 本轮实测漏网 |
| 2 | 代数等价表达式 / 变量重命名，轨迹不变 | `recovery.py:88` 逐步字典比较；`cad_plan_component_repair.py:36-43` 整步替换 | 中高 | 可（几何层）；计划符号等价不可知 | 推断，待受控夹具验证 |
| 3 | 仅放宽失败断言容差 / 替换失败断言 | `cad_plan_component_repair.py:44-57` 允许 `failed_assertion` 替换；断言集合由合并器保留其余项 | 中 | 部分：几何验收仍按新断言重算；容差是否宽于用户事实需来源侧比对 | **待验证**：是否存在断言容差不得宽于来源事实的既有校验（`cad_source_acceptance.py:35-61` 独立测 bounds） |
| 4 | 仅改 `semantic` 标签/文本，几何不动 | 合并器恢复 `step_id/output_ref/semantic/layer_id`（`cad_plan_component_repair.py:40-42`）；身份修复只取 `object_id`（:27-33） | 低中 | 否：标签不在几何内；需 A 侧身份/语义比对 | 标签变化不改变几何指纹 |
| 5 | 段序重排但轨迹不变 | 局部范围校验顺序 `cad_local_repair.py:181`；部件合并保留原索引 `cad_plan_component_repair.py:36-43` | 低 | 可（点云轨迹等价）；顺序本身已被两条渠道保护 | 多步轨迹等价未在进展门比对 |
| 6 | 放宽 `max_sampling_error` / 加密或变疏采样字段 | 部件渠道整步替换可带入该字段（`cad_plan_component_repair.py:39,43`） | 中 | 验收侧采样残差界可拦过粗（B1.2 `spline_residual_bound`）；进展门不直接覆盖 | 字段在计划内，几何层间接反映 |
| 7 | 只提置信度、计划空转 | 既有 `confidence_only_repair`（`recovery.py:54-60`；拦截 `agent_service.py:6521-6527`） | 中低 | 不适用（非几何问题） | 现有守卫仅限 `low_confidence` + 复用被拒计划 + 转 ready；其他错误码下的空转未覆盖 |
| 8 | 单位/比例缩放使包围盒达标、内部比例失真 | 单位被合并器锁定 `cad_plan_component_repair.py:14-15`；内部比例由 H2/H4 验收覆盖 | 中 | 几何测量可发现比例失真；进展门不覆盖 | 单位越界直接报错 |

## 6. 最小修改建议（**待批准**，本轮未实施；三件套）

> 以下仅为方案与证据，未改任何生产文件；实现归属恢复策略/服务层 owner，C 线不代改 A/B 文件。

### 建议 1：恢复策略层增加 `stalled_equivalent` 进展分类（首选）

- **最小改动**：`cad_generation_recovery.py::bounded_repair_available` 在两轮以上比对时，除既有签名/字典比较外，读取尝试记录中的 `measured_features`（失败特征集合）与可选 `geometry_hash`；双窄条件命中即返回 `False`，并在 `recovery_record` 追加 `progress` 取值。
- **回归范围**：`cad_generation_recovery` 单测；C1.2 循环 Mock（两轮几何实质改变的既有夹具必须仍通过）；既有 `confidence_only_repair`、`model_plan_invalid`、`constraint_conflict` 用例；A9 同形夹具（特征不变 + 域平移）应被拦在第二次请求前。
- **回滚点**：移除新增进展分支与 `progress` 字段，恢复函数原签名与 `before!=after` 比较；`max_repairs`、预算、保存条件一行不动。

### 建议 2：失败路径附带轻量几何快照（解除输入退化）

- **最小改动**：`cad_construction_interpreter.py:1035-1043` 的 invalid 返回中，附带已执行 `result` 的几何指纹/采样摘要（不持久化候选、不改错误码与消息），供建议 1 做几何等价比对。
- **回归范围**：解释器失败路径既有测试；不得改变 `construction_error` 结构、候选保存条件与 H2/H3/H4 语义。
- **回滚点**：移除附加字段，返回形状其余不变。

### 建议 3：服务循环层落地 `no_progress` 拦截（与建议 1 二选一或配套）

- **最小改动**：仿 `agent_service.py:6521-6527`，在第二次调用前对 `stalled_equivalent` 转 `invalid`，错误码建议 `no_progress`，不保存候选，`next_action` 保留人工重试。
- **回归范围**：`_formal_cad_construction` 循环级 Mock；确认放行三类正例（特征转好、几何越容差移动、结构重编译）不被误杀。
- **回滚点**：删除该分支与错误码映射，回到既有循环语义。

## 7. 结论与明确意见

1. **第二轮被判有效进展的根因**：第二次放行发生在 `bounded_repair_available` 的单尝试早返分支（`recovery.py:35-36`），无前后对照；唯一的进展度量是计划字典/字段不等（`recovery.py:49-51, 77-90`），参数域平移被记为 `modified`；几何无进展识别缺位。
2. **反馈到达情况**：`lower_tip=false`、失败特征、refs、前次计划均进入第二次请求的组装路径；但失败特征目标几何量、前后差异摘要未提供；提示词正文未落盘，模型是否利用反馈属待验证。
3. **是否需要先补进展检测再做下一案例：需要（建议先补）**。
   - 理由：现有循环会对"轨迹等价、仅计划文本外形变化"的空转照样发修复请求；下一案例若出现同形空转，将继续白花请求与预算，且失败账本只能记 `model_plan_invalid`，无法区分"真在修"与"原地打转"。
   - 最小前提：先上建议 1 的特征向量级 `stalled_equivalent` 判定（不依赖几何快照即可覆盖 A9 同形）；几何级等价比对随建议 2 补强。
   - 不阻塞事项：隔离库重定向（D 报告 §6）、A/B 侧规划与几何能力改进可并行；进展检测不提高 `max_repairs`、不降验收，不改变本轮已冻结指标口径。
4. **本轮未验证/残余**：提示词正文与模型实际采纳情况；断言容差是否可被放宽绕过（#3）；代数等价表达式漏检（#2）；样本仅 A9 一例，结论不外推到其他几何类别。
