# -*- coding: utf-8 -*-
"""Round8 C-line P0 production caller-wiring probe (zero model, offline).

All geometry below is a **reconstructed fixture (重建夹具, 非历史回放)**:
synthetic polylines built in this script, not a persisted run artifact and not a
replay of any recorded output. No real model request is issued.

Usage (from ``backend/``)::

    python evaluations/v1/round8/c_round8_wire_probe.py --out evaluations/v1/round8/c_round8_wire_results.json
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import pathlib
import subprocess
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[3]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.cad_construction import execute_construction_plan  # noqa: E402
from app.cad_construction_interpreter import (  # noqa: E402
    _semantic_backend_binding,
    _verify_semantic_requirements_bound,
    construction_acceptance_summary,
)
from app.cad_candidate_state import (  # noqa: E402
    candidate_is_accepted,
    candidate_is_reviewable_draft,
)
from app.cad_semantic_dispatch import bind_targets  # noqa: E402

FIXTURE_NOTE = "重建夹具（非历史回放）：脚本内合成折线，非落盘真实几何，非历史回放"
BASELINE_SHA = "7567f7bb32d9571048f1d66deb8124df3bcf9d02"
PATCH_SHA = "e7831921ef904deaa893573da8cc793056a9cf41"

HEART_TEXT = "生成一个闭合爱心轮廓，宽度4米，高度4米"
HEART_RECON_TEXT = "生成一个左右对称、平滑闭合的爱心，宽4米高4米"
C10_TEXT = "生成一个爱心和一个五角星，爱心在左，五角星在右"
LETTER_TEXT = "生成一个大写字母A的轮廓，高3米宽2米"
HOUSE_TEXT = "生成一个房子轮廓，宽4米高3米，屋顶是三角形，下面加一个门"


def _poly(i, points):
    return {"id": i, "type": "polyline", "closed": True,
            "vertices": [{"x": x, "y": y} for x, y in points]}


def _step(step_id, ref, label, points, closed=True):
    return {"op": "add_polyline", "step_id": step_id, "output_ref": ref,
            "semantic": {"label": label}, "closed": closed,
            "vertices": [{"x": x, "y": y} for x, y in points]}


def _heart(scale=2000):
    norm = [(0.20, 0.90), (0.50, 0.62), (0.80, 0.90), (0.95, 0.50),
            (0.75, 0.20), (0.50, 0.00), (0.25, 0.20), (0.05, 0.50)]
    return [(round(x * scale, 3), round(y * scale, 3)) for x, y in norm]


def _star(ox=3000, cy=1000, ro=1000, ri=400):
    points = []
    for k in range(10):
        r = ro if k % 2 == 0 else ri
        ang = math.pi / 2 + k * math.pi / 5
        points.append((round(r * math.cos(ang) + ox, 3),
                       round(r * math.sin(ang) + cy, 3)))
    return points


def _letter_outer():
    return [(0, 0), (850, 3000), (1150, 3000), (2000, 0), (1550, 0),
            (1350, 750), (650, 750), (450, 0)]


def _letter_triangle():
    return [(800, 1400), (1200, 1400), (1000, 2400)]


def _house_outer():
    return [(0, 0), (4000, 0), (4000, 2000), (2000, 3000), (0, 2000)]


def _house_door():
    return [(1500, 0), (2500, 0), (2500, 1500), (1500, 1500)]


def _exec(steps):
    return execute_construction_plan({"units": "mm", "steps": steps})


GIT_EXE = r"C:\Users\29924\Softwares\git\Git\cmd\git.exe"


def _git(*args: str) -> str:
    return subprocess.run(
        [GIT_EXE, *args], cwd=str(BACKEND.parent), check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def _proof_brief(proof: dict) -> dict:
    return {
        "status": proof.get("status"),
        "review_required": proof.get("review_required"),
        "coverage": proof.get("coverage"),
        "reason": proof.get("reason"),
        "binding": proof.get("binding"),
        "object_acceptance": [
            {"geometry_ids": t["target_ref"]["geometry_ids"],
             "status": t["status"], "reason": t.get("reason"),
             "profile": t.get("profile")}
            for t in proof.get("object_acceptance", [])
        ],
        "unsupported_objects": proof.get("unsupported_objects"),
    }


def main() -> dict:
    result: dict[str, Any] = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "fixture_note": FIXTURE_NOTE,
        "zero_model": True,
        "git": {},
        "call_sites": [
            {
                "index": 1,
                "file": "backend/app/cad_construction_interpreter.py",
                "function": "interpret_construction_request",
                "line": 973,
                "path_category": "正常构造（执行后验收）",
                "before_args": "verify_semantic_requirements(original_requirement, result['geometries'])",
                "after_args": "_verify_semantic_requirements_bound(original_requirement, result)",
                "result_source_line": "result = execute_construction_plan(plan)  (line 911)",
                "trusted_binding_available": True,
            },
            {
                "index": 2,
                "file": "backend/app/cad_construction_interpreter.py",
                "function": "interpret_construction_request",
                "line": 1022,
                "path_category": "诊断回放（assertion_failed 去断言诊断试算）",
                "before_args": "verify_semantic_requirements(original_requirement, diagnostic_trial['geometries'])，返回值丢弃，仅捕 StructureContractError",
                "after_args": "_verify_semantic_requirements_bound(original_requirement, diagnostic_trial)，记录 status/review_required/reason/coverage/binding",
                "result_source_line": "diagnostic_trial=execute_construction_plan(diagnostic_plan)  (line 1020)",
                "trusted_binding_available": True,
            },
            {
                "index": 3,
                "file": "backend/app/cad_construction_interpreter.py",
                "function": "interpret_construction_request",
                "line": 1079,
                "path_category": "修复试算（astroid 平滑性断言移除）",
                "before_args": "verify_semantic_requirements(original_requirement, trial['geometries'])",
                "after_args": "_verify_semantic_requirements_bound(original_requirement, trial)",
                "result_source_line": "trial=execute_construction_plan(corrected)  (line 1078)",
                "trusted_binding_available": True,
            },
            {
                "index": 4,
                "file": "backend/app/cad_construction_interpreter.py",
                "function": "interpret_construction_request",
                "line": 1112,
                "path_category": "修复试算（regular polygon 边界断言移除）",
                "before_args": "verify_semantic_requirements(original_requirement, trial['geometries'])",
                "after_args": "_verify_semantic_requirements_bound(original_requirement, trial)",
                "result_source_line": "trial=execute_construction_plan(corrected)  (line 1107)",
                "trusted_binding_available": True,
            },
        ],
        "cases": {},
        "negative_binding_matrix": [],
        "gate_audit": {},
    }

    # Git provenance
    try:
        result["git"] = {
            "head_sha": _git("rev-parse", "HEAD"),
            "head_parent": _git("rev-parse", "HEAD^"),
            "baseline_sha": BASELINE_SHA,
            "patch_sha": PATCH_SHA,
            "patch_parent": _git("rev-parse", f"{PATCH_SHA}^"),
            "branch": _git("branch", "--show-current"),
            "patch_show_stat": _git("show", "--stat", "--oneline", PATCH_SHA),
        }
    except Exception as exc:  # pragma: no cover - probe diagnostic only
        result["git"]["error"] = str(exc)

    # A1 single heart
    r_a1 = _exec([_step("h", "heart", "爱心", _heart(4000))])
    result["cases"]["A1_single_heart"] = _proof_brief(
        _verify_semantic_requirements_bound(HEART_TEXT, r_a1))

    # A9 reconstructed fixture (explicitly not a historical replay)
    r_a9 = _exec([_step("h", "heart", "爱心", _heart(2000))])
    result["cases"]["A9_reconstructed_fixture"] = {
        "fixture_note": FIXTURE_NOTE,
        **_proof_brief(_verify_semantic_requirements_bound(HEART_RECON_TEXT, r_a9)),
    }

    # C10 heart + star
    r_c10 = _exec([
        _step("h", "heart", "爱心", _heart(2000)),
        _step("s", "star", "五角星", _star()),
    ])
    result["cases"]["C10_heart_star"] = _proof_brief(
        _verify_semantic_requirements_bound(C10_TEXT, r_c10))

    # C26 letter A (inherited partial / review_required=False)
    r_c26 = _exec([
        _step("o", "outer", "字母A外轮廓", _letter_outer()),
        _step("t", "tri", "三角区域", _letter_triangle()),
    ])
    proof_c26 = _verify_semantic_requirements_bound(LETTER_TEXT, r_c26)
    summary_c26 = construction_acceptance_summary(
        preflight_structure=None, structure_contract=None, structure_validation=None,
        composition_contract=None, composition_validation=None,
        source_acceptance={"coverage": "partial", "unknown_requirements": [],
                           "semantic_acceptance": proof_c26, "checks": []})
    result["cases"]["C26_letter_a"] = {
        "wrapper_proof": _proof_brief(proof_c26),
        "summary": summary_c26,
        "candidate_accepted": candidate_is_accepted({"acceptance_summary": summary_c26}),
        "candidate_reviewable_draft": candidate_is_reviewable_draft({"acceptance_summary": summary_c26}),
    }

    # Unknown kind
    r_unknown = _exec([_step("v", "vase", "花瓶", _heart(1000))])
    result["cases"]["unknown_kind"] = _proof_brief(
        _verify_semantic_requirements_bound("画一个花瓶", r_unknown))

    # Negative binding matrix
    g1 = _poly(1, [(0, 0), (1000, 0), (1000, 1000), (0, 1000)])
    g2 = _poly(2, [(1000, 0), (2000, 0), (2000, 1000), (1000, 1000)])
    g3 = _poly(3, [(3000, 0), (4000, 0), (4000, 1000), (3000, 1000)])

    matrix = [
        ("missing_logical_objects", {"geometries": [g1]}, None),
        ("wrong_geometry_ref_id", {"geometries": [g1],
         "logical_objects": [{"object_id": "x", "geometry_refs": [999]}]}, None),
        ("duplicate_geometry_ref", {"geometries": [g1],
         "logical_objects": [{"object_id": "x", "geometry_refs": [1, 1]}]}, None),
        ("stale_geometry_ref", {"geometries": [g1],
         "logical_objects": [{"object_id": "x", "geometry_refs": [1, 2]}]}, None),
        ("model_declared_id_without_refs", {"geometries": [g1],
         "logical_objects": [{"object_id": "model-claimed", "label": "爱心"}]}, None),
        ("unowned_active_geometry", {"geometries": [g1, g2],
         "logical_objects": [{"object_id": "x", "geometry_refs": [1]}]}, None),
    ]
    for name, payload, _ in matrix:
        binding = _semantic_backend_binding(payload)
        result["negative_binding_matrix"].append({
            "case": name, "trust": binding["trust"],
            "issues": binding["issues"],
        })

    # Overlap kept separate / one object multi-segment kept together
    overlap = _semantic_backend_binding({
        "geometries": [g1, g2],
        "logical_objects": [{"object_id": "a", "geometry_refs": [1]},
                            {"object_id": "b", "geometry_refs": [2]}],
        "topology": {"schema_version": "cad.topology.v1", "shared_geometries": [], "relations": []}})
    result["negative_binding_matrix"].append({
        "case": "overlapping_objects_kept_separate",
        "trust": overlap["trust"],
        "targets": [t["target_ref"]["geometry_ids"]
                    for t in bind_targets([g1, g2], overlap["logical_objects"], overlap["topology"])],
    })
    multiseg = _semantic_backend_binding({
        "geometries": [g1, g3],
        "logical_objects": [{"object_id": "one", "geometry_refs": [1, 3]}],
        "topology": {"schema_version": "cad.topology.v1", "shared_geometries": [], "relations": []}})
    result["negative_binding_matrix"].append({
        "case": "one_object_disconnected_segments_not_split",
        "trust": multiseg["trust"],
        "targets": [t["target_ref"]["geometry_ids"]
                    for t in bind_targets([g1, g3], multiseg["logical_objects"], multiseg["topology"])],
    })

    # Gate audit: real producer state vs latent residual condition
    partial_false = {"status": "partial", "review_required": False,
                     "coverage": "straight_capital_a_structural_relations_only",
                     "checks": [{"status": "passed"}]}
    summary_real = construction_acceptance_summary(
        preflight_structure=None, structure_contract=None, structure_validation=None,
        composition_contract=None, composition_validation=None,
        source_acceptance={"coverage": "partial", "unknown_requirements": [],
                           "semantic_acceptance": partial_false, "checks": []})
    summary_residual = construction_acceptance_summary(
        preflight_structure=None, structure_contract=None, structure_validation=None,
        composition_contract=None, composition_validation=None,
        source_acceptance={"coverage": "complete", "unknown_requirements": [],
                           "semantic_acceptance": partial_false, "checks": []})
    result["gate_audit"] = {
        "real_producer_partial_coverage": {
            "summary_status": summary_real["status"],
            "review_required": summary_real["review_required"],
            "candidate_accepted": candidate_is_accepted({"acceptance_summary": summary_real}),
            "candidate_reviewable_draft": candidate_is_reviewable_draft({"acceptance_summary": summary_real}),
        },
        "residual_condition_complete_coverage": {
            "summary_status": summary_residual["status"],
            "review_required": summary_residual["review_required"],
            "candidate_accepted": candidate_is_accepted({"acceptance_summary": summary_residual}),
            "candidate_reviewable_draft": candidate_is_reviewable_draft({"acceptance_summary": summary_residual}),
            "note": "条件性残留：当前 source_acceptance 生产者不会为房屋/字母A通道输出 coverage=complete；仅当未来某生产者输出 complete 且无 unknown_requirements 时，partial+review_required=False 才会被正式接受。",
        },
    }
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(BACKEND / "evaluations" / "v1" / "round8" / "c_round8_wire_results.json"))
    args = parser.parse_args()
    report = main()
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"written": str(out), "cases": list(report["cases"].keys())}, ensure_ascii=False))
