"""B01/B02 frozen-protocol probe: creation confirmation then generation.

No frozen construction plan exists for these two cases; this probe checks the
production deterministic path after the normal creation confirmation.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKTREE / "backend"))

from app import agent_http_service, agent_service  # noqa: E402
from app.agent_http_service import agent_chat  # noqa: E402
from app.conversation_memory import ConversationMemoryStore  # noqa: E402
from app.creative_projects import CreativeProjectStore  # noqa: E402
from app.schemas import AgentChatRequest  # noqa: E402

RUNS = Path(r"C:\Users\29924\Codes\xikao\cad_e2e_generalization_live_01\runs\GENERALIZATION-01")
OUT = Path(r"C:\Users\29924\Codes\xikao\cad_core_generalization_integration_03\b01_b02_protocol.json")

CASES = {
    "B01": ("确认新建 CAD 图纸并生成候选方案。", "正方形检测平台外轮廓，边长850毫米，左下角在原点，只保留闭合轮廓。"),
    "B02": ("确认新建 CAD 图纸并生成候选方案。", "圆形井盖基座，圆心在(-2400,1600)，半径1275毫米，只画圆。"),
}


def run(case: str, confirmation: str, restatement: str) -> dict:
    prompt = json.loads((RUNS / case / "request-1.json").read_text(encoding="utf-8"))["message"]
    work = Path(tempfile.mkdtemp(prefix=f"int03-proto-{case}-"))
    store = CreativeProjectStore(work / "projects.json")
    memory = ConversationMemoryStore(work / "memory.json")

    def route(_message: str, _mode: str, _history=None) -> dict:
        return {"name": "drawing_design", "tool_family": "cad", "operation": "create", "decision_source": "integration_03_protocol"}

    for module in (agent_service, agent_http_service):
        setattr(module, "get_creative_project_store", lambda: store)
        setattr(module, "conversation_memory", memory)
    agent_service.robot_agent.mode = "local"
    agent_service.robot_agent.api_keys = {}
    agent_service.robot_agent.resolve_intent = route
    agent_service.robot_agent.route_intent = route

    first = agent_chat(AgentChatRequest(message=prompt, mode="advanced", conversation_id=f"int03-proto-{case}", client_id="integration-03"))
    project_id = first.get("project_id")
    second = agent_chat(AgentChatRequest(message=confirmation, mode="advanced", conversation_id=f"int03-proto-{case}", client_id="integration-03", project_id=project_id))
    third = None
    if not (second.get("variant") or second.get("variants")):
        third = agent_chat(AgentChatRequest(message=restatement, mode="advanced", conversation_id=f"int03-proto-{case}", client_id="integration-03", project_id=project_id))

    def brief(response: dict | None) -> dict | None:
        if response is None:
            return None
        variant = response.get("variant") or {}
        return {
            "ok": response.get("ok"),
            "message": str(response.get("message") or "")[:300],
            "project_id": response.get("project_id"),
            "candidate_visibility": (response.get("candidate_visibility") or {}).get("status"),
            "variant_present": bool(variant),
            "acceptance": (variant.get("acceptance_summary") or {}).get("status"),
            "geometry_hash": (variant.get("construction_record") or {}).get("geometry_hash"),
        }

    return {"case": case, "prompt": prompt, "first": brief(first), "second": brief(second), "third": brief(third)}


def main() -> int:
    rows = [run(case, *payload) for case, payload in CASES.items()]
    OUT.write_text(json.dumps({"schema": "cad.integration03.b01-b02-protocol.v1",
        "evidence_level": "PRODUCTION_DETERMINISTIC_PATH_NO_FROZEN_PLAN",
        "real_model_calls": 0, "cases": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
