# -*- coding: utf-8 -*-
"""Round9 G2 three-path controlled dynamic trigger harness (Agent C).

Zero real model calls: every plan below is supplied by a local Mock callback.
The real production chain (plan compile -> executor -> assertion verification ->
independent semantic acceptance -> summary -> candidate predicate) is exercised
for:

- Path A: diagnostic replay after an assertion failure (``diagnostic_trial``).
- Path B: astroid repair trial (inapplicable smoothness assertion removed).
- Path C: regular-polygon boundary repair trial (unrequested bounds assertion
  removed).

Each record carries the six evidence items required by the G2 brief:
binding evidence, attribution preservation, summary propagation, non-acceptance,
repair budget, and mock call count.

Usage (from ``backend/``)::

    python evaluations/v1/round9/c_round9_g2_path_harness.py --out evaluations/v1/round9/c_round9_g2_path_results.json
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import pathlib
import subprocess
import sys
from copy import deepcopy

BACKEND = pathlib.Path(__file__).resolve().parents[3]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.cad_construction_interpreter import (  # noqa: E402
    construction_acceptance_summary,
    interpret_construction_request,
)
from app.cad_candidate_state import (  # noqa: E402
    authoritative_acceptance_summary,
    candidate_is_accepted,
)
from app.cad_generation_recovery import bounded_repair_available  # noqa: E402

GIT_EXE = r"C:\Users\29924\Softwares\git\Git\cmd\git.exe"
PARENT_SHA = "fe63db32249205abcdb8d0677067dd597ddcbc26"
MAX_REPAIRS_BUDGET = 2  # bounded_repair_available default; not changed this round.


def _git(*args: str) -> str:
    return subprocess.run([GIT_EXE, *args], cwd=str(BACKEND.parent), check=True,
                          capture_output=True, text=True).stdout.strip()


def _counting_callback(payload: dict, counter: list):
    def callback(_text, _schema):
        counter.append(1)
        return deepcopy(payload)
    return callback


def _attribution_preserved(proof: dict, *, require_review_fields: bool) -> bool:
    """Whether the independent acceptance verdict survived into the record.

    A passed special-branch proof legitimately omits ``review_required`` /
    ``reason``; those fields are only mandatory when the proof carries a
    non-passing verdict.
    """
    core = all(k in proof for k in ("status", "coverage", "binding"))
    if not require_review_fields:
        return core
    return core and all(k in proof for k in ("review_required", "reason"))


def _binding_evidence(binding: dict | None) -> dict:
    binding = binding or {}
    return {
        "binding_source": binding.get("binding_source"),
        "binding_trust": binding.get("binding_trust"),
        "issues": binding.get("issues"),
        "model_declared_object_id_trusted": binding.get("model_declared_object_id_trusted"),
        "identity_anchor": binding.get("identity_anchor"),
        "trusted_with_empty_issues": (
            binding.get("binding_trust") == "trusted"
            and binding.get("binding_source") == "execute_construction_plan.logical_objects"
            and binding.get("issues") == []
        ),
    }


def _candidate_state(summary: dict | None) -> dict:
    variant = {"acceptance_summary": summary} if isinstance(summary, dict) else {}
    return {
        "candidate_is_accepted": candidate_is_accepted(variant),
        "authoritative_acceptance_summary": authoritative_acceptance_summary(variant),
    }


def _record_common(path_id: str, path_entry: str, trigger_kind: str, source: str,
                    plan: dict, mock_calls: int, repairs: list) -> dict:
    return {
        "input_fixture_id": path_id,
        "path_entry": path_entry,
        "trigger_kind": trigger_kind,
        "source": source,
        "actual_params": {"plan": plan, "mock_model_calls": mock_calls},
        "repair": {
            "deterministic_repair_count": len(repairs),
            "repair_kinds": [r.get("kind") for r in repairs],
            "max_repairs_budget": MAX_REPAIRS_BUDGET,
            "within_budget": len(repairs) <= MAX_REPAIRS_BUDGET,
            "bounded_repair_available_default": bounded_repair_available.__defaults__,
        },
    }


def run_path_a() -> dict:
    """Path A: diagnostic replay. Entity-count assertion fails naturally; the
    assertion-free diagnostic trial still runs the bound semantic acceptance and
    records its verdict in ``independent_source_failure``."""
    source = "画一个半径1米的圆"
    plan = {"units": "m", "steps": [{
        "op": "add_circle", "step_id": "circle-1", "output_ref": "circle-1",
        "semantic": {"object_type": "circle", "label": "圆"},
        "center": {"x": 0, "y": 0}, "radius": 1,
    }], "assertions": [{
        "kind": "entity_count", "assertion_id": "wrong-count",
        "target_ref": "circle-1", "equals": 2,
    }]}
    counter: list = []
    result = interpret_construction_request(
        source, _counting_callback(
            {"schema_version": "cad.construction-interpretation.v1",
             "is_construction_request": True, "confidence": 0.9,
             "evidence_text": [source], "assumptions": [], "plan": plan}, counter),
        force_structured_model=True)

    error = result.get("construction_error") or result.get("error") or {}
    details = error.get("details") or {}
    diagnostic = details.get("independent_source_failure") or {}
    binding = diagnostic.get("binding")

    # The invalid diagnostic result does not carry a production summary; rebuild
    # one from the recorded diagnostic report to prove the recorded verdict reaches
    # the summary layer. This reconstruction is an audit-only step, not a persisted
    # candidate path.
    diagnostic_report = {
        "status": diagnostic.get("status"),
        "review_required": diagnostic.get("review_required"),
        "reason": diagnostic.get("reason"),
        "coverage": diagnostic.get("coverage"),
        "binding": binding,
        "applicable_requirement_kinds": [],
    }
    reconstructed_summary = construction_acceptance_summary(
        preflight_structure=None, structure_contract=None, structure_validation=None,
        composition_contract=None, composition_validation=None,
        source_acceptance={"coverage": "partial", "unknown_requirements": [],
                           "semantic_acceptance": diagnostic_report, "checks": []},
        source=source)

    acceptance_output = {
        "diagnostic_record": diagnostic,
        "binding_evidence": _binding_evidence(binding),
        "attribution_fields_present": all(
            k in diagnostic for k in ("status", "review_required", "reason", "coverage", "binding")),
        "diagnostic_only": diagnostic.get("diagnostic_only"),
        "candidate_accepted_flag": diagnostic.get("candidate_accepted"),
    }
    record = _record_common(
        "A-diagnostic-replay",
        "cad_construction_interpreter.py:1028 (diagnostic_trial semantic verify); record :1041-1047",
        "natural", source, plan, len(counter), [])
    record.update({
        "interpreter_status": result.get("status"),
        "error_code": error.get("code"),
        "acceptance_output": acceptance_output,
        "summary_output": {
            "note": "invalid 诊断结果不挂正式汇总；以下为诊断报告离线重建的审计汇总。",
            "summary": reconstructed_summary,
        },
        "candidate_state": _candidate_state(reconstructed_summary),
        "evidence_checks": {
            "binding_passed_to_verifier": _binding_evidence(binding)["trusted_with_empty_issues"],
            "attribution_not_dropped": acceptance_output["attribution_fields_present"],
            "review_required_reaches_summary": reconstructed_summary["review_required"] is True,
            "not_accepted": candidate_is_accepted({"acceptance_summary": reconstructed_summary}) is False,
            "repair_budget_unchanged": record["repair"]["within_budget"],
            "zero_real_model_requests": len(counter) == 1,
        },
    })
    return record


def run_path_b() -> dict:
    """Path B: astroid repair trial. The inapplicable smoothness radial assertion
    fails; removing it, the independent astroid identity proof passes and the
    repaired plan is re-interpreted through the normal chain."""
    source = "生成星形线，最大半径2米"
    plan = {"units": "m", "steps": [{
        "op": "add_parametric_curve", "step_id": "outline", "output_ref": "outline",
        "semantic": {"label": "星形线"},
        "x_expression": "2*cos(t)**3", "y_expression": "2*sin(t)**3",
        "t_start": "0", "t_end": "2*pi", "max_sampling_error": 0.001, "closed": True,
    }], "assertions": [{
        "kind": "radial_pattern", "assertion_id": "smooth", "target_ref": "outline",
        "lobes": 4, "profile": "smooth",
    }]}
    counter: list = []
    result = interpret_construction_request(
        source, _counting_callback(
            {"schema_version": "cad.construction-interpretation.v1",
             "is_construction_request": True, "plan": deepcopy(plan),
             "confidence": 0.99, "evidence_text": [source], "assumptions": []}, counter),
        force_structured_model=True)

    repairs = result.get("deterministic_repairs") or []
    repair = next((r for r in repairs if r.get("kind") ==
                   "source_curve_identity_replaces_inapplicable_smoothness"), {})
    proof = repair.get("independent_acceptance") or {}
    summary = result.get("acceptance_summary")

    record = _record_common(
        "B-astroid-repair",
        "cad_construction_interpreter.py:1085 (repair trial semantic verify); record :1093-1097",
        "natural", source, plan, len(counter), repairs)
    record.update({
        "interpreter_status": result.get("status"),
        "acceptance_output": {
            "proof": {
                "status": proof.get("status"),
                "review_required": proof.get("review_required"),
                "reason": proof.get("reason"),
                "coverage": proof.get("coverage"),
                "object_acceptance": proof.get("object_acceptance"),
            },
            "binding_evidence": _binding_evidence(proof.get("binding")),
            "geometry_unchanged": repair.get("geometry_unchanged"),
            "attribution_fields_present": _attribution_preserved(proof, require_review_fields=False),
        },
        "summary_output": {"summary": summary},
        "candidate_state": _candidate_state(summary),
        "evidence_checks": {
            "binding_passed_to_verifier": _binding_evidence(proof.get("binding"))["trusted_with_empty_issues"],
            "attribution_not_dropped": _attribution_preserved(proof, require_review_fields=False),
            "review_required_reaches_summary": isinstance(summary, dict) and summary["review_required"] is True,
            "not_accepted": candidate_is_accepted({"acceptance_summary": summary}) is False,
            "repair_budget_unchanged": record["repair"]["within_budget"],
            "zero_real_model_requests": len(counter) == 1,
        },
    })
    return record


def run_path_c() -> dict:
    """Path C: regular-polygon boundary repair trial. The unrequested bounds_size
    assertion fails; removing it, the independent polygon proof passes and the
    repaired plan is re-interpreted through the normal chain."""
    source = "生成一个正六边形，外接圆半径1米"
    plan = {"units": "m", "steps": [{
        "op": "add_polyline", "step_id": "hex", "output_ref": "hex",
        "semantic": {"label": "正六边形"}, "closed": True,
        "vertices": [{"x": math.cos(i * math.pi / 3), "y": math.sin(i * math.pi / 3)}
                     for i in range(6)],
    }], "assertions": [{
        "kind": "bounds_size", "assertion_id": "wrong_bbox", "target_ref": "hex",
        "width": 2, "height": 2,
    }]}
    counter: list = []
    payload = {"schema_version": "cad.construction-interpretation.v1",
               "is_construction_request": True, "confidence": 0.95,
               "evidence_text": [source], "assumptions": [], "plan": plan}
    result = interpret_construction_request(source, _counting_callback(payload, counter),
                                            force_structured_model=True)

    repairs = result.get("deterministic_repairs") or []
    repair = next((r for r in repairs if r.get("kind") ==
                   "source_radial_acceptance_replaces_unrequested_bounds"), {})
    proof = repair.get("independent_acceptance") or {}
    summary = result.get("acceptance_summary")

    record = _record_common(
        "C-polygon-boundary-repair",
        "cad_construction_interpreter.py:1118 (repair trial semantic verify); record :1127-1131",
        "natural", source, plan, len(counter), repairs)
    record.update({
        "interpreter_status": result.get("status"),
        "acceptance_output": {
            "proof": {
                "status": proof.get("status"),
                "review_required": proof.get("review_required"),
                "reason": proof.get("reason"),
                "coverage": proof.get("coverage"),
                "object_acceptance": proof.get("object_acceptance"),
            },
            "binding_evidence": _binding_evidence(proof.get("binding")),
            "geometry_unchanged": repair.get("geometry_unchanged"),
            "attribution_fields_present": _attribution_preserved(proof, require_review_fields=False),
        },
        "summary_output": {"summary": summary},
        "candidate_state": _candidate_state(summary),
        "evidence_checks": {
            "binding_passed_to_verifier": _binding_evidence(proof.get("binding"))["trusted_with_empty_issues"],
            "attribution_not_dropped": _attribution_preserved(proof, require_review_fields=False),
            "review_required_reaches_summary": isinstance(summary, dict) and summary["review_required"] is True,
            "not_accepted": candidate_is_accepted({"acceptance_summary": summary}) is False,
            "repair_budget_unchanged": record["repair"]["within_budget"],
            "zero_real_model_requests": len(counter) == 1,
        },
    })
    return record


def main() -> dict:
    report: dict = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "zero_model": True,
        "git": {},
        "paths": [],
    }
    try:
        head = _git("rev-parse", "HEAD")
        report["git"] = {
            "base_commit": head,
            "base_parent": _git("rev-parse", "HEAD^"),
            "expected_commit_parent": head,
            "expected_base_sha": PARENT_SHA,
            "branch": _git("branch", "--show-current"),
        }
    except Exception as exc:  # pragma: no cover
        report["git"]["error"] = str(exc)

    for runner in (run_path_a, run_path_b, run_path_c):
        report["paths"].append(runner())
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(BACKEND / "evaluations" / "v1" / "round9" /
                                             "c_round9_g2_path_results.json"))
    args = parser.parse_args()
    data = main()
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"written": str(out), "paths": len(data["paths"])}, ensure_ascii=False))
