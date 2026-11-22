# R1-C 解析与有界求交设计

- 版本：设计稿 v1
- 日期：2026-11-16
- 状态：设计定稿；四项裁定已完成；编码等待物理独立备份门禁
- 适用范围：R1-C / G1-C
- 当前基线：`215f2eafb7f39e36c4230576905b3b403c6d1c4d`

## 1. 结论先行

R1-C 应新增一个独立求交模块，不改造正式 Engine，不修改 `cad_construction.py`，不接入 Translate HTTP 路由。模块只消费已经规范化过的 `Line` 与 `CubicBezier`，对 `GenericSpline`、`UnknownCurve` 和退化输入一律拒绝或返回 `indeterminate`。

推荐模块：

- 新增 `app/curve_intersections.py`
- 新增 `tests/test_curve_intersections.py`
- `app/agent_skills.py` 在 R1-C 默认不改；是否在 `analyze_geometry_topology` 增加 `curve_intersections` 加法字段，留到 R1-D 做兼容性审查后再决定

理由：

1. R1-C 的核心是算法可信度，不是生产路由；
2. 独立模块可以先由 G1-C 定向测试证明，不牵动旧拓扑统计；
3. 后续 O7 安全复查可以显式调用，不会让现有拓扑分析自动承担阻断职责；
4. `GenericSpline` 与 `UnknownCurve` 的边界可以保持在类型规范化层，不必在求交层重复猜测。

## 2. 只读证据

### 2.1 现有类型边界

`app/cad_topology_types.py` 已提供：

- `TOPOLOGY_LINE = "Line"`
- `TOPOLOGY_CUBIC_BEZIER = "CubicBezier"`
- `TOPOLOGY_GENERIC_SPLINE = "GenericSpline"`
- `TOPOLOGY_UNKNOWN_CURVE = "UnknownCurve"`
- `normalize_curve_geometry()` / `normalize_curve_types()`
- `CUBIC_BEZIER_PARAMETER_DOMAIN = (0.0, 1.0)`

`CubicBezier` 的已确认语义：

- 恰好 4 个有序控制点；
- degree = 3；
- basis = `bernstein`；
- 参数域 `[0.0, 1.0]`；
- 定义式 `B(t) = (1-t)^3 P0 + 3(1-t)^2 t P1 + 3(1-t)t^2 P2 + t^3 P3`。

### 2.2 现有采样边界

`app/drawing_store.py` 已有：

- `_sample_cubic_bezier()`：固定 `CURVE_SAMPLES + 1` 点；
- `_geometry_points()` 支持 `cubic_bezier` / `cubic-bezier` / `cubicbezier`；
- 该采样只用于预览与拓扑路径，不是求交证据。

R1-C 不得把该采样结果直接升级为最终求交结论。采样只能用于：

- 候选包围盒预筛；
- 自适应细分前的粗略定位；
- 诊断可视化。

### 2.3 现有拓扑求交边界

`app/agent_skills.py` 的旧 `analyze_geometry_topology`：

- 用固定采样线的两两线段相交统计 `self_intersection_count`；
- 旧字段语义保持不变；
- 不能把旧字段当成解析求交或 P2.0 安全放行证据。

`app/agent_skills.py` 已有 `_segments_intersect()` / `_intersection_key()`，但它们是线段级辅助函数，不处理：

- 共线重叠；
- 退化线段；
- Bezier 相切重根；
- Bezier-Bezier 自适应收敛；
- 自交参数区间；
- 误差界与 `indeterminate`。

## 3. 设计目标

### 3.1 必须做到

- Line-Line 解析求交，区分普通交叉、平行、共线、端点接触、重叠、退化。
- Line-CubicBezier 用三次多项式求根，能识别相切重根，不只依赖符号变化。
- CubicBezier-CubicBezier 用有界自适应细分、保守包围盒和交点验证。
- CubicBezier 自交检测，区分相邻参数段、非相邻真实交叉、重复控制点、完全折返。
- 所有结果带方法、几何身份、参数位置、收敛状态、误差界。
- 无法可靠判定时返回 `indeterminate`，不得当作安全通过。
- `GenericSpline` / `UnknownCurve` 不进入 CubicBezier 求交。

### 3.2 明确不做

