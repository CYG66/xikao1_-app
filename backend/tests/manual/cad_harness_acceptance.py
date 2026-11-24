"""Read-only formal-delivery judge shared by the CAD E2E harnesses.

The production predicate remains the authority for candidate acceptance.  This
adapter adds the evidence a *delivery* must carry: visible current-run binding,
a reloadable persisted candidate, independent geometry checks, and the task's
requirement-coverage gate.  It never mutates production state or widens
tolerances; a missing construction-record summary is a warning, not a reason to
override production acceptance.
"""
from __future__ import annotations

from typing import Any

from app.cad_candidate_state import (
    accepted_project_view,
    authoritative_acceptance_summary,
    candidate_is_accepted,
    candidate_is_reviewable_draft,
    geometry_evidence_hash,
)


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _variant(project: Any, variant_id: str) -> dict:
    project = _dict(project)
    for item in _list(project.get("variants")):
        if isinstance(item, dict) and str(item.get("id") or "") == variant_id:
            return item
    return {}


def _summary_state(summary: Any) -> dict:
    summary = _dict(summary)
    return {
        "present": bool(summary),
        "status": summary.get("status"),
        "review_required": summary.get("review_required"),
        "passed": summary.get("status") == "passed"
        and summary.get("review_required") is not True,
    }


def _acceptance_evidence(variant: dict) -> dict:
    """Read production acceptance authority and keep missing record as a warning.

    ``candidate_is_accepted`` is the production authority: it requires the
    variant summary and every *present* construction-record summary to be
    passed.  A legacy variant without a record summary is therefore still
    accepted by production, and the harness must not tighten that contract on
    its own.  The missing record is surfaced as a diagnostic warning instead.
    """
    variant_summary = _summary_state(variant.get("acceptance_summary"))
    record = _dict(variant.get("construction_record"))
    record_summary = _summary_state(record.get("acceptance_summary"))
    authoritative = _summary_state(authoritative_acceptance_summary(variant))
    reasons: list[str] = []
    warnings: list[str] = []
    if not variant_summary["present"]:
        reasons.append("variant_acceptance_summary_missing")
    elif not variant_summary["passed"]:
        reasons.append("variant_acceptance_summary_not_passed")
    if not authoritative["present"]:
        reasons.append("authoritative_acceptance_summary_missing")
    elif not authoritative["passed"]:
        reasons.append("authoritative_acceptance_summary_not_passed")
    if not record_summary["present"]:
        warnings.append("record_acceptance_summary_missing")
    elif not record_summary["passed"]:
        warnings.append("record_acceptance_summary_not_passed")
    if (
        variant_summary["present"]
        and record_summary["present"]
        and variant_summary["passed"]
        and record_summary["passed"]
        and variant_summary["status"] != record_summary["status"]
    ):
        warnings.append("acceptance_summary_status_mismatch")
    return {
        "ok": not reasons,
        "reason": reasons,
        "warnings": warnings,
        "variant_summary": variant_summary,
        "record_summary": record_summary,
        "authoritative": authoritative,
    }


def _coverage_evidence(variant: dict) -> dict:
    """Require complete, verified requirement coverage for formal delivery."""
    summary = _dict(variant.get("acceptance_summary"))
    coverage = _dict(summary.get("coverage_evidence"))
    state = coverage.get("state") or summary.get("requirement_coverage")
    reasons: list[str] = []
    if not coverage:
        reasons.append("coverage_evidence_missing")
    if state != "complete":
        reasons.append("requirement_coverage_not_complete")
    if _list(summary.get("unknown_requirements")):
        reasons.append("unknown_requirements_present")
    if _list(summary.get("unverified_geometry_ids")):
        reasons.append("unverified_geometry_ids_present")
    if coverage:
        if _list(coverage.get("blocking_requirements")):
            reasons.append("blocking_requirements_present")
        if coverage.get("unverified_requirement_count") not in (0, None):
            reasons.append("unverified_requirements_present")
        if coverage.get("partial_requirement_count") not in (0, None):
            reasons.append("partial_requirements_present")
        verified = coverage.get("verified_requirement_count")
        if not isinstance(verified, int) or verified <= 0:
            reasons.append("verified_requirement_count_not_positive")
    semantic = summary.get("semantic_requirement_state")
    if semantic in {"partial", "unverified", "unbound", "unknown", "not_checked", "blocked"}:
        reasons.append("semantic_requirement_not_verified")
    return {
        "ok": not reasons,
        "reason": reasons,
        "state": state,
        "coverage_evidence": coverage,
        "semantic_requirement_state": semantic,
    }


