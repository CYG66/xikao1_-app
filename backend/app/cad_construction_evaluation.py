"""Read-only benchmark utilities for generic natural-language CAD construction."""

from __future__ import annotations

import time
from copy import deepcopy
from pathlib import Path
import json
from typing import Any, Callable

from .cad_construction_interpreter import (
    interpret_construction_request,
    interpret_sketch_graph_candidates,
)


DEFAULT_CONSTRUCTION_BENCHMARK_PATH = (
    Path(__file__).resolve().parents[1]
    / "evaluations"
    / "cad_construction_model_benchmark.json"
)

ConstructionRunner = Callable[[str, str], dict[str, Any]]


def evaluate_construction_interpretation(
    service: Any,
    message: str,
    *,
    mode: str = "advanced",
    alternatives: bool = False,
    force_structured_model: bool = False,
) -> dict[str, Any]:
    """Exercise evaluation-only construction modes without persistence.

    Production always uses the service's single-plan, rule-first entry. This
    adapter owns forced structured-model and multi-candidate SketchGraph modes
    so benchmark controls cannot leak into the chat pipeline.
    """
    callback, state = service._cad_construction_model_callback(
        mode=mode,
        alternatives=alternatives,
    )
    if alternatives:
        result = interpret_sketch_graph_candidates(message, callback)
    else:
        result = interpret_construction_request(
            message,
            callback,
            force_structured_model=force_structured_model,
        )
    attempted = bool(state["provider_attempted"])
    attempts = int(state["request_attempts"])
    result["provider"] = service.mode if attempted else None
    result["provider_attempted"] = attempted
    result["request_attempts"] = attempts
    result["structured_retry_used"] = attempts > 1
    result["persisted"] = False
    result["experimental"] = True
    result["candidate_mode"] = alternatives
    result["force_structured_model"] = force_structured_model
    return result


