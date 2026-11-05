"""State-machine decisions for deterministic CAD candidate orchestration."""

from __future__ import annotations

import re
from copy import deepcopy
from collections.abc import Callable
from typing import Any

from .cad_project_candidates import (
    assess_reusable_variant,
    candidate_response_payload,
    candidate_requirement_readiness,
    candidate_variant_metadata,
    design_geometries_for_project,
    is_generator_supported_shape,
    project_logical_graph,
    template_instance_assessment,
    validate_candidate_geometries,
)
from .drawing_store import preview_paths, geometry_preview_paths


_SHORT_CONFIRMATIONS = {"确认", "同意", "可以", "好的", "好", "对", "正确"}


def persist_candidate_variant(
    *,
    project_id: str,
    name: str,
    geometries: list[dict[str, Any]],
    rationale: str,
    assessment: dict[str, Any],
    add_variant: Callable[..., dict[str, Any] | None],
    get_project: Callable[[str], dict[str, Any] | None],
    stored_preview: list[Any] | None = None,
    **metadata: Any,
) -> dict[str, Any]:
    """Single durable write boundary for every generated CAD candidate."""
    if not project_id or not geometries:
        return {"ok": False, "message": "候选方案缺少项目或有效几何。"}
    # Never manufacture a pass merely because geometries reached this write
    # boundary.  Only a measured construction/edit acceptance result may make
    # the candidate selectable or visible.
    if not isinstance(metadata.get("acceptance_summary"), dict):
        record_summary = (
            metadata.get("construction_record", {}).get("acceptance_summary")
            if isinstance(metadata.get("construction_record"), dict)
            else None
        )
        if isinstance(record_summary, dict):
            metadata["acceptance_summary"] = deepcopy(record_summary)
    from .cad_candidate_state import candidate_is_accepted
    if not candidate_is_accepted({
        "acceptance_summary": metadata.get("acceptance_summary"),
        "construction_record": metadata.get("construction_record"),
    }):
        return {"ok": False, "message": "候选缺少独立几何验收通过证据，不能保存为可用候选。"}
    preview = stored_preview or preview_paths({"lines": geometries})
    store=getattr(add_variant,'__self__',None)
    receipt_writer=getattr(store,'add_variant_with_receipt',None) if getattr(add_variant,'__name__','')=='add_variant' else None
    written = (receipt_writer or add_variant)(
        project_id,
        name,
        geometries,
        rationale,
        assessment,
        preview,
        **metadata,
    )
    variant=written.get('variant') if receipt_writer and written else written
    if variant is None:
        return {
            "ok": False,
            "message": "候选方案生成失败，当前项目状态可能已发生变化，请刷新项目后重试。",
        }
    try:
        project = written['project'] if receipt_writer else get_project(project_id)
    except (OSError, RuntimeError):
        project = None
    if not isinstance(project, dict):
        return {"ok": True,"persisted":True,"refresh_required":True,
                "project":None,"variant":variant,
                "preview_paths":geometry_preview_paths({"lines":geometries}),
                "message": "候选已保存，项目状态需要刷新；请勿重复生成。"}
    return {"ok": True, "project": project, "variant": variant,
            "persisted":True,"refresh_required":False,
            "preview_paths": geometry_preview_paths({"lines":geometries})}


def design_confirmation_gate(
    message: str,
    project: dict[str, Any] | None,
    *,
    explicit_confirmation: bool,
) -> dict[str, Any]:
    """Decide whether deterministic candidate confirmation owns this message."""
    normalized = re.sub(r"[\s，。！？、,.!?；;：:]+", "", message.strip().lower())
    contextual_confirmation = (
        normalized in _SHORT_CONFIRMATIONS
        and isinstance(project, dict)
        and str(project.get("status") or "") == "ready_for_design"
        and candidate_requirement_readiness(project, {}).get("ready") is True
        and not list(project.get("variants") or [])
    )
    should_handle = explicit_confirmation or contextual_confirmation
    if not should_handle:
        return {
            "should_handle": False,
            "contextual_confirmation": contextual_confirmation,
        }
    if project is None:
        return {
            "should_handle": True,
            "contextual_confirmation": contextual_confirmation,
            "error": "请先选择要生成方案的项目；如果这是新任务，请先说明图形和关键尺寸。",
        }
    return {
        "should_handle": True,
        "contextual_confirmation": contextual_confirmation,
        "project": project,
    }


