# -*- coding: utf-8 -*-
"""Round11 R-04 wiring evidence probe, round 3 (Agent C), zero model, offline.

Drives the local verifier / summary chain with synthetic geometry; no real
model request, no network. Records the caller-side retention gate after the
alignment with A's explicit ``applicability_decision`` and the recognized-but-
unverifiable star-family kinds:

* attached-report cases: W1 / M1 / M1b / explicit star / family wording /
  ordinary shapes / C10;
* missing-report fallback: explicit / ambiguous / family wording blocked,
  ordinary shapes released; astroid wording keeps its own channel.

Usage (from ``backend/``)::

    python evaluations/v1/round11/c_round11_r04_wiring_probe.py \
        --out evaluations/v1/round11/c_round11_r04_wiring_probe.json
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import pathlib
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[3]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

os.environ.setdefault("XLINE_AGENT_PROVIDER", "local")
os.environ.pop("DEEPSEEK_API_KEY", None)

from app.cad_semantic_acceptance import semantic_requirements, verify_semantic_requirements  # noqa: E402
from app.cad_semantic_dispatch import (  # noqa: E402
    DECISION_TERMS,
    recognized_star_family_unsupported_kinds_from_text,
    semantic_requirement_state,
    state_allows_summary_passed,
)
from app.cad_construction_interpreter import construction_acceptance_summary  # noqa: E402
from app.cad_candidate_state import candidate_is_accepted  # noqa: E402


def _star_geom(i=2, ox=3000.0, ro=1000.0, ri=400.0, cy=1000.0):
    pts = []
    for k in range(10):
        r = ro if k % 2 == 0 else ri
        ang = math.pi / 2 + k * math.pi / 5
        pts.append({"x": round(r * math.cos(ang) + ox, 3),
                    "y": round(r * math.sin(ang) + cy, 3)})
    return {"id": i, "type": "polyline", "closed": True, "selected": True, "vertices": pts}


def _poly_geom(i, n, r=1000.0, cy=1000.0):
    pts = [{"x": round(r * math.cos(k * math.tau / n), 3),
            "y": round(cy + r * math.sin(k * math.tau / n), 3)} for k in range(n)]
    return {"id": i, "type": "polyline", "closed": True, "selected": True, "vertices": pts}


def _circle_geom(i):
    return {"id": i, "type": "circle", "center": {"x": 0, "y": 1000}, "radius": 1000}


def _rect_geom(i):
    return {"id": i, "type": "polyline", "closed": True, "selected": True,
            "vertices": [{"x": -1000, "y": 0}, {"x": 1000, "y": 0},
                         {"x": 1000, "y": 2000}, {"x": -1000, "y": 2000}]}


_HEART_NORM = [(0.20, 0.90), (0.50, 0.62), (0.80, 0.90), (0.95, 0.50),
               (0.75, 0.20), (0.50, 0.00), (0.25, 0.20), (0.05, 0.50)]


def _heart_geom(i=1, scale=2000.0):
    return {"id": i, "type": "polyline", "closed": True, "selected": True,
            "vertices": [{"x": round(x * scale, 3), "y": round(y * scale, 3)}
                         for x, y in _HEART_NORM]}


def _gate_retained(report: dict) -> bool:
    applicable = report.get("applicable_requirement_kinds") or []
    decision = report.get("applicability_decision")
    decision_ok = isinstance(decision, str) and decision in DECISION_TERMS
    return report["status"] != "not_checked" or bool(applicable) or decision_ok


def _summary(source_acceptance, source):
    return construction_acceptance_summary(
        preflight_structure=None, structure_contract=None, structure_validation=None,
        composition_contract=None, composition_validation=None,
        source_acceptance=source_acceptance, source=source)


def attached_case(label, text, geometries, logical=None, coverage="complete"):
    report = verify_semantic_requirements(text, geometries, logical_objects=logical)
    verdict = semantic_requirement_state(report, text)
    source = {"coverage": coverage, "unknown_requirements": [],
              "checks": [{"status": "passed", "field": "primitive_dimension"}],
              "semantic_acceptance": report}
    summary = _summary(source, text)
    candidate = {"acceptance_summary": summary}
    return {
        "label": label,
        "text": text,
        "report_status": report.get("status"),
        "report_coverage": report.get("coverage"),
        "report_unsupported_kind": report.get("unsupported_kind"),
        "report_decision": report.get("applicability_decision"),
        "report_applicable": report.get("applicable_requirement_kinds") or [],
        "report_ambiguous": report.get("ambiguous_requirement_kinds") or [],
        "verdict_state": verdict.get("state"),
        "verdict_reasons": verdict.get("reasons"),
        "gate_retained": _gate_retained(report),
        "summary_status": summary.get("status"),
        "review_required": summary.get("review_required"),
        "accepted": candidate_is_accepted(candidate),
        "allows_summary_passed": state_allows_summary_passed(verdict),
    }


def fallback_case(label, text):
    summary = _summary({"coverage": "complete", "unknown_requirements": [],
                        "checks": [{"status": "passed", "field": "primitive_dimension"}]},
                       source=text)
    return {
        "label": label,
        "text": text,
        "summary_status": summary.get("status"),
        "semantic_state": summary.get("semantic_requirement_state"),
        "semantic_reasons": summary.get("semantic_incomplete_reasons"),
        "review_required": summary.get("review_required"),
        "accepted": candidate_is_accepted({"acceptance_summary": summary}),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    c10_logical = [{"object_id": "heart-1", "geometry_refs": [1], "label": "爱心"},
                   {"object_id": "star-1", "geometry_refs": [2], "label": "五角星"}]

    attached = [
        attached_case("W1_no_signal_star_like_geometry", "画一个圆和一个矩形",
                      [_star_geom(1, ox=0.0)]),
        attached_case("M1_ambiguous_pentagon_resolved_non_star", "生成一个五角形",
                      [_poly_geom(1, 5)]),
        attached_case("M1b_ambiguous_star_geometry_blocked", "画一个五角形",
                      [_star_geom(1, ox=0.0)]),
        attached_case("EXPLICIT_五角星", "画一个五角星", []),
        attached_case("FAMILY_four_pointed_star", "画一个四角星", []),
        attached_case("FAMILY_six_pointed_star", "画一个六角星", []),
        attached_case("FAMILY_asterisk", "画一个星号", []),
        attached_case("FAMILY_generic_english", "draw a star", []),
        attached_case("ORDINARY_circle", "画一个圆", [_circle_geom(1)]),
        attached_case("ORDINARY_rectangle", "画一个矩形", [_rect_geom(1)]),
        attached_case("ORDINARY_plain_pentagon", "画一个五边形", [_poly_geom(1, 5)]),
        attached_case("ORDINARY_hexagon", "画一个六边形", [_poly_geom(1, 6)]),
        attached_case("C10_heart_star_partial",
                      "生成一个爱心和一个五角星，爱心在左，五角星在右",
                      [_heart_geom(1), _star_geom(2)], c10_logical, coverage="partial"),
    ]
    fallback = [
        fallback_case("MISSING_explicit_五角星", "画一个五角星"),
        fallback_case("MISSING_ambiguous_五角形", "画一个五角形"),
        fallback_case("MISSING_family_四角星", "画一个四角星"),
        fallback_case("MISSING_family_六角星", "画一个六角星"),
        fallback_case("MISSING_family_星号", "画一个星号"),
        fallback_case("MISSING_family_generic_english", "draw a star"),
        fallback_case("MISSING_ordinary_圆", "画一个圆"),
        fallback_case("MISSING_ordinary_矩形", "画一个矩形"),
        fallback_case("MISSING_ordinary_五边形", "画一个五边形"),
        fallback_case("MISSING_ordinary_六边形", "画一个六边形"),
    ]

    astroid_text = "星形线 astroid 具有四个内禀尖点"
    astroid_scan = {
        "text": astroid_text,
        "family_kinds": recognized_star_family_unsupported_kinds_from_text(astroid_text),
        "structured_kinds": [(req or {}).get("kind")
                             for req in semantic_requirements(astroid_text) or []],
    }

    result = {
        "probe": "c_round11_r04_wiring_probe",
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "model_requests": 0,
        "network": False,
        "code_version": "e2f343775af15466d612a974006c51a404aa552a",
        "attached_report_cases": attached,
        "fallback_missing_report_cases": fallback,
        "astroid_scan": astroid_scan,
    }

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
