"""Persist verified generic CAD construction results as design candidates."""

from __future__ import annotations

from copy import deepcopy
import json
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
from .cad_requirement_binding import (
    bind_construction_coverage,
    unresolved_drawing_creation_requirements,
)


class ConstructionCommitError(ValueError):
    """Raised when an interpretation cannot be committed atomically."""


def _validated_write_receipt(
    persisted: dict[str, Any],
    *,
    project_id: str,
    variant_id: str,
    expected_before_variant_count: int,
    require_created: bool,
) -> dict[str, Any]:
    """Validate the store-issued receipt after the atomic write."""
    receipt = persisted.get("write_receipt")
    if not isinstance(receipt, dict):
        raise ConstructionCommitError("候选写入缺少可验证的存储回执。")
    if str(receipt.get("project_id") or "") != project_id:
        raise ConstructionCommitError("候选写入回执的项目身份不一致。")
    if str(receipt.get("variant_id") or "") != variant_id:
        raise ConstructionCommitError("候选写入回执的候选身份不一致。")
    if not str(receipt.get("authority") or ""):
        raise ConstructionCommitError("候选写入回执缺少存储权威。")
    snapshot = persisted.get("project")
    snapshot_variant_ids = {
        str(item.get("id"))
        for item in ((snapshot or {}).get("variants") or [])
        if isinstance(item, dict)
    } if isinstance(snapshot, dict) else set()
    if variant_id not in snapshot_variant_ids:
        raise ConstructionCommitError("候选写入回执声称的候选不在原子项目快照中。")
    if receipt.get("created") is True:
        expected_after = (
            int(receipt.get("before_variant_count") or 0)
            - int(receipt.get("superseded_count") or 0)
            + 1
        )
        if receipt.get("after_variant_count") != expected_after:
            raise ConstructionCommitError("候选写入回执的新增计数不自洽。")
    elif (
        receipt.get("after_variant_count") != receipt.get("before_variant_count")
        or int(receipt.get("superseded_count") or 0) != 0
    ):
        raise ConstructionCommitError("候选写入回执的复用计数不自洽。")
    if require_created:
        if receipt.get("created") is not True or receipt.get("reused_existing") is not False:
            raise ConstructionCommitError(
                "本次请求没有创建新的可用图纸候选；不能复用已有候选满足“新建图纸”。"
            )
        if receipt.get("before_variant_count") != expected_before_variant_count:
            raise ConstructionCommitError("候选写入回执的写入前状态与本次请求不一致。")
    return receipt



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
    prior_variant_count = len(project.get("variants") or []) if isinstance(project, dict) else 0
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

    persisted: list[dict[str, Any]] = []
    by_candidate_id: dict[str, dict[str, Any]] = {}
    try:
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
        # Re-execution and binding are part of the same atomic commit boundary
        # as project creation and candidate persistence.  Any failure here
        # must reach the rollback below, not escape past it.
        _refresh_candidate_trials(candidates)
        req = project.get("requirements") or {}
        source_ledger = req.get("requirement_ledger") or project_requirement_ledger(
            str(project.get("original_prompt") or source_text), req.get("source_followups") or [],
            missing=project.get("missing_parameters") or [])
        base_interpretation = deepcopy(interpretation)
        store_for_update = store if store is not None else getattr(add_variant, "__self__", None)
        for index, candidate in enumerate(candidates, start=1):
            trial = candidate["trial_result"]
            # Pre-bind without claiming a write.  The provisional candidate may
            # remain review-only until the store returns a real receipt.
            candidate_interpretation = _candidate_interpretation(
                source_text,
                base_interpretation,
                candidate,
                source_ledger,
                project,
                project_created_in_commit=project_created_in_commit,
                prior_variant_count=prior_variant_count,
                candidate_write_in_commit=False,
                write_receipt=None,
            )
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
            provisional_record = _construction_record(candidate_interpretation, candidate, trial)
            persisted_variant = persist_candidate_variant(
                project_id=str(project["id"]),
                name=str(metadata.get("title") or candidate.get("title") or f"结构候选 {index}"),
                geometries=geometries,
                rationale=str(metadata.get("description") or candidate.get("rationale") or "由结构化构造计划确定性生成。"),
                assessment=assessment,
                add_variant=add_variant,
                get_project=get_project,
                stored_preview=preview_paths({"lines": geometries}),
                acceptance_summary=deepcopy(candidate_interpretation.get("acceptance_summary")),
                logical_objects=list(metadata.get("logical_objects") or trial.get("logical_objects") or []),
                topology=dict(metadata.get("topology") or trial.get("topology") or {}),
                **({"instance_contract": metadata["instance_contract"]} if metadata.get("instance_contract") else {}),
                construction_record=provisional_record,
                **({"execution_context": deepcopy(metadata["execution_context"])}
                   if isinstance(metadata.get("execution_context"), dict) else {}),
            )
            if persisted_variant.get("ok") is not True:
                raise ConstructionCommitError(
                    str(persisted_variant.get("message") or f"结构候选 {index} 未通过项目写入校验。")
                )
            variant = persisted_variant["variant"]
            # A later candidate in the same request sees the earlier writes;
            # the store receipt must therefore report that exact prior count.
            expected_before = int(prior_variant_count) + index - 1
            requires_first_write = bool(
                unresolved_drawing_creation_requirements(
                    (candidate_interpretation.get("source_acceptance") or {}).get(
                        "coverage_evidence"
                    )
                )
                and not project_created_in_commit
            )
            receipt = _validated_write_receipt(
                persisted_variant,
                project_id=str(project["id"]),
                variant_id=str(variant.get("id")),
                expected_before_variant_count=expected_before,
                require_created=requires_first_write,
            ) if (
                isinstance(persisted_variant.get("write_receipt"), dict)
                or requires_first_write
            ) else None
            if receipt is not None and receipt.get("created") is True:
                # The receipt proves this request created the candidate.  A
                # still-unverified operation clause may now be rebound against
                # that proven write inside the same transaction.
                if requires_first_write:
                    _rebind_source_acceptance(
                        source_text,
                        candidate_interpretation,
                        candidate,
                        project,
                        project_created_in_commit=False,
                        prior_variant_count=prior_variant_count,
                        candidate_write_in_commit=True,
                        write_receipt=receipt,
                    )
                final_record = _construction_record(
                    candidate_interpretation, candidate, trial, write_receipt=receipt
                )
                updater = getattr(store_for_update, "update_variant_acceptance_with_receipt", None)
                if not callable(updater):
                    raise ConstructionCommitError("候选已创建，但缺少原子验收更新入口。")
                updated_candidate = updater(
                    str(project["id"]),
                    str(variant["id"]),
                    acceptance_summary=deepcopy(candidate_interpretation.get("acceptance_summary")),
                    construction_record=final_record,
                )
                if not isinstance(updated_candidate, dict) or updated_candidate.get("updated") is not True:
                    raise ConstructionCommitError("候选已创建，但验收状态无法回写。")
                variant = updated_candidate["variant"]
            persisted.append(variant)
            by_candidate_id[str(candidate["candidate_id"])] = variant
        # The post-write readback is part of the same transaction boundary: a
        # project created by this call must not survive a failed final read.
        updated = get_project(str(project["id"]))
        if updated is None:
            raise ConstructionCommitError("候选已写入，但无法重新读取项目。")
        reloaded_variants = {
            str(item.get("id")): item
            for item in (updated.get("variants") or [])
            if isinstance(item, dict)
        }
        for persisted_variant in persisted:
            reloaded = reloaded_variants.get(str(persisted_variant.get("id")))
            if reloaded is None:
                raise ConstructionCommitError("候选已写入，但回读时不在项目中。")
            expected_hash = str(persisted_variant.get("geometry_evidence_hash") or "")
            reloaded_hash = str(reloaded.get("geometry_evidence_hash") or "")
            if expected_hash and reloaded_hash != expected_hash:
                raise ConstructionCommitError("候选已写入，但回读的几何哈希不一致。")
    except Exception as exc:
        if not project_id and isinstance(project, dict) and project.get("id"):
            store.delete(str(project["id"]))
        if isinstance(exc, ConstructionCommitError):
            raise
        raise ConstructionCommitError(str(exc)) from exc

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


