"""CLOSE-04 B01/B02 mock-plan handoff probe.

No frozen construction plan exists for B01/B02.  This probe supplies one
generic, legal rectangle/circle plan after the creation confirmation and
observes whether the production entry still invokes the plan producer and the
candidate commit boundary.  It is a synthetic handoff test, not a replay of the
historical model output.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import PropertyMock, patch

WORKTREE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKTREE / "backend"))

from app.agent_service import RobotAgentService  # noqa: E402
from app.creative_projects import CreativeProjectStore  # noqa: E402

OUT = Path(r"C:\Users\29924\Codes\xikao\cad_core_generalization_close_04\b01_b02_mock_plan.json")

CASES = {
    "B01": (
        "正方形检测平台外轮廓，边长850毫米，左下角在原点，只保留闭合轮廓。",
        {"schema_version": "cad.construction-plan.v1", "units": "m", "steps": [
            {"step_id": "plate", "op": "add_rectangle", "output_ref": "plate",
             "origin": {"x": 0, "y": 0}, "width": 0.85, "height": 0.85,
             "semantic": {"label": "外轮廓", "role": "outline"}}],
         "assertions": [
             {"kind": "bounds_size", "assertion_id": "size", "target_ref": "plate",
              "width": 0.85, "height": 0.85, "tolerance": 0.001},
             {"kind": "closed", "assertion_id": "closed", "target_ref": "plate"}]},
    ),
    "B02": (
        "圆形井盖基座，圆心放在(-2400,1600)，半径1275毫米，只画这个圆，不要加十字中心线。",
        {"schema_version": "cad.construction-plan.v1", "units": "m", "steps": [
            {"step_id": "base", "op": "add_circle", "output_ref": "base",
             "center": {"x": -2.4, "y": 1.6}, "radius": 1.275,
             "semantic": {"label": "井盖基座", "role": "outline"}}],
         "assertions": [{"kind": "entity_count", "assertion_id": "count", "equals": 1}]},
    ),
}


def run(case: str, source: str, plan: dict) -> dict:
    service = RobotAgentService(restore_pending_actions=False)
    service.mode = "deepseek"
    store = CreativeProjectStore(Path(tempfile.mkdtemp()) / "projects.json")
    project = store.create(
        case, source, requirements={"shape": "generic_2d_cad"}, missing_parameters=[])
    route = {
        "name": "drawing_design",
        "operation": "create",
        "stage": "candidate_generation",
        "selected_project_id": project["id"],
    }
    payload = {
        "schema": "cad.construction-interpretation-result.v1",
        "status": "ready",
        "parser": "structured_model",
        "provider_attempted": True,
        "confidence": 0.9,
        "plan": plan,
        "acceptance_summary": {"status": "passed", "review_required": False},
    }
    calls: list[str] = []
    commits: list[str] = []

    def interpret(_model_input, request_budget=None, planning_kind="initial", **_kwargs):
        if request_budget:
            request_budget(planning_kind)
        calls.append("plan")
        return payload

    def commit(*_args, **_kwargs):
        commits.append("commit")
        return {
            "schema": "cad.construction-commit.v1",
            "recommended_candidate_id": "mock",
            "project": {"id": project["id"], "status": "designing"},
            "recommended_variant": {
                "id": "mock", "preview_paths": [], "geometries": [],
                "logical_objects": [], "topology": {},
                "acceptance_summary": {"status": "passed", "review_required": False},
            },
            "persisted_candidate_count": 1,
        }

    with patch("app.agent_service.get_creative_project_store", return_value=store), \
         patch.object(RobotAgentService, "configured",
                      new_callable=PropertyMock, return_value=True), \
         patch("app.agent_service.commit_construction_interpretation", side_effect=commit), \
         patch.object(service, "_interpret_cad_construction_plan", side_effect=interpret):
        raw = service._formal_cad_construction(
            "确认新建 CAD 图纸并生成候选方案。", route, mode="advanced")

    if not isinstance(raw, dict):
        return {"case": case, "raw": repr(raw),
                "plan_calls": len(calls), "commit_calls": len(commits)}
    variant = raw.get("variant") or {}
    return {
        "case": case,
        "ok": raw.get("ok"),
        "plan_calls": len(calls),
        "commit_calls": len(commits),
        "variant": bool(variant),
        "variant_id": variant.get("id"),
        "acceptance": (variant.get("acceptance_summary") or {}).get("status"),
        "message": str(raw.get("message") or "")[:240],
    }


def main() -> int:
    rows = [run(case, *payload) for case, payload in CASES.items()]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "schema": "cad.close04.b01-b02-mock-plan.v1",
        "evidence_level": "SYNTHETIC_GENERIC_PLAN_HANDOFF",
        "historical_frozen_plan_present": False,
        "real_model_calls": 0,
        "cases": rows,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
