from copy import deepcopy
import json

from app.cad_candidate_state import candidate_is_accepted
from tests.manual import run_cad_product_acceptance as product_acceptance
from tests.manual.cad_acceptance_metrics import summarize
from tests.manual.cad_harness_acceptance import (
    evaluate_edit_formal_delivery,
    evaluate_formal_delivery,
    evaluate_no_change_delivery,
)


def _summary(status="passed", review_required=False):
    return {
        "status": status,
        "review_required": review_required,
        "coverage_evidence": {
            "state": "complete",
            "verified_requirement_count": 2,
            "partial_requirement_count": 0,
            "unverified_requirement_count": 0,
            "blocking_requirements": [],
        },
        "requirement_coverage": "complete",
        "unknown_requirements": [],
        "unverified_geometry_ids": [],
        "semantic_requirement_state": "passed",
    }


def _variant(variant_id="v1", summary=None, record_summary=True, parent=None):
    summary = deepcopy(summary or _summary())
    record = {
        "acceptance_summary": deepcopy(summary) if record_summary else None,
        "feasibility": {"ok": True},
        "constraint_solve": {"verified": True},
    }
    variant = {
        "id": variant_id,
        "project_id": "p1",
        "parent_variant_id": parent,
        "geometries": [
            {"id": "g1", "type": "line", "start": {"x": 0, "y": 0}, "end": {"x": 1000, "y": 0}}
        ],
        "acceptance_summary": summary,
        "construction_record": record,
    }
    return variant


def _project(variant):
    return {"id": "p1", "variants": [deepcopy(variant)]}


def _response(variant, *, visibility="visible", binding="ok", ok=True, project_id="p1"):
    result = {
        "ok": ok,
        "project_id": project_id,
        "variant": deepcopy(variant),
        "preview_paths": [{"points": [[0, 0], [1000, 0]]}],
        "candidate_visibility": {"status": visibility, "run_id": "r1"},
    }
    if binding == "ok":
        result["candidate_binding"] = {
            "run_id": "r1",
            "project_id": project_id,
            "variant_id": variant["id"],
        }
    elif isinstance(binding, dict):
        result["candidate_binding"] = binding
    return result


def _persisted_source(variant, project=None):
    variant = deepcopy(variant)
    project = deepcopy(project) if project is not None else _project(variant)
    return {
        "authority": "projects.json",
        "independent": True,
        "project_id": "p1",
        "variant_id": variant["id"],
        "project": project,
        "variant": variant,
    }


def _evaluate(response, project, **kwargs):
    checks = kwargs.pop("geometry_checks", True)
    variant = response.get("variant") or {}
    return evaluate_formal_delivery(
        response,
        project=project,
        persisted_project=project,
        persisted_source=kwargs.pop(
            "persisted_source", _persisted_source(variant, project)
        ),
        expected_project_id="p1",
        expected_variant_id=response.get("variant", {}).get("id") or "v1",
        run_id="r1",
        geometry_checks=checks,
        **kwargs,
    )


def test_formal_positive_requires_visibility_binding_reload_and_coverage():
    variant = _variant()
    result = _evaluate(_response(variant), _project(variant))
    assert result["generation_ok"] is True
    assert result["geometry_ok"] is True
    assert result["formal_evaluable"] is True
    assert result["formal_delivery_ok"] is True
    assert result["diagnostic_status"] == "formal_accepted"
    assert result["formal_reason"] == []


def test_formal_positive_requires_independent_persisted_source():
    variant = _variant()
    project = _project(variant)
    result = evaluate_formal_delivery(
        _response(variant),
        project=project,
        persisted_project=project,
        reloaded_variant=variant,
        expected_project_id="p1",
        expected_variant_id="v1",
        run_id="r1",
        geometry_checks=True,
    )
    assert result["formal_delivery_ok"] is False
    assert result["persisted_source_ok"] is False
    assert "persisted_source_missing" in result["formal_reason"]


def test_persisted_source_identity_and_geometry_are_checked():
    variant = _variant()
    project = _project(variant)
    wrong_identity = _persisted_source(variant, project)
    wrong_identity["project_id"] = "p2"
    identity_result = evaluate_formal_delivery(
        _response(variant), project=project, persisted_project=project,
        persisted_source=wrong_identity, expected_project_id="p1",
        expected_variant_id="v1", run_id="r1", geometry_checks=True,
    )
    assert identity_result["formal_delivery_ok"] is False
    assert "persisted_source_project_mismatch" in identity_result["formal_reason"]

    wrong_geometry = _persisted_source(variant, project)
    wrong_geometry["project"]["variants"][0]["geometries"][0]["end"]["x"] = 2000
    geometry_result = evaluate_formal_delivery(
        _response(variant), project=project, persisted_project=project,
        persisted_source=wrong_geometry, expected_project_id="p1",
        expected_variant_id="v1", run_id="r1", geometry_checks=True,
    )
    assert geometry_result["formal_delivery_ok"] is False
    assert "persisted_source_geometry_mismatch" in geometry_result["formal_reason"]