def load_construction_benchmark(path: Path | None = None) -> dict[str, Any]:
    source = path or DEFAULT_CONSTRUCTION_BENCHMARK_PATH
    payload = json.loads(source.read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(cases, list) or not cases:
        raise ValueError("construction benchmark must contain a non-empty cases list")
    ids = [item.get("id") for item in cases if isinstance(item, dict)]
    if len(ids) != len(cases) or any(not isinstance(value, str) or not value for value in ids):
        raise ValueError("every construction benchmark case requires a non-empty id")
    if len(ids) != len(set(ids)):
        raise ValueError("construction benchmark case ids must be unique")
    return payload


def run_construction_benchmark(
    providers: list[str],
    runner: ConstructionRunner,
    corpus: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run every case for every provider and return aggregate metrics.

    The runner owns network configuration. This function never persists CAD
    projects, reads credentials or retries failed model calls.
    """
    benchmark = deepcopy(corpus or load_construction_benchmark())
    cases = benchmark["cases"]
    results: list[dict[str, Any]] = []
    for provider in providers:
        for case in cases:
            started = time.perf_counter()
            try:
                raw = runner(provider, str(case["command"]))
                result = raw if isinstance(raw, dict) else {}
                error = ""
            except Exception as exc:
                result = {}
                error = str(exc)
            elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
            results.append(_evaluate_case(provider, case, result, elapsed_ms, error))
    summaries = {
        provider: _provider_summary(provider, results)
        for provider in providers
    }
    return {
        "schema": "cad.construction-benchmark-report.v1",
        "corpus_version": benchmark.get("version"),
        "read_only": True,
        "project_persistence": False,
        "providers": list(providers),
        "case_count": len(cases),
        "results": results,
        "summaries": summaries,
    }


def _evaluate_case(
    provider: str,
    case: dict[str, Any],
    result: dict[str, Any],
    elapsed_ms: float,
    error: str,
) -> dict[str, Any]:
    expected = case.get("expected") or {}
    status = str(result.get("status") or "provider_error")
    plan = result.get("plan") if isinstance(result.get("plan"), dict) else None
    trial = (
        result.get("trial_result")
        if isinstance(result.get("trial_result"), dict) else None
    )
    geometries = trial.get("geometries") if trial else None
    objects = trial.get("logical_objects") if trial else None
    geometries = geometries if isinstance(geometries, list) else []
    objects = objects if isinstance(objects, list) else []
    geometry_types = {str(item.get("type")) for item in geometries if isinstance(item, dict)}
    schema_valid_actual = plan is not None
    trial_executed_actual = trial is not None
    checks = {
        "expected_status": status == expected.get("status", "ready"),
        "schema_valid": plan is not None if status == "ready" else True,
        "trial_executed": trial is not None if status == "ready" else True,
        "feasible": (
            bool((trial.get("feasibility") or {}).get("ok"))
            if status == "ready" and expected.get("require_feasible", True)
            else True
        ),
        "minimum_entities": len(geometries) >= int(expected.get("minimum_entities", 0)),
        "maximum_entities": len(geometries) <= int(expected.get("maximum_entities", 5000)),
        "minimum_logical_objects": len(objects) >= int(expected.get("minimum_logical_objects", 0)),
        "required_types": set(expected.get("required_types", [])).issubset(geometry_types),
        "required_parser": (
            result.get("parser") == expected.get("required_parser")
            if expected.get("required_parser")
            else True
        ),
        "provider_attempted": (
            bool(result.get("provider_attempted"))
            if expected.get("require_provider_attempted") is True
            else True
        ),
        "no_runner_error": not error,
    }
    return {
        "provider": provider,
        "case_id": case["id"],
        "category": case.get("category", "general"),
        "passed": all(checks.values()),
        "status": status,
        "checks": checks,
        "metrics": {
            "latency_ms": elapsed_ms,
            "schema_valid": schema_valid_actual,
            "trial_executed": trial_executed_actual,
            "request_attempts": int(result.get("request_attempts") or 0),
            "structured_retry_used": bool(result.get("structured_retry_used")),
            "deterministic_repair_count": len(result.get("deterministic_repairs") or []),
            "entity_count": len(geometries),
            "logical_object_count": len(objects),
            "assertion_count": int((trial.get("assertions") or {}).get("count", 0)) if trial else 0,
        },
        "parser": result.get("parser"),
        "provider_attempted": bool(result.get("provider_attempted")),
        "error": error or (result.get("error") or {}).get("message", ""),
        "diagnostic_plan": deepcopy(
            result.get("plan")
            if isinstance(result.get("plan"), dict)
            else result.get("rejected_plan")
            if isinstance(result.get("rejected_plan"), dict)
            else None
        ),
    }


def _provider_summary(provider: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    items = [item for item in results if item["provider"] == provider]
    total = len(items)
    ready = sum(item["status"] == "ready" for item in items)
    passed = sum(bool(item["passed"]) for item in items)
    clarification = sum(item["status"] == "clarification_required" for item in items)
    retried = sum(bool(item["metrics"]["structured_retry_used"]) for item in items)
    repaired = sum(int(item["metrics"]["deterministic_repair_count"]) for item in items)
    latencies = [float(item["metrics"]["latency_ms"]) for item in items]
    return {
        "provider": provider,
        "total": total,
        "passed": passed,
        "pass_rate": passed / total if total else 0.0,
        "ready_rate": ready / total if total else 0.0,
        "clarification_rate": clarification / total if total else 0.0,
        "structured_retry_rate": retried / total if total else 0.0,
        "deterministic_repair_count": repaired,
        "average_latency_ms": sum(latencies) / total if total else 0.0,
        "schema_valid_rate": (
            sum(bool(item["metrics"]["schema_valid"]) for item in items) / total
            if total else 0.0
        ),
        "trial_success_rate": (
            sum(bool(item["metrics"]["trial_executed"]) for item in items) / total
            if total else 0.0
        ),
    }
