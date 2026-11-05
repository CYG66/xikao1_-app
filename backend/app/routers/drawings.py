from __future__ import annotations

from fastapi import APIRouter
import asyncio
import json
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from fastapi import File, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from ..agent_skills import (
    analyze_geometry_topology,
    check_drawing_feasibility,
    layer_drawing_paths,
    snapshot_drawing,
    validate_drawing,
)
from ..drawing_store import cad_directory as _cad_directory
from ..drawing_store import build_path_preview_contract, preview_paths, resolve_drawing
from ..schemas import (
    DrawingJsonImportRequest,
    DrawingLayerRoleRequest,
    CadLayerFilteredImportRequest,
    DrawingSaveRequest,
    DrawingVersionRollbackRequest,
)
from ..state import robot_state
from ..drawing_versions import drawing_versions
from ..cad_import import (
    convert_dxf_to_dwg,
    convert_dwg_to_dxf,
    dwg_converter_status,
    export_dxf,
    inspect_dxf_layers,
    parse_dxf,
)
from ..cad_import import PATH_SEMANTIC_TO_ROLE, ROLE_TO_PATH_SEMANTIC
from ..image_drawing_import import (
    image_vectorizer_status,
    resolve_source_image,
    save_source_image,
    validate_image_upload,
    vectorize_image_to_drawing,
)

router = APIRouter()


BUILT_IN_DRAWINGS = {
    "test_pattern.json",
    "huanong_skeleton.json",
    "square_image.json",
}



BUILT_IN_PREVIEWS = {
    "test_pattern.json": [
        [[0.0, 0.0], [4.0, 0.0]],
        [[0.0, 0.6], [4.0, 0.6]],
        [[0.0, 1.2], [4.0, 1.2]],
    ],
    "huanong_skeleton.json": [
        [[0.0, 0.0], [1.5, 2.2], [3.0, 0.0]],
        [[0.75, 1.1], [2.25, 1.1]],
    ],
    "square_image.json": [
        [[0.0, 0.0], [3.0, 0.0], [3.0, 3.0], [0.0, 3.0], [0.0, 0.0]],
    ],
}



@router.get("/api/drawings")
def list_drawings() -> dict[str, object]:
    directory = _cad_directory()
    directory.mkdir(parents=True, exist_ok=True)
    return {"ok": True, "files": sorted(path.name for path in directory.glob("*.json"))}



@router.get("/api/drawings/versions")
def list_drawing_versions() -> dict[str, object]:
    return {"ok": True, "versions": drawing_versions.list()}



@router.get("/api/drawings/versions/{drawing_id}")
def drawing_version_history(drawing_id: str) -> dict[str, object]:
    return {"ok": True, "versions": drawing_versions.list(drawing_id)}



@router.post("/api/drawings/versions/{file_name}/rollback")
def rollback_drawing_version(
    file_name: str, command: DrawingVersionRollbackRequest
) -> dict[str, object]:
    if robot_state.mission_running:
        return {"ok": False, "message": "任务执行中不能回退图纸，请先停止任务。"}
    source = drawing_versions.find_by_file(file_name)
    if source is None:
        return {"ok": False, "message": "历史图纸版本不存在"}
    if command.project_id and source.get("project_id") not in {None, command.project_id}:
        return {"ok": False, "message": "图纸版本不属于当前项目"}
    source_payload = drawing_versions.payload(file_name)
    source_geometries = (
        source_payload.get("lines") if isinstance(source_payload, dict) else None
    )
    if not isinstance(source_geometries, list):
        return {"ok": False, "message": "历史图纸缺少可验证的几何数据"}
    source_validation = validate_drawing(source_geometries)
    if source_validation.get("ok") is not True:
        return {
            "ok": False,
            "message": "历史图纸未通过几何验证，未创建回退版本。",
            "validation": source_validation,
        }
    expected_snapshot = snapshot_drawing(source_geometries, "回退目标")
    version = drawing_versions.restore(
        file_name,
        _cad_directory(),
        command.project_id,
    )
    if version is None:
        return {"ok": False, "message": "图纸版本回退失败"}
    restored_payload = drawing_versions.payload(str(version["file_name"]))
    restored_geometries = (
        restored_payload.get("lines") if isinstance(restored_payload, dict) else None
    )
    actual_snapshot = snapshot_drawing(
        restored_geometries if isinstance(restored_geometries, list) else [],
        "回退结果",
    )
    verified = actual_snapshot.get("sha256") == expected_snapshot.get("sha256")
    rollback_verification = {
        "schema": "cad.rollback.verification.v1",
        "status": "success" if verified else "failed",
        "verified": verified,
        "expected_sha256": expected_snapshot.get("sha256"),
        "actual_sha256": actual_snapshot.get("sha256"),
        "validation": source_validation,
    }
    if not verified:
        return {
            "ok": False,
            "message": "回退版本已隔离保存，但几何快照复核失败，请勿用于规划。",
            "source_version": source,
            "version": version,
            "rollback_verification": rollback_verification,
        }
    return {
        "ok": True,
        "message": f"已从 {file_name} 创建新的回退版本 {version['file_name']}，几何快照复核通过",
        "source_version": source,
        "version": version,
        "rollback_verification": rollback_verification,
    }



