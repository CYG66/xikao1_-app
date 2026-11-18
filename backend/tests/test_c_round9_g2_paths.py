"""Round9 G2 three-path controlled dynamic trigger regression (Agent C).

Zero real model calls. Each path is driven through the real production chain
with a local Mock callback; the harness records binding evidence, attribution
preservation, summary propagation, non-acceptance, repair budget and mock call
count. No production code semantics are changed by these tests; the only triggers
are controlled plan/assertion inputs supplied through the Mock callback.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

HARNESS_PATH = (
    Path(__file__).resolve().parents[1]
    / "evaluations" / "v1" / "round9" / "c_round9_g2_path_harness.py"
)
_spec = importlib.util.spec_from_file_location("c_round9_g2_path_harness", HARNESS_PATH)
harness = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(harness)

PATHS = {
    "A": harness.run_path_a(),
    "B": harness.run_path_b(),
    "C": harness.run_path_c(),
}


@pytest.mark.parametrize("path_id", ["A", "B", "C"])
def test_six_evidence_items_hold_for_each_path(path_id):
    record = PATHS[path_id]
    checks = record["evidence_checks"]
    assert all(checks.values()), checks
    # Trusted backend binding with an empty issue list actually reached the
    # verifier; the model-declared object id is not trusted.
    binding = record["acceptance_output"]["binding_evidence"]
    assert binding["binding_trust"] == "trusted"
    assert binding["binding_source"] == "execute_construction_plan.logical_objects"
    assert binding["issues"] == []
    assert binding["model_declared_object_id_trusted"] is False
    # No accepted candidate and no authoritative accepted summary.
    assert record["candidate_state"]["candidate_is_accepted"] is False
    assert record["candidate_state"]["authoritative_acceptance_summary"] is None
    # Repair budget unchanged: at most one deterministic repair, budget 2.
    assert record["repair"]["max_repairs_budget"] == 2
    assert record["repair"]["within_budget"] is True
    # Zero real model requests: the local Mock callback is the only caller.
    assert record["actual_params"]["mock_model_calls"] == 1
    assert record["trigger_kind"] == "natural"


def test_path_a_diagnostic_replay_records_independent_failure():
    record = PATHS["A"]
    assert record["interpreter_status"] == "invalid"
    assert record["error_code"] == "assertion_failed"
    diagnostic = record["acceptance_output"]["diagnostic_record"]
    assert diagnostic["diagnostic_only"] is True
    assert diagnostic["candidate_accepted"] is False
    assert diagnostic["status"] == "not_checked"
    assert diagnostic["review_required"] is True
    assert diagnostic["reason"] == "no_semantic_requirement_matched"
    assert diagnostic["coverage"] == "partial"
    assert record["repair"]["deterministic_repair_count"] == 0
    summary = record["summary_output"]["summary"]
    assert summary["review_required"] is True


def test_path_b_astroid_repair_keeps_independent_proof_and_geometry():
    record = PATHS["B"]
    assert record["interpreter_status"] == "ready"
    repairs = record["repair"]["repair_kinds"]
    assert repairs == ["source_curve_identity_replaces_inapplicable_smoothness"]
    proof = record["acceptance_output"]["proof"]
    assert proof["status"] == "passed"
    assert proof["coverage"] == "astroid_identity_radius_and_four_cusps"
    assert record["acceptance_output"]["geometry_unchanged"] is True
    summary = record["summary_output"]["summary"]
    assert summary["semantic_requirement_state"] == "fully_verified"
    assert summary["review_required"] is True
    assert record["repair"]["deterministic_repair_count"] == 1


def test_path_c_polygon_boundary_repair_keeps_independent_proof_and_geometry():
    record = PATHS["C"]
    assert record["interpreter_status"] == "ready"
    repairs = record["repair"]["repair_kinds"]
    assert repairs == ["source_radial_acceptance_replaces_unrequested_bounds"]
    proof = record["acceptance_output"]["proof"]
    assert proof["status"] == "passed"
    assert proof["coverage"] == "explicit_regular_polygon_and_concentric_hole"
    assert record["acceptance_output"]["geometry_unchanged"] is True
    summary = record["summary_output"]["summary"]
    assert summary["semantic_requirement_state"] == "fully_verified"
    assert summary["review_required"] is True
    assert record["repair"]["deterministic_repair_count"] == 1
