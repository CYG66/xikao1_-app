# 第一批接线修复统一报告（Wiring-01）

## 0. 结论

在固定父提交 `aa628fc76ac57368c9afc637971f6deb32be9f6d` 上，已完成第一批最小接线；独立终验固定检出 `f2a6da690e69d95bad30b931eaa2a0b2d74bd6e4` 后发现的“逗号追加未知条款仍被接受”阻断，已用提交 `2fb8dc75fb338a8e1c3d6507664b1bcaa7d7ed54` 追加最小修复；随后独立复核又发现“重复圆心被清除但未验证”，已用提交 `fbe7de5726f0d5e838134fb7d308663ef52b123a` 将残留判断改为复用解析器实际消费的匹配位置。终验已认可的 A、C1、C2、三圆正例和计数口径均保留，不回滚、不重新立项。第一批最小接线：

- **A**：来源验收消费执行器的对象引用，并把已有逐件测量、二分图匹配和对象归属输出为可复用证据；
- **C1**：已经确定的来源数量/身份失败，进入现有有界修复循环，不再停留在 `ready`；
- **C2**：后续数量、身份和汇总闸消费已有的完整来源证据，不再把同一需求重复当作未知。

第一批四条结束条件均已实测；独立复核追加的“逗号未知条款”和“重复圆心”两项完整性反例也已关闭：

1. 正确的具名尺寸被真实测量；错误尺寸继续被拒绝。
2. 已确定的缺件触发现有修复循环，`max_repairs=2` 未改变。
3. 三圆完整清单正例沿真实服务、执行、验收、隔离存储链成为 **1 条正式 accepted 候选**。
4. 同一正例加入未知条款（分号与逗号两种连接方式）、重复冲突圆心、错误尺寸、缺件、错误绑定后，**accepted 均为 0**。

**正式集成仍维持 NO-GO。** 本批只完成接线，不代表真实生成通过率已有新评测结论，也不代表 App 画布/HTTP 渲染已验收。

---

## 1. 版本与提交

| 项目 | 值 |
|---|---|
| 固定父提交 | `aa628fc76ac57368c9afc637971f6deb32be9f6d` |
| 修复分支 | `fix/wiring-01` |
| 远端评审分支 | `doubao/review-wiring-01-20261120` |
| A 提交 | `f05c5b860d970e62d40d59fdbc166986cffa73dd` |
| C1 提交 | `fa65bb37e883b2fb3e592ccec82f9ee2586f5936` |
| C2 提交 | `730a7c333abfebb4f1ef04f003fab0b0c51a0510` |
| 逗号阻断修复提交 | `2fb8dc75fb338a8e1c3d6507664b1bcaa7d7ed54` |
| 重复圆心收尾提交 | `fbe7de5726f0d5e838134fb7d308663ef52b123a` |
| 文档提交 | 上述提交之后的报告与证据提交，仅文档，不改生产代码 |
| 生产代码最后提交 | `fbe7de5726f0d5e838134fb7d308663ef52b123a` |
| 是否推送 | **是**，正常 fast-forward 到独立评审分支 |
| 是否合并 main | **否** |
| 是否 amend / force push | **否** |

实际父链（Git 实测）：

```text
aa628fc76ac57368c9afc637971f6deb32be9f6d
  └─ f05c5b860d970e62d40d59fdbc166986cffa73dd  A
      └─ fa65bb37e883b2fb3e592ccec82f9ee2586f5936  C1
          └─ 730a7c333abfebb4f1ef04f003fab0b0c51a0510  C2
              └─ 0812b6c2f14e8b47a8495f1c8dcc266da5165701  文档
                  └─ f2a6da690e69d95bad30b931eaa2a0b2d74bd6e4  文档修正
                      └─ 2fb8dc75fb338a8e1c3d6507664b1bcaa7d7ed54  逗号阻断最小修复
                          └─ fbe7de5726f0d5e838134fb7d308663ef52b123a  重复圆心收尾
```

`2fb8dc7` 和 `fbe7de5` 都只改 `cad_source_acceptance.py` 及现有测试文件，不新增生产入口、不改 `cad_construction_interpreter.py`。`fbe7de5` 之后的文档提交只更新报告与证据，最终分支 HEAD 以远端评审分支 tip 为准。

