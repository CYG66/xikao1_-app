# B 线第五轮 · FEATURE-CONTRACT 几何等价判据与独立测试（离线，零模型调用）

> 边界：本轮未实例化模型客户端、未联网、未重跑 A9、未启动其他案例；未改公共 Schema、
> 未改 `backend/app` 生产代码。判据原型为离线探针，不含任何 A9/爱心坐标、case_id 或
> 形状白名单。结论分级：**已查证**（探针实测）、**推断**、**待验证**。
>
> 探针：
> - `probes/b_round5_geometry_contract.py`（判据函数库）
> - `probes/b_round5_test_matrix.py`（独立测试矩阵，一条命令复跑）
>
> 复跑命令（在 `backend/` 下）：
> `python evaluations/v1/probes/b_round5_test_matrix.py`

## 1. 判据清单（多维，不只看 Hausdorff）

### 1.1 轨迹等价 `trajectory_equivalent`

等价判定同时覆盖五个维度，任一维度失败都在 `fail_reasons` 里指明是哪一维：

| 维度 | 判据 | 数据来源 |
|---|---|---|
| 点集距离 | 双向 Hausdorff，按包围盒对角线归一化，落在相对形状带宽内 | 采样点列 |
| 方向/参数化朝向 | 闭合多边形有向面积符号；反向遍历判方向维失败，标记 `reversed` | 采样点列 |
| 端点与闭合状态 | 闭合标志一致；开口曲线端点距离在带宽内 | 规格字段 + 点列 |
| 拓扑关系 | 自相交个数一致；显式段数/段签名一致（采样 tessellation 段数不作闸门） | 弦跨立求交 + 规格元数据 |
| 控制点签名 | 提供控制点列时逐点比对 | 规格字段 |

综合关系取值：`equivalent` / `same_trajectory_reversed`（点集相同、方向相反）/
`different` / `undetermined`。**反向遍历不算有效几何改善**：它是方向维失败，
`same_trajectory_reversed` 不得计入修复进展。

### 1.2 相似变换识别 `similarity_transform`

判定第二曲线是否为第一曲线的缩放/平移/旋转/反射版本。相似变换保持形状、闭合与拓扑；
这类样本**几何不等价但可能合规**，不得因"几何变了"判失败。输出平移向量、尺度、
旋转角、是否反射、对齐残差（绝对 + 归一化）。

### 1.3 独立对称验证 `symmetry_check`

不依赖形状名称：绕质心构造径向剖面 `r(θ)`，扫描镜像轴方向，比较 `r(α+φ)` 与
`r(α−φ)` 的残差分布（中位数 / p90 / 最大值）。输出判定 `symmetric / near_symmetric /
asymmetric / undetermined`、轴角、残差与置信度。

### 1.4 边界特征分类 `classify_boundary_feature`

对单个边界点输出可复核测量值 + 置信度 + 未决状态：左右切线角、切线夹角、曲率比、
内外侧符号、邻弦法向偏移。角色：`outward_extrema / inward_notch / cusp / regular /
undetermined`。自交邻域由拓扑模块通过 `crossing_hint` 传入；提示存在交叉时内部侧
歧义，直接 `undetermined`。

## 2. 函数签名与 C 线消费字段

### 2.1 `trajectory_equivalent`

```
trajectory_equivalent(spec_a, spec_b, tolerance) -> EquivalenceResult

EquivalenceResult:
  equivalent: bool
  undetermined: bool
  relation: equivalent | same_trajectory_reversed | different | undetermined
  reversed: bool
  checks: {维度: {status: pass|fail|undetermined, 测量值...}}
  fail_reasons: list[str]            # 哪一维导致不等价
  hausdorff, hausdorff_normalized: float
  orientation_match, endpoints_match, closed_match: Optional[bool]
  topology: {self_intersections: (a,b), explicit_segments: (a,b)}
  counterexample: Optional[((x,y),(x,y))]
```

**C 必须提供的输入字段**（任一缺失 → `undetermined`，不得判等价）：

| 字段 | 含义 |
|---|---|
| 段类型 | line / bezier / arc / spline / parametric |
| 控制点或参数表达式 | bezier/spline 控制点列；arc 圆心/半径/起止角；parametric 的 x/y 求值器 |
| 参数区间 | `t_start / t_end`（允许 `t_end < t_start`，记反向） |
| 闭合标志 | closed / open |
| 既有容差 | `connection_tolerance`、`max_sampling_error` |
| 采样密度 / 离散化方式 | 采样点数或弦高控制 |

### 2.2 `similarity_transform`

```
similarity_transform(a_points, b_points, tolerance) -> TransformResult
  is_similarity: bool
  translation: (dx, dy)
  scale: float
  rotation_deg: Optional[float]
  reflected: bool
  residual, residual_normalized: float
  preserved: {closed, topology_match}
```

