"""R-IDENTITY-1 interpreter-side identity sub-report probe (zero model).

Runs the real entry path ``interpret_construction_request`` with a deterministic
payload callback, plus direct private-helper calls on synthetic trial results.
No real model, no network, no production routing.
"""
import json
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.cad_construction_interpreter import (
    interpret_construction_request,
    _object_identity_consistency,
    _logical_object_count_consistency,
)


def payload_for(steps, source):
    return {
        "schema_version": "cad.construction-interpretation.v1",
        "is_construction_request": True,
        "confidence": 0.95,
        "evidence_text": [source],
        "assumptions": [],
        "plan": {"units": "m", "steps": steps},
    }


def circle_step(ref, x, y, radius=1.0, label="圆"):
    return {
        "op": "add_circle", "step_id": ref, "output_ref": ref,
        "semantic": {"label": label, "object_type": "circle"},
        "center": {"x": x, "y": y}, "radius": radius,
    }


def rectangle_polyline_step(ref, x, y, w, h, label="矩形"):
    return {
        "op": "add_polyline", "step_id": ref, "output_ref": ref,
        "semantic": {"label": label}, "closed": True,
        "vertices": [{"x": x, "y": y}, {"x": x + w, "y": y},
                     {"x": x + w, "y": y + h}, {"x": x, "y": y + h}],
    }


def four_line_rectangle_steps(ref, x, y, w, h, label="矩形"):
    corners = [{"x": x, "y": y}, {"x": x + w, "y": y},
               {"x": x + w, "y": y + h}, {"x": x, "y": y + h}]
    lines = []
    for index in range(4):
        a, b = corners[index], corners[(index + 1) % 4]
        lines.append({
            "op": "add_line", "step_id": f"{ref}-l{index}",
            "output_ref": f"{ref}-l{index}",
            "semantic": {"label": label},
            "start": a, "end": b,
        })
    return lines


report = {"entry": {}, "direct": {}, "count_regression": {}}
failures = []


def identity_of(result):
    if isinstance(result, dict) and "object_identity_acceptance" in result.get("source_acceptance", {}):
        return result["source_acceptance"]["object_identity_acceptance"]
    return result if isinstance(result, dict) else None


def entry_layers(result):
    """Capture three layers separately; never merge a sub-report pass into the
    summary verdict. The interpreter layer does not own the candidate gate."""
    sa = result.get("source_acceptance", {})
    ident = sa.get("object_identity_acceptance", {})
    summary = result.get("acceptance_summary", {})
    tr = result.get("trial_result") or {}
    return {
        "identity_status": ident.get("status"),
        "identity_state": ident.get("identity_state"),
        "identity_evidence_grade": ident.get("evidence_grade"),
        "summary_status": summary.get("status"),
        "summary_review_required": summary.get("review_required"),
        "summary_coverage": summary.get("requirement_coverage"),
        "summary_unknown_requirements": summary.get("unknown_requirements"),
        "top_status": result.get("status"),
        "geometry_count": len(tr.get("geometries") or []),
        "logical_object_count": len(tr.get("logical_objects") or []),
        "candidate_is_accepted": result.get("candidate_is_accepted"),
        "views": tr.get("views"),
    }


def record(bucket, key, result, expect_status):
    identity = identity_of(result) if isinstance(result, dict) else result
    report[bucket][key] = {
        "status": identity.get("status") if identity else None,
        "identity_state": identity.get("identity_state") if identity else None,
        "evidence_grade": identity.get("evidence_grade") if identity else None,
        "matched_entries": identity.get("matched_entries") if identity else None,
        "unmatched_entries": identity.get("unmatched_entries") if identity else None,
        "unmatched_objects": identity.get("unmatched_objects") if identity else None,
        "ambiguous_bindings": identity.get("ambiguous_bindings") if identity else None,
        "note": identity.get("note") if identity else None,
    }
    if expect_status is not None and (identity or {}).get("status") != expect_status:
        failures.append((bucket, key, (identity or {}).get("status"), expect_status))


def synthetic_trial(geometries, objects, topology=None):
    return {"geometries": geometries, "logical_objects": objects,
            "topology": topology or {"shared_geometries": []},
            "graph_validation": {"verified": True, "errors": []}}


# --- 1. Entry: two compliant circles -> identity passed (set-level). ----------
source1 = "画两个圆，半径1米"
steps1 = [circle_step("circle-1", -1.5, 0), circle_step("circle-2", 1.5, 0)]
r1 = interpret_construction_request(source1, lambda *_: deepcopy(payload_for(steps1, source1)),
                                    force_structured_model=True)