评审入口：

- 分支树：https://github.com/CYG66/xikao1_-app/tree/doubao/review-wiring-01-20261120
- 相对父提交的评审范围：https://github.com/CYG66/xikao1_-app/compare/aa628fc76ac57368c9afc637971f6deb32be9f6d...doubao/review-wiring-01-20261120

代码与测试共 6 个文件，相对父提交合计 **+588/−18**：

- `backend/app/cad_source_acceptance.py`（+134/−10，累计）
- `backend/app/cad_construction_interpreter.py`（+185/−8）
- `backend/tests/test_cad_final_source_contract.py`（+28）
- `backend/tests/test_cad_source_acceptance.py`（+42）
- `backend/tests/test_wiring_01_repair_gate.py`（+78）
- `backend/tests/test_wiring_01_evidence_consumption.py`（+121）

生产代码只有两个文件，合计 **+319/−18**。重复圆心收尾本身为 3 文件 **+55/−26**，其中生产代码只动 `cad_source_acceptance.py`（**+42/−25**），消费侧 `cad_construction_interpreter.py` 保持零补丁。

---

## 2. A：对象引用与完整证据

### 2.1 修复内容

新增单一引用读取入口 `_object_geometry_refs(obj)`：

- 优先读取执行器逻辑对象的 `geometry_refs`；
- 兼容读取旧的 `geometry_ids`；
- 两者同时存在但内容不一致时返回 `None`；
- 空、非列表、布尔、浮点、非整数、重复引用均返回 `None`；
- 调用方在拿不到可信引用时继续输出 `unknown`，保留“缺失/悬空/歧义引用不能通过”的保护。

`verify_final_source_contract()` 与 `verify_scoped_primitives()` 均改为消费该入口。没有新增尺寸验收器，也没有绕过原有 `StructureContractError`。

`verify_scoped_primitives()` 新增 `scope_evidence`（`cad.source-scope-evidence.v1`），逐条携带：

- `requirement_id`、`subject`、`category`、`quantity`
- `geometry_ids`、`object_ids`、`assembly_ids`
- `evidence`、`measurement`

只有同时满足以下条件才输出 `state=complete`、`status=passed`、`coverage=complete`：

- 来源声明完整部件清单，且清单内所有条款都已完整解析、没有未解释残留；
- 没有清单之外的可见图元；
- 每个来源条目有唯一逻辑对象和整体归属；
- 关系验收没有待复核项；
- 所有逐件检查均为 `passed`。

否则保留原 `partial / explicit_scoped_primitives_only` 并给出原因。未把 `partial` 批量改为 `passed`。

另外增加“对象标签—来源主体”矛盾检测：模型标签不作正向身份证明；若一个对象被标注为另一个已声明主体、却拥有当前主体的测量几何，则抛出 `object_binding_conflict`。这条检查用于让错误绑定负例受控，不参与正常三圆判定。

### 2.2 实测证据

原文：

> 画一个圆和一个矩形，圆半径1米，矩形宽2米，矩形高2米

| 输入 | 结果 |
|---|---|
| 执行器原始 `geometry_refs` | **3 项真实测量，0 项 unknown** |
| 圆半径改为 2 米 | 现有测量器抛出 `StructureContractError`，失败 `geometry_ids=[1]` |
| 引用冲突、重复、浮点 `1.5`、字符串 `"1.0"` | 保持 `unknown`，不测量错误几何 |

三圆完整清单：

- `scope_evidence.state=complete`
- `count_baseline.expected_object_count=3`，`grouping=object`
- 三个条目分别绑定 `r0/r1/r2`
- `object_identity_acceptance.status=passed`

### 2.3 条款内残留：已捕获文本不等于已完整验证

独立终验复现的阻断是：同一三圆清单末尾用分号追加“嘴巴为一条微笑曲线”会被拒绝；仅把分隔符改成逗号，实际图元仍只有三个圆，却在 `f2a6da6` 得到 `complete/passed/accepted=true`。

根因在来源验收的完整覆盖判定：

1. 解析器把整条条款正文保存进 `evidence`；
2. 实际只测量圆心、半径、尺寸、端点等支持字段；
3. 完整清单检查只看“条款字符串是否已进入 evidence 集合”；
4. 因而“嘴巴”被保存在右眼的 evidence 文本里，却没有被解析、测量或登记为未决要求。

