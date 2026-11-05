from __future__ import annotations

import json
import hashlib
import os
import tempfile
import threading
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from .task_store import utc_now
from .cad_candidate_state import candidate_is_accepted
from .project_ownership import owner_conversation
from .database import xline_database
from .drawing_store import (
    geometry_preview_paths,
    preview_paths as build_preview_paths,
)
from .geometry_diff import build_geometry_diff
from .geometry_identity import normalize_geometry_identity, validate_identity_continuity
from .cad_revision import (
    build_cad_revision_contract,
    verify_variant_revision_for_planning,
)
from .cad_edit_contract import CadEditCommand
from .cad_edit_preview import validate_cad_edit_preview
from .cad_assertions import validate_cad_machine_assertions
from .logical_topology import build_confirmed_instance_graph, validate_logical_object_graph
from .spatial_partition import (
    build_spatial_partition,
    update_partition_segment as apply_partition_segment_update,
    update_partition_zone as apply_partition_zone_update,
)


PROJECT_STATUSES = {
    "draft", "clarifying", "ready_for_design", "designing",
    "ready_for_planning", "planning", "planning_ready", "planning_failed",
    "pending_execution", "executing", "paused", "execution_failed",
    "completed", "cancelled",
}

ALLOWED_TRANSITIONS = {
    "draft": {"clarifying", "ready_for_design", "cancelled"},
    "clarifying": {"clarifying", "ready_for_design", "designing", "cancelled"},
    "ready_for_design": {"ready_for_design", "designing", "cancelled"},
    "designing": {"designing", "clarifying", "ready_for_planning", "cancelled"},
    "ready_for_planning": {"designing", "planning", "cancelled"},
    "planning": {"planning", "planning_ready", "planning_failed", "cancelled"},
    "planning_failed": {"designing", "planning", "cancelled"},
    "planning_ready": {"planning", "planning_failed", "pending_execution", "cancelled"},
    "pending_execution": {"planning_ready", "executing", "execution_failed", "cancelled"},
    "executing": {
        "executing", "paused", "completed", "execution_failed",
        "ready_for_planning", "cancelled",
    },
    "paused": {"paused", "executing", "planning", "execution_failed", "cancelled"},
    "execution_failed": {"designing", "planning", "cancelled"},
    "completed": {"designing"},
    "cancelled": {"designing", "planning"},
}