### 2.3 `symmetry_check` / `classify_boundary_feature`

```
symmetry_check(points, tolerance, near_band_factor=10.0) -> SymmetryResult
  verdict, undetermined, axis_angle_deg, axis_intercept
  residual_median, residual_p90, residual_max, matched, confidence, reason

classify_boundary_feature(polyline, index, tolerance, window=4,
                          crossing_hint=False) -> FeatureResult
  role, undetermined, reason
  tangent_left_deg, tangent_right_deg, angle_gap_deg
  curvature_ratio, side_sign, offset, confidence, evidence
```

## 3. 测试矩阵逐格结果（本轮实测）

### 3.1 A 类 · 同轨迹不同参数化（期望等价）

| 用例 | 曲线类型 | 实测 | 归一化 Hausdorff |
|---|---|---|---|
| 参数域平移 `[0,2π]` vs `[−π,π]` | 参数方程 | equivalent | 4.94e-16 |
| 非均匀重参数化（同圆） | 参数方程 | equivalent | 3.71e-03 |
| 密度 300 vs 1000 | 参数方程 | equivalent | 3.70e-03 |
| 起点相位偏移 | 参数方程 | equivalent | 9.39e-04 |
| Bezier 环重采样 | bezier | equivalent | 0.00e+00 |
| Spline 环重采样 | spline | equivalent | 0.00e+00 |

### 3.2 B 类 · 方向反转（期望不等价，方向维触发）

| 用例 | 实测 | relation | 触发维度 |
|---|---|---|---|
| 反向参数域 `[2π,0]` | 非等价 | same_trajectory_reversed | orientation reversed |
| 点列倒序 | 非等价 | same_trajectory_reversed | orientation reversed |

### 3.3 C 类 · 合规真实改变（期望不等价但合规）

| 用例 | 形状 | 相似变换识别 | 说明 |
|---|---|---|---|
| 均匀缩放 ×1.5 | 圆 | 是 | 尺度保持形状 |
| 平移 (3,−2) | 圆 | 是 | 位置改变 |
| 旋转 30° | 非旋转对称豆形环 | 是 | 旋转保持形状 |
| 反射 | 非旋转对称豆形环 | 是 | 反射保持形状 |
| 方形 → 平滑闭合环 | 多边形/样条 | 否 | 拓扑保持（0 自交、闭合、对称保留），形状改变，归 `compliant_other` |

### 3.4 D 类 · 真实几何差异（期望不等价）

| 用例 | 触发维度 |
|---|---|
| 圆 vs 椭圆 | 点集距离 |
| 圆 vs 单侧凸起 | 点集距离 |
| 闭合环 vs 自交蝴蝶结 | 点集距离 + 拓扑（自交 0 vs 1） |
| 闭合圆 vs 开口弧 | 点集距离 + 闭合状态 |
| 单环 vs 两个近接触环 | 点集距离 + 拓扑（自交 0 vs 3，段数差异） |

### 3.5 E 类 · 容差边界

| 用例 | 实测 | 判据 |
|---|---|---|
| 半径扰动 +1e-7（2·tol 带内） | equivalent | 点集距离在带宽内 |
| 半径扰动 +0.35（相对形状带外） | different | 点集距离超带宽 |

### 3.6 F 类 · 曲线类型 × 尺度网格（0.1 与 1000，两个数量级）

| 曲线类型 | 尺度 0.1 | 尺度 1000 |
|---|---|---|
| 参数方程圆 | equivalent（hd_norm 4.45e-16） | equivalent（4.40e-16） |
| Bezier 环 | equivalent（0） | equivalent（0） |
| Spline 环 | equivalent（0） | equivalent（0） |
| 开口弧 | equivalent（0） | equivalent（0） |

### 3.7 对称验证

| 样本 | 期望 | 实测判定 | 中位数 / p90 / 最大残差 |
|---|---|---|---|
| 圆 | symmetric | symmetric | 8.92e-05 / 1.38e-04 / 1.76e-04 |
| 椭圆 | symmetric | near_symmetric | 2.51e-02 / 5.24e-02 / 7.05e-02 |
| 故意单侧凸起（幅度 0.60） | asymmetric | symmetric（**原型漏判，见 §6**） | 6.41e-03 / 2.26e-02 / 2.36e-02 |
| 轻微扰动（幅度 0.05） | near/asymmetric | symmetric | 6.08e-04 / 1.89e-03 / 2.86e-03 |

### 3.8 边界特征分类

| 样本 | 期望 | 实测角色 | 置信度 | 切线夹角 | 侧别 |
|---|---|---|---|---|---|
| 方形角点 | 外凸/尖点 | outward_extrema | 0.80 | 90.0° | +1 |
| 圆上正则点 | regular | regular | 0.70 | 0.4° | 0 |
| 蝴蝶结交叉邻域 | undetermined | undetermined | 0.00 | n/a | 0 |