- 不修改正式 Engine。
- 不修改 `app/cad_construction.py`。
- 不写入生产 `extension_of`。
- 不接入 Translate HTTP 路由。
- 不修改 P1.9 Gold、`cad/main`。
- 不改变旧拓扑统计字段语义。
- 不把固定采样结果直接当安全放行。
- 不因控制点恰好为 4 个就把 legacy spline 升级为 CubicBezier。

## 4. 模块与接口

### 4.1 公共函数

```python
def analyze_curve_intersections(
    geometries: list[dict],
    *,
    curve_types: list[dict] | None = None,
    tolerance_mm: float = 1e-9,
    parameter_tolerance: float = 1e-9,
    max_depth: int = 32,
    max_nodes: int = 8192,
) -> dict:
    ...
```

行为：

- 若未传 `curve_types`，内部调用 `normalize_curve_types(geometries)`；
- 只对 `Line` 与 `CubicBezier` 建对；
- `GenericSpline`、`UnknownCurve` 不建对，记录为 `unsupported` / `fail_closed`；
- 曲线身份按 `geometry_id` 保留；缺失 ID 时保留 `input_index`；
- 返回值是独立诊断结果，不设置旧 `ok`，不替代 `analyze_geometry_topology`。

### 4.2 返回契约

```json
{
  "schema": "cad.curve-intersections.v1",
  "status": "clear | intersection | overlap | indeterminate",
  "tolerance_mm": 1e-9,
  "status_counts": {
    "clear": 0,
    "intersection": 0,
    "overlap": 0,
    "indeterminate": 0
  },
  "unsupported_geometry_ids": [],
  "fail_closed_geometry_ids": [],
  "pairs": [
    {
      "pair_id": "p1",
      "geometry_ids": [1, 2],
      "left_type": "Line",
      "right_type": "CubicBezier",
      "self_intersection": false,
      "status": "intersection",
      "method": "cubic_polynomial_roots",
      "parameters": [
        {
          "left_t": 0.5,
          "right_t": 0.5
        }
      ],
      "points": [
        {
          "x_mm": 500.0,
          "y_mm": 750.0,
          "kind": "crossing"
        }
      ],
      "converged": true,
      "iteration_count": 3,
      "error_bound_mm": 1.2e-10,
      "reason": null,
      "overlap": null,
      "issues": []
    }
  ],
  "issues": []
}
```

### 4.3 统一结果字段

| 字段 | 含义 |
|---|---|
| `status` | `clear` / `intersection` / `overlap` / `indeterminate` |
| `geometry_ids` | 参与检测的几何身份；自交时为同一 ID 的左右两侧 |
| `method` | 实际检测方法，不允许用采样方法冒充解析/有界方法 |
| `parameters` | 曲线参数位置；自交时包含 `left_t` 与 `right_t` |
| `points` | 交点坐标与类型；`kind` 只能是 `crossing` / `tangent` / `endpoint` |
| `converged` | 是否在误差界内完成判定 |
| `error_bound_mm` | 数值误差界；未收敛时也必须有值 |
| `reason` | `indeterminate` 的原因；`clear` / `intersection` / `overlap` 时为 `null` |

`indeterminate` 必须在 `reason` 或 `issues` 中给出可审计原因，调用方不得把它解释成 `clear`。

建议 `reason` 代码：

- `degenerate_line`
- `degenerate_curve`
- `non_finite_coordinate`
- `numerical_limit`
- `unresolved_tangency`
- `unsupported_curve_type`
- `incomplete_provenance`
- `sampling_only_candidate`

### 4.4 状态语义

| 状态 | 含义 | 是否允许安全通过 |
|---|---|---|
| `clear` | 检测完成，没有发现冲突 | 仅表示本模块未发现冲突，不单独构成 P2.0 放行 |
| `intersection` | 检测到交点 | 否 |
| `overlap` | 检测到重叠 | 否 |
| `indeterminate` | 无法可靠判定 | 否，必须 fail-closed |

聚合规则：

1. 任一 pair 为 `indeterminate`，顶层为 `indeterminate`；
2. 否则任一 pair 为 `overlap`，顶层为 `overlap`；
3. 否则任一 pair 为 `intersection`，顶层为 `intersection`；
4. 全部为 `clear` 且没有 unsupported/fail-closed 项，顶层为 `clear`。

不要把 `clear` 写成 `ok=true`。本模块不拥有最终安全放行权。