@router.get("/api/drawings/cad-capabilities")
def cad_file_capabilities() -> dict[str, object]:
    dwg = dwg_converter_status()
    return {
        "ok": True,
        "dxf_import": True,
        "dxf_export": True,
        "dwg_import": bool(dwg["import_available"]),
        "dwg_export": bool(dwg["export_available"]),
        "dwg": dwg,
    }



@router.get("/api/drawings/{file_name}/export-dxf", response_model=None)
def export_drawing_dxf(file_name: str) -> Response | dict[str, object]:
    """Export the selected internal drawing version as a real DXF file."""
    if Path(file_name).name != file_name or Path(file_name).suffix.lower() != ".json":
        return JSONResponse(status_code=400, content={"ok": False, "message": "图纸文件名无效。"})
    target = resolve_drawing(file_name)
    if target is None:
        return JSONResponse(status_code=404, content={"ok": False, "message": "图纸文件不存在。"})
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        content, warnings = export_dxf(payload)
    except (OSError, json.JSONDecodeError, RuntimeError, ValueError) as exc:
        return JSONResponse(
            status_code=422,
            content={"ok": False, "message": f"DXF 导出失败：{exc}"},
        )
    headers = {
        "Content-Disposition": 'attachment; filename="drawing.dxf"',
        "X-DXF-Warning-Count": str(len(warnings)),
    }
    return Response(content=content, media_type="application/dxf", headers=headers)



@router.get("/api/drawings/{file_name}/export-dwg", response_model=None)
def export_drawing_dwg(file_name: str) -> Response | dict[str, object]:
    """Export an internal drawing as DWG through the configured converter."""
    if Path(file_name).name != file_name or Path(file_name).suffix.lower() != ".json":
        return JSONResponse(status_code=400, content={"ok": False, "message": "图纸文件名无效。"})
    target = resolve_drawing(file_name)
    if target is None:
        return JSONResponse(status_code=404, content={"ok": False, "message": "图纸文件不存在。"})
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        dxf_content, warnings = export_dxf(payload)
        import tempfile
        with tempfile.TemporaryDirectory(prefix="dashes-dwg-export-") as temporary:
            directory = Path(temporary)
            dxf_path = directory / "drawing.dxf"
            dwg_path = directory / "drawing.dwg"
            dxf_path.write_bytes(dxf_content)
            conversion = convert_dxf_to_dwg(dxf_path, dwg_path)
            content = dwg_path.read_bytes()
    except (OSError, json.JSONDecodeError, RuntimeError, ValueError) as exc:
        return JSONResponse(
            status_code=422,
            content={
                "ok": False,
                "message": f"DWG 导出失败：{exc}",
                "dwg_support": dwg_converter_status(),
            },
        )
    headers = {
        "Content-Disposition": 'attachment; filename="drawing.dwg"',
        "X-CAD-Warning-Count": str(len(warnings)),
        "X-DWG-Engine": str(conversion.get("engine") or "unknown"),
    }
    return Response(content=content, media_type="application/acad", headers=headers)