## 4. 双向误判率（本轮样本集）

| 方向 | 定义 | 结果 |
|---|---|---|
| 误判等价（false equivalent） | 已知不等价/未决样本被判等价 | **0 / 15** |
| 误判不等价（false inequivalent） | 已知等价样本被判非等价 | **0 / 6** |
| 相似变换漏识 | 合规变换未被识别为相似 | **0 / 4** |

> 样本量为原型级小样本，误判率不代表生产分布；对称侧的漏判见 §6。

## 5. 阈值纪律与新增量

**复用既有量**：距离闸门的绝对下限为既有 `connection_tolerance` /
`max_sampling_error` 与 `2·tol` 邻近带；自交判定复用拓扑模块弦跨立结果。

**新增量（明确标注，含风险）**：

| 新增旋钮 | 取值 | 误杀风险 | 漏杀风险 |
|---|---|---|---|
| 相对形状带宽 `rel_point_band` | 0.02（对角线 2%） | 过大把近似不同形状判等价 | 过小拒绝同轨迹重采样 |
| 对称对称/近对称带 `sym_sym / sym_near` | 0.03 / 0.10（径向 p90 相对残差） | 过大放过偏斜形状 | 过小拒绝近似对称 |
| 特征邻域窗口 `window` | 4 采样点 | 过小读噪声为尖点 | 过大平滑真特征 |
| 正则点曲率比阈值 | 曲率比 <1.5 且夹角 <30° | 把平缓凸点判正则 | 把弱特征误判为极值 |

未为任何具体图形自定通过阈值；所有新增旋钮在生产接线前需用更多曲线族校准。

## 6. `undetermined` 触发条件与 C 放行口径

**返回 `undetermined` 的情形**：

1. 规格缺失（无求值器/点列/区间）；
2. 采样不足（<4 点或参数区间退化）；
3. 闭合/端点信息缺失，无法判定闭合状态；
4. 自交邻域内部侧歧义（`crossing_hint` 置位）；
5. 尺度退化或邻弦退化，法向偏移不可算。

**C 线放行口径**：拿到 `undetermined` 时，**不得**记为等价、不得记为成功生成；
按既有 fail-closed 语义升级为 `replan_or_human_review`，由规划器重规划或人工复核。
`undetermined` 与"检测出错误图形"同属非成功生成，不进入 generation 成功统计；
detection outcome 与 generation outcome 继续分栏。

## 7. 建议接入点（供 C 裁决，本轮未接线）

1. **修复前后几何比对**：在一轮修复返回候选后、记入修复进展前，调用
   `trajectory_equivalent(旧快照, 新快照, tol)`；`equivalent=True` 且无拓扑/特征变化
   → 记为"无几何改善"，不消耗有效修复计数；`same_trajectory_reversed` 同理。
2. **合规变换标注**：`similarity_transform` 判为真时，在证据里标注"相似变换，
   形状保持"，避免 M3 把缩放/平移/旋转误判为失败。
3. **特征证据**：`classify_boundary_feature` 的角色/夹角/曲率比/置信度写入候选
   几何证据账本，供结构契约复核。
4. **缺快照退化**：若上游未提供修复前几何快照，等价判定返回 `undetermined`，
   C 不得用计划文本相似度替代几何比对。

## 8. 残余风险与未完成项

1. **对称判别原型偏弱（待验证）**：径向剖面只捕捉全局径向调制，对单侧局部凸起
   漏判（§3.7 故意凸起仍判 symmetric）。生产化需按弧长/参数序做双侧点对应匹配，
   而非最近邻或径向剖面；椭圆主轴角识别到 45° 亦待校正。
2. **误判率样本量小**：6 等价 + 15 非等价 + 4 变换的原型样本，未覆盖开口样条、
   非均匀样条、近切双轮廓等边界；误判率需更大曲线族估计。
3. **参数重映射残差**接口预留未实现；当前等价判定不含保序参数重映射检验。
4. **自交守卫**依赖拓扑模块 `crossing_hint` 输入，原型自身不重复求交；接线时需
   保证拓扑结果先于特征分类可用。
5. 本轮未改生产代码、未调模型、未联网；基线回归见 §9。

## 9. 回归结果（本轮实测）

| 测试组 | 命令 | 结果 |
|---|---|---|
| B 线拓扑 | `pytest tests/test_cad_topology_safety_b1.py b11 b12 -q` | **21 passed** |
| 执行器 + 解释器基线 | `pytest tests/test_cad_construction.py test_cad_construction_interpreter.py -q` | **111 passed**（37 执行器 + 74 解释器） |

合计 B 线 21 + 基线 111 = **132 passed，无回归**；本轮未改生产代码。
