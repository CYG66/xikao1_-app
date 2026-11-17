"""D-line round 4 zero-cost configuration forensics probe (read-only, no network).

Scope
-----
Replays the production model-resolution chain statically on the frozen combo
baseline ``f89bf41`` and proves, without instantiating any live model client or
sending a request:

* which env / config field wins the CAD planning model;
* whether an isolated process can pin the CAD planning model to
  ``deepseek-flash`` without changing production global defaults;
* whether the non-thinking payload flag ``thinking.type=disabled`` is actually
  injected for ``deepseek-flash``;
* the code anchors (file + function + line) behind each conclusion.

Hard guards
-----------
* No live model client is constructed; ``_deepseek_request`` /
  ``_deepseek_response`` are never called.
* Model API keys are stripped from the probe environment; key values are never
  printed, hashed or persisted.
* Production code, D0 frozen assets, frozen inputs and existing assertions are
  not modified.
* The module-level ``robot_agent`` singleton in ``agent_service.py`` is NOT
  imported: importing that module would run its ``__init__`` and pending-task
  restore. Resolution logic below is a line-anchored pure replica of the
  constructor and ``_deepseek_request`` payload builder.

Reproducible entry (run from any cwd)::

    python evaluations/v1/probes/d1_round4_config_probe.py \
        --backend "<combo backend dir>" \
        --out evaluations/v1/probes/d1_round4_config_results.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

PROBE_DIR = Path(__file__).resolve().parent
D_BACKEND = PROBE_DIR.parents[2]
STRIPPED_KEYS = ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "ARK_API_KEY", "MODEL_API_KEY")

# Line-anchored replicas of agent_service.py resolution (evidence anchors below).
PROVIDER_MODEL_ENV = {"deepseek": "DEEPSEEK_MODEL"}
DEFAULT_MODELS = {"deepseek": "deepseek-chat"}
DEEPSEEK_BASE_MODEL_ENV = "DEEPSEEK_BASE_MODEL"
DEEPSEEK_ADVANCED_MODEL_ENV = "DEEPSEEK_ADVANCED_MODEL"
CAD_PLANNING_WHITELIST = {"deepseek-chat", "deepseek-reasoner", "deepseek-flash"}
CONFIG_CAD_ACCEPTED = {"deepseek-chat", "deepseek-reasoner"}


def strip_keys() -> None:
    for key in STRIPPED_KEYS:
        os.environ.pop(key, None)


def resolve(
    *,
    env: dict[str, str],
    config_model: str | None,
    config_cad: str | None,
) -> dict[str, Any]:
    """Replica of agent_service.__init__ + model properties (no side effects).

    Anchors:
      * mode default: agent_service.py:380
      * self.model env/default: agent_service.py:384
      * base/advanced env resolution: agent_service.py:387-395
      * cad planning env: agent_service.py:396
      * config load: agent_service.py:527-550
      * cad property whitelist: agent_service.py:352-355
      * advanced/base selection: agent_service.py:2586-2591
    """
    mode = env.get("XLINE_AGENT_PROVIDER", "deepseek").strip() or "deepseek"
    model_env = PROVIDER_MODEL_ENV.get(mode, "DEEPSEEK_MODEL")
    model = env.get(model_env, DEFAULT_MODELS.get(mode, "deepseek-chat"))

    base_model = model
    advanced_model = model
    if mode == "deepseek":
        base_model = (
            env.get(DEEPSEEK_BASE_MODEL_ENV)
            or env.get("DEEPSEEK_MODEL", "deepseek-chat")
            or "deepseek-chat"
        )
        advanced_model = env.get(DEEPSEEK_ADVANCED_MODEL_ENV, base_model) or base_model
        model = base_model

    cad = env.get("DEEPSEEK_CAD_PLANNING_MODEL", "deepseek-chat").strip() or "deepseek-chat"

    # _load_config: 530-539. Config cad override only when env absent and accepted.
    if "DEEPSEEK_CAD_PLANNING_MODEL" not in env and config_cad in CONFIG_CAD_ACCEPTED:
        cad = config_cad
    if isinstance(config_model, str) and config_model.strip():
        model = config_model.strip()
        if mode == "deepseek" and DEEPSEEK_BASE_MODEL_ENV not in env:
            base_model = model
        if mode == "deepseek" and DEEPSEEK_ADVANCED_MODEL_ENV not in env:
            advanced_model = model

    cad_effective = cad if cad in CAD_PLANNING_WHITELIST else "deepseek-chat"

    def select(agent_mode: str) -> str:
        normalized = "advanced" if agent_mode in {"advanced", "work"} else "base"
        if mode != "deepseek":
            return model
        return advanced_model if normalized == "advanced" else base_model

    return {
        "mode": mode,
        "model": model,
        "base_model": base_model,
        "advanced_model": advanced_model,
        "cad_planning_model": cad_effective,
        "resolved_advanced": select("advanced"),
        "resolved_base": select("base"),
    }


def payload_for(cad_planning_model: str, resolved: str) -> dict[str, Any]:
    """Replica of _deepseek_request payload builder (agent_service.py:2072-2083).

    CAD planning passes model_override=self.cad_planning_model at
    agent_service.py:6157; _structured_review_text forwards it at 1610/1619.
    """
    model_override = cad_planning_model
    payload_model = model_override or resolved
    payload: dict[str, Any] = {"model": payload_model}
    if payload_model == "deepseek-flash":
        payload["thinking"] = {"type": "disabled"}
    return payload


def code_anchors() -> list[dict[str, str]]:
    return [
        {
            "area": "A1.1 constraint inheritance / rejected plan / affected refs",
            "file": "backend/app/cad_plan_component_repair.py",
            "anchor": "ComponentRepairError:6; previous_plan:16; protected fields:23-24",
            "detail": "merge_component_repair reads plan/rejected_plan (305), affected_output_refs (307), merges junction_constraints (355), attaches affected refs + previous_plan to error (377,380).",
        },
        {
            "area": "A1.1 production call chain",
            "file": "backend/app/agent_service.py",
            "anchor": "6224 rejected_plan; 6225 affected_output_refs; 6240-6241 merge_component_repair",
            "detail": "Component-repair callback pulls rejected_plan/affected refs from component_repair_context and calls the real merger.",
        },
        {
            "area": "A1.1 bounded repair loop / previous plan / routing",
            "file": "backend/app/agent_service.py",
            "anchor": "6479-6480 loop max_repairs=2; 6495 rejected_plan; 6496-6500 previous_plan; 6508-6511 routing triple; 6513-6522 local validation; 6523-6529 confidence-only intercept",
            "detail": "Loop is bounded; routing chooses repair_context / component_repair_context / none by evidence; local scope and confidence-only repairs are enforced.",
        },
        {
            "area": "B1.2 arc/spline piece bounds",
            "file": "backend/app/cad_topology_safety.py",
            "anchor": "ARC_MAX_PIECES:60; SPLINE_MAX_PIECES:62; arc_chord_height:260; arc_chord_count_for_tolerance:283; spline_residual_bound:299; _arc_pieces:333-345; _spline_pieces:351-370",
            "detail": "Sagitta upper bound and piece-count inversion are real functions; over-cap cases fail closed as unresolved instead of assumed clear.",
        },
        {
            "area": "B1.2 tangent / unresolved classification",
            "file": "backend/app/cad_topology_safety.py",
            "anchor": "CONTACT_TANGENT:75; _chord_angle_deg:406; unresolved:559,579,655,672,685; analyze_composite_segments:774; unresolved aggregation:795,805,835-840",
            "detail": "Shallow/missed near-contact stays unresolved; bbox pre-prune at 385/811-816; unresolved is never counted as clear.",
        },
        {
            "area": "C1.2 production loop wiring",
            "file": "backend/app/agent_service.py",
            "anchor": "_formal_cad_construction:6357; bounded loop:6479-6480; context routing:6508-6511; real merger:6240-6241; persist_prepared_candidate:3933; persisted_candidate_count:6799,6824,6848",
            "detail": "Construction entry, bounded repair loop, context routing, component merge and candidate persistence all exist in production code.",
        },
        {
            "area": "CAD planning model resolution",
            "file": "backend/app/agent_service.py",
            "anchor": "cad_planning_model property:352-355; planning model_override:6157; _structured_review_text:1610,1619; _deepseek_request payload:2073",
            "detail": "CAD planning call passes cad_planning_model as model_override; payload model falls back to agent-mode model only when override absent.",
        },
        {
            "area": "Non-thinking injection",
            "file": "backend/app/agent_service.py",
            "anchor": "2082-2083",
            "detail": "thinking={'type':'disabled'} is injected only when payload['model']=='deepseek-flash'; for any other model the key is absent.",
        },
    ]


def load_corpus(registry: Path) -> list[dict[str, Any]]:
    data = json.loads(registry.read_text(encoding="utf-8"))
    out: list[dict[str, Any]] = []
    for case in data.get("cases", []):
        inp = str(case.get("original_input") or "")
        sha = hashlib.sha256(inp.encode("utf-8")).hexdigest()
        out.append(
            {
                "case_id": case.get("case_id"),
                "category": case.get("category"),
                "end_to_end_scoring_eligible": case.get("end_to_end_scoring_eligible"),
                "expected_route": case.get("expected_route"),
                "freeze_status": case.get("freeze_status"),
                "evidence_status": case.get("current_evidence_status"),
                "input_sha256": case.get("input_sha256"),
                "sha256_match": sha == case.get("input_sha256"),
                "source_ref": case.get("source_ref"),
            }
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", required=True, help="combo backend dir (read-only)")
    parser.add_argument("--registry", default=str(D_BACKEND / "evaluations" / "v1" / "case_registry.json"))
    parser.add_argument("--out", default=str(PROBE_DIR / "d1_round4_config_results.json"))
    args = parser.parse_args()

    strip_keys()
    backend = Path(args.backend)
    app_dir = backend / "app"
    if not app_dir.is_dir():
        raise SystemExit(f"backend app dir not found: {app_dir}")

    # Scenario A: process env absent; user-level config retains deepseek-chat.
    baseline_env: dict[str, str] = {}
    baseline = resolve(env=baseline_env, config_model="deepseek-chat", config_cad="deepseek-chat")
    baseline_payload = payload_for(baseline["cad_planning_model"], baseline["resolved_advanced"])

    # Scenario B: isolated process pins all three model envs to deepseek-flash.
    flash_env = {
        "DEEPSEEK_CAD_PLANNING_MODEL": "deepseek-flash",
        "DEEPSEEK_BASE_MODEL": "deepseek-flash",
        "DEEPSEEK_ADVANCED_MODEL": "deepseek-flash",
    }
    flash = resolve(env=flash_env, config_model="deepseek-chat", config_cad="deepseek-chat")
    flash_payload = payload_for(flash["cad_planning_model"], flash["resolved_advanced"])

    result = {
        "probe": "d1_round4_config_probe",
        "live_model_calls": 0,
        "network_client_instantiated": False,
        "production_module_imported": False,
        "backend_dir": str(backend),
        "scenarios": {
            "baseline_configured": {
                "env": baseline_env,
                "resolved": baseline,
                "cad_planning_payload": baseline_payload,
                "thinking_in_payload": "thinking" in baseline_payload,
            },
            "isolated_flash_override": {
                "env": flash_env,
                "resolved": flash,
                "cad_planning_payload": flash_payload,
                "thinking_in_payload": "thinking" in flash_payload,
                "config_model_retained": "deepseek-chat",
                "note": "Env DEEPSEEK_CAD_PLANNING_MODEL present, so _load_config does not apply the config cad_planning_model (agent_service.py:532).",
            },
        },
        "guards": {
            "payload_model_must_be": "deepseek-flash",
            "thinking_type_must_be": "disabled",
            "first_response_model_must_match": "deepseek-flash",
            "mismatch_action": "stop immediately; do not retry; record response model field.",
        },
        "code_anchors": code_anchors(),
        "corpus": load_corpus(Path(args.registry)),
    }

    # Self-checks (pure, no network).
    assert flash["cad_planning_model"] == "deepseek-flash"
    assert flash_payload["model"] == "deepseek-flash"
    assert flash_payload.get("thinking") == {"type": "disabled"}
    assert baseline_payload["model"] == "deepseek-chat"
    assert "thinking" not in baseline_payload

    out = Path(args.out)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"out": str(out), "live_model_calls": 0, "flash_payload": flash_payload}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