def _summary_passed(summary: Any) -> bool:
    return bool(
        isinstance(summary, dict)
        and summary.get("status") == "passed"
        and summary.get("review_required") is not True
    )


def _construction_record(
    interpretation: dict[str, Any],
    candidate: dict[str, Any],
    trial: dict[str, Any],
    write_receipt: dict[str, Any] | None = None,
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
        "residual_vector": deepcopy(interpretation.get("residual_vector")),
        "write_receipt": deepcopy(write_receipt) if isinstance(write_receipt, dict) else None,
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


def _candidate_interpretation(
    source_text: str,
    interpretation: dict[str, Any],
    candidate: dict[str, Any],
    source_ledger: dict[str, Any],
    project: dict[str, Any],
    *,
    project_created_in_commit: bool,
    prior_variant_count: int,
    candidate_write_in_commit: bool = False,
    write_receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return an isolated acceptance view for exactly one candidate."""
    candidate_interpretation = deepcopy(interpretation)
    _rebind_source_acceptance(
        source_text,
        candidate_interpretation,
        candidate,
        project,
        project_created_in_commit=project_created_in_commit,
        prior_variant_count=prior_variant_count,
        candidate_write_in_commit=candidate_write_in_commit,
        write_receipt=write_receipt,
    )
    construction_ledger = candidate_interpretation.get("requirement_ledger") or {}
    candidate_interpretation["requirement_ledger"] = candidate_requirement_snapshot(
        source_ledger,
        {**construction_ledger,
         "source_geometry_acceptance": candidate_interpretation.get("source_acceptance") or {}},
    )
    return candidate_interpretation


def _inventory_proof_matches(entry: Any, proof: dict[str, Any]) -> bool:
    """Whether one unknown entry belongs to this measured count proof."""
    if not isinstance(proof, dict):
        return False
    category = str(proof.get("category") or "")
    category_terms = {
        "circle": ("圆", "circle", "孔"),
        "outline": ("轮廓", "外形", "外框", "outline"),
        "arc": ("弧", "arc"),
    }.get(category, (category,) if category else ())
    requirement_id = str(proof.get("source_requirement_id")
                         or proof.get("requirement_id") or "")
    text = entry if isinstance(entry, str) else json.dumps(entry, ensure_ascii=False)
    if requirement_id and requirement_id in text:
        return True
    return any(term and term in text for term in category_terms)


def _resolve_inventory_acceptance(source_acceptance: dict[str, Any],
                                  count_proofs: list[dict[str, Any]]) -> None:
    """Resolve inventory-only reports from measured count/identity proofs.

    The historical producer leaves these two reports ``unverified`` whenever a
    count phrase was not parsed into its structural inventory.  When the atomic
    pass has independently measured exactly that category/quantity and each
    member is a distinct object, the reports can be rebuilt from that proof.
    Nothing is inferred for a category that has no proof.
    """
    covered = [
        proof for proof in count_proofs
        if proof.get("quantity") == proof.get("actual")
        and proof.get("category")
        and (proof.get("source_requirement_id") or proof.get("requirement_id"))
        and proof.get("unique_objects") is True
        and proof.get("unique_geometries") is True
        and len(proof.get("object_ids") or []) == proof.get("actual")
        and len(set(proof.get("object_ids") or [])) == len(proof.get("object_ids") or [])
        and len(proof.get("geometry_ids") or []) == proof.get("actual")
        and len(set(proof.get("geometry_ids") or [])) == len(proof.get("geometry_ids") or [])
    ]
    if not covered:
        return
    count_report = source_acceptance.get("object_count_consistency_acceptance")
    if isinstance(count_report, dict) and count_report.get("status") != "passed":
        updated = deepcopy(count_report)
        updated["status"] = "passed"
        updated["review_required"] = False
        updated["checks"] = [{
            "kind": "object_count",
            "requirement_id": proof.get("requirement_id"),
            "category": proof.get("category"),
            "expected": proof.get("quantity"),
            "actual": proof.get("actual"),
            "object_ids": list(proof.get("object_ids") or []),
            "status": "passed",
            "authority": "backend_measured_geometry",
        } for proof in covered]
        updated["unknown_requirements"] = [
            entry for entry in updated.get("unknown_requirements") or []
            if not any(_inventory_proof_matches(entry, proof) for proof in covered)
        ]
        remaining_entries = [
            entry for entry in (updated.get("baseline") or {}).get("entries") or []
            if not any(_inventory_proof_matches(entry, proof) for proof in covered)
        ]
        updated["baseline"] = {
            **(updated.get("baseline") or {}),
            "state": "complete" if not remaining_entries else "partial",
            "entries": remaining_entries,
        }
        if updated["unknown_requirements"] or remaining_entries:
            updated["status"] = "review_required"
            updated["review_required"] = True
        updated["actual_object_count"] = sum(int(proof.get("actual") or 0)
                                             for proof in covered)
        updated["note"] = "对象数量由后端测量对象逐类对账。"
        source_acceptance["object_count_consistency_acceptance"] = updated

    identity_report = source_acceptance.get("object_identity_acceptance")
    if isinstance(identity_report, dict) and identity_report.get("status") != "passed":
        updated = deepcopy(identity_report)
        updated["status"] = "passed"
        updated["review_required"] = False
        updated["identity_state"] = "bound"
        updated["evidence_grade"] = "measured"
        updated["matched_entries"] = [{
            "requirement_id": proof.get("requirement_id"),
            "category": proof.get("category"),
            "quantity": proof.get("quantity"),
            "object_ids": list(proof.get("object_ids") or []),
            "geometry_ids": list(proof.get("geometry_ids") or []),
            "status": "matched",
            "authority": "backend_measured_geometry",
        } for proof in covered]
        matched_object_ids = {
            object_id for proof in covered for object_id in proof.get("object_ids") or []
        }
        updated["unmatched_entries"] = [
            entry for entry in updated.get("unmatched_entries") or []
            if not any(_inventory_proof_matches(entry, proof) for proof in covered)
        ]
        updated["unmatched_objects"] = [
            obj for obj in updated.get("unmatched_objects") or []
            if not (
                isinstance(obj, dict)
                and str(obj.get("object_id") or "") in matched_object_ids
            )
        ]
        updated["ambiguous_bindings"] = [
            entry for entry in updated.get("ambiguous_bindings") or []
            if not any(_inventory_proof_matches(entry, proof) for proof in covered)
        ]
        updated["checks"] = [{
            "kind": "object_identity",
            "requirement_id": proof.get("requirement_id"),
            "status": "passed",
            "object_count": len(proof.get("object_ids") or []),
            "geometry_count": len(proof.get("geometry_ids") or []),
        } for proof in covered]
        updated["unknown_requirements"] = [
            entry for entry in updated.get("unknown_requirements") or []
            if not any(_inventory_proof_matches(entry, proof) for proof in covered)
        ]
        remaining_entries = [
            entry for entry in (updated.get("baseline") or {}).get("entries") or []
            if not any(_inventory_proof_matches(entry, proof) for proof in covered)
        ]
        updated["baseline"] = {
            **(updated.get("baseline") or {}),
            "inventory_state": "complete" if not remaining_entries else "partial",
            "entries": remaining_entries,
        }
        if (updated["unknown_requirements"] or remaining_entries
                or updated["unmatched_entries"] or updated["unmatched_objects"]
                or updated["ambiguous_bindings"]):
            updated["status"] = "review_required"
            updated["review_required"] = True
            updated["identity_state"] = "partial"
        updated["note"] = "对象身份由独立对象与几何一一对应关系确认。"
        source_acceptance["object_identity_acceptance"] = updated


def _rebind_source_acceptance(
    source_text: str,
    interpretation: dict[str, Any],
    candidate: dict[str, Any],
    project: dict[str, Any],
    *,
    project_created_in_commit: bool,
    prior_variant_count: int,
    candidate_write_in_commit: bool = False,
    write_receipt: dict[str, Any] | None = None,
) -> None:
    """Attach the project record and measured object binding before persistence.

    The binding is computed from this candidate's final trial result only, so a
    correct candidate cannot lend its acceptance summary to a different
    candidate.  Only ordinary, unique-object clauses can be promoted; all
    ambiguous or missing bindings keep their original blocking state.
    """
    source_acceptance = interpretation.get("source_acceptance")
    if not isinstance(source_acceptance, dict):
        return
    coverage = source_acceptance.get("coverage_evidence")
    if not isinstance(coverage, dict):
        return
    # Bindings are candidate-specific.  A base interpretation may already carry
    # the recommended candidate's verified clauses; reusing them would lend one
    # candidate's acceptance to another.  Reset only the proof state, keeping
    # the source facts, and re-measure this candidate from scratch.
    coverage = deepcopy(coverage)
    coverage.pop("binding", None)
    coverage["unresolved_fact_ids"] = []
    for clause in coverage.get("clauses") or []:
        if not isinstance(clause, dict):
            continue
        if clause.get("resolved_unsupported_evidence"):
            clause["unsupported_evidence"] = deepcopy(
                clause["resolved_unsupported_evidence"]
            )
        for key in ("binding", "evidence", "prior_status", "prior_reason",
                    "prior_evidence", "resolved_unsupported_evidence",
                    "binding_failures"):
            clause.pop(key, None)
        clause["status"] = "unverified"
        clause["reason"] = "当前没有可用的独立验证能力"
    source_acceptance = deepcopy(source_acceptance)
    source_acceptance["coverage_evidence"] = coverage
    trial = candidate.get("trial_result") if isinstance(candidate, dict) else None
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
            "prior_variant_count": int(prior_variant_count),
            "candidate_write_in_commit": candidate_write_in_commit,
            "write_receipt": deepcopy(write_receipt) if isinstance(write_receipt, dict) else None,
            "authority": "creative_project_store",
        },
        source_text=source_text,
    )
    source_acceptance = deepcopy(source_acceptance)
    source_acceptance["coverage_evidence"] = bound
    if bound.get("state") == "complete":
        clause_ids = {
            str(item.get("requirement_id"))
            for item in bound.get("clauses") or []
            if isinstance(item, dict) and item.get("requirement_id")
        }
        bound_fact_ids = {
            str(item)
            for item in ((bound.get("binding") or {}).get("bound_fact_ids") or [])
            if item
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
            if ref and (ref in clause_ids or ref in bound_fact_ids):
                continue
            remaining_unknown.append(item)
        count_proofs = (
            (bound.get("binding") or {}).get("object_count_proofs") or []
            if isinstance(bound.get("binding"), dict) else []
        )
        if count_proofs:
            filtered_unknown = []
            for item in remaining_unknown:
                if item.get("source") != "object_inventory":
                    filtered_unknown.append(item)
                    continue
                entries = [entry for entry in (item.get("entries") or [])
                           if isinstance(entry, dict)]
                unmatched = []
                for entry in entries:
                    category = entry.get("category")
                    quantity = entry.get("quantity")
                    if not any(
                        (proof.get("category") in (None, category))
                        and proof.get("quantity") == quantity
                        and proof.get("actual") == quantity
                        and proof.get("unique_objects") is True
                        and proof.get("unique_geometries") is True
                        and (proof.get("source_requirement_id")
                             or proof.get("requirement_id"))
                        for proof in count_proofs
                    ):
                        unmatched.append(entry)
                if unmatched:
                    filtered_unknown.append({**item, "entries": unmatched})
                # An entry-free inventory warning is resolved only when every
                # declared count in this coverage now has a measured proof.
            remaining_unknown = filtered_unknown
        source_acceptance["unknown_requirements"] = remaining_unknown
        if not remaining_unknown and count_proofs:
            _resolve_inventory_acceptance(source_acceptance, count_proofs)
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
        _refresh_residual_vector(interpretation, plan)
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
    _refresh_residual_vector(interpretation, plan)


def _refresh_residual_vector(
    interpretation: dict[str, Any], plan: dict[str, Any],
) -> None:
    """Rebuild residuals after final coverage binding.

    The interpreter emits an early vector before the atomic requirement pass.
    Once the final source acceptance is bound, measured failures such as a
    closure gap must be re-collected so the existing repair loop can consume
    them; no new verifier or tolerance is introduced here.
    """
    from .cad_residual_repair import build_residual_vector
    interpretation["residual_vector"] = build_residual_vector(
        source_acceptance=interpretation.get("source_acceptance"),
        plan=plan,
    )


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
