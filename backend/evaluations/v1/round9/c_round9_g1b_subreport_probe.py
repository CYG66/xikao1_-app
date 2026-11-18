# -*- coding: utf-8 -*-
"""Round9 G1b sub-report acceptable-status gate probe (zero model, offline).

D's PARTIAL review found the same shape as the G1 semantic hole in the
non-semantic generic sub-reports: a ``partial`` report with
``review_required=False`` and top-level ``coverage=complete`` was still
summarized as passed / accepted. This probe captures the before/after table
for the four generic ``*_acceptance`` channels, keeps the G1 semantic positives
and negatives stable, and records the known source-vocabulary identification
gap without changing the vocabulary.

Usage (from ``backend/``)::

    python evaluations/v1/round9/c_round9_g1b_subreport_probe.py --out evaluations/v1/round9/c_round9_g1b_subreport_results.json
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import subprocess
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[3]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.cad_construction_interpreter import (  # noqa: E402
    construction_acceptance_summary,
    interpret_construction_request,
)
from app.cad_candidate_state import candidate_is_accepted  # noqa: E402

GIT_EXE = r"C:\Users\29924\Softwares\git\Git\cmd\git.exe"
PARENT_SHA = "fe63db32249205abcdb8d0677067dd597ddcbc26"

VASE_TEXT = "画一个花瓶"
POLYGON_TEXT = "生成一个正五边形，外接圆半径2米"
HEART_TEXT = "生成一个闭合爱心轮廓，宽度4米，高度4米"
STAR_TEXT = "生成一个五角星，外接圆半径2米"

# Before the G1b gate (measured at parent fe63db32): the generic loop only
# blocked on {failed, unverified, review_required} or a stray flag, so a
# partial report without review_required was promoted to a complete pass.
BEFORE_PARTIAL_REVIEW_FALSE = {"summary_status": "passed",
                                "review_required": False, "accepted": True}

GENERIC_REPORTS = ["stroke_acceptance", "path_relation_acceptance",
                   "repetition_acceptance", "projection_acceptance"]


def _git(*args: str) -> str:
    return subprocess.run([GIT_EXE, *args], cwd=str(BACKEND.parent), check=True,
                          capture_output=True, text=True).stdout.strip()


def _summarize(source_acceptance, source=None):
    return construction_acceptance_summary(
        preflight_structure=None, structure_contract=None, structure_validation=None,
        composition_contract=None, composition_validation=None,
        source_acceptance=source_acceptance, source=source)


def _base(extra=None, coverage="complete"):
    source = {"coverage": coverage, "unknown_requirements": [],
              "checks": [{"status": "passed", "field": "primitive_dimension"}]}
    if extra:
        source.update(extra)
    return source


def _verdict(source_acceptance, source):
    summary = _summarize(source_acceptance, source=source)
    return {
        "summary_status": summary["status"],
        "review_required": summary["review_required"],
        "accepted": candidate_is_accepted({"acceptance_summary": summary}),
        "semantic_requirement_state": summary["semantic_requirement_state"],
        "semantic_incomplete_reasons": summary["semantic_incomplete_reasons"],
        "verified_checks": summary["verified_checks"],
    }


def _star_vertices(ox=0, cy=2000, ro=2000, ri=800):
    import math
    points = []
    for k in range(10):
        r = ro if k % 2 == 0 else ri
        ang = math.pi / 2 + k * math.pi / 5
        points.append({"x": round(r * math.cos(ang) + ox, 3),
                       "y": round(r * math.sin(ang) + cy, 3)})
    return points


def main() -> dict:
    report: dict = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "zero_model": True,
        "git": {},
        "generic_partial_rows": [],
        "semantic_stability": [],
        "star_only_entry": {},
        "known_gaps": [],
    }
    try:
        report["git"] = {
            "base_commit": _git("rev-parse", "HEAD"),
            "base_parent": _git("rev-parse", "HEAD^"),
            "expected_commit_parent": PARENT_SHA,
            "branch": _git("branch", "--show-current"),
        }
    except Exception as exc:  # pragma: no cover
        report["git"]["error"] = str(exc)

    # G1b negatives: partial + review_required=False in every generic channel.
    for key in GENERIC_REPORTS:
        report_dict = {"status": "partial", "review_required": False,
                       "coverage": "explicit_channel_only", "checks": []}
        after = _verdict(_base({key: report_dict}), source=VASE_TEXT)
        report["generic_partial_rows"].append({
            "channel": key,
            "sub_report": report_dict,
            "before": dict(BEFORE_PARTIAL_REVIEW_FALSE),
            "after": after,
        })

    # Semantic positives / negatives must keep their G1 verdicts.
    semantic_rows = [
        {"row": "R4", "source": VASE_TEXT, "semantic": None, "allows_pass": True},
        {"row": "R5", "source": VASE_TEXT,
         "semantic": {"status": "not_checked", "review_required": True,
                      "applicable_requirement_kinds": []}, "allows_pass": True},
        {"row": "T1", "source": VASE_TEXT,
         "semantic": {"status": "not_checked", "review_required": True,
                      "applicable_requirement_kinds": []}, "allows_pass": True},
        {"row": "T2", "source": POLYGON_TEXT,
         "semantic": {"status": "passed", "review_required": False,
                      "applicable_requirement_kinds": ["regular_polygon"],
                      "object_acceptance": [{"target_ref": {"geometry_ids": [1]},
                                             "status": "passed"}]}, "allows_pass": True},
        {"row": "R1", "source": HEART_TEXT,
         "semantic": {"status": "partial", "review_required": False,
                      "applicable_requirement_kinds": ["heart_outline_features"]},
         "allows_pass": False},
    ]
    for row in semantic_rows:
        after = _verdict(_base({"semantic_acceptance": row["semantic"]}), source=row["source"])
        report["semantic_stability"].append({"row": row["row"], "after": after,
                                              "allows_pass": row["allows_pass"]})

    def callback(_text, _schema):
        return {"schema_version": "cad.construction-interpretation.v1",
                "is_construction_request": True, "confidence": 0.99,
                "evidence_text": [STAR_TEXT], "assumptions": [],
                "plan": {"units": "mm", "steps": [
                    {"op": "add_polyline", "step_id": "star", "output_ref": "star",
                     "semantic": {"label": "五角星"}, "closed": True,
                     "vertices": _star_vertices()}]}}

    entry = interpret_construction_request(STAR_TEXT, callback, force_structured_model=True)
    source = entry.get("source_acceptance") or {}
    semantic = source.get("semantic_acceptance")
    report["star_only_entry"] = {
        "request": STAR_TEXT,
        "interpreter_status": entry.get("status"),
        "semantic_report_stored": "semantic_acceptance" in source,
        "semantic_report": None if semantic is None else {
            "status": semantic.get("status"),
            "review_required": semantic.get("review_required"),
            "applicable_requirement_kinds": semantic.get("applicable_requirement_kinds"),
        },
        "entry_summary": entry.get("acceptance_summary"),
        "candidate_is_accepted": candidate_is_accepted(
            {"acceptance_summary": entry.get("acceptance_summary")}),
    }

    report["known_gaps"].append({
        "id": "GAP-source-star-vocabulary",
        "description": "源侧星形词表仅识别『五角星|五芒星|星形轮廓』；『星形/五角形/星星』不进入适用性标记，仅由几何 profile 兜底。本轮不改词表，登记为待后续轮次处理的识别缺口。",
        "blocked_now": False,
    })
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(BACKEND / "evaluations" / "v1" / "round9" /
                                             "c_round9_g1b_subreport_results.json"))
    args = parser.parse_args()
    data = main()
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"written": str(out),
                      "generic_rows": len(data["generic_partial_rows"])}, ensure_ascii=False))
