"""Q03 contract-route HTTP addendum for INTEGRATION-03.

The historical Q03 path reaches `clarify_requirements` only after a real model
tool call. Under the zero-model freeze we inject the already-produced contract
question into the production route and pass it through `agent_chat`. This proves
HTTP delivery of the clarified question, not model tool selection.
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
from app.agent_skills import clarify_requirements  # noqa: E402
from app.conversation_memory import ConversationMemoryStore  # noqa: E402
from app.creative_projects import CreativeProjectStore  # noqa: E402
from app.schemas import AgentChatRequest  # noqa: E402

OUT = Path(r"C:\Users\29924\Codes\xikao\cad_core_generalization_integration_03\q03_http_addendum.json")
PROMPT = "在车间里排两排设备，中间留一条检修通道。"


def main() -> int:
    contract = clarify_requirements(PROMPT)
    work = Path(tempfile.mkdtemp(prefix="int03-q03-"))
    store = CreativeProjectStore(work / "projects.json")
    memory = ConversationMemoryStore(work / "memory.json")

    def route(_message: str, _mode: str, _history=None) -> dict:
        return {
            "name": "drawing_design",
            "tool_family": "cad",
            "operation": "create",
            "decision_source": "integration_03_q03_contract_route",
            "clarification_required": True,
            "clarification_question": contract.get("next_question"),
            "clarification_question_key": contract.get("next_question_key"),
        }

    for module in (agent_service, agent_http_service):
        setattr(module, "get_creative_project_store", lambda: store)
        setattr(module, "conversation_memory", memory)
    agent_service.robot_agent.mode = "local"
    agent_service.robot_agent.api_keys = {}
    agent_service.robot_agent.resolve_intent = route
    agent_service.robot_agent.route_intent = route

    response = agent_chat(
        AgentChatRequest(message=PROMPT, mode="advanced", conversation_id="int03-q03", client_id="integration-03")
    )
    payload = {
        "schema": "cad.integration-03.q03-http-addendum.v1",
        "prompt": PROMPT,
        "model_calls": 0,
        "route_injected": True,
        "question_source": "app.agent_skills.clarify_requirements",
        "contract": {
            "next_question_key": contract.get("next_question_key"),
            "next_question": contract.get("next_question"),
            "ready_for_design": contract.get("ready_for_design"),
        },
        "http": {
            "ok": bool(response.get("ok")),
            "message": response.get("message"),
            "clarification_required": bool((response.get("agent_context") or {}).get("route", {}).get("clarification_required")),
            "clarification_question_key": (response.get("agent_context") or {}).get("route", {}).get("clarification_question_key"),
            "candidate_visibility": (response.get("candidate_visibility") or {}).get("status"),
            "variant_present": bool(response.get("variant")),
        },
        "limitation": "The frozen zero-model run cannot reproduce the model's decision to call clarify_requirements; the route question is injected from the real contract function.",
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
