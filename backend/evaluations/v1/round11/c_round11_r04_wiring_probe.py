# -*- coding: utf-8 -*-
"""Round11 R-04 wiring evidence probe (Agent C), zero model, offline.

Drives the local verifier / summary chain with empty geometry; no real model
request, no network. Records the caller-side retention gate and the
missing-report fallback after A's 238a84e scope fix.

Usage (from ``backend/``)::

    python evaluations/v1/round11/c_round11_r04_wiring_probe.py \
        --out evaluations/v1/round11/c_round11_r04_wiring_probe.json
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[3]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

os.environ.setdefault("XLINE_AGENT_PROVIDER", "local")
os.environ.pop("DEEPSEEK_API_KEY", None)

from app.cad_semantic_acceptance import verify_semantic_requirements  # noqa: E402
from app.cad_semantic_dispatch import (  # noqa: E402
    semantic_requirement_state,
    state_allows_summary_passed,
)
from app.cad_construction_interpreter import construction_acceptance_summary  # noqa: E402


def _summary(source_acceptance, source):
    return construction_acceptance_summary(
        preflight_structure=None, structure_contract=None, structure_validation=None,
        composition_contract=None, composition_validation=None,
        source_acceptance=source_acceptance, source=source)


def _gate_retained(report: dict) -> bool:
    applicable = report.get("applicable_requirement_kinds") or []
    return report["status"] != "not_checked" or bool(applicable)


def real_case(text: str) -> dict:
    report = verify_semantic_requirements(text, [], None, None)
    verdict = semantic_requirement_state(report, text)
    return {
        "text": text,
        "report_status": report.get("status"),
        "report_reason": report.get("reason"),
        "ambiguity_resolution": report.get("ambiguity_resolution"),
        "report_applicable": report.get("applicable_requirement_kinds") or [],
        "report_ambiguous": report.get("ambiguous_requirement_kinds") or [],
        "verdict_state": verdict.get("state"),
        "verdict_reasons": verdict.get("reasons"),
        "verdict_applicable": verdict.get("applicable_requirement_kinds"),
        "verdict_ambiguous": verdict.get("ambiguous_requirement_kinds"),
        "allows_summary_passed": state_allows_summary_passed(verdict),
        "storage_gate_retained": _gate_retained(report),
    }


def fallback_case(text: str) -> dict:
    summary = _summary({"coverage": "complete", "unknown_requirements": [],
                        "checks": [{"status": "passed", "field": "primitive_dimension"}]},
                       source=text)
    return {
        "text": text,
        "summary_status": summary.get("status"),
        "semantic_state": summary.get("semantic_requirement_state"),
        "semantic_applicable": summary.get("semantic_applicable_requirement_kinds"),
        "semantic_reasons": summary.get("semantic_incomplete_reasons"),
        "review_required": summary.get("review_required"),
        "allows_summary_passed": state_allows_summary_passed(
            {"state": summary.get("semantic_requirement_state")}),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    texts = ["画一个五角星", "画一个五角形", "画一个星星", "画一个圆", "画一个矩形"]
    result = {
        "probe": "c_round11_r04_wiring_probe",
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "model_requests": 0,
        "network": False,
        "code_version": "238a84e44bd4ea01a8c580df6d4b2cdfc411722d",
        "real_reports": [real_case(t) for t in texts],
        "fallback_missing_report": [fallback_case(t) for t in texts],
    }

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