record("entry", "two_circles_passed", r1, "passed")
report["entry"]["two_circles_passed"]["layers"] = entry_layers(r1)
# Tamper model labels/object_type; identity must not depend on them.
tampered = deepcopy(payload_for(steps1, source1))
for step in tampered["plan"]["steps"]:
    step["semantic"]["label"] = "矩形"
    step["semantic"]["object_type"] = "rectangle"
r1b = interpret_construction_request(source1, lambda *_: deepcopy(tampered),
                                    force_structured_model=True)
record("entry", "two_circles_label_tampered", r1b, "passed")
report["entry"]["two_circles_label_tampered"]["layers"] = entry_layers(r1b)

# --- 2. Entry: mixed circle + polyline rectangle reaches ready; the existing
# composition compile binds one step per component, so a four-line rectangle is
# verified through the direct helper below instead. -----------------------------
source2b = "画一个圆和一个矩形，圆半径1米，矩形宽2米高2米"
steps2b = [circle_step("circle-1", -3, 0),
           rectangle_polyline_step("rect-1", -1, -1, 2, 2)]
r2b = interpret_construction_request(source2b, lambda *_: deepcopy(payload_for(steps2b, source2b)),
                                      force_structured_model=True)
record("entry", "circle_and_rectangle_ready", r2b, None)
report["entry"]["circle_and_rectangle_ready"]["layers"] = entry_layers(r2b)

# --- 2c. Entry gap: a bare rectangle count phrase has no structured baseline in
# the existing contract; the identity channel must not fabricate one from the
# model label. Recorded as a known gap, not asserted passed. --------------------
source2c = "画两个矩形并排，宽2米高2米"
steps2c = [rectangle_polyline_step("rect-1", -3, -1, 2, 2),
           rectangle_polyline_step("rect-2", 1, -1, 2, 2)]
r2c = interpret_construction_request(source2c, lambda *_: deepcopy(payload_for(steps2c, source2c)),
                                      force_structured_model=True)
sa2c = r2c.get("source_acceptance") or {}
report["entry"]["rectangle_only_baseline_gap"] = {
    "composition_contract": r2c.get("composition_contract"),
    "identity_status": (sa2c.get("object_identity_acceptance") or {}).get("status"),
    "top_status": r2c.get("status"),
    "note": "既有结构化契约未捕获纯矩形数量短语；入口身份通道未建立基线，缺口留证。",
}

# --- 3. Entry: cube projection required, actual two circles -> unverified. -----
source3 = "画两个立方体的等轴投影，边长2米"
steps3 = [circle_step("circle-1", -1.5, 0), circle_step("circle-2", 1.5, 0)]
r3 = interpret_construction_request(source3, lambda *_: deepcopy(payload_for(steps3, source3)),
                                     force_structured_model=True)
record("entry", "cube_projection_two_circles", r3, "unverified")
report["entry"]["cube_projection_two_circles"]["layers"] = entry_layers(r3)

# --- 5. Direct: only self-report / unclassified geometry -> unverified. -------
arc_g = {"id": 1, "type": "arc", "role": "printing", "selected": True,
         "center": {"x": 0, "y": 0}, "radius": 1, "start_angle": 0, "end_angle": 90}
arc_obj = {"object_id": "obj-1", "geometry_refs": [1], "label": "圆", "object_type": "circle"}
contract5 = {"object_requirements_state": "complete", "logical_object_count": 2,
             "object_requirements": [{
                 "requirement_id": "request-0:object-1:object", "object_noun": "圆",
                 "quantity": 2, "measure_word": "个", "expected_category": "object",
                 "evidence": "两个圆", "evidence_span": [1, 4], "source_id": "request-0"}]}
r5 = _object_identity_consistency(
    trial_result=synthetic_trial([arc_g], [arc_obj]),
    composition_contract=contract5, structure_contract=None,
    scalar_contract={"subjects": ["圆"]}, source="画两个圆，半径1米")
record("direct", "self_report_only_unverified", r5, "unverified")

# --- 2b. Direct: one four-line closed rectangle + one polyline rectangle. -----
def line_g(geom_id, x0, y0, x1, y1):
    return {"id": geom_id, "type": "line", "role": "printing", "selected": True,
            "start": {"x": x0, "y": y0}, "end": {"x": x1, "y": y1}}

loop = [line_g(1, 0, 0, 2, 0), line_g(2, 2, 0, 2, 2),
        line_g(3, 2, 2, 0, 2), line_g(4, 0, 2, 0, 0)]