## 5. 数值政策

### 5.1 单位与容差

| 参数 | 建议值 | 用途 |
|---|---:|---|
| `tolerance_mm` | `1e-9` | 求交数值残差目标；不是 Junction 判据 |
| `JUNCTION_TOLERANCE_MM` | `1e-6` | 由图级 Junction 层使用；R1-C 求交不使用，不得把近失升级为交点 |
| `ZERO_DISPLACEMENT_MM` | `1e-9` | 沿用现有编辑守卫，独立用途；不参与求交 |
| `PARAM_TOLERANCE` | `1e-9` | 无量纲参数去重、端点判定；不使用 mm 容差 |
| `TANGENT_ANGLE_EPS` | `1e-9` | 无量纲切向夹角判据；用于相切分类 |
| `DEGENERATE_LENGTH_MM` | `1e-9` | 线段/曲线零长度判定 |
| `MIN_SELF_PARAM_GAP` | `1e-6` | 自交检测排除相邻参数段；无量纲 |
| `MAX_BEZIER_DEPTH` | `32` | 自适应细分上限 |
| `MAX_BEZIER_NODES` | `8192` | 自适应节点上限 |
| `LEAF_SIZE_MM` | `1e-3` | 自适应搜索叶尺寸；不是最终容差，叶子内仍需最近点/牛顿精化 |
| `MAX_ROOT_ITERATIONS` | `20` | 多项式根/牛顿迭代上限 |

容差分工必须固定：

- `1e-9 mm` 是求交残差目标，不是 Junction 成立条件；
- `1e-6 mm` 只用于端点接缝，不能作为曲线求交的宽松放行条件；
- 参数误差使用无量纲 `PARAM_TOLERANCE`，不能直接拿 `1e-9 mm` 当参数容差；
- 大坐标下先做局部坐标归一化：减去包围盒中心，按最大尺度缩放，在局部坐标中求交，再把点和误差界映射回 mm；
- 归一化后的误差界必须乘以尺度因子，不能把局部坐标误差直接当成全局 mm 误差。

R1-C 的 `endpoint` 只表示实际点重合误差在 `tolerance_mm` 内；`JUNCTION_TOLERANCE_MM=1e-6` 的接缝成立由图级 Junction 层判断，不能在本模块把 1e-6 近失写成 `intersection`。若调用方需要接缝语义，应分别读取 Junction 结果与本模块求交结果，不能互相替代。

### 5.2 误差界

每个 pair 必须记录 `error_bound_mm`：

- Line-Line：解析计算，记录浮点残差；通常为 `0.0` 或 `<= 1e-12`。
- Line-Cubic：记录根区间宽度乘以保守速度上界，再加点残差。
- Cubic-Cubic：已完成精化的交点记录精化后的参数区间宽度乘以速度上界，再加点残差；未完成精化的分支才记录叶子包围盒对角线的一半，并直接进入 `indeterminate`。
- 自交：同 Cubic-Cubic，并额外记录两个参数区间的隔离宽度。

若 `error_bound_mm > tolerance_mm`，不得返回 `clear`；应返回 `intersection`（如果已确认交点）或 `indeterminate`。

### 5.3 收敛

`converged` 只在以下条件为真：

- 所有分支都完成了包围盒排除、叶子验证或根验证；
- 没有触发 `MAX_BEZIER_DEPTH` / `MAX_BEZIER_NODES` / `MAX_ROOT_ITERATIONS`；
- 所有候选交点的残差 `<= tolerance_mm`。

任一条件不满足，`converged=false`，状态必须是 `indeterminate`，除非已有独立、可验证的 `overlap` 结论。

## 6. Line-Line 解析求交

### 6.1 输入校验

- 任一线段长度为 `<= DEGENERATE_LENGTH_MM`：`indeterminate`，`issues=["degenerate_line"]`。
- 非有限坐标：`indeterminate`，`issues=["non_finite_coordinate"]`。

### 6.2 算法

设 `L1 = A + t r`，`L2 = C + u s`，`r = B-A`，`s = D-C`。

- `denom = cross(r, s)`；
- 若 `|denom| <= eps_parallel * |r| * |s|`：
  - 计算 `C` 到 `L1` 支撑线的距离 `dist = |cross(C-A, r)| / |r|`；
  - 若 `dist > tolerance_mm`：平行不共线，`clear`；
  - 否则共线，投影到 `r` 上求两个线段的参数区间交集：
    - 交集物理长度 `> tolerance_mm`：`overlap`；
    - 交集物理长度为单点：`intersection`，`kind="endpoint"`；
    - 无交集：`clear`。