修复仅动 `cad_source_acceptance.py`：

- 新增 `_unsupported_clause_residue(kind, body)`，按当前解析器真正消费的字段逐个移除 span；
- 坐标内部逗号随整个坐标字段一起移除，不会把逗号当条款分隔符；
- 字段移除后仍剩下有意义字符时，写入该条目的 `unresolved_evidence`，原 `evidence` 全文保持不变；
- 完整清单的 evidence 集合只纳入“无未解释残留”的条款；
- `scope_evidence` 仍保留逐条 `unresolved_evidence` 供审计，`complete_scope` 显式要求没有残留。

修复后服务级复跑：

| 同一三圆计划的输入 | `f2a6da6` | `2fb8dc7` |
|---|---:|---:|
| 原三圆完整清单 | 1，正确 | **1，正确** |
| 末尾 `；嘴巴为一条微笑曲线` | 0，正确 | **0，正确** |
| 末尾 `，嘴巴为一条微笑曲线` | **1，错误接受** | **0，正确拒绝** |

逗号变体复跑的关键值：

- `source_acceptance.status=partial`
- `inventory_scope=partial`
- `scope_evidence.state=partial`
- `scope_evidence.reasons` 同时包含“来源完整清单未声明或包含未解析条款”和“条款包含未解释、未测量的片段”
- `unresolved_evidence=["嘴巴为一条微笑曲线"]`
- 原 `evidence` 仍是完整右眼条款，未丢弃原文
- `acceptance_summary.status=review_required`，`requirement_coverage=unknown`
- `accepted_count=0`

没有硬编码“嘴巴”“微笑”或 `case_id`，没有新增微笑曲线生成器、验收器或通用 NLP，也没有把全部逗号当分隔符。C 线核对现有消费侧后确认无需改动：`scope_evidence` 的 `partial` 状态已被汇总与候选门禁消费，`cad_construction_interpreter.py` 在本补丁中保持零补丁。

### 2.4 重复字段：解析采用一份，残留就不能扣除两份

独立复核在 `2fb8dc7` 上继续追加同一三圆计划的原文：

```text
，圆心(9,9)
```

右眼条款于是同时含有两个圆心：

```text
右眼：圆，圆心(0.35,0.35)，半径0.09米，坐标单位米，圆心(9,9)
```

修复前，解析器采用第一个圆心 `(0.35,0.35)` 并据此测量；残留检查使用 `re.sub` 删除了该字段的**全部**匹配，第二个 `圆心(9,9)` 也被从残留中清除。结果是原文中仍有一个未处理要求，系统却输出 `complete/passed/accepted=true`。独立复核确认同一反例在 `f2a6da6` 上也为 accepted=1，属于上一轮完整性修复未覆盖到的同一机制，不是本次新增回归。

`fbe7de5` 的收尾只做一件事：让解析与残留共用同一份消费证据。

- 新增 `_clause_field_matches(kind, body)`，按解析器实际会消费的字段各取第一个 `re.search` 匹配，返回同一组 match 对象及其 span；
- `extract_scoped_primitives()` 从这组 match 对象取值，不再另起一套字段正则；
- `_unsupported_clause_residue()` 只删除这组已消费 span，不再对字段做全量 `re.sub`；
- 剩余文本只裁掉边界空白和分隔符，保留内部逗号与括号，因此第二个圆心会原样进入 `unresolved_evidence`；
- 未增加冲突消解能力；重复或冲突字段只保留为未决，不声称已处理。

服务级复跑：

| 同一三圆计划的输入 | 结果 |
|---|---:|
| 原三圆完整清单 | **accepted=1** |
| 末尾 `；嘴巴为一条微笑曲线` | **accepted=0** |
| 末尾 `，嘴巴为一条微笑曲线` | **accepted=0** |
| 末尾 `，圆心(9,9)` | **accepted=0** |

重复圆心变体的关键值：

- `source_acceptance.status=partial`
- `inventory_scope=partial`
- `scope_evidence.state=partial`
- `unresolved_evidence=["圆心(9,9)"]`
- 实际执行仍采用第一个圆心 `(0.35,0.35)`，但不再把第二个圆心当成已验证
- `acceptance_summary.status=review_required`，`accepted_count=0`

