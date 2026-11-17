# B 线第四轮判定口径预注册（几何 / 拓扑侧）

> 冻结时点：在看到任何第四轮真实模型产出结果之前注册。本文件只规定几何与拓扑一侧
> "怎么判"，不发起模型请求、不实例化模型客户端、不改动 `backend/app` 生产代码。
> 第四轮收到 D 的案例记录后，按本口径逐条判定；**口径不得在看到结果后修改**。
> 若事后发现口径必须调整，另起"修订记录"小节，注明条目、原口径、修订原因与影响范围，
> 不得直接覆盖本节。

## 0. 适用范围与前提

- 判定对象：真实模型产出、经构造链路落库的复合路径几何（line / bezier / arc / spline 段）。
- 判定依据：第三轮已落地的 `cad_topology_safety.py` 曲线级分析与构造层门控既有语义，
  以及既有 B1 / B1.1 / B1.2 测试夹具。
- 判定方式：对 D 记录中保存的几何与步骤字段，本地复跑同一分析函数 / 门控；
  不依据模型自述、不依据计划文本措辞、不依据 Mock 通过记录判通过。
- 本轮不评估：模型语言规划合理性、生成耗时、重试次数、UI 表现。

## 1. 判定三态定义

| 状态 | 定义 | 是否计入生成成功 |
|---|---|---|
| **通过（pass）** | 下列 C1–C9 判据全部满足，且每条都有对应数值证据；无任何拒绝码、无未决标记 | 是（仅几何/拓扑栏） |
| **拒绝（reject）** | 存在已证明的自相交 / 交叉 / 重复段 / 断开 / 开口 / 连续性失败等硬缺陷，证据确定 | 否 |
| **未决（unresolved / review_required）** | 拓扑尚未被证明清楚，或误差界 / 片数预算未能在容差内建立；不得按通过计 | 否 |

三态互斥：一条记录先归未决，就不得再因"其余部分看起来合法"改判通过。

## 2. 判据清单（证据字段 + 硬规则）

通用硬规则：**无证据即不得判通过**。某判据缺少对应字段或分析输出为空时，
该判据记"证据缺失 → 未决"，不得推定合法。

### C1 自相交 / 段间交叉
- 证据来源：`analyze_composite_segments(...)` 返回的 `contacts`；门控 details 的
  `curve_contacts`、`affected_segment_indices`、`conflicts`。
- 接触类型（`kind`）：`crossing`、`self` 为已证明交叉；`endpoint` 为端点接触；
  `tangent` 为已证明切线；`near_contact` 为未决近距。
- 通过条件：`crossing` / `self` 类接触数为 0；`curve_contacts` 中无确定交叉。
- 拒绝条件：存在任一 `crossing` / `self` 接触，或构造层弦门 `self_intersection_count > 0`。
- 证据字段：`segment_indices`、`parameters`、`parameter_intervals`、`points`、
  `distance`、`kind`；交叉接触 `distance` 应为 0.0 量级。

### C2 切线接触
- 证据来源：`kind == tangent` 的接触条目；叶弦夹角 ≤ `TANGENT_ANGLE_DEG=15°`，
  距离 ≤ 邻近带（`PROXIMITY_FACTOR·tol = 2·tol`）。
- 通过条件（路径不允许自交时）：无切线接触；若计划显式 `allow_self_intersection=True`，
  单独记录切线位置，不按拓扑拒绝，但仍在检测栏留痕。
- 拒绝 / 未决：锐夹角子邻近残差（夹角 >15° 且未被 straddle 证明）不得记为切线，
  归 `near_contact` 未决。

### C3 端点接触与连接连续性
- 证据来源：`kind == endpoint` 接触；构造层 `disconnected_composite_path`、
  `open_composite_path`、`c1_continuity_failed` 错误码及 details 中的
  `previous_segment` / `next_segment` / `gap` / 关节诊断。
- 通过条件：相邻段端点距离 ≤ `connection_tolerance`；闭合路径首尾闭合；
  要求 G1/C1 的关节切向偏差在 `tangent_tolerance_deg` 内。
- 拒绝条件：任一端点超容差断开、闭合路径开口、必需连续性失败。

### C4 闭合性
- 证据来源：步骤字段 `closed`；门控 `open_composite_path`；首尾端点距离。
- 通过条件：`closed=True` 时首尾端点距离 ≤ 容差；`closed=False` 不要求首尾相接。
- 未决：首尾坐标缺失或距离无法计算时记未决，不推定闭合。

### C5 Arc 合法性与弦高界
- 证据来源：arc 段字段 `center` / `radius` / `start_angle` / `end_angle` / `clockwise`；
  `arc_chord_height`、`arc_chord_count_for_tolerance`；展开片数与 bounded 标志。
- 通过条件：半径 >0；扫角非零（`zero_sweep_composite_arc` 不得出现）；
  反解片数下精确矢高 ≤ 目标弦高（邻近带 `2·tol`）；bounded=True。
- 拒绝条件：零扫角、退化半径、弧端点与相邻段冲突（`sector_arc_endpoint_conflict` 等）。
- 未决：所需片数超 `ARC_MAX_PIECES=2048`，弦高界无法在预算内建立（见第 4 节）。

### C6 Spline 合法性与残差界
- 证据来源：spline 字段 `degree` / `control_points`；`spline_residual_bound`；
  展开片数与 bounded 标志。
- 通过条件：控制点数量 > 阶数；保守残差界 `B = 3.0·e ≤ h_max`，bounded=True。
- 拒绝条件：控制点 ≤ 阶数、阶数越界（模型若产出非均匀 / 开口 / 未夹紧节点方案，
  本轮无曲线级精确求交能力，不得判通过）。
