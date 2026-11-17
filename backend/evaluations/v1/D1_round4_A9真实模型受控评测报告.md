# D1 第四轮 · A9 爱心真实模型受控评测报告（零费用预检 + 单案例实跑）

> 基线组合树 `f89bf41facfb7032cbb9647250cff6bbdcc6bbb7`（A1.1 `ea8323a` + B1.2 `d7e00bd` + C1.2 `49d48de`）。
> 本轮主控仅批准 **A9 爱心** 一个真实案例；A9 完成后即停止，未启动 S1、多对象组合、Arc 曲线或复杂自由曲线案例。
> 评测期 `backend/app` 零改动，未合并、未推送、未 amend；模型调用未被 Mock；Key 不入报告、账本与原始日志。

## 0. 首段结论（主控必答）

**A9 确实完成了真实模型调用**：隔离评测进程内共发出 **2 次** `deepseek-flash` 结构化请求（首轮计划 1 次 + 有界修复轮 1 次），`real_model_calls = 2`。真实 usage：输入 **31554** tokens（缓存命中 15872、未命中 15682），输出 **804** tokens；按 peak 价结算实际费用 **0.005764632 USD**。案例九态状态为 **`failed`**（后端结构契约校验拒绝：心形下方尖点 `lower_tip` 两次均未检出）；**未持久化任何候选方案**。**未命中任何硬上限**：费用 0.576%、输入 10.52%、输出 1.34%、请求 6.67%、案例 20%，均在限额内。

- 两次响应返回的 `model` 字段均为 `deepseek-flash`，与守卫要求一致，未触发"模型不匹配即停"。
- 本轮之前（第一至三轮）真实调用为 0；本轮账本从 0 起算。

## 1. 放行前六项预检留证

### 1.1 基线与工作树
- 组合树 HEAD = `f89bf41facfb7032cbb9647250cff6bbdcc6bbb7`；`git status --short` 为空；`git diff --stat HEAD -- backend/app` 为空（生产代码相对基线零改动）。
- D 线工作树 HEAD `4ad73eb038bbdf5a8ded8be5bc3a2feb0a2dcd70`；本轮新增/修改均落在 `backend/evaluations/v1/` 评测范围。

### 1.2 价格口径（主控裁决，唯一有效）
- 模型名 `deepseek-flash`（DeepSeek-V4.1-Flash-1017）；官方价目页 `https://api-docs.deepseek.com/quick_start/pricing`，变更日志 `https://api-docs.deepseek.com/updates/`；复核时间 2026-11-17 16:16:43 +08:00 / 08:16:43Z。
- peak 价（USD / 1M tokens）：缓存未命中输入 0.30、缓存命中输入 0.006、输出 1.20；off-peak 输入未命中 0.15 / 命中 0.003 / 输出 0.60。
- peak 时段：UTC 周一至周五 01:00–04:00、06:00–10:00（中国法定节假日除外）；跨边界按 peak 计。本轮两次请求发生在 08:36 UTC（周二），属 **peak**，预留与结算均按 peak 最坏值。
- Key 可用性：复用主控实测结论（Key 有效可达），D 线未重复 `/models` 探测。
- 旧假定 0.14 / 0.28 口径已作废，不用于结算。

### 1.3 模型覆盖与 payload 取证（零费用，未触网）
取证探针 `probes/d1_round4_a9_forensic_probe.py`，快照 `probes/d1_round4_forensic_snapshot.json`。隔离进程在导入应用前设置三枚覆盖变量：

| 变量 | 值 |
|---|---|
| `DEEPSEEK_CAD_PLANNING_MODEL` | `deepseek-flash` |
| `DEEPSEEK_BASE_MODEL` | `deepseek-flash` |
| `DEEPSEEK_ADVANCED_MODEL` | `deepseek-flash` |

零费用取证（传输层被进程内桩替换，未打开任何 socket）实际构造出的 payload：

- `model = deepseek-flash` ✅
- `thinking = {"type": "disabled"}` ✅（注入条件见 `agent_service.py:2082-2083`，仅当 `payload['model']=='deepseek-flash'` 注入）
- `max_tokens = 8192` ✅（`_construction_review_max_tokens` 缺省 8192，`agent_service.py:2616-2621`，夹取 1200–32768）
- `response_format = {"type": "json_object"}` ✅
- 实例字段：`base_model / advanced_model / cad_planning_model` 均为 `deepseek-flash`；遗留 `model` 字段保留 `deepseek-chat`，但 CAD 规划路径以 `cad_planning_model` 覆盖（`agent_service.py:6157`），不参与本次结构化请求。

