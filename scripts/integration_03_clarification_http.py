"""INTEGRATION-03 clarification HTTP acceptance for Q01-Q04.

The zero-model freeze cannot reproduce a model's tool choice.  Each case is
sent through the production HTTP entry with either the deterministic
clarification path or the already-produced contract question injected into the
route.  A follow-up then supplies the missing parameter so the next production
step can be observed.  Real model requests stay at zero.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

WORKTREE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKTREE / "backend"))

from app import agent_http_service, agent_service  # noqa: E402
from app.agent_http_service import agent_chat  # noqa: E402
from app.agent_skills import clarify_requirements  # noqa: E402
from app.conversation_memory import ConversationMemoryStore  # noqa: E402
from app.creative_projects import CreativeProjectStore  # noqa: E402
from app.schemas import AgentChatRequest  # noqa: E402

RUNS = Path(r"C:\Users\29924\Codes\xikao\cad_e2e_generalization_live_01\runs\GENERALIZATION-01")
OUT = Path(r"C:\Users\29924\Codes\xikao\cad_core_generalization_integration_03\clarification_http.json")

FOLLOW_UP = {
    "Q01": "半径300毫米，相对左上角偏移500毫米、500毫米。",
    "Q02": "总宽3000毫米、总高1800毫米，每级踏步深300毫米、高600毫米。",
    "Q03": "生成 CAD 平面图，车间12米乘8米，设备2米乘1米，排两排，中间留1米检修通道。",
    "Q04": "把刚才那个矩形左右镜像，保留原来的标注。",
}


def brief(response: dict[str, Any]) -> dict[str, Any]:
    variant = response.get("variant") or {}
    clarification = response.get("clarification") or {}
    return {
        "ok": bool(response.get("ok")),
        "message": str(response.get("message") or "")[:400],
        "project_id": response.get("project_id"),
        "clarification_status": clarification.get("status"),
        "clarification_question_key": clarification.get("question_key")
        or ((response.get("agent_context") or {}).get("route", {}) or {}).get("clarification_question_key"),
        "candidate_visibility": (response.get("candidate_visibility") or {}).get("status"),
        "variant_present": bool(variant),
        "acceptance": (variant.get("acceptance_summary") or {}).get("status"),
        "geometry_hash": (variant.get("construction_record") or {}).get("geometry_hash"),
    }


def run(case: str) -> dict[str, Any]:
    prompt = json.loads((RUNS / case / "request-1.json").read_text(encoding="utf-8"))["message"]
    work = Path(tempfile.mkdtemp(prefix=f"int03-clar-{case}-"))
    store = CreativeProjectStore(work / "projects.json")
    memory = ConversationMemoryStore(work / "memory.json")
    contract = clarify_requirements(prompt) if case == "Q03" else {}

    def route(message: str, _mode: str, _history=None) -> dict[str, Any]:
        payload = {
            "name": "drawing_design",
            "tool_family": "cad",
            "operation": "create",
            "decision_source": "integration_03_clarification_http",
            "user_message": message,
        }
        if case == "Q03" and message == prompt:
            payload.update(
                {
                    "clarification_required": True,
                    "clarification_question": contract.get("next_question"),
                    "clarification_question_key": contract.get("next_question_key"),
                }
            )
        return payload

    for module in (agent_service, agent_http_service):
        setattr(module, "get_creative_project_store", lambda: store)
        setattr(module, "conversation_memory", memory)
    agent_service.robot_agent.mode = "local"
    agent_service.robot_agent.api_keys = {}
    agent_service.robot_agent.resolve_intent = route
    agent_service.robot_agent.route_intent = route

    first = agent_chat(
        AgentChatRequest(
            message=prompt,
            mode="advanced",
            conversation_id=f"int03-clar-{case}",
            client_id="integration-03",
        )
    )
    project_id = first.get("project_id")
    second = agent_chat(
        AgentChatRequest(
            message=FOLLOW_UP[case],
            mode="advanced",
            conversation_id=f"int03-clar-{case}",
            client_id="integration-03",
            project_id=project_id,
        )
    )
    return {
        "case": case,
        "prompt": prompt,
        "first": brief(first),
        "follow_up": FOLLOW_UP[case],
        "second": brief(second),
    }


def main() -> int:
    rows = [run(case) for case in ("Q01", "Q02", "Q03", "Q04")]
    payload = {
        "schema": "cad.integration-03.clarification-http.v1",
        "real_model_calls": 0,
        "route_injected_cases": ["Q03"],
        "cases": rows,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