def test_persisted_source_variant_alone_is_not_persistence_proof():
    variant = _variant()
    project = _project(variant)
    source = _persisted_source(variant, project)
    source.pop("project")
    result = evaluate_formal_delivery(
        _response(variant), project=project, persisted_project=project,
        persisted_source=source, expected_project_id="p1",
        expected_variant_id="v1", run_id="r1", geometry_checks=True,
    )
    assert result["formal_delivery_ok"] is False
    assert "persisted_source_project_missing" in result["formal_reason"]


def test_persisted_source_must_declare_independence_and_authority():
    variant = _variant()
    project = _project(variant)
    source = _persisted_source(variant, project)
    source["independent"] = False
    result = evaluate_formal_delivery(
        _response(variant), project=project, persisted_project=project,
        persisted_source=source, expected_project_id="p1",
        expected_variant_id="v1", run_id="r1", geometry_checks=True,
    )
    assert result["formal_delivery_ok"] is False
    assert "persisted_source_not_independent" in result["formal_reason"]


def test_ok_true_draft_review_is_not_formal_delivery():
    summary = _summary(status="review_required", review_required=True)
    variant = _variant(summary=summary)
    response = {
        "ok": True,
        "project_id": "p1",
        "variant": None,
        "variants": [],
        "preview_paths": [],
        "candidate_visibility": {"status": "draft_review", "run_id": "r1"},
        "draft_preview": {"variant_id": "v1", "selectable": False},
    }
    result = evaluate_formal_delivery(
        response, project=_project(variant), persisted_project=_project(variant),
        expected_project_id="p1", expected_variant_id="v1", geometry_checks=True,
    )
    assert result["generation_ok"] is True
    assert result["formal_evaluable"] is True
    assert result["formal_delivery_ok"] is False
    assert result["diagnostic_status"] == "draft_review"
    assert "candidate_visibility_draft_review" in result["formal_reason"]


def test_hidden_candidate_is_not_formal_delivery():
    variant = _variant()
    response = _response(variant, visibility="hidden", binding=None)
    result = _evaluate(response, _project(variant))
    assert result["formal_delivery_ok"] is False
    assert result["diagnostic_status"] == "hidden"
    assert "candidate_visibility_hidden" in result["formal_reason"]


def test_binding_mismatch_is_not_formal_delivery():
    variant = _variant()
    response = _response(
        variant,
        binding={"run_id": "r1", "project_id": "p2", "variant_id": "v1"},
    )
    result = _evaluate(response, _project(variant))
    assert result["formal_delivery_ok"] is False
    assert "candidate_binding_missing_or_mismatch" in result["formal_reason"]


def test_geometry_ok_but_requirement_unbound_is_not_formal_delivery():
    summary = _summary()
    summary["coverage_evidence"] = {
        "state": "partial",
        "verified_requirement_count": 0,
        "partial_requirement_count": 1,
        "unverified_requirement_count": 1,
        "blocking_requirements": [{"clause": "画一个宽5米高3米的矩形", "status": "unbound"}],
    }
    summary["requirement_coverage"] = "unknown"
    summary["unknown_requirements"] = [{"reason": "requirement_unbound"}]
    variant = _variant(summary=summary)
    result = _evaluate(_response(variant), _project(variant))
    assert result["geometry_ok"] is True
    assert result["production_accepted"] is True
    assert result["formal_delivery_ok"] is False
    assert result["coverage_ok"] is False
    assert "requirement_coverage_not_complete" in result["formal_reason"]


def test_missing_record_acceptance_does_not_override_production_acceptance():
    variant = _variant(record_summary=False)
    assert candidate_is_accepted(variant) is True
    result = _evaluate(_response(variant), _project(variant))
    assert result["production_accepted"] is True
    assert result["acceptance_summary_ok"] is True
    assert result["formal_delivery_ok"] is True
    assert "record_acceptance_summary_missing" in result["formal_warnings"]
    assert "record_acceptance_summary_missing" not in result["formal_reason"]


def test_persisted_candidate_unavailable_is_not_formal_delivery():
    variant = _variant()
    empty_project = {"id": "p1", "variants": []}
    result = _evaluate(_response(variant), empty_project)
    assert result["formal_delivery_ok"] is False
    assert "persisted_candidate_missing" in result["formal_reason"]


