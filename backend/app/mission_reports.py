from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def build_acceptance_report(mission: dict[str, Any], final_state: str,
                            localization_source: str, oscillation_events: list[dict[str, Any]]) -> dict[str, Any]:
    segments = mission.get("segments", [])
    segments = [item for item in segments if isinstance(item, dict)]
    completed = [item for item in segments if item.get("state") == "completed"]
    def check_for(item: dict[str, Any]) -> dict[str, Any]:
        postcheck = item.get("postcheck")
        if isinstance(postcheck, dict):
            return postcheck
        verification = item.get("verification")
        return verification if isinstance(verification, dict) else {}

    errors = [check_for(item).get("endpoint_error_m") for item in completed]
    errors = [float(value) for value in errors if isinstance(value, (int, float))]
    warnings = [
        warning
        for item in segments
        for warning in check_for(item).get("warnings", [])
        if isinstance(warning, str)
    ]
    quality = mission.get("quality") if isinstance(mission.get("quality"), dict) else {}
    construction_diagnostics = quality.get("construction_diagnostics")
    if not isinstance(construction_diagnostics, dict):
        construction_diagnostics = {}
    for warning in construction_diagnostics.get("acceptance_warnings", []):
        if isinstance(warning, str) and warning not in warnings:
            warnings.append(warning)
    execution_mode = str(mission.get("execution_mode") or "unknown")
    nozzle_offset = construction_diagnostics.get("nozzle_offset")
    if (
        execution_mode != "virtual_sim"
        and isinstance(nozzle_offset, dict)
        and nozzle_offset.get("configured") is False
    ):
        warning = "尚未配置喷头相对底盘偏移，无法验证喷头补偿"
        if warning not in warnings:
            warnings.append(warning)
    if final_state == "completed" and not warnings and not oscillation_events:
        verdict = "accepted"
    elif final_state == "completed":
        verdict = "accepted_with_warnings"
    elif final_state in {"failed", "interrupted"}:
        verdict = "failed"
    else:
        verdict = "incomplete"
    return {
        "mission_id": mission.get("id"), "file_name": mission.get("file_name"),
        "execution_mode": execution_mode,
        "drawing_version": mission.get("drawing_version"), "quality": quality,
        "construction_diagnostics": construction_diagnostics,
        "final_state": final_state, "verdict": verdict, "localization_source": localization_source,
        "segment_counts": {"total": len(segments), "completed": len(completed),
                           "failed": sum(item.get("state") == "failed" for item in segments),
                           "pending": sum(item.get("state") == "pending" for item in segments)},
        "endpoint_error_m": {"maximum": round(max(errors), 4) if errors else None,
                             "average": round(sum(errors) / len(errors), 4) if errors else None},
        "oscillation_events": oscillation_events, "warnings": warnings,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
