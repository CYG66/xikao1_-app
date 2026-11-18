# -*- coding: utf-8 -*-
"""Round9 A-line semantic coverage completeness contract probe (zero model).

Offline, deterministic, no real model request, no network. All geometry below
is a **reconstructed fixture (重建夹具, 非历史回放)**: synthetic polylines built
in this script, not a persisted run artifact and not a replay of a recorded
output.

The probe has two jobs:

1. Apply the single truth function :func:`semantic_requirement_state` to real
   verifier reports across the contract's three states.
2. Reproduce the interpreter's existing ``status != 'not_checked'`` drop guard
   verbatim (production wiring belongs to Agent C; this probe only observes)
   and record whether a mandatory semantic signal reaches the summary layer,
   confirming or refuting the second suspected gap.

Usage (from ``backend/``)::

    python evaluations/v1/round9/A_round9_semantic_coverage_probe.py \
        --out evaluations/v1/round9/A_round9_semantic_coverage_probe.json
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import pathlib
import subprocess
import sys
from typing import Any

BACKEND = pathlib.Path(__file__).resolve().parents[3]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.cad_construction_interpreter import construction_acceptance_summary  # noqa: E402
import app.cad_semantic_acceptance as acceptance_mod  # noqa: E402
from app.cad_semantic_acceptance import verify_semantic_requirements  # noqa: E402
from app.cad_semantic_dispatch import (  # noqa: E402
    DISPATCH_CHANNELS,
    MANDATORY_REQUIREMENT_KINDS,
    SPECIAL_VERIFIED_KINDS,
    UNVERIFIABLE_RECOGNIZED_KINDS,
    semantic_requirement_state,
    state_allows_summary_passed,
)

FIXTURE_NOTE = "重建夹具（非历史回放）：脚本内合成折线，非落盘真实几何，非历史回放"
BASELINE_SHA = "07bd888f8c888a543d1983d8246f35d5939351e8"
GIT_EXE = r"C:\Users\29924\Softwares\git\Git\cmd\git.exe"

HEART_TEXT = "生成一个闭合爱心轮廓，宽度4米，高度4米"
C10_TEXT = "生成一个爱心和一个五角星，爱心在左，五角星在右"
LETTER_TEXT = "生成一个大写字母A的轮廓，高3米宽2米"
HOUSE_TEXT = "生成一个房子轮廓，宽4米高3米，屋顶是三角形，下面加一个门"
STAR_ONLY_TEXT = "生成一个五角星，外接圆半径2米，内外半径比0.381966，尖角朝上"
VASE_TEXT = "画一个花瓶"
NESTED_TEXT = "画一个嵌套正方形，外框边长3米，内框边长2米，内框居中"


def _poly(i: int, points: list[tuple[float, float]]) -> dict[str, Any]:
    return {"id": i, "type": "polyline", "closed": True, "selected": True,
            "vertices": [{"x": x, "y": y} for x, y in points]}


def _heart(i: int = 1, scale: float = 2000.0, ox: float = 0.0) -> dict[str, Any]:
    norm = [(0.20, 0.90), (0.50, 0.62), (0.80, 0.90), (0.95, 0.50),
            (0.75, 0.20), (0.50, 0.00), (0.25, 0.20), (0.05, 0.50)]
    return {"id": i, "type": "polyline", "closed": True, "selected": True,
            "vertices": [{"x": round(x * scale + ox, 3), "y": round(y * scale, 3)}
                         for x, y in norm]}


def _star(i: int = 2, ox: float = 3000.0, ro: float = 1000.0,
          ri: float = 400.0, cy: float = 1000.0) -> dict[str, Any]:
    pts = []
    for k in range(10):
        r = ro if k % 2 == 0 else ri
        ang = math.pi / 2 + k * math.pi / 5
        pts.append({"x": round(r * math.cos(ang) + ox, 3),
                     "y": round(r * math.sin(ang) + cy, 3)})
    return {"id": i, "type": "polyline", "closed": True, "selected": True, "vertices": pts}


def _house() -> list[dict[str, Any]]:
    return [_poly(1, [(0, 0), (4000, 0), (4000, 2000), (2000, 3000), (0, 2000)]),
            _poly(2, [(1500, 0), (2500, 0), (2500, 1500), (1500, 1500)])]


def _letter() -> list[dict[str, Any]]:
    return [_poly(1, [(0, 0), (850, 3000), (1150, 3000), (2000, 0), (1550, 0),
                      (1350, 750), (650, 750), (450, 0)]),
            _poly(2, [(800, 1400), (1200, 1400), (1000, 2400)])]


def _nested() -> list[dict[str, Any]]:
    return [_poly(1, [(-1500, -1500), (1500, -1500), (1500, 1500), (-1500, 1500)]),
            _poly(2, [(-1000, -1000), (1000, -1000), (1000, 1000), (-1000, 1000)])]


def _git(*args: str) -> str:
    return subprocess.run([GIT_EXE, *args], cwd=str(BACKEND.parent), check=True,
                          capture_output=True, text=True).stdout.strip()


def _report_brief(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": report.get("status"),
        "coverage": report.get("coverage"),
        "review_required": report.get("review_required"),
        "reason": report.get("reason"),
        "applicable_requirement_kinds": report.get("applicable_requirement_kinds"),
        "unsupported_kind": report.get("unsupported_kind"),
        "checks": [{"name": c.get("name"), "status": c.get("status")}
                   for c in report.get("checks", []) if isinstance(c, dict)],
        "object_acceptance": [
            {"geometry_ids": (e.get("target_ref") or {}).get("geometry_ids"),
             "object_id": (e.get("target_ref") or {}).get("object_id"),
             "status": e.get("status"), "reason": e.get("reason"),
             "profile": e.get("profile")}
            for e in report.get("object_acceptance", [])
        ],
    }


def _run_case(name: str, text: str, geoms: list[dict[str, Any]],
              logical: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    report = verify_semantic_requirements(text, geoms, logical_objects=logical)
    verdict = semantic_requirement_state(report, text)
    return {
        "text": text,
        "report": _report_brief(report),
        "contract_verdict": verdict,
        "summary_allows_passed": state_allows_summary_passed(verdict),
    }


def _summarize(source: dict[str, Any]) -> dict[str, Any]:
    return construction_acceptance_summary(
        preflight_structure=None, structure_contract=None, structure_validation=None,
        composition_contract=None, composition_validation=None, source_acceptance=source)


def simulate_drop_guard(text: str, report: dict[str, Any]) -> dict[str, Any]:
    """Reproduce the interpreter's existing attachment guard verbatim.

    Production wiring (interpreter line ~974) attaches the semantic report to
    ``source_acceptance`` only when ``status != 'not_checked'``.  The summary
    then iterates ``source_acceptance`` and its ``*_acceptance`` children.
    This simulation keeps that guard unchanged and records visibility under
    two source profiles: an empty-checks base, and a base that already carries
    one passed primitive check with ``coverage=complete`` (the BLOCK-01 residual
    condition under which a hidden mandatory requirement could otherwise reach
    a summary PASS).
    """
    attached = report.get("status") != "not_checked"

    def build_source(with_passed_check: bool) -> dict[str, Any]:
        source: dict[str, Any] = {"coverage": "complete", "unknown_requirements": [], "checks": []}
        if with_passed_check:
            source["checks"].append({"field": "primitive_dimension", "status": "passed",
                                     "authority": "backend_measured_geometry"})
        if attached:
            source["semantic_acceptance"] = report
        return source

    summary_empty = _summarize(build_source(False))
    summary_with_check = _summarize(build_source(True))
    verdict = semantic_requirement_state(report, text)
    return {
        "semantic_report_status": report.get("status"),
        "report_attached_to_source_acceptance": attached,
        "semantic_visible_to_summary": "semantic_acceptance" in build_source(False),
        "summary_empty_checks": {
            "status": summary_empty["status"],
            "review_required": summary_empty["review_required"],
        },
        "summary_with_passed_primitive_check": {
            "status": summary_with_check["status"],
            "review_required": summary_with_check["review_required"],
        },
        "contract_state": verdict["state"],
        "contract_reasons": verdict["reasons"],
        "contract_allows_passed": state_allows_summary_passed(verdict),
        "guard_would_hide_mandatory_requirement": (
            not attached and verdict["state"] == "unverified_or_partial"),
    }


def main() -> dict[str, Any]:
    cases: dict[str, Any] = {}

    cases["no_requirement_vase"] = _run_case(VASE_TEXT, VASE_TEXT, [_heart(1, 1000.0)])
    cases["heart_single"] = _run_case(HEART_TEXT, HEART_TEXT, [_heart(1, 4000.0)])
    cases["nested_frames_fully_verified"] = _run_case(NESTED_TEXT, NESTED_TEXT, _nested())
    cases["c10_heart_star"] = _run_case(
        C10_TEXT, C10_TEXT, [_heart(1, 2000.0), _star(2)],
        logical=[{"object_id": "heart-1", "geometry_refs": [1], "label": "爱心"},
                 {"object_id": "star-1", "geometry_refs": [2], "label": "五角星"}])
    cases["house_partial_review_false"] = _run_case(HOUSE_TEXT, HOUSE_TEXT, _house())
    cases["letter_a_partial_review_false"] = _run_case(LETTER_TEXT, LETTER_TEXT, _letter())
    cases["star_only_not_checked"] = _run_case(STAR_ONLY_TEXT, STAR_ONLY_TEXT, [_star(1, ox=0.0)])

    # Unknown recognized-but-unregistered kind (dispatch terminates in the
    # unsupported branch; no default checker may receive it).
    orig_requirements = acceptance_mod.semantic_requirements
    acceptance_mod.semantic_requirements = lambda _text: [
        {"kind": "mystery_contour", "instruction": "未知轮廓"}]
    try:
        unknown_report = verify_semantic_requirements(HEART_TEXT, [_heart(1, 4000.0)])
    finally:
        acceptance_mod.semantic_requirements = orig_requirements
    cases["unknown_kind"] = {
        "text": HEART_TEXT,
        "report": _report_brief(unknown_report),
        "contract_verdict": semantic_requirement_state(unknown_report, HEART_TEXT),
        "summary_allows_passed": state_allows_summary_passed(
            semantic_requirement_state(unknown_report, HEART_TEXT)),
    }

    # Drop-guard audit: replay the existing attachment guard against every
    # real report and record whether the mandatory semantic signal reaches
    # the summary layer.
    guard_audit: dict[str, Any] = {}
    for name, case in cases.items():
        report = _report_from_case(case)
        guard_audit[name] = simulate_drop_guard(case["text"], report)

    # Direct distinction between the two not_checked shapes the old code mixed.
    distinction = {
        "no_requirement_report": {
            "status": cases["no_requirement_vase"]["report"]["status"],
            "applicable_requirement_kinds": cases["no_requirement_vase"]["report"]["applicable_requirement_kinds"],
            "contract_state": cases["no_requirement_vase"]["contract_verdict"]["state"],
            "guard_hides_mandatory_requirement": False,
        },
        "star_only_report": {
            "status": cases["star_only_not_checked"]["report"]["status"],
            "applicable_requirement_kinds": cases["star_only_not_checked"]["report"]["applicable_requirement_kinds"],
            "contract_state": cases["star_only_not_checked"]["contract_verdict"]["state"],
            "guard_hides_mandatory_requirement": guard_audit["star_only_not_checked"]["guard_would_hide_mandatory_requirement"],
        },
    }

    doc: dict[str, Any] = {
        "schema": "round9.a-semantic-coverage-contract.v1",
        "generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "zero_real_model_calls": True,
        "zero_network": True,
        "fixture_note": FIXTURE_NOTE,
        "baseline_sha": BASELINE_SHA,
        "registries": {
            "dispatch_channels": dict(DISPATCH_CHANNELS),
            "special_verified_kinds": sorted(SPECIAL_VERIFIED_KINDS),
            "unverifiable_recognized_kinds": sorted(UNVERIFIABLE_RECOGNIZED_KINDS),
            "mandatory_requirement_kinds": sorted(MANDATORY_REQUIREMENT_KINDS),
        },
        "cases": cases,
        "drop_guard_audit": guard_audit,
        "not_checked_distinction": distinction,
    }

    try:
        doc["git"] = {
            "head_sha": _git("rev-parse", "HEAD"),
            "head_parent": _git("rev-parse", "HEAD^"),
            "baseline_sha": BASELINE_SHA,
            "branch": _git("branch", "--show-current"),
        }
    except Exception as exc:  # pragma: no cover - probe diagnostic only
        doc["git"] = {"error": str(exc)}

    return doc


def _report_from_case(case: dict[str, Any]) -> dict[str, Any]:
    """Rebuild a report-shaped dict for the guard simulation.

    The verifier report itself was retained in ``cases``; the guard only
    reads ``status`` and attaches the dict, so the stored brief plus verdict
    fields are sufficient to replay attachment visibility.
    """
    brief = case["report"]
    report: dict[str, Any] = {
        "status": brief["status"],
        "coverage": brief["coverage"],
        "review_required": brief["review_required"],
        "reason": brief["reason"],
        "applicable_requirement_kinds": brief["applicable_requirement_kinds"],
        "requirements": [{"kind": k} for k in (brief["applicable_requirement_kinds"] or [])],
        "checks": brief.get("checks", []),
        "object_acceptance": brief["object_acceptance"],
    }
    if brief.get("unsupported_kind"):
        report["unsupported_kind"] = brief["unsupported_kind"]
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(BACKEND / "evaluations" / "v1" / "round9"
                                              / "A_round9_semantic_coverage_probe.json"))
    args = parser.parse_args()
    doc = main()
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"written": str(out), "cases": list(doc["cases"].keys()),
                      "guard_hidden": [k for k, v in doc["drop_guard_audit"].items()
                                       if v["guard_would_hide_mandatory_requirement"]]},
                     ensure_ascii=False))