### 1.4 非思考模式
- `thinking.type=disabled` 已进入实际 payload（1.3 节序列化取证），不是仅存在于常量。
- 守卫：首次真实响应必须核对返回 `model == deepseek-flash`；两次响应均匹配，未停止。

### 1.5 策略未改（行号证据，均在基线生产代码上复核）
- 有界修复上限 `max_repairs=2`：`agent_service.py:6480`、`6590`；`cad_generation_recovery.py:25`（`bounded_repair_available`）、`:33`（`repairs>=max_repairs` 即停）。
- 自交标准 `allow_self_intersection: bool = False`：`cad_construction.py:285`；强制拦截 `cad_construction.py:1202`（有接触或 unresolved 且未允许自交即拦截）。
- H2 连续性：`cad_construction.py:273`（`intent` 与连续性约束校验，C0/G1/C1）。
- 来源授权（H3）：`source_requirement_refs` 字段 `cad_construction.py:266`（max_length=20）；部件修复模块显式声明"H3 是来源引用唯一权威" `cad_plan_component_repair.py:87-88`；解释器来源索引 `cad_construction_interpreter.py:590`、`:755`。
- 候选保存条件：`agent_service.py:6762` `commit_construction_interpretation(...)`；保存失败落 `candidate_persistence_failed`（`6778-6792`）；独立验收通过要求 `acceptance.status=="passed"` 且 `review_required is not True`（`6800-6806`）。
- 本轮未为跑通放宽任何上述语义、未降 `max_tokens`、未改验收阈值。

### 1.6 预留与结算规则
- 单请求 peak 最坏预留 = 输入估算 10000 × 0.30/M + 实际 `max_tokens`（缺省 8192；局部修复上下文夹到 4096）× 1.20/M = **0.0128304 USD**。
- A9 案例级最坏信封：首轮 + 2 次有界重试 + 至多 2 轮修复 = 5 请求，信封费用 0.064152 USD、输入 50000、输出 40960，均在硬上限内（快照 `A9_case_record.json` → `precheck.budget_envelope`）。
- 响应后按真实 usage 结算并释放未用预留；usage 缺失、计费不明、超时或状态不明、预留破限即停，不重试。本轮两次 usage 字段完整（`prompt_tokens / completion_tokens / total_tokens` 及缓存拆分），无 `missing_usage_calls`。

## 2. 代码真实性核验（运行代码，非测试/报告）

在 `f89bf41` 生产代码函数体中逐项核对，结论：**未发现任何能力只存在于测试、报告或部分模块中**。

| 线 | 能力 | 生产代码证据（文件 · 函数/位置 · 行号） |
|---|---|---|
| A1.1 | 拒绝计划回挂 `rejected_plan` / `previous_plan` | `agent_service.py:6495-6499`（`rejected_plan = interpretation.get("plan") or interpretation.get("rejected_plan")`，`previous_plan` 序列化回挂）；`6520`、`6527` 入列失败尝试 |
| A1.1 | 受影响输出引用 `affected_output_refs` | `agent_service.py:6225`（从 `construction_error.details` 取受影响引用）；`6483-6484`（`failed_refs` / `plan_refs` 比对）；`6511`（修复上下文携带受影响引用） |
| B1.2 | Arc/Spline 曲线级求交与片级包络预剪 | `cad_topology_safety.py`：`_arc_pieces:333`、`_spline_pieces:351`、`_bbox_overlap:385`、`_leaf_sample_points:421`；片数上限 `ARC_MAX_PIECES=2048:60`、`SPLINE_MAX_PIECES=512:62` |
| B1.2 | 保守误差界（矢高上界与片数反解） | `arc_chord_height:260`（矢高定义）、`arc_chord_count_for_tolerance:283`（按矢高界反解最少等弦片数）、`spline_residual_bound:299`（样条残差界） |
| B1.2 | 切线角度判别与未决分类 | `_chord_angle_deg:406`；`CONTACT_TANGENT:75`；未决 fail-closed `unresolved:119` 与注释 `36-42`（截断子树不得判定"必然清晰"） |
| C1.2 | 真实生产循环接线（有界循环 / 路由 / 部件合并 / 候选保存） | 有界循环 `agent_service.py:6479-6480`；修复路由三元组 `6508-6511`；部件合并 `6240-6241`（`merge_component_repair`）；候选保存 `6762` |

