"""Persist verified generic CAD construction results as design candidates."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from collections.abc import Callable

from .agent_skills import score_design_variant
from .cad_candidate_orchestrator import persist_candidate_variant
from .cad_candidate_state import geometry_evidence_hash
from .cad_project_candidates import normalize_model_geometry_units
from .creative_projects import CreativeProjectStore
from .drawing_store import preview_paths
from .cad_requirement_ledger import project_requirement_ledger, candidate_requirement_snapshot
from .cad_construction import execute_construction_plan
from .cad_requirement_binding import bind_construction_coverage


class ConstructionCommitError(ValueError):
    """Raised when an interpretation cannot be committed atomically."""


def commit_construction_interpretation(
    source_text: str,
    interpretation: dict[str, Any],
    *,
    store: CreativeProjectStore | None,
    owner_conversation_id: str | None = None,
    project_id: str | None = None,
    candidate_metadata: dict[str, Any] | None = None,
    add_variant: Callable | None = None,
    get_project: Callable | None = None,
) -> dict[str, Any]:
    """Persist verified production plans in their active project.

    Trial execution is deliberately completed before this function is called.
    Standalone/evaluation candidate sets create a project and roll it back on
    failure. Existing projects accept a single atomic candidate write and are
    never deleted on failure.
    """
    candidates, recommended_id = _verified_candidates(interpretation)
    if not candidates:
        raise ConstructionCommitError("没有通过确定性验证的构造候选可保存。")

    add_variant = add_variant or (store.add_variant if store is not None else None)
    get_project = get_project or (store.get if store is not None else None)
    if add_variant is None or get_project is None or (store is None and not project_id):
        raise ConstructionCommitError("缺少候选写入目标。")
    project = get_project(project_id) if project_id else None
    project_created_in_commit = project is None
    if project_id:
        if project is None:
            raise ConstructionCommitError("当前项目已不存在，未创建其他项目。")
        allowed = {"draft", "ready_for_design", "designing"}
        if candidate_metadata is not None:
            allowed.add("ready_for_planning")
        if project.get("missing_parameters") or project.get("status") not in allowed:
            raise ConstructionCommitError("当前项目尚未就绪或已进入规划执行阶段。")
        # Production has one plan and one atomic variant write. Evaluation
        # candidate sets create their own project so rollback stays isolated.
        if len(candidates) != 1:
            raise ConstructionCommitError("当前项目只接受一个已验证的生产构造计划。")
    if project is None:
        project = store.create(
            _project_name(source_text),
            source_text,
            requirements={
                "shape": "generic_2d_cad",
                "construction_mode": "deterministic_ir",
                "units": str(candidates[0]["trial_result"]["plan"].get("units") or "m"),
                "candidate_count": len(candidates),
                **deepcopy(interpretation.get("project_requirements") or {}),
            },
            constraints={
                "validated_before_persist": True,
                "geometry_authority": "deterministic_backend",
            },
            missing_parameters=[],
            owner_conversation_id=owner_conversation_id,
        )
    interpretation = deepcopy(interpretation)
    _refresh_candidate_trials(candidates)
    _rebind_source_acceptance(
        source_text,
        interpretation,
        candidates,
        project,
        project_created_in_commit=project_created_in_commit,
    )
    req = project.get("requirements") or {}
    source_ledger = req.get("requirement_ledger") or project_requirement_ledger(
        str(project.get("original_prompt") or source_text), req.get("source_followups") or [],
        missing=project.get("missing_parameters") or [])
    interpretation["requirement_ledger"] = candidate_requirement_snapshot(
        source_ledger, {**(interpretation.get("requirement_ledger") or {}),
                       "source_geometry_acceptance":interpretation.get("source_acceptance") or {}})
    persisted: list[dict[str, Any]] = []
    by_candidate_id: dict[str, dict[str, Any]] = {}
    try:
        for index, candidate in enumerate(candidates, start=1):
            trial = candidate["trial_result"]
            committed_plan = trial.get("_construction_plan") if isinstance(trial, dict) else None
            if isinstance(committed_plan, dict) and not trial.get("_p1_plan_refreshed"):
                refreshed = execute_construction_plan(committed_plan)
                trial = {**trial, **refreshed}
            geometries = list(trial.get("geometries") or [])
            if not geometries:
                raise ConstructionCommitError("构造候选没有可保存的图元。")
            # execute_construction_plan has already converted every output to
            # internal millimetres. plan.units describes the input plan only;
            # applying it again here would enlarge metre plans 1000 times.
            geometries, units_note = normalize_model_geometry_units(
                geometries,
                project,
                explicit_units="mm",
            )
            assessment = score_design_variant(geometries)
            assessment["construction_validation"] = {
                "assertions": deepcopy(trial.get("assertions") or {}),
                "constraint_solve": deepcopy(trial.get("constraint_solve") or {}),
                "curve_quality": deepcopy(trial.get("curve_quality") or {}),
                "graph_validation": deepcopy(trial.get("graph_validation") or {}),
                "units_normalized": units_note,
            }
            metadata = candidate_metadata or {}
            persisted_variant = persist_candidate_variant(
                project_id=str(project["id"]),
                name=str(metadata.get("title") or candidate.get("title") or f"结构候选 {index}"),
                geometries=geometries,
                rationale=str(metadata.get("description") or candidate.get("rationale") or "由结构化构造计划确定性生成。"),
                assessment=assessment,
                add_variant=add_variant,
                get_project=get_project,
                stored_preview=preview_paths({"lines": geometries}),
                logical_objects=list(metadata.get("logical_objects") or trial.get("logical_objects") or []),
                topology=dict(metadata.get("topology") or trial.get("topology") or {}),
                **({"instance_contract": metadata["instance_contract"]} if metadata.get("instance_contract") else {}),
                construction_record=_construction_record(
                    interpretation, candidate, trial
                ),
                **({"execution_context": deepcopy(metadata["execution_context"])}
                   if isinstance(metadata.get("execution_context"), dict) else {}),
            )
            if persisted_variant.get("ok") is not True:
                raise ConstructionCommitError(
                    str(persisted_variant.get("message") or f"结构候选 {index} 未通过项目写入校验。")
                )
            variant = persisted_variant["variant"]
            persisted.append(variant)
            by_candidate_id[str(candidate["candidate_id"])] = variant
    except Exception as exc:
        if not project_id:
            store.delete(str(project["id"]))
        if isinstance(exc, ConstructionCommitError):
            raise
        raise ConstructionCommitError(str(exc)) from exc

    updated = persisted_variant.get('project')
    if not isinstance(updated,dict):
        updated = get_project(str(project["id"]))
    if updated is None:
        raise ConstructionCommitError("候选已写入，但无法重新读取项目。")
    recommended = by_candidate_id.get(str(recommended_id or "")) or persisted[0]
    return {
        "schema": "cad.construction-commit.v1",
        "project": updated,
        "project_id": str(updated["id"]),
        "variants": list(updated.get("variants") or []),
        "recommended_variant": recommended,
        "recommended_candidate_id": recommended_id,
        "persisted_candidate_count": len(persisted),
    }


def _verified_candidates(
    interpretation: dict[str, Any],
) -> tuple[list[dict[str, Any]], str | None]:
    if interpretation.get("status") != "ready":
        return [], None
    if interpretation.get("schema") == "cad.construction-interpretation-result.v1":
        trial = interpretation.get("trial_result")
        if not isinstance(trial, dict):
            return [], None
        committed_plan = interpretation.get("plan") or trial.get("plan") or {}
        trial = {**trial, "_construction_plan": deepcopy(committed_plan)}
        return [{
            "candidate_id": "candidate-1",
            "title": _single_candidate_title(trial),
            "rationale": "按已验证的结构化构造计划生成。",
            "trial_result": trial,
            "graph": None,
        }], "candidate-1"

    evaluation = interpretation.get("evaluation")
    if not isinstance(evaluation, dict):
        return [], None
    candidates = [
        item for item in list(evaluation.get("candidates") or [])
        if isinstance(item, dict)
        and item.get("status") == "valid"
        and isinstance(item.get("trial_result"), dict)
    ]
    candidates.sort(key=lambda item: int(item.get("rank") or 999))
    return candidates, str(evaluation.get("recommended_candidate_id") or "") or None


def _construction_record(
    interpretation: dict[str, Any],
    candidate: dict[str, Any],
    trial: dict[str, Any],
) -> dict[str, Any]:
    acceptance = interpretation.get("acceptance_summary")
    if not isinstance(acceptance, dict):
        assertions = trial.get("assertions") if isinstance(trial, dict) else None
        feasibility = trial.get("feasibility") if isinstance(trial, dict) else None
        # Some deterministic/template interpretations predate the explicit
        # acceptance field.  Reuse only the measured trial evidence already
        # required for commit; do not infer pass from project status or shape.
        if (
            isinstance(assertions, dict)
            and assertions.get("ok") is True
            and isinstance(feasibility, dict)
            and feasibility.get("ok") is True
        ):
            acceptance = {
                "status": "passed",
                "review_required": False,
                "authority": "backend_measured_geometry",
                "source": "construction_trial",
                "verified_checks": 2,
            }
        else:
            acceptance = {
                "status": "review_required",
                "review_required": True,
                "authority": "backend_measured_geometry",
                "source": "missing_acceptance_evidence",
            }
    return {
        "schema": "cad.construction-record.v1",
        "template_specifications": deepcopy(interpretation.get("template_specifications") or []),
        "parser": str(interpretation.get("parser") or "unknown"),
        "recovery": deepcopy(interpretation.get("recovery")),
        "confidence": float(interpretation.get("confidence") or 0.0),
        "requirements_contract": deepcopy(interpretation.get("requirements_contract")),
        "requirement_ledger": deepcopy(interpretation.get("requirement_ledger")),
        "structure_contract": deepcopy(interpretation.get("structure_contract")),
        "structure_validation": deepcopy(interpretation.get("structure_validation")),
        "composition_contract": deepcopy(interpretation.get("composition_contract")),
        "composition_validation": deepcopy(interpretation.get("composition_validation")),
        "source_acceptance": deepcopy(interpretation.get("source_acceptance")),
        "acceptance_summary": deepcopy(acceptance),
        "local_repair_validation": deepcopy(interpretation.get("local_repair_validation")),
        "repair_changes": deepcopy(
            ((interpretation.get("acceptance_summary") or {}).get("repair_changes")
             if isinstance(interpretation.get("acceptance_summary"), dict) else None)
            or ({
                "changed_step_refs": list((interpretation.get("local_repair_validation") or {}).get("changed_step_refs") or []),
                "changed_fields_by_ref": deepcopy((interpretation.get("local_repair_validation") or {}).get("changed_fields_by_ref") or {}),
            } if isinstance(interpretation.get("local_repair_validation"), dict) else None)
        ),
        "evidence_text": deepcopy(interpretation.get("evidence_text") or []),
        "assumptions": deepcopy(interpretation.get("assumptions") or []),
        "normalization_facts": deepcopy(
            interpretation.get("normalization_facts") or []
        ),
        "deterministic_repairs": deepcopy(
            interpretation.get("deterministic_repairs") or []
        ),
        "candidate_id": str(candidate.get("candidate_id") or "candidate-1"),
        "plan": deepcopy(trial.get("plan") or interpretation.get("plan") or {}),
        "assertions": deepcopy(trial.get("assertions") or {}),
        "constraint_solve": deepcopy(trial.get("constraint_solve") or {}),
        "symbol_table": deepcopy(trial.get('symbol_table') or {}),
        "geometry_hash": geometry_evidence_hash(trial.get('geometries') or []),
        "curve_quality": deepcopy(trial.get("curve_quality") or {}),
        "feasibility": deepcopy(trial.get("feasibility") or {}),
        "graph_validation": deepcopy(trial.get("graph_validation") or {}),
        "sketch_graph": deepcopy(candidate.get("graph")),
    }


def _refresh_candidate_trials(candidates: list[dict[str, Any]]) -> None:
    """Execute the stored plan before binding, so evidence uses final geometry."""
    for candidate in candidates:
        trial = candidate.get("trial_result")
        if not isinstance(trial, dict):
            continue
        plan = trial.get("_construction_plan")
        if not isinstance(plan, dict):
            continue
        refreshed = execute_construction_plan(plan)
        candidate["trial_result"] = {**trial, **refreshed, "_p1_plan_refreshed": True}


def _rebind_source_acceptance(
    source_text: str,
    interpretation: dict[str, Any],
    candidates: list[dict[str, Any]],
    project: dict[str, Any],
    *,
    project_created_in_commit: bool,
) -> None:
    """Attach the project record and measured object binding before persistence.

    The project exists at this point and is the actual durable target of the
    create request.  Only ordinary, unique-object clauses can be promoted; all
    ambiguous or missing bindings keep their original blocking state.
    """
    source_acceptance = interpretation.get("source_acceptance")
    if not isinstance(source_acceptance, dict):
        return
    coverage = source_acceptance.get("coverage_evidence")
    if not isinstance(coverage, dict):
        return
    trial = (candidates[0] or {}).get("trial_result") if candidates else None
    trial = trial if isinstance(trial, dict) else {}
    plan = trial.get("plan") if isinstance(trial.get("plan"), dict) else interpretation.get("plan")
    plan = plan if isinstance(plan, dict) else {}
    bound = bind_construction_coverage(
        coverage,
        logical_objects=list(trial.get("logical_objects") or []),
        geometries=list(trial.get("geometries") or []),
        plan_steps=list(plan.get("steps") or []),
        symbol_table=trial.get("symbol_table") if isinstance(trial.get("symbol_table"), dict) else {},
        project_evidence={
            "project_id": str(project.get("id") or ""),
            "project_status": project.get("status"),
            "project_exists": bool(project.get("id")),
            "created_in_this_commit": project_created_in_commit,
            "authority": "creative_project_store",
        },
    )
    source_acceptance = deepcopy(source_acceptance)
    source_acceptance["coverage_evidence"] = bound
    if bound.get("state") == "complete":
        clause_ids = {
            str(item.get("requirement_id"))
            for item in bound.get("clauses") or []
            if isinstance(item, dict) and item.get("requirement_id")
        }
        remaining_unknown = []
        for item in source_acceptance.get("unknown_requirements") or []:
            if not isinstance(item, dict):
                remaining_unknown.append(item)
                continue
            ref = str(
                item.get("source_requirement_id")
                or item.get("requirement_id")
                or ""
            )
            if ref and ref in clause_ids:
                continue
            remaining_unknown.append(item)
        source_acceptance["unknown_requirements"] = remaining_unknown
        if remaining_unknown:
            # A non-clause unknown requirement is not cleared by object binding.
            source_acceptance["status"] = "partial"
            source_acceptance["coverage"] = "complete"
            source_acceptance["review_required"] = True
        else:
            source_acceptance["status"] = "passed"
            source_acceptance["coverage"] = "complete"
            source_acceptance["review_required"] = False
        interpretation["source_acceptance"] = source_acceptance
        from .cad_construction_interpreter import construction_acceptance_summary
        interpretation["acceptance_summary"] = construction_acceptance_summary(
            preflight_structure=interpretation.get("preflight_structure"),
            structure_contract=interpretation.get("structure_contract"),
            structure_validation=interpretation.get("structure_validation"),
            composition_contract=interpretation.get("composition_contract"),
            composition_validation=interpretation.get("composition_validation"),
            source_acceptance=source_acceptance,
            trial_result=trial,
            source=source_text,
        )
        return
    interpretation["source_acceptance"] = source_acceptance
    summary = interpretation.get("acceptance_summary")
    if isinstance(summary, dict):
        summary = deepcopy(summary)
        summary["coverage_evidence"] = {
            "state": bound.get("state"),
            "verified_requirement_count": bound.get("verified_requirement_count"),
            "partial_requirement_count": bound.get("partial_requirement_count"),
            "unverified_requirement_count": bound.get("unverified_requirement_count"),
            "blocking_requirements": deepcopy(bound.get("blocking_requirements") or []),
        }
        summary["status"] = "review_required"
        summary["review_required"] = True
        summary["requirement_coverage"] = "unknown"
        summary["unknown_requirements"] = deepcopy(bound.get("blocking_requirements") or [])
        interpretation["acceptance_summary"] = summary


def _single_candidate_title(trial: dict[str, Any]) -> str:
    objects = list(trial.get("logical_objects") or [])
    labels = [str(item.get("label") or "").strip() for item in objects if isinstance(item, dict)]
    labels = [label for label in labels if label]
    return labels[0][:100] if len(labels) == 1 else "通用 CAD 构造候选"


def _project_name(source_text: str) -> str:
    compact = " ".join(source_text.strip().split())
    if len(compact) > 48:
        compact = compact[:48].rstrip() + "..."
    return f"{compact or '通用 CAD'} · 构造项目"