- 否则：
  - `t = cross(C-A, s) / denom`；
  - `u = cross(C-A, r) / denom`；
  - 若 `t`、`u` 均在 `[0,1]` 容差内：`intersection`；
  - 若其中一个参数刚好在端点容差内，`kind="endpoint"`；
  - 否则 `clear`。

### 6.3 端点接触与重叠的区别

- 端点接触：两个线段只有一个公共点，`status="intersection"`，`kind="endpoint"`。
- 共线重叠：交集是一个非零长度区间，`status="overlap"`，必须返回重叠区间。
- 不允许把共线重叠误判为“无交点”。

### 6.4 近平行保护

当 `|denom|` 接近 0 但又不完全为 0 时：

- 若参数解在 `[0,1]` 外且距离大于容差：`clear`；
- 若解在端点附近但方向条件数过高：`indeterminate`，`issues=["near_parallel_ambiguous"]`；
- 不得用四舍五入网格判断平行或重叠。

## 7. Line-CubicBezier 多项式求根

### 7.1 多项式构造

设线段 `P + s d`，`d = Q - P`。Cubic Bezier 的幂基形式：

```text
B(t) = a t^3 + b t^2 + c t + d0

a  = -P0 + 3P1 - 3P2 + P3
b  =  3P0 - 6P1 + 3P2
c  = -3P0 + 3P1
d0 =  P0
```

线段的隐式方程使用归一化有符号距离：

```text
f(t) = cross(d, B(t) - P) / |d| = 0
```

这样 `|f(t)|` 的单位是 mm，才能直接与 `tolerance_mm` 比较。得到三次标量多项式 `A t^3 + B t^2 + C t + D / |d|`。

### 7.2 根候选

1. 用三次多项式求根得到实根候选；
2. 额外加入导数 `f'(t)` 的实根，用于捕获相切重根；
3. 额外加入区间端点 `t=0`、`t=1`；
4. 过滤 `|imag|` 超过相对阈值的复根；
5. 只保留 `t` 在 `[0,1]` 容差内的候选；
6. 用牛顿法或有界二分法做局部精化，记录根的区间宽度。

### 7.3 相切重根

相切对应 `f(t)=0` 且 `f'(t)=0`，可能是二重根。不能只靠 `f` 的符号变化寻找根。

判定：

- 若 `|f(t)| <= tolerance_mm` 且 `|f'(t)| <= TANGENT_ANGLE_EPS * |B'(t)|`：`kind="tangent"`；
- 若根附近 `f` 不变号，但导数根处 `|f| <= tolerance_mm`：也按 `tangent` 处理；
- 若无法区分“相切”与“近失”，返回 `indeterminate`，不得返回 `clear`。

### 7.4 点与线段验证

对每个根：

- 计算 `B(t)`；
- 计算线段投影参数 `s = dot(B(t)-P, d) / dot(d,d)`；
- 若 `s` 不在 `[0,1]` 容差内，丢弃；
- 计算点到线段距离；若 `> tolerance_mm`，丢弃；
- 以 `t` 和点坐标双重去重。

### 7.5 重叠

若多项式系数全部接近 0（按尺度归一化后），说明整条曲线落在直线支撑线上：

- 若曲线在线段范围内有非零长度：`overlap`；
- 若只接触一个端点：`intersection`，`kind="endpoint"`；
- 若不在线段范围内：`clear`。

### 7.6 无根但近失

若没有根，但 `f` 在导数临界点或区间端点的最小绝对值 `<= tolerance_mm`：

- 投影在线段内：`indeterminate` 或 `tangent`，取决于能否证明重根；
- 投影在线段外：`clear`；
- 不允许在近失情况下直接返回 `clear` 而不记录误差界。

## 8. CubicBezier-CubicBezier 有界自适应

### 8.1 表示

每条曲线保存：

- 4 个控制点；
- 参数区间 `[t0, t1]`；
- 控制点包围盒；
- 控制多边形最大边长；
- 细分深度与节点 ID。

### 8.2 包围盒排除

