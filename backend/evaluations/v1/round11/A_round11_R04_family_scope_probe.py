"""Round11 R-04 third-round offline probe: source applicability boundary.

Zero model requests, zero network. Runs against local backend modules only.
Writes a machine-readable JSON snapshot alongside this script.

Question: can the system distinguish "an existing but temporarily
unverifiable object intent" from "truly no applicable semantic requirement"?
The rule: a vocabulary miss must NOT equal "the user stated no requirement".

This snapshot records:
  * explicit five-pointed star wording -> applicable, blocked;
  * ambiguous wording -> ambiguous_unresolved / applicable, blocked;
  * other recognized star-family wording (four-/six-pointed, asterisk,
    generic English star) -> recorded under its own kind, unverifiable,
    blocked; NOT bound to ``star_profile``;
  * ordinary shapes and the W1 no-signal geometry boundary -> released;
  * C10 regression -> heart passed, star not_checked, rejected.
"""
import json
import math
import os
import sys

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, BACKEND)

from app.cad_semantic_acceptance import verify_semantic_requirements  # noqa: E402
from app.cad_semantic_dispatch import (  # noqa: E402
    STATE_NO_APPLICABLE_REQUIREMENT,
    STATE_UNVERIFIED_OR_PARTIAL,
    ambiguous_requirement_kinds_from_text,
    recognized_star_family_unsupported_kinds_from_text,
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
        "report_coverage": report.get("coverage"),
        "report_review_required": report.get("review_required"),
        "unsupported_kind": report.get("unsupported_kind"),
        "recognized_unverifiable_kinds": report.get("recognized_unverifiable_kinds"),
        "report_applicable": report.get("applicable_requirement_kinds"),
        "report_ambiguous": report.get("ambiguous_requirement_kinds"),
        "report_decision": report.get("applicability_decision"),
        "verdict_state": verdict["state"],
        "verdict_decision": verdict.get("applicability_decision"),
        "verdict_reasons": verdict["reasons"],
        "verdict_applicable": verdict["applicable_requirement_kinds"],
        "verdict_unknown": verdict["recognized_unknown_kinds"],
        "allows_summary_passed": state_allows_summary_passed(verdict),
        "object_acceptance": [
            {"object_id": (e.get("target_ref") or {}).get("object_id"),
             "geometry_ids": (e.get("target_ref") or {}).get("geometry_ids"),
             "profile": e.get("profile"), "status": e.get("status"),
             "reason": e.get("reason")}
            for e in report.get("object_acceptance") or []
        ],
    }


cases = []

# 1. Explicit five-pointed star wording: applicable, blocked.
for word in ("五角星", "五芒星", "星形轮廓"):
    cases.append(("EXPLICIT_" + word, evaluate(f"画一个{word}", [])))

# 2. Ambiguous wording: blocked (unresolved or geometry-confirmed).
cases.append(("AMBIGUOUS_unresolved_星星", evaluate("画一个星星", [])))
cases.append(("AMBIGUOUS_unresolved_星形", evaluate("画一个星形", [])))
cases.append(("AMBIGUOUS_confirmed_五角形", evaluate("画一个五角形", [star(1, ox=0.0)])))
cases.append(("AMBIGUOUS_resolved_non_star", evaluate("生成一个五角形", [regular_poly(1, 5)])))

# 3. Other recognized star-family wording: recorded under own kind, blocked.
for label, text in [
    ("four_pointed_star", "画一个四角星"),
    ("six_pointed_star", "画一个六角星"),
    ("six_pointed_star_hexagram", "画一个六芒星"),
    ("asterisk", "画一个星号"),
    ("generic_english", "draw a star"),
    ("generic_english_five", "a five-pointed star"),
    ("generic_english_mixed", "一个star"),
]:
    cases.append(("FAMILY_" + label, evaluate(text, [])))

# 4. Negative controls: ordinary shapes released; W1 no-signal star geometry.
for label, text, geometry in [
    ("hexagon", "画一个六边形", regular_poly(1, 6)),
    ("circle", "画一个圆", circle(1)),
    ("rectangle", "画一个矩形", rect(1)),
    ("plain_pentagon", "画一个五边形", regular_poly(1, 5)),
]:
    cases.append(("ORDINARY_" + label, evaluate(text, [geometry])))
cases.append(("W1_no_signal_star_like_geometry",
              evaluate("画一个圆和一个矩形", [star(1, ox=0.0)])))

# 5. English negative control: ``start`` must not be read as a star.
cases.append(("NEG_start_word", evaluate("start here", [])))

# 6. C10 regression: heart passed, star not_checked, rejected.
c10_text = "生成一个爱心和一个五角星，爱心在左，五角星在右"
c10_logical = [{"object_id": "heart-1", "geometry_refs": [1], "label": "爱心"},
               {"object_id": "star-1", "geometry_refs": [2], "label": "五角星"}]
cases.append(("C10_heart_star_partial", evaluate(c10_text, [heart(1), star(2)], c10_logical)))

# 7. Astroid guard: text scans must not classify it as star or family.
astroid_text = "星形线 astroid 具有四个内禀尖点"
astroid_scan = {
    "text": astroid_text,
    "explicit_kinds": recognized_unverifiable_kinds_from_text(astroid_text),
    "ambiguous_kinds": ambiguous_requirement_kinds_from_text(astroid_text),
    "family_kinds": recognized_star_family_unsupported_kinds_from_text(astroid_text),
}

snapshot = {
    "probe": "A_round11_R04_family_scope_probe",
    "model_requests": 0,
    "network": False,
    "states": {
        "no_applicable": STATE_NO_APPLICABLE_REQUIREMENT,
        "unverified_or_partial": STATE_UNVERIFIED_OR_PARTIAL,
    },
    "cases": [{"label": label, **result} for label, result in cases],
    "astroid_scan": astroid_scan,
}

out = os.path.join(os.path.dirname(__file__), "A_round11_R04_family_scope_probe.json")
with open(out, "w", encoding="utf-8") as fh:
    json.dump(snapshot, fh, ensure_ascii=False, indent=2)

print(json.dumps(snapshot, ensure_ascii=False, indent=2))