没有新增生成器、验收器、通用 NLP、冲突消解器或修复循环；解释器与候选门禁未改。

---

## 3. C1：确定失败进入现有修复循环

### 3.1 修复内容

在 `construction_acceptance_summary()` 之后、最终 `ready` 返回之前新增确定失败闸：

- 仅当 `object_count_consistency_acceptance.status == "failed"` 或 `object_identity_acceptance.status == "failed"` 时进入；
- `unverified / unknown / not_checked` **不触发自动重试**；
- 数量失败返回 `status=invalid`、`construction_error.code=object_count_mismatch`，携带要求数、实际数、`missing_object/extra_object`、`requires_structural_replan=True` 和重规划指令；
- 身份失败返回 `object_identity_mismatch`，携带失败条目；
- 返回中保留原计划、来源验收、汇总、试算结果和结构契约，供现有 `_formal_cad_construction` 捕获；
- 未新增修复循环、未修改 `max_repairs`、未改错误反馈协议。

### 3.2 服务级实测

原文：

> 两个立方体并排，画等轴投影

首轮只返回 1 个立方体，第二轮返回 2 个立方体。

| 指标 | 实测 |
|---|---|
| 模型文本出口调用 | **2 次** |
| 修复次数 | **1 次** |
| 修复预算 | **2，未改变** |
| 首轮状态 | `invalid` |
| 首轮错误 | `object_count_mismatch / missing_object` |
| 要求 / 实际 | **2 / 1** |
| 第二轮数量报告 | `passed`，2 / 2 |
| 最终草稿 | 1 |
| 最终正式 accepted | **0** |

第二轮修复后数量已通过，但“等轴投影”的完整几何合同仍未被现有证据完全覆盖，因此最终汇总为 `review_required`，`requirement_coverage=unknown`，候选仍不 accepted。这符合“修复后其他未决要求如实保留”的边界。

---

## 4. C2：已有完整证据被后续汇总消费

### 4.1 修复内容

- `_logical_object_count_consistency()` 增加可选 `source_acceptance` 参数：在没有更强来源契约基线时，消费 `scope_evidence.count_baseline` 作为 `source_scoped_primitives` 基线；
- `_identity_baseline_entries()` 在原有 composition/structure 通道没有条目、且 scope 完整时，把逐件证据转为身份条目，携带精确 `object_ids / geometry_ids / assembly_ids`；
- `_object_identity_consistency()` 增加预绑定分支：优先按来源逐件证据绑定的精确对象核验，要求数量一致、对象存在且未复用、测量类别与来源类别一致；不做按类别的模糊分配；
- 解释器只把 `verify_final_source_contract()` 的 `unknown_requirements` 合并进 base 汇总，并把 `coverage` 置为 `partial`、`review_required=True`；**没有把 final checks 并入 base checks**，避免破坏 `candidate_requirement_snapshot` 对 `check["source_requirement"]` 的既有契约。

### 4.2 三圆完整正例

原文：

> 生成一个图案。完整部件清单：外圆：圆，圆心(0,0)，半径1米，坐标单位米；左眼：圆，圆心(-0.35,0.35)，半径0.09米，坐标单位米；右眼：圆，圆心(0.35,0.35)，半径0.09米，坐标单位米

| 指标 | 实测 |
|---|---|
| 模型文本出口调用 | **1 次** |
| 隔离库持久化候选 | **1 条**（本次运行内同一 `variant_id`） |
| 其中 accepted | **1 条** |
| 正式候选视图 | **1 条**，同一 `variant_id` |
| `candidate_is_accepted` | **true** |
| `persisted_candidate_count` | **1** |
| `acceptance_summary.status` | **passed** |
| `review_required` | **false** |
| `verified_checks` | **5** |
| `requirement_coverage` | **complete** |

该正例沿真实 `_formal_cad_construction`、执行器、逐件来源验收、数量/身份验收、候选提交和隔离存储运行；只替换了 `_structured_review_text` 这一模型文本出口。持久化记录与正式候选视图指向同一个 `variant_id`，没有产生第二条候选。该 ID 是本次隔离存储运行内的一致性键，不作为跨运行的稳定标识。**没有测试注入 `passed/complete`，没有放宽 `_verified_candidates` 或正式 accepted 门禁。**

