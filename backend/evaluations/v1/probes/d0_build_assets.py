"""Build D0 case registry, six-dimension schema and zero-cost replay records.

All generated evidence is derived from repository files or from deterministic
probes in this directory. No model callback, credential, project store or
candidate store is used.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[3]
PROBES = Path(__file__).resolve().parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(PROBES) not in sys.path:
    sys.path.insert(0, str(PROBES))

from app.cad_construction_interpreter import interpret_construction_request
from d0_geometry_probe import a9_plan, run_plan, s1_plan, junction_repair_probe

V1 = BACKEND / "evaluations" / "v1"
FROZEN = BACKEND / "evaluations" / "p1.3e_dual_case_frozen.json"
BENCH6 = BACKEND / "evaluations" / "cad_construction_model_benchmark.json"
BENCH55 = BACKEND / "evaluations" / "cad_construction_model_benchmark_extended.json"
BASELINE = "9bd105fed075c717df88774f7abb4cd4e7a21c3a"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_text(raw)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def rel(path: Path) -> str:
    return path.relative_to(BACKEND).as_posix()


def status(value: Any, allowed: set[str], default: str = "unknown") -> str:
    return value if isinstance(value, str) and value in allowed else default


def dimension(status_value: str, reason: str | None = None, refs: list[str] | None = None) -> dict:
    return {
        "status": status_value,
        "reason": reason,
        "evidence_refs": refs or [],
    }


def model_dimension(*, called: bool = False, provider: str | None = None,
                    model: str | None = None, request_ref: str | None = None,
                    response_ref: str | None = None, input_tokens: int | None = None,
                    output_tokens: int | None = None, cost_usd: float | None = None) -> dict:
    return {
        "called": called,
        "provider": provider,
        "model": model,
        "request_ref": request_ref,
        "response_ref": response_ref,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost_usd,
    }


def version_dimension() -> dict:
    return {
        "project_id": None,
        "candidate_id": None,
        "parent_version_id": None,
        "version_id": None,
        "final_version_status": "not_persisted",
        "project_persistence": False,
    }


def empty_geometry(status_value: str = "not_run", reason: str | None = None) -> dict:
    return {
        "status": status_value,
        "reason": reason,
        "geometry_hash": None,
        "geometry_count": 0,
        "closed": None,
        "self_intersection_count": None,
        "continuity": {
            "required": None,
            "measured": None,
            "passed": None,
            "max_tangent_delta_deg": None,
        },
        "bounds": None,
        "error_code": None,
    }


def build_registry() -> dict:
    frozen = load_json(FROZEN)
    cases = frozen["cases"]
    canonical_cases = canonical_sha256(cases)
    if canonical_cases != frozen["frozen_input_sha256"]:
        raise RuntimeError("frozen_input_sha256 mismatch; refusing to build registry")
    bench6 = load_json(BENCH6)
    bench55 = load_json(BENCH55)
    ids6 = [item["id"] for item in bench6["cases"]]
    ids55 = [item["id"] for item in bench55["cases"]]
    if not set(ids6).issubset(set(ids55)):
        raise RuntimeError("core6 is not a subset of extended55")

    entries: list[dict] = []

    for case_id in ("A9", "S1"):
        case = cases[case_id]
        entries.append({
            "case_id": case_id,
            "case_version": "p1.3e_dual_case_frozen",
            "category": "complex_closed_heart" if case_id == "A9" else "open_three_segment_bezier",
            "original_input": case["prompt"],
            "input_sha256": sha256_text(case["prompt"]),
            "case_canonical_sha256": canonical_sha256(case),
            "acceptance_rules": case["acceptance"],
            "acceptance_rules_sha256": canonical_sha256(case["acceptance"]),
            "expected_route": "construction_scope",
            "expected_requirements": case["acceptance"],
            "freeze_status": "frozen",
            "formal_scoring_eligible": True,
            "end_to_end_scoring_eligible": True,
            "current_evidence_status": "not_run_exact_replay",
            "source_ref": rel(FROZEN),
            "units": case.get("units"),
            "kind": case.get("kind"),
            "historical_plan_status": "unavailable" if case_id == "A9" else "not_applicable",
            "historical_plan_ref_sha256": (
                sha256_text(case["historical_plan"])
                if case_id == "A9" and isinstance(case.get("historical_plan"), str)
                else None
            ),
            "notes": (
                "A9 historical plan path is external and unavailable in the repository; "
                "only prompt, acceptance and diagnostic control points are reusable."
                if case_id == "A9"
                else "S1 prompt and acceptance are frozen; real model response is unavailable."
            ),
        })

    entries.append({
        "case_id": "M1",
        "case_version": "unfrozen",
        "category": "mechanical_folded_corner",
        "original_input": None,
        "input_sha256": None,
        "case_canonical_sha256": None,
        "acceptance_rules": None,
        "acceptance_rules_sha256": None,
        "expected_route": None,
        "expected_requirements": [],
        "freeze_status": "unfrozen",
        "formal_scoring_eligible": False,
        "end_to_end_scoring_eligible": False,
        "current_evidence_status": "not_run",
        "source_ref": "backend/evaluations/P1.4 A9-S1-M1真实DeepSeek评测零费用准入报告20261107.md",
        "units": None,
        "kind": None,
        "historical_plan_status": "not_applicable",
        "historical_plan_ref_sha256": None,
        "missing_fields": [
            "formal_case_id",
            "natural_language_input",
            "units",
            "fold_corner_location",
            "allowed_curve_connections",
            "independent_acceptance_fields",
            "expected_route",
            "freeze_authority",
        ],
        "notes": "M1 has no complete frozen definition; it must not enter formal scoring.",
    })

    for item in bench55["cases"]:
        case_id = item["id"]
        suite = ["extended55"] + (["core6"] if case_id in ids6 else [])
        entries.append({
            "case_id": case_id,
            "case_version": "extended55",
            "category": item["category"],
            "original_input": item["command"],
            "input_sha256": sha256_text(item["command"]),
            "case_canonical_sha256": canonical_sha256(item),
            "acceptance_rules": item["expected"],
            "acceptance_rules_sha256": canonical_sha256(item["expected"]),
            "expected_route": "construction_scope",
            "route_evidence": "inferred from construction benchmark category; benchmark calls the interpreter directly and bypasses the product router",
            "expected_requirements": item["expected"],
            "freeze_status": "repository_fixture",
            "formal_scoring_eligible": True,
            "end_to_end_scoring_eligible": False,
            "current_evidence_status": "rule_parser_zero_cost",
            "benchmark_suites": suite,
            "source_ref": rel(BENCH55),
            "units": None,
            "kind": "construction_benchmark_case",
            "historical_plan_status": "not_applicable",
            "historical_plan_ref_sha256": None,
            "notes": "Construction-interpretation benchmark fixture, not an end-to-end acceptance case.",
        })

    counts = {
        "total_cases": len(entries),
        "frozen_cases": 2,
        "unfrozen_cases": 1,
        "benchmark_unique_cases": len(ids55),
        "benchmark_core6_cases": len(ids6),
        "benchmark_extended55_cases": len(ids55),
    }
    return {
        "schema": "cad.d0.case-registry.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "baseline_commit": BASELINE,
        "source_files": {
            "frozen_cases": {
                "path": rel(FROZEN),
                "file_sha256": sha256_bytes(FROZEN.read_bytes()),
                "declared_cases_sha256": frozen.get("frozen_input_sha256"),
                "recomputed_cases_sha256": canonical_cases,
            },
            "benchmark_core6": {
                "path": rel(BENCH6),
                "file_sha256": sha256_bytes(BENCH6.read_bytes()),
                "case_count": len(ids6),
            },
            "benchmark_extended55": {
                "path": rel(BENCH55),
                "file_sha256": sha256_bytes(BENCH55.read_bytes()),
                "case_count": len(ids55),
            },
        },
        "freeze_status_vocabulary": ["frozen", "unfrozen", "repository_fixture"],
        "formal_scoring_policy": {
            "M1": "excluded until a complete frozen definition exists",
            "benchmark_cases": "eligible for construction-interpretation scoring only; not end-to-end scoring",
            "A9_S1": "eligible for formal scoring when exact or reconstructed evidence is explicitly labelled",
        },
        "cases": entries,
        "counts": counts,
    }


def build_schema() -> dict:
    status_enum = ["passed", "failed", "not_checked", "unknown", "not_applicable"]
    evidence_modes = [
        "mock", "reconstructed_fixture", "historical_report",
        "rule_parser_zero_cost", "live_model", "unavailable",
    ]
    failure_categories = [
        "self_intersection", "constraint_loss", "c1_continuity",
        "route_misclassification", "source_acceptance_gap",
        "clarification_required", "benchmark_expectation_mismatch",
        "collection_blocked", "environment_blocked",
        "checkpoint_contract_mismatch", "unfrozen_case_definition",
        "http_e2e_unverified", "not_applicable", "unknown",
    ]
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "cad.d0.evaluation-record.v1",
        "title": "Natural Language CAD Agent D0 six-dimension evaluation record",
        "type": "object",
        "additionalProperties": True,
        "required": [
            "schema_version", "case_id", "input_sha256", "evidence_mode",
            "expected_route", "actual_route", "model", "planning", "source",
            "geometry", "acceptance", "version", "final_outcome", "failure_category",
        ],
        "properties": {
            "schema_version": {"const": "cad.d0.evaluation-record.v1"},
            "case_id": {"type": "string", "minLength": 1},
            "case_version": {"type": ["string", "null"]},
            "input_sha256": {
                "anyOf": [
                    {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                    {"type": "null"},
                ]
            },
            "evidence_mode": {"enum": evidence_modes},
            "evidence_refs": {"type": "array", "items": {"type": "string"}},
            "expected_route": {"type": ["string", "null"]},
            "actual_route": {"type": ["string", "null"]},
            "model": {"$ref": "#/$defs/model"},
            "planning": {"$ref": "#/$defs/planning"},
            "source": {"$ref": "#/$defs/source"},
            "geometry": {"$ref": "#/$defs/geometry"},
            "acceptance": {"$ref": "#/$defs/acceptance"},
            "version": {"$ref": "#/$defs/version"},
            "final_outcome": {
                "enum": ["passed", "failed", "not_run", "unknown",
                         "collection_blocked", "environment_blocked"]
            },
            "outcome_scope": {"type": "string"},
            "failure_category": {
                "anyOf": [
                    {"enum": failure_categories},
                    {"type": "null"},
                ]
            },
            "notes": {"type": "string"},
        },
        "$defs": {
            "model": {
                "type": "object",
                "additionalProperties": True,
                "required": ["called", "provider", "model", "request_ref",
                              "response_ref", "input_tokens", "output_tokens", "cost_usd"],
                "properties": {
                    "called": {"type": "boolean"},
                    "provider": {"type": ["string", "null"]},
                    "model": {"type": ["string", "null"]},
                    "request_ref": {"type": ["string", "null"]},
                    "response_ref": {"type": ["string", "null"]},
                    "input_tokens": {"type": ["integer", "null"]},
                    "output_tokens": {"type": ["integer", "null"]},
                    "cost_usd": {"type": ["number", "null"]},
                },
            },
            "planning": {
                "type": "object",
                "additionalProperties": True,
                "required": ["route", "requirement_contract_ref", "requirement_ledger_ref",
                              "structured_plan_hash", "parser", "status"],
                "properties": {
                    "route": {"type": ["string", "null"]},
                    "requirement_contract_ref": {"type": ["string", "null"]},
                    "requirement_ledger_ref": {"type": ["string", "null"]},
                    "structured_plan_hash": {
                        "anyOf": [
                            {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                            {"type": "null"},
                        ]
                    },
                    "parser": {"type": ["string", "null"]},
                    "status": {"type": "string"},
                    "expected_status": {"type": ["string", "null"]},
                    "failed_checks": {"type": "array", "items": {"type": "string"}},
                },
            },
            "source": {
                "type": "object",
                "additionalProperties": True,
                "required": ["conversation_id", "source_ids", "h3_status", "evidence_refs"],
                "properties": {
                    "conversation_id": {"type": ["string", "null"]},
                    "source_ids": {"type": "array", "items": {"type": "string"}},
                    "h3_status": {"enum": status_enum},
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                },
            },
            "geometry": {
                "type": "object",
                "additionalProperties": True,
                "required": ["status", "geometry_hash", "geometry_count", "closed",
                              "self_intersection_count", "continuity", "bounds", "error_code"],
                "properties": {
                    "status": {"enum": status_enum},
                    "geometry_hash": {
                        "anyOf": [
                            {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                            {"type": "null"},
                        ]
                    },
                    "geometry_count": {"type": "integer", "minimum": 0},
                    "closed": {"type": ["boolean", "null"]},
                    "self_intersection_count": {"type": ["integer", "null"]},
                    "continuity": {
                        "type": "object",
                        "additionalProperties": True,
                        "required": ["required", "measured", "passed",
                                      "max_tangent_delta_deg"],
                        "properties": {
                            "required": {"type": ["string", "null"]},
                            "measured": {"type": ["string", "null"]},
                            "passed": {"type": ["boolean", "null"]},
                            "max_tangent_delta_deg": {"type": ["number", "null"]},
                        },
                    },
                    "bounds": {"type": ["object", "null"]},
                    "error_code": {"type": ["string", "null"]},
                },
            },
            "acceptance": {
                "type": "object",
                "additionalProperties": True,
                "required": ["h2", "h3", "h4"],
                "properties": {
                    "h2": {"$ref": "#/$defs/dimension"},
                    "h3": {"$ref": "#/$defs/dimension"},
                    "h4": {"$ref": "#/$defs/dimension"},
                },
            },
            "dimension": {
                "type": "object",
                "additionalProperties": True,
                "required": ["status", "reason", "evidence_refs"],
                "properties": {
                    "status": {"enum": status_enum},
                    "reason": {"type": ["string", "null"]},
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                },
            },
            "version": {
                "type": "object",
                "additionalProperties": True,
                "required": ["project_id", "candidate_id", "parent_version_id",
                              "version_id", "final_version_status", "project_persistence"],
                "properties": {
                    "project_id": {"type": ["string", "null"]},
                    "candidate_id": {"type": ["string", "null"]},
                    "parent_version_id": {"type": ["string", "null"]},
                    "version_id": {"type": ["string", "null"]},
                    "final_version_status": {
                        "enum": ["not_persisted", "created", "saved", "failed", "unknown"]
                    },
                    "project_persistence": {"type": "boolean"},
                },
            },
        },
    }


def benchmark_acceptance(raw: dict) -> tuple[dict, dict, dict]:
    structure = raw.get("structure_validation")
    if isinstance(structure, dict):
        ok = structure.get("ok")
        h2_status = "passed" if ok is True else "failed" if ok is False else "unknown"
        h2_reason = structure.get("reason") or structure.get("message")
    else:
        h2_status, h2_reason = "not_checked", "structure_validation not emitted by benchmark path"
    source = raw.get("source_acceptance") if isinstance(raw.get("source_acceptance"), dict) else {}
    h3_status = status(source.get("status"), {"passed", "failed", "not_checked", "unknown"}, "not_checked")
    h3_reason = source.get("reason") or "source acceptance status from interpreter"
    summary = raw.get("acceptance_summary") if isinstance(raw.get("acceptance_summary"), dict) else {}
    constraint = summary.get("constraint_satisfaction")
    assertion = summary.get("assertion_status")
    if constraint == "passed" and assertion == "passed":
        h4_status = "passed"
    elif constraint == "failed" or assertion == "failed":
        h4_status = "failed"
    else:
        h4_status = "not_checked"
    h4_reason = f"constraint_satisfaction={constraint}; assertion_status={assertion}"
    return (
        dimension(h2_status, h2_reason),
        dimension(h3_status, h3_reason),
        dimension(h4_status, h4_reason, ["app/cad_semantic_acceptance.py"]),
    )


def benchmark_record(case: dict, report_item: dict, raw: dict) -> dict:
    trial = raw.get("trial_result") if isinstance(raw.get("trial_result"), dict) else {}
    geometries = trial.get("geometries") if isinstance(trial.get("geometries"), list) else []
    plan = raw.get("plan") if isinstance(raw.get("plan"), dict) else None
    topology = trial.get("topology") if isinstance(trial.get("topology"), dict) else {}
    feasibility = trial.get("feasibility") if isinstance(trial.get("feasibility"), dict) else {}
    self_intersection = topology.get("self_intersection_count")
    if not isinstance(self_intersection, int):
        self_intersection = feasibility.get("self_intersection_count")
    if not isinstance(self_intersection, int):
        self_intersection = None
    closed = None
    if len(geometries) == 1 and isinstance(geometries[0], dict):
        closed = bool(geometries[0].get("closed"))
    h2, h3, h4 = benchmark_acceptance(raw)
    failed = [key for key, value in (report_item.get("checks") or {}).items() if not value]
    passed = bool(report_item.get("passed"))
    status_value = report_item.get("status") or raw.get("status") or "unknown"
    failure_category = None
    if not passed:
        failure_category = (
            "clarification_required" if status_value == "clarification_required"
            else "benchmark_expectation_mismatch"
        )
    return {
        "schema_version": "cad.d0.evaluation-record.v1",
        "case_id": case["id"],
        "case_version": "extended55",
        "input_sha256": sha256_text(case["command"]),
        "evidence_mode": "rule_parser_zero_cost",
        "expected_route": "construction_scope",
        "actual_route": "benchmark_direct_interpreter",
        "model": model_dimension(
            called=False, provider="deterministic_rules", model="rule_parser",
            input_tokens=0, output_tokens=0, cost_usd=0.0,
        ),
        "planning": {
            "route": "benchmark_direct_interpreter",
            "requirement_contract_ref": None,
            "requirement_ledger_ref": None,
            "structured_plan_hash": canonical_sha256(plan) if plan else None,
            "parser": raw.get("parser") or report_item.get("parser"),
            "status": status_value,
            "expected_status": case["expected"].get("status"),
            "failed_checks": failed,
        },
        "source": {
            "conversation_id": None,
            "source_ids": [f"benchmark:{case['id']}"],
            "h3_status": h3["status"],
            "evidence_refs": [rel(BENCH55)],
        },
        "geometry": {
            "status": "passed" if geometries else "not_run",
            "geometry_hash": canonical_sha256(geometries) if geometries else None,
            "geometry_count": len(geometries),
            "closed": closed,
            "self_intersection_count": self_intersection,
            "continuity": {
                "required": None,
                "measured": None,
                "passed": None,
                "max_tangent_delta_deg": None,
            },
            "bounds": feasibility.get("bounds"),
            "error_code": (report_item.get("error") or None),
        },
        "acceptance": {"h2": h2, "h3": h3, "h4": h4},
        "version": version_dimension(),
        "final_outcome": "passed" if passed else "failed",
        "outcome_scope": "benchmark_interpretation_only",
        "failure_category": failure_category,
        "notes": "Rule-parser construction benchmark record; not an end-to-end success.",
        "evidence_refs": [rel(BENCH55), "backend/evaluations/v1/probes/rule_benchmark_extended55.json"],
    }


def build_mock_replay(registry: dict) -> dict:
    a9 = run_plan(a9_plan())
    s1 = run_plan(s1_plan())
    junction = junction_repair_probe()
    report6 = load_json(PROBES / "rule_benchmark_core6.json")
    report55 = load_json(PROBES / "rule_benchmark_extended55.json")
    by_id = {item["case_id"]: item for item in report55["results"]}
    bench55 = load_json(BENCH55)

    a9_record = {
        "schema_version": "cad.d0.evaluation-record.v1",
        "case_id": "A9",
        "case_version": "p1.3e_dual_case_frozen",
        "input_sha256": sha256_text(
            load_json(FROZEN)["cases"]["A9"]["prompt"]
        ),
        "evidence_mode": "reconstructed_fixture",
        "expected_route": "construction_scope",
        "actual_route": "not_available",
        "model": model_dimension(),
        "planning": {
            "route": "construction_scope",
            "requirement_contract_ref": None,
            "requirement_ledger_ref": None,
            "structured_plan_hash": a9["status"] and canonical_sha256(a9_plan()),
            "parser": None,
            "status": "historical_response_unavailable",
            "expected_status": "ready",
            "failed_checks": ["self_intersection"],
        },
        "source": {
            "conversation_id": None,
            "source_ids": ["frozen:p1.3e_dual_case_frozen#A9"],
            "h3_status": "not_checked",
            "evidence_refs": [rel(FROZEN)],
        },
        "geometry": {
            "status": "failed",
            "geometry_hash": None,
            "geometry_count": 0,
            "closed": True,
            "self_intersection_count": len(
                ((a9.get("error") or {}).get("details") or {}).get("conflicts") or []
            ),
            "continuity": {
                "required": "measure_C0_and_C1",
                "measured": None,
                "passed": None,
                "max_tangent_delta_deg": None,
            },
            "bounds": None,
            "error_code": (a9.get("error") or {}).get("code"),
        },
        "acceptance": {
            "h2": dimension("not_checked", "no current H2 end-to-end run"),
            "h3": dimension("not_checked", "no current H3 source ledger"),
            "h4": dimension("not_checked", "no current H4 semantic acceptance run"),
        },
        "version": version_dimension(),
        "final_outcome": "failed",
        "outcome_scope": "reconstructed_fixture_geometry",
        "failure_category": "self_intersection",
        "notes": "Exact historical plan response is unavailable. This fixture uses the exact A9 segment 0/5 control points plus one synthetic connector; it is not an exact historical replay.",
        "evidence_refs": [
            rel(FROZEN),
            "backend/evaluations/v1/probes/d0_geometry_probe.py",
            "backend/app/cad_construction.py:1151-1195",
        ],
    }

    junction_record = {
        "schema_version": "cad.d0.evaluation-record.v1",
        "case_id": "A9-JUNCTION",
        "case_version": "derived_mock",
        "input_sha256": a9_record["input_sha256"],
        "evidence_mode": "mock",
        "expected_route": "construction_scope",
        "actual_route": "component_repair_merge_mock",
        "model": model_dimension(),
        "planning": {
            "route": "component_repair_merge",
            "requirement_contract_ref": None,
            "requirement_ledger_ref": None,
            "structured_plan_hash": junction.get("before_plan_sha256"),
            "parser": "pure_function_mock",
            "status": "failed",
            "expected_status": "junction_constraints_preserved",
            "failed_checks": ["junction_constraints_preserved"],
        },
        "source": {
            "conversation_id": None,
            "source_ids": ["mock:a9-junction-fixture"],
            "h3_status": "not_checked",
            "evidence_refs": ["backend/app/cad_plan_component_repair.py:36-43"],
        },
        "geometry": empty_geometry("not_run", "merge occurs before geometry execution"),
        "acceptance": {
            "h2": dimension("not_checked", "merge-only probe"),
            "h3": dimension("not_checked", "merge-only probe"),
            "h4": dimension("not_checked", "geometry not reached after constraint loss"),
        },
        "version": version_dimension(),
        "final_outcome": "failed",
        "outcome_scope": "component_repair_merge_only",
        "failure_category": "constraint_loss",
        "notes": "Pure-function reproduction: merge_component_repair retains only step_id/output_ref/semantic/layer_id, so the replacement step loses junction_constraints. This reproduces the A9 symptom without claiming an exact historical model response.",
        "evidence_refs": [
            "backend/app/cad_plan_component_repair.py:36-43",
            "backend/app/agent_service.py:6229-6232",
            "backend/evaluations/v1/probes/d0_geometry_probe.py",
        ],
    }

    quality = (s1.get("curve_quality") or [{}])[0]
    bounds = (s1.get("feasibility") or {}).get("bounds")
    s1_record = {
        "schema_version": "cad.d0.evaluation-record.v1",
        "case_id": "S1",
        "case_version": "p1.3e_dual_case_frozen",
        "input_sha256": sha256_text(load_json(FROZEN)["cases"]["S1"]["prompt"]),
        "evidence_mode": "reconstructed_fixture",
        "expected_route": "construction_scope",
        "actual_route": "not_run_end_to_end",
        "model": model_dimension(),
        "planning": {
            "route": "construction_scope",
            "requirement_contract_ref": None,
            "requirement_ledger_ref": None,
            "structured_plan_hash": canonical_sha256(s1_plan()),
            "parser": "reconstructed_fixture",
            "status": "ready",
            "expected_status": "ready",
            "failed_checks": [],
        },
        "source": {
            "conversation_id": None,
            "source_ids": ["frozen:p1.3e_dual_case_frozen#S1"],
            "h3_status": "not_checked",
            "evidence_refs": [
                rel(FROZEN),
                "backend/app/cad_construction_interpreter.py:170-177",
            ],
        },
        "geometry": {
            "status": "passed",
            "geometry_hash": s1.get("geometry_hash"),
            "geometry_count": s1.get("geometry_count") or 0,
            "closed": quality.get("closed"),
            "self_intersection_count": quality.get("self_intersection_count"),
            "continuity": {
                "required": quality.get("continuity_required"),
                "measured": "C1" if quality.get("c1") else "C0",
                "passed": bool(quality.get("c1")),
                "max_tangent_delta_deg": quality.get("maximum_tangent_delta_deg"),
            },
            "bounds": bounds,
            "error_code": None,
        },
        "acceptance": {
            "h2": dimension("not_checked", "no current H2 end-to-end run"),
            "h3": dimension("not_checked", "source acceptance has no current conversation/source ledger fixture"),
            "h4": dimension("not_checked", "C1 geometry measured independently; H4 semantic acceptance not executed"),
        },
        "version": version_dimension(),
        "final_outcome": "passed",
        "outcome_scope": "reconstructed_fixture_geometry_only",
        "failure_category": None,
        "notes": "C1 geometry independently passes with maximum tangent delta 0.0 deg and zero self-intersections. This does not prove the real model can generate it or that H3 source acceptance passes.",
        "evidence_refs": [
            rel(FROZEN),
            "backend/evaluations/v1/probes/d0_geometry_probe.py",
            "backend/app/cad_construction_interpreter.py:170-177",
        ],
    }

    m1_record = {
        "schema_version": "cad.d0.evaluation-record.v1",
        "case_id": "M1",
        "case_version": "unfrozen",
        "input_sha256": None,
        "evidence_mode": "unavailable",
        "expected_route": None,
        "actual_route": "not_run",
        "model": model_dimension(),
        "planning": {
            "route": None,
            "requirement_contract_ref": None,
            "requirement_ledger_ref": None,
            "structured_plan_hash": None,
            "parser": None,
            "status": "not_run",
            "expected_status": None,
            "failed_checks": [],
        },
        "source": {
            "conversation_id": None,
            "source_ids": [],
            "h3_status": "not_checked",
            "evidence_refs": [],
        },
        "geometry": empty_geometry("not_run", "M1 has no frozen input or acceptance rules"),
        "acceptance": {
            "h2": dimension("not_checked", "no frozen M1 definition"),
            "h3": dimension("not_checked", "no frozen M1 definition"),
            "h4": dimension("not_checked", "no frozen M1 definition"),
        },
        "version": version_dimension(),
        "final_outcome": "not_run",
        "outcome_scope": "unfrozen_case",
        "failure_category": "unfrozen_case_definition",
        "notes": "M1 is excluded from formal scoring until the missing fields are confirmed.",
        "evidence_refs": [
            "backend/evaluations/P1.4 A9-S1-M1真实DeepSeek评测零费用准入报告20261107.md",
        ],
    }

    records = [a9_record, junction_record, s1_record, m1_record]
    for case in bench55["cases"]:
        records.append(benchmark_record(case, by_id[case["id"]], interpret_construction_request(case["command"], None)))

    counts = {
        "records_total": len(records),
        "passed": sum(item["final_outcome"] == "passed" for item in records),
        "failed": sum(item["final_outcome"] == "failed" for item in records),
        "not_run": sum(item["final_outcome"] == "not_run" for item in records),
        "real_model_calls": 0,
        "project_persistence": False,
        "candidate_writes": 0,
    }
    return {
        "schema": "cad.d0.mock-replay.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "baseline_commit": BASELINE,
        "no_real_model_calls": True,
        "no_project_or_candidate_writes": True,
        "evidence_mode_policy": {
            "live_model": "real provider call; unavailable in D0",
            "rule_parser_zero_cost": "deterministic rule interpreter; not end-to-end",
            "mock": "pure function or test double; no provider",
            "reconstructed_fixture": "built from repository-known inputs or control points; not an exact historical response",
            "historical_report": "existing Markdown report; observation only, not a reproduced run",
            "unavailable": "raw response or frozen definition does not exist",
        },
        "benchmark_runs": {
            "core6": {
                "path": rel(BENCH6),
                "file_sha256": sha256_bytes(BENCH6.read_bytes()),
                "summary": report6["summaries"]["rules"],
            },
            "extended55": {
                "path": rel(BENCH55),
                "file_sha256": sha256_bytes(BENCH55.read_bytes()),
                "summary": report55["summaries"]["rules"],
            },
        },
        "http_capability": {
            "status": "partial",
            "modules": {
                "tests/test_agent_run_api.py": {"passed": 6, "failed": 4, "status": "failed"},
                "tests/test_candidate_save.py": {"passed": 1, "failed": 0, "status": "passed"},
                "tests/test_cad_construction_commit.py": {"passed": 10, "failed": 0, "status": "passed"},
            },
            "resume_failures": [
                "test_resume_from_generated_result_skips_model_and_execution",
                "test_resume_from_prepared_context_skips_context_rebuild",
                "test_resume_run_api_replays_original_request_into_same_run",
                "test_resume_run_api_respects_owner",
            ],
            "resume_failure_reason": "checkpoint fixture lacks signed execution_context required by agent_http_service.py:754-768",
            "missing_e2e_assets": [
                "valid agent.checkpoint.v3 execution_context with sha256",
                "HTTP create-project -> chat -> candidate -> save-drawing -> start-iteration chain",
                "parent/child version inheritance assertion",
            ],
        },
        "records": records,
        "summary": counts,
    }


def main() -> int:
    registry = build_registry()
    schema = build_schema()
    replay = build_mock_replay(registry)

    (V1 / "case_registry.json").write_text(
        json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    (V1 / "evaluation_schema.json").write_text(
        json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
    (V1 / "mock_replay_results.json").write_text(
        json.dumps(replay, ensure_ascii=False, indent=2), encoding="utf-8")

    required = set(schema["required"])
    for record in replay["records"]:
        missing = required - set(record)
        if missing:
            raise RuntimeError(f"record {record.get('case_id')} missing {sorted(missing)}")
    print(json.dumps({
        "case_registry": {"cases": registry["counts"]["total_cases"]},
        "evaluation_schema": {"required_fields": sorted(required)},
        "mock_replay": replay["summary"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