@router.get("/api/drawings/{file_name}/source-image", response_model=None)
def drawing_source_image(file_name: str) -> FileResponse | JSONResponse:
    """Return the review-only raster source associated with an image drawing."""
    if Path(file_name).name != file_name or Path(file_name).suffix.lower() != ".json":
        return JSONResponse(status_code=400, content={"ok": False, "message": "图纸文件名无效。"})
    target = resolve_drawing(file_name)
    if target is None:
        return JSONResponse(status_code=404, content={"ok": False, "message": "图纸文件不存在。"})
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return JSONResponse(status_code=422, content={"ok": False, "message": "图纸数据无法读取。"})
    analysis = payload.get("cad_analysis") if isinstance(payload, dict) else None
    source_key = analysis.get("source_image_file") if isinstance(analysis, dict) else None
    source = resolve_source_image(_cad_directory(), str(source_key or ""))
    if source is None:
        return JSONResponse(status_code=404, content={"ok": False, "message": "该图纸没有可复核的原始图片。"})
    media_type = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }[source.suffix.lower()]
    return FileResponse(source, media_type=media_type, filename=f"{Path(file_name).stem}{source.suffix.lower()}")



@router.get("/api/drawings/{file_name}")
def drawing_preview(file_name: str) -> dict[str, object]:
    """Return CAD geometry in the same metre-based format used by the map."""
    if Path(file_name).name != file_name or Path(file_name).suffix.lower() != ".json":
        return {"ok": False, "message": "Invalid drawing file name."}

    target = resolve_drawing(file_name)
    if target is not None:
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"ok": False, "message": "Drawing file cannot be read."}
        if not isinstance(payload, dict):
            return {"ok": False, "message": "Drawing data must be a JSON object."}
        paths = preview_paths(payload)
    else:
        paths = BUILT_IN_PREVIEWS.get(file_name, [])
        if not paths:
            return {"ok": False, "message": "Drawing file does not exist."}
        # Built-in drawings are preview-only definitions rather than JSON
        # files, so provide the same metadata shape as stored drawings.
        payload = {"editor_path_metadata": []}

    planned_paths = [
        {
            "namespace": "path_lines",
            "color": {"r": 0.1, "g": 0.8, "b": 1.0, "a": 1.0},
            "points": points,
        }
        for points in paths if len(points) >= 2
    ]
    segments = [
        {
            "start_x": float(start[0]),
            "start_y": float(start[1]),
            "end_x": float(end[0]),
            "end_y": float(end[1]),
        }
        for points in paths
        for start, end in zip(points, points[1:])
    ]
    return {
        "ok": True,
        "file_name": file_name,
        "geometries": payload.get("lines", []),
        "planned_paths": planned_paths,
        "path_preview": build_path_preview_contract(payload, file_name=file_name),
        "segments": segments,
        "path_metadata": payload.get("editor_path_metadata", []),
        "source_format": payload.get("source_format", "xline_json"),
        "cad_analysis": payload.get("cad_analysis", {}),
    }



@router.delete("/api/drawings/{file_name}")
def delete_drawing(file_name: str) -> dict[str, object]:
    if Path(file_name).name != file_name or Path(file_name).suffix.lower() != ".json":
        return {"ok": False, "message": "图纸文件名无效。"}
    if file_name in BUILT_IN_DRAWINGS:
        return {"ok": False, "message": "内置任务不能删除。"}
    if robot_state.mission_running and robot_state.mission_file == file_name:
        return {"ok": False, "message": "任务正在执行，不能删除当前图纸。"}
    target = _cad_directory() / file_name
    if not target.is_file():
        return {"ok": False, "message": "图纸不存在或已经删除。"}
    target.unlink()
    robot_state.add_log(f"drawing deleted {file_name}")
    return {"ok": True, "message": "图纸已删除。", "file_name": file_name}



