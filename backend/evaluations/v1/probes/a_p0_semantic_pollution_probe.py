"""Read-only P0 probe: trace four corpus inputs through the backend classification layers.

Zero model call, no geometry measurement, no candidate decision. Pure standard
library plus existing read-only backend functions. Run from the backend/ dir:

    python -m evaluations.v1.probes.a_p0_semantic_pollution_probe

Output: probes/a_p0_four_cases_semantic_trace.json (next to this file).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from app.cad_creation_intent import local_creation_objects
from app.cad_requirement_contract import requirement_contract
from app.agent_skills import parameterize_design
from app.cad_semantic_acceptance import semantic_requirements
from app.cad_feature_contract import (
    build_feature_source_index,
    build_feature_contracts,
    real_source_facts,
)
from app.cad_semantic_acceptance import verify_semantic_requirements
from app.cad_structure_contract import StructureContractError

HEART_LIKE_PTS = [(600, 3800), (2000, 2400), (3400, 3800),
                  (3600, 1600), (2000, 0), (400, 1600)]
RECT_PTS = [(0, 0), (4000, 0), (4000, 4000), (0, 4000)]


def _polyline(pts, gtype="polyline"):
    return [{"id": 1, "type": gtype, "closed": True,
             "vertices": [{"x": x, "y": y} for x, y in pts]}]


def _dispatch_replay(key, source, geometries):
    """Full dispatch/acceptance replay on the pre-fix snapshot (no model call)."""
    try:
        result = verify_semantic_requirements(source, geometries)
        return {"key": key, "source": source, "outcome": "returned",
                "status": result["status"], "coverage": result["coverage"],
                "raised_check": None, "measurements": None}
    except StructureContractError as exc:
        details = getattr(exc, "details", {}) or {}
        measurements = details.get("measurements")
        return {"key": key, "source": source, "outcome": "raised",
                "status": None, "coverage": None,
                "raised_check": details.get("check"),
                "measurements": {
                    "observed_triangular_regions":
                        (measurements or {}).get("observed_triangular_regions"),
                    "required_relation":
                        (measurements or {}).get("required_relation"),
                }}

CASES = {
    "A1": "生成一个闭合爱心轮廓，宽度4米，高度4米",
    "A9": "生成一个左右对称、平滑闭合的爱心，中心在(2,3)，宽4米高4米",
    "C10": "生成一个爱心和一个五角星，爱心在左，五角星在右",
    "C26": "生成一个大写字母A的轮廓，高3米宽2米",
}

HEART_RE = re.compile(r"爱心|心形")
LETTER_RE = re.compile(r"大写字母\s*A", re.I)


def _match(regex, text):
    match = regex.search(text)
    if not match:
        return None
    return {"start": match.start(), "end": match.end(), "text": match[0],
            "count": len(regex.findall(text))}


def _sidecar_shadow(contract, source_index, case_id, subjects):
    """Shadow-only feature-contract wiring; never consumed by a decision path."""
    facts = real_source_facts(contract)
    declarations = []
    if case_id == "C10":
        # Two declared subjects without a unique source-to-part correspondence.
        declarations.append({
            "feature_id": f"fc-{case_id}-multi",
            "feature_class": "boundary_extremum",
            "source_class": "explicit",
            "source_refs": [f["source_id"] for f in facts] or ["user-1"],
            "evidence": None,
            "target_ref": None,
            "target_refs": ["step-1:outline", "step-2:outline"],
            "acceptance_scope": "advisory",
        })
    else:
        fact = facts[0] if facts else None
        refs = [fact["source_id"]] if fact else ["user-1"]
        evidence = None
        if fact and fact.get("evidence"):
            evidence = {
                "source_ref": fact["source_id"],
                "start": fact["evidence"]["start"],
                "end": fact["evidence"]["end"],
                "text": fact["evidence"]["text"],
                "source_revision": source_index["contract_version"],
            }
        declarations.append({
            "feature_id": f"fc-{case_id}-1",
            "feature_class": "boundary_extremum",
            "source_class": "explicit",
            "source_refs": refs,
            "evidence": evidence,
            "target_ref": "step-1:outline",
            "acceptance_scope": "mandatory",
        })
    result = build_feature_contracts(contract, source_index, declarations)
    return {
        "records": [
            {"feature_id": r["feature_id"], "valid": r["valid"],
             "source_class": r["source_class"], "acceptance_scope": r["acceptance_scope"],
             "source_refs": r["source_refs"], "errors": [e["code"] for e in result["errors"]
                                                         if e["feature_id"] == r["feature_id"]]}
            for r in result["records"]
        ],
        "bindings": result["bindings"],
        "errors": result["errors"],
        "shadow_only": result["shadow_only"],
    }


def trace_case(case_id, text):
    stripped = text.strip()
    contract = requirement_contract([{"source_id": "user-1", "text": stripped}])
    bundle = build_feature_source_index(contract)
    source_index = bundle["source_index"]
    requirements = semantic_requirements(stripped)
    return {
        "case_id": case_id,
        "input": text,
        "entry_normalization": {
            "trim_only": text != stripped,
            "lowercase_applied_to_rule_text": False,
            "prefix_or_suffix_added": False,
        },
        "local_creation_objects": local_creation_objects(stripped),
        "regex_matches": {
            "heart": _match(HEART_RE, stripped),
            "capital_a": _match(LETTER_RE, stripped),
        },
        "requirement_contract": {
            "subjects": contract["subjects"],
            "facts": [
                {"fact_id": f["fact_id"], "source_id": f["source_id"], "field": f["field"],
                 "operator": f["operator"], "value_mm": f["value_mm"], "binding": f["binding"],
                 "status": f["status"], "evidence": f["evidence"]}
                for f in contract["facts"]
            ],
        },
        "semantic_requirements": [
            {"kind": r["kind"], "origin": r.get("origin"),
             "source_evidence": r.get("source_evidence")}
            for r in requirements
        ],
        "parameterize_design": parameterize_design(stripped),
        "sidecar_shadow": _sidecar_shadow(contract, source_index, case_id,
                                           contract["subjects"]),
    }


MIXED_TURNS = [
    ("heart_then_A", "生成一个爱心轮廓。\n生成一个大写字母A的轮廓"),
    ("A_then_heart", "生成一个大写字母A的轮廓。\n生成一个爱心轮廓。"),
    ("three_objects", "生成一个爱心、一个五角星和一个圆形。"),
]

# Deterministic rule replay on other corpus shape cases; no model call.
REPLAY_CASES = {
    "C4": "画一个三角形轮廓，顶点(0,0)(3,0)(1.5,2.6)",
    "C5": "生成一个正五边形，外接圆半径1.5米",
    "C13": "生成一个正六边形，边长1米",
    "C15": "画一个圆环，外圆半径1米，内圆半径1米",
    "C16": "生成一个房子轮廓，宽4米高3米，屋顶是三角形，下面加一个门",
    "C18": "生成一个星形线（内凹四角星），最大半径2米",
    "C19": "生成一个心形线（cardioid），尖点朝下，最大宽度3米",
    "C29": "画一个回字形（嵌套正方形），外框边长2米，内框边长1米，内框居中",
    "C32": "画一个六角螺母轮廓，外六角外接圆半径1.5米，中心圆孔半径0.8米",
}


def trace_mixed(key, text):
    return {
        "key": key,
        "text": text,
        "local_creation_objects": local_creation_objects(text),
        "semantic_requirements": [r["kind"] for r in semantic_requirements(text)],
    }


def main():
    payload = {
        "schema": "cad.p0-semantic-pollution-trace.v1",
        "model_calls": 0,
        "cases": [trace_case(case_id, text) for case_id, text in CASES.items()],
        "mixed_turn_traces": [trace_mixed(k, t) for k, t in MIXED_TURNS],
        "replay_cases": [
            {"case_id": k, "text": t,
             "local_creation_objects": local_creation_objects(t),
             "semantic_requirements": [r["kind"] for r in semantic_requirements(t)]}
            for k, t in REPLAY_CASES.items()
        ],
        "dispatch_replay": [
            _dispatch_replay("heart_passing_polyline", CASES["A1"],
                             _polyline(HEART_LIKE_PTS)),
            _dispatch_replay("rectangle_fails_heart_features", CASES["A1"],
                             _polyline(RECT_PTS)),
            _dispatch_replay("spline_unsupported_type", CASES["A1"],
                             _polyline(HEART_LIKE_PTS, "spline")),
        ],
    }
    out = Path("evaluations/v1/probes/a_p0_four_cases_semantic_trace.json")
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    for case in payload["cases"]:
        kinds = [r["kind"] for r in case["semantic_requirements"]]
        print(case["case_id"], "->", kinds, "| shape=", case["parameterize_design"].get("shape"))


if __name__ == "__main__":
    main()