- 未决：残差在 `SPLINE_MAX_PIECES=512` 内仍不收敛到容差。

### C7 重复段
- 证据来源：构造层 `duplicate_composite_segment`；`duplicate_pairs` 与 details `conflicts`。
- 拒绝条件：存在重复边且 `allow_duplicate_segments=False`。

### C8 采样 / 尺寸误差
- 证据来源：`sampling_error_exceeded`、`maximum_sampling_error`、布局放大后误差上界。
- 拒绝条件：尺寸缩放后采样误差上界超过精度限制。

### C9 未决标记（fail-closed）
- 证据来源：`TopologyReport.unresolved`；门控 details `unresolved_topology=True`、
  `failure_scope="unresolved_topology"`、`escalation="replan_or_human_review"`。
- 归集规则：只要 `unresolved=True` 且无已证明接触覆盖该段对，整记录归未决，
  不计生成成功；不得用"不确定"充通过。

### C10 计划意图与开关口径
- 证据来源：步骤字段 `allow_self_intersection`、`allow_duplicate_segments`、
  `continuity`、`connection_tolerance`、`samples_per_curve`。
- 规则：门控严格按计划开关裁决；本轮不得事后放宽 `allow_self_intersection=False`
  或任何验收阈值。计划未显式允许自交时，接触即拒绝。

## 3. 必须归入 unresolved_topology / review_required 的情形

1. 段对搜索预算耗尽或深度截断，仍落在不确定带（`near_contact` 条目）。
2. arc 所需片数超上限，或 spline 残差在片数上限内未收敛。
3. 锐夹角子邻近残差，无法证明是切线还是浅交叉。
4. 几何字段缺失、坐标不可计算、样条节点方案超出本轮能力范围。
5. 同一段对既有一条已证明接触、又有一条未决近距：该段对按已证明接触归类；
   其余未被已证明接触覆盖的段对仍归未决。

以上情形在检测栏记 `unresolved_topology`，处置栏记 `review_required` /
`replan_or_human_review`，**不计入成功生成**。

## 4. 片数 / 预算超限处置口径

| 超限项 | 上限 | 处置 | 理由 |
|---|---|---|---|
| arc 展开片数 | 2048 | 记**未决**（非拒绝） | 弦高界尚未证明失败，只是预算内未能建立；fail-closed 待复核，而非判定存在交叉 |
| spline 展开片数 | 512 | 记**未决**（非拒绝） | 残差界未收敛，不能证明清楚也不能证明相交 |
| 段对节点预算 | 8000 / 段对；自交二分 10 层 | 记**未决** | 截断 subtree 不输出确定无交或确定相交 |
| 细分深度 | 16 | 记**未决** | 同上 |

区分"拒绝"与"未决"：拒绝必须有已证明的缺陷证据（straddle、端点超差、重复段、
断开等）；预算 / 界未建立一律未决。两者都不计成功生成，但复核路径与修复提示不同。

## 5. Mock 能证明、真实模型不能证明的边界

- Mock 计划 / 夹具合法，只证明检测链路与判定函数可用；**不等于**真实输出几何可验收。
- 本地构造的解析夹具（回环、混阶交叉、偏移拱等）通过，不代表模型生成的同类形状合法。
- 门控对 Mock 输入放行，不能作为真实案例 `feasibility.ok` 的证据；真实案例必须用其
  记录的实际几何复跑分析并留数值证据。
- 检测栏"拒绝了一个错误图形"不得计入 generation 成功；detection 与 generation 分栏统计。
- 模型自述"已避开交叉 / 已闭合"不构成证据；以坐标、接触条目、错误码为准。

## 6. 预判：真实模型输出最可能被判失败的三个几何原因

1. **窄回环 / 自交轮廓**：模型生成的闭合曲线控制点顺序导致曲线自身回穿，
   叶级粗采样容易漏，曲线级 `self` / `crossing` 检出后直接拒绝。
2. **端点未对齐或闭合缺口**：相邻段端点、闭合首尾存在超 `connection_tolerance` 的
   间隙，或 G1/C1 关节切向不连续，触发断开 / 开口 / 连续性失败。
3. **弧 / 样条逼近失控**：大半径或大扫角弧、高曲率样条在有限采样下弦高 / 残差超界，
   片数预算内无法建立保守界，归未决待复核；局部尖峰也可能产生未被采样覆盖的近距。

## 7. 引用的现有常量与字段（以工作树代码现状为准）

- 模块常量：`PROXIMITY_TOLERANCE=1e-6`、`SUBDIVISION_MAX_DEPTH=16`、
  `PROXIMITY_FACTOR=2.0`、`NODE_BUDGET_CAP=8000`、`SELF_HALF_DEPTH=10`、
  `ARC_MAX_PIECES=2048`、`SPLINE_MIN_PIECES=8`、`SPLINE_MAX_PIECES=512`、
  `SPLINE_RESIDUE_FACTOR=3.0`、`TANGENT_ANGLE_DEG=15.0`。
- 接触字典：`segment_indices` / `parameters` / `parameter_intervals` / `points` /
  `distance` / `kind`。
- 门控 details：`curve_contacts` / `affected_segment_indices` / `failure_scope` /
  `unresolved_topology` / `escalation` / `conflicts`。

## 8. 修订记录

（暂无。任何对第 2–5 节口径的事后调整必须在此登记：条目、原口径、修订原因、
影响的判定结论。）
