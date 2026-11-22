# B 线第七轮 · C 组复杂生成失败归因矩阵（离线诊断，零模型调用）

> 边界：本轮只诊断 + 离线探针，**未改 `backend/app` 生产代码**、未改公共 Schema；未调用真实模型、
> 未联网、未重跑 A9、未改冻结语料与冻结输入；不为任何单图形（齿轮/蜂窝/太极/爱心/字母 A 等）
> 加专用生成器、专用判据分支或固定控制点。不 amend、不 push、不合并。
>
> 探针（在 `backend/` 下一条命令复跑）：
> `python evaluations/v1/probes/b_round7_c_failure_attribution.py`
>
> 结论分级：**已查证**（探针/既有记录实测）、**推断**、**待验证（unverified）**。
> 检测结果与生成结果分栏：本轮只做失败归因与判据缺口诊断，**不证明任何生成成功**。

## 0. 附件使用边界（哪些来自提案、哪些来自实测）

| 内容 | 来源 | 使用方式 |
|---|---|---|
| 七类 Predicate 定义（`boundary_extremum/local_extremum/cusp/notch/mirror_symmetry/continuity/connection`）、Measurement 三态、M2 闭包、M3 双条件 stalled | Codex FEATURE-CONTRACT V1.1 提案（独立仓库 `codex-cad-agent`，基线 `9bd105f`，提案提交 `bd8e43c`，自述未改生产代码、未跑测试） | 仅作**判据口径参照**；不当作已实现成果，不把其测试设计当作已通过回归，不合并该分支、不共享其工作树/数据库。 |
| 五层根因分类、C1–C34 编号锚定、证据账本、合成缺口演示、回归结果 | 本线离线探针与既有 D/C 线只读记录 | 实测/记录证据，标注 `evidence_mode`。 |

**与提案口径对齐的四条边界**（本线归因遵循）：
1. `lower_tip` 旧区域存在性布尔**不得冒充数学 cusp**："底部区域有无极值点"与"左右切线角不连续的尖点"是两件事；归因时不把前者判成后者。
2. 旧语义检查先做 legacy parity，不自动升级为强制数学门禁。
3. 未授权语义不进入强制集合。
4. M3 只有"失败特征无实质改善 **且** 闭包几何确定等价"才 stalled；与 C 线当前实现相容，本线判据建议不与此冲突。

**已识别的口径差异（不自行折中，单列）**：
- 提案 `continuity` 中 C1 要求共同参数化下**导数向量相等（含幅值）**；本线既有探针的切线角差（15° 门控）只证明角度接近，**不构成 C1 导数幅值证明**。接入时须按提案口径把 C1 与 G1 分开标注，不得把角度检查上报为 C1 通过。
- 提案 `cusp` 要求半三次尖点的正则化局部参数与 `det(γ″,γ″′)≠0`；折线角点只有 corner 证据，不能升级为 cusp。

## 1. 证据模式与归因分层口径

### 1.1 证据模式（沿用 D1 词汇，禁止 Mock 冒充真实通过率）

| evidence_mode | 含义 | 本轮可否作为生成失败证据 |
|---|---|---|
| `live_model` | 真实 provider 调用 | 可作端到端失败证据；本线仅 A9 一例 |
| `reconstructed_fixture` | 由仓库已知输入/控制点离线重建 | 只证明测量/诊断链路行为，不是历史真实响应 |
| `rule_parser_zero_cost` | 确定性规则解释器零成本回放 | 只证明规则路由与模板行为；**不是**端到端生成结果 |
| `unavailable` | 无冻结定义/原始响应 | 记 `not_run`，不计编辑器缺陷 |

### 1.2 五层根因类别

| 层 | 含义 |
|---|---|
| `model_planning` | 计划本身错、缺字段、表达式与声明不符；或规则链路未覆盖该形态 |
| `geometry_measurement` | 判据测不出或误判（弦采样、最近点、径向剖面、计数/规则性维度不足） |
| `geometry_execution` | 构造/求交/布尔/连接执行失败 |
| `acceptance` | 测得出但判定规则错，或容差口径错 |
| `pre_dependency_pending` | 依赖另一版本产物尚未通过；**单独记账，不计编辑器缺陷** |

