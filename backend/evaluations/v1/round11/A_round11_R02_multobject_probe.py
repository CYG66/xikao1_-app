# -*- coding: utf-8 -*-
"""Round11 R-02 two-producer short-circuit fix probe (Agent A), zero model.

Drives the real production entry ``interpret_construction_request`` with a local
deterministic callback returning a controlled plan fixture, and also records
the direct producer return. No real model call, no network.

Rules under test:
  A. No applicable requirement -> stays ``not_checked``, discarded by the gate.
  B. Requirement recognized from source, multiple objects unscoped ->
     ``unverified`` + ``review_required=True`` + ``coverage=unscoped_multiple_objects``
     with auditable clause detail; report retained by the existing gate.
  C. Single-object measurement / failure-to-raise behavior unchanged.

Usage (from ``backend/``)::

    python evaluations/v1/round11/A_round11_R02_multobject_probe.py \
        --out evaluations/v1/round11/A_round11_R02_multobject_probe.json
"""
from __future__ import annotations

import argparse
import copy
import datetime
import json
import math
import pathlib
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[3]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.cad_construction_interpreter import interpret_construction_request  # noqa: E402
from app.cad_candidate_state import candidate_is_accepted, accepted_project_view  # noqa: E402
from app.cad_creation_intent import local_creation_objects  # noqa: E402
from app.cad_projection_acceptance import verify_projection_requirements  # noqa: E402
from app.cad_repetition_acceptance import verify_repetition_requirements  # noqa: E402
from app.cad_structure_contract import StructureContractError  # noqa: E402

MULTI_GEOM = [{"id": 1, "type": "circle", "center": {"x": 0, "y": 3000}, "radius": 1000},
              {"id": 2, "type": "rectangle", "origin": {"x": -1000, "y": -1000},
               "width": 2000, "height": 2000}]

PROJECTION_MULTI_SOURCE = (
    "生成一个圆形和一个立方体，圆形在立方体正上方。圆半径1米，圆心(0,3)；"
    "立方体宽2米高2米，等轴投影，12条棱，棱长100毫米；坐标单位米")
REPETITION_MULTI_SOURCE = (
    "生成一个圆形和一个齿轮轮廓，圆形在齿轮上方。圆半径1米，圆心(0,3)；"
    "齿轮轮廓宽2米高2米，8个齿，外径2米，齿根圆直径1.5米，齿顶角宽15度；坐标单位米")
NO_MATCH_MULTI_SOURCE = "生成一个圆形和一个矩形，宽2米高2米"
PROJECTION_SINGLE_SOURCE = "画一个立方体的二维等轴投影，各投影棱长2米，包含隐藏的12条棱线"
PROJECTION_BAD_SOURCE = "画一个立方体，等轴投影，12条棱，棱长100毫米"
REPETITION_TOOTH_SOURCE = "生成一个齿轮轮廓，外径2米，8个齿，齿根圆直径1.5米，各齿齿顶角宽15度"
REPETITION_BAD_SOURCE = "3条对称分支，每条分支带2个侧枝"


def _two_object_payload(source: str, label2: str) -> dict:
    return {
        "schema_version": "cad.construction-interpretation.v1",
        "is_construction_request": True,
        "confidence": 0.99,
        "evidence_text": [source],
        "assumptions": [],
        "plan": {"units": "m", "steps": [
            {"op": "add_circle", "step_id": "circle", "output_ref": "circle",
             "semantic": {"label": "圆形"}, "center": {"x": 0, "y": 3}, "radius": 1},
            {"op": "add_rectangle", "step_id": "rect", "output_ref": "rect",
             "semantic": {"label": label2}, "origin": {"x": -1, "y": -1},
             "width": 2, "height": 2},
        ]},
    }


def _projection_edges():
    vectors = [(0, 2000), (-math.sqrt(3) * 1000, -1000), (math.sqrt(3) * 1000, -1000)]
    points = {bits: {k: sum(bits[i] * vectors[i][axis] for i in range(3))
                     for axis, k in enumerate(("x", "y"))}
              for bits in __import__("itertools").product((0, 1), repeat=3)}
    result = []
    for bits, start in points.items():
        for axis in range(3):
            if bits[axis]:
                continue
            end = list(bits)
            end[axis] = 1
            result.append({"id": len(result) + 1, "type": "line",
                           "start": start, "end": points[tuple(end)]})
    return result


def _tooth_geometry():
    points = []
    for i in range(8):
        for delta, radius in [(-7.5, 1000), (7.5, 1000), (15, 750), (30, 750)]:
            angle = math.radians(i * 45 + delta)
            points.append({"x": radius * math.cos(angle), "y": radius * math.sin(angle)})
    return [{"id": 1, "type": "polyline", "closed": True, "vertices": points}]


PRODUCERS = {"projection": verify_projection_requirements,
             "repetition": verify_repetition_requirements}