- 包围盒由 4 个控制点直接取 min/max，外扩 `tolerance_mm`；
- 若两个包围盒不相交：该分支 `clear`；
- 包围盒是保守的：控制点凸包包含曲线，不能漏掉真实交点。

### 8.3 细分

- 在 `t=0.5` 用 de Casteljau 一分为二；
- 两个子曲线都保留 `[t0, t1]` 参数映射；
- 递归处理所有包围盒相交的分支；
- 节点数超过 `max_nodes` 或深度超过 `max_depth`：`indeterminate`，`issues=["numerical_limit"]`。

### 8.4 叶子判定

当两个包围盒的最大对角线 `<= LEAF_SIZE_MM`（默认 `1e-3 mm`）时停止细分。`LEAF_SIZE_MM` 只是搜索截止尺寸，不是最终精度；叶子内必须继续做以下精化：

1. 先用两条弦做线段求交，得到候选参数；
2. 用候选参数在两条曲线上做点验证；
3. 若残差 `<= tolerance_mm`：`intersection`；
4. 若弦不相交，但包围盒重叠：
   - 求两条子曲线之间的最小距离；
   - 若最小距离 `<= tolerance_mm`：`tangent` 或 `intersection`；
   - 若最小距离下界 `> tolerance_mm`：`clear`；
   - 若下界与上界跨越容差：`indeterminate`；
5. 若叶子内最近点求解不收敛，继续细分；达到上限仍不收敛则 `indeterminate`。

不能把“叶子尺寸大于 `tolerance_mm`”直接当成失败；叶子内的最近点/牛顿精化负责把误差压到 `tolerance_mm` 以内。若精化后 `error_bound_mm > tolerance_mm`，仍须 `indeterminate`。

### 8.5 相切

相切时两条曲线在交点处可能没有弦交叉。叶子必须做“最小距离 + 参数验证”，不能只做弦相交。

候选点确认后，还要计算两条曲线在该参数处的切向量 `T1`、`T2`：

- `|cross(T1, T2)| / (|T1| * |T2|) <= TANGENT_ANGLE_EPS` 且局部只有一个接触点：`kind="tangent"`；
- 上式明显大于 `TANGENT_ANGLE_EPS`：`kind="crossing"`；
- 切向量为零或无法稳定计算：`indeterminate`。

若最小距离求解的雅可比矩阵奇异：

- 退化为局部密集采样；
- 若仍不能把残差压到容差内：`indeterminate`，`issues=["unresolved_tangency"]`；
- 不得把“弦没有交点”直接当成 `clear`。

### 8.6 重叠

局部重叠采用分级证明，不允许用有限采样一致直接判 `overlap`。

| 证据 | 结果 |
|---|---|
| 控制点或多项式系数证明完全相同 | `overlap` |
| De Casteljau 子曲线关系验证通过 | `overlap` |
| 反向参数对应关系可证明 | `overlap` |
| 多参数采样一致，但无法证明 | `indeterminate` |
| 明确存在交点 | `intersection` |
| 可靠证明没有交点 | `clear` |
| 超过计算上限 | `indeterminate` |

实现要求：

- “多参数采样一致”只能作为候选发现方法，不能作为重叠成立的证明；
- 两条不同曲线可能在有限采样点上重合，但中间仍然偏离；
- 局部重叠必须返回重叠参数区间；不能只返回一个交点；
- 暂不支持证明的复杂局部重叠，保持 `indeterminate`，不得强行给出 `overlap`。

### 8.7 去重

交点按以下键去重：

- 空间距离 `<= tolerance_mm`；
- 或参数对 `(t_left, t_right)` 的曼哈顿距离 `<= PARAM_TOLERANCE`。

多交点必须全部保留；不能因为包围盒递归而重复计数。

## 9. CubicBezier 自交

### 9.1 目标

同一条曲线的两个不同参数位置映射到同一个点时，判定为自交。必须区分：

- 相邻参数段共享端点：不是自交；
- 非相邻参数段真实交叉：自交；
- 重复控制点导致的端点退化：按退化规则处理；
- 曲线完全折返或重合：`overlap`，不是单点自交。

### 9.2 算法

推荐用“参数区间自适应”而不是固定采样：