def candidate_preflight(
    project: dict[str, Any],
    context: dict[str, Any],
    *,
    check_requirements: bool = True,
) -> dict[str, Any]:
    """Resolve blocking requirement errors before geometry generation."""
    conflicts = [str(item) for item in context.get("layout_conflicts") or []]
    if conflicts:
        return {
            "ok": False,
            "message": (
                "当前排列要求存在冲突，未生成或保存候选方案："
                + "、".join(conflicts)
                + "。请明确选择上下排列或左右排列，并只保留一个间距值。"
            ),
        }
    if not check_requirements:
        return {"ok": True}
    readiness = candidate_requirement_readiness(project, context)
    missing = list(readiness.get("missing") or [])
    if missing:
        return {
            "ok": False,
            "message": (
                "还缺少生成候选方案所需的："
                + "、".join(str(item) for item in missing)
                + "。请先补充并确认这些参数。"
            ),
            "readiness": readiness,
        }
    return {"ok": True, "readiness": readiness}


def restore_existing_candidate(
    project: dict[str, Any],
    variants: object,
    context: dict[str, Any],
    expected_geometries: list[dict[str, Any]] | None,
    *,
    migrate_variant: Callable[
        [str, str, list[dict[str, Any]], dict[str, Any]],
        dict[str, Any] | None,
    ],
) -> dict[str, Any]:
    """Find a reusable candidate and persist deterministic legacy ID migration."""
    status = str(project.get("status") or "")
    candidate_list = variants if isinstance(variants, list) else []
    eligible = status in {"designing", "ready_for_planning"} and bool(candidate_list)
    if not eligible:
        return {"variant": None, "quantity_mismatch": False}

    source_drawing = (
        project.get("source_drawing")
        if isinstance(project.get("source_drawing"), dict)
        else None
    )
    expected_template_name = str(context.get("expected_template_name") or "")
    expected_quantity = int(context.get("expected_quantity") or 1)
    for item in reversed(candidate_list):
        reuse = assess_reusable_variant(
            item,
            expected_geometries=expected_geometries,
            expected_template_name=expected_template_name,
            expected_quantity=expected_quantity,
            source_drawing=source_drawing,
        )
        migrated = reuse.get("migrated_geometries")
        assessment = reuse.get("instance_assessment")
        if (
            isinstance(item, dict)
            and isinstance(migrated, list)
            and isinstance(assessment, dict)
            and item.get("id")
        ):
            migrated_variant = migrate_variant(
                str(project["id"]),
                str(item["id"]),
                migrated,
                {
                    key: deepcopy(value)
                    for key, value in assessment.items()
                    if key != "migrated_geometries"
                },
            )
            if migrated_variant is not None:
                item.clear()
                item.update(migrated_variant)
        if reuse.get("reusable") is True:
            return {"variant": item, "quantity_mismatch": False}
    return {"variant": None, "quantity_mismatch": True}


