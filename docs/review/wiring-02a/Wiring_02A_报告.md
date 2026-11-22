# Wiring-02A：约束求解失败反馈接线报告

## 1. 结论

- 缺陷存在，且首个丢失节点已通过运行时逐节点追踪定位。
- 已做最小接线修复：只修改 1 个现有生产文件，新增 6 行。
- 求解器已有的残差、容差、全部报告、失败约束和类别，现在能进入第二次修复的模型输入。
- 错误几何仍不被接受，未产生候选；`max_repairs=2` 未修改。
- 定向用例 2 passed；相关既有与新增模块合计 36 passed、4 skipped、0 failed、0 errors。
- 未合并 main，未推送，未启动 Wiring-02B，全程 0 次真实模型调用。

## 2. 基线与环境

| 项目 | 值 |
|---|---|
| 固定基线 | `2939e914c77a07fdd2ba5ce3a122e86cbfafcd1c` |
| 分支 | `fix/wiring-02a` |
| Python | 3.13.18（本地隔离 venv） |
| pytest | 9.2.0 |
| 真实模型调用 | 0 次 |

## 3. 真实调用链与首个丢失节点

使用既有三圆冲突场景：A 圆心 0、B 圆心 10、C 圆心 3，半径均为 1 米，约束 `c-a: C→A`、`c-b: C→B`。

### NODE1 求解器出口（完整）

- `code=constraint_residual_exceeded`
- `category=constraint_unsatisfied`
- `constraint_id=c-a`
- `reports=2` 条
- `failed_constraints=1` 条
- 失败约束：`residual=10000.0`、`tolerance=1.0`、`metric=distance_mm`

### NODE2 执行器异常包装（首个丢失节点）

修复前：`ConstructionPlanError.details = null`，`reports`、`failed_constraints` 全部消失。

定位：`backend/app/cad_construction.py` 的 `except ConstraintSolveError` 只传了 `code/message/constraint_id`，没有使用该类已支持的 `details`。

修复前代码：

```python
except ConstraintSolveError as exc:
    raise ConstructionPlanError(
        exc.code,
        exc.message,
        constraint_id=exc.constraint_id,
    ) from exc
```

### NODE3 解释器

修复前：`status=invalid`，`construction_error` 只剩 `schema/code/message/constraint_id`，无 `details/reports/failed_constraints`。

解释器本身只是透传 `exc.as_dict()`，上游丢失后无法恢复，因此不是修复点。

### NODE4 现有修复循环的模型输入

修复前：真实 `_formal_cad_construction` 运行了 2 次模型输入，但第二次提示词中的“结构化验证证据”只有：

```json
{"schema": "cad.construction-error.v1", "code": "constraint_residual_exceeded", "message": "最终几何未同时满足约束：c-a", "constraint_id": "c-a"}
```

不含 `reports`、`failed_constraints`、`tolerance`、`residual` 数值。提示词中出现的 `tolerance` 只来自计划自身字段，`residual` 只来自错误代码字符串，不能算求解诊断。

**结论：首个丢失节点是 NODE2；必须在该处接线，NODE3/NODE4 无需新增逻辑。**

## 4. 最小修复

文件：`backend/app/cad_construction.py`（唯一生产修改文件）

```diff
@@ -785,10 +785,16 @@ def execute_construction_plan(
             backend=validated.constraint_backend,
         )
     except ConstraintSolveError as exc:
+        diagnostics = {"category": exc.category}
+        if getattr(exc, "reports", None):
+            diagnostics["reports"] = exc.reports
+        if getattr(exc, "failed_constraints", None):
+            diagnostics["failed_constraints"] = exc.failed_constraints
         raise ConstructionPlanError(
             exc.code,
             exc.message,
             constraint_id=exc.constraint_id,
+            details=diagnostics,
         ) from exc
```

Diff：`1 file changed, 6 insertions(+)`。