1. 将 `[0,1]` 递归细分；
2. 只比较参数区间不重叠、且间隔大于 `MIN_SELF_PARAM_GAP` 的两个子曲线；
3. 对每对子曲线复用 Cubic-Cubic 的包围盒与叶子验证；
4. 交点参数必须满足 `|t1-t2| > MIN_SELF_PARAM_GAP`；
5. 同一参数附近的候选去重；
6. 达到深度/节点上限时返回 `indeterminate`。

### 9.3 相邻段排除

- 两个子区间共享端点且没有非零长度重叠：忽略共享端点；
- 若参数区间有非零交集：不是自交，交给重叠检测；
- 若 `|t1-t2| <= MIN_SELF_PARAM_GAP`：不认定为自交，记录为相邻段。

### 9.4 重复控制点与折返

- 全部控制点重合：`indeterminate`，`issues=["degenerate_curve"]`；
- 端点重复但内部导数非零：不自动判自交；
- 内部参数导数同时为 0（尖点）：若无法证明不是自交，`indeterminate`，`issues=["zero_derivative_cusp"]`；
- 曲线沿同一路径折返：`overlap`，返回参数区间；
- 完全折返且参数区间无法隔离：`indeterminate`。

### 9.5 自交输出

自交 pair 使用同一个 `geometry_id` 的左右两侧：

```json
{
  "geometry_ids": [7, 7],
  "self_intersection": true,
  "method": "bounded_adaptive_bezier",
  "parameters": [
    {
      "left_t": 0.11270167,
      "right_t": 0.88729833
    }
  ],
  "points": [
    {
      "x_mm": 250.0,
      "y_mm": 300.0,
      "kind": "crossing"
    }
  ],
  "converged": true,
  "error_bound_mm": 1.2e-10,
  "reason": null
}
```

## 10. 类型与 fail-closed 边界

### 10.1 只接受两类

- `Line`
- `CubicBezier`

### 10.2 不接受

- `GenericSpline`：`unsupported_geometry_ids`，不建对，顶层 `indeterminate`；
- `UnknownCurve`：`fail_closed_geometry_ids`，不建对，顶层 `indeterminate`；
- 缺 `geometry_id` 的曲线：保留 `input_index`，但不得伪造 ID；
- 控制点数量不是 4、degree 不是 3、basis 不是 bernstein、参数域不是 `[0,1]`：拒绝。

### 10.3 不允许的“自动升级”

- 4 个控制点 + degree=3 但没有 cubic provenance：不进入 CubicBezier 求交；
- `curve_kind="cubic_bezier"` 但 basis/domain 缺失：`UnknownCurve`，fail-closed；
- 旧 `spline` 的固定采样路径：不能作为 Bezier 求交输入；
- 任何“看起来像 Bezier”的启发式都不得绕过类型规范化。

## 11. 与现有拓扑的关系

### 11.1 R1-C 默认不改 `agent_skills.py`

原因：

- 保持旧统计字段与旧 `ok` 语义完全不变；
- 避免每次 `analyze_geometry_topology` 都承担 O(n²) 求交成本；
- 让 G1-C 先证明算法本身；
- 后续 O7 可以显式调用独立模块。

### 11.2 后续加法接入建议

R1-D 或 Translate 安全复查阶段再考虑：

```python
result["curve_intersections"] = analyze_curve_intersections(
    geometries,
    curve_types=curve_types,
)
```

该字段必须是加法字段，不参与旧 `ok` 计算；如果接入，必须有独立的兼容性测试。

## 12. 实施顺序

1. 数据校验、状态与误差界骨架；
2. Line-Line 解析求交；
3. Line-Cubic 多项式求根与相切重根；
4. Cubic-Cubic 包围盒自适应；
5. Cubic 自交参数区间；
6. 类型边界与 fail-closed；
7. 测试矩阵与全量回归。

建议单个 R1-C 提交，包含：

- `app/curve_intersections.py`
- `tests/test_curve_intersections.py`

不修改：

- `app/cad_construction.py`
- `app/tooling.py`（除非测试夹具复用已有 `CadCubicBezier`，不需要改）
- `app/drawing_store.py`
- `app/agent_skills.py`（默认不接入）

## 13. G1-C 测试矩阵

### 13.1 必测 C-01～C-12

