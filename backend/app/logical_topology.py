"""Validation and revision evidence for logical CAD objects and topology."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from typing import Any


def logical_graph_fingerprint(
    logical_objects: list[dict[str, Any]] | None,
    topology: dict[str, Any] | None,
) -> str:
    payload = {
        "logical_objects": logical_objects or [],
        "topology": _normalized_topology(topology),
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_logical_object_graph(
    geometries: list[dict[str, Any]],
    logical_objects: list[dict[str, Any]] | None,
    topology: dict[str, Any] | None,
) -> dict[str, Any]:
    """Validate cross references that Pydantic alone cannot preserve over revisions."""
    objects = logical_objects or []
    graph_topology = _normalized_topology(topology)
    errors: list[dict[str, Any]] = []
    geometry_ids = [_positive_int(item.get("id")) for item in geometries]
    known_geometry_ids = {value for value in geometry_ids if value is not None}
    if len(known_geometry_ids) != len(geometries):
        errors.append(_error("invalid_geometry_ids", "图纸包含缺失、重复或无效的几何 ID"))

    object_ids = [str(item.get("object_id") or "") for item in objects]
    if any(not value for value in object_ids) or len(set(object_ids)) != len(object_ids):
        errors.append(_error("invalid_object_ids", "逻辑对象 ID 缺失或重复"))
    known_object_ids = {value for value in object_ids if value}
    objects_by_id = {
        str(item.get("object_id") or ""): item for item in objects
        if str(item.get("object_id") or "")
    }
    owners: dict[int, set[str]] = {}
    assembly_labels: dict[str, str] = {}
    for item in objects:
        object_id = str(item.get("object_id") or "")
        assembly_id=item.get("assembly_id")
        if assembly_id:
            label=item.get("assembly_label")
            if (not isinstance(assembly_id,str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}",assembly_id)
                or not isinstance(label,str) or not label.strip()
                or (assembly_id in assembly_labels and assembly_labels[assembly_id]!=label)):
                errors.append(_error("invalid_assembly", "整体归属ID或名称无效、冲突",object_id=object_id))
            else:
                assembly_labels[assembly_id]=label
        refs = item.get("geometry_refs")
        if not isinstance(refs, list) or not refs:
            errors.append(_error(
                "missing_geometry_refs", f"逻辑对象 {object_id or '未命名对象'} 没有关联图元"
            ))
            continue
        normalized_refs = [_positive_int(value) for value in refs]
        if any(value is None for value in normalized_refs) or len(set(normalized_refs)) != len(normalized_refs):
            errors.append(_error("invalid_geometry_refs", f"逻辑对象 {object_id} 的图元引用无效"))
            continue
        missing = sorted(set(normalized_refs) - known_geometry_ids)
        if missing:
            errors.append(_error(
                "dangling_geometry_refs",
                f"逻辑对象 {object_id} 引用了不存在的图元",
                object_id=object_id, geometry_ids=missing,
            ))
        for geometry_id in normalized_refs:
            owners.setdefault(int(geometry_id), set()).add(object_id)

    declared_shared: dict[int, set[str]] = {}
    for item in graph_topology["shared_geometries"]:
        geometry_id = _positive_int(item.get("geometry_id"))
        object_refs = item.get("object_ids")
        object_refs = [str(value) for value in object_refs] if isinstance(object_refs, list) else []
        if geometry_id is None or geometry_id not in known_geometry_ids:
            errors.append(_error(
                "dangling_shared_geometry", "共享拓扑引用了不存在的图元",
                geometry_ids=[geometry_id] if geometry_id is not None else [],
            ))
            continue
        if geometry_id in declared_shared:
            errors.append(_error(
                "duplicate_shared_declaration", f"共享图元 {geometry_id} 被重复声明",
                geometry_ids=[geometry_id],
            ))
            continue
        missing_objects = sorted(set(object_refs) - known_object_ids)
        if len(set(object_refs)) < 2 or missing_objects:
            errors.append(_error(
                "invalid_shared_owners", f"共享图元 {geometry_id} 的归属对象无效",
                geometry_ids=[geometry_id], object_ids=missing_objects,
            ))
        declared_shared[geometry_id] = set(object_refs)
        if declared_shared[geometry_id] != owners.get(geometry_id, set()):
            errors.append(_error(
                "shared_ownership_mismatch", f"共享图元 {geometry_id} 的声明与对象引用不一致",
                geometry_ids=[geometry_id],
                object_ids=sorted(declared_shared[geometry_id] ^ owners.get(geometry_id, set())),
            ))

    undeclared = sorted(
        geometry_id for geometry_id, object_owners in owners.items()
        if len(object_owners) > 1 and geometry_id not in declared_shared
    )
    if undeclared:
        errors.append(_error(
            "missing_shared_declaration", "多个对象共用的图元缺少共享拓扑声明",
            geometry_ids=undeclared,
        ))

    for relation in graph_topology["relations"]:
        endpoints = {
            str(relation.get("source_object_id") or ""),
            str(relation.get("target_object_id") or ""),
        }
        missing = sorted(value for value in endpoints if value not in known_object_ids)
        if "" in endpoints or len(endpoints) != 2 or missing:
            errors.append(_error(
                "invalid_topology_relation", "对象拓扑关系的端点不存在或相同",
                object_ids=missing,
            ))
            continue
        source_id = str(relation.get("source_object_id"))
        target_id = str(relation.get("target_object_id"))
        spatial_check = _validate_spatial_relation(
            objects_by_id[source_id], objects_by_id[target_id],
            str(relation.get("relation") or ""),
        )
        if spatial_check is False:
            errors.append(_error(
                "topology_relation_mismatch",
                f"对象关系 {source_id} -> {target_id} 与当前空间位置不一致",
                object_ids=[source_id, target_id],
                relation=str(relation.get("relation") or ""),
            ))

    return {
        "schema": "cad.logical-validation.v1",
        "verified": not errors,
        "errors": errors,
        "object_count": len(objects),
        "shared_geometry_count": len(graph_topology["shared_geometries"]),
        "relation_count": len(graph_topology["relations"]),
        "fingerprint": logical_graph_fingerprint(objects, graph_topology),
    }


def build_confirmed_instance_graph(
    geometries: list[dict[str, Any]],
    groups: list[dict[str, Any]],
    *,
    object_type: str = "drawing",
) -> dict[str, Any]:
    """Build authoritative logical objects from user-confirmed groups."""
    geometry_by_id = {
        value: item for item in geometries
        if (value := _positive_int(item.get("id"))) is not None
    }
    objects: list[dict[str, Any]] = []
    for index, group in enumerate(groups, 1):
        instance_id = _positive_int(group.get("instance_id")) or index
        refs = [
            value for raw in group.get("geometry_ids") or []
            if (value := _positive_int(raw)) is not None and value in geometry_by_id
        ]
        bounds = _geometry_bounds([geometry_by_id[value] for value in refs])
        objects.append({
            "object_id": f"{object_type}-{instance_id}",
            "identity_key": f"{object_type}-{instance_id}",
            "object_type": object_type,
            "label": str(group.get("label") or f"实例 {instance_id}"),
            "geometry_refs": refs,
            **({"bounds": bounds} if bounds is not None else {}),
            "confirmed": True,
            "confidence": 1.0,
        })
    return {
        "logical_objects": objects,
        "topology": {
            "schema_version": "cad.topology.v1",
            "shared_geometries": [],
            "relations": [],
        },
    }


def build_logical_object_diff(
    source_logical_objects: list[dict[str, Any]] | None,
    target_logical_objects: list[dict[str, Any]] | None,
    source_topology: dict[str, Any] | None,
    target_topology: dict[str, Any] | None,
) -> dict[str, Any]:
    normalized_source,_=preserve_logical_graph(source_logical_objects,{})
    normalized_target,_=preserve_logical_graph(target_logical_objects,{})
    source = {str(item.get("object_id")): item for item in normalized_source}
    target = {str(item.get("object_id")): item for item in normalized_target}
    source_ids, target_ids = set(source), set(target)
    modified = sorted(
        object_id for object_id in source_ids & target_ids
        if _canonical(source[object_id]) != _canonical(target[object_id])
    )
    source_shared = _shared_map(source_topology)
    target_shared = _shared_map(target_topology)
    shared_changes = sorted(
        geometry_id for geometry_id in set(source_shared) | set(target_shared)
        if source_shared.get(geometry_id) != target_shared.get(geometry_id)
    )
    source_relations = {
        _canonical(item) for item in _normalized_topology(source_topology)["relations"]
    }
    target_relations = {
        _canonical(item) for item in _normalized_topology(target_topology)["relations"]
    }
    return {
        "schema": "cad.logical-diff.v1",
        "added_object_ids": sorted(target_ids - source_ids),
        "removed_object_ids": sorted(source_ids - target_ids),
        "modified_object_ids": modified,
        "shared_geometry_changes": shared_changes,
        "added_relations": [
            json.loads(value) for value in sorted(target_relations - source_relations)
        ],
        "removed_relations": [
            json.loads(value) for value in sorted(source_relations - target_relations)
        ],
    }


def validate_logical_object_continuity(
    source_geometries: list[dict[str, Any]],
    target_geometries: list[dict[str, Any]],
    source_logical_objects: list[dict[str, Any]] | None,
    target_logical_objects: list[dict[str, Any]] | None,
    source_topology: dict[str, Any] | None,
    target_topology: dict[str, Any] | None,
    *,
    target_object_ids: list[str] | None = None,
    edit_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_validation = validate_logical_object_graph(
        source_geometries, source_logical_objects, source_topology
    )
    target_validation = validate_logical_object_graph(
        target_geometries, target_logical_objects, target_topology
    )
    difference = build_logical_object_diff(
        source_logical_objects, target_logical_objects, source_topology, target_topology
    )
    errors = list(target_validation["errors"])
    source_by_id={str(o.get("object_id")):o for o in source_logical_objects or []}
    for obj in target_logical_objects or []:
        original=source_by_id.get(str(obj.get("object_id")))
        if original and original.get("assembly_id") and (
            original.get("assembly_id")!=obj.get("assembly_id") or original.get("assembly_label")!=obj.get("assembly_label")):
            errors.append(_error("assembly_ownership_drift", "修改不能静默改写部件的整体归属",object_id=obj.get("object_id")))
    allowed = set(target_object_ids or [])
    if source_validation["verified"] and source_logical_objects:
        changed = set(difference["modified_object_ids"])
        changed.update(difference["removed_object_ids"])
        unexpected = sorted(changed - allowed) if target_object_ids is not None else sorted(changed)
        if unexpected:
            errors.append(_error(
                "non_target_object_drift", "非目标逻辑对象的定义发生了变化",
                object_ids=unexpected,
            ))
        if difference["added_object_ids"] and target_object_ids is None:
            errors.append(_error(
                "unexpected_object_addition", "修改过程中意外增加了逻辑对象",
                object_ids=difference["added_object_ids"],
            ))
        declared_split = (
            isinstance(edit_contract, dict)
            and edit_contract.get("operation") == "translate"
            and (edit_contract.get("parameters") or {}).get("boundary_policy") == "split_shared"
        )
        if difference["shared_geometry_changes"] and not declared_split:
            errors.append(_error(
                "shared_topology_drift", "共享边界归属在修改过程中发生了变化",
                geometry_ids=difference["shared_geometry_changes"],
            ))
        changed_relations = (
            difference["added_relations"] + difference["removed_relations"]
        )
        unexpected_relations = [
            relation for relation in changed_relations
            if not allowed.intersection({
                str(relation.get("source_object_id") or ""),
                str(relation.get("target_object_id") or ""),
            })
        ]
        if unexpected_relations:
            errors.append(_error(
                "topology_relation_drift", "对象拓扑关系在修改过程中被静默改写",
                relations=unexpected_relations,
            ))
        source_geometry_ids = {
            value for item in source_geometries
            if (value := _positive_int(item.get("id"))) is not None
        }
        target_owners = {
            _positive_int(geometry_id)
            for item in target_logical_objects or []
            for geometry_id in item.get("geometry_refs") or []
        }
        unowned_added = sorted(
            value for item in target_geometries
            if (value := _positive_int(item.get("id"))) is not None
            and value not in source_geometry_ids
            and value not in target_owners
        )
        if unowned_added:
            errors.append(_error(
                "unowned_added_geometry", "新增图元没有归属到新的逻辑对象",
                geometry_ids=unowned_added,
            ))
    return {
        "schema": "cad.logical-continuity.v1",
        "verified": source_validation["verified"] and not errors,
        "errors": errors,
        "source_validation": source_validation,
        "target_validation": target_validation,
        "diff": difference,
    }


def preserve_logical_graph(
    logical_objects: list[dict[str, Any]] | None,
    topology: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    objects = deepcopy(logical_objects or [])
    for item in objects:
        if not isinstance(item, dict):
            continue
        object_id = str(item.get("object_id") or "").strip()
        if object_id:
            item.setdefault("identity_key", object_id)
    return objects, deepcopy(_normalized_topology(topology))


def _adopt_new_template_instances(
    source_geometries: list[dict[str, Any]],
    target_geometries: list[dict[str, Any]],
    objects: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Create logical objects for added template instances (no edit contract).

    Composite additions such as "在篮球场的上下方各添加一个羽毛球场" add
    whole template instances.  Each added geometry must be owned by a logical
    object or the revision contract rejects the candidate; group unowned
    additions by template_instance and adopt them.
    """
    source_ids = {
        value for item in source_geometries
        if (value := _positive_int(item.get("id"))) is not None
    }
    owned_ids = {
        value for item in objects
        for raw in item.get("geometry_refs") or []
        if (value := _positive_int(raw)) is not None
    }
    grouped: dict[int, list[dict[str, Any]]] = {}
    for item in target_geometries:
        geometry_id = _positive_int(item.get("id"))
        instance = _positive_int(item.get("template_instance"))
        if (
            geometry_id is None
            or geometry_id in source_ids
            or geometry_id in owned_ids
            or instance is None
        ):
            continue
        grouped.setdefault(instance, []).append(item)
    if not grouped:
        return objects
    adopted = list(objects)
    existing_ids = {str(item.get("object_id") or "") for item in objects}
    for instance in sorted(grouped):
        items = grouped[instance]
        base = next(
            (
                str(item.get("template_type") or "").strip()
                for item in items
                if item.get("template_type")
            ),
            "drawing",
        ) or "drawing"
        object_id = f"{base}-{instance}"
        suffix = 2
        while object_id in existing_ids:
            object_id = f"{base}-{instance}-{suffix}"
            suffix += 1
        existing_ids.add(object_id)
        refs = sorted(
            value for value in (
                _positive_int(item.get("id")) for item in items
            ) if value is not None
        )
        bounds = _geometry_bounds(items)
        adopted.append({
            "object_id": object_id,
            "identity_key": object_id,
            "object_type": base,
            "label": f"{base} {instance}",
            "geometry_refs": refs,
            **({"bounds": bounds} if bounds else {}),
            "confirmed": True,
            "confidence": 1.0,
        })
    return adopted