**编辑器自身失败 vs 前置版本未阻塞必须分开**：规则未覆盖导致的 `clarification_required`、依赖挂起
（`dependency_pending`）归入前置/链路覆盖层，不计入几何执行器缺陷；只有执行器在已给定合法计划上
构造/求交/连接失败才归 `geometry_execution`。

## 2. 失败类型矩阵（六类 × C 编号 × 根因 × 最早失败层 × 证据）

> C1–C34 的真实运行记录**不存在**于本仓库；下表 C 编号来自语料输入原文锚定，层归属为基于既有
> 同类记录与合成演示的**推断**，逐条证据见 §3。凡无 live 记录者标 `unverified`。

| # | 失败形态 | 语料 C 编号（主归属） | 最早失败层（推断） | 测量/验收缺口 | 证据状态 |
|---|---|---|---|---|---|
| 1 | 复合轮廓（曲线段+直线段/尖角混合） | C3, C4, C5, C6, C11, C12, C13, C18, C19, C20, C21, C26, C27, C33, C34 | `model_planning`（规则未覆盖复合路径） | 缺段类型混合标记；直线-曲线接点类型维度 | 规则回放旁证（stepped_foundation / factory_zone_grid）；C 系列 live `unverified` |
| 2 | 多部件组合（相对位置/连接关系） | C7, C9, C10, C15, C16, C24, C25, C28, C29, C31, C32 | `acceptance/geometry_measurement`（逻辑对象未拆分） | 缺部件身份与独立对象计数；相对位置约束未绑定来源 | 规则回放旁证（warehouse / workshop / parking）；live `unverified` |
| 3 | 曲线与直线连接（C0/G1/C1 连续性） | C1, C2（次级 C3, C19, C20, C34） | `geometry_measurement`（已有部分诊断，维度不全） | G2 无判据；零导数/未指定参数化应 `undetermined`；cusp/corner 不强制 G1 | 重建夹具 S1 通过、A9-JUNCTION 2 接点失败；live 仅 A9 局部 |
| 4 | 重复结构（同形 N 次/数量/等距/对齐） | C14, C22, C23（次级 C6, C17, C30） | `geometry_measurement`（计数与规则性维度缺失） | 最近点/Hausdorff 测不出重复个数、等距偏差、对齐偏差 | 规则回放旁证（stadium / solar）；live `unverified` |
| 5 | 阵列拓扑（行列/间距/包围盒/单元归属） | C8, C17, C30 | `geometry_measurement`（阵列维度缺失） | 缺行列数、行列间距一致性、阵列包围盒、单元-部件归属 | 规则回放旁证（parking_rows）；live `unverified` |
| 6 | 整体几何尺寸约束（整体宽高/中心/比例，作用域分离） | 跨类次级：C3, C5, C8, C11, C12, C13, C14, C16, C18, C19, C20, C21, C26, C27, C29, C32, C33, C34 | `geometry_measurement/acceptance`（作用域未分离） | 整体 bbox/中心/比例须与部件尺寸分scope测量；部件满足不得掩盖整体缺失 | A9 live 仅验收侧（lower_tip）证据；尺寸/中心维度单独取证 `unverified` |

## 3. 归因证据逐条

### 3.1 既有记录证据（只读引用）