| 编号 | 测试 | 夹具 | 期望 |
|---|---|---|---|
| C-01 | Line-Line 普通交叉 | `L1=(0,0)-(1000,1000)`，`L2=(0,1000)-(1000,0)` | `intersection`，点 `(500,500)`，`t=u=0.5`，`kind=crossing` |
| C-02 | Line-Line 共线重叠 | `L1=(0,0)-(1000,0)`，`L2=(500,0)-(1500,0)`；另测端点接触 `L3=(1000,0)-(2000,0)` | 重叠为 `overlap`，区间 `[500,1000]`；端点接触为 `intersection`，`kind=endpoint` |
| C-03 | Line-Cubic 穿越 | Cubic `P0=(0,0), P1=(300,1000), P2=(700,1000), P3=(1000,0)`；`L: x=500, y=0..1000` | `intersection`，点 `(500,750)`，`t=0.5`，`kind=crossing` |
| C-04 | Line-Cubic 单点相切 | Cubic `P0=(-1000,0), P1=(-500,1000), P2=(500,1000), P3=(1000,0)`；`L: y=750, x=-1000..1000` | `intersection`，点 `(0,750)`，`t=0.5`，`kind=tangent`；只允许一个解 |
| C-05 | Cubic-Cubic 多交点 | C1 同 C-04；C2 `P0=(-1000,500), P1=(-333,500), P2=(333,500), P3=(1000,500)` | `intersection`，2 点：`(-625.462791622,500)`、`(625.462791622,500)`，参数约 `0.2113248654`、`0.7886751346` |
| C-06 | Cubic-Cubic 相切 | C1 同 C-04；C2 `P0=(-1000,750), P1=(-333,750), P2=(333,750), P3=(1000,750)` | `intersection`，点 `(0,750)`，`kind=tangent`；不得返回 0 交点或 `clear` |
| C-07 | Cubic 自交 | `P0=(0,0), P1=(1000,1000), P2=(-500,1000), P3=(500,0)` | 自交 `intersection`，点 `(250,300)`，参数约 `0.11270167`、`0.88729833` |
| C-08 | 近距离但不相交 | C1 同 C-04；`L: y=750.000001` | `clear`，最小距离约 `1e-6 mm`，不得判相切 |
| C-09 | 退化曲线/退化线段 | Cubic 四点全部 `(0,0)`；另测零长度 Line `(5,5)-(5,5)` | 两者均 `indeterminate`，`issues` 分别含 `degenerate_curve` / `degenerate_line` |
| C-10 | 算法达到上限 | C1/C2 同 C-05，调用时 `max_depth=1`、`max_nodes=8` | `indeterminate`，`issues` 含 `numerical_limit`，`converged=false` |
| C-11 | GenericSpline 不误送 | `type=spline`、4 CP、degree=3、无 provenance；另加一条 Line | 顶层 `indeterminate`，`unsupported_geometry_ids` 含该 spline；不得出现 `cubic_polynomial_roots` 对该 spline 的 pair |
| C-12 | 不可信 provenance 不升级 | `type=spline`、4 CP、degree=3、`curve_kind=cubic_bezier`，缺 basis/domain | 顶层 `indeterminate`，`fail_closed_geometry_ids` 含该几何；不得进入 Cubic 求交 |

### 13.2 补充测试 C-13～C-14

| 编号 | 测试 | 夹具 | 期望 |
|---|---|---|---|
| C-13 | Cubic-Cubic 局部重叠 | C1 同 C-04；C2 为 C1 前半段子曲线 `P0=(-1000,0), P1=(-750,500), P2=(-375,750), P3=(0,750)` | `overlap`，返回非零参数区间；不得只报一个交点 |
| C-14 | 完全折返/重复控制点 | 退化折返曲线，例如 `P0=(0,0), P1=(1000,0), P2=(0,0), P3=(1000,0)` | 若可证明重合返回 `overlap`；否则 `indeterminate`；不得返回 `clear` |

### 13.3 断言要求

每个测试至少断言：

- 顶层 `status`；
- 对应 pair 的 `status`；
- `geometry_ids` 未被替换；
- `method` 与实际算法一致；
- `parameters` 与 `points` 数量一致；
- `converged`；
- `error_bound_mm <= tolerance_mm`（`clear` 与已确认交点）；
- `indeterminate` 必须带 `reason`，且不被当作 `clear`。

重点断言：

