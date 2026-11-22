"""Zero-model dual-tree count parity probe for R-IDENTITY-1.

Runs the count reconciliation helper and the inventory side-car against the
same synthetic fixtures in whichever tree PYTHONPATH points to. No model, no
network, no production routing. Run once per tree; compare the two JSON dumps.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.cad_structure_contract import object_inventory_sidecar, explicit_composition
from app.cad_construction_interpreter import _logical_object_count_consistency


def geom(gid, gtype):
    return {"id": gid, "type": gtype, "selected": True}


def obj(oid, refs):
    return {"object_id": oid, "geometry_refs": refs}


def trial(geometries, objects, shared=None):
    return {
        "geometries": geometries,
        "logical_objects": objects,
        "topology": {"shared_geometries": shared or []},
        "graph_validation": {"verified": True, "errors": []},
    }


def count_report(source, trial_result, composition_contract):
    return _logical_object_count_consistency(
        trial_result=trial_result,
        composition_contract=composition_contract,
        structure_contract=None,
        scalar_contract=None,
        source=source,
    )


def summarize(source, trial_result, composition_contract):
    sidecar = object_inventory_sidecar(source)
    inventory = None
    if sidecar:
        inventory = {
            "state": sidecar["object_requirements_state"],
            "count": sidecar["logical_object_count"],
            "entries": [
                {"object_noun": e["object_noun"], "quantity": e["quantity"],
                 "evidence": e["evidence"], "span": e["evidence_span"]}
                for e in sidecar["object_requirements"]
            ],
        }
    report = count_report(source, trial_result, composition_contract)
    mismatch = None
    if report.get("unknown_requirements"):
        mismatch = report["unknown_requirements"][0].get("mismatch")
    return {
        "source": source,
        "inventory": inventory,
        "count_status": report.get("status"),
        "actual_object_count": report.get("actual_object_count"),
        "expected_object_count": (report.get("baseline") or {}).get("expected_object_count"),
        "baseline_source": (report.get("baseline") or {}).get("source"),
        "mismatch": mismatch,
        "checks": [
            {"status": c.get("status"), "expected": c.get("expected_object_count"),
             "actual": c.get("actual_object_count")}
            for c in report.get("checks") or []
        ],
    }


results = {}

# S1 inventory 2/1 -> failed / missing_object
src_box = "两个立方体并排，画等轴投影"
results["S1_box_2_of_1"] = summarize(
    src_box,
    trial([geom(1, "polyline")], [obj("obj-1", [1])]),
    object_inventory_sidecar(src_box),
)

# S2 inventory 2/2 -> passed
results["S2_box_2_of_2"] = summarize(
    src_box,
    trial([geom(1, "polyline"), geom(2, "polyline")],
          [obj("obj-1", [1]), obj("obj-2", [2])]),
    object_inventory_sidecar(src_box),
)

# S3 legacy circles 2/2 -> passed
src_circle = "画两个圆，半径1米"
legacy = explicit_composition(src_circle)
results["S3_circle_2_of_2"] = summarize(
    src_circle,
    trial([geom(1, "circle"), geom(2, "circle")],
          [obj("obj-1", [1]), obj("obj-2", [2])]),
    legacy,
)

# S4 required 2, actual 3 -> failed / extra_object
results["S4_circle_2_of_3"] = summarize(
    src_circle,
    trial([geom(1, "circle"), geom(2, "circle"), geom(3, "circle")],
          [obj("obj-1", [1]), obj("obj-2", [2]), obj("obj-3", [3])]),
    legacy,
)

# S5 one object, four line segments -> ownership count 1
src_lines = "画一个矩形轮廓"
lines = [geom(i, "line") for i in (1, 2, 3, 4)]
results["S5_one_object_four_segments"] = summarize(
    src_lines,
    trial(lines, [obj("obj-1", [1, 2, 3, 4])]),
    explicit_composition(src_lines),
)

# S6 declared shared geometry, two verified owners -> count 2
results["S6_shared_two_owners"] = summarize(
    src_circle,
    trial([geom(1, "circle"), geom(2, "circle")],
          [obj("obj-1", [1]), obj("obj-2", [2])],
          shared=[{"geometry_id": 1, "object_ids": ["obj-1", "obj-2"]}]),
    legacy,
)

# S7 attribute phrases -> no object inventory; count not_checked
for label, src in [
    ("S7a_edges", "一个立方体有 12 条棱"),
    ("S7b_teeth", "8 个齿的齿轮轮廓"),
    ("S7c_length", "长度 20 mm"),
    ("S7d_angle", "角度 90 度"),
    ("S7e_lines", "3 条平行横线"),
    ("S7f_pentagon", "正五边形"),
    ("S7g_outer_dia", "外径 2 米"),
    ("S7h_side", "边长 50 毫米"),
]:
    results[label] = summarize(src, trial([], []), explicit_composition(src))

# S8 repeated phrase -> inventory count 4 both trees
src_repeat = "生成两个立方体和两个立方体"
results["S8_repeated_4"] = summarize(
    src_repeat,
    trial([geom(1, "polyline"), geom(2, "polyline"),
           geom(3, "polyline"), geom(4, "polyline")],
          [obj("obj-1", [1]), obj("obj-2", [2]),
           obj("obj-3", [3]), obj("obj-4", [4])]),
    object_inventory_sidecar(src_repeat),
)

print(json.dumps(results, ensure_ascii=False, indent=2))