| 案例 | evidence_mode | 层 | 实测记录 | 证据位置 |
|---|---|---|---|---|
| A9 | live_model | acceptance + model_planning | 真实 `deepseek-flash` 两轮，`failed`，未持久化候选；`lower_tip` 两次未检出；旧区域布尔不等于 cusp 证明 | `D1_round4_A9真实模型受控评测报告.md`；`round4/A9_case_record.json` |
| S1 | reconstructed_fixture | geometry_measurement | 三段开放 Bezier：C0/C1 通过，2 接点 0 失败，max tangent delta 0.0°，自交 0 | `p1.3g-S1-diagnostics.json` |
| A9-JUNCTION | reconstructed_fixture | geometry_measurement | 4 接点 2 失败，max tangent delta 107.94°，c1=false；接点诊断字段已增强 | `p1.3g-A9-diagnostics.json`；`P1.3-G Bezier连接点失败证据增强报告20261107.md` |
| M1 | unavailable | pre_dependency_pending | 无冻结输入与验收规则，`not_run`；不计编辑器缺陷 | `mock_replay_results.json#M1` |
| warehouse_with_aisles | rule_parser_zero_cost | acceptance（测量缺口） | 几何已出（6 图元）但 `minimum_logical_objects` 未通过：未识别为独立逻辑对象 | `mock_replay_results.json#warehouse_with_aisles` |
| parking_rows_and_driveway | rule_parser_zero_cost | acceptance（测量缺口） | `minimum_entities` + `minimum_logical_objects` 未通过；重复车位未按对象计数 | `mock_replay_results.json#parking_rows_and_driveway` |
| workshop_with_machine_pads | rule_parser_zero_cost | acceptance（测量缺口） | `minimum_entities` + `minimum_logical_objects` 未通过；设备基础未独立成对象 | `mock_replay_results.json#workshop_with_machine_pads` |
| stepped_foundation | rule_parser_zero_cost | model_planning（规则覆盖） | `clarification_required`：`required_types/minimum_entities/objects` 缺失；规则解析器未覆盖嵌套台阶 | `mock_replay_results.json#stepped_foundation` |
| factory_zone_grid | rule_parser_zero_cost | model_planning（规则覆盖） | `clarification_required`：分割线/网格类型与对象数未被规则表达 | `mock_replay_results.json#factory_zone_grid` |
| stadium_bleacher_rows | rule_parser_zero_cost | model_planning（规则覆盖） | `clarification_required`：重复排/座席数量与对象数缺失 | `mock_replay_results.json#stadium_bleacher_rows` |
| solar_panel_rows | rule_parser_zero_cost | model_planning（规则覆盖） | `clarification_required`：两排阵列单元与间距未被规则表达 | `mock_replay_results.json#solar_panel_rows` |

### 3.2 合成离线演示证据（探针输出，确定性，非历史案例）

探针 `b_round7_c_failure_attribution.py` 实测：

| 缺口演示 | 实测输出 | 说明 |
|---|---|---|
| G1 接点 | gap=0.00e+00，切线差 0.00°，C0=通过，G1=通过 | 端点重合且切线同向 |
| C0-only 接点 | gap=0.00e+00，切线差 90.00°，C0=通过，G1=不通过 | 距离重合但切线突变；距离单一判据无法标注连接类型 |
| 规则重复行（4 点等距） | count=4，spacing_dev=0.000，perp_dev=0.000 | 计数 + 等距 + 对齐三量可分离测量 |
| 不规则重复行 | count=4，spacing_dev=0.267，perp_dev=0.000 | 个数相同但间距不一致，Hausdorff 类距离难以暴露 |
| 部件尺寸满足 | overall=通过，part=通过 | 整体与部件双 scope 均过 |
| 部件尺寸偏差 | overall=通过，part=不通过，scope_mixed=True | 整体包围盒满足不能掩盖部件缺口；缺作用域分离时会被误放 |

## 4. 通用判据缺口建议（可推广，不绑单个图形）

| 缺口 ID | 现有判据为何测不出 | 需要补的维度 | 对既有 21 + 111 回归的影响评估 |
|---|---|---|---|
| G1 连接类型维度 | 现有连续性把端点距离与切线角度混在同一字段；只看距离无法区分 C0 接点、G1 顺滑、尖角 corner | 分离：C0 端点距离；G1 非零单侧导数同向；C1 共同参数化导数幅值相等；corner 走 `intentional_corner` 分支不强制 G1；零导数/无可比参数化 → `undetermined` | 接入须先 shadow parity；H4 局部约束回退兼容已存在，既有行为不改。风险：把合法尖角误判 G1 失败，须由 intent 分支豁免 |
| G2 重复计数 + 规则性维度 | 点集距离/最近点只比位置接近，不回答"有几个、是否等距、是否对齐" | 来源授权的期望基数；相邻副本间距均值与最大偏差；垂直方向对齐偏差；缺一维即 `undetermined`，不猜个数 | 纯新增测量维度，不动既有拓扑门禁；既有 21+111 不涉及重复对象断言，预期零行为变化 |
| G3 阵列拓扑维度 | 无行列结构、阵列包围盒、单元归属概念；平面点云无法还原行列 | 行列数、行距/列距一致性、阵列外接框、单元-部件绑定证据；单元归属不明 → `unresolved` | 同上，shadow 接入；不放宽既有闭合/自交门禁 |
| G4 尺寸作用域分离 | 现有包围盒测量不标 scope，部件尺寸通过可掩盖整体宽高/中心/比例缺失 | 整体 scope 与部件 scope 分别测 bbox、中心、比例；合取判定，任一项缺证据 → `undetermined`；禁止部件通过计入整体通过 | 与既有尺寸断言解耦；接入前须核对既有用例的 scope 标注，避免双重计数 |
| G5 部件身份与逻辑对象拆分 | `geometry_count` 是图元数，不等于可独立选中的逻辑对象；模型自报 object_id/assembly_id 不可信 | 后端归属证据 + 来源 selector 重建对应；一对多须明确基数与成员归属；归属不明 → `unresolved` | 对应提案 §2.2 两阶段绑定；只读建议，不改现有身份系统 |
| G6 自由曲线误差界维度 | 弦采样/剖面残差缺保守上界时，连续曲线性质不能被采样点冒充证明 | 沿用 B1.2 arc/spline 保守弦高界；无误差界或预算截断 → `undetermined`，不输出确定相交/无交 | 与 B1.2 既有口径一致，不新增生产阈值 |

