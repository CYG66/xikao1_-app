"""Bounded arithmetic expressions and adaptive sampling; never executes code."""
from __future__ import annotations

import ast
import math
import operator
import re


class ParametricError(ValueError):
    pass


_FUNCTIONS = {name: getattr(math, name) for name in (
    "sin", "cos", "tan", "sqrt", "exp", "log", "sinh", "cosh", "atan", "asin", "acos",
)}
_FUNCTIONS["abs"] = abs
_FUNCTIONS["atan2"] = math.atan2
_BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.Pow: operator.pow}


def expression(source: str):
    """Validate once, evaluate only whitelisted AST nodes with finite bounds."""
    if len(source) > 512:
        raise ParametricError("表达式超过512字符")
    try:
        tree = ast.parse(source, mode="eval")
    except (SyntaxError, RecursionError) as exc:
        raise ParametricError("表达式语法无效") from exc
    if len(list(ast.walk(tree))) > 128:
        raise ParametricError("表达式过于复杂")

    def validate(node, depth=0):
        if depth > 24:
            raise ParametricError("表达式嵌套过深")
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            if abs(node.value) > 1e12 or not math.isfinite(node.value):
                raise ParametricError("常数超出范围")
        elif isinstance(node, ast.Name):
            if node.id not in {"t", "pi", "e"}:
                raise ParametricError(f"未定义变量：{node.id}；仅允许t、pi、e，其余参数必须按需求展开为数值")
        elif isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            validate(node.left, depth+1); validate(node.right, depth+1)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            validate(node.operand, depth+1)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id in _FUNCTIONS and len(node.args) == (2 if node.func.id == "atan2" else 1) and not node.keywords):
            for arg in node.args:
                validate(arg, depth+1)
        else:
            raise ParametricError("表达式包含未允许的语法或函数")
    validate(tree.body)

    def evaluate(t):
        def visit(node):
            if isinstance(node, ast.Constant):
                value = node.value
            elif isinstance(node, ast.Name):
                value = {"t": t, "pi": math.pi, "e": math.e}[node.id]
            elif isinstance(node, ast.UnaryOp):
                value = visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
            elif isinstance(node, ast.Call):
                value = _FUNCTIONS[node.func.id](*(visit(arg) for arg in node.args))
            else:
                left, right = visit(node.left), visit(node.right)
                if isinstance(node.op, ast.Pow) and abs(right) > 16:
                    raise ParametricError("指数绝对值不能超过16")
                value = _BINARY[type(node.op)](left, right)
            if isinstance(value, complex) or not math.isfinite(value) or abs(value) > 1e12:
                raise ParametricError("表达式结果非有限实数或超出范围")
            return float(value)
        try:
            return visit(tree.body)
        except (ArithmeticError, ValueError) as exc:
            raise ParametricError(str(exc)) from exc
    return evaluate


def construction_expression_errors(plan):
    """Collect syntax failures together; never evaluate or repair expressions."""
    errors=[]
    for index,step in enumerate((plan.get('steps') or [])[:100]):
        if not isinstance(step,dict) or step.get('op')!='add_parametric_curve':
            continue
        for field in ('x_expression','y_expression','t_start','t_end'):
            source=step.get(field)
            if not isinstance(source,str):
                continue  # Schema validation reports missing/non-string fields.
            try:
                expression(source)
            except ParametricError as exc:
                errors.append({'path':['plan','steps',index,field],
                    'output_ref':step.get('output_ref'),'input':source,'message':str(exc)})
    return errors


def sample_curve(x_source, y_source, start, end, tolerance, max_points=500):
    """Quarter-point chord checks with a fixed initial grid and bounded work.

    Error is an observed estimate, not a proof for arbitrary analytic functions.
    Unresolved intervals fail closed instead of silently reducing accuracy.
    """
    x, y = expression(x_source), expression(y_source)
    def point(t):
        p = (x(t), y(t))
        if max(map(abs, p)) > 100000:
            raise ParametricError("曲线坐标超出范围")
        return p
    points = [point(start)]
    worst = 0.0
    evaluations = 0
    def split(a, b, pa, pb, depth=0):
        nonlocal worst, evaluations
        evaluations += 5
        if evaluations > 16000 or depth > 16 or len(points) >= max_points:
            raise ParametricError("曲线在采样预算内无法达到误差要求")
        errors = []
        # Include nonuniform probes so integer-period oscillations cannot
        # trivially alias every point of the initial dyadic grid.
        for fraction in (.211324865405187, .25, .5, .75, .788675134594813):
            p = point(a+(b-a)*fraction)
            chord = tuple(pa[i]+(pb[i]-pa[i])*fraction for i in (0, 1))
            errors.append(math.dist(p, chord))
        error = max(errors)
        if error <= tolerance:
            worst = max(worst, error)
            points.append(pb)
        else:
            middle = (a+b)/2
            pm = point(middle)
            split(a, middle, pa, pm, depth+1)
            split(middle, b, pm, pb, depth+1)
    for index in range(64):
        a = start+(end-start)*index/64
        b = start+(end-start)*(index+1)/64
        split(a, b, points[-1], point(b))
    return points, worst


