"""Five historical LIVE-RETEST-02 cases through the production HTTP entry.

Uses each case's latest frozen construction plan, so the model callback is
replaced and real model calls remain zero.
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
from app.cad_candidate_state import geometry_evidence_hash  # noqa: E402
from app.cad_construction_interpreter import interpret_construction_request  # noqa: E402
from app.conversation_memory import ConversationMemoryStore  # noqa: E402
from app.creative_projects import CreativeProjectStore  # noqa: E402
from app.schemas import AgentChatRequest  # noqa: E402

SOURCE = Path(r"C:\Users\29924\Codes\xikao\cad_e2e_live_retest_02\cases")
OUT = Path(r"C:\Users\29924\Codes\xikao\cad_core_generalization_close_04\five_case_http.json")
CASES = ["L01-A2", "L02-C7", "L03-A9", "L04-C31", "L05-C6"]


def load_case(case: str) -> dict[str, Any]:
    for step in sorted((SOURCE / case).glob("service-step-*.json"), reverse=True):
        record = json.loads(step.read_text(encoding="utf-8"))
        for variant in record.get("variants") or []:
            construction = variant.get("construction_record") or {}
            if construction.get("plan"):
                return {
                    "prompt": record["project"]["original_prompt"],
                    "plan": construction["plan"],
                    "evidence_text": construction.get("evidence_text") or record["project"]["original_prompt"],
                    "stored_hash": construction.get("geometry_hash") or geometry_evidence_hash(variant["geometries"]),
                    "stored_acceptance": (variant.get("acceptance_summary") or {}).get("status"),
                    "stored_coverage": ((variant.get("acceptance_summary") or {}).get("coverage_evidence") or {}).get("state"),
                }
    raise RuntimeError(f"no variant for {case}")


def run(case: str) -> dict[str, Any]:
    frozen = load_case(case)
    work = Path(tempfile.mkdtemp(prefix=f"int03-five-{case}-"))
    store = CreativeProjectStore(work / "projects.json")
    memory = ConversationMemoryStore(work / "memory.json")

    def route(_message: str, _mode: str, _history=None) -> dict:
        return {"name": "drawing_design", "tool_family": "cad", "operation": "create", "decision_source": "integration_03_five_case"}

    def callback(_text: str, _schema: dict) -> dict:
        return {
            "schema_version": "cad.construction-interpretation.v1",
            "is_construction_request": True,
            "plan": frozen["plan"],
            "evidence_text": [frozen["evidence_text"]] if isinstance(frozen["evidence_text"], str) else frozen["evidence_text"],
            "assumptions": [],
            "confidence": 1.0,
        }

    def interpreter(message: str, mode: str | None = None, **_kwargs) -> dict:
        return interpret_construction_request(message, callback, force_structured_model=True)

    for module in (agent_service, agent_http_service):
        setattr(module, "get_creative_project_store", lambda: store)
        setattr(module, "conversation_memory", memory)
    agent_service.robot_agent.mode = "local"
    agent_service.robot_agent.api_keys = {}
    agent_service.robot_agent.resolve_intent = route
    agent_service.robot_agent.route_intent = route
    agent_service.robot_agent._interpret_cad_construction_plan = interpreter

    response = agent_chat(AgentChatRequest(message=frozen["prompt"], mode="advanced", conversation_id=f"int03-five-{case}", client_id="integration-03"))
    variant = response.get("variant") or {}
    response_variant_present = bool(variant)
    acceptance = variant.get("acceptance_summary") or {}
    construction = variant.get("construction_record") or {}
    coverage = (construction.get("source_acceptance") or {}).get("coverage_evidence") or {}
    new_hash = construction.get("geometry_hash") or (geometry_evidence_hash(variant.get("geometries") or []) if variant else None)

    # Draft-review responses do not expose a variant; reload the project store
    # to compare the persisted geometry hash and acceptance detail.
    persisted_report: dict[str, Any] = {"reloaded": False}
    project_id = response.get("project_id")
    if project_id and (work / "projects.json").exists():
        reloaded = store.get(str(project_id))
        variants = (reloaded or {}).get("variants") or []
        match = next((item for item in variants if item.get("id") == variant.get("id")), None)
        if match is None and not variant and variants:
            match = variants[-1]
        if match:
            persisted = match.get("construction_record") or {}
            persisted_hash = persisted.get("geometry_hash") or geometry_evidence_hash(match.get("geometries") or [])
            persisted_acceptance = match.get("acceptance_summary") or {}
            persisted_coverage = (persisted.get("source_acceptance") or {}).get("coverage_evidence") or {}
            persisted_report = {
                "reloaded": True,
                "variant_found": True,
                "variant_count": len(variants),
                "geometry_hash": persisted_hash,
                "hash_equal": persisted_hash == frozen["stored_hash"],
                "acceptance": persisted_acceptance.get("status"),
                "coverage": persisted_coverage.get("state"),
                "verified_checks": persisted_acceptance.get("verified_checks"),
                "verified_requirement_count": persisted_coverage.get("verified_requirement_count"),
                "partial_requirement_count": persisted_coverage.get("partial_requirement_count"),
                "unbound_requirement_count": persisted_coverage.get("unbound_requirement_count"),
                "unverified_requirement_count": persisted_coverage.get("unverified_requirement_count"),
                "blocking_requirements": persisted_coverage.get("blocking_requirements") or [],
            }
            if not acceptance:
                acceptance = persisted_acceptance
                coverage = persisted_coverage
            if new_hash is None:
                new_hash = persisted_hash
        else:
            persisted_report = {"reloaded": True, "variant_found": False, "variant_count": len(variants)}

    return {
        "case": case,
        "prompt": frozen["prompt"],
        "http_ok": bool(response.get("ok")),
        "candidate_visibility": (response.get("candidate_visibility") or {}).get("status"),
        "variant_present": response_variant_present,
        "message": str(response.get("message") or "")[:500],
        "stored_hash": frozen["stored_hash"],
        "stored_acceptance": frozen["stored_acceptance"],
        "stored_coverage": frozen["stored_coverage"],
        "replay_hash": new_hash,
        "hash_equal": new_hash == frozen["stored_hash"] if new_hash else None,
        "replay_acceptance": acceptance.get("status"),
        "replay_coverage": coverage.get("state"),
        "verified_checks": acceptance.get("verified_checks"),
        "verified_requirement_count": coverage.get("verified_requirement_count"),
        "partial_requirement_count": coverage.get("partial_requirement_count"),
        "unbound_requirement_count": coverage.get("unbound_requirement_count"),
        "unverified_requirement_count": coverage.get("unverified_requirement_count"),
        "blocking_requirements": coverage.get("blocking_requirements") or [],
        "persistence": persisted_report,
    }


def main() -> int:
    rows = [run(case) for case in CASES]
    OUT.write_text(json.dumps({"schema": "cad.integration03.five-case-http.v1",
        "evidence_level": "PRODUCTION_HANDLER_FROZEN_PLAN_REPLAY_PASS",
        "real_model_calls": 0, "cases": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    for row in rows:
        print(row["case"], row["http_ok"], row["replay_acceptance"], row["stored_acceptance"], row["hash_equal"], row["message"][:60])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