## 5. 误判风险与避免措施

| 风险 | 触发场景 | 避免措施 |
|---|---|---|
| 误拦合法简化 | 模型用单条多段线/单轮廓表达 N 个重复单元（合法简化），被计数维度判"缺对象" | 基数要求必须来自显式来源；未授权不强制计数；无法确定表达层级时 `undetermined` 放行修复，不直接拒绝 |
| 误把尖角当 G1 失败 | 设计上 intentional corner 被切线门控拒绝 | corner 由连接意图分支识别，不进入 G1/C1 强制；无意图证据时 `undetermined` |
| 部件通过掩盖整体失败 | 只测部件 bbox 就放行整体比例/中心要求 | 双 scope 合取；整体要求无整体测量证据不得判通过 |
| 区域布尔冒充数学尖点 | 旧 `lower_tip` 区域存在性被上报为 cusp 证明 | 沿用边界：区域存在性记 `legacy_region_presence`；cusp 需导数/展开证据，缺证 `undetermined` |
| 规则回放失败被记成生成失败 | `rule_parser_zero_cost` 的 51 条未通过被计入端到端通过率 | 按 evidence_mode 分桶；规则路由问题归链路覆盖层，不计执行器缺陷，不计真实生成成功 |

## 6. `unverified` 清单（拿不到证据，不推测）

1. **C1–C34 全部 34 例**：仓库内无 live_model 记录，无原始模型响应；其真实失败层归属为推断，须待授权真实受控运行后回填。
2. **A9 尺寸/中心维度**：live 证据仅验收侧 `lower_tip` 未检出；中心 (2,3)、宽 4 高 4 是否达成未单独取证。
3. **G2 连续性**：现有探针/夹具未覆盖二阶导数连续判据。
4. **3D 投影类 C27/C33**：空间投影轮廓的连接与可见性无任何记录。
5. **嵌套同心类 C15/C29**：内外同心度、环域宽度一致性无测量记录。
6. **密铺阵列 C17**：六边形无缝拼接的间隙/重叠误差无判据与记录。
7. **参数曲线 C12/C18/C19**：螺旋/星形线/心形线的解析误差界与采样充分性未验证。
8. **M1**：无冻结定义，既不能归因也不能排除缺陷。

## 7. 回归与本轮改动范围

复跑命令（`backend/` 下）：

```
python -m pytest tests/test_cad_topology_safety_b1.py tests/test_cad_topology_safety_b11.py tests/test_cad_topology_safety_b12.py tests/test_cad_construction.py tests/test_cad_construction_interpreter.py -q --tb=short
```

- B 线拓扑三文件 + 执行器 + 解释器：**132 passed**（B 21 + 执行器/解释器 111）。
- 本轮改动仅探针 `probes/b_round7_c_failure_attribution.py` 与本报告；`backend/app` 零改动。
- 既有 `test_design_requirement_followup.py` 3 条基线失败与本轮无关（第六轮已核实：生产目录 diff 为空，属既有失败）。

## 8. 待裁决越界候选（B 线不动手，仅记录）

- 若要把 G1–G5 维度接入生产门禁，涉及 `cad_construction.py` 连续性/对象计数、解释器绑定与公共 Schema 字段，属 A/C 线范围；接入前须先做 shadow parity，不自动升级强制门禁。
- 阵列/重复/部件身份的绑定语义依赖来源索引与 selector 闭包，与提案 M2 闭包图相关，需 C/A 线评估。