def _geometry_hash(variant: dict) -> str | None:
    if not isinstance(variant, dict) or not variant.get("geometries"):
        return None
    try:
        return geometry_evidence_hash(variant.get("geometries") or [])
    except (TypeError, ValueError):
        return None


def _checks_ok(geometry_checks: Any) -> bool | None:
    if geometry_checks is None:
        return None
    if isinstance(geometry_checks, bool):
        return geometry_checks
    if isinstance(geometry_checks, dict):
        return all(bool(value) for value in geometry_checks.values()) if geometry_checks else False
    if isinstance(geometry_checks, (list, tuple)):
        return all(
            bool(item.get("passed")) if isinstance(item, dict) else bool(item)
            for item in geometry_checks
        ) if geometry_checks else False
    return bool(geometry_checks)


def _persisted_source_evidence(
    persisted_source: Any,
    *,
    project_id: str,
    variant_id: str,
    variant_hash: str | None,
) -> dict:
    """Require a separately declared, reloaded storage source.

    ``persisted_project``/``reloaded_variant`` may still be response-adjacent
    objects.  Formal delivery additionally needs an explicit source that states
    it is independent, carries the same project/variant identity, and exposes
    the persisted geometry read from that source.
    """
    source = _dict(persisted_source)
    source_project = _dict(source.get("project"))
    # The candidate geometry must come from the separately reloaded project
    # record, never from a response-shaped variant copied beside it.
    source_variant = _variant(source_project, variant_id)
    authority = str(source.get("authority") or "").strip()
    independent = source.get("independent") is True
    declared_project_id = str(source.get("project_id") or "").strip()
    record_project_id = str(source_project.get("id") or "").strip()
    source_project_id = record_project_id or declared_project_id
    declared_variant_id = str(source.get("variant_id") or "").strip()
    record_variant_id = str(source_variant.get("id") or "").strip()
    source_variant_id = record_variant_id or declared_variant_id
    source_hash = _geometry_hash(source_variant)
    reasons: list[str] = []
    if not source:
        reasons.append("persisted_source_missing")
    else:
        if not independent:
            reasons.append("persisted_source_not_independent")
        if not authority:
            reasons.append("persisted_source_authority_missing")
        if not source_project:
            reasons.append("persisted_source_project_missing")
        if declared_project_id and record_project_id and declared_project_id != record_project_id:
            reasons.append("persisted_source_project_mismatch")
        if not project_id or source_project_id != project_id:
            reasons.append("persisted_source_project_mismatch")
        if declared_variant_id and record_variant_id and declared_variant_id != record_variant_id:
            reasons.append("persisted_source_variant_mismatch")
        if not variant_id or source_variant_id != variant_id:
            reasons.append("persisted_source_variant_mismatch")
        if not source_variant:
            reasons.append("persisted_source_variant_missing")
        elif not (source_hash and variant_hash and source_hash == variant_hash):
            reasons.append("persisted_source_geometry_mismatch")
    return {
        "ok": not reasons,
        "reason": reasons,
        "present": bool(source),
        "independent": independent,
        "authority": authority or None,
        "project_id": source_project_id or None,
        "variant_id": source_variant_id or None,
        "geometry_hash": source_hash,
        "variant": source_variant,
    }