def evolve_logical_graph_for_edit(
    source_geometries: list[dict[str, Any]],
    target_geometries: list[dict[str, Any]],
    logical_objects: list[dict[str, Any]] | None,
    topology: dict[str, Any] | None,
    edit_contract: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Carry stable object identity through deterministic quantity edits."""
    objects, graph_topology = preserve_logical_graph(logical_objects, topology)
    if not objects:
        return objects, graph_topology
    if not isinstance(edit_contract, dict):
        objects = _adopt_new_template_instances(
            source_geometries, target_geometries, objects
        )
    objects = _refresh_changed_object_bounds(
        source_geometries, target_geometries, objects
    )
    if not isinstance(edit_contract, dict):
        return objects, graph_topology
    operation = str(edit_contract.get("operation") or "")
    source_ids = {
        value for item in source_geometries
        if (value := _positive_int(item.get("id"))) is not None
    }
    target_ids = {
        value for item in target_geometries
        if (value := _positive_int(item.get("id"))) is not None
    }
    if operation in {"delete", "retain"}:
        kept: list[dict[str, Any]] = []
        for item in objects:
            refs = [
                value for raw in item.get("geometry_refs") or []
                if (value := _positive_int(raw)) is not None and value in target_ids
            ]
            if refs:
                updated = deepcopy(item)
                updated["geometry_refs"] = refs
                kept.append(updated)
        return kept, _prune_topology(graph_topology, kept, target_ids)
    parameters = edit_contract.get("parameters") or {}
    selected_refs=list((edit_contract.get('target') or {}).get('geometry_ids') or [])
    created_refs=list(parameters.get('created_geometry_ids') or [])
    if operation in {'duplicate','mirror','offset','array'} and selected_refs and created_refs:
        if len(created_refs)%len(selected_refs):return objects,graph_topology
        selected_set=set(selected_refs);clones=[]
        for start in range(0,len(created_refs),len(selected_refs)):
            mapping=dict(zip(sorted(selected_refs),created_refs[start:start+len(selected_refs)]))
            suffix=f".copy.{created_refs[start]}";object_mapping={}
            for obj in objects:
                refs=list(obj.get('geometry_refs') or [])
                if not refs or not set(refs)<=selected_set:continue
                clone=deepcopy(obj);oldid=clone['object_id'];clone['object_id']=oldid+suffix
                object_mapping[oldid]=clone['object_id'];clone['identity_key']=clone['object_id']
                clone['derived_from_object_id']=oldid;clone['geometry_refs']=[mapping[i] for i in refs]
                clone['label']=str(clone.get('label') or '图形')+' 副本'
                clone['assembly_id']=str(clone.get('assembly_id') or oldid)+suffix
                clone['assembly_label']=str(clone.get('assembly_label') or obj.get('label') or '图形')+' 副本'
                clones.append(clone)
            for relation in list(graph_topology.get('relations') or []):
                if relation.get('source_object_id') in object_mapping and relation.get('target_object_id') in object_mapping:
                    graph_topology.setdefault('relations',[]).append({**deepcopy(relation),
                        'source_object_id':object_mapping[relation['source_object_id']],
                        'target_object_id':object_mapping[relation['target_object_id']]})
            for shared in list(graph_topology.get('shared_geometries') or []):
                if shared.get('geometry_id') in mapping and all(i in object_mapping for i in shared.get('object_ids') or []):
                    graph_topology.setdefault('shared_geometries',[]).append({**deepcopy(shared),
                        'geometry_id':mapping[shared['geometry_id']],
                        'object_ids':[object_mapping[i] for i in shared['object_ids']]})
        objects=_refresh_changed_object_bounds(source_geometries,target_geometries,objects+clones)
        return objects,graph_topology
    if operation == "translate" and parameters.get("boundary_policy") == "split_shared":
        target = edit_contract.get("target") or {}
        target_object_ids = [
            str(value) for value in [target.get("object_id"), *(target.get("object_ids") or [])]
            if value
        ]
        shared_ids = {
            value for raw in parameters.get("shared_geometry_ids", [])
            if (value := _positive_int(raw)) is not None
        }
        created_ids = [
            value for raw in parameters.get("created_geometry_ids", [])
            if (value := _positive_int(raw)) is not None
        ]
        if target_object_ids and shared_ids and len(created_ids) == len(shared_ids):
            id_map = dict(zip(sorted(shared_ids), sorted(created_ids)))
            target_set = set(target_object_ids)
            updated_objects: list[dict[str, Any]] = []
            for item in objects:
                updated = deepcopy(item)
                object_id = str(updated.get("object_id") or "")
                refs = [_positive_int(value) for value in updated.get("geometry_refs") or []]
                if object_id in target_set:
                    updated["geometry_refs"] = [
                        id_map.get(value, value) for value in refs if value is not None
                    ]
                updated_objects.append(updated)
            old_shared = []
            new_shared = []
            for item in graph_topology.get("shared_geometries") or []:
                geometry_id = _positive_int(item.get("geometry_id"))
                owners = {str(value) for value in item.get("object_ids") or []}
                if geometry_id not in id_map:
                    old_shared.append(deepcopy(item))
                    continue
                remaining = sorted(owners - target_set)
                if len(remaining) > 1:
                    old_shared.append({**deepcopy(item), "object_ids": remaining})
                moved = sorted(owners & target_set)
                if len(moved) > 1:
                    new_shared.append({
                        **deepcopy(item), "geometry_id": id_map[geometry_id],
                        "object_ids": moved,
                    })
            graph_topology["shared_geometries"] = old_shared + new_shared
            objects = _refresh_changed_object_bounds(
                source_geometries, target_geometries, updated_objects
            )
            objects_by_id = {
                str(item.get("object_id") or ""): item for item in objects
            }
            graph_topology["relations"] = [
                deepcopy(relation)
                for relation in graph_topology.get("relations") or []
                if (
                    str(relation.get("source_object_id") or "") in objects_by_id
                    and str(relation.get("target_object_id") or "") in objects_by_id
                    and _validate_spatial_relation(
                        objects_by_id[str(relation.get("source_object_id"))],
                        objects_by_id[str(relation.get("target_object_id"))],
                        str(relation.get("relation") or ""),
                    ) is not False
                )
            ]
            return objects, graph_topology
    if operation in {"mirror", "offset", "array", "add_template", "rearrange_layout"}:
        objects = _adopt_new_template_instances(
            source_geometries, target_geometries, objects
        )
        objects = _refresh_changed_object_bounds(
            source_geometries, target_geometries, objects
        )
        return objects, graph_topology
    if operation != "duplicate":
        return objects, graph_topology

    target = edit_contract.get("target")
    created_instance = _positive_int(edit_contract.get("created_instance_id"))
    instance_ids = target.get("instance_ids") if isinstance(target, dict) else None
    if created_instance is None or not isinstance(instance_ids, list) or len(instance_ids) != 1:
        return objects, graph_topology
    source_instance = _positive_int(instance_ids[0])
    source_instance_geometries = [
        item for item in source_geometries
        if _positive_int(item.get("template_instance")) == source_instance
    ]
    new_geometries = [
        item for item in target_geometries
        if _positive_int(item.get("template_instance")) == created_instance
        and _positive_int(item.get("id")) not in source_ids
    ]
    if not source_instance_geometries or len(source_instance_geometries) != len(new_geometries):
        return objects, graph_topology
    id_map = {
        int(source_item["id"]): int(target_item["id"])
        for source_item, target_item in zip(source_instance_geometries, new_geometries)
    }
    existing_ids = {str(item.get("object_id") or "") for item in objects}
    clones: list[dict[str, Any]] = []
    assembly_copies={}
    existing_assemblies={str(item["assembly_id"]) for item in objects if item.get("assembly_id")}
    for item in objects:
        refs = [_positive_int(value) for value in item.get("geometry_refs") or []]
        if not refs or any(value not in id_map for value in refs):
            continue
        clone = deepcopy(item)
        source_object_id = str(item.get("object_id") or "")
        clone["object_id"] = _copied_object_id(
            source_object_id or "object", created_instance, existing_ids
        )
        existing_ids.add(clone["object_id"])
        clone["identity_key"] = clone["object_id"]
        clone["derived_from_object_id"] = source_object_id or None
        clone["label"] = _copied_label(str(item.get("label") or "图形"), created_instance)
        if item.get("assembly_id"):
            original_assembly=str(item["assembly_id"])
            if original_assembly not in assembly_copies:
                assembly_copies[original_assembly]=_copied_object_id(original_assembly,created_instance,existing_assemblies)
                existing_assemblies.add(assembly_copies[original_assembly])
            clone["assembly_id"]=assembly_copies[original_assembly]
            clone["assembly_label"]=_copied_label(str(item.get("assembly_label") or "图形"),created_instance)
        clone["geometry_refs"] = [id_map[int(value)] for value in refs]
        bounds = _geometry_bounds([
            geometry for geometry in new_geometries
            if _positive_int(geometry.get("id")) in clone["geometry_refs"]
        ])
        if bounds is not None:
            clone["bounds"] = bounds
        clones.append(clone)
    return objects + clones, graph_topology


def logical_object_ids_for_edit(
    source_geometries: list[dict[str, Any]],
    logical_objects: list[dict[str, Any]] | None,
    edit_contract: dict[str, Any] | None,
) -> list[str] | None:
    if not isinstance(edit_contract, dict):
        source_by_id = {
            value: item for item in source_geometries
            if (value := _positive_int(item.get("id"))) is not None
        }
        geometry_ids = set(source_by_id)
        return sorted(
            str(item.get("object_id")) for item in logical_objects or []
            if geometry_ids.intersection({
                value for raw in item.get("geometry_refs") or []
                if (value := _positive_int(raw)) is not None
            })
        )
    if edit_contract.get("operation") == "retain":
        return sorted(
            str(item.get("object_id")) for item in logical_objects or []
            if str(item.get("object_id") or "")
        )
    if edit_contract.get("operation") == "add_constrained":
        target = edit_contract.get("target") or {}
        parameters = edit_contract.get("parameters") or {}
        return sorted({
            str(value)
            for value in [
                target.get("object_id"),
                *(target.get("object_ids") or []),
                *(parameters.get("created_object_ids") or []),
            ]
            if value
        })
    if edit_contract.get("operation") == "add_template":
        target = edit_contract.get("target") or {}
        parameters = edit_contract.get("parameters") or {}
        geometry_ids = {
            value for raw in [
                *(target.get("geometry_ids") or []),
                *(parameters.get("created_geometry_ids") or []),
            ]
            if (value := _positive_int(raw)) is not None
        }
        return sorted(
            str(item.get("object_id")) for item in logical_objects or []
            if geometry_ids.intersection({
                value for raw in item.get("geometry_refs") or []
                if (value := _positive_int(raw)) is not None
            })
        )
    target = edit_contract.get("target")
    if not isinstance(target, dict):
        return None
    geometry_ids: set[int] = set()
    if target.get("scope") in {"geometry", "logical_object"}:
        geometry_ids = {
            value for raw in target.get("geometry_ids") or []
            if (value := _positive_int(raw)) is not None
        }
    elif target.get("scope") == "instance":
        instances = {
            value for raw in target.get("instance_ids") or []
            if (value := _positive_int(raw)) is not None
        }
        geometry_ids = {
            int(item["id"]) for item in source_geometries
            if _positive_int(item.get("template_instance")) in instances
            and _positive_int(item.get("id")) is not None
        }
    explicit_object_ids = {
        str(value) for value in [target.get("object_id"), *(target.get("object_ids") or [])]
        if value
    }
    if target.get("scope") == "logical_object" and explicit_object_ids:
        return sorted(explicit_object_ids)
    return sorted(
        str(item.get("object_id")) for item in logical_objects or []
        if geometry_ids.intersection({
            value for raw in item.get("geometry_refs") or []
            if (value := _positive_int(raw)) is not None
        })
    )


def _normalized_topology(topology: dict[str, Any] | None) -> dict[str, Any]:
    value = topology if isinstance(topology, dict) else {}
    return {
        "schema_version": "cad.topology.v1",
        "shared_geometries": deepcopy(value.get("shared_geometries") or []),
        "relations": deepcopy(value.get("relations") or []),
    }


def _prune_topology(
    topology: dict[str, Any], objects: list[dict[str, Any]], geometry_ids: set[int]
) -> dict[str, Any]:
    object_ids = {str(item.get("object_id") or "") for item in objects}
    owners = {
        geometry_id: {
            str(item.get("object_id")) for item in objects
            if geometry_id in {
                _positive_int(value) for value in item.get("geometry_refs") or []
            }
        }
        for geometry_id in geometry_ids
    }
    shared = []
    for item in topology.get("shared_geometries") or []:
        geometry_id = _positive_int(item.get("geometry_id"))
        if geometry_id in geometry_ids and len(owners.get(geometry_id, set())) > 1:
            updated = deepcopy(item)
            updated["object_ids"] = sorted(owners[geometry_id])
            shared.append(updated)
    relations = [
        deepcopy(item) for item in topology.get("relations") or []
        if str(item.get("source_object_id") or "") in object_ids
        and str(item.get("target_object_id") or "") in object_ids
    ]
    return {
        "schema_version": "cad.topology.v1",
        "shared_geometries": shared,
        "relations": relations,
    }


def _copied_object_id(source: str, instance: int, existing: set[str]) -> str:
    prefix = re.sub(r"-\d+$", "", source) or source
    candidate = f"{prefix}-{instance}"
    suffix = 2
    while candidate in existing:
        candidate = f"{prefix}-{instance}-copy-{suffix}"
        suffix += 1
    return candidate


def _copied_label(source: str, instance: int) -> str:
    if re.search(r"\d+$", source):
        return re.sub(r"\d+$", str(instance), source)
    return f"{source} {instance}"


def _geometry_bounds(geometries: list[dict[str, Any]]) -> dict[str, float] | None:
    points: list[tuple[float, float]] = []
    for item in geometries:
        for key in ("start", "end", "center", "position"):
            point = item.get(key)
            if isinstance(point, dict) and "x" in point and "y" in point:
                points.append((float(point["x"]), float(point["y"])))
        for point in item.get("vertices") or []:
            if isinstance(point, dict) and "x" in point and "y" in point:
                points.append((float(point["x"]), float(point["y"])))
        center = item.get("center")
        if not isinstance(center, dict) or "x" not in center or "y" not in center:
            continue
        try:
            center_x, center_y = float(center["x"]), float(center["y"])
            geometry_type = str(item.get("type") or "")
            if geometry_type in {"circle", "arc"}:
                radius_x = radius_y = abs(float(item.get("radius") or 0.0))
            elif geometry_type == "ellipse":
                axis = item.get("major_axis") or {}
                major_x = float(axis.get("x") or 0.0)
                major_y = float(axis.get("y") or 0.0)
                ratio = abs(float(item.get("ratio") or 0.0))
                minor_x, minor_y = -major_y * ratio, major_x * ratio
                radius_x = (major_x * major_x + minor_x * minor_x) ** 0.5
                radius_y = (major_y * major_y + minor_y * minor_y) ** 0.5
            else:
                continue
        except (TypeError, ValueError):
            continue
        points.extend([
            (center_x - radius_x, center_y - radius_y),
            (center_x + radius_x, center_y + radius_y),
        ])
    if not points:
        return None
    xs, ys = zip(*points)
    return {"min_x": min(xs), "min_y": min(ys), "max_x": max(xs), "max_y": max(ys)}


def _refresh_changed_object_bounds(
    source_geometries: list[dict[str, Any]],
    target_geometries: list[dict[str, Any]],
    objects: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    source_by_id = {
        value: item for item in source_geometries
        if (value := _positive_int(item.get("id"))) is not None
    }
    target_by_id = {
        value: item for item in target_geometries
        if (value := _positive_int(item.get("id"))) is not None
    }
    changed_ids = {
        geometry_id for geometry_id in set(source_by_id) & set(target_by_id)
        if _canonical(source_by_id[geometry_id]) != _canonical(target_by_id[geometry_id])
    }
    if not changed_ids:
        return objects
    refreshed: list[dict[str, Any]] = []
    for item in objects:
        updated = deepcopy(item)
        refs = {
            value for raw in item.get("geometry_refs") or []
            if (value := _positive_int(raw)) is not None
        }
        if refs.intersection(changed_ids):
            bounds = _geometry_bounds([
                target_by_id[geometry_id]
                for geometry_id in refs
                if geometry_id in target_by_id
            ])
            if bounds is not None and _bounds_are_reliable(item.get("bounds"), bounds):
                updated["bounds"] = bounds
        refreshed.append(updated)
    return refreshed


def _bounds_are_reliable(
    previous: Any, current: dict[str, float]
) -> bool:
    if not isinstance(previous, dict):
        return True
    try:
        previous_width = float(previous["max_x"]) - float(previous["min_x"])
        previous_height = float(previous["max_y"]) - float(previous["min_y"])
        current_width = float(current["max_x"]) - float(current["min_x"])
        current_height = float(current["max_y"]) - float(current["min_y"])
    except (KeyError, TypeError, ValueError):
        return False
    # Shared dividers do not describe the full 2D extent of a room or bay.
    return not (
        previous_width > 1e-6 and previous_height > 1e-6
        and (current_width <= 1e-6 or current_height <= 1e-6)
    )


def _validate_spatial_relation(
    source: dict[str, Any], target: dict[str, Any], relation: str,
    tolerance: float = 1.0,
) -> bool | None:
    source_bounds = _normalized_bounds(source.get("bounds"))
    target_bounds = _normalized_bounds(target.get("bounds"))
    if source_bounds is None or target_bounds is None:
        return None
    source_center = (
        (source_bounds[0] + source_bounds[2]) / 2,
        (source_bounds[1] + source_bounds[3]) / 2,
    )
    target_center = (
        (target_bounds[0] + target_bounds[2]) / 2,
        (target_bounds[1] + target_bounds[3]) / 2,
    )
    if relation == "left_of":
        return source_center[0] < target_center[0] - tolerance
    if relation == "right_of":
        return source_center[0] > target_center[0] + tolerance
    if relation == "above":
        return source_center[1] > target_center[1] + tolerance
    if relation == "below":
        return source_center[1] < target_center[1] - tolerance
    if relation == "contains":
        return _contains(source_bounds, target_bounds, tolerance)
    if relation == "inside":
        return _contains(target_bounds, source_bounds, tolerance)
    if relation == "intersects":
        return _overlap(source_bounds[0], source_bounds[2], target_bounds[0], target_bounds[2]) >= -tolerance and _overlap(
            source_bounds[1], source_bounds[3], target_bounds[1], target_bounds[3]
        ) >= -tolerance
    if relation == "adjacent":
        vertical_touch = (
            min(abs(source_bounds[2] - target_bounds[0]), abs(target_bounds[2] - source_bounds[0]))
            <= tolerance
            and _overlap(source_bounds[1], source_bounds[3], target_bounds[1], target_bounds[3])
            > tolerance
        )
        horizontal_touch = (
            min(abs(source_bounds[3] - target_bounds[1]), abs(target_bounds[3] - source_bounds[1]))
            <= tolerance
            and _overlap(source_bounds[0], source_bounds[2], target_bounds[0], target_bounds[2])
            > tolerance
        )
        return vertical_touch or horizontal_touch
    return None


def _normalized_bounds(value: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(value, dict):
        return None
    try:
        result = (
            float(value["min_x"]), float(value["min_y"]),
            float(value["max_x"]), float(value["max_y"]),
        )
    except (KeyError, TypeError, ValueError):
        return None
    if result[0] > result[2] or result[1] > result[3]:
        return None
    return result


def _contains(
    outer: tuple[float, float, float, float],
    inner: tuple[float, float, float, float],
    tolerance: float,
) -> bool:
    return (
        outer[0] <= inner[0] + tolerance
        and outer[1] <= inner[1] + tolerance
        and outer[2] >= inner[2] - tolerance
        and outer[3] >= inner[3] - tolerance
    )


def _overlap(left_min: float, left_max: float, right_min: float, right_max: float) -> float:
    return min(left_max, right_max) - max(left_min, right_min)


def _shared_map(topology: dict[str, Any] | None) -> dict[int, tuple[str, ...]]:
    result: dict[int, tuple[str, ...]] = {}
    for item in _normalized_topology(topology)["shared_geometries"]:
        geometry_id = _positive_int(item.get("geometry_id"))
        if geometry_id is not None:
            result[geometry_id] = tuple(sorted(str(value) for value in item.get("object_ids") or []))
    return result


def _positive_int(value: Any) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _error(code: str, message: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **details}
