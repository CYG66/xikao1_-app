# -*- coding: utf-8 -*-
"""Round8 A-line P0 exhaustive dispatch + P0' per-object acceptance probe.

Offline, deterministic, zero model calls, zero network. All geometry below is
a **reconstructed fixture (非历史回放)**: synthetic polylines built in this
script, not a persisted run artifact and not a replay of any recorded output.

Usage (from ``backend/``)::

    python evaluations/v1/round8/a_round8_p0_probe.py \
        [--baseline-snapshot PATH] [--patched-snapshot PATH] [--out PATH]
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import pathlib
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[3]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.cad_semantic_acceptance import (  # noqa: E402
    semantic_requirements,
    verify_semantic_requirements,
)
import app.cad_semantic_acceptance as acceptance_mod  # noqa: E402
from app.cad_semantic_dispatch import (  # noqa: E402
    DISPATCH_CHANNELS,
    bind_targets,
    classify_profile,
    heart_features,
)
from app.cad_structure_contract import StructureContractError  # noqa: E402

FIXTURE_NOTE = "重建夹具（非历史回放）：脚本内合成折线，非落盘真实几何，非历史回放"

# Baseline (independently certified by D-line; see round8 report).
BASELINE_SHA = "7567f7bb32d9571048f1d66deb8124df3bcf9d02"
PREFIX_ACCEPTANCE_BLOB_SHA1 = "7ab40244c1428eb333005bb647e694b007d43b10"
PREFIX_ACCEPTANCE_BLOB_SHA256_LF = "c9dcc002a6f3212a49a796c380cf05efb8521e231f6457d13be363775f8f45ef"

CASES = {
    "A1": "生成一个闭合爱心轮廓，宽度4米，高度4米",
    "A9": "生成一个左右对称、平滑闭合的爱心，中心在(2,3)，宽4米高4米",
    "C10": "生成一个爱心和一个五角星，爱心在左，五角星在右",
    "C26": "生成一个大写字母A的轮廓，高3米宽2米",
}

HEART_NORM = [
    (0.20, 0.90), (0.50, 0.62), (0.80, 0.90), (0.95, 0.50),
    (0.75, 0.20), (0.50, 0.00), (0.25, 0.20), (0.05, 0.50),
]


def heart(i=1, scale=2000.0, ox=0.0):
    return {"id": i, "type": "polyline", "closed": True, "selected": True,
            "vertices": [{"x": round(x * scale + ox, 3), "y": round(y * scale, 3)}
                         for x, y in HEART_NORM]}


def star(i=2, ox=3000.0, ro=1000.0, ri=400.0, cy=1000.0):
    pts = []
    for k in range(10):
        r = ro if k % 2 == 0 else ri
        ang = math.pi / 2 + k * math.pi / 5
        pts.append({"x": round(r * math.cos(ang) + ox, 3),
                    "y": round(r * math.sin(ang) + cy, 3)})
    return {"id": i, "type": "polyline", "closed": True, "selected": True, "vertices": pts}


def pentagon(i=3, r=1000.0, cy=1000.0):
    pts = [{"x": round(r * math.cos(math.pi / 2 + k * math.tau / 5), 3),
            "y": round(r * math.sin(math.pi / 2 + k * math.tau / 5) + cy, 3)} for k in range(5)]
    return {"id": i, "type": "polyline", "closed": True, "selected": True, "vertices": pts}


def letter_outer():
    return {"id": 1, "type": "polyline", "closed": True, "vertices": [
        {"x": x, "y": y} for x, y in
        [(0, 0), (850, 3000), (1150, 3000), (2000, 0), (1550, 0),
         (1350, 750), (650, 750), (450, 0)]]}


def letter_triangle():
    return {"id": 2, "type": "polyline", "closed": True, "vertices": [
        {"x": x, "y": y} for x, y in [(800, 1400), (1200, 1400), (1000, 2400)]]}


GEOMETRIES = {
    "A1": [heart(1, 4000.0)],
    "A9": [heart(1, 4000.0)],
    "C10": [heart(1, 2000.0), star(2)],
    "C26": [letter_outer(), letter_triangle()],
}
LOGICAL = {
    "C10": [{"object_id": "heart-1", "geometry_refs": [1], "label": "爱心"},
            {"object_id": "star-1", "geometry_refs": [2], "label": "五角星"}],
}


def _run(cid, text, geoms, logical=None):
    reqs = semantic_requirements(text)
    try:
        res = verify_semantic_requirements(text, geoms, logical_objects=logical)
        return {"requirements_kinds": [r.get("kind") for r in reqs],
                "result": {"status": res.get("status"), "coverage": res.get("coverage"),
                           "review_required": res.get("review_required"),
                           "reason": res.get("reason"),
                           "checks": [c.get("name") for c in res.get("checks", [])],
                           "object_acceptance": res.get("object_acceptance"),
                           "unsupported_objects": res.get("unsupported_objects")},
                "error": None}
    except StructureContractError as exc:
        return {"requirements_kinds": [r.get("kind") for r in reqs], "result": None,
                "error": {"type": "StructureContractError", "message": str(exc),
                          "check": (exc.details or {}).get("check"),
                          "target_ref": (exc.details or {}).get("target_ref"),
                          "failed_features": (exc.details or {}).get("failed_features")}}


def unknown_kind_case():
    """N3: an unregistered kind must terminate in the unsupported branch."""
    orig = acceptance_mod.semantic_requirements
    acceptance_mod.semantic_requirements = lambda text: [
        {"kind": "mystery_contour", "instruction": "未知轮廓"}]
    traced = set()

    def tracer(frame, event, _arg, traced=traced):
        if frame.f_code.co_filename == acceptance_mod.__file__:
            traced.add(frame.f_code.co_name)

    sys.settrace(tracer)
    try:
        res = verify_semantic_requirements(CASES["A1"], [heart(1, 4000.0)])
    finally:
        sys.settrace(None)
        acceptance_mod.semantic_requirements = orig
    return {"status": res.get("status"), "review_required": res.get("review_required"),
            "reason": res.get("reason"), "checks": res.get("checks"),
            "unsupported_kind": res.get("unsupported_kind"),
            "letter_checker_reached": "_verify_capital_a_channel" in traced,
            "passed": (res.get("status") == "unverified" and res.get("review_required") is True
                        and res.get("checks") == []
                        and res.get("reason") == "no_verifier_for_kind"
                        and "_verify_capital_a_channel" not in traced)}


def negative_tests():
    out = {}
    c10 = _run("C10", CASES["C10"], GEOMETRIES["C10"], LOGICAL["C10"])
    oa = c10["result"]["object_acceptance"]
    heart_entry, star_entry = oa[0], oa[1]
    heart_b = heart_entry["target_ref"]["bounds"]
    star_b = star_entry["target_ref"]["bounds"]

    out["N1_no_count_skip"] = {
        "description": "两个对象都不得因数量为 2 而跳过验收",
        "object_count": len(oa),
        "statuses": [o["status"] for o in oa],
        "passed": len(oa) == 2 and heart_entry["status"] == "passed"
        and star_entry["status"] == "not_checked"}

    out["N2_heart_isolation"] = {
        "description": "爱心验收不得把五角星顶点当作自身轮廓",
        "heart_geometry_ids": heart_entry["target_ref"]["geometry_ids"],
        "star_geometry_ids": star_entry["target_ref"]["geometry_ids"],
        "heart_bounds": heart_b, "star_bounds": star_b,
        "heart_check_geometry_ids": heart_entry["target_ref"]["geometry_ids"],
        "disjoint_x": heart_b["max_x"] < star_b["min_x"],
        "star_outside_heart_bounds": all(
            not (heart_b["min_x"] <= p["x"] <= heart_b["max_x"]) for p in star(2)["vertices"]),
        "passed": heart_entry["target_ref"]["geometry_ids"] == [1]
        and heart_b["max_x"] < star_b["min_x"]}

    out["N3_unknown_kind_rejected"] = {"description": "未知语义不得通过默认检查器获得 PASS",
                                       **unknown_kind_case()}

    # N4: star-only single object rejected by the heart negative gate.
    try:
        verify_semantic_requirements(CASES["A1"], [star(1, ox=0.0)])
        n4 = {"raised": None, "passed": False}
    except StructureContractError as exc:
        n4 = {"raised": "StructureContractError",
              "check": (exc.details or {}).get("check"),
              "passed": (exc.details or {}).get("check") == "rejected_non_heart_profile"}
    out["N4_star_gate_rejects_single_star"] = n4

    # N5: convex non-heart polygon must fail heart features honestly.
    try:
        verify_semantic_requirements(CASES["A1"], [pentagon(1)])
        n5 = {"raised": None, "passed": False}
    except StructureContractError as exc:
        n5 = {"raised": "StructureContractError",
              "check": (exc.details or {}).get("check"),
              "failed_features": (exc.details or {}).get("failed_features"),
              "passed": (exc.details or {}).get("check") == "heart_bilateral_lobes_notch_and_lower_tip"}
    out["N5_convex_polygon_not_heart"] = n5
    return out


def calibration():
    fixtures = {
        "heart_single": [heart(1, 4000.0)],
        "star_single": [star(2, ox=0.0)],
        "regular_pentagon": [pentagon(3)],
        "rectangle": [{"id": 4, "type": "polyline", "closed": True, "selected": True,
                       "vertices": [{"x": 0, "y": 0}, {"x": 2000, "y": 0},
                                    {"x": 2000, "y": 1500}, {"x": 0, "y": 1500}]}],
    }
    rows = {}
    for name, geoms in fixtures.items():
        prof = classify_profile(geoms)
        feat = heart_features(geoms)
        rows[name] = {"profile": prof["profile"], "votes": prof["votes"],
                      "measurements": prof["measurements"], "heart_features": feat["features"]}
    return rows


def binding_matrix():
    targets = bind_targets(GEOMETRIES["C10"], logical_objects=LOGICAL["C10"])
    rows = []
    for t in targets:
        prof = classify_profile(t["geometries"])
        rows.append({"target_ref": t["target_ref"], "profile": prof["profile"],
                     "profile_measurements": prof["measurements"]})
    return rows


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_snapshot(path: str | None) -> dict:
    if not path:
        return {}
    p = pathlib.Path(path)
    if not p.exists():
        return {"missing": "snapshot file not supplied"}
    doc = json.loads(p.read_text(encoding="utf-8"))
    suites = {s["suite_id"]: s["counts"] for s in doc.get("suites", [])}
    collect = doc.get("collect_only", {})
    blocked = [{"module": b.get("module"), "exception": b.get("exception"),
                 "sub_class": b.get("sub_class")} for b in collect.get("blocked_modules", [])]
    return {"suites": suites,
            "collect_only": {"tests_collected": collect.get("tests_collected"),
                              "collection_errors": collect.get("collection_errors"),
                              "blocked_modules": blocked}}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-snapshot", default=None)
    parser.add_argument("--patched-snapshot", default=None)
    parser.add_argument("--out", default=str(pathlib.Path(__file__).with_suffix(".json")))
    args = parser.parse_args()

    cases = {cid: _run(cid, text, GEOMETRIES[cid], LOGICAL.get(cid))
             for cid, text in CASES.items()}

    doc = {
        "schema": "round8.a-p0.semantic-dispatch.v1",
        "generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "zero_real_model_calls": True,
        "zero_network": True,
        "fixture_note": FIXTURE_NOTE,
        "baseline_sha": BASELINE_SHA,
        "dispatch_matrix": DISPATCH_CHANNELS,
        "cases": cases,
        "binding_matrix_c10": binding_matrix(),
        "negative_tests": negative_tests(),
        "profile_calibration": calibration(),
        "regression": {"baseline": load_snapshot(args.baseline_snapshot),
                       "patched": load_snapshot(args.patched_snapshot)},
        "file_hashes": {
            "cad_semantic_acceptance.py": {
                "blob_sha1_at_baseline": PREFIX_ACCEPTANCE_BLOB_SHA1,
                "blob_sha256_lf_at_baseline": PREFIX_ACCEPTANCE_BLOB_SHA256_LF,
                "post_fix_sha256_disk": _sha256(BACKEND / "app" / "cad_semantic_acceptance.py"),
            },
            "cad_semantic_dispatch.py": {
                "post_fix_sha256_disk": _sha256(BACKEND / "app" / "cad_semantic_dispatch.py"),
            },
        },
    }
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"out": str(out), "cases": len(CASES),
                      "negative_passed": all(v.get("passed") for v in doc["negative_tests"].values())},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
