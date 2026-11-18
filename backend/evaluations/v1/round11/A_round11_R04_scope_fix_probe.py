"""Round11 R-04 offline probe: explicit / ambiguous / not-applicable star scope.

Zero model requests, zero network. Runs against local backend modules only.
Writes a machine-readable JSON snapshot alongside this script.
"""
import json
import math
import os
import sys

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, BACKEND)

from app.cad_semantic_acceptance import verify_semantic_requirements  # noqa: E402
from app.cad_semantic_dispatch import (  # noqa: E402
    STATE_FULLY_VERIFIED,
    STATE_NO_APPLICABLE_REQUIREMENT,
    STATE_UNVERIFIED_OR_PARTIAL,
    ambiguous_requirement_kinds_from_text,
    recognized_unverifiable_kinds_from_text,
    semantic_requirement_state,
    state_allows_summary_passed,
)


def star(i=2, ox=3000.0, ro=1000.0, ri=400.0, cy=1000.0):
    pts = []
    for k in range(10):
        r = ro if k % 2 == 0 else ri
        ang = math.pi / 2 + k * math.pi / 5
        pts.append({"x": round(r * math.cos(ang) + ox, 3),
                    "y": round(r * math.sin(ang) + cy, 3)})
    return {"id": i, "type": "polyline", "closed": True, "selected": True, "vertices": pts}


def regular_poly(i, n, r=1000.0, cy=1000.0):
    pts = [{"x": round(r * math.cos(k * math.tau / n), 3),
            "y": round(cy + r * math.sin(k * math.tau / n), 3)} for k in range(n)]
    return {"id": i, "type": "polyline", "closed": True, "selected": True, "vertices": pts}


def rect(i):
    return {"id": i, "type": "polyline", "closed": True, "selected": True,
            "vertices": [{"x": -1000, "y": 0}, {"x": 1000, "y": 0},
                         {"x": 1000, "y": 2000}, {"x": -1000, "y": 2000}]}


def circle(i):
    return {"id": i, "type": "circle", "center": {"x": 0, "y": 1000}, "radius": 1000}


HEART_NORM = [(0.20, 0.90), (0.50, 0.62), (0.80, 0.90), (0.95, 0.50),
              (0.75, 0.20), (0.50, 0.00), (0.25, 0.20), (0.05, 0.50)]


def heart(i=1, scale=2000.0):
    return {"id": i, "type": "polyline", "closed": True, "selected": True,
            "vertices": [{"x": round(x * scale, 3), "y": round(y * scale, 3)}
                         for x, y in HEART_NORM]}


def evaluate(text, geometries, logical=None):
    report = verify_semantic_requirements(text, geometries, logical_objects=logical)
    verdict = semantic_requirement_state(report, text)
    return {
        "text": text,
        "report_status": report.get("status"),
        "report_reason": report.get("reason"),
        "report_review_required": report.get("review_required"),
        "ambiguity_resolution": report.get("ambiguity_resolution"),
        "report_applicable": report.get("applicable_requirement_kinds"),
        "report_ambiguous": report.get("ambiguous_requirement_kinds"),
        "verdict_state": verdict["state"],
        "verdict_reasons": verdict["reasons"],
        "verdict_applicable": verdict["applicable_requirement_kinds"],
        "verdict_ambiguous": verdict["ambiguous_requirement_kinds"],
        "allows_summary_passed": state_allows_summary_passed(verdict),
        "object_acceptance": [
            {"object_id": (e.get("target_ref") or {}).get("object_id"),
             "geometry_ids": (e.get("target_ref") or {}).get("geometry_ids"),
             "profile": e.get("profile"), "status": e.get("status"),
             "reason": e.get("reason")}
            for e in report.get("object_acceptance") or []
        ],
    }


# 1. Text-layer classification
TEXT_CASES = [
    "五角星", "五芒星", "星形轮廓", "五角星形",
    "五角形", "星形", "星星", "星型",
    "星形线", "star", "five-pointed star",
]
text_scan = []
for expr in TEXT_CASES:
    text_scan.append({
        "expression": expr,
        "explicit_kinds": recognized_unverifiable_kinds_from_text(expr),
        "ambiguous_kinds": ambiguous_requirement_kinds_from_text(expr),
    })

# 2. Explicit wording: applicable, not_checked, review required, blocked
explicit_cases = [
    evaluate("画一个五角星", []),
    evaluate("画一个五芒星", []),
    evaluate("画一个星形轮廓", []),
]

# 3. Ambiguous wording, three geometry outcomes
ambiguous_cases = [
    evaluate("画一个五角形", [star(1, ox=0.0)]),
    evaluate("画一个五角形", [regular_poly(1, 5)]),
    evaluate("画一个星星", []),
    evaluate("画一个星形", []),
]

# 4. Ordinary shapes without any star/ambiguous signal: released
ordinary_cases = [
    evaluate("画一个六边形", [regular_poly(1, 6)]),
    evaluate("画一个圆", [circle(1)]),
    evaluate("画一个矩形", [rect(1)]),
    evaluate("画一个五边形", [regular_poly(1, 5)]),
]

# 5. Astroid guard: must not be flagged star / ambiguous
astroid_text = "星形线 astroid 具有四个内禀尖点"
astroid_case = {
    "text": astroid_text,
    "explicit_kinds": recognized_unverifiable_kinds_from_text(astroid_text),
    "ambiguous_kinds": ambiguous_requirement_kinds_from_text(astroid_text),
}

# 6. C10: heart passes, star not_checked, partial + review required
c10_text = "生成一个爱心和一个五角星，爱心在左，五角星在右"
c10_logical = [{"object_id": "heart-1", "geometry_refs": [1], "label": "爱心"},
               {"object_id": "star-1", "geometry_refs": [2], "label": "五角星"}]
c10_case = evaluate(c10_text, [heart(1), star(2)], c10_logical)

snapshot = {
    "probe": "A_round11_R04_scope_fix_probe",
    "model_requests": 0,
    "network": False,
    "states": {
        "no_applicable": STATE_NO_APPLICABLE_REQUIREMENT,
        "fully_verified": STATE_FULLY_VERIFIED,
        "unverified_or_partial": STATE_UNVERIFIED_OR_PARTIAL,
    },
    "text_scan": text_scan,
    "explicit_cases": explicit_cases,
    "ambiguous_cases": ambiguous_cases,
    "ordinary_cases": ordinary_cases,
    "astroid_case": astroid_case,
    "c10_case": c10_case,
}

out = os.path.join(os.path.dirname(__file__), "A_round11_R04_scope_fix_probe.json")
with open(out, "w", encoding="utf-8") as fh:
    json.dump(snapshot, fh, ensure_ascii=False, indent=2)

print(json.dumps(snapshot, ensure_ascii=False, indent=2))
