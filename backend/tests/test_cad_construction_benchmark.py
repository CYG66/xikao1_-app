from __future__ import annotations

from copy import deepcopy

from app.cad_construction_evaluation import (
    load_construction_benchmark,
    run_construction_benchmark,
)


def _ready_result(entity_count: int = 2) -> dict:
    geometries = [
        {"id": index + 1, "type": "polyline"}
        for index in range(entity_count)
    ]
    objects = [
        {"object_id": f"object-{index + 1}"}
        for index in range(entity_count)
    ]
    return {
        "status": "ready", "parser": "structured_model",
        "provider_attempted": True,
        "plan": {"schema_version": "cad.construction-plan.v1"},
        "trial_result": {
            "geometries": geometries,
            "logical_objects": objects,
            "feasibility": {"ok": True},
            "assertions": {"ok": True, "count": 1},
        },
    }


def test_benchmark_corpus_is_valid_and_unique() -> None:
    corpus = load_construction_benchmark()
    ids = [item["id"] for item in corpus["cases"]]

    assert len(ids) == len(set(ids))
    assert len(ids) >= 6
    assert {item["category"] for item in corpus["cases"]} >= {
        "freeform_outline", "composite_layout", "repeated_layout",
    }


def test_benchmark_aggregates_each_provider_without_mutating_corpus() -> None:
    corpus = {
        "version": "test",
        "cases": [{
            "id": "shape", "category": "test", "command": "构造图形",
            "expected": {
                "status": "ready", "minimum_entities": 2,
                "maximum_entities": 3, "minimum_logical_objects": 2,
                "required_types": ["polyline"], "require_feasible": True,
            },
        }],
    }
    before = deepcopy(corpus)

    report = run_construction_benchmark(
        ["qwen", "glm"], lambda _provider, _command: _ready_result(), corpus,
    )

    assert corpus == before
    assert len(report["results"]) == 2
    assert report["summaries"]["qwen"]["pass_rate"] == 1.0
    assert report["summaries"]["glm"]["trial_success_rate"] == 1.0
    assert report["read_only"] is True
    assert report["project_persistence"] is False
    assert report["results"][0]["diagnostic_plan"] == {
        "schema_version": "cad.construction-plan.v1"
    }


def test_benchmark_records_clarification_and_provider_failure() -> None:
    corpus = {
        "version": "test",
        "cases": [{
            "id": "shape", "category": "test", "command": "构造图形",
            "expected": {"status": "ready", "minimum_entities": 1},
        }],
    }

    def runner(provider: str, _command: str) -> dict:
        if provider == "qwen":
            return {
                "status": "clarification_required", "provider_attempted": True,
                "error": {"message": "尺寸不足"},
            }
        raise RuntimeError("network unavailable")

    report = run_construction_benchmark(["qwen", "glm"], runner, corpus)

    assert report["summaries"]["qwen"]["clarification_rate"] == 1.0
    assert report["summaries"]["qwen"]["pass_rate"] == 0.0
    assert report["summaries"]["qwen"]["schema_valid_rate"] == 0.0
    assert report["summaries"]["qwen"]["trial_success_rate"] == 0.0
    glm = next(item for item in report["results"] if item["provider"] == "glm")
    assert glm["status"] == "provider_error"
    assert glm["checks"]["no_runner_error"] is False
    assert "network unavailable" in glm["error"]


def test_benchmark_fails_geometry_constraints_even_when_status_is_ready() -> None:
    corpus = {
        "version": "test",
        "cases": [{
            "id": "shape", "category": "test", "command": "构造图形",
            "expected": {
                "status": "ready", "minimum_entities": 3,
                "minimum_logical_objects": 3, "required_types": ["circle"],
            },
        }],
    }

    report = run_construction_benchmark(
        ["qwen"], lambda _provider, _command: _ready_result(2), corpus,
    )
    item = report["results"][0]

    assert item["status"] == "ready"
    assert item["passed"] is False
    assert item["checks"]["minimum_entities"] is False
    assert item["checks"]["required_types"] is False


def test_benchmark_can_require_actual_structured_model_path() -> None:
    corpus = {
        "version": "test",
        "cases": [{
            "id": "shape", "category": "test", "command": "构造图形",
            "expected": {
                "status": "ready", "minimum_entities": 1,
                "required_parser": "structured_model",
                "require_provider_attempted": True,
            },
        }],
    }
    rule_result = _ready_result(1)
    rule_result["parser"] = "deterministic_rules"
    rule_result["provider_attempted"] = False

    report = run_construction_benchmark(
        ["deepseek"], lambda _provider, _command: rule_result, corpus,
    )
    item = report["results"][0]

    assert item["passed"] is False
    assert item["checks"]["required_parser"] is False
    assert item["checks"]["provider_attempted"] is False