def evaluate_formal_delivery(
    response: Any,
    *,
    project: Any = None,
    persisted_project: Any = None,
    reloaded_variant: Any = None,
    persisted_source: Any = None,
    expected_project_id: str | None = None,
    expected_variant_id: str | None = None,
    run_id: str | None = None,
    geometry_checks: Any = None,
) -> dict:
    """Judge one candidate response against the formal delivery contract.

    Returns ``formal_delivery_ok`` as ``True``, ``False`` or ``None``.  ``None``
    means the recording lacks the minimum evidence to decide; it must never be
    counted as success.
    """
    response = _dict(response)
    variant = _dict(response.get("variant"))
    project = _dict(project or response.get("project"))
    persisted_project = _dict(persisted_project or project)
    draft_preview = _dict(response.get("draft_preview"))
    visibility = _dict(response.get("candidate_visibility"))
    binding = _dict(response.get("candidate_binding"))
    visibility_status = str(visibility.get("status") or "")
    draft_variant_id = str(draft_preview.get("variant_id") or "").strip()
    if not variant and draft_variant_id:
        # The production draft branch deliberately clears ``variant`` and
        # returns only a non-selectable draft preview. Recover the persisted
        # draft for diagnosis; it still cannot pass the formal gate.
        variant = _variant(persisted_project, draft_variant_id)

    project_id = str(
        response.get("project_id")
        or project.get("id")
        or variant.get("project_id")
        or ""
    ).strip()
    variant_id = str(variant.get("id") or draft_variant_id or "").strip()
    binding_run_id = str(binding.get("run_id") or visibility.get("run_id") or run_id or "").strip()
    binding_project_id = str(binding.get("project_id") or "").strip()
    binding_variant_id = str(binding.get("variant_id") or "").strip()

    persisted_variant = _variant(persisted_project, variant_id)
    source_evidence = _persisted_source_evidence(
        persisted_source,
        project_id=project_id,
        variant_id=variant_id,
        variant_hash=_geometry_hash(variant),
    )
    reloaded = _dict(reloaded_variant) if isinstance(reloaded_variant, dict) else {}
    if not reloaded and source_evidence["variant"]:
        reloaded = source_evidence["variant"]
    if not reloaded and persisted_variant:
        reloaded = persisted_variant

    production_accepted = bool(candidate_is_accepted(variant)) if variant else False
    summary = _acceptance_evidence(variant) if variant else {
        "ok": False,
        "reason": ["candidate_missing"],
        "warnings": [],
        "variant_summary": _summary_state(None),
        "record_summary": _summary_state(None),
        "authoritative": _summary_state(None),
    }
    coverage = _coverage_evidence(variant) if variant else {
        "ok": False,
        "reason": ["coverage_evidence_missing"],
        "state": None,
        "coverage_evidence": {},
        "semantic_requirement_state": None,
    }
    draft = bool(candidate_is_reviewable_draft(variant)) if variant else False
    geometry_ok = _checks_ok(geometry_checks)
    variant_hash = _geometry_hash(variant)
    reload_hash = _geometry_hash(reloaded)
    persisted_ok = bool(persisted_variant)
    reloaded_ok = bool(reloaded)
    geometry_hash_match = bool(variant_hash and reload_hash and variant_hash == reload_hash)

    binding_ok = bool(
        visibility_status == "visible"
        and binding
        and binding_run_id
        and binding_project_id == project_id
        and binding_variant_id == variant_id
        and (not expected_project_id or project_id == str(expected_project_id))
        and (not expected_variant_id or variant_id == str(expected_variant_id))
        and (not run_id or binding_run_id == str(run_id))
    )

    candidate_claimed = bool(
        variant_id
        or response.get("variants")
        or response.get("preview_paths")
        or response.get("draft_preview")
    )
    generation_ok = bool(response.get("ok") is True and candidate_claimed)

    reasons: list[str] = []
    evaluable = True
    if not response:
        evaluable = False
        reasons.append("response_missing")
    elif variant_id and visibility_status == "draft_review":
        reasons.extend(["candidate_visibility_draft_review", *summary["reason"], *coverage["reason"]])
    elif variant_id and visibility_status == "hidden":
        reasons.extend(["candidate_visibility_hidden", *summary["reason"], *coverage["reason"]])
        reasons.extend(str(item) for item in _list(visibility.get("reason")))
    elif variant_id and visibility_status != "visible":
        evaluable = False
        reasons.append("candidate_visibility_missing")
    elif not variant_id:
        reasons.append("candidate_missing")
        if response.get("ok") is not True:
            reasons.append("generation_not_ok")
    elif not binding_ok:
        reasons.append("candidate_binding_missing_or_mismatch")
    if variant_id and visibility_status == "visible":
        if not production_accepted:
            reasons.append("production_candidate_not_accepted")
        reasons.extend(summary["reason"])
        reasons.extend(coverage["reason"])
        if draft:
            reasons.append("candidate_is_reviewable_draft")
        if geometry_ok is not True:
            reasons.extend(["geometry_evidence_missing", "geometry_checks_not_passed"])
        if not persisted_ok:
            reasons.append("persisted_candidate_missing")
        if not source_evidence["ok"]:
            reasons.extend(source_evidence["reason"])
        if not reloaded_ok:
            reasons.append("reloaded_candidate_missing")
        if not geometry_hash_match:
            reasons.append("geometry_hash_not_reloadable")

    if not evaluable:
        formal_ok = None
        diagnostic = "unassessable"
    elif visibility_status == "draft_review":
        formal_ok = False
        diagnostic = "draft_review"
    elif visibility_status == "hidden":
        formal_ok = False
        diagnostic = "hidden"
    elif not variant_id:
        formal_ok = False
        diagnostic = "generation_failed" if response.get("ok") is not True else "no_candidate"
    elif visibility_status != "visible":
        formal_ok = None
        diagnostic = "unassessable"
    else:
        formal_ok = all(
            [
                response.get("ok") is True,
                production_accepted,
                summary["ok"],
                coverage["ok"],
                binding_ok,
                geometry_ok is True,
                persisted_ok,
                source_evidence["ok"],
                reloaded_ok,
                geometry_hash_match,
                not draft,
            ]
        )
        diagnostic = "formal_accepted" if formal_ok else "acceptance_incomplete"

    if not variant_id and not response:
        diagnostic = "unassessable"

    return {
        "schema": "cad.formal-delivery.v2",
        "generation_ok": generation_ok,
        "geometry_ok": geometry_ok,
        "formal_evaluable": evaluable,
        "formal_delivery_ok": formal_ok,
        "diagnostic_status": diagnostic,
        "formal_reason": reasons,
        "production_accepted": production_accepted,
        "candidate_is_reviewable_draft": draft,
        "acceptance_summary_ok": summary["ok"],
        "strict_summary_ok": summary["ok"],
        "formal_warnings": summary["warnings"],
        "coverage_ok": coverage["ok"],
        "visibility_status": visibility_status or None,
        "binding_ok": binding_ok,
        "persisted_ok": persisted_ok,
        "persisted_source_ok": source_evidence["ok"],
        "persisted_source_independent": source_evidence["independent"],
        "persisted_source_authority": source_evidence["authority"],
        "reloaded_ok": reloaded_ok,
        "geometry_hash_match": geometry_hash_match,
        "project_id": project_id or None,
        "variant_id": variant_id or None,
        "run_id": binding_run_id or None,
        "evidence": {
            "variant_acceptance_summary": summary["variant_summary"],
            "record_acceptance_summary": summary["record_summary"],
            "authoritative_acceptance_summary": summary["authoritative"],
            "requirement_coverage": coverage,
            "candidate_binding": binding,
            "candidate_visibility": visibility,
            "variant_geometry_hash": variant_hash,
            "reloaded_geometry_hash": reload_hash,
            "persisted_source": {
                key: value for key, value in source_evidence.items()
                if key not in {"variant"}
            },
        },
    }