class CreativeProjectStore:
    def __init__(self, path: Path | None = None) -> None:
        self._database_enabled = path is None
        configured = os.getenv("XLINE_CREATIVE_PROJECT_STORE", "").strip()
        default_root = (
            Path(tempfile.gettempdir()) / "xline-agent"
            if os.name == "nt"
            else Path(os.getenv("XDG_STATE_HOME", Path.home() / ".local" / "state"))
            / "xline-agent"
        )
        self.path = path or (Path(configured) if configured else default_root / "creative_projects.json")
        self._lock = threading.RLock()
        self._projects: dict[str, dict[str, Any]] = {}
        self._load()
        self._durable_projects = deepcopy(self._projects)

    def create(self, name: str, original_prompt: str,
               requirements: dict[str, Any] | None = None,
               constraints: dict[str, Any] | None = None,
               missing_parameters: list[str] | None = None,
               source_drawing: dict[str, Any] | None = None,
               owner_conversation_id: str | None = None) -> dict[str, Any]:
        now = utc_now()
        missing = self._clean_missing(missing_parameters or [])
        project_id = str(uuid.uuid4())
        status = "clarifying" if missing else "ready_for_design"
        project = {
            "id": project_id, "name": name.strip(),
            "owner_conversation_id": owner_conversation_id.strip() if owner_conversation_id else owner_conversation.get(),
            "original_prompt": original_prompt.strip(),
            "requirements": deepcopy(requirements or {}),
            "constraints": deepcopy(constraints or {}),
            "missing_parameters": missing, "status": status, "variants": [],
            "created_at": now, "updated_at": now,
            "events": [self._event("created", f"项目已创建，状态为 {status}")],
        }
        normalized_source = self._normalize_source_drawing(source_drawing)
        if normalized_source is not None:
            project["source_drawing"] = normalized_source
        with self._lock:
            if self._database_enabled and project.get("owner_conversation_id"):
                from .conversation_archive import archived_chats
                if project["owner_conversation_id"] in archived_chats():
                    raise ValueError("所属对话已移入回收站，请先恢复对话")
            self._projects[project_id] = project
            self._save()
        return deepcopy(project)

    def update(self, project_id: str, *, name: str | None = None,
               requirements: dict[str, Any] | None = None,
               constraints: dict[str, Any] | None = None,
               missing_parameters: list[str] | None = None,
               status: str | None = None,
               event_message: str = "项目需求已更新") -> dict[str, Any] | None:
        with self._lock:
            project = self._projects.get(project_id)
            if project is None or project.get("deleted_at"):
                return None
            content_update = any(value is not None for value in (
                name, requirements, constraints, missing_parameters
            ))
            if content_update and project.get("status") not in {
                "draft", "clarifying", "ready_for_design", "designing"
            }:
                return None
            target_status = status
            if target_status is None and missing_parameters is not None:
                if self._clean_missing(missing_parameters):
                    target_status = "clarifying"
                elif project.get("design_base_variant_id") or project.get("status") == "designing":
                    # Clarification of an active edit returns to its existing
                    # design iteration and parent candidate.
                    target_status = "designing"
                else:
                    target_status = "ready_for_design"
            if target_status is not None:
                if target_status not in PROJECT_STATUSES:
                    raise ValueError(f"unsupported project status: {target_status}")
                if not self._transition(project, target_status):
                    return None
            if name is not None:
                project["name"] = name.strip()
            if requirements is not None:
                project["requirements"] = self._merge(project["requirements"], requirements)
            if constraints is not None:
                project["constraints"] = self._merge(project["constraints"], constraints)
            if missing_parameters is not None:
                project["missing_parameters"] = self._clean_missing(missing_parameters)
            project["updated_at"] = utc_now()
            project["events"].append(self._event("updated", event_message))
            self._save()
            return deepcopy(project)

    def get(self, project_id: str) -> dict[str, Any] | None:
        with self._lock:
            project = self._projects.get(project_id)
            return deepcopy(project) if project is not None and not project.get("deleted_at") else None

    def list(self, limit: int = 50, status: str | None = None, *, summary: bool = False,
             conversation_id: str | None = None, include_unowned: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            projects = [item for item in self._projects.values() if not item.get("deleted_at")]
            if conversation_id:
                projects = [item for item in projects
                            if item.get("owner_conversation_id") == conversation_id
                            or conversation_id in (item.get("referenced_conversation_ids") or [])
                            or (include_unowned and not item.get("owner_conversation_id"))]
            if status:
                projects = [item for item in projects if item.get("status") == status]
            projects.sort(key=lambda item: str(item.get("updated_at", "")), reverse=True)
            selected = projects[:max(1, min(limit, 200))]
            if summary:
                keys = {"id", "name", "status", "created_at", "updated_at", "selected_variant_id", "missing_parameters", "owner_conversation_id", "referenced_conversation_ids"}
                return deepcopy([{**{key: value for key, value in project.items() if key in keys},
                                  "variant_count": len(project.get("variants") or [])} for project in selected])
            return deepcopy(selected)

    def lifecycle(self, action: str, project_ids: list[str], conversation_id: str | None = None, *, persist: bool = True) -> dict[str, Any]:
        """Apply a preflighted lifecycle batch under one store lock."""
        with self._lock:
            items = [self._projects[key] for key in project_ids if key in self._projects]
            blocked = [item["name"] for item in items if item.get("status") in {"pending_execution", "executing", "paused", "planning"}]
            if blocked:
                return {"ok": False, "message": "请先结束任务：" + "、".join(blocked), "blocked_projects": blocked}
            if action == "preflight":
                return {"ok": True, "project_count": len(items)}
            if action not in {"trash", "restore", "purge", "claim", "reference"}:
                raise ValueError("unsupported lifecycle action")
            if len(items) != len(set(project_ids)):
                return {"ok": False, "message": "部分项目不存在，请刷新后重试"}
            if action == "purge" and any(not item.get("deleted_at") for item in items):
                return {"ok": False, "message": "请先移入回收站"}
            if action == "claim" and any(item.get("owner_conversation_id") not in {None, conversation_id} for item in items):
                return {"ok": False, "message": "项目已有所属对话，请引用或复制"}
            if action in {"claim", "reference"} and not conversation_id:
                return {"ok": False, "message": "必须指定对话"}
            if action in {"claim", "reference"} and any(item.get("deleted_at") for item in items):
                return {"ok": False, "message": "请先恢复项目"}
            if action in {"claim", "reference", "restore"} and persist:
                from .conversation_archive import archived_chats
                archived = archived_chats()
                targets = [conversation_id] if action != "restore" else [item.get("owner_conversation_id") for item in items]
                if any(target in archived for target in targets):
                    return {"ok": False, "message": "所属或目标对话已删除，请先恢复对话"}
            for item in items:
                if action == "trash":
                    item["deleted_at"] = utc_now()
                    item["deleted_with_conversation"] = item.get("owner_conversation_id") if conversation_id == "__batch__" else conversation_id
                elif action == "restore":
                    item.pop("deleted_at", None)
                    item.pop("deleted_with_conversation", None)
                elif action == "claim":
                    item["owner_conversation_id"] = conversation_id
                elif action == "reference":
                    item["referenced_conversation_ids"] = sorted(set(item.get("referenced_conversation_ids") or []) | {conversation_id})
                elif action == "purge":
                    if not item.get("deleted_at"):
                        return {"ok": False, "message": "请先移入回收站"}
            if action == "purge":
                for item in items:
                    self._projects.pop(item["id"])
                    if self._database_enabled and persist:
                        xline_database.delete_project(item["id"])
            else:
                for item in items:
                    item["updated_at"] = utc_now()
                    item.setdefault("events", []).append(self._event(action, "项目生命周期：" + action))
            if persist:
                self._save()
            return {"ok": True, "project_count": len(items)}

    def record_saved_drawing(self, project_id: str, variant_id: str, version: dict[str, Any]) -> None:
        with self._lock:
            project = self._projects.get(project_id)
            if project is None or project.get("deleted_at"):
                return
            for variant in project.get("variants") or []:
                if variant.get("id") == variant_id:
                    variant["saved_drawing"] = deepcopy(version)
                    project["updated_at"] = utc_now()
                    self._save()
                    return

    def lifecycle_items(self, *, deleted: bool = False, owner: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy([item for item in self._projects.values()
                             if bool(item.get("deleted_at")) == deleted
                             and (owner is None or item.get("owner_conversation_id") == owner)])

    def delete(self, project_id: str) -> bool:
        with self._lock:
            project = self._projects.get(project_id)
            if project is None or project.get("deleted_at") or project.get("status") in {"pending_execution", "executing", "paused"}:
                return False
            self._projects.pop(project_id)
            self._save()
            return True

    def add_variant_with_receipt(self, *args, **kwargs):
        """Return the committed project snapshot under the same store lock."""
        with self._lock:
            project_id=args[0] if args else kwargs['project_id']
            before=deepcopy(self._projects.get(project_id))
            try:
                variant=self.add_variant(*args, **kwargs)
            except Exception:
                if before is not None:
                    self._projects[project_id]=before
                raise
            if variant is None:
                return None
            return {'variant':variant,'project':deepcopy(self._projects[project_id])}

    def add_variant(self, project_id: str, name: str, geometries: list[dict[str, Any]],
                    rationale: str, assessment: dict[str, Any],
                    preview_paths: list[list[list[float]]],
                    parent_variant_id: str | None = None,
                    instance_contract: dict[str, Any] | None = None,
                    expected_quantity: int | None = None,
                     edit_contract: dict[str, Any] | None = None,
                     logical_objects: list[dict[str, Any]] | None = None,
                     topology: dict[str, Any] | None = None,
                     edit_plan: dict[str, Any] | None = None,
                     edit_preview: dict[str, Any] | None = None,
                     machine_assertions: dict[str, Any] | None = None,
                     construction_record: dict[str, Any] | None = None,
                     acceptance_summary: dict[str, Any] | None = None) -> dict[str, Any] | None:
        with self._lock:
            project = self._projects.get(project_id)
            if project is None or project.get("deleted_at"):
                return None
            # Content identity is scoped to the parent and requirement revision.
            # Random titles, scores and recovery diagnostics are not new work.
            identity_payload={"geometries":geometries,"logical_objects":logical_objects or [],
                "topology":topology or {},"parent":parent_variant_id or project.get("design_base_variant_id") or project.get("selected_variant_id"),
                "edit_contract":edit_contract,"source_revision":((construction_record or {}).get("requirement_ledger") or {}).get("revision_sha256")}
            write_key=hashlib.sha256(json.dumps(identity_payload,sort_keys=True,ensure_ascii=False).encode('utf-8')).hexdigest()
            incoming_accepted = candidate_is_accepted({
                'acceptance_summary': acceptance_summary,
                'construction_record': construction_record,
            })
            for existing in project.get('variants') or []:
                # Reuse only a candidate that is already eligible everywhere.
                # An earlier review-required write must not suppress a later
                # run that supplies real acceptance evidence for the same
                # geometry.
                if existing.get('write_key')==write_key:
                    if candidate_is_accepted(existing) or not incoming_accepted:
                        return deepcopy(existing)
            if project is None or project.get("deleted_at") or project.get("status") not in {
                "ready_for_design", "designing", "ready_for_planning", "planning_failed"
            }:
                return None
            if expected_quantity is not None and not 1 <= expected_quantity <= 50:
                return None
            if isinstance(edit_contract, dict):
                try:
                    edit_contract = CadEditCommand.model_validate(
                        edit_contract
                    ).model_dump(mode="json", by_alias=True, exclude_none=True)
                    normalized_target = edit_contract.get("target")
                    if (
                        isinstance(normalized_target, dict)
                        and not normalized_target.get("object_ids")
                    ):
                        normalized_target.pop("object_ids", None)
                except (TypeError, ValueError):
                    return None
            normalized_geometries, identity_contract, _ = normalize_geometry_identity(
                geometries
            )
            if normalized_geometries is None:
                return None
            geometries = normalized_geometries
            effective_parent_id = (
                parent_variant_id
                or project.get("design_base_variant_id")
                or project.get("selected_variant_id")
            )
            parent_variant = None
            if effective_parent_id is not None:
                parent_variant = next(
                    (item for item in project["variants"]
                     if item.get("id") == effective_parent_id),
                    None,
                )
                if not candidate_is_accepted(parent_variant):
                    return None
                if validate_identity_continuity(
                    parent_variant.get("geometries") or [], geometries
                ) is not None:
                    return None
            variant = {
                "write_key":write_key,
                "id": str(uuid.uuid4()),
                "name": name.strip(),
                "rationale": rationale.strip(),
                "geometries": deepcopy(geometries),
                "identity_contract": deepcopy(identity_contract),
                "assessment": deepcopy(assessment),
                "acceptance_summary": deepcopy(acceptance_summary) if isinstance(acceptance_summary, dict) else None,
                "preview_paths": geometry_preview_paths({"lines": geometries}),
                "selected": False,
                "created_at": utc_now(),
                "logical_objects": deepcopy(logical_objects or []),
                "topology": {
                    "schema_version": "cad.topology.v1",
                    "shared_geometries": [],
                    "relations": [],
                    **deepcopy(topology or {}),
                },
            }
            if expected_quantity is not None:
                variant["expected_quantity"] = expected_quantity
            if isinstance(edit_plan, dict):
                if (
                    edit_plan.get("schema") != "cad.edit-plan.v1"
                    or (edit_plan.get("verification") or {}).get("verified") is not True
                ):
                    return None
                variant["edit_plan"] = deepcopy(edit_plan)
            if isinstance(edit_preview, dict):
                if parent_variant is None or edit_contract is None:
                    return None
                preview_validation = validate_cad_edit_preview(
                    edit_preview,
                    list(parent_variant.get("geometries") or []),
                    geometries,
                    edit_contract,
                )
                if preview_validation.get("verified") is not True:
                    return None
                edit_preview = dict(preview_validation["preview"])
                variant["edit_preview"] = deepcopy(edit_preview)
                variant["edit_preview"]["execution"] = {
                    **dict(variant["edit_preview"].get("execution") or {}),
                    "persisted": True,
                    "execution_allowed": False,
                }
            if isinstance(machine_assertions, dict):
                if not all(isinstance(value, dict) for value in (
                    edit_contract, edit_plan, edit_preview,
                )) or parent_variant is None:
                    return None
                assertion_validation = validate_cad_machine_assertions(
                    machine_assertions,
                    list(parent_variant.get("geometries") or []),
                    geometries,
                    edit_contract,
                    edit_plan,
                    edit_preview,
                )
                if assertion_validation.get("verified") is not True:
                    return None
                variant["machine_assertions"] = deepcopy(
                    assertion_validation["report"]
                )
            if construction_record is not None:
                if (
                    not isinstance(construction_record, dict)
                    or construction_record.get("schema")
                    != "cad.construction-record.v1"
                    or not isinstance(construction_record.get("plan"), dict)
                    or not isinstance(construction_record.get("assertions"), dict)
                    or construction_record["assertions"].get("ok") is not True
                ):
                    return None
                variant["construction_record"] = deepcopy(construction_record)
                if construction_record.get("requirement_ledger"):
                    variant["requirement_ledger"] = deepcopy(construction_record["requirement_ledger"])
            elif parent_variant is not None and isinstance(edit_contract, dict):
                parent_ledger=parent_variant.get("requirement_ledger") or (parent_variant.get("construction_record") or {}).get("requirement_ledger")
                if parent_ledger:
                    from .cad_requirement_ledger import project_requirement_ledger, _revision
                    texts=[s["text"] for s in parent_ledger.get("sources") or [] if s.get("origin")=="user"]
                    if texts:
                        message=edit_contract.get("source_text")
                        edit_sources=(edit_contract.get('intent_grounding') or {}).get('source_turns')
                        if not isinstance(edit_sources,list) or not all(isinstance(t,str) and t.strip() for t in edit_sources):
                            edit_sources=[message] if message else []
                        variant["requirement_ledger"]=project_requirement_ledger(
                            texts[0],texts[1:]+edit_sources,previous=parent_ledger)
                        # Previous coordinate checks describe the previous
                        # revision. Preserve provenance, never reuse its pass.
                        variant["requirement_ledger"]["geometry_acceptance"]={"status":"not_checked","checks":[]}
                        variant["requirement_ledger"].pop("revision_sha256",None)
                        variant["requirement_ledger"]["revision_sha256"]=_revision(variant["requirement_ledger"])
            logical_validation = validate_logical_object_graph(
                geometries, variant["logical_objects"], variant["topology"]
            )
            if logical_validation["verified"] is not True:
                return None
            variant["logical_object_validation"] = logical_validation
            if not isinstance(variant.get("acceptance_summary"), dict):
                edit_verified = (
                    isinstance(variant.get("machine_assertions"), dict)
                    and variant["machine_assertions"].get("verified") is True
                )
                variant["acceptance_summary"] = {
                    "status": "passed" if edit_verified else "review_required",
                    "review_required": not edit_verified,
                    "authority": "backend_measured_geometry",
                    "source": "cad_edit_machine_assertions" if edit_verified else "missing_acceptance_evidence",
                }
            project_scale = (
                variant["assessment"].get("project_scale")
                if isinstance(variant.get("assessment"), dict)
                else None
            )
            if (
                isinstance(project_scale, dict)
                and project_scale.get("requires_partitioning") is True
            ):
                spatial_partition = build_spatial_partition(
                    str(variant["id"]),
                    geometries,
                    variant["logical_objects"],
                    variant["topology"],
                    project_scale,
                )
                if spatial_partition.get("status") != "ready":
                    return None
                variant["spatial_partition"] = spatial_partition
            if isinstance(instance_contract, dict):
                variant["instance_contract"] = deepcopy(instance_contract)
            if parent_variant is not None:
                variant["parent_variant_id"] = effective_parent_id
                variant["parent_variant_name"] = str(parent_variant.get("name") or "")
                current_feasibility = (variant["assessment"].get("feasibility")
                                       if isinstance(variant["assessment"], dict) else {}) or {}
                parent_assessment = parent_variant.get("assessment") or {}
                parent_feasibility = parent_assessment.get("feasibility") or {}

                def number(data: dict[str, Any], key: str) -> float:
                    try:
                        return float(data.get(key) or 0.0)
                    except (TypeError, ValueError):
                        return 0.0

                change_summary = {
                    "geometry_delta": int(number(current_feasibility, "geometry_count")
                                           - number(parent_feasibility, "geometry_count")),
                    "path_delta": int(number(current_feasibility, "preview_path_count")
                                      - number(parent_feasibility, "preview_path_count")),
                    "printing_length_delta_m": round(
                        number(current_feasibility, "printing_length_m")
                        - number(parent_feasibility, "printing_length_m"), 4
                    ),
                }
                variant["assessment"]["change_summary"] = change_summary
                variant["assessment"]["change_summary_text"] = (
                    f"几何 {change_summary['geometry_delta']:+d} · "
                    f"路径 {change_summary['path_delta']:+d} · "
                    f"喷墨 {change_summary['printing_length_delta_m']:+.2f} m"
                )
            source = project.get("source_drawing")
            source_geometries = (
                parent_variant.get("geometries")
                if isinstance(parent_variant, dict)
                else source.get("geometries") if isinstance(source, dict) else None
            )
            if isinstance(source_geometries, list):
                diff = build_geometry_diff(source_geometries, geometries)
                variant["diff"] = diff
                variant["revision_contract"] = build_cad_revision_contract(
                    source_geometries,
                    geometries,
                    parent_variant_id=str(effective_parent_id or ""),
                    variant_id=str(variant["id"]),
                    edit_contract=edit_contract,
                    source_logical_objects=list(parent_variant.get("logical_objects") or [])
                    if isinstance(parent_variant, dict) else [],
                    target_logical_objects=variant["logical_objects"],
                    source_topology=dict(parent_variant.get("topology") or {})
                    if isinstance(parent_variant, dict) else {},
                    target_topology=variant["topology"],
                )
                logical_revision = variant["revision_contract"].get(
                    "logical_object_validation"
                )
                if (
                    isinstance(logical_revision, dict)
                    and logical_revision.get("verified") is not True
                ):
                    return None
                variant["source_preview_paths"] = build_preview_paths({"lines": source_geometries})
                diff_paths: list[dict[str, Any]] = []
                for geometry in diff["added"]:
                    diff_paths.extend(
                        {"points": points, "diff_kind": "added"}
                        for points in build_preview_paths({"lines": [geometry]})
                    )
                for geometry in diff["removed"]:
                    diff_paths.extend(
                        {"points": points, "diff_kind": "removed"}
                        for points in build_preview_paths({"lines": [geometry]})
                    )
                for change in diff["modified"]:
                    for geometry in (change["after"],):
                        diff_paths.extend(
                            {"points": points, "diff_kind": "modified"}
                            for points in build_preview_paths({"lines": [geometry]})
                        )
                for geometry in diff["unchanged"]:
                    diff_paths.extend(
                        {"points": points, "diff_kind": "unchanged"}
                        for points in build_preview_paths({"lines": [geometry]})
                    )
                variant["diff_preview_paths"] = diff_paths
            project["variants"].append(variant)
            if not self._transition(project, "designing"):
                project["variants"].pop()
                return None
            if expected_quantity is not None:
                project["requirements"]["quantity"] = expected_quantity
            project["updated_at"] = utc_now()
            event_message = f"新增方案：{variant['name']}"
            if parent_variant is not None:
                event_message += f"（基于 {parent_variant.get('name') or effective_parent_id}）"
            project["events"].append(self._event("variant_added", event_message))
            self._save()
            return deepcopy(variant)

    def migrate_variant_instances(
        self,
        project_id: str,
        variant_id: str,
        geometries: list[dict[str, Any]],
        instance_contract: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Persist a deterministic legacy-template instance migration."""
        with self._lock:
            normalized, identity_contract, _ = normalize_geometry_identity(geometries)
            if normalized is None:
                return None
            project = self._projects.get(project_id)
            if project is None or project.get("deleted_at"):
                return None
            variant = next(
                (item for item in project.get("variants", []) if item.get("id") == variant_id),
                None,
            )
            if variant is None:
                return None
            if validate_identity_continuity(
                variant.get("geometries") or [], normalized
            ) is not None:
                return None
            variant["geometries"] = deepcopy(normalized)
            variant["instance_contract"] = deepcopy(instance_contract)
            variant["identity_contract"] = deepcopy(identity_contract)
            project["updated_at"] = utc_now()
            project["events"].append(self._event(
                "variant_instances_migrated",
                f"已为旧模板方案 {variant.get('name') or variant_id} 补充稳定实例编号",
            ))
            self._save()
            return deepcopy(variant)

    def migrate_variant_logical_graph(
        self,
        project_id: str,
        variant_id: str,
        logical_objects: list[dict[str, Any]],
        topology: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Add a verified logical graph to a legacy variant without changing geometry."""
        with self._lock:
            project = self._projects.get(project_id)
            if project is None or project.get("deleted_at"):
                return None
            variant = next(
                (item for item in project.get("variants", []) if item.get("id") == variant_id),
                None,
            )
            if variant is None:
                return None
            if list(variant.get("logical_objects") or []):
                return deepcopy(variant)
            validation = validate_logical_object_graph(
                list(variant.get("geometries") or []), logical_objects, topology
            )
            if validation.get("verified") is not True:
                return None
            variant["logical_objects"] = deepcopy(logical_objects)
            variant["topology"] = deepcopy(topology)
            project["updated_at"] = utc_now()
            project["events"].append(self._event(
                "variant_logical_graph_migrated",
                f"已为旧方案 {variant.get('name') or variant_id} 补充完整图形分组",
            ))
            self._save()
            return deepcopy(variant)

    def set_variant_partition(
        self,
        project_id: str,
        variant_id: str,
        partition: dict[str, Any],
    ) -> dict[str, Any] | None:
        with self._lock:
            project = self._projects.get(project_id)
            if project is None or project.get("deleted_at"):
                return None
            variant = next(
                (
                    item
                    for item in project.get("variants", [])
                    if item.get("id") == variant_id
                ),
                None,
            )
            if variant is None or partition.get("status") != "ready":
                return None
            variant["spatial_partition"] = deepcopy(partition)
            project["updated_at"] = utc_now()
            project["events"].append(
                self._event(
                    "spatial_partition_created",
                    f"方案 {variant.get('name') or variant_id} 已拆分为 "
                    f"{(partition.get('summary') or {}).get('construction_zone_count', 0)} 个施工区",
                )
            )
            self._save()
            return deepcopy(project)

    def update_variant_partition_zone(
        self,
        project_id: str,
        variant_id: str,
        zone_id: str,
        status: str,
        **updates: Any,
    ) -> dict[str, Any] | None:
        with self._lock:
            project = self._projects.get(project_id)
            if project is None or project.get("deleted_at"):
                return None
            variant = next(
                (
                    item
                    for item in project.get("variants", [])
                    if item.get("id") == variant_id
                ),
                None,
            )
            partition = variant.get("spatial_partition") if variant else None
            if not isinstance(partition, dict):
                return None
            try:
                variant["spatial_partition"] = apply_partition_zone_update(
                    partition, zone_id, status, **updates
                )
            except ValueError:
                return None
            project["updated_at"] = utc_now()
            project["events"].append(
                self._event(
                    "partition_zone_updated",
                    f"施工区 {zone_id} 状态更新为 {status}",
                )
            )
            self._save()
            return deepcopy(project)

    def update_variant_partition_segment(
        self,
        project_id: str,
        variant_id: str,
        zone_id: str,
        segment_id: str,
        status: str,
        **updates: Any,
    ) -> dict[str, Any] | None:
        with self._lock:
            project = self._projects.get(project_id)
            if project is None or project.get("deleted_at"):
                return None
            if not self._apply_variant_partition_segment(
                project, variant_id, zone_id, segment_id, status, **updates
            ):
                return None
            self._save()
            return deepcopy(project)

    def _apply_variant_partition_segment(
        self,
        project: dict[str, Any],
        variant_id: str,
        zone_id: str,
        segment_id: str,
        status: str,
        **updates: Any,
    ) -> bool:
        """Update one partition segment without crossing a persistence boundary."""
        try:
            variant = next(
                (
                    item
                    for item in project.get("variants", [])
                    if item.get("id") == variant_id
                ),
                None,
            )
            partition = variant.get("spatial_partition") if variant else None
            if not isinstance(partition, dict):
                return False
            variant["spatial_partition"] = apply_partition_segment_update(
                partition,
                zone_id,
                segment_id,
                status,
                **updates,
            )
            project["updated_at"] = utc_now()
            project["events"].append(
                self._event(
                    "partition_segment_updated",
                    f"施工区 {zone_id} 分段 {segment_id} 状态更新为 {status}",
                )
            )
            return True
        except (StopIteration, ValueError, TypeError):
            return False

    def confirm_source_instance_groups(
        self, project_id: str, groups: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        with self._lock:
            project = self._projects.get(project_id)
            source = project.get("source_drawing") if isinstance(project, dict) else None
            if project is None or project.get("deleted_at") or not isinstance(source, dict):
                return None
            geometries = source.get("geometries")
            if not isinstance(geometries, list):
                return None
            geometry_by_id = {
                str(item.get("id")): item for item in geometries
                if isinstance(item, dict) and item.get("id") is not None
            }
            seen: set[str] = set()
            normalized: list[dict[str, Any]] = []
            for index, group in enumerate(groups, 1):
                if not isinstance(group, dict):
                    return None
                raw_ids = group.get("geometry_ids")
                if not isinstance(raw_ids, list) or not raw_ids:
                    return None
                ids = [str(value) for value in raw_ids]
                if len(ids) != len(set(ids)) or any(value not in geometry_by_id for value in ids):
                    return None
                if seen.intersection(ids):
                    return None
                seen.update(ids)
                normalized.append({
                    "instance_id": int(group.get("instance_id") or index),
                    "geometry_ids": [int(value) if value.isdigit() else value for value in ids],
                    "label": str(group.get("label") or f"实例 {index}"),
                })
            if seen != set(geometry_by_id):
                return None
            for group in normalized:
                for geometry_id in group["geometry_ids"]:
                    geometry = geometry_by_id[str(geometry_id)]
                    geometry["template_instance"] = group["instance_id"]
                    geometry["template_type"] = str(
                        project.get("requirements", {}).get("shape") or "cad"
                    )
            normalized_geometries, identity_contract, _ = normalize_geometry_identity(
                geometries
            )
            if normalized_geometries is None:
                return None
            source["geometries"] = normalized_geometries
            source["identity_contract"] = identity_contract
            source_format = str(source.get("source_format") or "").lower()
            object_type = "image_drawing" if source_format == "image" else "imported_cad"
            graph = build_confirmed_instance_graph(
                normalized_geometries, normalized, object_type=object_type
            )
            graph_validation = validate_logical_object_graph(
                normalized_geometries,
                graph["logical_objects"],
                graph["topology"],
            )
            if graph_validation.get("verified") is not True:
                return None
            source["logical_objects"] = graph["logical_objects"]
            source["topology"] = graph["topology"]
            analysis = source.setdefault("cad_analysis", {})
            analysis["instance_groups"] = deepcopy(normalized)
            analysis["instance_groups_confirmed"] = True
            analysis["instance_group_count"] = len(normalized)
            project["updated_at"] = utc_now()
            project["events"].append(self._event(
                "cad_instance_groups_confirmed",
                f"用户确认 CAD 实例分组，共 {len(normalized)} 组",
            ))
            self._save()
            return deepcopy(project)

    def select_variant(self, project_id: str, variant_id: str) -> dict[str, Any] | None:
        with self._lock:
            project = self._projects.get(project_id)
            if project is None or project.get("deleted_at") or project.get("status") not in {"designing", "ready_for_planning"}:
                return None
            selected = next(
                (variant for variant in project["variants"]
                 if variant.get("id") == variant_id),
                None,
            )
            if not candidate_is_accepted(selected):
                return None
            assessment = selected.get("assessment") or {}
            feasibility = assessment.get("feasibility") or {}
            if isinstance(feasibility.get("errors"), list) and feasibility["errors"]:
                # Keep invalid designs reviewable, but never let them enter
                # the planning/execution state through a direct API call.
                return None
            revision_gate = verify_variant_revision_for_planning(selected)
            if revision_gate.get("ok") is not True:
                return None
            for variant in project["variants"]:
                variant["selected"] = variant.get("id") == variant_id
            project["selected_variant_id"] = variant_id
            project.pop("design_base_variant_id", None)
            if not self._transition(project, "ready_for_planning"):
                return None
            project["updated_at"] = utc_now()
            project["events"].append(self._event("variant_selected", f"已选择方案：{selected['name']}"))
            self._save()
            return deepcopy(project)

    def begin_design_iteration(
        self, project_id: str, parent_variant_id: str
    ) -> dict[str, Any] | None:
        """Return a selected candidate to the design stage without planning it."""
        with self._lock:
            project = self._projects.get(project_id)
            if project is None or project.get("deleted_at") or project.get("status") not in {
                "clarifying", "ready_for_design",
                "designing", "ready_for_planning", "planning_failed",
                "execution_failed", "completed", "cancelled",
            }:
                return None
            parent = next(
                (item for item in project["variants"]
                 if item.get("id") == parent_variant_id),
                None,
            )
            if not candidate_is_accepted(parent):
                return None
            previous_status = str(project.get("status") or "")
            if not self._transition(project, "designing"):
                return None
            if previous_status in {
                "planning_failed", "execution_failed", "completed", "cancelled",
            }:
                archived = {
                    "closed_at": utc_now(),
                    "status": previous_status,
                    "parent_variant_id": parent_variant_id,
                }
                for key in ("planning", "execution", "acceptance_report"):
                    value = project.pop(key, None)
                    if isinstance(value, dict):
                        archived[key] = deepcopy(value)
                history = project.setdefault("iteration_history", [])
                if isinstance(history, list):
                    history.append(archived)
                    if len(history) > 20:
                        del history[:-20]
            for variant in project["variants"]:
                variant["selected"] = False
            project.pop("selected_variant_id", None)
            project["design_base_variant_id"] = parent_variant_id
            geometries = parent.get("geometries")
            if isinstance(geometries, list) and geometries:
                instance_ids = {
                    item.get("template_instance") for item in geometries
                    if isinstance(item, dict)
                    and isinstance(item.get("template_instance"), int)
                    and item["template_instance"] > 0
                }
                if len(instance_ids) > 0 and all(
                    isinstance(item, dict)
                    and item.get("template_instance") in instance_ids
                    for item in geometries
                ):
                    declared_quantity = parent.get("expected_quantity")
                    if isinstance(declared_quantity, int) and declared_quantity > 0:
                        project.setdefault("requirements", {})["quantity"] = declared_quantity
            project["updated_at"] = utc_now()
            project["events"].append(self._event(
                "design_iteration_started",
                f"以方案 {parent.get('name') or parent_variant_id} 开始新一轮优化",
            ))
            self._save()
            return deepcopy(project)

    def set_planning(self, project_id: str, planning: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            project = self._projects.get(project_id)
            if project is None or project.get("deleted_at"):
                return None
            if project.get("planning") == planning:
                return deepcopy(project)
            if not self._apply_planning(project, planning):
                return None
            self._save()
            return deepcopy(project)

    def set_planning_with_partition(
        self,
        project_id: str,
        planning: dict[str, Any],
        partition_update: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Persist planning and its segment state in one project snapshot."""
        with self._lock:
            project = self._projects.get(project_id)
            if project is None or project.get("deleted_at"):
                return None
            before = deepcopy(project)
            try:
                if isinstance(partition_update, dict):
                    update = deepcopy(partition_update)
                    updates = update.pop("updates", {})
                    if not self._apply_variant_partition_segment(
                        project,
                        str(update["variant_id"]),
                        str(update["zone_id"]),
                        str(update["segment_id"]),
                        str(update["status"]),
                        **(updates if isinstance(updates, dict) else {}),
                    ):
                        self._projects[project_id] = before
                        return None
                if not self._apply_planning(project, planning):
                    self._projects[project_id] = before
                    return None
                self._save()
                return deepcopy(project)
            except Exception:
                self._projects[project_id] = before
                raise

    def _apply_planning(
        self, project: dict[str, Any], planning: dict[str, Any]
    ) -> bool:
        """Apply planning state in memory for a larger atomic unit of work."""
        stage = str(planning.get("stage", ""))
        target_status = "planning"
        if stage == "ready" and (planning.get("validation") or {}).get("ok") is True:
            target_status = "planning_ready"
        elif stage in {"planning_failed", "failed", "cancelled"} or planning.get("error"):
            target_status = "planning_failed"
        if not self._transition(project, target_status):
            return False
        project["planning"] = deepcopy(planning)
        project["updated_at"] = utc_now()
        project["events"].append(
            self._event("planning_updated", f"规划阶段：{stage or 'unknown'}")
        )
        return True

    def set_execution(self, project_id: str, execution: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            project = self._projects.get(project_id)
            if project is None or project.get("deleted_at"):
                return None
            if project.get("execution") == execution:
                return deepcopy(project)
            stage = str(execution.get("stage", ""))
            target_status = {
                "pending_confirmation": "pending_execution",
                "confirmation_cancelled": "planning_ready",
                "executing": "executing",
                "paused": "paused",
                "completed": "completed",
                "zone_completed": "ready_for_planning",
                "segment_completed": "ready_for_planning",
                "cancelled": "cancelled",
                "failed": "execution_failed",
                "interrupted": "execution_failed",
            }.get(stage, project["status"])
            if target_status != project["status"] and not self._transition(project, target_status):
                return None
            project["execution"] = deepcopy(execution)
            project["updated_at"] = utc_now()
            project["events"].append(self._event("execution_updated", f"执行阶段：{stage or 'unknown'}"))
            self._save()
            return deepcopy(project)

    def set_report(self, project_id: str, report: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            project = self._projects.get(project_id)
            if project is None or project.get("deleted_at"):
                return None
            project["acceptance_report"] = deepcopy(report)
            project["updated_at"] = utc_now()
            project["events"].append(self._event("report_generated", "项目验收报告已生成"))
            self._save()
            return deepcopy(project)

    def confirm_recovery_inspection(self, project_id: str) -> dict[str, Any] | None:
        with self._lock:
            project = self._projects.get(project_id)
            if project is None or project.get("deleted_at") or project.get("status") != "planning_ready":
                return None
            planning = project.get("planning")
            recovery = planning.get("recovery") if isinstance(planning, dict) else None
            if not isinstance(recovery, dict) or recovery.get("manual_inspection_required") is not True:
                return None
            recovery["manual_inspection_confirmed"] = True
            recovery["manual_inspection_confirmed_at"] = utc_now()
            project["updated_at"] = utc_now()
            project["events"].append(self._event("recovery_inspection_confirmed", "用户已确认检查疑似部分喷墨段"))
            self._save()
            return deepcopy(project)

    def find_by_action(self, action_id: str) -> dict[str, Any] | None:
        with self._lock:
            project = next((item for item in self._projects.values()
                            if (item.get("execution") or {}).get("action_id") == action_id), None)
            return deepcopy(project) if project is not None else None

    def _load(self) -> None:
        if self._database_enabled:
            stored = xline_database.load_payloads("projects", "project_id")
            if stored:
                self._projects = {
                    str(item["id"]): item for item in stored
                    if isinstance(item, dict) and isinstance(item.get("id"), str)
                }
                return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            projects = payload.get("projects", [])
            if isinstance(projects, list):
                self._projects = {str(item["id"]): item for item in projects
                                  if isinstance(item, dict) and isinstance(item.get("id"), str)}
                if self._database_enabled:
                    for item in self._projects.values():
                        xline_database.save_project(item)
        except (OSError, json.JSONDecodeError, TypeError):
            self._projects = {}

    def _save(self) -> None:
        try:
            from .cad_requirement_contract import project_requirement_state
            for project in self._projects.values():
                project['requirement_state'] = project_requirement_state(project)
            if self._database_enabled:
                xline_database.save_project_snapshots(list(self._projects.values()))
            else:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.path.with_suffix(self.path.suffix + ".tmp")
                temporary.write_text(json.dumps(
                    {"schema_version": "1.0", "projects": list(self._projects.values())},
                    ensure_ascii=False, indent=2), encoding="utf-8")
                os.replace(temporary, self.path)
                try:
                    os.chmod(self.path, 0o600)
                except OSError:
                    pass
        except Exception:
            # A failed durable write must not leave a newer in-memory truth.
            self._projects = deepcopy(getattr(self, '_durable_projects', {}))
            raise
        self._durable_projects = deepcopy(self._projects)

    @staticmethod
    def _merge(current: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
        merged = deepcopy(current)
        merged.update(deepcopy(updates))
        return merged

    @staticmethod
    def _clean_missing(values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))

    @staticmethod
    def _normalize_source_drawing(value: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        raw_geometries = value.get("geometries", value.get("lines"))
        if not isinstance(raw_geometries, list):
            return None
        geometries = [deepcopy(item) for item in raw_geometries if isinstance(item, dict)]
        if not geometries:
            return None
        normalized = {
            "file_name": str(value.get("file_name") or "").strip(),
            "geometries": geometries,
        }
        if isinstance(value.get("logical_objects"), list):
            normalized["logical_objects"] = deepcopy(value["logical_objects"])
        if isinstance(value.get("topology"), dict):
            normalized["topology"] = deepcopy(value["topology"])
        if value.get("source_format"):
            normalized["source_format"] = str(value["source_format"])
        if isinstance(value.get("cad_analysis"), dict):
            normalized["cad_analysis"] = deepcopy(value["cad_analysis"])
        return normalized

    @staticmethod
    def _event(event_type: str, message: str) -> dict[str, str]:
        return {"at": utc_now(), "type": event_type, "message": message}

    @staticmethod
    def _transition(project: dict[str, Any], target: str) -> bool:
        current = str(project.get("status", "draft"))
        if target == current:
            return True
        if target not in ALLOWED_TRANSITIONS.get(current, set()):
            return False
        project["status"] = target
        return True


_project_store = CreativeProjectStore()

def get_creative_project_store() -> CreativeProjectStore:
    """Return the current process-wide project repository.

    Callers use this accessor at execution boundaries so test isolates and
    runtime reconfiguration cannot leave stale imported store references.
    """
    return _project_store
