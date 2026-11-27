"""INTEGRATION-03 P0 frozen-response HTTP replay.

All model calls are replaced by a frozen callback that returns the persisted
construction interpretation. Real model requests remain zero.
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
from app.cad_construction_interpreter import interpret_construction_request  # noqa: E402
from app.conversation_memory import ConversationMemoryStore  # noqa: E402
from app.creative_projects import CreativeProjectStore  # noqa: E402
from app.schemas import AgentChatRequest  # noqa: E402

RUNS = Path(r"C:\Users\29924\Codes\xikao\cad_e2e_generalization_live_01\runs\GENERALIZATION-01")
OUT = Path(r"C:\Users\29924\Codes\xikao\cad_core_generalization_integration_03")
OUT.mkdir(parents=True, exist_ok=True)

CASES = ["B04", "M01", "M02", "M03", "M04", "F01", "T01", "T04"]
EXTRA = ["B01", "B02", "B03", "F03", "T02", "Q01", "Q03", "Q04"]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def request_message(case: str) -> str:
    return str(load_json(RUNS / case / "request-1.json")["message"])


def find_record(node: Any) -> dict[str, Any] | None:
    if isinstance(node, dict):
        record = node.get("construction_record")
        if isinstance(record, dict) and isinstance(record.get("plan"), dict):
            return record
        for value in node.values():
            found = find_record(value)
            if found:
                return found
    elif isinstance(node, list):
        for value in node:
            found = find_record(value)
            if found:
                return found
    return None


def frozen_record(case: str) -> dict[str, Any] | None:
    service = RUNS / case / "service-step-1.json"
    if service.exists():
        return find_record(load_json(service))
    return None


def evidence_list(record: dict[str, Any], prompt: str) -> list[str]:
    value = record.get("evidence_text") or prompt
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]


def run_case(case: str, *, use_frozen_plan: bool = True) -> dict[str, Any]:
    prompt = request_message(case)
    record = frozen_record(case) if use_frozen_plan else None
    work = Path(tempfile.mkdtemp(prefix=f"int03-{case}-"))
    project_path = work / "projects.json"
    store = CreativeProjectStore(project_path)
    memory = ConversationMemoryStore(work / "memory.json")
    captured: dict[str, Any] = {}

    def route(_message: str, _mode: str, _history=None) -> dict[str, Any]:
        return {
            "name": "drawing_design",
            "tool_family": "cad",
            "operation": "create",
            "decision_source": "integration_03_frozen_http_replay",
        }

    def callback(_text: str, _schema: dict[str, Any]) -> dict[str, Any]:
        assert record is not None
        return {
            "schema_version": "cad.construction-interpretation.v1",
            "is_construction_request": True,
            "plan": record["plan"],
            "evidence_text": evidence_list(record, prompt),
            "assumptions": record.get("assumptions") or [],
            "confidence": 1.0,
        }

    def interpreter(message: str, mode: str | None = None, **_kwargs) -> dict[str, Any]:
        if record is None:
            return interpret_construction_request(message)
        return interpret_construction_request(message, callback, force_structured_model=True)

    for module in (agent_service, agent_http_service):
        setattr(module, "get_creative_project_store", lambda: store)
        setattr(module, "conversation_memory", memory)
    agent_service.robot_agent.mode = "local"
    agent_service.robot_agent.api_keys = {}
    agent_service.robot_agent.resolve_intent = route
    agent_service.robot_agent.route_intent = route
    agent_service.robot_agent._interpret_cad_construction_plan = interpreter

    response = agent_chat(
        AgentChatRequest(
            message=prompt,
            mode="advanced",
            conversation_id=f"int03-{case}",
            client_id="integration-03",
        )
    )
    captured.update(response)
    variant = response.get("variant") or {}
    response_variant_present = bool(variant)
    construction = variant.get("construction_record") or {}
    acceptance = variant.get("acceptance_summary") or {}
    source_acceptance = construction.get("source_acceptance") or {}
    coverage = source_acceptance.get("coverage_evidence") or {}
    recovery = construction.get("recovery") or {}
    residual = construction.get("residual_vector") or recovery.get("final_residual_vector") or {}
    acceptance_detail = {
        "status": acceptance.get("status"),
        "verified_checks": acceptance.get("verified_checks"),
        "coverage_state": coverage.get("state"),
        "verified_requirement_count": coverage.get("verified_requirement_count"),
        "partial_requirement_count": coverage.get("partial_requirement_count"),
        "unbound_requirement_count": coverage.get("unbound_requirement_count"),
        "unverified_requirement_count": coverage.get("unverified_requirement_count"),
        "blocking_requirements": coverage.get("blocking_requirements") or [],
        "residual_vector_present": bool(residual),
        "residual_record_count": residual.get("record_count"),
        "failing_numeric_count": residual.get("failing_numeric_count"),
        "unverifiable_count": residual.get("unverifiable_count"),
        "repair_present": construction.get("repair") is not None,
        "local_repair_validation_present": construction.get("local_repair_validation") is not None,
    }

    live_hash = (
        construction.get("geometry_hash")
        or variant.get("geometry_hash")
        or (variant.get("versions") or [{}])[-1].get("geometry_hash")
    )

    reload_report: dict[str, Any] = {"reloaded": False}
    project_id = response.get("project_id") or (variant.get("project_id") if isinstance(variant, dict) else None)
    if project_id and Path(project_path).exists():
        reloaded = CreativeProjectStore(project_path).get(str(project_id))
        if reloaded:
            variants = reloaded.get("variants") or []
            match = next((item for item in variants if item.get("id") == variant.get("id")), None)
            if match is None and not variant and len(variants) == 1:
                match = variants[0]
                variant = match
            persisted = (match or {}).get("construction_record") or {}
            reload_hash = (
                persisted.get("geometry_hash")
                or (match or {}).get("geometry_hash")
                or ((match or {}).get("versions") or [{}])[-1].get("geometry_hash")
            )
            reload_report = {
                "reloaded": True,
                "variant_found": match is not None,
                "geometry_hash": reload_hash,
                "hash_equal": reload_hash == live_hash if live_hash or reload_hash else None,
                "variant_count": len(variants),
            }
            if variant and not acceptance:
                construction = variant.get("construction_record") or {}
                acceptance = variant.get("acceptance_summary") or {}
                source_acceptance = construction.get("source_acceptance") or {}
                coverage = source_acceptance.get("coverage_evidence") or {}
                recovery = construction.get("recovery") or {}
                residual = construction.get("residual_vector") or recovery.get("final_residual_vector") or {}
                acceptance_detail = {
                    "status": acceptance.get("status"),
                    "verified_checks": acceptance.get("verified_checks"),
                    "coverage_state": coverage.get("state"),
                    "verified_requirement_count": coverage.get("verified_requirement_count"),
                    "partial_requirement_count": coverage.get("partial_requirement_count"),
                    "unbound_requirement_count": coverage.get("unbound_requirement_count"),
                    "unverified_requirement_count": coverage.get("unverified_requirement_count"),
                    "blocking_requirements": coverage.get("blocking_requirements") or [],
                    "residual_vector_present": bool(residual),
                    "residual_record_count": residual.get("record_count"),
                    "failing_numeric_count": residual.get("failing_numeric_count"),
                    "unverifiable_count": residual.get("unverifiable_count"),
                    "repair_present": construction.get("repair") is not None,
                    "local_repair_validation_present": construction.get("local_repair_validation") is not None,
                }
                live_hash = (
                    construction.get("geometry_hash")
                    or variant.get("geometry_hash")
                    or (variant.get("versions") or [{}])[-1].get("geometry_hash")
                )
                reload_report["geometry_hash"] = live_hash
                reload_report["hash_equal"] = live_hash == persisted.get("geometry_hash") if persisted.get("geometry_hash") else None

    return {
        "case": case,
        "prompt": prompt,
        "frozen_plan": record is not None,
        "http_ok": bool(response.get("ok")),
        "clarification": bool(response.get("clarification")),
        "candidate_visibility": (response.get("candidate_visibility") or {}).get("status"),
        "variant_present": response_variant_present,
        "variant_id": variant.get("id"),
        "project_id": project_id,
        "message": str(response.get("message") or "")[:600],
        "acceptance_status": acceptance.get("status"),
        "acceptance_detail": acceptance_detail,
        "coverage_state": coverage.get("state"),
        "geometry_hash": live_hash,
        "geometry_count": len(variant.get("geometries") or []),
        "persistence": reload_report,
    }


def main() -> int:
    results = []
    for case in CASES + EXTRA:
        record = frozen_record(case)
        result = run_case(case, use_frozen_plan=record is not None)
        results.append(result)
        print(json.dumps(result, ensure_ascii=False))
    payload = {"schema": "cad.integration-03.http-replay.v1", "cases": results}
    (OUT / "http_replay.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"written {OUT / 'http_replay.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