需要明确的口径：三圆正例的完整覆盖来自 base `verify_scoped_primitives()` 的 `scope_evidence`。对带“完整部件清单”标记的源文本，`verify_final_source_contract()` 本身返回 `not_checked`，因此本批没有把 final contract 当成正例的完整测量来源，也没有用它替代 base 证据。

### 4.3 同一正例的六类负例

| 负例 | 结果 |
|---|---|
| 末尾用分号增加未知条款“嘴巴为一条微笑曲线” | **accepted=0** |
| 末尾用逗号增加同一未知条款 | **accepted=0**，来源 `partial`，`unresolved_evidence` 保留该片段 |
| 末尾用逗号增加重复圆心 `圆心(9,9)` | **accepted=0**，来源 `partial`，`unresolved_evidence` 精确保留该片段 |
| 外圆半径改为 1.2 米 | **accepted=0**，试算阶段拒绝 |
| 缺少最后一个圆 | **accepted=0**；先由逐件来源匹配找不到“右眼”拒绝，早于数量一致性报告 |
| 标签与几何归属互换 | **accepted=0**，`object_binding_conflict` |

没有为了这六类负例新增专用生成器或验收框架；它们分别由现有尺寸测量、逐件来源匹配、共享消费的条款残留判定、数量/身份报告和 A 的绑定矛盾检查拦住。特别更正：三圆缺最后一圆的首拒原因不是“两立方体”负例中的 `missing_object`，而是逐件来源匹配先找不到右眼。

---

## 5. 回归结果

### 5.1 统一回归

按主控 14 模块口径，加上本批 5 个接线/来源模块，共 **19 个模块**：

| 指标 | 结果 |
|---|---|
| passed | **279**（比上一轮 277 增加 2 条） |
| skipped | **4** |
| failed | **0** |
| errors | **0** |

拆分口径：

- 主控 14 模块：**214 passed、4 skipped**（本轮未改动这些模块，沿用已核对的基线）；
- 本批 5 模块：**65 passed**（本收尾新增 2 条用例，较上一轮 63 条增加 2 条）；
- 4 条 skip 仍因审查环境未安装原生 `planegcs` / `solvespace`，与本次改动无关。

本轮 19 模块的实际命令为：

```powershell
python -m pytest -q `
  tests/test_c12_production_loop_mock.py `
  tests/test_cad_constraint_solver.py `
  tests/test_cad_construction.py `
  tests/test_cad_construction_commit.py `
  tests/test_cad_construction_interpreter.py `
  tests/test_cad_feature_contract.py `
  tests/test_cad_generation_recovery.py `
  tests/test_cad_plan_component_repair.py `
  tests/test_candidate_visibility_gate.py `
  tests/test_cad_edit_chain.py `
  tests/test_cad_edit_preview.py `
  tests/test_cad_edit_session.py `
  tests/test_cad_version_symbols.py `
  tests/test_candidate_save.py `
  tests/test_wiring_01_repair_gate.py `
  tests/test_wiring_01_evidence_consumption.py `
  tests/test_cad_source_acceptance.py `
  tests/test_cad_final_source_contract.py `
  tests/test_cad_relation_acceptance.py
```

5 模块命令为：

```powershell
python -m pytest -q `
  tests/test_wiring_01_repair_gate.py `
  tests/test_wiring_01_evidence_consumption.py `
  tests/test_cad_source_acceptance.py `
  tests/test_cad_final_source_contract.py `
  tests/test_cad_relation_acceptance.py
```

### 5.2 C1 提交单独验证

为避免“三个提交只有最终状态能跑”，在 `fa65bb37e883b2fb3e592ccec82f9ee2586f5936` 建立临时 detached worktree，单独运行：

- `test_wiring_01_repair_gate.py`
- `test_cad_construction_interpreter.py`

结果：**75 passed、0 failed、0 errors**。临时 worktree 已删除。

### 5.3 不能作为回归口径的项

直接 `pytest tests` 在当前分支仍会因缺少 `tests/manual` 目录产生 **8 个 collection errors**。这是分支/环境缺件，不是本轮测试失败；本报告未把这 8 个错误算作回归结果，也未扩大无关测试范围。

---