def polar_requirements(text):
    """Extract only explicit, unambiguous origin-based winding requirements.

    This produces validation data, never geometry or model formulas.
    """
    text = text.split("\n后端试算反馈：", 1)[0]
    turns = re.search(r"(?:旋转|转)\s*(\d+(?:\.\d+)?)\s*圈", text)
    radius = re.search(r"最大半径\s*(\d+(?:\.\d+)?)\s*(毫米|厘米|米|mm|cm|m)", text)
    origin = re.search(r"从\s*[(（]\s*0\s*[,，]\s*0\s*[)）]|从原点", text)
    if not (turns and radius and origin and ("螺旋" in text or "螺线" in text)):
        return None
    factor = {"毫米": .001, "mm": .001, "厘米": .01, "cm": .01, "米": 1, "m": 1}[radius[2]]
    return {"turns": float(turns[1]), "radius_m": float(radius[1])*factor,
            "linear_radius": "阿基米德" in text or "线性" in text,
            "direction": -1 if "顺时针" in text and "逆时针" not in text else 1 if "逆时针" in text else 0}


def verify_polar_requirements(requirements, geometries):
    """Check actual mm geometry against source-derived winding constraints."""
    if not requirements:
        return
    if len(geometries) != 1 or geometries[0].get("type") != "polyline" or geometries[0].get("closed"):
        raise ParametricError("要求一条开放连续路径")
    points = [(p["x"]/1000, p["y"]/1000) for p in geometries[0]["vertices"]]
    radius = requirements["radius_m"]
    if radius <= 0 or requirements["turns"] <= 0:
        raise ParametricError("圈数和最大半径必须为正数")
    tolerance = max(.003, radius*.003)
    if math.hypot(*points[0]) > tolerance:
        raise ParametricError("路径起点不在要求的原点")
    previous, angle, radii = 0.0, 0.0, []
    for x, y in points[1:]:
        r = math.hypot(x, y)
        if r < 1e-10:
            raise ParametricError("路径中途返回原点，无法满足螺旋约束")
        current = math.atan2(y, x)
        delta = (current-previous+math.pi) % math.tau-math.pi
        angle += delta
        previous = current
        radii.append((r, angle))
    # The user need not specify the initial radial orientation. Extrapolate
    # it to radius zero from the first two samples for linear-radius paths.
    if requirements["linear_radius"] and len(radii) > 1:
        r0, a0 = radii[0]
        r1, a1 = radii[1]
        if abs(r1-r0) < 1e-12:
            raise ParametricError("半径未从原点开始增长")
        phase = a0-r0*(a1-a0)/(r1-r0)
        radii = [(r, a-phase) for r,a in radii]
        angle = radii[-1][1]
    observed = abs(angle)/math.tau
    if abs(observed-requirements["turns"]) > .02:
        raise ParametricError(f"实际旋转{observed:.4g}圈，要求{requirements['turns']:g}圈")
    if requirements["direction"] and angle*requirements["direction"] < 0:
        raise ParametricError("旋转方向不符合要求")
    if abs(max(r for r,a in radii)-radius) > tolerance or abs(radii[-1][0]-radius) > tolerance:
        raise ParametricError("最大半径或终点半径不符合要求")
    if requirements["linear_radius"]:
        total_angle = requirements["turns"]*math.tau
        if any(abs(r-radius*abs(a)/total_angle) > tolerance for r,a in radii):
            raise ParametricError("实际半径没有随旋转角度线性增长")
        if any(b[0] < a[0]-tolerance for a,b in zip(radii,radii[1:])):
            raise ParametricError("螺旋半径出现不符合要求的回退")