@router.post("/api/drawings/save")
def save_drawing(command: DrawingSaveRequest) -> dict[str, object]:
    directory = _cad_directory()
    directory.mkdir(parents=True, exist_ok=True)
    source_file_name = command.file_name if command.overwrite else None
    if source_file_name and robot_state.mission_running and robot_state.mission_file == source_file_name:
        return {"ok": False, "message": "任务正在执行，不能编辑当前图纸。"}

    safe_stem = re.sub(r"[^\w\-\u4e00-\u9fff]", "_", command.name).strip("_")
    if source_file_name:
        source = drawing_versions.find_by_file(source_file_name)
        if source is not None:
            safe_stem = str(source.get("base_name") or safe_stem)
        else:
            # Built-in or legacy files may not be present in the version index.
            # Strip only the version suffix so the next save remains coherent.
            safe_stem = re.sub(r"_v\d{3}$", "", Path(source_file_name).stem) or safe_stem
    if not safe_stem:
        safe_stem = f"app_drawing_{datetime.now():%Y%m%d_%H%M%S}"
    file_name = f"{safe_stem}.json"
    lines = []
    for index, segment in enumerate(command.segments, start=1):
        if abs(segment.start_x - segment.end_x) + abs(segment.start_y - segment.end_y) < 0.001:
            continue
        lines.append(
            {
                "id": index,
                "type": "line",
                "layer_id": 1,
                "start": {"x": round(segment.start_x * 1000, 3), "y": round(segment.start_y * 1000, 3), "z": 0.0},
                "end": {"x": round(segment.end_x * 1000, 3), "y": round(segment.end_y * 1000, 3), "z": 0.0},
            }
        )
    if not lines:
        return {"ok": False, "message": "图纸中没有有效线段。"}
    feasibility = check_drawing_feasibility(lines)
    if feasibility["ok"] is not True:
        return {
            "ok": False,
            "message": "保存前检查未通过：" + "；".join(feasibility["errors"]),
            "feasibility": feasibility,
        }
    payload = {
        "schema_version": "1.0",
        "unit": "mm",
        "editor_path_metadata": command.path_metadata,
        **layer_drawing_paths(lines, "center"),
    }
    version = drawing_versions.save(
        directory,
        file_name,
        payload,
        "app_edit" if source_file_name else "app",
        f"编辑图纸 {source_file_name}" if source_file_name else "画图工具保存",
    )
    file_name = str(version["file_name"])
    robot_state.add_log(f"drawing saved {file_name} ({len(lines)} segments)")
    return {
        "ok": True,
        "file_name": file_name,
        "segments": len(lines),
        "feasibility": feasibility,
        "path_layers": payload["layers"],
        "version": version,
        "edited_file_name": source_file_name,
    }



@router.post("/api/drawings/import-json")
def import_drawing_json(command: DrawingJsonImportRequest) -> dict[str, object]:
    paths = preview_paths(command.payload)
    if not paths:
        return {
            "ok": False,
            "message": "JSON does not contain geometry supported by the path planner.",
        }

    directory = _cad_directory()
    directory.mkdir(parents=True, exist_ok=True)
    version = drawing_versions.save(directory, f"{command.name}.json", command.payload, "import", "JSON 导入")
    file_name = str(version["file_name"])
    robot_state.add_log(f"drawing JSON imported {file_name} ({len(paths)} paths)")
    return {"ok": True, "file_name": file_name, "paths": len(paths), "version": version}