未新增求解器、诊断器、修复循环或公共接口；未修改判定标准、修复预算和候选接受门禁。

## 5. 修复前后对照

| 节点 | 修复前 | 修复后 |
|---|---|---|
| NODE1 求解器 | 2 条报告、1 条失败约束、residual 10000.0、tolerance 1.0 | 不变 |
| NODE2 执行器 | `details=null` | `details` 含 `category`、2 条 `reports`、1 条 `failed_constraints` |
| NODE3 解释器 | 无 `details` | 原样透传 `details` |
| NODE4 第二次模型输入 | 无 `reports/failed_constraints`，无残差/容差 | 完整包含 `reports`、`failed_constraints`、`residual: 10000.0`、`tolerance: 1.0` |

修复后第二次模型输入中的关键片段：

```json
{"schema": "cad.construction-error.v1", "code": "constraint_residual_exceeded",
 "message": "最终几何未同时满足约束：c-a", "constraint_id": "c-a",
 "details": {"category": "constraint_unsatisfied",
  "reports": [{"constraint_id": "c-a", "kind": "concentric", "target_ref": "C",
   "reference_ref": "A", "verified": false, "residual": 10000.0,
   "tolerance": 1.0, "metric": "distance_mm"}, ...],
  "failed_constraints": [{"constraint_id": "c-a", "kind": "concentric",
   "target_ref": "C", "reference_ref": "A", "verified": false,
   "residual": 10000.0, "tolerance": 1.0, "metric": "distance_mm"}]}}
```

## 6. 定向测试

新增：`backend/tests/test_wiring_02a_constraint_feedback.py`

两个用例：

1. 执行器异常保留既有求解诊断：断言 `category`、2 条 `reports`、1 条 `failed_constraints`，以及 `residual=10000.0`、`tolerance=1.0`、`metric=distance_mm`。
2. 诊断到达第二次模型输入：真实 `_formal_cad_construction` 和修复循环运行，只 mock 模型文本出口，捕获第二轮 `messages[-1]["content"]`；断言反馈段包含 `failed_constraints`、`reports`、`residual`、`tolerance`、`c-a`；同时断言错误几何未落库、`result.ok is False`。

结果：`2 passed`。

## 7. D 独立验证结果

执行模块：

```text
backend/tests/test_cad_constraint_solver.py
backend/tests/test_acceptance_boundaries.py
backend/tests/test_cad_p0_trust_boundary.py
backend/tests/test_wiring_01_repair_gate.py
backend/tests/test_c12_production_loop_mock.py
backend/tests/test_wiring_01_evidence_consumption.py
backend/tests/test_wiring_02a_constraint_feedback.py
```

结果：**36 passed，4 skipped，0 failed，0 errors**。

4 条 skip 均为审查环境未安装原生 `planegcs` / `solvespace`（`tests/test_cad_constraint_solver.py:197` 与 `:251`），与本次 builtin 冲突场景无关。

三项验收：

| 验收项 | 结果 | 证据 |
|---|---|---|
| 真实约束失败诊断进入实际修复输入 | 通过 | 第二轮模型输入包含 2 条报告、1 条失败约束、残差 10000.0、容差 1.0 |
| 正常约束求解不受影响 | 通过 | `test_concentric_and_equal_radius_constraints_are_solved_and_verified` 等既有求解用例通过 |
| 错误几何仍不能通过验收、修复预算不变 | 通过 | 冲突圆心用例通过；服务级失败后无候选；既有修复门用例断言 `max_repairs == 2` 并通过 |

## 8. 限制与未做事项

- 只验证到“实际交给模型的第二轮输入”边界；未调用真实模型，因此不能声称模型一定据此修复成功。
- 未运行冻结的 70 例或 A9。
- 未合并 main、未 push、未启动 Wiring-02B。
- 本地同步清单偏好目标路径在本机不存在，未改写其他同名文件。
- 正式集成仍为 NO-GO，真实模型评测继续冻结。