loop_obj = {"object_id": "rect-loop", "geometry_refs": [1, 2, 3, 4], "label": "矩形"}
poly = {"id": 5, "type": "polyline", "closed": True, "role": "printing", "selected": True,
        "vertices": [{"x": 4, "y": 0}, {"x": 6, "y": 0}, {"x": 6, "y": 2}, {"x": 4, "y": 2}]}
poly_obj = {"object_id": "rect-poly", "geometry_refs": [5], "label": "矩形"}
contract_rect = {"object_requirements_state": "complete", "logical_object_count": 2,
                 "object_requirements": [{
                     "requirement_id": "request-0:object-1:object", "object_noun": "矩形",
                     "quantity": 2, "measure_word": "个", "expected_category": "object",
                     "evidence": "两个矩形", "evidence_span": [1, 5], "source_id": "request-0"}]}
r_rect = _object_identity_consistency(
    trial_result=synthetic_trial(loop + [poly], [loop_obj, poly_obj]),
    composition_contract=contract_rect, structure_contract=None,
    scalar_contract={"subjects": ["矩形"]}, source="画两个矩形，宽2米高2米")
record("direct", "rectangle_expressions_both_recognized", r_rect, "passed")

# --- 6. Direct: one object reused for two independent requirements -> not passed.
contract6 = {"object_requirements_state": "complete", "logical_object_count": 2,
             "object_requirements": [
                 {"requirement_id": "request-0:object-1:object", "object_noun": "圆",
                  "quantity": 1, "measure_word": "个", "expected_category": "object",
                  "evidence": "第一个圆", "evidence_span": [1, 5], "source_id": "request-0"},
                 {"requirement_id": "request-0:object-2:object", "object_noun": "圆",
                  "quantity": 1, "measure_word": "个", "expected_category": "object",
                  "evidence": "第二个圆", "evidence_span": [6, 10], "source_id": "request-0"}]}
circle_g = {"id": 1, "type": "circle", "role": "printing", "selected": True,
            "center": {"x": 0, "y": 0}, "radius": 1}
circle_obj = {"object_id": "obj-1", "geometry_refs": [1], "label": "圆"}
r6 = _object_identity_consistency(
    trial_result=synthetic_trial([circle_g], [circle_obj]),
    composition_contract=contract6, structure_contract=None,
    scalar_contract={"subjects": ["圆"]}, source="画两个圆，半径1米")
record("direct", "reused_object_not_passed", r6, "unverified")

# --- 7. Direct: binding rebuilt per execution; no stale cache. ------------------
bad = synthetic_trial([arc_g], [arc_obj])
good = synthetic_trial([circle_g], [circle_obj])
r7a = _object_identity_consistency(
    trial_result=bad, composition_contract=contract5, structure_contract=None,
    scalar_contract={"subjects": ["圆"]}, source="画两个圆，半径1米")
r7b = _object_identity_consistency(
    trial_result=good, composition_contract=contract5, structure_contract=None,
    scalar_contract={"subjects": ["圆"]}, source="画两个圆，半径1米")
report["direct"]["rebuild_bad"] = {"status": r7a["status"], "note": r7a["note"]}
report["direct"]["rebuild_good"] = {"status": r7b["status"], "note": r7b["note"]}
if r7a["status"] == "passed" or r7b["status"] == "passed":
    failures.append(("direct", "rebuild", "unexpected pass", "unverified/partial"))

# --- 4. Direct: operable 3D solid -> unverified (3D channel missing). ---------
contract_solid = {"object_requirements_state": "complete", "logical_object_count": 2,
                  "object_requirements": [{
                      "requirement_id": "request-0:object-1:object", "object_noun": "实体",
                      "quantity": 2, "measure_word": "个", "expected_category": "object",
                      "evidence": "两个可操作的三维实体", "evidence_span": [2, 10],
                      "source_id": "request-0"}]}
solid_objs = [
    {"object_id": "solid-1", "geometry_refs": [1], "label": "实体"},
    {"object_id": "solid-2", "geometry_refs": [2], "label": "实体"},
]
solid_geoms = [
    {"id": 1, "type": "polyline", "closed": True, "role": "printing", "selected": True,
     "vertices": [{"x": -2, "y": -1}, {"x": 0, "y": -1}, {"x": 0, "y": 1}, {"x": -2, "y": 1}]},
    {"id": 2, "type": "polyline", "closed": True, "role": "printing", "selected": True,
     "vertices": [{"x": 1, "y": -1}, {"x": 3, "y": -1}, {"x": 3, "y": 1}, {"x": 1, "y": 1}]},
]
r4 = _object_identity_consistency(
    trial_result=synthetic_trial(solid_geoms, solid_objs),
    composition_contract=contract_solid, structure_contract=None,
    scalar_contract={"subjects": ["实体"]}, source="生成两个可操作的三维实体，宽2米高2米")