@router.post("/api/drawings/import-cad")
async def import_cad_drawing(file: UploadFile = File(...), unit: str = "mm") -> dict[str, object]:
    """Import DXF or convert DWG before entering the canonical drawing chain."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".dxf", ".dwg"}:
        return {"ok": False, "message": "仅支持 DXF 或 DWG 文件。"}
    import tempfile
    content = await file.read()
    if not content:
        return {"ok": False, "message": "上传的 CAD 文件为空。"}
    if len(content) > 50 * 1024 * 1024:
        return {"ok": False, "message": "CAD 文件超过 50MB，不能导入。"}
    if suffix == ".dwg" and content[:4] != b"AC10":
        return {"ok": False, "message": "文件扩展名是 DWG，但文件内容不是有效的 DWG。"}
    conversion: dict[str, object] | None = None
    with tempfile.TemporaryDirectory(prefix="dashes-cad-") as temporary:
        directory_path = Path(temporary)
        uploaded = directory_path / f"source{suffix}"
        uploaded.write_bytes(content)
        source = uploaded
        if suffix == ".dwg":
            source = directory_path / "converted.dxf"
            try:
                conversion = convert_dwg_to_dxf(uploaded, source)
            except RuntimeError as exc:
                return {
                    "ok": False,
                    "message": str(exc),
                    "dwg_support": dwg_converter_status(),
                }
        try:
            layer_summary = inspect_dxf_layers(source)
            # INSERT blocks can expand into hundreds of thousands of canonical
            # geometries, so the lightweight entity count alone is not enough.
            # Large block-heavy drawings and drawings whose entities all live
            # on an unclassified layer must go through layer selection first.
            # The latter is common in older DWG files that define named layers
            # but place every model-space entity on layer 0.
            large_cad = (
                int(layer_summary.get("estimated_geometry_count", 0)) > 100_000
                or int(layer_summary.get("entity_counts", {}).get("INSERT", 0)) > 1_000
            )
            summary_layers = list(layer_summary.get("layers") or [])
            needs_role_confirmation = bool(summary_layers) and not any(
                isinstance(layer, dict) and layer.get("path_semantic") == "DRAW"
                for layer in summary_layers
            )
            if large_cad or needs_role_confirmation:
                import_root = _cad_directory() / ".imports"
                import_root.mkdir(parents=True, exist_ok=True)
                import_token = uuid.uuid4().hex
                staged_path = import_root / f"{import_token}.dxf"
                staged_path.write_bytes(source.read_bytes())
                metadata = {
                    "original_name": file.filename or "drawing.dxf",
                    "source_format": "dwg" if suffix == ".dwg" else "dxf",
                    "unit": unit,
                    "dwg_conversion": conversion,
                    "created_at": time.time(),
                }
                (import_root / f"{import_token}.json").write_text(
                    json.dumps(metadata, ensure_ascii=False), encoding="utf-8"
                )
                return {
                    "ok": True,
                    "requires_layer_selection": True,
                    "layer_selection_reason": "large" if large_cad else "unclassified",
                    "import_token": import_token,
                    "message": (
                        "施工图较大，请先关闭不需要的图层和内容。"
                        if large_cad
                        else "CAD 图元所在图层用途尚未确认，请选择需要喷墨的图层。"
                    ),
                    "layers": layer_summary["layers"],
                    "cad_analysis": layer_summary,
                    "source_format": metadata["source_format"],
                    "dwg_conversion": conversion,
                }
            payload, warnings = parse_dxf(source, unit)
        except (ValueError, RuntimeError) as exc:
            return {"ok": False, "message": str(exc)}
    if suffix == ".dwg":
        payload["source_format"] = "dwg"
        payload["cad_analysis"] = {
            **dict(payload.get("cad_analysis") or {}),
            "converted_from_dwg": True,
            "dwg_conversion": conversion,
        }
    feasibility = check_drawing_feasibility(list(payload.get("lines", [])))
    payload["cad_analysis"] = {
        **dict(payload.get("cad_analysis") or {}),
        "feasibility": feasibility,
    }
    if len(payload.get("lines", [])) > 100_000:
        return {
            "ok": False,
            "message": (
                f"CAD 已解析出 {len(payload.get('lines', []))} 个图元，请使用图层筛选后再导入。"
            ),
            "warnings": warnings,
            "analysis": payload.get("cad_analysis", {}),
            "source_format": payload.get("source_format"),
            "dwg_conversion": conversion,
        }
    paths = preview_paths(payload)
    if not paths:
        return {
            "ok": False,
            "message": "DXF 只包含参考/标注内容，没有可执行的喷墨几何。",
            "warnings": warnings,
            "analysis": feasibility,
        }
    directory = _cad_directory()
    directory.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^\w\-\u4e00-\u9fff]", "_", Path(file.filename or "drawing").stem).strip("_") or "cad_drawing"
    source_label = "DWG" if suffix == ".dwg" else "DXF"
    version = drawing_versions.save(
        directory, f"{stem}.json", payload, "cad_import", f"{source_label} 导入"
    )
    file_name = str(version["file_name"])
    robot_state.add_log(f"drawing {source_label} imported {file_name} ({len(paths)} paths)")
    return {
        "ok": True,
        "file_name": file_name,
        "paths": len(paths),
        "warnings": warnings,
        "analysis": feasibility,
        "layers": payload.get("layers", []),
        "cad_analysis": payload.get("cad_analysis", {}),
        "version": version,
        "source_format": payload.get("source_format"),
        "dwg_conversion": conversion,
    }



@router.post("/api/drawings/import-cad/filtered")
def import_filtered_cad_drawing(command: CadLayerFilteredImportRequest) -> dict[str, object]:
    import_root = _cad_directory() / ".imports"
    source = import_root / f"{command.import_token}.dxf"
    metadata_path = import_root / f"{command.import_token}.json"
    if not source.is_file() or not metadata_path.is_file():
        return {"ok": False, "message": "CAD 临时导入会话已失效，请重新选择文件。"}
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"ok": False, "message": "CAD 临时导入信息损坏，请重新选择文件。"}
    if time.time() - float(metadata.get("created_at", 0)) > 3600:
        source.unlink(missing_ok=True)
        metadata_path.unlink(missing_ok=True)
        return {"ok": False, "message": "CAD 临时导入会话已过期，请重新选择文件。"}

    summary = inspect_dxf_layers(source)
    id_to_name = {
        str(layer["id"]): str(layer["name"])
        for layer in summary["layers"] if isinstance(layer, dict)
    }
    unknown = sorted(set(command.roles) - set(id_to_name))
    if unknown:
        return {"ok": False, "message": "包含不存在的图层 ID：" + ", ".join(unknown)}
    layer_roles = {
        name: command.roles.get(layer_id, "SKIP")
        for layer_id, name in id_to_name.items()
    }
    try:
        payload, warnings = parse_dxf(
            source,
            str(metadata.get("unit") or "mm"),
            layer_roles=layer_roles,
            excluded_entity_types=set(command.excluded_entity_types),
        )
    except (ValueError, RuntimeError) as exc:
        return {"ok": False, "message": str(exc)}
    geometry_count = len(payload.get("lines", []))
    if geometry_count > 100_000:
        return {
            "ok": False,
            "message": f"筛选后仍有 {geometry_count} 个图元，请继续关闭不需要的图层。",
            "layers": summary["layers"],
            "cad_analysis": payload.get("cad_analysis", {}),
        }
    paths = preview_paths(payload)
    if not paths:
        return {"ok": False, "message": "筛选后没有喷墨路径，请至少保留一个喷墨图层。"}
    payload["source_format"] = str(metadata.get("source_format") or "dxf")
    payload["cad_analysis"] = {
        **dict(payload.get("cad_analysis") or {}),
        "layer_roles_confirmed": True,
        "filtered_import": True,
        "excluded_entity_types": command.excluded_entity_types,
    }
    stem = re.sub(
        r"[^\w\-\u4e00-\u9fff]", "_", Path(str(metadata.get("original_name"))).stem
    ).strip("_") or "cad_drawing"
    version = drawing_versions.save(
        _cad_directory(), f"{stem}.json", payload, "cad_import", "CAD 筛选导入"
    )
    source.unlink(missing_ok=True)
    metadata_path.unlink(missing_ok=True)
    return {
        "ok": True,
        "file_name": str(version["file_name"]),
        "paths": len(paths),
        "warnings": warnings,
        "layers": payload.get("layers", []),
        "cad_analysis": payload.get("cad_analysis", {}),
        "version": version,
        "source_format": payload.get("source_format"),
    }



@router.post("/api/drawings/{file_name}/layer-roles")
def update_drawing_layer_roles(
    file_name: str, command: DrawingLayerRoleRequest
) -> dict[str, object]:
    """Persist a human-confirmed CAD layer mapping as a new drawing version."""
    target = resolve_drawing(file_name)
    if target is None:
        return {"ok": False, "message": "图纸不存在或文件名无效。"}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"ok": False, "message": f"图纸读取失败：{exc}"}
    layers = payload.get("layers")
    geometries = payload.get("lines")
    if not isinstance(layers, list) or not isinstance(geometries, list):
        return {"ok": False, "message": "该图纸没有可确认的 CAD 图层元数据。"}
    known_ids = {str(item.get("id")): item for item in layers if isinstance(item, dict)}
    unknown = sorted(set(command.roles) - set(known_ids))
    if unknown:
        return {"ok": False, "message": "包含不存在的图层 ID：" + ", ".join(unknown)}
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        layer_id = str(layer.get("id"))
        if layer_id in command.roles:
            selected_value = command.roles[layer_id]
            semantic = (
                selected_value
                if selected_value in PATH_SEMANTIC_TO_ROLE
                else ROLE_TO_PATH_SEMANTIC[selected_value]
            )
            layer["path_semantic"] = semantic
            layer["role"] = PATH_SEMANTIC_TO_ROLE[semantic]
    for geometry in geometries:
        if not isinstance(geometry, dict):
            continue
        selected_value = command.roles.get(str(geometry.get("layer_id")))
        if selected_value is not None:
            semantic = (
                selected_value
                if selected_value in PATH_SEMANTIC_TO_ROLE
                else ROLE_TO_PATH_SEMANTIC[selected_value]
            )
            role = PATH_SEMANTIC_TO_ROLE[semantic]
            geometry["path_semantic"] = semantic
            geometry["role"] = role
            geometry["selected"] = semantic == "DRAW"
    analysis = dict(payload.get("cad_analysis") or {})
    analysis["printing_geometry_count"] = sum(
        item.get("role") == "printing" for item in geometries if isinstance(item, dict)
    )
    analysis["reference_geometry_count"] = sum(
        item.get("role") != "printing" for item in geometries if isinstance(item, dict)
    )
    analysis["path_semantic_counts"] = {
        semantic: sum(
            item.get("path_semantic") == semantic
            for item in geometries if isinstance(item, dict)
        )
        for semantic in PATH_SEMANTIC_TO_ROLE
    }
    analysis["layer_roles_confirmed"] = True
    payload["cad_analysis"] = analysis
    paths = preview_paths(payload)
    if not paths:
        return {"ok": False, "message": "确认后没有可执行的喷墨路径，请至少保留一个 DRAW 图层。"}
    version = drawing_versions.save(
        _cad_directory(), file_name, payload, "layer_confirmation", "用户确认 CAD 图层角色"
    )
    return {
        "ok": True,
        "file_name": version["file_name"],
        "paths": len(paths),
        "layers": layers,
        "version": version,
    }



@router.get("/api/drawings/{file_name}/analysis")
def drawing_analysis(file_name: str) -> dict[str, object]:
    target = resolve_drawing(file_name)
    if target is None:
        return {"ok": False, "message": "图纸不存在或文件名无效。"}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"ok": False, "message": f"图纸读取失败：{exc}"}
    geometries = payload.get("lines", []) if isinstance(payload, dict) else []
    geometry_list = geometries if isinstance(geometries, list) else []
    return {
        "ok": True,
        "file_name": file_name,
        "layers": payload.get("layers", []),
        "cad_analysis": payload.get("cad_analysis", {}),
        "feasibility": check_drawing_feasibility(
            geometry_list
        ),
        "topology": analyze_geometry_topology(geometry_list),
    }



@router.post("/api/drawings/import-image")
async def import_image_drawing(
    file: UploadFile = File(...), physical_width_mm: float = 0.0
) -> dict[str, object]:
    """Vectorize a calibrated raster image into the canonical drawing chain."""
    import tempfile

    content = await file.read()
    try:
        suffix = validate_image_upload(file.filename or "drawing.png", content)
    except ValueError as exc:
        return {"ok": False, "message": str(exc)}
    with tempfile.TemporaryDirectory(prefix="dashes-image-drawing-") as temporary:
        source = Path(temporary) / f"source{suffix}"
        source.write_bytes(content)
        try:
            payload, warnings = await asyncio.to_thread(
                vectorize_image_to_drawing,
                source,
                physical_width_mm=physical_width_mm,
            )
        except (ValueError, RuntimeError) as exc:
            return {
                "ok": False,
                "message": str(exc),
                "vectorizer": image_vectorizer_status(),
            }
    feasibility = check_drawing_feasibility(list(payload.get("lines", [])))
    payload["cad_analysis"] = {
        **dict(payload.get("cad_analysis") or {}),
        "feasibility": feasibility,
    }
    paths = preview_paths(payload)
    if not paths:
        return {
            "ok": False,
            "message": "图片已解析，但没有生成可预览的划线图元。",
            "warnings": warnings,
        }
    directory = _cad_directory()
    directory.mkdir(parents=True, exist_ok=True)
    try:
        source_image_file = save_source_image(directory, suffix, content)
    except (OSError, ValueError) as exc:
        return {"ok": False, "message": f"原始图片保存失败：{exc}"}
    payload["cad_analysis"] = {
        **dict(payload.get("cad_analysis") or {}),
        "source_image_file": source_image_file,
        "source_image_available": True,
        "source_image_review_only": True,
    }
    stem = (
        re.sub(r"[^\w\-\u4e00-\u9fff]", "_", Path(file.filename or "image_drawing").stem)
        .strip("_")
        or "image_drawing"
    )
    try:
        version = drawing_versions.save(
            directory, f"{stem}.json", payload, "image_import", "图片转图纸"
        )
    except Exception:
        source = resolve_source_image(directory, source_image_file)
        if source is not None:
            source.unlink(missing_ok=True)
        raise
    file_name = str(version["file_name"])
    robot_state.add_log(f"image drawing imported {file_name} ({len(paths)} paths)")
    return {
        "ok": True,
        "file_name": file_name,
        "paths": len(paths),
        "warnings": warnings,
        "analysis": feasibility,
        "cad_analysis": payload.get("cad_analysis", {}),
        "layers": payload.get("layers", []),
        "version": version,
        "source_format": "image",
    }