- C-04：只允许一个交点，`kind="tangent"`；返回 `clear` 或重复两个交点均失败。
- C-06：必须返回相切交点；因弦不相交而返回 `clear` 失败。
- C-10：`status="indeterminate"`、`converged=false`、`reason` 含 `numerical_limit`；不得返回 `intersection` 或 `clear`。
- C-13：必须由精确子曲线关系证明 `overlap`；仅凭采样一致得出 `overlap` 失败。
- C-14：仅在能证明重合时返回 `overlap`；否则必须 `indeterminate`，不得 `clear`。
- C-11/C-12：不得出现进入 CubicBezier 求交的 pair；不得调用 `cubic_polynomial_roots` 处理 GenericSpline 或 UnknownCurve。
- 所有用例：固定采样漏检后返回 `clear` 失败；非收敛结果通过安全检查失败；有限采样一致直接返回 `overlap` 失败。

C-04、C-06、C-10 必须单独断言，不能用普通交叉测试替代。

## 14. G1-C 验收命令

```text
.venv\Scripts\python.exe -m pytest tests\test_curve_intersections.py -q
.venv\Scripts\python.exe -m pytest tests\test_geometry_topology_graph.py tests\test_geometry_topology_types.py tests\test_cad_import.py tests\test_cad_path_relation_acceptance.py tests\test_logical_topology.py -q
.venv\Scripts\python.exe -m pytest -q --tb=no -rf
```

预期：

- 新增 14 个用例（C-01～C-14）；
- 拓扑相关基线 69 保持；
- 全量基线 1700 + 14 = 1714（最终以实际收集数为准）；
- 旧 `analyze_geometry_topology` 的旧字段不变；
- 工作树干净；
- 独立提交、独立 Bundle、`git bundle verify` OK；
- 外部物理介质备份门禁完成，或用户明确提供新的书面授权；本设计默认不豁免。

## 15. 风险与限制

1. 三次多项式求根在极端尺度下可能出现病态；必须用残差验证和误差界，不能只信根。
2. Cubic-Cubic 自适应最坏情况节点数增长快；必须设上限，并在上限处 fail-closed。
3. 相切与近失的区分依赖容差；默认 `1e-9 mm` 是数值容差，不是施工容差。
4. 局部重叠的通用判定很难；R1-C 只把“完全相同/精确子曲线/可证明反向对应”作为 `overlap` 证据；多参数采样一致只能作为候选，无法证明时返回 `indeterminate`。
5. 自交的尖点/折返情形可能无法在有限深度内证明；按 `indeterminate` 处理。
6. 本模块不是 P2.0 最终安全放行器；它只提供可信的几何证据。
7. `AddBezierStep` 的生产 provenance 问题仍未解决；R1-C 只能用显式 `CadCubicBezier` 夹具测试，不能宣称现有构造已生产级支持 CubicBezier。

## 16. 四项设计裁定

以下裁定已生效，不再作为待确认项：

| 编号 | 裁定 | 设计落点 |
|---|---|---|
| 1 | 求交残差目标 `1e-9 mm`；`1e-6 mm` 只用于 Junction；参数误差无量纲 | 第 5.1 节容差表与局部坐标归一化 |
| 2 | R1-C 保持独立 API，不默认改 `agent_skills.py` | 第 4 节接口与第 11 节接入边界 |
| 3 | Cubic 重叠分级证明；采样一致只能作为候选 | 第 8.6 节重叠证据表 |
| 4 | 物理独立备份不豁免 | 第 17 节实施门禁 |

## 17. 实施门禁

R1-C 生产代码修改前，必须完成：

1. 接入一块可写外部物理介质；
2. 将 `r1-b-g1-b.bundle` 复制到该介质；
3. 核对 SHA256 为 `96A05339A43382690519E163899C4AFADD1FB1EB6EB2A777D84E691BAC980A92`；
4. 在外部介质上执行 `git bundle verify`；
5. 确认 3 refs 与 complete history；
6. 同时备份 R1-A Bundle，并核对 SHA256；
7. 记录外部介质标识、复制时间、校验结果。

在上述门禁完成前，允许继续：

- 只读设计；
- 算法推演；
- 测试矩阵整理；
- 夹具数值核算。

不允许：

- 修改 `app/curve_intersections.py` 或其他生产代码；
- 新增 R1-C 提交；
- 生成 R1-C Bundle；
- 声称 R1-C 已开始实施。

本设计稿不改变备份挂账状态。