record("direct", "three_d_solid_unverified", r4, "unverified")

# --- Round 2: per-object evidence scope, three-state classification. ----------
report["round2"] = {}


def _circle_g(gid, x, y):
    return {"id": gid, "type": "circle", "role": "printing", "selected": True,
            "center": {"x": x, "y": y}, "radius": 1.0}


def _obj(oid, refs):
    return {"object_id": oid, "geometry_refs": refs, "label": "圆"}


def _arc_g(gid):
    return {"id": gid, "type": "arc", "role": "printing", "selected": True,
            "center": {"x": 0, "y": 0}, "radius": 1,
            "start_angle": 0, "end_angle": 90}


def _circle_contract(noun, quantity, evidence):
    return {"object_requirements_state": "complete", "logical_object_count": quantity,
            "object_requirements": [{
                "requirement_id": "request-0:object-1:object", "object_noun": noun,
                "quantity": quantity, "measure_word": "个", "expected_category": "object",
                "evidence": evidence, "evidence_span": [1, 4], "source_id": "request-0"}]}


def _identity(geometries, objects, contract, source, topology=None, source_acceptance=None):
    return _object_identity_consistency(
        trial_result=synthetic_trial(geometries, objects, topology),
        composition_contract=contract, structure_contract=None,
        scalar_contract={"subjects": []}, source=source,
        source_acceptance=source_acceptance)


# R2-1: one classified circle, one unclassified arc -> unverified, not passed.
r21 = _identity([_circle_g(1, -1, 0), _arc_g(2)], [_obj("obj-1", [1]), _obj("obj-2", [2])],
                _circle_contract("圆", 2, "两个圆"), "画两个圆，半径1米")
report["round2"]["one_classified_one_unclassified"] = {
    "status": r21["status"],
    "unmatched": r21["unmatched_entries"],
}
if r21["status"] != "unverified":
    failures.append(("round2", "one_classified_one_unclassified", r21["status"], "unverified"))

# R2-2: two classified circles -> passed, matched entries carry geometry_ids.
r22 = _identity([_circle_g(1, -1, 0), _circle_g(2, 1, 0)],
                [_obj("obj-1", [1]), _obj("obj-2", [2])],
                _circle_contract("圆", 2, "两个圆"), "画两个圆，半径1米")
r22_geo = [b["geometry_ids"] for e in r22["matched_entries"] for b in e["bindings"]]
report["round2"]["two_classified_circles"] = {
    "status": r22["status"], "geometry_ids": r22_geo,
}
if r22["status"] != "passed" or not all(r22_geo):
    failures.append(("round2", "two_classified_circles", r22["status"], "passed+geometry_ids"))

# R2-3: channel passed but covers only object A; B uncovered -> unverified.
r23 = _identity([_circle_g(1, -1, 0), _circle_g(2, 1, 0)],
                [_obj("obj-1", [1]), _obj("obj-2", [2])],
                _circle_contract("立方体", 2, "两个立方体的等轴投影"),
                "画两个立方体的等轴投影，边长2米",
                source_acceptance={"projection_acceptance": {
                    "status": "passed", "checks": [{"geometry_ids": [1]}]}})
report["round2"]["channel_partial_coverage"] = {
    "status": r23["status"], "unmatched": r23["unmatched_entries"],
}
if r23["status"] != "unverified":
    failures.append(("round2", "channel_partial_coverage", r23["status"], "unverified"))

# R2-4: two rectangles required, two proven circles (both classified) -> failed.
rect_contract = _circle_contract("矩形", 2, "两个矩形")
r24 = _identity([_circle_g(1, -1, 0), _circle_g(2, 1, 0)],
                [_obj("obj-1", [1]), _obj("obj-2", [2])],
                rect_contract, "画两个矩形，宽2米高2米")
report["round2"]["proven_mismatch_both_classified"] = {
    "status": r24["status"], "unmatched": r24["unmatched_entries"],
}
if r24["status"] != "failed":
    failures.append(("round2", "proven_mismatch_both_classified", r24["status"], "failed"))