def evaluate_accepted_base(variant: Any) -> dict:
    """Check that an edit base is a formally accepted candidate."""
    variant = _dict(variant)
    summary = _acceptance_evidence(variant) if variant else {
        "ok": False,
        "reason": ["base_candidate_missing"],
        "warnings": [],
        "variant_summary": _summary_state(None),
        "record_summary": _summary_state(None),
        "authoritative": _summary_state(None),
    }
    accepted = bool(
        variant
        and candidate_is_accepted(variant)
        and summary["ok"]
        and not candidate_is_reviewable_draft(variant)
    )
    return {
        "accepted": accepted,
        "reason": list(summary["reason"]) if not accepted else [],
        "warnings": list(summary["warnings"]),
        "variant_id": str(variant.get("id") or "") or None,
        "variant_acceptance_summary": summary["variant_summary"],
        "record_acceptance_summary": summary["record_summary"],
    }


def evaluate_edit_formal_delivery(
    response: Any,
    *,
    base_variant: Any,
    project: Any = None,
    persisted_project: Any = None,
    reloaded_variant: Any = None,
    persisted_source: Any = None,
    expected_project_id: str | None = None,
    expected_variant_id: str | None = None,
    run_id: str | None = None,
    geometry_checks: Any = None,
) -> dict:
    """Formal candidate delivery plus the accepted-base precondition."""
    base = evaluate_accepted_base(base_variant)
    result = evaluate_formal_delivery(
        response,
        project=project,
        persisted_project=persisted_project,
        reloaded_variant=reloaded_variant,
        persisted_source=persisted_source,
        expected_project_id=expected_project_id,
        expected_variant_id=expected_variant_id,
        run_id=run_id,
        geometry_checks=geometry_checks,
    )
    result["delivery_kind"] = "edit_candidate"
    result["base_candidate_accepted"] = base["accepted"]
    result["base_candidate_evidence"] = base
    if not base["accepted"]:
        result["formal_delivery_ok"] = False
        result["diagnostic_status"] = "blocked_by_draft_base"
        result["formal_reason"] = [
            *result.get("formal_reason", []),
            "base_candidate_not_formally_accepted",
            *base["reason"],
        ]
    return result