def prepare_new_candidate(
    project: dict[str, Any],
    route: dict[str, Any],
    context: dict[str, Any],
    *,
    quantity_mismatch: bool,
    update_project: Callable[..., dict[str, Any] | None],
    construction_interpretation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Prepare validated candidate data without persisting the candidate itself."""
    preflight = candidate_preflight(project, context)
    if preflight.get("ok") is not True:
        return {"ok": False, "message": preflight.get("message")}
    readiness = preflight["readiness"]
    inferred_requirements = readiness.get("inferred_requirements") or {}
    if readiness["apply_default_printer"] or inferred_requirements:
        # 只补当前项目缺失的键，绝不覆盖用户已确认/已修改的参数。
        # inferred_requirements 是从 original_prompt 重新解析的，若浅覆盖写库，
        # 会把用户后续补充/修改的尺寸静默回滚成原 prompt 里的旧值。
        existing = dict(project.get("requirements") or {})
        requirements_update: dict[str, Any] = {}
        if readiness["apply_default_printer"] and not existing.get("printer"):
            requirements_update.update(readiness["default_requirements"])
        for key, value in inferred_requirements.items():
            if key not in existing or not existing[key]:
                requirements_update[key] = deepcopy(value)
        if requirements_update:
            updated = update_project(
                str(project["id"]),
                requirements=requirements_update,
                missing_parameters=[],
                event_message="确认生成候选方案时补齐缺失参数和默认中心喷码机",
            )
            if updated is not None:
                project = updated

    from .cad_template_plan import interpret_template_project
    try:
        interpretation = construction_interpretation or interpret_template_project(project, route)
        if interpretation is not None:
            geometries, missing_geometry = interpretation["trial_result"]["geometries"], []
        else:
            geometries, missing_geometry = design_geometries_for_project(project, route)
    except ValueError as exc:
        return {"ok": False, "message": "构造计划未通过校验：" + str(exc)}
    if geometries is None:
        # 非枚举图形（如 bezier）走构造/直投路径，确定性生成器不支持——
        # 明确告知而非误导为“缺图形类型和关键尺寸”。
        shape = str((project.get("requirements") or {}).get("shape") or "").strip()
        if shape and not is_generator_supported_shape(shape):
            return {
                "ok": False,
                "message": (
                    "该图形类型（" + shape + "）由 AI 按构造指令直接生成，"
                    "请让 AI 直接生成候选方案（不使用“确认需求并生成候选方案”按钮）。"
                ),
            }
        return {
            "ok": False,
            "message": (
                "还缺少生成候选方案所需的："
                + "、".join(str(item) for item in missing_geometry)
                + "。请先补充并确认这些参数。"
            ),
        }
    validation = validate_candidate_geometries(geometries, context)
    if validation.get("ok") is not True:
        return {
            "ok": False,
            "message": validation.get("message") or "候选方案校验失败。",
        }

    if isinstance(interpretation, dict) and not isinstance(
        interpretation.get("acceptance_summary"), dict
    ):
        # Template/rule interpretations share the same durable construction
        # commit as structured plans. Preserve the measured backend result in
        # that record so the common candidate gate can verify it.
        interpretation["acceptance_summary"] = {
            "status": "passed",
            "review_required": False,
            "authority": "backend_measured_geometry",
            "source": "candidate_geometry_validation",
            "verified_checks": 1 + (1 if validation.get("layout_validation") else 0),
        }

    expected_template_name = str(context.get("expected_template_name") or "")
    instance_contract = (
        template_instance_assessment(geometries, expected_template_name)
        if expected_template_name
        else None
    )
    metadata = candidate_variant_metadata(
        context, quantity_mismatch=quantity_mismatch
    )
    graph = project_logical_graph(project, metadata["graph_match"], geometries)
    return {
        "ok": True,
        "project": project,
        "geometries": geometries,
        "assessment": validation["assessment"],
        # Deterministic/template candidates do not have a construction
        # interpretation record, but they still need the same authoritative
        # evidence as model-produced candidates.  This summary is produced
        # from the backend geometry/feasibility checks above, never inferred
        # from project status or missing_parameters.
        "acceptance_summary": {
            "status": "passed",
            "review_required": False,
            "authority": "backend_measured_geometry",
            "source": "candidate_geometry_validation",
            "verified_checks": 1 + (1 if validation.get("layout_validation") else 0),
        },
        "layout_validation": validation.get("layout_validation"),
        "instance_contract": instance_contract,
        "logical_objects": graph["logical_objects"],
        "topology": graph["topology"],
        "title": metadata["title"],
        "description": metadata["description"],
        "construction_interpretation": interpretation,
    }


def persist_prepared_candidate(
    prepared: dict[str, Any],
    *,
    add_variant: Callable[..., dict[str, Any] | None],
    get_project: Callable[[str], dict[str, Any] | None],
    geometry_preview: Callable[[dict[str, Any]], list[Any]],
    drawing_payload: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """Persist prepared geometry and build the complete generated response."""
    project = prepared["project"]
    geometries = prepared["geometries"]
    project_id = str(project["id"])
    interpretation = prepared.get("construction_interpretation")
    if interpretation is not None:
        # Lazy import avoids the commit module's dependency on the common writer.
        from .cad_construction_commit import commit_construction_interpretation, ConstructionCommitError
        try:
            committed = commit_construction_interpretation(
                str(project.get("original_prompt") or project.get("name") or ""),
                interpretation, store=None, project_id=project_id,
                candidate_metadata=prepared, add_variant=add_variant, get_project=get_project,
            )
        except ConstructionCommitError as exc:
            return {"ok": False, "message": str(exc)}
        persisted = {"ok": True, "variant": committed["recommended_variant"], "project": committed["project"]}
    else:
        # Imported drawing snapshots and legacy parameterized custom shapes.
        persisted = persist_candidate_variant(
            project_id=project_id,
            name=str(prepared["title"]),
            geometries=geometries,
            rationale=str(prepared["description"]),
            assessment=prepared["assessment"],
            add_variant=add_variant,
            get_project=get_project,
            instance_contract=prepared["instance_contract"],
            logical_objects=prepared["logical_objects"],
            topology=prepared["topology"],
            acceptance_summary=deepcopy(prepared.get("acceptance_summary")),
            construction_record=deepcopy(prepared.get("construction_record")),
        )
    if persisted.get("ok") is not True:
        return persisted

    variant = persisted["variant"]
    updated_project = persisted["project"]
    preview = geometry_preview({"geometries": geometries})
    layout_validation = prepared.get("layout_validation")
    response = candidate_response_payload(
        updated_project,
        variant,
        preview,
        drawing_payload({
            "geometries": geometries,
            "logical_objects": list(variant.get("logical_objects") or []),
            "topology": dict(variant.get("topology") or {}),
        }),
        restored=False,
        layout_validation=(
            layout_validation if isinstance(layout_validation, dict) else None
        ),
    )
    if interpretation is not None:
        response["construction_commit"] = {"schema": committed["schema"], "persisted_candidate_count": 1}
    return {"ok": True, "response": response, "variant": variant}