def test_geometry_check_failure_is_not_formal_delivery():
    variant = _variant()
    result = _evaluate(_response(variant), _project(variant), geometry_checks=False)
    assert result["geometry_ok"] is False
    assert result["formal_delivery_ok"] is False
    assert "geometry_checks_not_passed" in result["formal_reason"]


def test_legacy_record_without_visibility_is_unassessable_not_passed():
    variant = _variant()
    result = evaluate_formal_delivery(
        {"ok": True, "variant": deepcopy(variant)}, project=_project(variant), geometry_checks=True
    )
    assert result["formal_evaluable"] is False
    assert result["formal_delivery_ok"] is None
    assert result["diagnostic_status"] == "unassessable"
    assert "candidate_visibility_missing" in result["formal_reason"]


def test_edit_with_draft_base_is_blocked_even_if_edited_candidate_looks_accepted():
    draft_summary = _summary(status="review_required", review_required=True)
    base = _variant("v1", summary=draft_summary)
    revised = _variant("v2", parent="v1")
    project = {"id": "p1", "variants": [deepcopy(base), deepcopy(revised)]}
    result = evaluate_edit_formal_delivery(
        _response(revised), base_variant=base, project=project, persisted_project=project,
        persisted_source=_persisted_source(revised, project),
        expected_project_id="p1", expected_variant_id="v2", geometry_checks=True,
    )
    assert result["formal_delivery_ok"] is False
    assert result["diagnostic_status"] == "blocked_by_draft_base"
    assert "base_candidate_not_formally_accepted" in result["formal_reason"]


def test_edit_non_target_mutation_is_not_formal_delivery():
    base = _variant("v1")
    revised = _variant("v2", parent="v1")
    project = {"id": "p1", "variants": [deepcopy(base), deepcopy(revised)]}
    result = evaluate_edit_formal_delivery(
        _response(revised), base_variant=base, project=project, persisted_project=project,
        persisted_source=_persisted_source(revised, project),
        expected_project_id="p1", expected_variant_id="v2", geometry_checks=False,
    )
    assert result["formal_delivery_ok"] is False
    assert "geometry_checks_not_passed" in result["formal_reason"]


def test_no_change_requires_source_binding_and_backend_measurement():
    base = _variant("v1")
    project = _project(base)
    response = {
        "ok": True,
        "project_id": "p1",
        "cad_edit_outcome": "already_satisfied",
        "variant_saved": False,
        "source_variant_id": "v1",
        "relation_verification": {
            "verified": True,
            "authority": "backend_measured_geometry",
        },
    }
    result = evaluate_no_change_delivery(
        response, base_variant=base, persisted_project=project,
        persisted_source=_persisted_source(base, project), expected_project_id="p1"
    )
    assert result["formal_evaluable"] is True
    assert result["formal_delivery_ok"] is True
    assert result["diagnostic_status"] == "no_change_verified"


def test_no_change_without_relation_evidence_is_not_success():
    base = _variant("v1")
    response = {
        "ok": True,
        "project_id": "p1",
        "cad_edit_outcome": "already_satisfied",
        "variant_saved": False,
        "source_variant_id": "v1",
    }
    result = evaluate_no_change_delivery(
        response, base_variant=base, persisted_project=_project(base), expected_project_id="p1"
    )
    assert result["formal_delivery_ok"] is False
    assert result["diagnostic_status"] == "no_change_unverified"
    assert "relation_not_verified" in result["formal_reason"]


def test_metrics_excludes_unassessable_and_keeps_legacy_counts(tmp_path):
    reports = [
        {"case": "a", "passed": True, "legacy_passed": True, "generation_ok": True,
         "geometry_ok": True, "formal_evaluable": True, "formal_delivery_ok": True},
        {"case": "b", "passed": False, "legacy_passed": True, "generation_ok": True,
         "geometry_ok": True, "formal_evaluable": True, "formal_delivery_ok": False},
        {"case": "c", "passed": False, "legacy_passed": True, "generation_ok": True,
         "geometry_ok": True, "formal_evaluable": False, "formal_delivery_ok": None},
    ]
    metrics = summarize(tmp_path, reports)
    assert metrics["case_count"] == 3
    assert metrics["evaluable_count"] == 2
    assert metrics["unassessable_count"] == 1
    assert metrics["unassessable_cases"] == ["c"]
    assert metrics["formal_delivery_pass_count"] == 1
    assert metrics["formal_delivery_rate"] == 0.5
    assert metrics["legacy_pass_count"] == 3
    assert metrics["end_to_end_pass_rate"] == 0.5
    assert metrics["new_execution_e2e_rate"] == 1 / 3

    new_metrics = summarize(tmp_path, reports, cohort="new")
    assert new_metrics["cohort"] == "new"
    assert new_metrics["new_execution_case_count"] == 3
    assert new_metrics["new_execution_pass_count"] == 1
    assert new_metrics["new_execution_e2e_rate"] == 1 / 3
    assert new_metrics["end_to_end_pass_rate"] == 1 / 3
    assert new_metrics["formal_delivery_rate"] == 0.5


