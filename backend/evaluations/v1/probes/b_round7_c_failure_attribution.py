"""B round-7: C-group complex-generation failure attribution (offline, diagnostic only).

Scope:
  * Map corpus C1-C34 inputs to the six failure morphologies (anchor = corpus text).
  * Carry a five-layer root-cause schema: model_planning / geometry_measurement /
    geometry_execution / acceptance / pre_dependency_pending.
  * Run deterministic SYNTHETIC geometry demos that exercise the generic criterion
    gaps (connection-type dimension, repeat count + spacing consistency, scope
    separation between overall and part dimensions).

No model client, no network, no production import, no frozen-input mutation.
Synthetic numbers are generated here; they are NOT historical case evidence.

Run: python evaluations/v1/probes/b_round7_c_failure_attribution.py
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# 1. Corpus anchor mapping (C1-C34). Primary morphology; secondary listed.
#    Morphology codes:
#      COMPOSITE   复合轮廓（曲线段 + 直线段 / 尖角混合）
#      MULTIPART   多部件组合（相对位置 / 连接关系）
#      CONNECTION  曲线与直线连接（C0 / G1 / C1 连续性）
#      REPEAT      重复结构（同形 N 次、数量、等距、对齐）
#      ARRAY       阵列拓扑（行列、间距、阵列包围盒、单元归属）
#      DIMENSION   整体几何尺寸约束（整体宽高 / 中心 / 比例，作用域分离）
# ---------------------------------------------------------------------------

MORPH_LABEL = {
    "COMPOSITE": "复合轮廓（曲线+直线/尖角）",
    "MULTIPART": "多部件组合（相对位置/连接）",
    "CONNECTION": "曲线-直线连接（连续性）",
    "REPEAT": "重复结构（数量/等距/对齐）",
    "ARRAY": "阵列拓扑（行列/间距/包围盒）",
    "DIMENSION": "整体尺寸约束（作用域分离）",
}

# case_id -> (short input description, primary, secondary)
CORPUS_CASES: dict[str, tuple[str, str, list[str]]] = {
    "C1": ("贝塞尔曲线 4 控制点", "CONNECTION", []),
    "C2": ("闭合样条曲线 5 控制点平滑闭合", "CONNECTION", ["COMPOSITE"]),
    "C3": ("半圆拱门：两段直线 + 顶部圆弧，宽2高3", "COMPOSITE", ["CONNECTION", "DIMENSION"]),
    "C4": ("三角形轮廓 3 点闭合", "COMPOSITE", []),
    "C5": ("正五边形 外接圆半径1.5", "COMPOSITE", ["DIMENSION"]),
    "C6": ("五瓣花瓣闭合曲线（缺尺寸先澄清）", "COMPOSITE", ["REPEAT"]),
    "C7": ("矩形 + 四角各一圆", "MULTIPART", ["DIMENSION"]),
    "C8": ("3行4列矩形阵列 单元1×0.6 行距1.2列距1.5", "ARRAY", ["REPEAT", "DIMENSION"]),
    "C9": ("两相交圆 圆心距1.5", "MULTIPART", []),
    "C10": ("爱心在左 五角星在右", "MULTIPART", []),
    "C11": ("正弦波浪线 长5 波幅0.5 波距1", "COMPOSITE", ["DIMENSION"]),
    "C12": ("阿基米德螺旋线 3圈 最大半径2", "COMPOSITE", ["DIMENSION"]),
    "C13": ("正六边形 边长1", "COMPOSITE", ["DIMENSION"]),
    "C14": ("齿轮轮廓 外径2 8齿", "REPEAT", ["COMPOSITE", "DIMENSION"]),
    "C15": ("圆环 外圆R2 内圆R1", "MULTIPART", ["DIMENSION"]),
    "C16": ("房子：墙体矩形 + 三角屋顶 + 门", "MULTIPART", ["DIMENSION"]),
    "C17": ("3列2行蜂窝六边形阵列 边长0.5 无缝", "ARRAY", ["REPEAT"]),
    "C18": ("内凹四角星 参数曲线 最大半径2", "COMPOSITE", ["DIMENSION"]),
    "C19": ("心形线 参数曲线 尖点朝下 宽3", "COMPOSITE", ["CONNECTION", "DIMENSION"]),
    "C20": ("圆角矩形 宽3高2 圆角R0.5", "COMPOSITE", ["CONNECTION", "DIMENSION"]),
    "C21": ("十字形 两等宽矩形垂直交叉 总宽4总高4 臂宽1", "COMPOSITE", ["DIMENSION"]),
    "C22": ("雪花 6对称分支 每支2侧枝 最大半径2", "REPEAT", ["COMPOSITE", "DIMENSION"]),
    "C23": ("楼梯轮廓 5级台阶 每级宽0.4高0.3", "REPEAT", ["COMPOSITE", "DIMENSION"]),
    "C24": ("环形交叉路口 外环R3 4条等角放射线 长2", "MULTIPART", ["REPEAT", "DIMENSION"]),
    "C25": ("禁止标志 圆R1.5 + 45度斜线", "MULTIPART", []),
    "C26": ("字母A轮廓 高3宽2", "COMPOSITE", ["DIMENSION"]),
    "C27": ("立方体透视轮廓 边长2", "COMPOSITE", ["DIMENSION"]),
    "C28": ("笑脸 圆R1 + 两圆点眼 + 圆弧嘴", "MULTIPART", []),
    "C29": ("回字形 外框边长3 内框边长2 居中", "MULTIPART", ["DIMENSION"]),
    "C30": ("斑马线 6条平行横线 长4宽0.4 间距0.6", "ARRAY", ["REPEAT", "DIMENSION"]),
    "C31": ("太极图 外圆R2 S形分割线 两对称小圆", "MULTIPART", ["COMPOSITE"]),
    "C32": ("六角螺母 外六角外接圆R1.5 中心孔R0.8", "MULTIPART", ["DIMENSION"]),
    "C33": ("圆柱轮廓 底圆R1 高3 顶圆可见", "COMPOSITE", ["MULTIPART", "DIMENSION"]),
    "C34": ("L形走廊 宽1 两臂长3和2 直角连接", "COMPOSITE", ["CONNECTION", "DIMENSION"]),
}

# ---------------------------------------------------------------------------
# 2. Five-layer root-cause schema
# ---------------------------------------------------------------------------

LAYERS = {
    "model_planning": "模型规划：计划本身错/缺字段/表达式与声明不符",
    "geometry_measurement": "几何测量：判据测不出或误判（弦采样/最近点/剖面不足）",
    "geometry_execution": "几何执行：构造/求交/布尔/连接执行失败",
    "acceptance": "验收：测得出但判定规则错，或容差口径错",
    "pre_dependency_pending": "前置依赖/版本未验收：依赖另一版本产物尚未通过，不计编辑器缺陷",
}

# Evidence ledger. evidence_mode follows D1 vocabulary:
#   live_model / reconstructed_fixture / rule_parser_zero_cost / unavailable
# C1-C34 have NO live record -> unverified by construction.
EVIDENCE_LEDGER = [
    {
        "case_id": "A9",
        "evidence_mode": "live_model",
        "layer": "acceptance+model_planning",
        "summary": "真实 deepseek-flash 两轮；lower_tip 区域未检出，failed，未持久化候选。"
                   "旧区域存在性布尔不等于数学 cusp 证明。",
        "ref": "D1_round4_A9真实模型受控评测报告.md; round4/A9_case_record.json",
    },
    {
        "case_id": "S1",
        "evidence_mode": "reconstructed_fixture",
        "layer": "geometry_measurement",
        "summary": "三段开放 Bezier 夹具：C0/C1 通过，2 接点 0 失败，max tangent delta 0.0°。",
        "ref": "p1.3g-S1-diagnostics.json",
    },
    {
        "case_id": "A9-JUNCTION",
        "evidence_mode": "reconstructed_fixture",
        "layer": "geometry_measurement",
        "summary": "4 接点 2 失败，max tangent delta 107.94°，c1=false；接点诊断字段已增强。",
        "ref": "p1.3g-A9-diagnostics.json; P1.3-G Bezier连接点失败证据增强报告",
    },
    {
        "case_id": "M1",
        "evidence_mode": "unavailable",
        "layer": "pre_dependency_pending",
        "summary": "无冻结输入与验收规则，not_run；不得计入编辑器缺陷。",
        "ref": "mock_replay_results.json#M1",
    },
    {
        "case_id": "warehouse_with_aisles",
        "evidence_mode": "rule_parser_zero_cost",
        "layer": "acceptance(measurement gap)",
        "summary": "几何已出(6 图元)但 minimum_logical_objects 未通过：未识别为独立逻辑对象。",
        "ref": "mock_replay_results.json#warehouse_with_aisles",
    },
    {
        "case_id": "parking_rows_and_driveway",
        "evidence_mode": "rule_parser_zero_cost",
        "layer": "acceptance(measurement gap)",
        "summary": "minimum_entities + minimum_logical_objects 未通过；重复车位未按对象计数。",
        "ref": "mock_replay_results.json#parking_rows_and_driveway",
    },
    {
        "case_id": "workshop_with_machine_pads",
        "evidence_mode": "rule_parser_zero_cost",
        "layer": "acceptance(measurement gap)",
        "summary": "minimum_entities + minimum_logical_objects 未通过；设备基础未独立成对象。",
        "ref": "mock_replay_results.json#workshop_with_machine_pads",
    },
    {
        "case_id": "stepped_foundation",
        "evidence_mode": "rule_parser_zero_cost",
        "layer": "model_planning(rule coverage)",
        "summary": "clarification_required：required_types/minimum_entities/objects 缺失；规则解析器未覆盖嵌套台阶。",
        "ref": "mock_replay_results.json#stepped_foundation",
    },
    {
        "case_id": "factory_zone_grid",
        "evidence_mode": "rule_parser_zero_cost",
        "layer": "model_planning(rule coverage)",
        "summary": "clarification_required：分割线/网格类型与对象数未被规则表达。",
        "ref": "mock_replay_results.json#factory_zone_grid",
    },
    {
        "case_id": "stadium_bleacher_rows",
        "evidence_mode": "rule_parser_zero_cost",
        "layer": "model_planning(rule coverage)",
        "summary": "clarification_required：重复排/座席数量与对象数缺失。",
        "ref": "mock_replay_results.json#stadium_bleacher_rows",
    },
    {
        "case_id": "solar_panel_rows",
        "evidence_mode": "rule_parser_zero_cost",
        "layer": "model_planning(rule coverage)",
        "summary": "clarification_required：两排阵列单元与间距未被规则表达。",
        "ref": "mock_replay_results.json#solar_panel_rows",
    },
]

# ---------------------------------------------------------------------------
# 3. Synthetic generic-gap demos (deterministic, self-contained)
# ---------------------------------------------------------------------------

@dataclass
class JointCheck:
    c0_gap: float
    tangent_delta_deg: float
    c0_pass: bool
    g1_pass: bool
    note: str


def _tangent(p0, p1, p2, p3, side: str):
    """Bezier endpoint tangent vector (existing parameterization convention)."""
    if side == "end":
        return (p3[0] - p2[0], p3[1] - p2[1])
    return (p1[0] - p0[0], p1[1] - p0[1])


def _angle_deg(v):
    return math.degrees(math.atan2(v[1], v[0]))


def check_joint(left, right, tol_pos=1e-3, tol_tan_deg=15.0) -> JointCheck:
    """Connection-type dimension: separate C0 (endpoint coincidence) from
    G1 (tangent continuity). A distance-only check cannot label the type."""
    le = left[3]
    rs = right[0]
    gap = math.hypot(le[0] - rs[0], le[1] - rs[1])
    vl = _tangent(*left, "end")
    vr = _tangent(*right, "start")
    dl = abs((_angle_deg(vl) - _angle_deg(vr) + 180) % 360 - 180)
    c0 = gap <= tol_pos
    g1 = c0 and dl <= tol_tan_deg
    note = "C0 only" if c0 and not g1 else ("G1" if g1 else "disconnected")
    return JointCheck(gap, dl, c0, g1, note)


def _spacing_consistency(centers, axis: int):
    """Repeat/array dimension: count match + equal-spacing deviation + alignment.
    Returns (count, max spacing deviation, max perpendicular deviation)."""
    xs = sorted(p[axis] for p in centers)
    gaps = [b - a for a, b in zip(xs, xs[1:])]
    mean = sum(gaps) / len(gaps) if gaps else 0.0
    spacing_dev = max((abs(g - mean) for g in gaps), default=0.0)
    perp = [p[1 - axis] for p in centers]
    perp_dev = max(perp) - min(perp) if perp else 0.0
    return len(centers), spacing_dev, perp_dev


def _bbox(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def scope_dimension_check(overall_pts, part_pts, req_overall, req_part):
    """Dimension scope separation: overall bbox/center vs part bbox must be
    measured under their own scope; a part match must not mask an overall miss."""
    ox0, oy0, ox1, oy1 = _bbox(overall_pts)
    px0, py0, px1, py1 = _bbox(part_pts)
    overall_w, overall_h = ox1 - ox0, oy1 - oy0
    part_w, part_h = px1 - px0, py1 - py0
    overall_ok = (abs(overall_w - req_overall[0]) <= req_overall[2]
                  and abs(overall_h - req_overall[1]) <= req_overall[2])
    part_ok = (abs(part_w - req_part[0]) <= req_part[2]
               and abs(part_h - req_part[1]) <= req_part[2])
    return {
        "overall": {"w": overall_w, "h": overall_h, "pass": overall_ok},
        "part": {"w": part_w, "h": part_h, "pass": part_ok},
        "scope_mixed": not (overall_ok == part_ok),
    }


def _synthetic_demos():
    # Demo 1: G1 joint vs C0-only joint.
    g1_left = [(0, 0), (1, 1), (2, 1), (3, 0)]
    g1_right = [(3, 0), (4, -1), (5, -1), (6, 0)]
    g1 = check_joint(g1_left, g1_right)

    c0_left = [(0, 0), (1, 1), (2, 1), (3, 0)]
    c0_right = [(3, 0), (4, 1), (5, 1), (6, 0)]  # tangent flips up: C0 only
    c0 = check_joint(c0_left, c0_right)

    # Demo 2: regular row of 4 vs irregular row.
    regular = [(i * 2.0, 0.0) for i in range(4)]
    irregular = [(0.0, 0.0), (2.1, 0.0), (3.9, 0.0), (6.2, 0.0)]
    reg = _spacing_consistency(regular, axis=0)
    irr = _spacing_consistency(irregular, axis=0)

    # Demo 3: overall bbox satisfied while a part is off (scope separation).
    overall = [(0, 0), (10, 0), (10, 6), (0, 6)]
    part_ok = [(1, 1), (3, 1), (3, 3), (1, 3)]
    part_off = [(1, 1), (5, 1), (5, 3), (1, 3)]  # part width 4 vs required 2
    sc_ok = scope_dimension_check(overall, part_ok, (10, 6, 0.05), (2, 2, 0.05))
    sc_off = scope_dimension_check(overall, part_off, (10, 6, 0.05), (2, 2, 0.05))

    return {
        "joint_g1": g1,
        "joint_c0_only": c0,
        "repeat_regular": reg,
        "repeat_irregular": irr,
        "scope_part_ok": sc_ok,
        "scope_part_off": sc_off,
    }


def main() -> int:
    demos = _synthetic_demos()

    print("=== C1-C34 morphology anchor ===")
    by_morph: dict[str, list[str]] = {k: [] for k in MORPH_LABEL}
    for cid, (desc, primary, secondary) in CORPUS_CASES.items():
        by_morph[primary].append(cid)
    for code, label in MORPH_LABEL.items():
        print(f"{code:11} {label}: {', '.join(by_morph[code])}")

    print("\n=== synthetic generic-gap demos ===")
    j1, j2 = demos["joint_g1"], demos["joint_c0_only"]
    print(f"G1 joint      : gap={j1.c0_gap:.2e} tangent={j1.tangent_delta_deg:.2f}° "
          f"C0={j1.c0_pass} G1={j1.g1_pass} -> {j1.note}")
    print(f"C0-only joint : gap={j2.c0_gap:.2e} tangent={j2.tangent_delta_deg:.2f}° "
          f"C0={j2.c0_pass} G1={j2.g1_pass} -> {j2.note}")
    r = demos["repeat_regular"]
    i = demos["repeat_irregular"]
    print(f"regular row 4 : count={r[0]} spacing_dev={r[1]:.3f} perp_dev={r[2]:.3f}")
    print(f"irregular row : count={i[0]} spacing_dev={i[1]:.3f} perp_dev={i[2]:.3f}")
    print(f"scope part ok : overall={demos['scope_part_ok']['overall']['pass']} "
          f"part={demos['scope_part_ok']['part']['pass']}")
    print(f"scope part off: overall={demos['scope_part_off']['overall']['pass']} "
          f"part={demos['scope_part_off']['part']['pass']} "
          f"scope_mixed={demos['scope_part_off']['scope_mixed']}")

    print("\n=== evidence ledger (C1-C34 live evidence: unverified) ===")
    for e in EVIDENCE_LEDGER:
        print(f"{e['case_id']:32} {e['evidence_mode']:24} {e['layer']}")

    # ---- deterministic assertions on synthetic demos ----
    assert j1.g1_pass and j1.c0_pass, "G1 fixture should pass both"
    assert j2.c0_pass and not j2.g1_pass, "C0-only fixture must fail G1"
    assert r[0] == 4 and r[1] < 1e-9, "regular row spacing must be equal"
    assert i[1] > r[1], "irregular row must show larger spacing deviation"
    assert demos["scope_part_ok"]["part"]["pass"]
    assert demos["scope_part_off"]["overall"]["pass"] and not demos["scope_part_off"]["part"]["pass"]
    assert demos["scope_part_off"]["scope_mixed"], "part miss must not be masked by overall pass"

    # Every C case must have a primary morphology in the six-code set.
    assert set(by_morph.keys()) == set(MORPH_LABEL.keys())
    assert len(CORPUS_CASES) == 34, "corpus anchor must cover C1-C34"

    print("\nALL ROUND-7 ATTRIBUTION PROBE ASSERTIONS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