# R2-5: three circles, requirement 2 -> identity 2/2 passed, third unmatched;
# count report still failed/extra_object (independent reports, no field cross-write).
three = [_circle_g(1, -2, 0), _circle_g(2, 0, 0), _circle_g(3, 2, 0)]
three_objs = [_obj("obj-1", [1]), _obj("obj-2", [2]), _obj("obj-3", [3])]
r25 = _identity(three, three_objs, _circle_contract("圆", 2, "两个圆"), "画两个圆，半径1米")
count25 = _logical_object_count_consistency(
    trial_result=synthetic_trial(three, three_objs),
    composition_contract=_circle_contract("圆", 2, "两个圆"),
    structure_contract=None, scalar_contract={"subjects": []}, source="画两个圆，半径1米")
report["round2"]["three_circles_require_two"] = {
    "identity_status": r25["status"],
    "matched_object_ids": [b["object_id"] for e in r25["matched_entries"] for b in e["bindings"]],
    "unmatched_objects": r25["unmatched_objects"],
    "count_status": count25.get("status"),
    "count_mismatch": (count25.get("unknown_requirements") or [{}])[0].get("mismatch"),
}
if r25["status"] != "passed" or len(r25["unmatched_objects"]) != 1:
    failures.append(("round2", "three_circles_identity", r25["status"], "passed+1 unmatched"))
if count25.get("status") != "failed" or (count25.get("unknown_requirements") or [{}])[0].get("mismatch") != "extra_object":
    failures.append(("round2", "three_circles_count", count25.get("status"), "failed/extra_object"))

# R2-6a: shared owners=2, each backed by own measured geometry -> passed.
shared_topology = {"shared_geometries": [{"geometry_id": 3, "object_ids": ["sh-1", "sh-2"]}]}
r26a = _identity([_circle_g(1, -1, 0), _circle_g(2, 1, 0), _arc_g(3)],
                [_obj("sh-1", [1, 3]), _obj("sh-2", [2, 3])],
                _circle_contract("圆", 2, "两个圆"), "画两个圆，半径1米",
                topology=shared_topology)
report["round2"]["shared_both_evidenced"] = {"status": r26a["status"]}
if r26a["status"] != "passed":
    failures.append(("round2", "shared_both_evidenced", r26a["status"], "passed"))

# R2-6b: second object only references the shared arc, no own measured evidence.
r26b = _identity([_circle_g(1, -1, 0), _arc_g(3)],
                [_obj("sh-1", [1]), _obj("sh-2", [3])],
                _circle_contract("圆", 2, "两个圆"), "画两个圆，半径1米",
                topology=shared_topology)
report["round2"]["shared_only_no_own_evidence"] = {
    "status": r26b["status"], "unmatched": r26b["unmatched_entries"],
}
if r26b["status"] == "passed":
    failures.append(("round2", "shared_only_no_own_evidence", r26b["status"], "not passed"))

# --- 8. Count regression: B2 missing object still failed; attribute not checked.
source8a = "画两个立方体并排，边长2米"
steps8a = [rectangle_polyline_step("cube-1", -1, -1, 2, 2)]
r8a = interpret_construction_request(source8a, lambda *_: deepcopy(payload_for(steps8a, source8a)),
                                     force_structured_model=True)
count8a = (r8a.get("source_acceptance", {})
           .get("object_count_consistency_acceptance", {}))
report["count_regression"]["b2_missing_object"] = {
    "status": count8a.get("status"),
    "unknown": count8a.get("unknown_requirements"),
    "layers": entry_layers(r8a),
}
if count8a.get("status") != "failed":
    failures.append(("count", "b2", count8a.get("status"), "failed"))

source8b = "一个立方体有12条棱"
r8b_count = _object_identity_consistency(
    trial_result=None, composition_contract=None, structure_contract=None,
    scalar_contract={"subjects": ["立方体"]}, source=source8b)
# Count-side helper on the same no-baseline source, kept for regression parity.
count8b = _logical_object_count_consistency(
    trial_result=None, composition_contract=None, structure_contract=None,
    scalar_contract={"subjects": ["立方体"]}, source=source8b)
report["count_regression"]["attribute_numbers"] = {
    "count_status": count8b.get("status"),
    "identity_status": r8b_count.get("status"),
}
if count8b.get("status") != "not_checked":
    failures.append(("count", "attribute", count8b.get("status"), "not_checked"))

report["failures"] = failures
print(json.dumps(report, ensure_ascii=False, indent=2))
if failures:
    sys.exit(1)