def _recording_variant(*, draft=False):
    summary = _summary(status="review_required", review_required=True) if draft else _summary()
    objects = [{"object_id": "o1", "assembly_id": "a1", "assembly_label": "矩形",
                "geometry_refs": ["g1"]}]
    ledger = {"sources": [
        {"text": "画一个矩形", "origin": "user"},
        {"text": "宽5米高3米，单位米", "origin": "user"},
    ]}
    return {
        "id": "v1",
        "project_id": "p1",
        "geometries": [{"id": "g1", "type": "line", "start": {"x": 0, "y": 0},
                        "end": {"x": 5000, "y": 0}}],
        "logical_objects": objects,
        "requirement_ledger": ledger,
        "acceptance_summary": summary,
        "construction_record": {
            "acceptance_summary": deepcopy(summary),
            "requirement_ledger": ledger,
            "feasibility": {"ok": True},
            "constraint_solve": {"verified": True},
        },
    }


def _write_recording(folder, *, draft=False):
    variant = _recording_variant(draft=draft)
    case = {"id": "rect", "messages": ["画一个矩形", "宽5米高3米，单位米", "确认并生成"],
            "expected_preview_count": 1, "expected_assemblies": 1}
    (folder / "ui-fixture.json").write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
    for step in (1, 2, 3):
        (folder / f"request-{step}.json").write_text(
            json.dumps({"message": case["messages"][step - 1]}), encoding="utf-8"
        )
    (folder / "step-1.json").write_text(json.dumps({
        "ok": True, "project_id": "p1", "clarification": {"question": "尺寸？"},
        "preview_paths": [], "variant": None,
    }, ensure_ascii=False), encoding="utf-8")
    (folder / "step-2.json").write_text(json.dumps({
        "ok": True, "project_id": "p1", "preview_paths": [], "variant": None,
    }, ensure_ascii=False), encoding="utf-8")
    final = {
        "ok": True,
        "project_id": "p1",
        "preview_paths": [{"geometry_id": "g1", "points": []}],
        "drawing_json": {"logical_objects": variant["logical_objects"]},
        "variant": variant,
        "candidate_visibility": {"status": "visible", "run_id": "r1"},
        "candidate_binding": {"run_id": "r1", "project_id": "p1", "variant_id": "v1"},
    }
    if draft:
        final.update({
            "variant": None, "variants": [], "preview_paths": [], "drawing_json": None,
            "candidate_visibility": {"status": "draft_review", "run_id": "r1"},
            "draft_preview": {"variant_id": "v1", "selectable": False},
        })
        final.pop("candidate_binding", None)
    (folder / "step-3.json").write_text(json.dumps(final, ensure_ascii=False), encoding="utf-8")
    (folder / "projects.json").write_text(json.dumps({
        "projects": [{"id": "p1", "variants": [variant]}],
    }, ensure_ascii=False), encoding="utf-8")
    return case


def test_verify_recording_positive_requires_formal_delivery(tmp_path, monkeypatch):
    folder = tmp_path / "rect"
    folder.mkdir()
    case = _write_recording(folder)
    monkeypatch.setattr(product_acceptance, "verify_scoped_primitives",
                        lambda *args, **kwargs: {"checks": [{"status": "passed"}]})
    report = product_acceptance.verify_recording(case, folder)
    assert report["legacy_passed"] is True
    assert report["formal_evaluable"] is True
    assert report["formal_delivery_ok"] is True
    assert report["passed"] is True
    assert report["diagnostic_status"] == "formal_accepted"


def test_verify_recording_ok_true_draft_is_not_a_pass(tmp_path, monkeypatch):
    folder = tmp_path / "rect"
    folder.mkdir()
    case = _write_recording(folder, draft=True)
    monkeypatch.setattr(product_acceptance, "verify_scoped_primitives",
                        lambda *args, **kwargs: {"checks": [{"status": "passed"}]})
    report = product_acceptance.verify_recording(case, folder)
    assert report["formal_evaluable"] is True
    assert report["formal_delivery_ok"] is False
    assert report["passed"] is False
    assert report["diagnostic_status"] == "draft_review"
    assert "candidate_visibility_draft_review" in report["formal_reason"]