## 6. B 线只读边界核对

B 线未修改生产代码，只核对对象作用域和证据边界。当前实现的支持边界如下：

1. **一个来源条目绑定一个逻辑对象**：`quantity=1` 且对象 ID 唯一；同一对象被两个来源条目复用时，后一个条目会进入 `unverified`，不会借用前一个条目的通过结果。
2. **一个来源部件跨多个逻辑对象**（如共享轮廓、多段组成一个具名部件）暂不输出 complete；`object_ids` 数量与条目数量不一致时保留未决，不做强制合并。
3. **多段/复合路径**仍由现有曲线质量与结构契约处理，本批没有新增曲线求交或连续性逻辑。
4. **对象粒度计数**：`scope_evidence.count_baseline` 固定按 object 粒度统计唯一对象 ID；没有把 `assembly_id=whole` 误并成 1。若未来出现显式 assembly 合同，当前逻辑只在“没有更强来源契约基线”时使用 object 粒度基线，不会覆盖已有 assembly 契约。
5. **标签只作矛盾信号**：不作为正向身份证明；没有标签的正常对象不会因此被拒绝，标签与来源主体冲突时才报 `object_binding_conflict`。
6. **证据边界**：正例只覆盖现有支持的三圆完整清单；不能据此宣称任意图形、任意复合路径或任意装配关系都已获得完整覆盖。

---

## 7. 明确未做 / 仍不在本批

以下项已登记，但**没有**在本批修改：

- Feature Contract 生产入口接入；本批未把它当作独立测量器；
- 顶层草稿 `variant` 残留与工具栏响应统一处理；
- 约束摘要 `verified/status` 字段映射；
- 求解器异常时残差、容差、失败约束的透传；
- M3 失败路径执行后几何快照、默认几何比较器两项缺口；
- R-IDENTITY-1 仍未关闭；
- App 画布/HTTP 端到端渲染验收；
- 真实模型调用、70 例重评、A9 重跑、S1 解冻。

正式集成状态：**NO-GO**。

---

## 8. 环境与同步清单

- 本批 A、C1、C2、两轮终验收尾及报告/证据提交均已正常推送到远端独立评审分支 `doubao/review-wiring-01-20261120`；均为普通 fast-forward。
- 两轮终验收尾分别为 `2fb8dc75fb338a8e1c3d6507664b1bcaa7d7ed54` 和 `fbe7de5726f0d5e838134fb7d308663ef52b123a`；原 `aa628fc` 评审分支、`f2a6da6` 和 `26d5938` 均未被改写。
- 生产代码最后提交为 `fbe7de5726f0d5e838134fb7d308663ef52b123a`；其后只有报告、证据提交，不改生产代码。远端最终 tip 以评审分支为准。
- 全程**未合并 main、未 force push、未 amend、未重写历史**。
- 用户偏好要求本地代码修改后更新指定的“后端最终同步清单”；该目标路径在本机不存在、不可达。已确认不可达，**未擅自改写其他同名文件**。
- `.audit-evidence` 为临时探针与原始输出目录，未纳入任何提交；原始证据已另存到交付证据包，提交前状态为仅该目录未跟踪。

---

## 9. 交付证据索引

证据包：`Wiring_01_Evidence_final.zip`。

- `manifest.json`：版本、提交、测试与探针原始结果摘要；
- `Wiring_01.diff`：`aa628fc..fbe7de5` 完整代码与测试差异；
- `Wiring_01_minimal_patch.diff`：`26d5938..fbe7de5` 本轮共享消费最小补丁；
- `pytest_final_19_modules.txt`：收尾后 19 模块统一回归原始输出（279 passed、4 skipped）；
- `pytest_five_modules.txt`：收尾后本批 5 模块原始输出（65 passed）；
- `pytest_positive_and_three_variants.txt`：三圆正例、分号未知条款、逗号未知条款、重复圆心四条服务级用例；
- `service_variants_after_patch.txt`：正例与六类负例的服务级结果、来源状态、未决片段与 accepted 计数；
- `notes.txt`：C1 独立 75 passed 的日志留存口径与本次报告更正说明。

C1 独立 75 passed 的原始命令日志未保留在本包中，仅作为报告记录；不伪造日志，也不以补丁后回归替代该历史结果。