def evaluate_no_change_delivery(
    response: Any,
    *,
    base_variant: Any,
    persisted_project: Any = None,
    persisted_source: Any = None,
    expected_project_id: str | None = None,
) -> dict:
    """A legal ``already_satisfied`` edit is a separate, evidenced outcome."""
    response = _dict(response)
    base = evaluate_accepted_base(base_variant)
    base_variant = _dict(base_variant)
    persisted_project = _dict(persisted_project)
    base_id = str(base_variant.get("id") or "").strip()
    persisted_base = _variant(persisted_project, base_id)
    relation = _dict(response.get("relation_verification"))
    project_id = str(
        response.get("project_id")
        or (response.get("project") or {}).get("id")
        or expected_project_id
        or ""
    ).strip()
    base_hash = _geometry_hash(base_variant)
    persisted_hash = _geometry_hash(persisted_base)
    base_unchanged = bool(
        base_id
        and persisted_base
        and base_hash
        and persisted_hash
        and base_hash == persisted_hash
    )
    source_evidence = _persisted_source_evidence(
        persisted_source,
        project_id=project_id,
        variant_id=base_id,
        variant_hash=base_hash,
    )
    source_base = _dict(source_evidence.get("variant"))
    source_hash = _geometry_hash(source_base)
    source_unchanged = bool(
        source_evidence["ok"]
        and source_hash
        and base_hash
        and source_hash == base_hash
    )
    reasons: list[str] = []
    if response.get("cad_edit_outcome") != "already_satisfied":
        reasons.append("edit_outcome_not_already_satisfied")
    if response.get("ok") is not True:
        reasons.append("generation_not_ok")
    if response.get("variant_saved") is not False:
        reasons.append("variant_saved_not_explicitly_false")
    if str(response.get("source_variant_id") or "").strip() != base_id:
        reasons.append("source_variant_not_bound")
    if relation.get("verified") is not True:
        reasons.append("relation_not_verified")
    if relation.get("authority") != "backend_measured_geometry":
        reasons.append("relation_authority_not_backend_measured")
    if expected_project_id and project_id != str(expected_project_id):
        reasons.append("project_not_bound")
    if not base["accepted"]:
        reasons.append("base_candidate_not_formally_accepted")
        reasons.extend(base["reason"])
    if not base_unchanged:
        reasons.append("base_candidate_not_reloadable_or_changed")
    if not source_evidence["ok"]:
        reasons.extend(source_evidence["reason"])
    if not source_unchanged:
        reasons.append("persisted_source_geometry_mismatch")

    evaluable = bool(base_variant and persisted_project and base_id)
    ok = bool(evaluable and not reasons)
    return {
        "schema": "cad.formal-delivery.v2",
        "delivery_kind": "no_change",
        "generation_ok": response.get("ok") is True,
        "geometry_ok": relation.get("verified") is True,
        "formal_evaluable": evaluable,
        "formal_delivery_ok": ok if evaluable else None,
        "candidate_present": False,
        "diagnostic_status": "no_change_verified" if ok else "no_change_unverified",
        "formal_reason": reasons,
        "production_accepted": False,
        "base_candidate_accepted": base["accepted"],
        "visibility_status": None,
        "binding_ok": bool(
            base_id
            and str(response.get("source_variant_id") or "").strip() == base_id
        ),
        "persisted_ok": bool(persisted_base and source_base),
        "persisted_source_ok": source_evidence["ok"],
        "persisted_source_independent": source_evidence["independent"],
        "persisted_source_authority": source_evidence["authority"],
        "reloaded_ok": bool(source_base),
        "geometry_hash_match": bool(base_unchanged and source_unchanged),
        "project_id": project_id or None,
        "variant_id": base_id or None,
        "run_id": None,
        "evidence": {
            "base_candidate": base,
            "relation_verification": relation,
            "base_geometry_hash": base_hash,
            "persisted_geometry_hash": persisted_hash,
            "persisted_source": {
                key: value for key, value in source_evidence.items()
                if key not in {"variant"}
            },
            "persisted_source_geometry_hash": source_hash,
        },
    }
