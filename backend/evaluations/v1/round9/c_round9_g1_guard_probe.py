# -*- coding: utf-8 -*-
"""Round9 G1 summary guard probe (read-only, zero model, offline).

Runs the real production summary and candidate predicates over the contract
truth table, plus one real interpreter entry for the star-only capability gap.
Writes a machine-readable evidence snapshot.

Usage (from ``backend/``)::

    python evaluations/v1/round9/c_round9_g1_guard_probe.py --out evaluations/v1/round9/c_round9_g1_guard_results.json
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

from app.cad_construction_interpreter import (  # noqa: E402
    construction_acceptance_summary,
    interpret_construction_request,
)
from app.cad_candidate_state import candidate_is_accepted  # noqa: E402

GIT_EXE = r"C:\Users\29924\Softwares\git\Git\cmd\git.exe"
BASELINE_SHA = "07bd888f8c888a543d1983d8246f35d5939351e8"
PARENT_SHA = "2989e8c42fff3fed73720d2b2e399046ef966645"

STAR_TEXT = "生成一个五角星，外接圆半径2米"
VASE_TEXT = "画一个花瓶"
HEART_TEXT = "生成一个闭合爱心轮廓，宽度4米，高度4米"
POLYGON_TEXT = "生成一个正五边形，外接圆半径2米"

# Verdicts captured by the pre-guard recon probe (round9 G1 recon, before the
# guard landed). Kept here so the snapshot carries the before/after table.
BEFORE = {
    "R1": {"summary_status": "passed", "review_required": False, "accepted": True},
    "R2": {"summary_status": "review_required", "review_required": True, "accepted": False},
    "R3": {"summary_status": "review_required", "review_required": True, "accepted": False},
    "R4": {"summary_status": "passed", "review_required": False, "accepted": True},
    "R5": {"summary_status": "review_required", "review_required": True, "accepted": False},
    "R6": {"summary_status": "review_required", "review_required": True, "accepted": False},
}


def _git(*args: str) -> str:
    return subprocess.run([GIT_EXE, *args], cwd=str(BACKEND.parent), check=True,
                           capture_output=True, text=True).stdout.strip()


def _summarize(source_acceptance, source=None):
    return construction_acceptance_summary(
        preflight_structure=None, structure_contract=None, structure_validation=None,
        composition_contract=None, composition_validation=None,
        source_acceptance=source_acceptance, source=source)


def _base(semantic=None, coverage="complete"):
    source = {"coverage": coverage, "unknown_requirements": [],
              "checks": [{"status": "passed", "field": "primitive_dimension"}]}
    if semantic is not None:
        source["semantic_acceptance"] = semantic
    return source


def _verdict(semantic, coverage, source):
    summary = _summarize(_base(semantic, coverage=coverage), source=source)
    return {
        "summary_status": summary["status"],
        "review_required": summary["review_required"],
        "accepted": candidate_is_accepted({"acceptance_summary": summary}),
        "semantic_requirement_state": summary["semantic_requirement_state"],
        "semantic_incomplete_reasons": summary["semantic_incomplete_reasons"],
        "semantic_incomplete_objects": summary["semantic_incomplete_objects"],
        "verified_checks": summary["verified_checks"],
    }


def _star_vertices(ox=0, cy=2000, ro=2000, ri=800):
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
        "truth_table": [],
        "star_only_entry": {},
    }
    try:
        report["git"] = {
            "head_sha": _git("rev-parse", "HEAD"),
            "parent_sha": _git("rev-parse", "HEAD^"),
            "expected_parent": PARENT_SHA,
            "baseline_sha": BASELINE_SHA,
            "branch": _git("branch", "--show-current"),
        }
    except Exception as exc:  # pragma: no cover
        report["git"]["error"] = str(exc)

    rows = [
        {"row": "R1", "source": HEART_TEXT, "coverage": "complete",
         "semantic": {"status": "partial", "review_required": False,
                      "applicable_requirement_kinds": ["heart_outline_features"]}},
        {"row": "R2", "source": HEART_TEXT, "coverage": "complete",
         "semantic": {"status": "partial", "review_required": True,
                      "applicable_requirement_kinds": ["heart_outline_features"]}},
        {"row": "R3", "source": HEART_TEXT, "coverage": "complete",
         "semantic": {"status": "unverified", "review_required": True}},
        {"row": "R4", "source": VASE_TEXT, "coverage": "complete", "semantic": None},
        {"row": "R5", "source": VASE_TEXT, "coverage": "complete",
         "semantic": {"status": "not_checked", "review_required": True,
                      "applicable_requirement_kinds": []}},
        {"row": "R6", "source": HEART_TEXT, "coverage": "partial",
         "semantic": {"status": "partial", "review_required": False,
                      "applicable_requirement_kinds": ["heart_outline_features"]}},
        {"row": "T1", "source": VASE_TEXT, "coverage": "complete",
         "semantic": {"status": "not_checked", "review_required": True,
                      "applicable_requirement_kinds": []}},
        {"row": "T2", "source": POLYGON_TEXT, "coverage": "complete",
         "semantic": {"status": "passed", "review_required": False,
                      "applicable_requirement_kinds": ["regular_polygon"],
                      "object_acceptance": [{"target_ref": {"geometry_ids": [1]},
                                             "status": "passed"}]}},
        {"row": "T8", "source": STAR_TEXT, "coverage": "complete",
         "semantic": {"status": "not_checked", "review_required": True,
                      "applicable_requirement_kinds": ["star_profile"],
                      "object_acceptance": []}},
    ]
    for row in rows:
        after = _verdict(row["semantic"], row["coverage"], row["source"])
        report["truth_table"].append({
            "row": row["row"], "source": row["source"], "coverage": row["coverage"],
            "semantic_acceptance": row["semantic"],
            "before": BEFORE.get(row["row"]), "after": after,
        })

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
            "object_acceptance": semantic.get("object_acceptance"),
        },
        "entry_summary": entry.get("acceptance_summary"),
        "candidate_is_accepted": candidate_is_accepted({"acceptance_summary": entry.get("acceptance_summary")}),
    }
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(BACKEND / "evaluations" / "v1" / "round9" / "c_round9_g1_guard_results.json"))
    args = parser.parse_args()
    data = main()
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"written": str(out), "rows": len(data["truth_table"])}, ensure_ascii=False))