# name, source, producer, geometry, payload kind, second label, expectation
SCENARIOS = [
    ("projection_multi_object_B", PROJECTION_MULTI_SOURCE, "projection", MULTI_GEOM,
     "two", "立方体", "unverified"),
    ("repetition_multi_object_B", REPETITION_MULTI_SOURCE, "repetition", MULTI_GEOM,
     "two", "齿轮轮廓", "unverified"),
    ("projection_no_match_multi_object_A", NO_MATCH_MULTI_SOURCE, "projection", MULTI_GEOM,
     "two", "矩形", "not_checked"),
    ("repetition_no_match_multi_object_A", NO_MATCH_MULTI_SOURCE, "repetition", MULTI_GEOM,
     "two", "矩形", "not_checked"),
    ("projection_single_success_C", PROJECTION_SINGLE_SOURCE, "projection",
     _projection_edges(), "none", None, "passed"),
    ("repetition_single_success_C", REPETITION_TOOTH_SOURCE, "repetition", _tooth_geometry(),
     "none", None, "partial"),
    ("projection_single_bad_geo_C", PROJECTION_BAD_SOURCE, "projection",
     [{"id": 1, "type": "line", "start": {"x": 0, "y": 0}, "end": {"x": 1000, "y": 0}}],
     "none", None, "structure_contract_error"),
    ("repetition_single_bad_geo_C", REPETITION_BAD_SOURCE, "repetition",
     [{"id": 1, "type": "line", "start": {"x": 0, "y": 0}, "end": {"x": 1000, "y": 0}}],
     "none", None, "structure_contract_error"),
]


def _direct_producer(channel, source, geometries):
    fn = PRODUCERS[channel]
    try:
        report = fn(source, geometries)
        return {"producer": channel, "outcome": "returned",
                "status": report.get("status"),
                "coverage": report.get("coverage"),
                "review_required": report.get("review_required"),
                "check_count": len(report.get("checks") or []),
                "unknown_requirements": report.get("unknown_requirements"),
                "report_keys": sorted(report.keys())}
    except StructureContractError as exc:
        return {"producer": channel, "outcome": "structure_contract_error",
                "message": str(exc)[:160]}
    except Exception as exc:  # audit record only
        return {"producer": channel, "outcome": type(exc).__name__, "message": str(exc)[:160]}


def _record(name, source, channel, geometries, kind, label2, expectation):
    direct = _direct_producer(channel, source, geometries)
    record = {"scenario": name, "source": source, "expectation": expectation,
              "local_objects": local_creation_objects(source),
              "object_count": len(local_creation_objects(source)),
              "direct_producer": direct}
    if kind == "two":
        payload = _two_object_payload(source, label2)
        result = interpret_construction_request(
            source, lambda *_: copy.deepcopy(payload), force_structured_model=True)
        summary = result.get("acceptance_summary")
        source_acc = result.get("source_acceptance")
        retained = None
        if isinstance(source_acc, dict):
            key = {"projection": "projection_acceptance",
                   "repetition": "repetition_acceptance"}[channel]
            report = source_acc.get(key)
            if isinstance(report, dict):
                retained = {"status": report.get("status"),
                            "coverage": report.get("coverage"),
                            "review_required": report.get("review_required"),
                            "unknown_requirements": report.get("unknown_requirements")}
        record.update({
            "interpreter_status": result.get("status"),
            "construction_error": result.get("construction_error"),
            "retained_channel_report": retained,
            "summary": summary,
            "candidate_is_accepted": candidate_is_accepted(result),
        })
        view = accepted_project_view({"variants": [result],
                                      "selected_variant_id": result.get("id")})
        record["visible_variant_count"] = len(view.get("variants") or [])
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    rows = []
    for name, source, channel, geometries, kind, label2, expectation in SCENARIOS:
        try:
            rows.append(_record(name, source, channel, geometries, kind, label2, expectation))
        except Exception as exc:  # audit record only
            rows.append({"scenario": name, "outcome": type(exc).__name__,
                         "message": str(exc)[:200]})
    result = {
        "probe": "a_round11_r02_multobject_probe",
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "model_requests": 0,
        "network": False,
        "rules": {"A": "no requirement -> not_checked, discarded",
                  "B": "recognized requirement + multi-object unscoped -> unverified/"
                       "review_required/unscoped_multiple_objects with detail",
                  "C": "single-object measurement and contract-error behavior unchanged"},
        "scenarios": rows,
    }
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    for r in rows:
        d = r.get("direct_producer") or {}
        print(r["scenario"], "| expectation=", r.get("expectation"),
              "| producer=", d.get("outcome"), d.get("status"),
              "| retained=", (r.get("retained_channel_report") or {}).get("status")
              if r.get("retained_channel_report") else None,
              "| accepted=", r.get("candidate_is_accepted"))


if __name__ == "__main__":
    main()
