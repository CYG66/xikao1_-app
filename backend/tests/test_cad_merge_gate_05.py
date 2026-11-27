"""MERGE-GATE-05: source-set isolation and the real geometric repair loop.

R01 is exercised at the decision boundary that resolves inventory reports.
R02 goes through the production creation entry with only the model provider
mocked; the interpretation, trial geometry, residual collection, repair
dispatch, second geometry pass, independent acceptance and project persistence
all run as production code.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import PropertyMock, patch

import pytest

from app.agent_service import RobotAgentService
from app.cad_construction_commit import (
    _rebind_source_acceptance,
    _resolve_inventory_acceptance,
)
from app.creative_projects import CreativeProjectStore

R02_SOURCE = "画一个矩形宽4米高2米，在(0,0)画一个半径0.5米的圆"


def _proof(requirement_id: str, object_ids: list[str], geometry_ids: list[int]) -> dict:
    return {
        "source_requirement_id": requirement_id,
        "requirement_id": requirement_id,
        "category": "circle",
        "quantity": len(object_ids),
        "actual": len(object_ids),
        "object_ids": object_ids,
        "geometry_ids": geometry_ids,
        "unique_objects": True,
        "unique_geometries": True,
    }


def _entry(requirement_id: str, object_id: str, geometry_id: int) -> dict:
    return {
        "source": "object_inventory",
        "source_requirement_id": requirement_id,
        "category": "circle",
        "quantity": 2,
        "object_ids": [object_id, f"{object_id}_2"],
        "geometry_ids": [geometry_id, geometry_id + 1],
        "source_evidence": f"两个圆 {object_id}",
    }


def _inventory_source_acceptance(entries: list[dict]) -> dict:
    checks = []
    for entry in entries:
        check = {
            "status": "passed",
            "category": entry.get("category") or "circle",
            "actual_count": entry.get("quantity", len(entry.get("geometry_ids") or [])),
            "source_evidence": entry.get("source_evidence", ""),
        }
        if entry.get("geometry_ids"):
            check["geometry_ids"] = entry["geometry_ids"]
        if entry.get("source_requirement_id"):
            check["source_requirement_id"] = entry["source_requirement_id"]
        checks.append(check)
    return {
        "status": "partial",
        # The same unresolved inventory entries can appear both in the coverage
        # list and inside the inventory report; a proof must filter both alike.
        "unknown_requirements": [
            {"source": "object_inventory", "reason": "数量未对账", "entries": [entry]}
            for entry in entries
        ],
        "final_source_acceptance": {"checks": checks},
        "object_count_consistency_acceptance": {
            "status": "review_required",
            "review_required": True,
            "checks": [
                {
                    "kind": "object_count",
                    "status": "failed",
                    "category": "circle",
                    "expected": 2,
                    "actual": 2,
                    "source_requirement_id": entry.get("source_requirement_id"),
                }
                for entry in entries
            ],
            "unknown_requirements": [
                {
                    "source": "object_inventory",
                    "reason": "数量未对账",
                    "entries": [entry],
                }
                for entry in entries
            ],
            "baseline": {"state": "partial", "entries": list(entries)},
            "actual_object_count": None,
        },
        "object_identity_acceptance": {
            "status": "review_required",
            "review_required": True,
            "identity_state": "partial",
            "checks": [
                {
                    "kind": "object_identity",
                    "status": "unbound",
                    "category": "circle",
                    "source_requirement_id": entry.get("source_requirement_id"),
                }
                for entry in entries
            ],
            "unmatched_entries": list(entries),
            "unmatched_objects": [
                {"object_id": object_id}
                for entry in entries for object_id in entry.get("object_ids") or []
            ],
            "ambiguous_bindings": [],
            "baseline": {"inventory_state": "partial", "entries": list(entries)},
        },
    }


def test_r01_one_proof_cannot_clear_another_source_set():
    entry_a = _entry("clause:0:0", "circle_a", 1)
    entry_b = _entry("clause:0:20", "circle_b", 11)
    source_acceptance = _inventory_source_acceptance([entry_a, entry_b])
    proof_a = _proof("clause:0:0", entry_a["object_ids"], entry_a["geometry_ids"])

    _resolve_inventory_acceptance(source_acceptance, [proof_a])

    count = source_acceptance["object_count_consistency_acceptance"]
    identity = source_acceptance["object_identity_acceptance"]
    # A is resolved; B keeps its original failure, entry, and unmatched object.
    assert [check["status"] for check in count["checks"]] == ["passed", "failed"]
    assert [check["status"] for check in identity["checks"]] == ["passed", "unbound"]
    assert [entry["source_requirement_id"] for entry in count["baseline"]["entries"]] == [
        "clause:0:20"
    ]
    assert [entry["source_requirement_id"] for entry in count["unknown_requirements"][0]["entries"]] == [
        "clause:0:20"
    ]
    assert [entry["source_requirement_id"] for entry in identity["unmatched_entries"]] == [
        "clause:0:20"
    ]
    assert {item["object_id"] for item in identity["unmatched_objects"]} == {
        "circle_b", "circle_b_2"
    }
    assert count["status"] == "review_required"
    assert identity["status"] == "review_required"


def test_r01_legacy_same_category_same_count_requires_same_measured_set():
    entry_a = {
        "source": "object_inventory",
        "category": "circle",
        "quantity": 2,
        "geometry_ids": [1, 2],
        "source_evidence": "左侧两个圆",
    }
    entry_b = {
        "source": "object_inventory",
        "category": "circle",
        "quantity": 2,
        "geometry_ids": [11, 12],
        "source_evidence": "右侧两个圆",
    }
    source_acceptance = _inventory_source_acceptance([entry_a, entry_b])
    proof_a = _proof("clause:0:0", ["circle_a", "circle_a_2"], [1, 2])

    _resolve_inventory_acceptance(source_acceptance, [proof_a])

    count = source_acceptance["object_count_consistency_acceptance"]
    # Category and quantity match B as well, but the measured set does not.
    assert count["status"] == "review_required"
    assert [entry["source_evidence"] for entry in count["baseline"]["entries"]] == [
        "右侧两个圆"
    ]
    statuses = [check["status"] for check in count["checks"]]
    # Both original failures stay; A is added as one exact-set passed proof.
    assert statuses.count("passed") == 1
    assert statuses.count("failed") == 2
    assert count["checks"][-1]["geometry_ids"] == [1, 2]


def test_r01_entry_free_warning_stays_ambiguous_for_two_same_count_sets():
    source_acceptance = _inventory_source_acceptance([])
    source_acceptance["final_source_acceptance"]["checks"] = [
        {
            "status": "passed",
            "category": "circle",
            "actual_count": 2,
            "geometry_ids": [1, 2],
            "source_evidence": "左侧两个圆",
            "source_requirement_id": "clause:0:0",
        },
        {
            "status": "passed",
            "category": "circle",
            "actual_count": 2,
            "geometry_ids": [11, 12],
            "source_evidence": "右侧两个圆",
            "source_requirement_id": "clause:0:20",
        },
    ]
    count = source_acceptance["object_count_consistency_acceptance"]
    count["checks"] = []
    count["unknown_requirements"] = [
        {"source": "object_inventory", "reason": "数量短语未解析", "entries": []}
    ]
    count["baseline"] = {"state": "partial", "entries": []}
    proofs = [
        _proof("clause:0:0", ["circle_a", "circle_a_2"], [1, 2]),
        _proof("clause:0:20", ["circle_b", "circle_b_2"], [11, 12]),
    ]

    _resolve_inventory_acceptance(source_acceptance, proofs)

    assert count["status"] == "review_required"
    assert count["unknown_requirements"], "two same-count sets must stay ambiguous"


def test_r01_rebind_filters_only_the_matching_source_entry(monkeypatch):
    entry_a = _entry("clause:0:0", "circle_a", 1)
    entry_b = _entry("clause:0:20", "circle_b", 11)
    source_acceptance = _inventory_source_acceptance([entry_a, entry_b])
    source_acceptance["coverage_evidence"] = {"state": "partial", "clauses": []}
    interpretation = {
        "source_acceptance": source_acceptance,
        "plan": {"units": "m", "steps": []},
        "acceptance_summary": {"status": "review_required", "review_required": True},
    }
    candidate = {"trial_result": {"plan": {"steps": []}, "geometries": [], "logical_objects": []}}
    proof_a = _proof("clause:0:0", entry_a["object_ids"], entry_a["geometry_ids"])

    def fake_bind(*_args, **_kwargs):
        return {
            "state": "complete",
            "clauses": [],
            "binding": {"object_count_proofs": [proof_a], "bound_fact_ids": []},
            "verified_requirement_count": 1,
            "partial_requirement_count": 0,
            "unverified_requirement_count": 0,
            "blocking_requirements": [],
        }

    monkeypatch.setattr(
        "app.cad_construction_commit.bind_construction_coverage", fake_bind
    )
    monkeypatch.setattr(
        "app.cad_construction_commit._refresh_residual_vector",
        lambda *_args, **_kwargs: None,
    )

    _rebind_source_acceptance(
        "画两个独立的圆",
        interpretation,
        candidate,
        {"id": "p1", "status": "ready_for_design"},
        project_created_in_commit=False,
        prior_variant_count=0,
    )

    remaining = interpretation["source_acceptance"]["unknown_requirements"]
    assert [item["entries"][0]["source_requirement_id"] for item in remaining] == [
        "clause:0:20"
    ]
    assert interpretation["source_acceptance"]["status"] == "partial"


def _r02_plan(width: float) -> dict:
    return {
        "schema_version": "cad.construction-interpretation.v1",
        "is_construction_request": True,
        "confidence": 0.99,
        "evidence_text": [R02_SOURCE],
        "assumptions": [],
        "plan": {
            "units": "m",
            "steps": [
                {
                    "op": "add_rectangle",
                    "step_id": "base",
                    "output_ref": "base",
                    "origin": {"x": -width / 2, "y": -1},
                    "width": width,
                    "height": 2,
                    "semantic": {
                        "object_id": "base",
                        "object_type": "rectangle",
                        "label": "矩形",
                    },
                },
                {
                    "op": "add_circle",
                    "step_id": "center_circle",
                    "output_ref": "center_circle",
                    "center": {"x": 0, "y": 0},
                    "radius": 0.5,
                    "semantic": {
                        "object_id": "center_circle",
                        "object_type": "circle",
                        "label": "圆",
                    },
                },
            ],
        },
    }


def test_r02_atomic_arc_error_is_visible_before_commit():
    """The trial pass must see atomic facts; otherwise P3 never runs."""
    from app.cad_construction_interpreter import interpret_construction_request

    source = "画一段圆弧，圆心(0,0)，半径2米，从30度画到150度，只画这段弧"

    def callback(_text, _schema):
        return {
            "schema_version": "cad.construction-interpretation.v1",
            "is_construction_request": True,
            "confidence": 0.99,
            "evidence_text": [source],
            "assumptions": [],
            "plan": {
                "units": "m",
                "steps": [{
                    "op": "add_arc", "step_id": "arc", "output_ref": "arc",
                    "center": {"x": 0, "y": 0}, "radius": 1.8,
                    "start_angle": 30, "end_angle": 150,
                    "semantic": {"object_id": "arc", "object_type": "arc", "label": "圆弧"},
                }],
            },
        }

    result = interpret_construction_request(
        source, callback, force_structured_model=True
    )
    vector = result["residual_vector"]
    assert result["status"] == "ready"
    assert vector["failing_discrete_count"] >= 1
    arc_radius = next(
        record for record in vector["records"]
        if record["predicate"] == "arc_radius"
    )
    assert arc_radius["expected"] == 2000.0
    assert arc_radius["measured"] == 1800.0
    assert vector["repair_targets"]["parameter_repair"] == ["arc"]


def test_r02_production_geometric_repair_loop_persists_and_reloads():
    service = RobotAgentService(restore_pending_actions=False)
    service.mode = "deepseek"
    store = CreativeProjectStore(Path(tempfile.mkdtemp()) / "projects.json")
    project = store.create(
        "r02", R02_SOURCE,
        requirements={"shape": "generic_2d_cad"},
        missing_parameters=[],
    )
    route = {
        "name": "drawing_design",
        "operation": "create",
        "stage": "candidate_generation",
        "selected_project_id": project["id"],
    }
    calls: list[str] = []
    state = {
        "provider_attempted": False,
        "request_attempts": 0,
        "transport_failed": False,
    }

    def callback(text: str, _schema: dict):
        calls.append(text)
        state["provider_attempted"] = True
        state["request_attempts"] = len(calls)
        return _r02_plan(3.8 if len(calls) == 1 else 4.0)

    with patch("app.agent_service.get_creative_project_store", return_value=store), \
         patch.object(
             RobotAgentService,
             "configured",
             new_callable=PropertyMock,
             return_value=True,
         ), \
         patch.object(
             service,
             "_cad_construction_model_callback",
             return_value=(callback, state),
         ):
        raw = service._formal_cad_construction(R02_SOURCE, route, mode="advanced")

    assert len(calls) == 2, "one initial plan and exactly one repair plan"
    assert raw["ok"] is True
    commit = raw["construction_commit"]
    assert commit["persisted_candidate_count"] == 1
    assert commit["recovery"]["repair_count"] == 1
    assert commit["repair_execution_ledger"]["automatic_repairs"] == 1
    assert commit["repair_execution_ledger"]["actual_planning_requests"] == 1
    first_attempt = commit["recovery"]["attempts"][0]
    assert first_attempt["residual_vector"]["failing_numeric_count"] >= 1
    width_residual = next(
        record for record in first_attempt["residual_vector"]["records"]
        if record["predicate"] == "width"
    )
    assert width_residual["expected"] == 4000.0
    assert width_residual["measured"] == 3800.0

    reloaded = store.get(project["id"])
    assert len(reloaded["variants"]) == 1
    variant = reloaded["variants"][0]
    assert variant["acceptance_summary"]["status"] == "passed"
    assert variant["acceptance_summary"]["requirement_coverage"] == "complete"
    assert variant["construction_record"]["residual_vector"]["failing_numeric_count"] == 0
    rectangle = next(
        item for item in variant["geometries"] if item["type"] == "polyline"
    )
    xs = [point["x"] for point in rectangle["vertices"]]
    assert max(xs) - min(xs) == pytest.approx(4000.0, abs=0.5)