## 3. A9 案例完整记录

### 3.1 输入与路由
| 字段 | 值 |
|---|---|
| case_id | A9 |
| 原始输入 | 生成一个左右对称、平滑闭合的爱心，中心在(2,3)，宽4米高4米 |
| `input_sha256` | `af12df04393e1da42acd9eae6e590f81fa8c66a4720c546c9d292fef89707d5b`（与注册表一致，冻结输入未改动） |
| `expected_route` | `construction_scope` |
| `actual_route` | `drawing_design / create`，`decision_source=deterministic_generic_cad_creation`，`review_required=false`，`clarification_required=false` |
| `provider_attempted` | true |
| model（规划覆盖） | `deepseek-flash` |
| 耗时 | 11.347 s |

### 3.2 请求与 usage 结算（peak）
| # | request_id | 响应 model | finish_reason | 输入 | 缓存命中 | 缓存未命中 | 输出 | 费用 USD |
|---|---|---|---|---|---|---|---|---|
| 1 | `1df31f91-b4bf-4331-b3e8-c24e2cbac675` | deepseek-flash | stop | 15382 | 1024 | 14358 | 354 | 0.004738344 |
| 2 | `6bda0ebb-7a0b-4f01-818c-559a060bb1b0` | deepseek-flash | stop | 16172 | 14848 | 1324 | 450 | 0.001026288 |
| 合计 | — | — | — | **31554** | **15872** | **15682** | **804** | **0.005764632** |

- 结算公式：未命中输入 × 0.30/M + 命中输入 × 0.006/M + 输出 × 1.20/M。
- 两次 `peak_band=true`；`missing_usage_calls=0`。

### 3.3 首轮计划与首轮验收
- 首轮计划（尝试 1，`plan_sha256=7295796f…d391`）：单步 `add_parametric_curve`，输出引用 `heart.outline`；
  - `x_expression = 2+2*sin(t)`，`y_expression = 3+2*cos(t)+2*sqrt(abs(sin(t)))*cos(t)`；`t_start=0`，`t_end=2*pi`，`closed=true`；
  - 断言：闭合 `heart.closed`；尺寸 `bounds_size` 宽 4.0 / 高 4.0（tolerance 0.001）；
  - 自由轮廓布局：中心 `(2.0, 3.0)`，宽 4.0、高 4.0。
- 首轮验收：**未通过**。后端结构契约检查 `heart_bilateral_lobes_notch_and_lower_tip` 实测特征：`center_notch=true`、`left_upper_lobe=true`、`right_upper_lobe=true`、`lower_tip=false`；失败特征 `lower_tip`。错误码 `structure_requirement_failed`，类别 `model_plan_invalid`，置信度 0.92。

### 3.4 修复轮与最终计划
- 修复次数：1（`recovery.repair_count=1`，上限 `max_repairs=2`）。
- 尝试 2（`plan_sha256=ecefd233…ac6cba`）：表达式与尝试 1 **完全相同**，仅参数区间改为 `t_start=-pi`、`t_end=pi`；
  - 后端复测特征不变：`lower_tip=false`，仍失败；`step_diff.comparison=exact_plan_steps_not_geometric_equivalence`，修改引用 `heart.outline`。
- 最终计划：无通过候选；`variants=[]`，`variant_id=not_available`，`geometry_count=0`。
- 最终返回：`ok=false`，`error_code=candidate_generation_failed`，`next_action=retry_candidate_generation`；消息"本次 CAD 构造失败：爱心缺少双侧上凸、中央凹口或下方尖点。需求已保留，可重试生成。"

