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
        "drawing_version": mission.get("drawing_version"), "quality": mission.get("quality", {}),
        "final_state": final_state, "verdict": verdict, "localization_source": localization_source,
        "segment_counts": {"total": len(segments), "completed": len(completed),
                           "failed": sum(item.get("state") == "failed" for item in segments),
                           "pending": sum(item.get("state") == "pending" for item in segments)},
        "endpoint_error_m": {"maximum": round(max(errors), 4) if errors else None,
                             "average": round(sum(errors) / len(errors), 4) if errors else None},
        "oscillation_events": oscillation_events, "warnings": warnings,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