### 3.5 H2 / H3 / H4 与几何结论
| 层 | 结论 | 证据 |
|---|---|---|
| H2 连续性 | `not_checked`（无已提交几何可测 C0/C1） | 计划步未给出可测连续性断言；候选未持久化，解释器连续性度量未执行 |
| H3 来源授权 | `not_checked`（计划无 `source_requirement_refs` 可校验） | 两轮计划 `constraints=[]`，步骤内无来源引用字段；H3 权威规则在位（1.5 节）但本轮无引用需校验 |
| H4 语义特征 | **未通过**：`lower_tip` 缺失 | 结构契约/语义验收实测 4 特征，下方中心尖点未检出（`cad_structure_contract.py:335-357`，`cad_semantic_acceptance.py:211-227`） |
| 自相交 | 未检出自相交接触 | 失败原因是特征缺失，不是段对相交；记录中无相交段对/参数/接触点 |
| 连续性/闭合 | 计划声明 `closed=true`；无已提交几何独立复核 | — |

### 3.6 候选最终状态与独立复核
- 隔离库回读：项目 `e089c984-…`，状态 `ready_for_design`，`variants=[]`；需求账本保留原文与宽/高事实，覆盖 `partial`。
- 因无持久化几何，**CGQ 不可计算**（`not_available_no_persisted_geometry`）；无法对落库候选做独立几何复核。

### 3.7 指标分桶（三类分开计数，不合并通过率）
| 桶 | 本轮结果 | 说明 |
|---|---|---|
| Detection（检出/检测） | 1 次检测执行，检出 `lower_tip` 缺失 | 后端在模型计划生成的几何上实测 4 个爱心特征；Detection 单列，不计生成成功 |
| Repair 成功（本轮为真实链路，非 Mock） | **0/1** | 唯一修复轮未产出通过候选 |
| 真实 Generation 成功 | **0/1** | 无候选持久化；`review_required` / `unresolved_topology` 本轮均未出现 |
| FSR（首轮计划通过率） | **0/1** | 首轮即被结构契约拒绝 |
| Rejection（后端拒绝） | 1 次 | `structure_requirement_failed` |
| CGQ | `not_available` | 无持久化几何 |

## 4. 六条重点验证逐条证据

1. **首轮计划是否真实表达闭合 / 对称 / 尺寸 / 连接意图**
   - 闭合：步骤 `closed=true`，断言 `heart.closed`（闭合）✅。
   - 尺寸：`bounds_size` 宽 4.0 / 高 4.0，布局中心 `(2.0,3.0)` ✅。
   - 对称：**未编码为约束**。计划中无对称断言、无对称轴/对称约束字段；"左右对称"只出现在语义标签，未进入可校验约束 ⚠️。
   - 连接：单条闭合轮廓，无内部连接点；`junction_constraints` 未生成（见下条）。

2. **`junction_constraints` 是否生成并跨轮保留**
   - 两轮计划均**未生成** `junction_constraints`；步骤内无该字段，`source_requirement_refs` 为空。
   - 因首轮即无连接约束，不存在"跨轮保留/丢失"问题；单闭合轮廓场景后端未要求内部连接约束。

3. **几何检测是否检出真实自相交**
   - 未检出自相交。本轮失败来自语义特征（`lower_tip`）缺失；记录中无相交段对、无相交参数、无接触点与距离。安全报告未标 `unresolved_topology`。

4. **自动修复是否真正改了几何（而非只改断言）**
   - **未实质改几何**。尝试 2 与尝试 1 的 `x/y` 表达式逐字相同，仅 `t_start/t_end` 区间由 `0→2pi` 改为 `-pi→pi`；修复指令本身注明"仅改变曲线参数区间不会改变完整周期的几何形态"。复测 `lower_tip` 仍为 `false`。断言集合未变；修复前后坐标/控制点无实质差异。

5. **H2 / H3 / H4 是否全过**
   - 未全过：H4 语义特征未过（`lower_tip` 缺失）；H2、H3 在无提交候选状态下为 `not_checked`，不计通过也不计失败。详见 3.5 节。

6. **候选可否被隔离库独立复核**
   - 不可复核：候选未持久化，隔离项目 `variants=[]`；回读仅见需求账本与项目元数据，无几何/断言记录可独立复测。

## 5. 与 D0 / Mock 结论的区别（Mock 给不出的结论）

- D0 及组合树 184 条通过全部来自确定性规则与 Mock 服务测试；本轮首次在**真实提示词、真实修复策略、真实候选保存链路**上观察模型行为。
- Mock 给不出、本轮首次暴露的事实：
  1. 真实模型用参数方程表达心形时，**未能生成下方尖点**，且修复轮只调整参数周期区间、未改变几何表达式；
  2. 后端结构契约对真实模型计划的**特征级拒绝**真实生效（双峰/凹口/尖点逐项实测）；
  3. 缓存命中在第二轮显著升高（1024 → 14848 命中），真实计费与 Mock 口径不同；
  4. 对称意图未被模型转成可校验约束，这一约束缺口在 Mock 夹具中不显现。
- 反过来说，本轮单案例失败**不能**外推为真实模型整体不可用；样本仅 1，且只覆盖心形自由轮廓一类。

## 6. 隔离与脱敏

- 隔离进程独立 owner `d1-round4-a9`；计划库、每用户配置库指向系统临时目录下的隔离子目录；项目库路径环境变量已设置（项目为进程内持有，未落盘共享文件）。
- 原始响应 `A9_raw_responses.jsonl` 仅记录 `id / model / finish_reason / usage`；写入前即脱敏，不含 `Authorization`、Key 或 Key 片段。
- **隔离缺口（如实记录）**：`agent_audit.jsonl`（`XLINE_AGENT_AUDIT_STORE` 可重定向，本轮未设置）与历史库 `xline.db`（`XLINE_DATABASE_PATH` 可重定向，本轮未设置）写入了共享临时默认目录；未写真实用户项目数据库，未持久化候选。下一轮跑案例前应补齐这两枚重定向。

## 7. 剩余风险与下一轮最优先问题

**剩余风险**
- 样本量：仅 A9 一个真实案例；注册表端到端合格案例仅 A9、S1，无其他合格替代。
- 模型表达：参数方程心形下尖点生成失败；对称约束未结构化。
- 修复有效性：有界修复未能推动几何实质改变；进度判定允许了"参数区间变化"但几何等价。
- 隔离：审计与历史库未重定向（见第 6 节）。
- 异常路径：本轮未触发超时/网络中断/usage 缺失，这些停止条件未被实战验证。

**下一轮最优先问题（交 A/B/C 领域分析，D 不代替判定）**
1. 规划（A）：心形下尖点应通过何种参数表达式/控制点序列表达？提示词是否需要显式约束对称与尖点？
2. 几何（B）：现有 Arc/Spline 安全界与特征检测对参数方程轮廓的覆盖是否充分？`lower_tip` 阈值归一化是否合理？
3. 生产链路（C）：修复轮应强制改变几何（坐标/控制点/表达式）而非参数区间；修复前后几何差异应入证据账本。

## 8. 是否建议继续真实模型受控评测

- 本轮已在受控条件下完成首案例真实调用，守卫、脱敏、账本、隔离基本到位。
- **建议**：先补齐审计/历史库重定向，由 A/B/C 对 A9 失败根因做领域分析后，再由主控决定是否放行 S1 及后续案例；**不建议**在当前隔离缺口下批量发请求。本轮不扩大案例范围。

## 9. 交付清单与复跑入口

| 文件 | 说明 |
|---|---|
| `D1_round4_budget_ledger.json` | 逐请求可审计账本：请求 / usage / 缓存拆分 / 费用 / 限额消耗比例 |
| `round4/A9_case_record.json` | A9 预检、案例记录、脱敏生产返回快照 |
| `round4/A9_raw_responses.jsonl` | 两次真实请求脱敏原始响应 |
| `round4/README.md` | 隔离目录说明与脱敏口径 |
| `probes/d1_round4_a9_forensic_probe.py` | 零费用 payload 取证探针（不触网） |
| `probes/d1_round4_forensic_snapshot.json` | 取证快照（model / thinking / max_tokens 断言全过） |
| `probes/d1_round4_a9_runner.py` | A9 隔离生产运行器（含预算信封守卫、脱敏回写、独立复核回读） |

复跑命令（一次性；账本已结算 A9，运行器拒绝重复计费）：

```
python probes/d1_round4_a9_runner.py --backend <组合树后端目录> --registry case_registry.json --ledger D1_round4_budget_ledger.json --out-dir round4
```

本轮 `real_model_calls = 2`；无重试、无并发、无 Mock。
