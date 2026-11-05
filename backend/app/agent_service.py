from __future__ import annotations

import json
from .project_ownership import owned_request
import hashlib
import math
import os
import re
import http.client
import socket
import threading
import time
import urllib.error
import urllib.request
import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .audit_store import agent_audit
from .agent_skills import (
    DRAWING_TEMPLATE_SKILLS,
    _template_layout_requirements,
    apply_drawing_modifications,
    check_drawing_feasibility,
    analyze_geometry_topology,
    build_template_logical_object_graph,
    calculate_geometry_bounds,
    diff_drawings,
    inspect_drawing,
    list_elements,
    clarify_requirements,
    drawing_template_geometries,
    drawing_template_motion_steps,
    layer_drawing_paths,
    validate_preview_paths,
    parameterize_design,
    recommend_recovery,
    recognize_drawing_template,
    recognize_drawing_template_set,
    compose_template_instance_count,
    normalize_template_layout_for_matches,
    score_design_variant,
    snapshot_drawing,
    validate_drawing,
    validate_template_layout,
)
from .agent_policy import agent_tool_allowed, agent_tool_policy, normalize_policy_mode
from .agent_plan_runtime import agent_plan_runtime
from .agent_service_context import (
    conversation_id_from_route,
    merge_design_requirements,
    project_id_from_route,
)
from .agent_service_config import (
    DEEPSEEK_ADVANCED_MODEL_ENV,
    DEEPSEEK_BASE_MODEL_ENV,
    DEFAULT_MODELS,
    PROVIDER_API_KEY_ENV,
    PROVIDER_MODEL_ENV,
    PROVIDERS,
)
from .agent_service_policy import SAFE_TOOL_NAMES, SYSTEM_PROMPT
from .answer_validation import validate_agent_answer
from .structured_usage import record_structured_usage, merge_structured_usage
from .structured_usage import structured_model_fallback, remember_structured_model_fallback
from .fault_evaluation import evaluate_live_vehicle
from .diagnostics import build_link_diagnosis
from .deepseek_transport import DeepSeekTransport
from .creative_projects import get_creative_project_store
from .conversation_memory import conversation_memory
from .database import xline_database
from .creative_workflow import (
    build_project_acceptance_report,
    prepare_project_plan,
    prepare_project_recovery,
    project_recovery_assessment,
    refresh_project_execution,
    refresh_project_plan,
)
from .drawing_store import (
    available_drawings,
    build_path_preview_contract,
    cad_directory,
    drawing_execution_ready,
    geometry_preview_paths,
    preview_paths,
    resolve_drawing,
)
from .drawing_versions import DuplicateDrawingOperationError, drawing_versions
from .geometry_diff import (
    build_diff_preview_paths,
    build_drawing_change_review,
    build_geometry_diff,
    build_path_impact,
)
from .geometry_catalog import build_geometry_catalog
from .incremental_cad import (
    add_symmetric_rectangles_on_circle,
    edit_candidate_geometries,
    parse_constrained_addition,
    parse_incremental_edit,
    space_two_instances,
)
from .cad_edit_chain import parse_incremental_edit_chain, replay_cad_edit_chain
from .cad_target_resolver import (
    bind_resolved_target,
    logical_object_topology_conflict,
    resolve_cad_target,
    resolve_logical_object_target,
    validate_split_shared_boundary_target,
    validate_logical_object_target,
)
from .cad_edit_contract import (
    build_cad_edit_chain_contract,
    build_cad_edit_contract,
    cad_edit_contract_to_edit,
)
from .cad_edit_intent import (
    apply_intent_metadata,
    build_cad_edit_intent,
    cad_edit_intent_clarification,
)
from .cad_counterfactual_guard import (
    validate_counterfactual_followup,
    validate_counterfactual_guard_report,
)
from .cad_edit_interpreter import parse_structured_cad_interpretation
from .cad_construction_interpreter import (
    clarify_construction_request,
    interpret_construction_request,
    parse_rule_construction_plan,
)
from .cad_structure_contract import reference_contract, explicit_composition
from .cad_generation_recovery import (
    should_repair, recovery_record, confidence_only_repair,
    bounded_repair_available,
)
from .cad_requirement_ledger import project_requirement_ledger
from .cad_creation_intent import has_compound_primitives
from .cad_creation_intent import local_creation_objects
from .cad_construction_commit import (
    ConstructionCommitError,
    commit_construction_interpretation,
)
from .cad_edit_plan import build_cad_edit_plan
from .cad_composition_addition import parse_relative_additions, execute_relative_additions
from .cad_edit_preview import build_cad_edit_preview, validate_cad_edit_preview
from .cad_assertions import (
    build_cad_machine_assertions,
    repair_cad_machine_assertions_once,
)
from .cad_edit_gate import (
    build_rejection_rollback_evidence,
    build_cad_edit_preflight,
    geometry_fingerprint,
    validate_target_change_scope,
)
from .cad_project_candidates import (
    candidate_generation_context,
    candidate_response_payload,
    design_geometries_for_project,
    effective_parent_variant,
    is_generator_supported_shape,
    normalize_design_requirements,
    normalize_model_geometry_units,
    project_logical_graph,
    template_instance_assessment,
)
from .cad_candidate_orchestrator import (
    candidate_preflight,
    design_confirmation_gate,
    persist_candidate_variant,
    persist_prepared_candidate,
    prepare_new_candidate,
    restore_existing_candidate,
)
from .knowledge_retrieval import project_knowledge
from .logical_topology import evolve_logical_graph_for_edit
from .ros_adapter import ros_adapter
from .state import robot_state
from .task_store import agent_tasks
from .request_context import bind_agent_user_id, current_agent_user_id
from .user_model_config import user_model_config
from .model_providers import provider_adapter
from .model_request_gateway import (
    request_openai_responses_json,
    request_provider_tool_json,
)
from .user_request_limits import user_request_limiter
from .telemetry_contract import (
    build_mission_contract,
    build_printer_contract,
    build_telemetry_contract,
)
from .tooling import (
    OPENAI_TOOLS,
    TOOL_REGISTRY,
    authorize_tool,
    build_action_preflight,
    validate_tool_arguments,
)


def _extract_upper_bound_dimensions(text: str) -> dict[str, float]:
    """Extract range-style dimensions ("宽不超过5米/最多3米/上限4米").

    ``parameterize_design`` extracts only explicit equality sizes; expressions
    like "宽不超过5米" return empty dimensions.  This fallback turns the upper
    bound into a usable width/height so clarified requirements always carry
    concrete numbers for the confirmation gate and generators.
    """
    if not text:
        return {}
    result: dict[str, float] = {}
    patterns = {
        "width_m": r"(?:宽|横向|左右)(?:度)?(?:不超过|最多|上限|最大|至多|至多)?\s*([\d.]+)\s*(?:米|m)",
        "height_m": r"(?:高|纵向|上下)(?:度)?(?:不超过|最多|上限|最大|至多|至多)?\s*([\d.]+)\s*(?:米|m)",
    }
    for key, pattern in patterns.items():
        # Explicit whole-drawing dimensions outrank local component sizes,
        # regardless of their order in a multi-clause supplement.
        axis = '宽' if key == 'width_m' else '高'
        overall = re.search(
            r'(?:整体|总体|总)\s*' + axis
            + r'(?:度)?\s*(?:为|是|=|：|:)?\s*([\d.]+)\s*(?:米|m)', text)
        match = overall or re.search(pattern, text)
        if match:
            try:
                result[key] = float(match.group(1))
            except (TypeError, ValueError):
                pass
    if not result:
        # 兜底：单个"不超过 N 米"同时约束宽高
        match = re.search(r"不超过|最多|上限|最大|至多\s*([\d.]+)\s*(?:米|m)", text)
        if match:
            try:
                value = float(match.group(1))
            except (TypeError, ValueError):
                value = 0.0
            if value > 0:
                result = {"width_m": value, "height_m": value}
    if not result:
        # 等尺寸："长宽均为5m/宽高都为5米/长和宽都是3米"——同一数值同时
        # 约束宽高（parameterize_design 与上限模式都不覆盖这类表达）。
        match = re.search(
            r"(?:长宽|宽高|长和宽|宽和高|长与宽|宽与高|边长)"
            r"(?:均|都|都是|均为|都为|是|为)?\s*"
            r"([\d.]+)\s*(?:米|m)",
            text,
            re.IGNORECASE,
        )
        if match:
            try:
                value = float(match.group(1))
            except (TypeError, ValueError):
                value = 0.0
            if value > 0:
                result = {"width_m": value, "height_m": value}
    return result


# Generated from Pydantic models in tooling.py.
TOOLS = OPENAI_TOOLS
MODEL_HIDDEN_TOOLS = frozenset()
DEEPSEEK_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["parameters"],
            "strict": True,
        },
    }
    for tool in OPENAI_TOOLS
]


@dataclass
class PendingAction:
    name: str
    arguments: dict[str, Any]
    expires_at: datetime
    mode: str = "base"
    owner_id: str = "local-default"


class RobotAgentService:
    @property
    def _active_user_profile(self) -> dict[str, Any] | None:
        owner = current_agent_user_id()
        return None if owner == "local-default" else user_model_config.get(owner)

    @property
    def mode(self) -> str:
        profile = self._active_user_profile
        return str(profile.get("mode")) if profile and profile.get("mode") else getattr(self, "_mode", "deepseek")

    @mode.setter
    def mode(self, value: str) -> None:
        self._mode = value

    @mode.deleter
    def mode(self) -> None:
        self.__dict__.pop("_mode", None)

    @property
    def model(self) -> str:
        profile = self._active_user_profile
        return str(profile.get("model")) if profile and profile.get("model") else getattr(self, "_model", "deepseek-chat")

    @model.setter
    def model(self, value: str) -> None:
        self._model = value

    @model.deleter
    def model(self) -> None:
        self.__dict__.pop("_model", None)

    @property
    def base_model(self) -> str:
        profile = self._active_user_profile
        return str(profile.get("base_model")) if profile and profile.get("base_model") else getattr(self, "_base_model", self.model)

    @base_model.setter
    def base_model(self, value: str) -> None:
        self._base_model = value

    @base_model.deleter
    def base_model(self) -> None:
        self.__dict__.pop("_base_model", None)

    @property
    def advanced_model(self) -> str:
        profile = self._active_user_profile
        return str(profile.get("advanced_model")) if profile and profile.get("advanced_model") else getattr(self, "_advanced_model", self.model)

    @advanced_model.setter
    def advanced_model(self, value: str) -> None:
        self._advanced_model = value

    @advanced_model.deleter
    def advanced_model(self) -> None:
        self.__dict__.pop("_advanced_model", None)

    @property
    def cad_planning_model(self) -> str:
        profile = self._active_user_profile
        value = str((profile or {}).get("cad_planning_model") or getattr(self, "_cad_planning_model", "deepseek-chat"))
        return value if value in {"deepseek-chat", "deepseek-reasoner"} else "deepseek-chat"

    @property
    def api_keys(self) -> dict[str, str]:
        profile = self._active_user_profile
        if profile is not None:
            return profile.setdefault("api_keys", {})
        return getattr(self, "_api_keys", {})

    @api_keys.setter
    def api_keys(self, value: dict[str, str]) -> None:
        self._api_keys = value

    @api_keys.deleter
    def api_keys(self) -> None:
        self.__dict__.pop("_api_keys", None)

    @staticmethod
    def normalize_agent_mode(mode: str | None) -> str:
        return "advanced" if mode in {"advanced", "work"} else "base"

    def __init__(self, *, restore_pending_actions: bool = True) -> None:
        self.pending: dict[str, PendingAction] = {}
        self._pending_lock = threading.RLock()
        self.config_path = Path.home() / ".config" / "xline-agent.json"
        self.mode = os.getenv("XLINE_AGENT_PROVIDER", "deepseek").strip()
        if self.mode not in {*PROVIDERS, "local"}:
            self.mode = "deepseek"
        model_env = PROVIDER_MODEL_ENV.get(self.mode, "DEEPSEEK_MODEL")
        self.model = os.getenv(model_env, DEFAULT_MODELS.get(self.mode, "deepseek-chat"))
        self.base_model = self.model
        self.advanced_model = self.model
        if self.mode == "deepseek":
            self.base_model = os.getenv(
                DEEPSEEK_BASE_MODEL_ENV,
                os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            ).strip() or "deepseek-chat"
            self.advanced_model = os.getenv(
                DEEPSEEK_ADVANCED_MODEL_ENV, self.base_model
            ).strip() or self.base_model
            self.model = self.base_model
        self._cad_planning_model = os.getenv("DEEPSEEK_CAD_PLANNING_MODEL", "deepseek-chat").strip() or "deepseek-chat"
        self.api_keys: dict[str, str] = {}
        # DeepSeek requests must not share a connection or a process-wide lock.
        # FastAPI already runs these synchronous handlers in its worker pool;
        # one connection per request lets independent users progress together.
        self._deepseek_connect_timeout = self._env_timeout(
            "XLINE_AGENT_DEEPSEEK_CONNECT_TIMEOUT_SECONDS", 10.0, maximum=120.0
        )
        self._deepseek_read_timeout = self._env_timeout(
            "XLINE_AGENT_DEEPSEEK_READ_TIMEOUT_SECONDS", 30.0, maximum=300.0
        )
        self._deepseek_request_timeout = self._env_timeout(
            "XLINE_AGENT_DEEPSEEK_REQUEST_TIMEOUT_SECONDS", 90.0, maximum=900.0
        )
        for provider, env_name in PROVIDER_API_KEY_ENV.items():
            value = os.getenv(env_name, "").strip()
            if value:
                self.api_keys[provider] = value
        self._load_config()
        if restore_pending_actions:
            self._restore_pending_actions()

    def _restore_pending_actions(self) -> None:
        for task in agent_tasks.recoverable_pending():
            try:
                name = str(task["tool"])
                mode = normalize_policy_mode(str(task.get("agent_mode") or "base"))
                policy = agent_tool_policy(name, mode)
                arguments, validation_error = validate_tool_arguments(
                    name, dict(task["arguments"])
                )
                if not policy["allowed"] or arguments is None:
                    reason = (
                        policy["reason"]
                        if not policy["allowed"]
                        else f"任务参数无效：{validation_error}"
                    )
                    agent_tasks.transition(
                        str(task["id"]), "failed", reason,
                        {"ok": False, "message": reason, "policy": policy},
                    )
                    continue
                expires_at = (
                    datetime.fromisoformat(str(task["expires_at"]))
                    .astimezone()
                    .replace(tzinfo=None)
                )
                self.pending[str(task["id"])] = PendingAction(
                    name=name,
                    arguments=arguments,
                    expires_at=expires_at,
                    mode=mode,
                    owner_id=str(task.get("owner_id") or "local-default"),
                )
            except (KeyError, TypeError, ValueError) as error:
                task_id = str(task.get("id") or "")
                if task_id:
                    reason = f"待确认任务恢复失败：{error}"
                    agent_tasks.transition(
                        task_id, "failed", reason,
                        {"ok": False, "message": reason},
                    )

    @property
    def api_key(self) -> str:
        return self.api_keys.get(self.mode, "")

    @property
    def configured(self) -> bool:
        return self.mode == "local" or bool(self.api_key)

    def config(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "model": self.model,
            "base_model": self.base_model,
            "advanced_model": self.advanced_model,
            "cad_planning_model": self.cad_planning_model,
            "configured": self.configured,
            "api_key_configured": bool(self.api_key),
            "provider": self.mode,
            "configured_providers": sorted(self.api_keys),
        }

    def update_config(
        self,
        mode: str,
        model: str,
        api_key: str | None = None,
        clear_api_key: bool = False,
        cad_planning_model: str | None = None,
    ) -> dict[str, Any]:
        owner = current_agent_user_id()
        if owner != "local-default":
            user_model_config.update(
                owner,
                mode=mode,
                model=model.strip(),
                api_key=api_key,
                clear_api_key=clear_api_key,
                cad_planning_model=cad_planning_model,
            )
            return self.config()
        self.mode = mode
        self.model = model.strip()
        if self.mode == "deepseek":
            self.base_model = self.model
            self.advanced_model = self.model
        else:
            self.base_model = self.model
            self.advanced_model = self.model
        if cad_planning_model is not None:
            self._cad_planning_model = cad_planning_model
        if clear_api_key:
            self.api_keys.pop(self.mode, None)
        elif api_key is not None and api_key.strip():
            self.api_keys[self.mode] = api_key.strip()
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(
                {"mode": self.mode, "model": self.model, "api_keys": self.api_keys,
                 "cad_planning_model": self.cad_planning_model},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        os.chmod(self.config_path, 0o600)
        return self.config()

    def _load_config(self) -> None:
        try:
            payload = json.loads(self.config_path.read_text(encoding="utf-8"))
            if payload.get("mode") in {*PROVIDERS, "local"}:
                self.mode = payload["mode"]
            if not os.getenv("DEEPSEEK_CAD_PLANNING_MODEL") and payload.get("cad_planning_model") in {"deepseek-chat", "deepseek-reasoner"}:
                self._cad_planning_model = payload["cad_planning_model"]
            if isinstance(payload.get("model"), str) and payload["model"].strip():
                self.model = payload["model"].strip()
                if self.mode == "deepseek" and not os.getenv(DEEPSEEK_BASE_MODEL_ENV):
                    self.base_model = self.model
                if self.mode == "deepseek" and not os.getenv(DEEPSEEK_ADVANCED_MODEL_ENV):
                    self.advanced_model = self.model
            stored_keys = payload.get("api_keys")
            if isinstance(stored_keys, dict):
                self.api_keys.update(
                    {
                        str(provider): str(key).strip()
                        for provider, key in stored_keys.items()
                        if provider in PROVIDERS and isinstance(key, str) and key.strip()
                    }
                )
            elif isinstance(payload.get("api_key"), str) and payload["api_key"].strip():
                self.api_keys[self.mode] = payload["api_key"].strip()
        except (OSError, json.JSONDecodeError):
            pass

    def test_connection(self) -> dict[str, Any]:
        if self.mode == "local":
            return {"ok": True, "message": "本地诊断助手可用，无需 API Key。"}
        if not self.api_key:
            return {"ok": False, "message": "请先填写并保存 API Key。"}
        provider_name, base_url = PROVIDERS[self.mode]
        adapter = provider_adapter(self.mode)
        if self.mode == "anthropic":
            url = f"{base_url}/models/{self.model}"
            headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}
        elif self.mode == "gemini":
            url = f"{base_url.rstrip('/')}/models/{self.model}"
            headers = {"x-goog-api-key": self.api_key}
        elif self.mode == "deepseek":
            # DeepSeek exposes an OpenAI-compatible model collection endpoint,
            # not GET /models/{model}. Authentication is validated by the list call.
            url = f"{base_url}/models"
            headers = {"Authorization": f"Bearer {self.api_key}"}
        else:
            url = f"{base_url}/models/{self.model}"
            headers = {"Authorization": f"Bearer {self.api_key}"}
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return {
                    "ok": response.status == 200,
                    "message": f"{provider_name} 服务连接成功。",
                }
        except urllib.error.HTTPError as error:
            return {"ok": False, "message": f"API Key 或模型不可用（{error.code}）。"}
        except urllib.error.URLError as error:
            return {"ok": False, "message": f"无法连接 {provider_name}：{error.reason}"}

    @owned_request
    def chat(
        self,
        message: str,
        history: list[dict[str, str]],
        *,
        mode: str = "chat",
        route: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        resolved_route = self._with_edit_domain(
            route or self.resolve_intent(message, mode, history)
        )
        return agent_plan_runtime.run(
            message,
            resolved_route,
            lambda: self._chat_impl(
                message,
                history,
                mode=mode,
                route=resolved_route,
            ),
            project_id=str(resolved_route.get("selected_project_id") or "") or None,
            variant_id=str(resolved_route.get("selected_variant_id") or "") or None,
        )

    def _chat_impl(
        self,
        message: str,
        history: list[dict[str, str]],
        *,
        mode: str = "chat",
        route: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        mode = self.normalize_agent_mode(mode)
        route = route or self.resolve_intent(message, mode, history)
        if route.get("decision_source") == "affirmative_followup":
            followup = self._confirmed_movement_followup(route, mode)
            if followup is not None:
                return followup
        if route.get("clarification_required"):
            coordinate_complete = (
                route.get("name") == "drawing_design"
                and route.get("operation") == "create"
                and len(re.findall(r"[（(]\\s*[-+]?\\d", message)) >= 2
                and re.search(r"坐标单位(?:为|是)?\\s*(?:米|厘米|毫米|m|cm|mm)", message, re.I)
            )
            if coordinate_complete:
                route = {**route, "clarification_required": False,
                         "clarification_question": None}
            else:
                # A dimension-only reply can be ambiguous to the general router
                # while being complete in the explicitly selected CAD project.
                requirement_followup = (
                    self._apply_design_requirement_followup(message, route)
                    if mode == "advanced" and route.get("decision_source") == "model_clarification"
                    else None
                )
                if requirement_followup is not None:
                    return requirement_followup
                return self._result(
                    str(route.get("clarification_question") or "请明确本次要处理的操作。"),
                    self._empty_usage(),
                )
        stale_guide = self._stale_project_guard(route)
        if stale_guide is not None:
            return self._result(stale_guide, self._empty_usage())
        pending_design = self._pending_design_followup(raw_message=message, route=route)
        if pending_design is not None:
            return pending_design
        requirement_followup = self._apply_design_requirement_followup(message, route)
        if requirement_followup is not None:
            return requirement_followup
        raw_message = str(route.get("resolved_message") or message)
        if mode == "base":
            json_action = self._chat_json_movement(raw_message)
            if json_action is not None:
                return json_action
        # Advanced mode is API-first. Only base-mode deterministic controls
        # may use a local shortcut before the model is contacted.
        if mode == "base":
            local_action = self._local_intent(raw_message, allow_design=False, mode=mode)
            if local_action is not None:
                return local_action
            if route.get("name") == "drawing_design":
                return self._result(
                    "基础模式只支持底盘运动演示，不能生成精确图纸或规划路径。"
                    "要设计图纸并预览路径，请切换进阶模式后发送这条需求；不会自动启动小车。",
                    self._empty_usage(),
                )
        if mode == "advanced":
            route, cad_result = self._run_advanced_cad_pipeline(
                raw_message, history, route, mode=mode
            )
            if cad_result is not None:
                return cad_result
        message = self._mode_message(raw_message, mode)
        if self.mode == "local":
            return {
                "ok": True,
                "configured": True,
                "message": self._local_diagnosis(),
                "usage": self._empty_usage(),
                "pending_action": None,
            }
        if not self.configured:
            return {
                "ok": False,
                "configured": False,
                "message": (
                    "智能助手尚未配置。请在 App 设置中填写当前 AI 服务的 API Key，"
                    "或联系管理员配置小车后端后重试。"
                ),
                "usage": self._empty_usage(),
                "pending_action": None,
            }
        if self.mode == "deepseek":
            return self._deepseek_chat(
                message, history, mode=mode, route=route, context_message=raw_message
            )
        if self.mode in ("anthropic", "gemini"):
            return self._native_tool_chat(
                message, history, mode=mode, route=route, context_message=raw_message
            )
        if self.mode != "openai":
            return self._tool_agent_chat(
                message, history, mode=mode, route=route, context_message=raw_message
            )

        conversation = [
            {"role": item.get("role", "user"), "content": item.get("content", "")}
            for item in history[-4:]
            if item.get("content")
        ]
        conversation.append({"role": "user", "content": message})
        instructions = self._system_context(raw_message, mode=mode, route=route)
        first = self._request(conversation, instructions, mode=mode)
        usage = self._usage(first)
        calls = [item for item in first.get("output", []) if item.get("type") == "function_call"]

        if not calls:
            return self._result(self._output_text(first), usage)

        followup_items: list[dict[str, Any]] = list(conversation)
        followup_items.extend(first.get("output", []))
        tool_results: list[dict[str, Any]] = []
        for call in calls:
            name = str(call.get("name", ""))
            raw_arguments = self._arguments(call.get("arguments"))
            raw_arguments = self._bind_drawing_selection(name, raw_arguments, route)
            domain_error = self._edit_domain_tool_error(name, route)
            if domain_error:
                followup_items.append({
                    "type": "function_call_output",
                    "call_id": call.get("call_id"),
                    "output": json.dumps(
                        {"ok": False, "message": domain_error}, ensure_ascii=False
                    ),
                })
                continue
            if name in MODEL_HIDDEN_TOOLS:
                followup_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": call.get("call_id"),
                        "output": json.dumps(
                            {"ok": False, "message": "该工具仅供后端内部使用。"},
                            ensure_ascii=False,
                        ),
                    }
                )
                continue
            arguments, validation_error = validate_tool_arguments(name, raw_arguments)
            if arguments is None:
                followup_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": call.get("call_id"),
                        "output": json.dumps(
                            {"ok": False, "message": validation_error},
                            ensure_ascii=False,
                        ),
                    }
                )
                continue
            # The routed project is authoritative for an edit session. Model
            # tool calls can carry an id from an earlier conversation; bind
            # mutating project tools to the active route before dispatch.
            routed_project_id = route.get("selected_project_id") if isinstance(route, dict) else None
            if routed_project_id and name in {"update_creative_project", "select_design_variant"}:
                arguments = dict(arguments)
                arguments["project_id"] = str(routed_project_id)
            if name in SAFE_TOOL_NAMES:
                output = self._execute_safe(name, arguments, mode=mode)
                output = self._stale_project_tool_guide(
                    name, arguments, output, route
                )
                # A model may create a project and then update it in the same
                # tool-calling turn.  Persist the newly created identity into
                # the active route before dispatching the next call; otherwise
                # the second call still carries an empty/stale project_id.
                if (
                    isinstance(route, dict)
                    and name == "create_creative_project"
                    and isinstance(output, dict)
                ):
                    created = output.get("project")
                    created_id = (
                        str(created.get("id") or "").strip()
                        if isinstance(created, dict) else ""
                    )
                    if created_id:
                        route["selected_project_id"] = created_id
                        route["project_id"] = created_id
                tool_results.append(self._tool_result_summary(name, output))
                followup_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": call.get("call_id"),
                        "output": json.dumps(output, ensure_ascii=False),
                    }
                )
                continue

            policy = agent_tool_policy(name, mode)
            if not policy["allowed"]:
                return self._result(policy["reason"], usage)
            pending_action = self._register_pending(name, arguments, mode=mode)
            return self._result(
                self._confirmation_text(name, arguments),
                usage,
                pending_action,
            )

        second = self._request(followup_items, instructions, mode=mode)
        usage = self._add_usage(usage, self._usage(second))
        return self._result(self._output_text(second), usage, tool_results=tool_results)

    def _deepseek_chat(
        self,
        message: str,
        history: list[dict[str, str]],
        *,
        mode: str = "advanced",
        route: dict[str, Any] | None = None,
        context_message: str | None = None,
    ) -> dict[str, Any]:
        context_message = context_message or message
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": self._system_context(
                    context_message, mode=mode, route=route
                ),
            },
            *[
                {"role": item.get("role", "user"), "content": item.get("content", "")}
                for item in history[-4:]
                if item.get("content")
            ],
            {"role": "user", "content": message},
        ]
        selected_tools = self._selected_deepseek_tools(
            context_message, mode=mode, route=route
        )
        first = self._deepseek_request(messages, selected_tools, mode=mode)
        usage = self._chat_usage(first)
        choices = first.get("choices") or []
        model_message = choices[0].get("message", {}) if choices else {}
        calls = model_message.get("tool_calls") or []
        if not calls:
            content = str(model_message.get("content") or "")
            if mode == "base":
                json_action = self._chat_json_movement(content)
                if json_action is not None:
                    return json_action
            if mode == "advanced" and not content.strip():
                # A provider may return an empty advanced response. Candidate
                # generation stays inside the backend construction pipeline.
                recovered = self._recover_candidate_after_empty_response(
                    route or {}, mode
                )
                if recovered is not None:
                    return recovered
                return self._advanced_empty_response(route or {}, usage)
            return self._result(content, usage)

        normalized_calls = []
        for raw_call in calls:
            function = raw_call.get("function") or {}
            normalized_calls.append({
                "id": str(raw_call.get("id") or ""),
                "name": str(function.get("name") or ""),
                "arguments": str(function.get("arguments") or "{}"),
            })
        return self._streamed_tool_result(
            normalized_calls,
            usage,
            mode=mode,
            messages=messages,
            tools=selected_tools,
            route=route,
        )

    def _recover_candidate_after_empty_response(
        self, route: dict[str, Any], mode: str
    ) -> dict[str, Any] | None:
        """Re-enter the sole construction-plan producer for a confirmed project."""
        project_id = (
            str(route.get("selected_project_id") or "").strip()
            or self._project_id_from_route(route)
        )
        project = get_creative_project_store().get(project_id) if project_id else None
        # The router may have persisted a generic construction confirmation
        # for this same turn before the CAD constructor runs.  An explicit
        # coordinate command with units is already complete; clear only that
        # stale scope marker so the command reaches the shared constructor.
        complete_coordinate_command = (
            len(re.findall(r"[（(]\\s*[-+]?\\d", raw_followup)) >= 2
            and re.search(r"坐标单位(?:为|是)?\\s*(?:米|厘米|毫米|m|cm|mm)", raw_followup, re.I)
        )
        if (complete_coordinate_command and isinstance(project, dict)
                and (project.get("requirements") or {}).get("construction_scope") == "awaiting_confirmation"):
            requirements = dict(project.get("requirements") or {})
            requirements.pop("construction_scope", None)
            project = get_creative_project_store().update(
                str(project["id"]), requirements=requirements,
                missing_parameters=[], status="ready_for_design",
                event_message="已确认坐标命令完整，进入结构化构造",
            ) or project
        if project is None:
            return None
        if list(project.get("missing_parameters") or []):
            return None
        construction_route = dict(route)
        construction_route.update({
            "name": "drawing_design",
            "tool_family": "cad",
            "operation": "create",
            "selected_project_id": project_id,
            "stage": "candidate_generation",
        })
        return self._formal_cad_construction(
            "确认生成候选方案", construction_route, mode=mode
        )

    def _advanced_empty_response(
        self, route: dict[str, Any], usage: dict[str, int]
    ) -> dict[str, Any]:
        """Return a truthful workflow prompt when the model emits no text."""
        project_id = str(route.get("selected_project_id") or "").strip() or self._project_id_from_route(route)
        project = get_creative_project_store().get(project_id) if project_id else None
        status = str(project.get("status") or "") if isinstance(project, dict) else ""
        missing = list(project.get("missing_parameters") or []) if isinstance(project, dict) else []
        if status == "ready_for_design" and not missing:
            # 统一口径：与生成器共用同一判定。仅当试算能真正产出几何
            # 时才承诺"可以生成候选方案"，避免 missing_parameters 为空
            # 而 requirements 结构仍不满足生成器契约的假就绪。
            try:
                geometries, missing_geometry = design_geometries_for_project(project, {})
            except Exception:
                geometries, missing_geometry = None, []
            if geometries is None:
                # 需求已确认但该图形没有确定性生成器（非枚举自定义图形）：
                # 不能误导用户"还缺少图形类型和关键尺寸"，改为说明 AI 建模
                # 生成候选的路径，避免与澄清阶段的"已收到图形和尺寸"口径冲突。
                req = project.get("requirements") if isinstance(project, dict) else {}
                req = req if isinstance(req, dict) else {}
                shape_label = str(req.get("shape") or "")
                dims = req.get("dimensions") if isinstance(req.get("dimensions"), dict) else {}
                dimension_note = ""
                try:
                    width = float(dims.get("width_m") or 0)
                    height = float(dims.get("height_m") or 0)
                    if width > 0 and height > 0:
                        dimension_note = f"（尺寸 {width:g}×{height:g} m）"
                except (TypeError, ValueError):
                    dimension_note = ""
                if shape_label and shape_label != "generic_2d_cad":
                    message = (
                        f"需求已确认：{shape_label}{dimension_note}。"
                        "本次 AI 建模未生成有效候选，当前没有后台生成任务。"
                    )
                elif dimension_note:
                    # 尺寸已完整落库，只是图形类型未枚举（自定义/复合图形）：
                    # 不再报"还缺少关键尺寸"，明确由 AI 建模确认并生成。
                    message = (
                        f"尺寸已确认{dimension_note}。本次 AI 建模未生成有效候选，"
                        "当前没有后台生成任务。"
                    )
                else:
                    message = (
                        "还缺少生成候选方案所需的："
                        + "、".join(
                            str(item)
                            for item in (missing_geometry or ["图形类型和关键尺寸"])
                        )
                        + "。请先补充并确认这些参数。"
                    )
                result = self._result(message, usage)
                result.update(ok=False, error_code="candidate_generation_failed", next_action="retry_candidate_generation")
                return result
            message = "设计要求已确认，可以生成候选方案。"
        elif status == "designing":
            message = "候选方案已生成，请在方案区查看并选择。"
        elif missing:
            labels = {
                "shape": "图形类型",
                "dimensions": "关键尺寸",
                "printer": "喷码机",
                "origin": "起点位置",
            }
            message = "还需要补充：" + "、".join(
                labels.get(str(item), str(item)) for item in missing
            ) + "。"
        else:
            message = "本次回复未生成有效内容，请重新描述要绘制的图形和尺寸。"
        return self._result(message, usage)

    def _pending_design_followup(
        self, *, raw_message: str, route: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Keep short follow-ups attached to the active design project.

        A clarifying project must not fall through to a provider's generic
        chat answer.  This is especially important for inputs such as ``?``
        or ``继续``: they are workflow replies, not new general questions.
        """
        original = str(raw_message or "").strip().lower()
        normalized = re.sub(r"[\s，。！？、,.!?；;：:]+", "", original)
        if not self._is_design_generation_confirmation(raw_message) and original not in {"?", "？"} and normalized not in {
            "继续", "继续生成", "继续补充", "确认", "确认生成", "确认生成候选方案"
        }:
            return None
        project_id = self._project_id_from_route(route)
        project = get_creative_project_store().get(project_id) if project_id else None
        if not isinstance(project, dict):
            return None
        missing = [str(item) for item in project.get("missing_parameters") or []]
        labels = {
            "shape": "图形类型",
            "dimensions": "关键尺寸",
            "printer": "喷码机",
            "origin": "坐标原点",
        }
        if missing:
            return self._result(
                "当前项目还缺少："
                + "、".join(labels.get(item, item) for item in missing)
                + "。请直接补充这些参数；如果原要求已经包含它们，请重新发送原要求，我会继续使用当前项目。",
                self._empty_usage(),
            )
        if str(project.get("status") or "") in {"draft", "ready_for_design"}:
            next_route = dict(route)
            next_route["selected_project_id"] = str(project.get("id") or "")
            generated = self.generate_project_candidate(str(project["id"]))
            if generated is not None:
                return generated
            return self._result(
                "当前项目要求已经完整，可以生成候选方案；请点击“确认需求并生成候选方案”。",
                self._empty_usage(),
            )
        return None

    @staticmethod
    def _parse_units_followup(message: str) -> str | None:
        """Extract an explicit coordinate-unit answer such as "坐标单位为米"."""
        text = str(message or "").strip().lower()
        # 触发条件：含“单位”/units 词，或整句就是简短的单位声明
        # （“用毫米”“用米”“用cm”等），避免误吞带尺寸的普通消息。
        if "单位" not in text and "units" not in text and text not in {
            "用米", "用毫米", "用厘米", "用m", "用mm", "用cm",
        }:
            return None
        # 毫米/厘米必须先于“米”匹配，避免“毫米”被“米”误吞。
        for alias, value in (
            ("毫米", "mm"), ("mm", "mm"),
            ("厘米", "cm"), ("cm", "cm"),
            ("米", "m"), ("m", "m"),
        ):
            if alias in text:
                return value
        return None

    def _apply_design_requirement_followup(
        self, message: str, route: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Merge a parameter-only answer into the active design project.

        Supports one-at-a-time parameter completion: a sentence carrying
        numeric dimensions (``parameterize_design``) or an explicit units
        statement (``_parse_units_followup``), e.g. "坐标单位为米".
        """
        if self.normalize_agent_mode(str(route.get("mode") or "advanced")) != "advanced":
            return None
        if local_creation_objects(message):
            return None
        parsed = parameterize_design(message)
        dimensions = parsed.get("dimensions") if isinstance(parsed, dict) else None
        if not isinstance(dimensions, dict):
            dimensions = None
        units = self._parse_units_followup(message)
        project_id = str(route.get("selected_project_id") or "").strip() or self._project_id_from_route(route)
        project = get_creative_project_store().get(project_id) if project_id else None
        if not isinstance(project, dict) or str(project.get("status") or "") not in {
            "draft", "clarifying", "ready_for_design", "designing"
        }:
            return None
        # A project with no candidate has requirements to revise, not geometry
        # to edit. Recognize source-bound scalar corrections (e.g. 改为) even
        # when the legacy numeric index does not parse them.
        variants = project.get('variants') or []
        from .cad_candidate_state import candidate_is_accepted
        if any(candidate_is_accepted(v) for v in variants):
            return None
        current = dict(project.get("requirements") or {})
        source_turns=list(current.get('source_followups') or [])
        from .cad_requirement_contract import requirement_contract
        scalar=requirement_contract([{'source_id':f'turn-{i}', 'text':text}
            for i,text in enumerate([str(project.get('original_prompt') or ''),*source_turns,message])])
        latest_id=f'turn-{len(source_turns)+1}'
        corrections=[f for f in scalar['facts'] if f['source_id']==latest_id and f['status']=='effective']
        if not dimensions and units is None and not corrections:
            return None
        merged = dict(current)
        # Numeric extraction is only an index. Preserve the user's complete
        # constraints (coordinates, per-component sizes, orientation, etc.)
        # for the construction model and subsequent independent validation.
        followups = list(current.get("source_followups") or [])
        if message.strip() and message.strip() not in followups:
            followups.append(message.strip())
        merged["source_followups"] = followups
        if units is not None:
            merged["units"] = units
        if dimensions:
            original = parameterize_design(str(project.get("original_prompt") or ""))
            for source in (original, parsed):
                if not isinstance(source, dict):
                    continue
                for key in (
                    "shape", "drawing_type", "quantity", "arrangement", "spacing_m",
                    "spacing_reference", "peer_placement", "printer", "origin", "units",
                    "closed", "smooth", "symmetric", "self_intersection", "assumptions",
                ):
                    value = source.get(key)
                    if value is not None and value != []:
                        merged[key] = deepcopy(value)
            merged["dimensions"] = {
                **(current.get("dimensions") or {}),
                **dimensions,
            }
            if "dimension_bounds" in parsed:
                merged["dimension_bounds"] = deepcopy(parsed["dimension_bounds"])
            shape = merged.get("shape") or merged.get("drawing_type")
            if shape and "shape" not in merged:
                merged["shape"] = shape
        if len(scalar['subjects'])==1:
            # A local crossbar/part height must not overwrite the drawing's
            # whole height merely because the legacy index found it last.
            fields={'width':'width_m','height':'height_m','radius':'radius_m','diameter':'diameter_m'}
            for fact in scalar['facts']:
                if fact['status']=='effective' and fact['operator']=='eq' and fact['field'] in fields:
                    merged.setdefault('dimensions',{})[fields[fact['field']]]=fact['value_mm']/1000
        from .cad_coordinate_requirements import coordinate_scale
        coordinate_sized=coordinate_scale(str(project.get('original_prompt') or '')+'\n'+'\n'.join(followups))['has_scale']
        missing = [
            key for key in ("shape", "dimensions")
            if not merged.get(key) or (
                key == "dimensions" and not isinstance(merged.get(key), dict)
            )
        ]
        if coordinate_sized:
            missing=[key for key in missing if key!='dimensions']
            merged['scale_source']='explicit_coordinates_and_units'
        missing.extend(key for key in project.get('missing_parameters') or []
            if key not in {'shape','dimensions','printer'} and key not in missing)
        # A resolved arc-and-straight-edge specification answers a previous
        # curve clarification. Do not keep the old model question forever
        # after the user explicitly supplies radius and straight lengths.
        if ('curve_constraints' in missing
                and re.search(r'半径\s*\d+(?:\.\d+)?\s*(?:毫米|厘米|米|mm|cm|m)', message)
                and re.search(r'(?:直墙|直边|直线段).{0,12}\d+(?:\.\d+)?\s*(?:毫米|厘米|米|mm|cm|m)', message)
                and re.search(r'半圆|圆弧', message)):
            missing.remove('curve_constraints')
            merged['curve_constraints'] = {'status': 'specified', 'source': message}
        merged["requirement_ledger"] = project_requirement_ledger(
            str(project.get("original_prompt") or ""), followups, missing=missing,
            previous=current.get("requirement_ledger"))
        updated = get_creative_project_store().update(
            str(project["id"]),
            requirements=merged,
            missing_parameters=missing,
            event_message="已记住并合并用户补充的 CAD 参数",
        )
        if updated is None:
            return None
        labels = {"shape": "图形类型", "dimensions": "关键尺寸", "printer": "喷码机",
                  "curve_constraints":"曲线约束", "standard_spec":"标准规格", "units":"坐标单位"}
        remembered = []
        if dimensions:
            remembered.append(
                "、".join(f"{key}={merged.get('dimensions',{}).get(key,value)}" for key, value in dimensions.items())
            )
        if units is not None:
            remembered.append(f"单位={units}")
        if not remembered and corrections:
            remembered.append(message.strip())
        values_text = "，".join(remembered)
        if missing:
            message_text = (
                f"已记住你补充的参数：{values_text}。还缺少："
                + "、".join(labels.get(item, item) for item in missing)
                + "。"
            )
        else:
            message_text = (
                f"已记住并合并你补充的参数：{values_text}。"
                "当前需求已完整，请确认后生成候选方案。"
            )
        return {
            **self._result(message_text, self._empty_usage()),
            "project_id": str(updated["id"]),
            "project": updated,
            "requirements": dict(updated.get("requirements") or {}),
            "missing_parameters": list(updated.get("missing_parameters") or []),
            "requirements_confirmation_required": not missing,
        }

    # ------------------------------------------------------------------
    # Multi-provider tool-calling agents.
    #
    # The tool execution chain, safety policy and CAD-modification logic
    # are provider-agnostic; only request construction and reply parsing
    # differ per vendor.  These methods let every configured provider run
    # the full agent (CAD editing, project generation, robot control)
    # instead of falling back to plain-text chat.
    # ------------------------------------------------------------------

    def _openai_compatible_request(
        self,
        provider: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        model: str,
        max_tokens: int,
    ) -> dict[str, Any]:
        """POST /chat/completions against any OpenAI-compatible provider."""
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return request_provider_tool_json(
            provider,
            model=model,
            api_key=self.api_key,
            payload=payload,
            timeout=self._env_timeout(
                "XLINE_AGENT_MODEL_REQUEST_TIMEOUT_SECONDS",
                45.0,
                maximum=900.0,
            ),
        )

    def _anthropic_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        return request_provider_tool_json(
            "anthropic",
            model=self.model,
            api_key=self.api_key,
            payload=payload,
            timeout=self._env_timeout(
                "XLINE_AGENT_MODEL_REQUEST_TIMEOUT_SECONDS",
                45.0,
                maximum=900.0,
            ),
        )

    def _gemini_request(self, model: str, payload: dict[str, Any]) -> dict[str, Any]:
        return request_provider_tool_json(
            "gemini",
            model=model,
            api_key=self.api_key,
            payload=payload,
            timeout=self._env_timeout(
                "XLINE_AGENT_MODEL_REQUEST_TIMEOUT_SECONDS",
                45.0,
                maximum=900.0,
            ),
        )

    @staticmethod
    def _strip_strict_tools(
        tools: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Remove the `strict` flag for providers that do not support it."""
        result: list[dict[str, Any]] = []
        for tool in tools or []:
            function = tool.get("function") or {}
            result.append(
                {
                    "type": "function",
                    "function": {
                        "name": function.get("name"),
                        "description": function.get("description"),
                        "parameters": function.get("parameters"),
                    },
                }
            )
        return result

    @staticmethod
    def _anthropic_tools(
        tools: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return [
            {
                "name": (tool.get("function") or {}).get("name"),
                "description": (tool.get("function") or {}).get("description"),
                "input_schema": (tool.get("function") or {}).get("parameters"),
            }
            for tool in (tools or [])
        ]

    @staticmethod
    def _gemini_tools(
        tools: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return [
            {
                "functionDeclarations": [
                    {
                        "name": (tool.get("function") or {}).get("name"),
                        "description": (tool.get("function") or {}).get("description"),
                        "parameters": (tool.get("function") or {}).get("parameters"),
                    }
                    for tool in (tools or [])
                ]
            }
        ]

    @staticmethod
    def _anthropic_usage(response: dict[str, Any]) -> dict[str, int]:
        usage = response.get("usage") or {}
        input_tokens = int(usage.get("input_tokens", 0) or 0)
        output_tokens = int(usage.get("output_tokens", 0) or 0)
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }

    @staticmethod
    def _gemini_usage(response: dict[str, Any]) -> dict[str, int]:
        usage = response.get("usageMetadata") or {}
        input_tokens = int(usage.get("promptTokenCount", 0) or 0)
        output_tokens = int(usage.get("candidatesTokenCount", 0) or 0)
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }

    def _drive_sequence_gate(
        self,
        calls: list[dict[str, Any]],
        usage: dict[str, int],
        mode: str,
    ) -> dict[str, Any] | None:
        """Merge two or more drive_robot calls into one confirmable sequence."""
        drive_steps: list[dict[str, Any]] = []
        for call in calls:
            if str(call.get("name", "")) != "drive_robot":
                continue
            raw = call.get("arguments") or {}
            if isinstance(raw, str):
                raw = self._arguments(raw)
            step, _ = validate_tool_arguments("drive_robot", raw)
            if step is not None:
                drive_steps.append(step)
        if len(drive_steps) < 2:
            return None
        policy = agent_tool_policy("drive_sequence", mode)
        if not policy["allowed"]:
            return self._result(policy["reason"], usage)
        sequence, error = validate_tool_arguments(
            "drive_sequence", {"steps": drive_steps}
        )
        if sequence is None:
            return self._result(error, usage)
        pending_action = self._register_pending("drive_sequence", sequence, mode=mode)
        return self._result(
            self._confirmation_text("drive_sequence", sequence),
            usage,
            pending_action,
        )

    def _dispatch_tool_calls(
        self,
        calls: list[dict[str, Any]],
        usage: dict[str, int],
        route: dict[str, Any] | None,
        mode: str,
        *,
        append_result,
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        """Validate, execute or stage each tool call for a provider-native loop.

        ``calls`` items are {"id", "name", "arguments"(dict)}.
        ``append_result(call, output)`` feeds a tool result back into the
        provider-specific message history.
        Returns (early_result_or_None, tool_results).
        """
        tool_results: list[dict[str, Any]] = []
        for call in calls:
            name = str(call.get("name", ""))
            raw_arguments = call.get("arguments") or {}
            if isinstance(raw_arguments, str):
                raw_arguments = self._arguments(raw_arguments)
            raw_arguments = self._bind_drawing_selection(name, raw_arguments, route)
            if (
                isinstance(route, dict)
                and name in {"update_creative_project", "select_design_variant"}
                and str(route.get("selected_project_id") or "").strip()
            ):
                raw_arguments = {
                    **raw_arguments,
                    "project_id": str(route["selected_project_id"]),
                }
            domain_error = self._edit_domain_tool_error(name, route)
            if domain_error:
                append_result(call, {"ok": False, "message": domain_error})
                continue
            if name in MODEL_HIDDEN_TOOLS:
                append_result(call, {"ok": False, "message": "该工具仅供后端内部使用。"})
                continue
            arguments, error = validate_tool_arguments(name, raw_arguments)
            if arguments is None:
                append_result(call, {"ok": False, "message": error})
                continue
            if name in SAFE_TOOL_NAMES:
                output = self._execute_safe(name, arguments, mode=mode)
                output = self._stale_project_tool_guide(
                    name, arguments, output, route
                )
                if (
                    isinstance(route, dict)
                    and name == "create_creative_project"
                    and isinstance(output, dict)
                ):
                    created = output.get("project")
                    created_id = (
                        str(created.get("id") or "").strip()
                        if isinstance(created, dict) else ""
                    )
                    if created_id:
                        route["selected_project_id"] = created_id
                        route["project_id"] = created_id
                tool_results.append(self._tool_result_summary(name, output))
                append_result(call, output)
                continue
            policy = agent_tool_policy(name, mode)
            if not policy["allowed"]:
                return self._result(policy["reason"], usage), tool_results
            pending_action = self._register_pending(name, arguments, mode=mode)
            return (
                self._result(
                    self._confirmation_text(name, arguments), usage, pending_action
                ),
                tool_results,
            )
        return None, tool_results

    def _tool_agent_chat(
        self,
        message: str,
        history: list[dict[str, str]],
        *,
        mode: str = "advanced",
        route: dict[str, Any] | None = None,
        context_message: str | None = None,
    ) -> dict[str, Any]:
        """Full tool-calling agent for OpenAI-compatible providers.

        Used by qwen / kimi / glm / minimax.  Mirrors the DeepSeek loop with
        the same safety gates, but without DeepSeek-only model switching.
        """
        context_message = context_message or message
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": self._system_context(
                    context_message, mode=mode, route=route
                ),
            },
            *[
                {"role": item.get("role", "user"), "content": item.get("content", "")}
                for item in history[-4:]
                if item.get("content")
            ],
            {"role": "user", "content": message},
        ]
        selected_tools = self._selected_deepseek_tools(
            context_message, mode=mode, route=route
        )
        compat_tools = self._strip_strict_tools(selected_tools)
        first = self._openai_compatible_request(
            self.mode,
            messages,
            compat_tools,
            model=self.model,
            max_tokens=self._compatible_agent_max_tokens(mode),
        )
        usage = self._chat_usage(first)
        choices = first.get("choices") or []
        model_message = choices[0].get("message", {}) if choices else {}
        calls = model_message.get("tool_calls") or []
        if not calls:
            content = str(model_message.get("content") or "")
            if mode == "base":
                json_action = self._chat_json_movement(content)
                if json_action is not None:
                    return json_action
            if mode == "advanced" and not content.strip():
                # A provider may return an empty advanced response. Candidate
                # generation stays inside the backend construction pipeline.
                recovered = self._recover_candidate_after_empty_response(
                    route or {}, mode
                )
                if recovered is not None:
                    return recovered
                return self._advanced_empty_response(route or {}, usage)
            return self._result(content, usage)

        normalized = [
            {
                "id": str(call.get("id") or ""),
                "name": str((call.get("function") or {}).get("name") or ""),
                "arguments": self._arguments(
                    (call.get("function") or {}).get("arguments")
                ),
            }
            for call in calls
        ]
        gate = self._drive_sequence_gate(normalized, usage, mode)
        if gate is not None:
            return gate

        messages.append(model_message)

        def append_result(call: dict[str, Any], output: dict[str, Any]) -> None:
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id"),
                    "content": json.dumps(output, ensure_ascii=False),
                }
            )

        early, tool_results = self._dispatch_tool_calls(
            normalized, usage, route, mode, append_result=append_result
        )
        if early is not None:
            return early

        second = self._openai_compatible_request(
            self.mode,
            messages,
            compat_tools,
            model=self.model,
            max_tokens=self._compatible_agent_max_tokens(mode),
        )
        usage = self._add_usage(usage, self._chat_usage(second))
        choices = second.get("choices") or []
        second_message = choices[0].get("message", {}) if choices else {}
        second_calls = []
        for raw_call in second_message.get("tool_calls") or []:
            function = raw_call.get("function") or {}
            second_calls.append(
                {
                    "id": str(raw_call.get("id") or ""),
                    "name": str(function.get("name") or ""),
                    "arguments": str(function.get("arguments") or "{}"),
                }
            )
        if second_calls:
            return self._streamed_tool_result(
                second_calls, usage, mode=mode, route=route
            )
        text = str(second_message.get("content") or "")
        if not text.strip() and not tool_results and mode == "advanced":
            return self._advanced_empty_response(route or {}, usage)
        return self._result(text or "需求信息已更新。", usage, tool_results=tool_results)

    def _compatible_agent_max_tokens(self, mode: str | None) -> int:
        normalized = RobotAgentService.normalize_agent_mode(mode)
        return 4096 if normalized == "advanced" else 2048

    def _structured_review_text(
        self,
        messages: list[dict[str, Any]],
        *,
        mode: str,
        max_tokens_override: int | None = None,
        model_override: str | None = None,
    ) -> str:
        """Send a JSON-only review prompt and return the model's raw text.

        Used by intent routing review (resolve_intent) and the structured CAD
        edit fallback.  Dispatches to the configured provider and normalizes
        each vendor's response to plain text; raises RuntimeError on API
        failure so callers can fall back to conservative rules.
        """
        if self.mode == "local" or not self.configured:
            raise RuntimeError("结构化复核 API 未配置")
        max_tokens = (
            max(128, min(32768, int(max_tokens_override)))
            if max_tokens_override is not None
            else self._structured_review_max_tokens()
        )
        if self.mode == "deepseek":
            configured_model = model_override or self._model_for_agent_mode(mode)
            fallback_model = structured_model_fallback("deepseek", configured_model)
            selected_model = fallback_model or configured_model
            response = self._deepseek_request(
                messages,
                tools=[],
                mode=mode,
                max_tokens_override=min(max_tokens, 8192) if fallback_model else max_tokens,
                stream_structured="reasoner" in selected_model,
                **({"model_override": fallback_model or model_override} if fallback_model or model_override else {}),
                json_output=True,
            )
            choices = response.get("choices") or []
            record_structured_usage(response, "deepseek")
            agent_audit.append('structured_response_received', 'cad_construction',
                {'model': selected_model, 'max_tokens': max_tokens},
                {'finish_reason': choices[0].get('finish_reason') if choices else None,
                 'content_chars': len(str((choices[0].get('message') or {}).get('content') or '')) if choices else 0,
                 'usage': deepcopy(response.get('usage') or {})})
            if choices and choices[0].get("finish_reason") == "length":
                if "reasoner" in selected_model:
                    # Keep the same strict construction protocol and verifier.
                    # A reasoning-only truncation gets one JSON emission retry,
                    # never a direct geometry write or a template fallback.
                    agent_audit.append("structured_model_fallback", "cad_construction",
                                       {"from_model": configured_model,
                                        "to_model": "deepseek-chat"},
                                       {"ok": False, "message": "reasoning_output_truncated"})
                    response = self._deepseek_request(
                        messages, tools=[], mode=mode,
                        max_tokens_override=8192,
                        model_override="deepseek-chat",
                        json_output=True,
                    )
                    choices = response.get("choices") or []
                    record_structured_usage(response, "deepseek")
                    if choices and choices[0].get("finish_reason") not in {None, "length"}:
                        remember_structured_model_fallback("deepseek", configured_model, "deepseek-chat")
                if not choices or choices[0].get("finish_reason") == "length":
                    raise RuntimeError(
                        f"结构化模型输出被截断（max_tokens={max_tokens}），未获得完整 CAD JSON。"
                    )
            return str(
                choices[0].get("message", {}).get("content") or ""
            ) if choices else ""
        if self.mode == "openai":
            system_text = "严格输出 JSON，禁止 Markdown。"
            input_items: list[dict[str, Any]] = []
            for item in messages:
                role = item.get("role")
                content = item.get("content") or ""
                if role == "system":
                    system_text = str(content)
                else:
                    input_items.append(
                        {"role": role or "user", "content": str(content)}
                    )
            payload: dict[str, Any] = {
                "model": self.model,
                "instructions": system_text,
                "input": input_items,
                "max_output_tokens": max_tokens,
                "store": False,
            }
            request = urllib.request.Request(
                "https://api.openai.com/v1/responses",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            request_lease = user_request_limiter.acquire(current_agent_user_id())
            request_lease.__enter__()
            try:
                with urllib.request.urlopen(
                    request,
                    timeout=self._env_timeout(
                        "XLINE_AGENT_MODEL_REQUEST_TIMEOUT_SECONDS",
                        45.0,
                        maximum=900.0,
                    ),
                ) as response:
                    result = json.loads(response.read().decode("utf-8"))
            except (
                urllib.error.HTTPError,
                urllib.error.URLError,
                TimeoutError,
                socket.timeout,
            ) as error:
                raise RuntimeError(f"OpenAI 复核请求失败：{error}") from error
            finally:
                request_lease.__exit__(None, None, None)
            record_structured_usage(result, "openai")
            return self._output_text(result)
        if self.mode == "anthropic":
            system_text = "严格输出 JSON，禁止 Markdown。"
            non_system: list[dict[str, Any]] = []
            for item in messages:
                if item.get("role") == "system":
                    system_text = str(item.get("content") or "")
                else:
                    non_system.append(
                        {
                            "role": (
                                "assistant"
                                if item.get("role") == "assistant"
                                else "user"
                            ),
                            "content": str(item.get("content") or ""),
                        }
                    )
            payload: dict[str, Any] = {
                "model": self.model,
                "system": system_text,
                "messages": non_system,
                "max_tokens": max_tokens,
            }
            response = self._anthropic_request(payload)
            record_structured_usage(response, "anthropic")
            blocks = response.get("content") or []
            return "".join(
                str(block.get("text") or "")
                for block in blocks
                if block.get("type") == "text"
            )
        if self.mode == "gemini":
            system_text = "严格输出 JSON，禁止 Markdown。"
            contents: list[dict[str, Any]] = []
            for item in messages:
                if item.get("role") == "system":
                    system_text = str(item.get("content") or "")
                else:
                    contents.append(
                        {
                            "role": (
                                "model"
                                if item.get("role") == "assistant"
                                else "user"
                            ),
                            "parts": [{"text": str(item.get("content") or "")}],
                        }
                    )
            payload: dict[str, Any] = {
                "systemInstruction": {"parts": [{"text": system_text}]},
                "contents": contents,
                "generationConfig": {
                    "maxOutputTokens": max_tokens
                },
            }
            response = self._gemini_request(self.model, payload)
            record_structured_usage(response, "gemini")
            candidates = response.get("candidates") or []
            parts = (
                candidates[0].get("content", {}).get("parts", [])
                if candidates
                else []
            )
            return "".join(
                str(part.get("text") or "") for part in parts if "text" in part
            )
        response = self._openai_compatible_request(
            self.mode,
            messages,
            tools=None,
            model=self.model,
            max_tokens=max_tokens,
        )
        record_structured_usage(response, "compatible")
        choices = response.get("choices") or []
        return str(
            choices[0].get("message", {}).get("content") or ""
        ) if choices else ""

    @staticmethod
    def _structured_review_retry_messages(
        messages: list[dict[str, Any]],
        invalid_text: str,
        *,
        reason: str,
    ) -> list[dict[str, Any]]:
        """Build one bounded correction turn for an invalid structured reply."""
        excerpt = invalid_text.strip() or "（空响应）"
        try:
            json.loads(invalid_text)
        except json.JSONDecodeError as exc:
            reason += f"；JSON错误位于第{exc.lineno}行第{exc.colno}列：{exc.msg}"
        return [
            *messages,
            {"role": "assistant", "content": excerpt},
            {
                "role": "user",
                "content": (
                    f"上次输出无法使用（{reason}）。请重新检查原始用户消息，"
                    "只输出一个完整 JSON 对象，不要输出 Markdown、解释或前后缀。"
                    "不得补猜原文没有提供的目标或参数。"
                    "完整保留原计划内容，仅修正JSON语法与字段嵌套；steps、assertions、free_outline_layout"
                    "均属于plan；evidence_text、assumptions、confidence属于最外层。"
                ),
            },
        ]

    @staticmethod
    def _route_review_payload_usable(review: dict[str, Any] | None) -> bool:
        return bool(
            isinstance(review, dict)
            and review.get("primary_intent") in {
                "conversation", "diagnosis", "status_query", "drawing_design",
                "motion_control", "printer_control", "mission_control",
                "localization_control", "stop",
            }
        )

    def _native_tool_chat(
        self,
        message: str,
        history: list[dict[str, str]],
        *,
        mode: str = "advanced",
        route: dict[str, Any] | None = None,
        context_message: str | None = None,
    ) -> dict[str, Any]:
        """Full tool-calling agent for providers with native tool schemas."""
        if self.mode == "anthropic":
            return self._anthropic_tool_chat(
                message,
                history,
                mode=mode,
                route=route,
                context_message=context_message,
            )
        return self._gemini_tool_chat(
            message,
            history,
            mode=mode,
            route=route,
            context_message=context_message,
        )

    def _anthropic_tool_chat(
        self,
        message: str,
        history: list[dict[str, str]],
        *,
        mode: str = "advanced",
        route: dict[str, Any] | None = None,
        context_message: str | None = None,
    ) -> dict[str, Any]:
        context_message = context_message or message
        system = self._system_context(context_message, mode=mode, route=route)
        messages: list[dict[str, Any]] = [
            {"role": item.get("role", "user"), "content": item.get("content", "")}
            for item in history[-4:]
            if item.get("content")
        ]
        messages.append({"role": "user", "content": message})
        selected_tools = self._selected_deepseek_tools(
            context_message, mode=mode, route=route
        )
        payload: dict[str, Any] = {
            "model": self.model,
            "system": system,
            "messages": messages,
            "max_tokens": self._compatible_agent_max_tokens(mode),
        }
        if selected_tools:
            payload["tools"] = self._anthropic_tools(selected_tools)
        first = self._anthropic_request(payload)
        usage = self._anthropic_usage(first)
        content_blocks = first.get("content") or []
        tool_uses = [block for block in content_blocks if block.get("type") == "tool_use"]
        text = "".join(
            str(block.get("text") or "")
            for block in content_blocks
            if block.get("type") == "text"
        )
        if not tool_uses:
            return self._result(text or "需求信息已更新。", usage)
        calls = [
            {
                "id": str(block.get("id") or ""),
                "name": str(block.get("name") or ""),
                "arguments": block.get("input") or {},
            }
            for block in tool_uses
        ]
        gate = self._drive_sequence_gate(calls, usage, mode)
        if gate is not None:
            return gate
        messages.append({"role": "assistant", "content": content_blocks})

        def append_result(call: dict[str, Any], output: dict[str, Any]) -> None:
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": call.get("id"),
                            "content": json.dumps(output, ensure_ascii=False),
                        }
                    ],
                }
            )

        early, tool_results = self._dispatch_tool_calls(
            calls, usage, route, mode, append_result=append_result
        )
        if early is not None:
            return early
        second = self._anthropic_request({**payload, "messages": messages})
        usage = self._add_usage(usage, self._anthropic_usage(second))
        blocks = second.get("content") or []
        second_tool_uses = [block for block in blocks if block.get("type") == "tool_use"]
        second_text = "".join(
            str(block.get("text") or "") for block in blocks if block.get("type") == "text"
        )
        if second_tool_uses:
            calls2 = [
                {
                    "id": str(block.get("id") or ""),
                    "name": str(block.get("name") or ""),
                    "arguments": json.dumps(
                        block.get("input") or {}, ensure_ascii=False
                    ),
                }
                for block in second_tool_uses
            ]
            return self._streamed_tool_result(calls2, usage, mode=mode, route=route)
        if not second_text.strip() and not tool_results and mode == "advanced":
            return self._advanced_empty_response(route or {}, usage)
        return self._result(second_text or "需求信息已更新。", usage, tool_results=tool_results)

    def _gemini_tool_chat(
        self,
        message: str,
        history: list[dict[str, str]],
        *,
        mode: str = "advanced",
        route: dict[str, Any] | None = None,
        context_message: str | None = None,
    ) -> dict[str, Any]:
        context_message = context_message or message
        system = self._system_context(context_message, mode=mode, route=route)
        contents: list[dict[str, Any]] = [
            {
                "role": "model" if item.get("role") == "assistant" else "user",
                "parts": [{"text": item.get("content", "")}],
            }
            for item in history[-4:]
            if item.get("content")
        ]
        contents.append({"role": "user", "parts": [{"text": message}]})
        selected_tools = self._selected_deepseek_tools(
            context_message, mode=mode, route=route
        )
        payload: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": self._compatible_agent_max_tokens(mode)
            },
        }
        if selected_tools:
            payload["tools"] = self._gemini_tools(selected_tools)
        first = self._gemini_request(self.model, payload)
        usage = self._gemini_usage(first)
        candidates = first.get("candidates") or []
        parts = (
            candidates[0].get("content", {}).get("parts", []) if candidates else []
        )
        text = "".join(str(part.get("text") or "") for part in parts if "text" in part)
        function_calls = [part["functionCall"] for part in parts if "functionCall" in part]
        if not function_calls:
            return self._result(text or "需求信息已更新。", usage)
        calls = [
            {
                "id": f"gc-{index}",
                "name": str(function_call.get("name") or ""),
                "arguments": function_call.get("args") or {},
            }
            for index, function_call in enumerate(function_calls)
        ]
        gate = self._drive_sequence_gate(calls, usage, mode)
        if gate is not None:
            return gate
        contents.append(
            {
                "role": "model",
                "parts": [
                    {
                        "functionCall": {
                            "name": function_call.get("name"),
                            "args": function_call.get("args") or {},
                        }
                    }
                    for function_call in function_calls
                ],
            }
        )

        def append_result(call: dict[str, Any], output: dict[str, Any]) -> None:
            contents.append(
                {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": call.get("name"),
                                "response": output,
                            }
                        }
                    ],
                }
            )

        early, tool_results = self._dispatch_tool_calls(
            calls, usage, route, mode, append_result=append_result
        )
        if early is not None:
            return early
        second = self._gemini_request(self.model, {**payload, "contents": contents})
        usage = self._add_usage(usage, self._gemini_usage(second))
        candidates = second.get("candidates") or []
        parts = (
            candidates[0].get("content", {}).get("parts", []) if candidates else []
        )
        second_calls = []
        for index, part in enumerate(parts):
            function_call = part.get("functionCall")
            if not function_call:
                continue
            second_calls.append(
                {
                    "id": f"gc-{index}",
                    "name": str(function_call.get("name") or ""),
                    "arguments": json.dumps(
                        function_call.get("args") or {}, ensure_ascii=False
                    ),
                }
            )
        if second_calls:
            return self._streamed_tool_result(second_calls, usage, mode=mode, route=route)
        second_text = "".join(
            str(part.get("text") or "") for part in parts if "text" in part
        )
        if not second_text.strip() and not tool_results and mode == "advanced":
            return self._advanced_empty_response(route or {}, usage)
        return self._result(second_text or "需求信息已更新。", usage, tool_results=tool_results)

    def _deepseek_request(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        mode: str = "base",
        max_tokens_override: int | None = None,
        stream_structured: bool = False,
        model_override: str | None = None,
        json_output: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model_override or self._model_for_agent_mode(mode),
            "messages": messages,
            "max_tokens": (
                max_tokens_override
                if max_tokens_override is not None
                else self._deepseek_max_tokens(mode)
            ),
        }
        selected_tools = DEEPSEEK_TOOLS if tools is None else tools
        if json_output:
            payload["response_format"] = {"type": "json_object"}
        if stream_structured:
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}
        if selected_tools:
            payload["tools"] = selected_tools
            payload["tool_choice"] = "auto"
        connection = None
        response = None
        deadline = time.monotonic() + self._deepseek_timeout("request", 90.0)
        request_lease = user_request_limiter.acquire(current_agent_user_id())
        request_lease.__enter__()
        try:
            connection, response = self._unpack_deepseek_response(
                self._deepseek_response(payload)
            )
            if stream_structured and response.status < 400:
                parts: list[str] = []
                finish_reason = None
                stream_usage = None
                while True:
                    self._deepseek_transport().set_socket_timeout(connection, deadline, response=response)
                    raw_line = response.readline()
                    if time.monotonic() >= deadline:
                        raise TimeoutError("DeepSeek response deadline exceeded")
                    if not raw_line:
                        break
                    line = raw_line.decode("utf-8").strip()
                    if not line.startswith("data:"):
                        continue
                    data_line = line[5:].strip()
                    if data_line == "[DONE]":
                        break
                    chunk = json.loads(data_line)
                    if isinstance(chunk.get("usage"), dict):
                        stream_usage = chunk["usage"]
                    if chunk.get("error"):
                        raise RuntimeError("DeepSeek 流式构造失败：" + str(chunk["error"]))
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    choice = choices[0]
                    # Reasoning chunks keep the connection alive but are not
                    # part of the JSON contract executed by the CAD backend.
                    content = (choice.get("delta") or {}).get("content")
                    if content:
                        parts.append(str(content))
                    finish_reason = choice.get("finish_reason") or finish_reason
                if finish_reason is None:
                    raise RuntimeError("DeepSeek 构造响应提前中断，未收到完成标记。")
                return {"choices": [{"finish_reason": finish_reason,
                                     "message": {"content": "".join(parts)}}],
                        **({"usage": stream_usage} if stream_usage is not None else {})}
            data = self._read_deepseek_body(response, connection, deadline)
            if response.status >= 400:
                raise RuntimeError(
                    f"DeepSeek API 请求失败（{response.status}）：{data[:300]}"
                )
            return json.loads(data)
        except (TimeoutError, socket.timeout) as error:
            raise RuntimeError("DeepSeek API 请求超时，请稍后重试。") from error
        finally:
            self._close_deepseek_response(connection, response)
            request_lease.__exit__(None, None, None)

    def analyze_diagnostic_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """Run API-only diagnosis without exposing any robot tools."""
        prompt = (
            "分析以下小车实时快照，指出异常方向、证据字段和建议人工核验项。"
            "不得声称已经修复，不得要求或调用运动、喷码、急停和任务执行工具。\n"
            + json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
        )
        if self.mode == "local" or not self.configured:
            return {
                "ok": False,
                "configured": self.configured,
                "message": "诊断 API 未配置，无法完成 API 分析阶段。",
                "usage": self._empty_usage(),
                "pending_action": None,
            }
        if self.mode == "deepseek":
            response = self._deepseek_request([
                {"role": "system", "content": self._system_context(prompt, mode="advanced")},
                {"role": "user", "content": prompt},
            ], tools=[], mode="advanced")
            usage = self._chat_usage(response)
            choices = response.get("choices") or []
            message = str(choices[0].get("message", {}).get("content") or "") if choices else ""
            return self._result(message or "API 未返回诊断正文。", usage)
        if self.mode == "openai":
            payload = {
                "model": self.model,
                "instructions": self._system_context(prompt, mode="advanced"),
                "input": [{"role": "user", "content": prompt}],
                "max_output_tokens": int(os.getenv("OPENAI_MAX_OUTPUT_TOKENS", "600")),
                "store": False,
            }
            try:
                result = request_openai_responses_json(
                    api_key=self.api_key,
                    payload=payload,
                    timeout=self._env_timeout(
                        "XLINE_AGENT_MODEL_REQUEST_TIMEOUT_SECONDS",
                        45.0,
                        maximum=900.0,
                    ),
                )
            except RuntimeError as error:
                raise RuntimeError(f"OpenAI 诊断 API 请求失败：{error}") from error
            return self._result(self._output_text(result), self._usage(result))
        return self._compatible_chat(prompt, [], mode="advanced")

    @staticmethod
    def _mode_message(message: str, mode: str) -> str:
        mode = RobotAgentService.normalize_agent_mode(mode)
        if mode == "base":
            return (
                "【当前模式：基础】这是底盘运动控制模式。用户描述前进、后退、转弯、绕圈、"
                "正方形、圆形、直线、椭圆形或自定义折线都只生成合法的低速运动 JSON，"
                "并调用 drive_robot 或 drive_sequence；"
                "任意图形都可以拆成多段 linear、angular、duration_seconds 运动步骤，不要求精确距离和角度。"
                "先返回待确认的运动操作，用户确认后才执行。基础模式通常只处理底盘运动；"
                "只有用户明确要求打开或关闭喷墨时，才允许使用 printer_spray，且必须再次确认。"
                "不创建项目、不生成图纸、不规划路径。默认喷墨关闭，打开后可与运动演示同时进行。"
                "运动 JSON 必须通过严格 Schema 和安全门禁。\n"
                + message
            )
        return (
            "【当前模式：进阶】请主动引导用户依次完成需求参数化、候选方案、规划检查、确认和执行。"
            "正式任务必须使用有效定位、完整规划和用户确认。对于正方形、矩形、边长或闭合路线，"
            "必须创建项目并调用 xline_ws3 路径规划，禁止用 drive_sequence 的时间估算冒充精确路径。\n"
            + message
        )

    def _run_advanced_cad_pipeline(
        self,
        message: str,
        history: list[dict[str, str]],
        route: dict[str, Any],
        *,
        mode: str,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Run the transport-independent CAD domain pipeline.

        Sync and streaming chat must use this exact order. In particular,
        creation requests cannot enter candidate editing, and verified generic
        construction must run before legacy provider tool calls.
        """
        route = self._with_edit_domain(route)
        if route.get("operation") == "modify" and route.get("edit_domain") == "candidate_variant":
            prior_addition = any(
                item.get("role") == "user"
                and re.search(r"(?:添加|增加|新增|加上|加两个|加2个)", str(item.get("content") or ""))
                and "矩形" in str(item.get("content") or "")
                for item in history[-4:]
                if isinstance(item, dict)
            )
            addition_intent = bool(re.search(r"(?:添加|增加|新增|加上)", message)) or (
                prior_addition and self._is_design_generation_confirmation(message)
            ) or (prior_addition and "确认参数" in message and "生成候选" in message)
            addition = parse_relative_additions(message) if addition_intent else None
            if addition is not None:
                route = {**route, "decision_source": "project_addition_plan",
                         "relative_addition_contract": addition}
                result = self._apply_cad_edit_commands(message, route)
                if result is not None:
                    return route, result
        if (
            route.get("operation") == "modify"
            and route.get("edit_domain") == "candidate_variant"
            and route.get("decision_source") not in {
                "incremental_cad_edit_chain", "constrained_cad_addition",
                "incremental_cad_edit", "drawing_relative_template_addition",
                "drawing_layout_followup",
            }
        ):
            deterministic_edit = parse_incremental_edit(message)
            if (
                isinstance(deterministic_edit, dict)
                and deterministic_edit.get("operation") == "scale"
                and deterministic_edit.get("instances") == "all"
            ):
                route.update({
                    "name": "drawing_design",
                    "tool_family": "cad",
                    "decision_source": "incremental_cad_edit",
                    "edit_intent": build_cad_edit_intent(
                        message, deterministic_edit
                    ),
                    "review_required": False,
                    "clarification_required": False,
                    "safety_confirmation_required": False,
                })
        route = self._structured_cad_edit_fallback(message, history, route, mode)
        route = self._with_edit_domain(route)
        if (
            route.get("operation") == "modify"
            and route.get("edit_domain") == "candidate_variant"
        ):
            result = self._apply_cad_edit_commands(message, route)
            if result is not None:
                return route, result

        result = self._formal_cad_construction(message, route, mode=mode)
        if result is not None:
            return route, result
        return route, None

    def _apply_cad_edit_commands(
        self, message: str, route: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Dispatch one already-parsed candidate edit without priority probing.

        Intent parsing owns ``decision_source``. The execution boundary must
        never try unrelated parsers/handlers in sequence because that restores
        keyword priority as a second router. Each selected branch still emits
        validated ``cad.edit.v2`` evidence before the common candidate writer.
        """
        route = self._with_edit_domain(route)
        if route.get("edit_domain") != "candidate_variant":
            return None
        handlers = {
            "incremental_cad_edit_chain": self._apply_incremental_candidate_chain,
            "constrained_cad_addition": self._apply_constrained_candidate_addition,
            "incremental_cad_edit": self._apply_incremental_candidate_edit,
            "conversation_pending_cad_edit": self._apply_incremental_candidate_edit,
            "drawing_relative_template_addition": self._apply_relative_template_addition,
            "drawing_layout_followup": self._apply_drawing_layout_followup,
            "project_addition_plan": self._apply_project_addition_plan,
        }
        handler = handlers.get(str(route.get("decision_source") or ""))
        return handler(message, route) if handler is not None else None

    @classmethod
    def _with_edit_domain(cls, route: dict[str, Any]) -> dict[str, Any]:
        """Bind every CAD modification to one explicit persistence domain."""
        resolved = route
        is_modify = resolved.get("operation") == "modify" or str(
            resolved.get("decision_source") or ""
        ) in {
            "incremental_cad_edit_chain", "constrained_cad_addition",
            "incremental_cad_edit", "conversation_pending_cad_edit",
            "drawing_relative_template_addition",
            "drawing_layout_followup",
        }
        if not is_modify:
            resolved.pop("edit_domain", None)
            return resolved
        explicit = str(resolved.get("edit_domain") or "")
        if explicit in {"candidate_variant", "standalone_drawing"}:
            return resolved
        selection = resolved.get("drawing_selection")
        if isinstance(selection, dict):
            has_project_context = bool(
                selection.get("project_id")
                or selection.get("variant_id")
                or resolved.get("selected_project_id")
                or cls._project_id_from_route(resolved)
            )
            if has_project_context:
                resolved["edit_domain"] = "candidate_variant"
            elif selection.get("source_file_name"):
                resolved["edit_domain"] = "standalone_drawing"
            else:
                resolved["edit_domain"] = "standalone_drawing"
            return resolved
        resolved["edit_domain"] = "candidate_variant"
        return resolved

    @classmethod
    def _edit_domain_tool_error(
        cls, name: str, route: dict[str, Any] | None,
    ) -> str | None:
        if not isinstance(route, dict):
            return None
        if (name == "create_creative_project"
                and route.get("operation") == "modify"
                and str(route.get("selected_project_id") or "").strip()):
            return "当前修改请求已绑定项目，不能另建项目；请在原项目和候选版本上继续。"
        if name != "modify_drawing":
            return None
        resolved = cls._with_edit_domain(route)
        if resolved.get("edit_domain") == "standalone_drawing":
            return None
        return "当前修改目标属于候选方案，不能通过独立图纸修改工具写入。"

    @owned_request
    def chat_stream(
        self,
        message: str,
        history: list[dict[str, str]],
        *,
        mode: str = "chat",
        route: dict[str, Any] | None = None,
        user_id: str | None = None,
    ):
        resolved_route = self._with_edit_domain(
            route or self.resolve_intent(message, mode, history)
        )
        session = agent_plan_runtime.begin(
            message,
            resolved_route,
            project_id=str(resolved_route.get("selected_project_id") or "") or None,
            variant_id=str(resolved_route.get("selected_variant_id") or "") or None,
        )
        finalized = False
        try:
            for event in self._chat_stream_impl(
                message,
                history,
                mode=mode,
                route=resolved_route,
                user_id=user_id,
            ):
                if event.get("type") == "result":
                    event = agent_plan_runtime.complete(session, event)
                    finalized = True
                yield event
        except Exception:
            if not finalized:
                agent_plan_runtime.complete(
                    session,
                    {"ok": False, "message": "流式执行异常"},
                )
            raise

    def _chat_stream_impl(
        self,
        message: str,
        history: list[dict[str, str]],
        *,
        mode: str = "chat",
        route: dict[str, Any] | None = None,
        user_id: str | None = None,
    ):
        bind_agent_user_id(user_id)
        mode = self.normalize_agent_mode(mode)
        route = route or self.resolve_intent(message, mode, history)
        if route.get("clarification_required"):
            requirement_followup = (
                self._apply_design_requirement_followup(message, route)
                if mode == "advanced" and route.get("decision_source") == "model_clarification"
                else None
            )
            if requirement_followup is not None:
                yield {"type": "result", **requirement_followup}
                return
            yield {
                "type": "result",
                **self._result(
                    str(route.get("clarification_question") or "请明确本次要处理的操作。"),
                    self._empty_usage(),
                ),
            }
            return
        stale_guide = self._stale_project_guard(route)
        if stale_guide is not None:
            yield {
                "type": "result",
                **self._result(stale_guide, self._empty_usage()),
            }
            return
        pending_design = self._pending_design_followup(raw_message=message, route=route)
        if pending_design is not None:
            yield {"type": "result", **pending_design}
            return
        requirement_followup = self._apply_design_requirement_followup(message, route)
        if requirement_followup is not None:
            yield {"type": "result", **requirement_followup}
            return
        raw_message = str(route.get("resolved_message") or message)
        if mode == "base":
            json_action = self._chat_json_movement(raw_message)
            if json_action is not None:
                yield {"type": "result", **json_action}
                return
        if mode == "base":
            local_action = self._local_intent(raw_message, allow_design=False, mode=mode)
            if local_action is not None:
                yield {"type": "result", **local_action}
                return
            if route.get("name") == "drawing_design":
                yield {"type": "result", **self._result(
                    "基础模式只支持底盘运动演示，不能生成精确图纸或规划路径。"
                    "要设计图纸并预览路径，请切换进阶模式后发送这条需求；不会自动启动小车。",
                    self._empty_usage(),
                )}
                return
        if mode == "advanced":
            route, cad_result = self._run_advanced_cad_pipeline(
                raw_message, history, route, mode=mode
            )
            if cad_result is not None:
                yield {"type": "result", **cad_result}
                return
        if self.mode != "deepseek" or not self.configured:
            yield {
                "type": "result",
                **self.chat(raw_message, history, mode=mode, route=route),
            }
            return

        message = self._mode_message(raw_message, mode)

        tools = self._selected_deepseek_tools(raw_message, mode=mode, route=route)
        messages = [
            {
                "role": "system",
                "content": self._system_context(raw_message, mode=mode, route=route),
            },
            *[
                {"role": item.get("role", "user"), "content": item.get("content", "")}
                for item in history[-4:]
                if item.get("content")
            ],
            {"role": "user", "content": message},
        ]
        payload = {
            "model": self._model_for_agent_mode(mode),
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "max_tokens": self._deepseek_max_tokens(mode),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        content_parts: list[str] = []
        streamed_calls: dict[int, dict[str, str]] = {}
        usage = self._empty_usage()
        connection = None
        response = None
        deadline = time.monotonic() + self._deepseek_timeout("request", 90.0)
        request_lease = user_request_limiter.acquire(current_agent_user_id())
        request_lease.__enter__()
        try:
            connection, response = self._unpack_deepseek_response(
                self._deepseek_response(payload)
            )
            if response.status >= 400:
                detail = self._read_deepseek_body(response, connection, deadline)
                raise RuntimeError(
                    f"DeepSeek API 请求失败（{response.status}）：{detail[:300]}"
                )
            while True:
                self._set_deepseek_socket_timeout(connection, deadline)
                raw_line = response.readline()
                if time.monotonic() >= deadline:
                    raise TimeoutError("DeepSeek stream deadline exceeded")
                if not raw_line:
                    break
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                event = json.loads(data)
                if event.get("usage"):
                    usage = self._chat_usage(event)
                choices = event.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                text = str(delta.get("content") or "")
                if text:
                    content_parts.append(text)
                    yield {"type": "delta", "text": text}
                for call in delta.get("tool_calls") or []:
                    index = int(call.get("index", 0))
                    target = streamed_calls.setdefault(
                        index, {"id": "", "name": "", "arguments": ""}
                    )
                    target["id"] += str(call.get("id") or "")
                    function = call.get("function") or {}
                    target["name"] += str(function.get("name") or "")
                    target["arguments"] += str(function.get("arguments") or "")
        except (TimeoutError, socket.timeout) as error:
            raise RuntimeError("DeepSeek 流式请求超时，请稍后重试。") from error
        finally:
            self._close_deepseek_response(connection, response)
            request_lease.__exit__(None, None, None)

        calls = [streamed_calls[index] for index in sorted(streamed_calls)]
        if calls:
            bind_agent_user_id(user_id)
            result = self._streamed_tool_result(
                calls,
                usage,
                mode=mode,
                messages=messages,
                tools=tools,
                route=route,
            )
        else:
            content = "".join(content_parts).strip()
            result = self._chat_json_movement(content) if mode == "base" else None
            if result is None and mode == "advanced" and not content:
                result = self._advanced_empty_response(route, usage)
            result = result or self._result(content, usage)
        yield {"type": "result", **result}

    def _model_for_agent_mode(self, mode: str | None) -> str:
        """Select the DeepSeek model without changing the provider setting."""
        normalized = self.normalize_agent_mode(mode)
        if self.mode != "deepseek":
            return self.model
        return self.advanced_model if normalized == "advanced" else self.base_model

    @staticmethod
    def _deepseek_max_tokens(mode: str | None) -> int:
        normalized = RobotAgentService.normalize_agent_mode(mode)
        env_name = (
            "DEEPSEEK_ADVANCED_MAX_TOKENS"
            if normalized == "advanced"
            else "DEEPSEEK_BASE_MAX_TOKENS"
        )
        default = 2400 if normalized == "advanced" else 900
        try:
            return max(600, min(8192, int(os.getenv(env_name, str(default)))))
        except ValueError:
            return default

    @staticmethod
    def _structured_review_max_tokens() -> int:
        try:
            value = int(os.getenv("XLINE_AGENT_REVIEW_MAX_TOKENS", "700"))
        except (TypeError, ValueError):
            value = 700
        return max(128, min(4096, value))

    @staticmethod
    def _construction_review_max_tokens() -> int:
        try:
            value = int(os.getenv("XLINE_AGENT_CONSTRUCTION_MAX_TOKENS", "8192"))
        except (TypeError, ValueError):
            value = 8192
        return max(1200, min(32768, value))

    def _streamed_tool_result(
        self,
        calls: list[dict[str, str]],
        usage: dict[str, int],
        *,
        mode: str = "base",
        messages: list[dict[str, Any]] | None = None,
        tools: list[dict[str, Any]] | None = None,
        route: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        mode = normalize_policy_mode(mode)
        drive_steps: list[dict[str, Any]] = []
        for call in calls:
            if call["name"] != "drive_robot":
                continue
            step, _ = validate_tool_arguments(
                "drive_robot", self._arguments(call["arguments"])
            )
            if step is not None:
                drive_steps.append(step)
        if len(drive_steps) >= 2:
            policy = agent_tool_policy("drive_sequence", mode)
            if not policy["allowed"]:
                return self._result(policy["reason"], usage)
            sequence, error = validate_tool_arguments(
                "drive_sequence", {"steps": drive_steps}
            )
            if sequence is None:
                return self._result(error, usage)
            pending = self._register_pending("drive_sequence", sequence, mode=mode)
            return self._result(
                self._confirmation_text("drive_sequence", sequence), usage, pending
            )

        safe_results: list[str] = []
        tool_results: list[dict[str, Any]] = []
        tool_messages: list[dict[str, Any]] = []
        cad_artifact: dict[str, Any] = {}
        for call in calls:
            raw_arguments = self._arguments(call["arguments"])
            raw_arguments = self._bind_drawing_selection(
                call["name"], raw_arguments, route
            )
            if (
                isinstance(route, dict)
                and call["name"] in {"update_creative_project", "select_design_variant"}
                and str(route.get("selected_project_id") or "").strip()
            ):
                raw_arguments = {
                    **raw_arguments,
                    "project_id": str(route["selected_project_id"]),
                }
            domain_error = self._edit_domain_tool_error(call["name"], route)
            if domain_error:
                return self._result(domain_error, usage)
            if call["name"] in MODEL_HIDDEN_TOOLS:
                return self._result(
                    "该候选写入工具仅供后端内部使用，模型调用已拒绝。", usage
                )
            arguments, error = validate_tool_arguments(call["name"], raw_arguments)
            if arguments is None:
                return self._result(error, usage)
            if call["name"] in SAFE_TOOL_NAMES:
                output = self._execute_safe(call["name"], arguments, mode=mode)
                output = self._stale_project_tool_guide(
                    call["name"], arguments, output, route
                )
                if (
                    isinstance(route, dict)
                    and call["name"] == "create_creative_project"
                    and isinstance(output, dict)
                ):
                    created = output.get("project")
                    created_id = (
                        str(created.get("id") or "").strip()
                        if isinstance(created, dict) else ""
                    )
                    if created_id:
                        route["selected_project_id"] = created_id
                        route["project_id"] = created_id
                summary = self._tool_result_summary(call["name"], output)
                tool_results.append(summary)
                safe_results.append(str(output.get("message") or json.dumps(output, ensure_ascii=False)))
                tool_messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(output, ensure_ascii=False),
                })
                continue
            policy = agent_tool_policy(call["name"], mode)
            if not policy["allowed"]:
                return self._result(policy["reason"], usage)
            pending = self._register_pending(call["name"], arguments, mode=mode)
            return self._result(
                self._confirmation_text(call["name"], arguments), usage, pending
            )
        if tool_messages and messages is not None:
            messages.append({
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": call["arguments"],
                        },
                    }
                    for call in calls
                ],
            })
            messages.extend(tool_messages)
            followup = self._deepseek_request(messages, tools, mode=mode)
            usage = self._add_usage(usage, self._chat_usage(followup))
            choices = followup.get("choices") or []
            followup_message = choices[0].get("message", {}) if choices else {}
            followup_calls = []
            for raw_call in followup_message.get("tool_calls") or []:
                function = raw_call.get("function") or {}
                followup_calls.append({
                    "id": str(raw_call.get("id") or ""),
                    "name": str(function.get("name") or ""),
                    "arguments": str(function.get("arguments") or "{}"),
                })
            if followup_calls:
                # Reading status and then deciding to move is a two-round
                # tool flow. The second call still requires explicit user
                # confirmation and must not be flattened into prose.
                return self._streamed_tool_result(
                    followup_calls,
                    usage,
                    mode=mode,
                    route=route,
                )
            answer = str(followup_message.get("content") or "").strip()
            if answer:
                result = self._result(answer, usage, tool_results=tool_results)
                result.update(cad_artifact)
                return result
        result = self._result(
            "\n".join(safe_results) or "工具调用已完成。",
            usage,
            tool_results=tool_results,
        )
        result.update(cad_artifact)
        return result

    @staticmethod
    def _env_timeout(name: str, default: float, *, maximum: float) -> float:
        try:
            value = float(os.getenv(name, str(default)))
        except (TypeError, ValueError):
            value = default
        return max(0.1, min(maximum, value))

    def _deepseek_timeout(self, kind: str, default: float) -> float:
        value = getattr(self, f"_deepseek_{kind}_timeout", None)
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
        return self._env_timeout(
            f"XLINE_AGENT_DEEPSEEK_{kind.upper()}_TIMEOUT_SECONDS",
            default,
            maximum=900.0,
        )

    def _set_deepseek_socket_timeout(
        self,
        connection: http.client.HTTPSConnection | None,
        deadline: float,
    ) -> None:
        self._deepseek_transport().set_socket_timeout(connection, deadline)

    def _read_deepseek_body(
        self,
        response: http.client.HTTPResponse,
        connection: http.client.HTTPSConnection | None,
        deadline: float,
    ) -> str:
        return self._deepseek_transport().read_body(
            response, connection, deadline
        )

    @staticmethod
    def _unpack_deepseek_response(
        result: Any,
    ) -> tuple[http.client.HTTPSConnection | None, http.client.HTTPResponse]:
        return DeepSeekTransport.unpack(result)

    @staticmethod
    def _close_deepseek_response(
        connection: http.client.HTTPSConnection | None,
        response: Any,
    ) -> None:
        DeepSeekTransport.close(connection, response)

    def _deepseek_transport(self) -> DeepSeekTransport:
        return DeepSeekTransport(
            api_key=self.api_key,
            timeout_for=self._deepseek_timeout,
        )

    def _deepseek_response(
        self, payload: dict[str, Any]
    ) -> tuple[http.client.HTTPSConnection, http.client.HTTPResponse]:
        return self._deepseek_transport().open(payload)

    @staticmethod
    def _selected_deepseek_tools(
        message: str,
        *,
        mode: str = "work",
        route: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        mode = RobotAgentService.normalize_agent_mode(mode)
        text = message.lower()
        route = route or RobotAgentService.route_intent(message, mode)
        route = RobotAgentService._with_edit_domain(route)
        family = route["tool_family"]
        names = {"get_robot_status", "stop_robot"}
        if family == "motion":
            names.update({"drive_robot", "drive_sequence"})
        if mode == "advanced" and family == "cad":
            names.update({
                "parameterize_design",
                "clarify_requirements",
                "create_creative_project",
                "update_creative_project",
                "select_design_variant",
                "prepare_project_plan",
                "refresh_project_plan",
                "refresh_project_execution",
                "assess_project_recovery",
                "generate_project_report",
                "check_drawing_feasibility",
                "inspect_drawing",
                "list_elements",
                "diff_drawing",
                "validate_drawing",
                "snapshot_drawing",
                "analyze_geometry_topology",
                "layer_drawing_paths",
                "validate_preview_paths",
            })
            if route.get("edit_domain") == "standalone_drawing":
                names.add("modify_drawing")
        if mode == "advanced" and family == "mission":
            names.update({
                "set_mission", "execute_prepared_mission",
                "refresh_project_plan", "refresh_project_execution",
            })
        if mode == "advanced" and family == "printer":
            names.add("control_printer")
        if mode == "base" and family == "printer":
            names.add("printer_spray")
        if mode == "advanced" and family == "localization":
            names.add("control_ln150")
        if mode == "advanced" and family == "telemetry" and route["name"] == "diagnosis":
            names.update({
                "recommend_recovery", "assess_project_recovery",
                "prepare_project_recovery",
            })
        if mode == "advanced" and family == "mission" and any(
            word in text for word in ("报告", "验收", "偏差", "轨迹对比")
        ):
            names.update({"refresh_project_execution", "generate_project_report"})
        names = {
            name for name in names
            if agent_tool_allowed(name, mode) and name not in MODEL_HIDDEN_TOOLS
        }
        return [
            tool
            for tool in DEEPSEEK_TOOLS
            if tool["function"]["name"] in names
        ]

    def _chat_json_movement(self, content: str) -> dict[str, Any] | None:
        """Turn only the explicit Chat movement-demo JSON into a confirmed action."""
        raw = content.strip()
        if not raw.startswith("{"):
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                raw = raw[start : end + 1].strip()
        if raw.startswith("```"):
            raw = re.sub(
                r"^```(?:json)?\s*|\s*```$", "", raw,
                flags=re.IGNORECASE | re.DOTALL,
            ).strip()
        if not raw.startswith("{"):
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict) or payload.get("task") not in {
            "movement_demo", "movement_command"
        }:
            return None
        forbidden_keys = {
            "ink", "printer", "printer_name", "mission", "project",
            "project_id", "drawing", "file_name", "spray", "printing",
        }
        if forbidden_keys.intersection(payload):
            return self._result(
                "Chat 运动 JSON 只能包含底盘运动内容，不能包含喷墨、喷码、项目或划线任务字段。",
                self._empty_usage(),
            )
        raw_steps = payload.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            return self._result("Chat 移动演示 JSON 缺少 steps 数组。", self._empty_usage())
        steps: list[dict[str, Any]] = []
        for index, item in enumerate(raw_steps, start=1):
            if not isinstance(item, dict):
                return self._result(f"第 {index} 段移动不是 JSON 对象。", self._empty_usage())
            try:
                linear = float(item.get("linear", 0.0))
                angular = float(item.get("angular", 0.0))
                duration = float(item.get("duration_seconds", item.get("duration", 0.0)))
            except (TypeError, ValueError):
                return self._result(f"第 {index} 段移动的速度或持续时间无效。", self._empty_usage())
            step, error = validate_tool_arguments(
                "drive_robot",
                {"linear": linear, "angular": angular, "duration_seconds": duration},
            )
            if step is None:
                return self._result(f"第 {index} 段移动不符合安全限制：{error}", self._empty_usage())
            steps.append(step)
        if len(steps) == 1:
            name, arguments = "drive_robot", steps[0]
        else:
            name, arguments = "drive_sequence", {"steps": steps}
        return self._result(
            f"已识别 Chat 移动演示，共 {len(steps)} 段。请确认周围环境和急停装置后执行。",
            self._empty_usage(),
            self._register_pending(name, arguments),
        )

    @staticmethod
    def _chat_usage(response: dict[str, Any]) -> dict[str, int]:
        usage = response.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens", 0))
        output_tokens = int(usage.get("completion_tokens", 0))
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": int(usage.get("total_tokens", input_tokens + output_tokens)),
        }

    def _register_pending(
        self, name: str, arguments: dict[str, Any], *, mode: str = "base"
    ) -> dict[str, Any]:
        mode = normalize_policy_mode(mode)
        policy = agent_tool_policy(name, mode)
        if not policy["allowed"]:
            raise PermissionError(policy["reason"])
        arguments = dict(arguments)
        prepared_modification = None
        if name == "modify_drawing":
            normalized = self._normalize_legacy_modify_arguments(arguments)
            validated, _ = validate_tool_arguments(name, normalized)
            if validated is not None:
                arguments = self._drop_none_values(validated)
            prepared_modification = self._prepare_drawing_modification(arguments)
            if prepared_modification.get("ok") is True:
                arguments.setdefault(
                    "source_sha256", prepared_modification["source_sha256"]
                )
                if prepared_modification.get("source_version") is not None:
                    arguments.setdefault(
                        "source_version", prepared_modification["source_version"]
                    )
        now = datetime.now()
        owner_id = current_agent_user_id()
        pending_lock = getattr(self, "_pending_lock", None)
        if pending_lock is None:
            pending_lock = self._pending_lock = threading.RLock()
        with pending_lock:
            existing = next(
                (
                    (pending_id, pending_action)
                    for pending_id, pending_action in self.pending.items()
                    if pending_action.expires_at > now
                    and pending_action.name == name
                    and pending_action.mode == mode
                    and pending_action.owner_id == owner_id
                    and pending_action.arguments == arguments
                ),
                None,
            )
            if existing is not None:
                action_id, action = existing
            else:
                action_id = uuid.uuid4().hex
                action = PendingAction(
                    name=name,
                    arguments=arguments,
                    expires_at=now + timedelta(minutes=2),
                    mode=mode,
                    owner_id=owner_id,
                )
                self.pending[action_id] = action
                agent_tasks.create_pending(
                    action_id, name, arguments, action.expires_at,
                    agent_mode=mode, owner_id=owner_id,
                )
        result = {
            "id": action_id,
            "name": name,
            "label": self._action_label(name, arguments),
            "arguments": arguments,
            "expires_in_seconds": 120,
            "agent_policy": policy,
        }
        result["preflight"] = build_action_preflight(name, arguments)
        spec = TOOL_REGISTRY.get(name)
        if spec is not None:
            result["confirmation_policy"] = {
                "required": spec.requires_confirmation,
                "risk": spec.risk,
                "scope": "仅确认本次显示的工具和参数，不能授权后续其他操作",
            }
        if name in {"drive_robot", "drive_sequence"}:
            result["motion_json"] = {
                "schema_version": "1.0",
                "task": "movement_command",
                "steps": [
                    dict(arguments)
                ] if name == "drive_robot" else [
                    dict(step) for step in arguments.get("steps", [])
                ],
            }
        if name == "modify_drawing" and isinstance(prepared_modification, dict):
            if prepared_modification.get("ok") is True:
                result.update({
                    "preview_status": "ready",
                    "preview_token": action_id,
                    "preview_paths": prepared_modification["diff_preview_paths"],
                    "cancel_preview_paths": prepared_modification["source_preview_paths"],
                    "review": prepared_modification["review"],
                    "command_batch": prepared_modification["command_batch"],
                    "geometry_diff": prepared_modification["geometry_diff"],
                    "path_impact": prepared_modification["path_impact"],
                    "scope_validation": prepared_modification.get("scope_validation"),
                })
            else:
                message = str(
                    prepared_modification.get("message") or "图纸修改预览生成失败"
                )
                result.update({
                    "preview_status": "invalid",
                    "preview_error": message,
                    "preflight": {
                        "ready": False,
                        "checks": [{
                            "key": "drawing_preview",
                            "label": "图纸修改预览",
                            "ok": False,
                            "detail": message,
                        }],
                    },
                })
        return result

    @staticmethod
    def _bind_drawing_selection(
        name: str,
        arguments: dict[str, Any],
        route: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Bind the editor selection so the model cannot silently retarget it."""
        if name != "modify_drawing" or not isinstance(route, dict):
            return arguments
        selection = route.get("drawing_selection")
        if not isinstance(selection, dict):
            return arguments
        bound = dict(arguments)
        bound["source_file_name"] = selection.get("source_file_name")
        scope = selection.get("scope")
        if scope == "logical_object":
            bound["target"] = {
                "scope": "logical_object",
                "object_id": selection.get("object_id"),
                "object_ids": list(selection.get("object_ids") or []),
                "geometry_ids": list(selection.get("geometry_ids") or []),
                "instance_ids": [],
            }
        else:
            bound["target"] = {
                "scope": "geometry",
                "geometry_ids": list(selection.get("geometry_ids") or []),
                "instance_ids": [],
            }
        return bound

    @staticmethod
    def _normalize_legacy_modify_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
        """Keep pre-target pending actions replayable after the typed contract upgrade."""
        if "target" in arguments:
            return arguments
        operations = arguments.get("operations")
        if not isinstance(operations, list):
            return arguments
        ids: list[int] = []
        normalized_operations: list[dict[str, Any]] = []
        for operation in operations:
            if not isinstance(operation, dict):
                normalized_operations.append(operation)
                continue
            item = dict(operation)
            kind = str(item.get("op", item.get("operation", ""))).lower()
            if kind in {"update", "remove"}:
                raw_id = item.get("geometry_id", item.get("id"))
                try:
                    geometry_id = int(raw_id)
                except (TypeError, ValueError):
                    geometry_id = None
                if geometry_id is not None:
                    ids.append(geometry_id)
                    item["geometry_id"] = geometry_id
                    item.pop("id", None)
                    if kind == "update" and isinstance(item.get("geometry"), dict):
                        geometry = dict(item.pop("geometry"))
                        geometry.pop("id", None)
                        geometry.pop("type", None)
                        geometry.pop("template_instance", None)
                        geometry.pop("template_type", None)
                        item["patch"] = geometry
            normalized_operations.append(item)
        if not ids:
            return arguments
        normalized = dict(arguments)
        normalized["target"] = {
            "scope": "geometry",
            "geometry_ids": sorted(set(ids)),
            "instance_ids": [],
        }
        normalized["operations"] = normalized_operations
        return normalized

    @staticmethod
    def _drop_none_values(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: RobotAgentService._drop_none_values(item)
                for key, item in value.items()
                if item is not None
            }
        if isinstance(value, list):
            return [RobotAgentService._drop_none_values(item) for item in value]
        return value

    @staticmethod
    def _drawing_payload(arguments: dict[str, Any]) -> dict[str, Any]:
        geometries = arguments.get("geometries")
        layered = layer_drawing_paths(
            geometries if isinstance(geometries, list) else [], "center"
        )
        return {
            "schema_version": "1.0",
            "unit": "mm",
            "logical_objects": list(arguments.get("logical_objects") or []),
            "topology": dict(arguments.get("topology") or {}),
            **layered,
        }

    def _geometry_preview(
        self, arguments: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Render generic CAD geometry without depending on a tool name."""
        candidate_paths = geometry_preview_paths(self._drawing_payload(arguments))
        validated = validate_preview_paths(candidate_paths)
        return validated["paths"] if validated["ok"] else []

    def _prepare_drawing_modification(
        self, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Build a deterministic review without writing a drawing version."""
        source_file_name = str(arguments.get("source_file_name") or "")
        source_path = resolve_drawing(source_file_name)
        if source_path is None:
            return {"ok": False, "message": f"源图纸不存在：{source_file_name}"}
        operation_id = str(arguments.get("operation_id") or "").strip()
        if operation_id:
            previous = drawing_versions.find_by_operation_id(operation_id)
            if previous:
                return {
                    "ok": False,
                    "message": f"该修改操作已处理：{previous['file_name']}",
                    "duplicate": True,
                    "version": previous,
                }
        source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
        expected_sha256 = str(arguments.get("source_sha256") or "").strip().lower()
        if expected_sha256 and expected_sha256 != source_sha256:
            return {
                "ok": False,
                "message": "源图纸已发生变化，请重新加载最新图纸后生成预览。",
                "conflict": True,
                "actual_source_sha256": source_sha256,
                "expected_source_sha256": expected_sha256,
            }
        tracked_latest = drawing_versions.latest_for_file(source_file_name)
        source_version = int(tracked_latest["version"]) if tracked_latest else None
        expected_version = arguments.get("source_version")
        if (
            expected_version is not None
            and source_version is not None
            and int(expected_version) != source_version
        ):
            return {
                "ok": False,
                "message": "源图纸版本已更新，请重新加载最新版本后生成预览。",
                "conflict": True,
                "expected_source_version": int(expected_version),
                "actual_source_version": source_version,
                "latest_version": tracked_latest,
            }
        try:
            source_payload = json.loads(source_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"ok": False, "message": "源图纸无法读取或 JSON 格式无效。"}
        source_lines = source_payload.get("lines") if isinstance(source_payload, dict) else None
        if not isinstance(source_lines, list):
            return {"ok": False, "message": "源图纸不包含可修改的 lines 几何。"}
        target = arguments.get("target")
        target = target if isinstance(target, dict) else None
        target_scope = str(target.get("scope") or "") if target else ""
        selected_ids_raw = arguments.get("selected_geometry_ids")
        target_instance_ids: set[int] = set()
        if target_scope == "geometry":
            selected_ids_raw = target.get("geometry_ids")
        elif target_scope == "instance":
            target_instance_ids = {
                int(value) for value in target.get("instance_ids") or []
                if isinstance(value, int) and value > 0
            }
            existing_instances = {
                int(item.get("template_instance")) for item in source_lines
                if isinstance(item, dict)
                and isinstance(item.get("template_instance"), int)
                and int(item["template_instance"]) > 0
            }
            missing_instances = sorted(target_instance_ids - existing_instances)
            if not target_instance_ids or missing_instances:
                return {
                    "ok": False,
                    "message": "目标实例不存在或已过期，请重新载入图纸后选择目标。",
                }
            selected_ids_raw = [
                int(item["id"]) for item in source_lines
                if isinstance(item, dict)
                and item.get("template_instance") in target_instance_ids
                and isinstance(item.get("id"), int)
            ]
        elif target_scope == "logical_object":
            selected_ids_raw = target.get("geometry_ids")
            object_ids = [value for value in [
                target.get("object_id"), *(target.get("object_ids") or [])
            ] if value]
            logical_objects = source_payload.get("logical_objects", []) if isinstance(source_payload, dict) else []
            if not isinstance(logical_objects, list) or not object_ids:
                return {"ok": False, "message": "逻辑对象目标缺少有效对象身份，请重新选择图形。"}
            wanted_ids = {str(value) for value in object_ids}
            expected_ids = sorted({
                int(ref)
                for item in logical_objects
                if isinstance(item, dict) and str(item.get("object_id")) in wanted_ids
                for ref in item.get("geometry_refs") or []
                if str(ref).isdigit()
            })
            actual_ids = sorted({
                int(value) for value in selected_ids_raw or []
                if isinstance(value, int) and value > 0
            })
            if not expected_ids or actual_ids != expected_ids:
                return {"ok": False, "message": "逻辑对象选区与当前图纸的图元引用不一致，请重新点选对象。"}
        elif target is not None:
            return {"ok": False, "message": "修改目标范围无效，请重新选择图元或实例。"}
        selected_ids = {
            int(value) for value in selected_ids_raw or []
            if isinstance(value, int) and value > 0
        }
        if selected_ids_raw is not None and not selected_ids:
            return {"ok": False, "message": "当前没有明确选中的有效图元，请先选择线段或整个图形。"}
        if selected_ids:
            existing_ids = {
                int(item.get("id")) for item in source_lines
                if isinstance(item, dict) and str(item.get("id", "")).isdigit()
            }
            missing_ids = sorted(selected_ids - existing_ids)
            if missing_ids:
                return {"ok": False, "message": "当前选区已过期，请重新载入图纸后再修改。"}
        source_by_id = {
            int(item["id"]): item for item in source_lines
            if isinstance(item, dict) and isinstance(item.get("id"), int)
        }
        operations: list[dict[str, Any]] = []
        for operation in list(arguments.get("operations") or []):
            if not isinstance(operation, dict):
                operations.append(operation)
                continue
            kind = str(operation.get("op", operation.get("operation", ""))).lower()
            target_id_raw = operation.get("geometry_id", operation.get("id"))
            try:
                target_id = int(target_id_raw) if target_id_raw is not None else None
            except (TypeError, ValueError):
                target_id = None
            if kind == "update":
                geometry = operation.get("geometry")
                patch = operation.get("patch")
                if isinstance(patch, dict) and target_id in source_by_id:
                    geometry = deepcopy(source_by_id[target_id])
                    geometry.update({
                        key: deepcopy(value) for key, value in patch.items()
                        if value is not None
                    })
                operations.append({"op": "update", "id": target_id, "geometry": geometry})
            elif kind == "remove":
                operations.append({"op": "remove", "id": target_id})
            elif kind == "add":
                operations.append({"op": "add", "geometry": operation.get("geometry")})
            else:
                operations.append(dict(operation))

        if selected_ids:
            targeted_ids: set[int] = set()
            has_selected_edit = False
            for operation in operations:
                if not isinstance(operation, dict):
                    continue
                kind = str(operation.get("op", operation.get("operation", ""))).lower()
                try:
                    target_id = int(operation.get("id"))
                except (TypeError, ValueError):
                    target_id = None
                if kind in {"update", "remove"}:
                    if target_id is None or target_id not in selected_ids:
                        return {"ok": False, "message": "修改目标不在当前选择中，已阻止操作。"}
                    targeted_ids.add(target_id)
                    has_selected_edit = True
                elif kind == "add":
                    geometry = operation.get("geometry")
                    try:
                        new_id = int(geometry.get("id")) if isinstance(geometry, dict) else None
                    except (TypeError, ValueError):
                        new_id = None
                    if new_id is None or new_id in selected_ids:
                        return {"ok": False, "message": "新增图元必须使用未占用的图元 ID。"}
                    if target_scope == "geometry":
                        return {
                            "ok": False,
                            "message": "单图元目标不能新增其他图元；请明确选择完整实例后再新增。",
                        }
                    if (
                        target_scope == "instance"
                        and isinstance(geometry, dict)
                        and geometry.get("template_instance") not in target_instance_ids
                    ):
                        return {
                            "ok": False,
                            "message": "新增图元不属于目标实例，已阻止操作。",
                        }
                else:
                    return {"ok": False, "message": "当前选区包含无效的修改操作。"}
            if not has_selected_edit:
                return {"ok": False, "message": "请先修改或删除当前选中的图元，不能只在选区外新增图形。"}
        modification = apply_drawing_modifications(
            source_lines, operations
        )
        if not modification["ok"]:
            reason = "图纸修改未通过：" + "；".join(modification["errors"])
            return {
                "ok": False,
                "message": reason,
                "modification": modification,
                "rollback_evidence": build_rejection_rollback_evidence(
                    source_lines, reason
                ),
            }
        geometries = list(modification["geometries"])
        feasibility = check_drawing_feasibility(geometries)
        if not feasibility["ok"]:
            reason = "修改后图纸检查未通过：" + "；".join(feasibility["errors"])
            return {
                "ok": False,
                "message": reason,
                "feasibility": feasibility,
                "modification": modification,
                "rollback_evidence": build_rejection_rollback_evidence(
                    source_lines, reason
                ),
            }
        geometry_diff = build_geometry_diff(source_lines, geometries)
        path_impact = build_path_impact(source_lines, geometries)
        scope_validation = None
        if target is not None:
            expected_modified_ids = {
                int(operation["id"]) for operation in operations
                if operation.get("op") == "update" and isinstance(operation.get("id"), int)
            }
            expected_removed_ids = {
                int(operation["id"]) for operation in operations
                if operation.get("op") == "remove" and isinstance(operation.get("id"), int)
            }
            expected_added_ids = {
                int(operation["geometry"]["id"]) for operation in operations
                if operation.get("op") == "add"
                and isinstance(operation.get("geometry"), dict)
                and isinstance(operation["geometry"].get("id"), int)
            }
            scope_validation = validate_target_change_scope(
                source_lines,
                geometries,
                target,
                expected_modified_ids=expected_modified_ids,
                expected_removed_ids=expected_removed_ids,
                expected_added_ids=expected_added_ids,
            )
            if scope_validation.get("ok") is not True:
                reason = str(scope_validation.get("message"))
                return {
                    "ok": False,
                    "message": reason,
                    "scope_validation": scope_validation,
                    "geometry_diff": geometry_diff,
                    "path_impact": path_impact,
                    "rollback_evidence": build_rejection_rollback_evidence(
                        source_lines, reason
                    ),
                }
        if not any(
            geometry_diff["counts"][key]
            for key in ("added", "removed", "modified")
        ):
            reason = "修改操作没有产生几何差异。"
            return {
                "ok": False,
                "message": reason,
                "geometry_diff": geometry_diff,
                "path_impact": path_impact,
                "rollback_evidence": build_rejection_rollback_evidence(
                    source_lines, reason
                ),
            }
        payload = self._drawing_payload({"geometries": geometries})
        final_preview_paths = self._geometry_preview({"geometries": geometries})
        source_preview_paths = self._geometry_preview({"geometries": source_lines})
        if not final_preview_paths:
            reason = "修改后图纸没有可预览的有效几何。"
            return {
                "ok": False,
                "message": reason,
                "rollback_evidence": build_rejection_rollback_evidence(
                    source_lines, reason
                ),
            }
        review = build_drawing_change_review(
            source_file_name,
            "",
            geometry_diff,
            path_impact,
            feasibility,
            source_sha256=source_sha256,
            source_version=source_version,
        )
        review["result"] = {
            "file_name": None,
            "status": "preview_pending",
            "next_action": "apply_changes",
        }
        review["scope_validation"] = scope_validation
        counts = geometry_diff.get("counts") or {}
        affected_geometry_count = (
            int(counts.get("added") or 0)
            + int(counts.get("removed") or 0)
            + int(counts.get("modified") or 0)
        )
        path_affected = bool(path_impact.get("affected_paths"))
        object_label = "整张图纸"
        target_ids: list[str] = []
        if target_scope == "logical_object":
            wanted_ids = {
                str(value) for value in [
                    target.get("object_id"), *(target.get("object_ids") or [])
                ] if value
            }
            matched = [
                item for item in source_payload.get("logical_objects") or []
                if isinstance(item, dict)
                and str(item.get("object_id")) in wanted_ids
            ]
            object_label = str(matched[0].get("label") or "逻辑对象") if matched else "逻辑对象"
            target_ids = [f"logical_object:{value}" for value in sorted(wanted_ids)]
        elif target_scope == "instance":
            type_by_instance: dict[int, str] = {}
            for item in source_lines:
                if (
                    isinstance(item, dict)
                    and item.get("template_instance") in target_instance_ids
                ):
                    template_type = str(item.get("template_type") or "").strip()
                    if template_type:
                        type_by_instance[int(item["template_instance"])] = template_type
            object_label = "、".join(
                f"{type_by_instance.get(instance_id) or '实例'} {instance_id}"
                for instance_id in sorted(target_instance_ids)
            ) or "模板实例"
            target_ids = [f"instance:{value}" for value in sorted(target_instance_ids)]
        elif target_scope == "geometry":
            object_label = f"单图元 × {len(selected_ids)}"
            target_ids = [f"geometry:{value}" for value in sorted(selected_ids)]
        operation_names = sorted({
            {"update": "修改", "remove": "删除", "add": "新增"}.get(
                str(operation.get("op", "")).lower(), str(operation.get("op", ""))
            )
            for operation in operations
            if isinstance(operation, dict)
        })
        parameter_parts: list[str] = []
        for operation in operations:
            if not isinstance(operation, dict):
                continue
            if str(operation.get("op", "")).lower() == "update":
                geometry = operation.get("geometry")
                if isinstance(geometry, dict):
                    for key in (
                        "radius", "length_mm", "width_mm", "height_mm",
                        "center_x", "center_y", "start_x", "start_y",
                        "end_x", "end_y", "angle_deg", "scale",
                    ):
                        if key in geometry:
                            parameter_parts.append(f"{key}={geometry[key]}")
                            break
            elif str(operation.get("op", "")).lower() == "remove":
                parameter_parts.append(f"删除图元 id={operation.get('id')}")
        plan_summary = {
            "object_label": object_label,
            "target_level": target_scope or "drawing",
            "target_ids": target_ids,
            "operation_label": "+".join(operation_names) or "修改",
            "parameters": parameter_parts[:6],
            "affected_geometry_count": affected_geometry_count,
            "affects_path": path_affected,
        }
        review["plan_summary"] = plan_summary
        return {
            "ok": True,
            "source_file_name": source_file_name,
            "source_path": source_path,
            "source_lines": source_lines,
            "source_sha256": source_sha256,
            "source_version": source_version,
            "tracked_latest": tracked_latest,
            "operation_id": operation_id,
            "modification": modification,
            "command_batch": modification.get("command_batch"),
            "geometries": geometries,
            "feasibility": feasibility,
            "geometry_diff": geometry_diff,
            "path_impact": path_impact,
            "scope_validation": scope_validation,
            "payload": payload,
            "final_preview_paths": final_preview_paths,
            "source_preview_paths": source_preview_paths,
            "diff_preview_paths": build_diff_preview_paths(geometry_diff),
            "review": review,
            "plan_summary": plan_summary,
        }

    @staticmethod
    def _preview_contract_from_points(
        paths: Any, *, namespace: str = "path_lines"
    ) -> list[dict[str, Any]]:
        """Convert stored point arrays into the App's validated preview contract."""
        if not isinstance(paths, list):
            return []
        candidates = []
        for item in paths:
            if isinstance(item, dict):
                candidate = dict(item)
                candidate.setdefault("namespace", namespace)
                candidate.setdefault("frame_id", "map")
                candidate.setdefault("route_type", "printing")
                candidates.append(candidate)
            elif isinstance(item, list):
                candidates.append({
                    "namespace": namespace,
                    "frame_id": "map",
                    "route_type": "printing",
                    "points": item,
                })
        validated = validate_preview_paths(candidates)
        return validated["paths"] if validated["ok"] else []

    @staticmethod
    def _is_design_generation_confirmation(message: str) -> bool:
        """Recognize the short confirmation sent after the design question."""
        normalized = re.sub(r"[\s，。！？、,.!?；;：:]+", "", message.strip().lower())
        if normalized in {
            "确认生成",
            "确认生成方案",
            "确认生成候选方案",
            "开始生成",
            "开始生成方案",
            "生成候选方案",
        }:
            return True
        return bool(
            re.match(r"^(?:确认|同意)(?:需求)?(?:并)?生成(?:cad)?候选(?:方案)?(?:只预览|不执行小车)*$", normalized)
            or
            re.search(r"(?:确认|同意|可以|就按|按照|按).{0,40}(?:生成|创建|出)(?:候选)?方案", normalized)
            or re.search(r"(?:确认|同意|可以).{0,40}(?:出图|生成图纸)", normalized)
        )

    @classmethod
    def _design_generation_confirmation_followup_route(
        cls, message: str, mode: str, history: list[dict[str, str]] | None
    ) -> dict[str, Any] | None:
        """Bind short approval replies to the immediately preceding design question."""
        if cls.normalize_agent_mode(mode) != "advanced":
            return None
        normalized = re.sub(r"[\s，。！？、,.!?；;：:]+", "", message.strip().lower())
        previous = next(
            (
                str(item.get("content") or "")
                for item in reversed(history or [])
                if item.get("role") == "assistant" and item.get("content")
            ),
            "",
        )
        short_approval = normalized in {
            "确认", "同意", "可以", "好的", "好", "没错", "是的", "对", "正确",
            "就按这个", "按这个", "就这样", "确认这个方案",
        }
        asked_to_generate = (
            any(marker in previous for marker in ("确认", "是否", "可以"))
            and any(marker in previous for marker in (
                "生成候选方案", "生成方案", "出图", "生成图纸", "再生成候选",
            ))
        )
        if not cls._is_design_generation_confirmation(message) and not (
            short_approval and asked_to_generate
        ):
            return None
        route = dict(cls.route_intent("确认生成候选方案", mode))
        route.update({
            "decision_source": "design_confirmation_followup",
            "review_required": False,
            "clarification_required": False,
            "resolved_message": "确认生成候选方案",
            "context_requirements": [],
            "requested_data_domains": [],
        })
        return route

    @staticmethod
    def _is_fresh_design_request(route: dict[str, Any]) -> bool:
        """Return true only for a new design brief, not candidate confirmation."""
        # An explicit project id from the App owns the conversation, even if
        # the follow-up text still contains creation words such as “新建” or
        # “画一个”. Do not drop it during requirement merge or confirmation.
        if str(route.get("selected_project_id") or "").strip():
            return False
        if (
            route.get("name") != "drawing_design"
            or route.get("operation") != "create"
        ):
            return False
        if route.get("stage") == "candidate_generation":
            return False
        return route.get("decision_source") not in {
            "deterministic_design_confirmation",
            "design_confirmation_followup",
        }

    @staticmethod
    def _project_id_from_route(route: dict[str, Any]) -> str | None:
        return project_id_from_route(
            route,
            fresh_design_request=RobotAgentService._is_fresh_design_request(route),
        )

    def _stale_project_guard(self, route: dict[str, Any]) -> str | None:
        """When the conversation memory references a project that no longer
        exists, clear the stale reference and return a guidance message so the
        workflow stops failing repeatedly; otherwise return ``None``.

        Only a project that is genuinely gone is forgotten. The reference
        resolution target is preferred over the raw memory list, so an
        ambiguous message or a reference to an older-but-valid project is
        never mis-blocked."""
        # A new design request is allowed to create a fresh project. Do not
        # let a deleted project from an earlier chat block unrelated work.
        # Stale-project protection remains active for edits, confirmations and
        # other project-scoped follow-ups where the old identity matters.
        if self._is_fresh_design_request(route):
            return None

        reference = route.get("reference_resolution")
        project_id = None
        if isinstance(reference, dict):
            target = reference.get("target")
            if isinstance(target, dict) and target.get("type") == "project":
                project_id = str(target.get("id") or "")
            ambiguous = bool(reference.get("ambiguous"))
        else:
            ambiguous = False
        if not project_id:
            project_id = self._project_id_from_route(route)
        if not project_id:
            return None
        if get_creative_project_store().get(project_id) is not None:
            return None
        conversation_id = self._conversation_id_from_route(route)
        if conversation_id:
            conversation_memory.forget_object(
                conversation_id, "project", project_id
            )
        if ambiguous:
            return None
        return (
            "检测到此前会话引用的项目已不存在（可能已被删除或后端数据有变更），"
            "已自动清理该引用。请重新描述你的需求（例如“画一个标准篮球场”），"
            "我会为你新建项目并继续。"
        )

    def _stale_project_tool_guide(
        self,
        name: str,
        arguments: dict[str, Any],
        output: dict[str, Any],
        route: dict[str, Any],
    ) -> dict[str, Any]:
        """When a project-scoped tool fails because the project is gone, clear
        the stale memory reference and hand the model a user-facing guidance
        message instead of an opaque failure.

        The memory reference is removed only after verifying the project is
        really missing. ``update``/``select_variant`` can also fail because of
        a state restriction or a missing variant while the project itself is
        still valid; in those cases the reference must be kept."""
        if not isinstance(output, dict):
            return output
        message = str(output.get("message") or "")
        if "创意项目不存在" not in message and "项目或候选方案不存在" not in message:
            return output
        project_id = str(arguments.get("project_id") or "").strip()
        project_gone = bool(project_id) and get_creative_project_store().get(project_id) is None
        conversation_id = self._conversation_id_from_route(route)
        if project_gone and conversation_id:
            conversation_memory.forget_object(
                conversation_id, "project", project_id
            )
        if not project_gone:
            return output
        output = dict(output)
        output["message"] = (
            "创意项目不存在（可能已被删除或后端数据有变更），"
            "请引导用户重新描述需求新建项目，不要继续使用旧项目。"
        )
        return output

    @staticmethod
    def _conversation_id_from_route(route: dict[str, Any]) -> str | None:
        return conversation_id_from_route(route)

    @staticmethod
    def _merge_design_requirements(
        project: dict[str, Any], route: dict[str, Any]
    ) -> dict[str, Any]:
        return merge_design_requirements(project, route)

    def _deterministic_design_confirmation(
        self, message: str, route: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Legacy adapter to the production entry, never a second producer."""
        project_id=self._project_id_from_route(route)
        project=get_creative_project_store().get(project_id) if project_id else None
        gate=design_confirmation_gate(message,project,
            explicit_confirmation=self._is_design_generation_confirmation(message))
        if not gate.get('should_handle'):
            return None
        return self._formal_cad_construction(message,{
            **route,'name':'drawing_design','tool_family':'cad','operation':'create',
            'stage':'candidate_generation','decision_source':'design_confirmation_followup',
            'selected_project_id':project_id},mode='advanced')

    def _confirm_parameterized_project(
        self, message: str, route: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Complete candidate generation when a model omits its tool call.

        This is intentionally limited to the design stage. It never plans,
        requests execution, changes hardware, or infers missing dimensions.
        """
        project_id = self._project_id_from_route(route)
        project = get_creative_project_store().get(project_id) if project_id else None
        if isinstance(project, dict):
            from .cad_template_plan import template_covers_request
            prompt = str(project.get("original_prompt") or project.get("name") or "")
            shape = str((project.get("requirements") or {}).get("shape") or "")
            source = project.get("source_drawing") or {}
            has_source = bool(source.get("geometries"))
            template_request = bool(recognize_drawing_template(prompt) or recognize_drawing_template_set(prompt)
                or recognize_drawing_template(str(project.get("name") or "")))
            if not has_source:
                if template_request:
                    if not template_covers_request(project, route):
                        return None
                elif (reference_contract(prompt) or explicit_composition(prompt)
                      or has_compound_primitives(prompt)
                      or (shape and not is_generator_supported_shape(shape))):
                    return None
                elif not list(project.get('variants') or []):
                    # New non-template candidates must execute a construction
                    # plan; indexed shape/radius fields cannot replace prose.
                    return None
        confirmation_gate = design_confirmation_gate(
            message,
            project,
            explicit_confirmation=self._is_design_generation_confirmation(message),
        )
        if confirmation_gate.get("should_handle") is not True:
            return None
        if confirmation_gate.get("error"):
            return {**self._result(str(confirmation_gate["error"]), self._empty_usage()),
                    "ok": False, "error_code": "candidate_generation_failed"}
        project = confirmation_gate["project"]

        variants = project.get("variants")
        candidate_context = candidate_generation_context(project, route)
        preflight = candidate_preflight(
            project, candidate_context, check_requirements=False
        )
        if preflight.get("ok") is not True:
            return {**self._result(str(preflight.get("message") or "候选方案需求尚未就绪。"), self._empty_usage()),
                    "ok": False, "error_code": "candidate_generation_failed"}
        try:
            from .cad_template_plan import interpret_template_project
            template_interpretation = interpret_template_project(project, route)
            if template_interpretation is not None:
                expected_geometries_for_migration = template_interpretation["trial_result"]["geometries"]
            elif variants:
                expected_geometries_for_migration, _ = design_geometries_for_project(project, route)
            else:
                expected_geometries_for_migration = None
        except ValueError as exc:
            return {**self._result("构造计划未通过校验：" + str(exc), self._empty_usage()), "ok": False}

        restore_decision = restore_existing_candidate(
            project,
            variants,
            candidate_context,
            (
                expected_geometries_for_migration
                if isinstance(expected_geometries_for_migration, list)
                else None
            ),
            migrate_variant=get_creative_project_store().migrate_variant_instances,
        )
        variant = restore_decision["variant"]
        quantity_mismatch = bool(restore_decision["quantity_mismatch"])
        if variant is not None:
            project = get_creative_project_store().get(str(project["id"])) or project
            variants = project.get("variants") or variants
            variant = next(
                (item for item in variants if item.get("id") == variant.get("id")),
                variant,
            )
            geometries = variant.get("geometries") if isinstance(variant, dict) else None
            geometries = geometries if isinstance(geometries, list) else []
            restored_preview = self._geometry_preview({"geometries": geometries})
            response_payload = candidate_response_payload(
                project,
                variant,
                restored_preview,
                self._drawing_payload({"geometries": geometries}),
                restored=True,
            )
            response_text = str(response_payload.pop("response_text"))
            tool_result = response_payload.pop("tool_result")
            return {
                **self._result(
                    response_text,
                    self._empty_usage(),
                    tool_results=[tool_result],
                ),
                **response_payload,
            }

        prepared = prepare_new_candidate(
            project,
            route,
            candidate_context,
            quantity_mismatch=quantity_mismatch,
            update_project=get_creative_project_store().update,
            construction_interpretation=template_interpretation,
        )
        if prepared.get("ok") is not True:
            return {**self._result(str(prepared.get("message") or "候选方案准备失败。"), self._empty_usage()),
                    "ok": False, "error_code": "candidate_geometry_verification_failed",
                    "failure_category": "geometry_acceptance_failure",
                    "retryable": True, "retry_limit": 3,
                    "next_action": "retry_candidate_generation"}
        persisted = persist_prepared_candidate(
            prepared,
            add_variant=get_creative_project_store().add_variant,
            get_project=get_creative_project_store().get,
            geometry_preview=self._geometry_preview,
            drawing_payload=self._drawing_payload,
        )
        if persisted.get("ok") is not True:
            return {**self._result(str(persisted.get("message") or "候选方案保存失败。"), self._empty_usage()),
                    "ok": False, "error_code": "candidate_persistence_failed",
                    "failure_category": "persistence_failure",
                    "retryable": True, "retry_limit": 3,
                    "next_action": "retry_candidate_generation"}
        response_payload = persisted["response"]
        response_text = str(response_payload.pop("response_text"))
        tool_result = response_payload.pop("tool_result")
        return {
            **self._result(
                response_text,
                self._empty_usage(),
                tool_results=[tool_result],
            ),
            **response_payload,
        }

    _INCREMENTAL_COPY_MARKERS = (
        "同样", "相同", "一样的", "复制", "拷贝",
        "再画", "再规划", "再加", "多一个", "另一个",
        "规划一个", "画一个", "添加一个", "增加一个",
    )

    _COPY_DIRECTION_SCALE = {"左": -1.0, "右": 1.0, "上": 1.0, "下": -1.0}

    @staticmethod
    def _parse_copy_offset(message: str) -> tuple[str, float] | None:
        match = re.search(
            r"(?:向|往|到)?(?P<dir>左|右|上|下)(?:侧|方|边)?(?:的|方向|位置)?\s*"
            r"(?:移动|平移|挪动|偏移)?\s*(?P<value>\d+(?:\.\d+)?)\s*"
            r"(?P<unit>m|米|mm|毫米|cm|厘米|公分)",
            message,
            re.IGNORECASE,
        )
        if match is None:
            return None
        value = float(match.group("value"))
        scale = {
            "m": 1000.0, "米": 1000.0,
            "mm": 1.0, "毫米": 1.0,
            "cm": 10.0, "厘米": 10.0, "公分": 10.0,
        }[match.group("unit").lower()]
        return match.group("dir"), value * scale

    @staticmethod
    def _translate_copy_geometries(
        geometries: list[dict[str, Any]], dx: float, dy: float,
    ) -> list[dict[str, Any]] | None:
        result: list[dict[str, Any]] = []
        for geometry in geometries:
            if not isinstance(geometry, dict):
                return None
            copied = deepcopy(geometry)
            geometry_type = str(copied.get("type"))
            keys = {
                "line": ("start", "end"), "circle": ("center",),
                "arc": ("center",), "ellipse": ("center",), "text": ("position",),
            }.get(geometry_type, ())
            for key in keys:
                point = copied.get(key)
                if isinstance(point, dict) and isinstance(point.get("x"), (int, float)):
                    point["x"] = float(point["x"]) + dx
                    point["y"] = float(point["y"]) + dy
            if geometry_type == "polyline" and isinstance(copied.get("vertices"), list):
                for point in copied["vertices"]:
                    if isinstance(point, dict) and isinstance(point.get("x"), (int, float)):
                        point["x"] = float(point["x"]) + dx
                        point["y"] = float(point["y"]) + dy
            if geometry_type == "spline" and isinstance(copied.get("control_points"), list):
                for point in copied["control_points"]:
                    if isinstance(point, dict) and isinstance(point.get("x"), (int, float)):
                        point["x"] = float(point["x"]) + dx
                        point["y"] = float(point["y"]) + dy
            result.append(copied)
        return result

    def _recover_incremental_copy(
        self,
        project: dict[str, Any],
        route: dict[str, Any],
        usage: dict[str, int],
    ) -> dict[str, Any] | None:
        message = str(route.get("user_message") or "")
        if not any(marker in message for marker in self._INCREMENTAL_COPY_MARKERS):
            return None
        parsed = self._parse_copy_offset(message)
        if parsed is None:
            return None
        direction, distance_mm = parsed
        if distance_mm <= 0:
            return None
        project, parent, activation_error = self._activate_preview_variant_for_edit(
            project, route
        )
        if activation_error or not isinstance(parent, dict):
            return None
        parent_geometries = list(parent.get("geometries") or [])
        if not parent_geometries:
            return None
        if direction in {"左", "右"}:
            dx = distance_mm * self._COPY_DIRECTION_SCALE[direction]
            dy = 0.0
        else:
            dx = 0.0
            dy = distance_mm * self._COPY_DIRECTION_SCALE[direction]
        geometries = self._translate_copy_geometries(parent_geometries, dx, dy)
        if geometries is None:
            return None
        description = "在%s侧 %.3g 米处复制一个相同图形" % (
            direction, distance_mm / 1000.0
        )
        return self._persist_candidate_edit(
            project, parent, geometries, description,
        )

    @staticmethod
    def _effective_parent_variant(
        project: dict[str, Any], parent_variant_id: str | None = None,
        preferred_variant_id: str | None = None,
    ) -> dict[str, Any] | None:
        return effective_parent_variant(
            project,
            parent_variant_id=parent_variant_id,
            preferred_variant_id=preferred_variant_id,
        )

    def _activate_preview_variant_for_edit(
        self,
        project: dict[str, Any],
        route: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any] | None, str | None]:
        """Use the candidate visible on the right as the next edit parent."""
        selection = route.get("drawing_selection")
        selection_variant_id = (
            str(selection.get("variant_id") or "")
            if isinstance(selection, dict)
            else ""
        )
        preview_variant_id = selection_variant_id or str(
            route.get("selected_variant_id") or ""
        )
        parent = self._effective_parent_variant(
            project,
            preferred_variant_id=preview_variant_id or None,
        )
        if preview_variant_id and parent is None:
            return project, None, "当前右侧预览方案已失效，请刷新候选方案后重试。"
        if not preview_variant_id:
            return project, parent, None

        if (
            project.get("status") != "designing"
            or str(project.get("design_base_variant_id") or "")
            != preview_variant_id
        ):
            activated = get_creative_project_store().begin_design_iteration(
                str(project.get("id") or ""), preview_variant_id
            )
            if not isinstance(activated, dict):
                return project, None, "当前右侧方案不能继续修改，请刷新项目状态后重试。"
            project = activated
            parent = self._effective_parent_variant(
                project,
                preferred_variant_id=preview_variant_id,
            )
        return project, parent, None

    def generate_project_candidate(self, project_id: str) -> dict[str, Any]:
        """Generate a candidate for the project explicitly selected by the App.

        Project toolbar actions must not depend on conversation memory because
        the user can switch projects without starting a new chat.
        """
        project = get_creative_project_store().get(project_id)
        if project is None:
            result = self._result(
                "当前项目已不存在，项目列表已刷新，请重新选择或新建设计。",
                self._empty_usage(),
            )
            result["ok"] = False
            return result
        route = {
            "name": "drawing_design",
            "tool_family": "cad",
            "operation": "create",
            "stage": "candidate_generation",
            "decision_source": "design_confirmation_followup",
            "selected_project_id": project_id,
            "object_memory": {
                "objects": {
                    "project": [{
                        "type": "project",
                        "id": project_id,
                        "label": str(project.get("name") or "当前项目"),
                    }]
                }
            },
            "retrieved_memory": {},
        }
        construction = self._formal_cad_construction(
            "确认生成候选方案",
            route,
            mode="advanced",
        )
        if construction is not None:
            if (construction.get("error_code") == "candidate_generation_failed"
                    and construction.get("construction_retry_available")
                    and not route.get("construction_retry")):
                # One bounded model retry for a complete confirmed project.
                # The commit layer remains the only persistence boundary, so
                # a failed first attempt cannot create a duplicate variant.
                retry_route = {**route, "construction_retry": True}
                retry = self._formal_cad_construction(
                    "确认生成候选方案（重试一次）", retry_route, mode="advanced"
                )
                if retry is not None:
                    return retry
            return construction
        fallback_requirements = (
            project.get("requirements")
            if isinstance(project, dict)
            else None
        )
        fallback_requirements = (
            fallback_requirements
            if isinstance(fallback_requirements, dict)
            else {}
        )
        fallback_shape = str(fallback_requirements.get("shape") or "").strip()
        fallback_dimensions = fallback_requirements.get("dimensions")
        fallback_dimensions = (
            fallback_dimensions
            if isinstance(fallback_dimensions, dict)
            else {}
        )
        shape_recorded = bool(fallback_shape) and fallback_shape != "generic_2d_cad"
        dimensions_recorded = bool(
            fallback_dimensions.get("width_m") or fallback_dimensions.get("height_m")
        )
        if shape_recorded or dimensions_recorded:
            # 需求已确认并落库（图形/尺寸至少一项完整）：不是缺参数的错误，
            # 候选由 AI 建模生成，返回正常提示（前端绿框），避免"需求已给全
            # 却被判为缺参数"的误导红框。
            fallback = self._result(
                "已记录需求，但本次未生成有效候选。当前没有后台生成任务，请重试生成候选方案。",
                self._empty_usage(),
            )
            fallback.update(ok=False, error_code="candidate_generation_failed",
                            failure_category="model_or_construction_failure",
                            retryable=True, retry_limit=3,
                            next_action="retry_candidate_generation")
            return fallback
        fallback = self._result(
            "当前项目还不能生成方案，请先补充图形和关键尺寸。",
            self._empty_usage(),
        )
        fallback["ok"] = False
        return fallback

    def _compatible_chat(
        self,
        message: str,
        history: list[dict[str, str]],
        *,
        mode: str = "base",
        route: dict[str, Any] | None = None,
        context_message: str | None = None,
    ) -> dict[str, Any]:
        provider_name, base_url = PROVIDERS[self.mode]
        adapter = provider_adapter(self.mode)
        system = self._system_context(
            context_message or message, mode=mode, route=route
        )
        messages = [
            {"role": item.get("role", "user"), "content": item.get("content", "")}
            for item in history[-4:]
            if item.get("content")
        ]
        messages.append({"role": "user", "content": message})
        request = adapter.build_request(
            base_url=base_url,
            model=self.model,
            api_key=self.api_key,
            system=system,
            messages=messages,
            max_tokens=1200,
        )
        request_lease = user_request_limiter.acquire(current_agent_user_id())
        request_lease.__enter__()
        try:
            result = adapter.send_json(
                request,
                timeout=self._env_timeout(
                    "XLINE_AGENT_MODEL_REQUEST_TIMEOUT_SECONDS",
                    45.0,
                    maximum=900.0,
                ),
            )
        finally:
            request_lease.__exit__(None, None, None)

        parsed = adapter.parse_reply(result)
        text = parsed.text
        usage = parsed.usage
        if not text.strip():
            choices = result.get("choices") or []
            finish_reason = choices[0].get("finish_reason") if choices else None
            raise RuntimeError(
                f"{provider_name} 未返回正文（finish_reason={finish_reason or 'unknown'}）。"
                "请确认模型名称有效，或改用该服务商的标准对话模型。"
            )
        return self._result(text, usage)

    def _local_intent(
        self,
        message: str,
        *,
        allow_design: bool = True,
        mode: str | None = None,
    ) -> dict[str, Any] | None:
        legacy_unscoped_call = mode is None
        mode = normalize_policy_mode(
            mode if mode is not None else ("advanced" if allow_design else "base")
        )
        normalized = message.lower().replace("×", "x").replace("*", "x")
        spray_intent = self._local_spray_intent(normalized)
        if spray_intent is not None:
            spraying, printer_name = spray_intent
            arguments = {"printer_name": printer_name, "spraying": spraying}
            return self._result(
                "已识别为持续喷墨控制。确认后才会改变喷墨状态；打开后可同时控制小车移动。"
                if spraying
                else "已识别为停止持续喷墨。确认后才会停止喷墨。",
                self._empty_usage(),
                self._register_pending("printer_spray", arguments, mode=mode),
            )
        if any(
            word in normalized
            for word in (
                "当前状态",
                "小车状态",
                "是否就绪",
                "能否控制",
                "能否开始任务",
                "是否可以开始任务",
                "是否能开始任务",
                "开始任务前检查",
                "执行前检查",
                "任务准备检查",
                "任务是否可以开始",
            )
        ):
            return self._result(self._local_diagnosis(), self._empty_usage())
        if normalized.strip() in {"停车", "停止", "立即停车", "停下"}:
            # Keep compatibility with integrations that still provide the
            # pre-mode two-argument safe executor.
            try:
                output = self._execute_safe("stop_robot", {}, mode=mode)
            except TypeError as error:
                if "mode" not in str(error):
                    raise
                output = self._execute_safe("stop_robot", {})
            return self._result(
                str(output["message"]),
                self._empty_usage(),
                tool_results=[self._tool_result_summary("stop_robot", output)],
            )
        template_match = recognize_drawing_template(normalized)
        if template_match is not None:
            template_action = self._local_template_intent(
                raw_message=message,
                match=template_match,
                allow_design=allow_design,
            )
            if template_action is not None:
                return template_action
        if mode == "base" or legacy_unscoped_call:
            polygon_motion = self._local_polygonal_motion_intent(normalized)
            if polygon_motion is not None:
                return polygon_motion
            circular_motion = self._local_circular_motion_intent(normalized)
            if circular_motion is not None:
                return circular_motion
            motion_sequence = self._local_motion_sequence_intent(normalized)
            if motion_sequence is not None:
                return motion_sequence
            turn_intent = self._local_turn_intent(normalized)
            if turn_intent is not None:
                return turn_intent
            drive_intent = self._local_drive_intent(normalized)
            if drive_intent is not None:
                return drive_intent
        if not allow_design:
            explicit_motion = any(
                word in normalized
                for word in (
                    "控制小车", "让小车", "小车走", "底盘", "机器人走",
                    "走一个", "走一圈", "运动演示", "从小车自身位置出发",
                )
            )
            design_request = any(
                word in normalized
                for word in ("图纸", "cad", "喷墨", "划线", "标线", "设计")
            )
            square_match = re.search(
                r"(?:边长|边长为|side)\s*(?:为|是|[:：])?\s*"
                r"(\d+(?:\.\d+)?)\s*(米|m)?",
                normalized,
            )
            if square_match is not None and any(
                word in normalized for word in ("正方形", "方形", "square")
            ) and explicit_motion and not design_request:
                side = float(square_match.group(1))
                if not 0.1 <= side <= 3.0:
                    return self._result(
                        "Chat 移动演示的正方形边长必须在 0.1 到 3 米之间。",
                        self._empty_usage(),
                    )
                # Chat mode is explicitly an open-loop demonstration. Keep
                # each action within the normal tool limits and require the
                # same confirmation path as every other motion command.
                forward_seconds = round(side / 0.1, 3)
                turn_seconds = round(math.pi / 2 / 0.4, 3)
                steps = []
                for _ in range(4):
                    steps.extend([
                        {
                            "linear": 0.1,
                            "angular": 0.0,
                            "duration_seconds": forward_seconds,
                        },
                        {
                            "linear": 0.0,
                            "angular": 0.4,
                            "duration_seconds": turn_seconds,
                        },
                    ])
                return self._result(
                    f"已生成基础模式正方形运动演示，共 {len(steps)} 段，边长约 {side:g} 米。"
                    "喷墨保持关闭；这是低速开环演示，不保证边长和 90 度角精度，"
                    "请检查周围环境后确认执行。",
                    self._empty_usage(),
                    self._register_pending("drive_sequence", {"steps": steps}),
                )
            rectangle_match = re.search(
                r"(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*(?:米|m)?",
                normalized,
            )
            if rectangle_match is not None and any(
                word in normalized
                for word in ("矩形", "长方形", "正方形", "rectangle", "square")
            ) and explicit_motion and not design_request:
                width = float(rectangle_match.group(1))
                height = float(rectangle_match.group(2))
                if not 0.1 <= width <= 3.0 or not 0.1 <= height <= 3.0:
                    return self._result(
                        "基础模式方形运动演示的边长必须在 0.1 到 3 米之间。",
                        self._empty_usage(),
                    )
                steps = drawing_template_motion_steps({
                    "template": "room",
                    "width_m": width,
                    "height_m": height,
                })
                return self._result(
                    f"已生成基础模式 {width:g}×{height:g} 米方形运动演示，共 {len(steps)} 段。"
                    "喷墨保持关闭；这是低速开环演示，不保证尺寸和转角精度，请检查周围环境后确认执行。",
                    self._empty_usage(),
                    self._register_pending("drive_sequence", {"steps": steps}),
                )
        if not allow_design:
            return None

        if not any(word in normalized for word in ("矩形", "长方形", "rectangle")):
            if not any(word in normalized for word in ("圆形", "圆", "circle")):
                return None
        circle_match = re.search(r"(?:半径|radius)\s*(\d+(?:\.\d+)?)", normalized)
        if circle_match is None and any(word in normalized for word in ("圆形", "圆", "circle")):
            numbers = re.findall(r"\d+(?:\.\d+)?", normalized)
            circle_match = re.match(r"(.*)", numbers[0]) if numbers else None
        if any(word in normalized for word in ("圆形", "圆", "circle")) and circle_match:
            radius = float(circle_match.group(1))
            if not (0.1 <= radius <= 5000):
                return self._result(
                    "圆的半径必须在 0.1 到 5000 米之间。",
                    self._empty_usage(),
                )
            radius_mm = radius * 1000.0
            geometries = [{
                "id": 1,
                "type": "polyline",
                "layer_id": 1,
                "vertices": [
                    {"x": radius_mm * math.cos(2 * math.pi * index / 32),
                     "y": radius_mm * math.sin(2 * math.pi * index / 32), "z": 0.0}
                    for index in range(32)
                ],
                "closed": True,
            }]
            project = get_creative_project_store().create(
                f"半径{radius:g}米圆绘制",
                message,
                {
                    "shape": "circle",
                    "dimensions": {"radius_m": radius},
                    "printer": "center",
                    "origin": "current_robot_pose",
                    "units": "m",
                },
                {},
                [],
            )
            assessment = score_design_variant(geometries)
            persisted_variant = persist_candidate_variant(
                project_id=str(project["id"]),
                name="快速圆形方案",
                geometries=geometries,
                rationale="按输入半径生成的闭合圆形喷墨路径",
                assessment=assessment,
                add_variant=get_creative_project_store().add_variant,
                get_project=get_creative_project_store().get,
                stored_preview=preview_paths({"lines": geometries}),
            )
            variant = persisted_variant.get("variant") if isinstance(persisted_variant, dict) else None
            if variant is not None:
                get_creative_project_store().select_variant(project["id"], variant["id"])
            project_scale = assessment.get("project_scale") or {}
            if project_scale.get("requires_partitioning") is True:
                partition_summary = (
                    (variant or {}).get("spatial_partition") or {}
                ).get("summary") or {}
                scale_message = (
                    f"该图纸跨度约 {project_scale.get('width_m', 0):g}×"
                    f"{project_scale.get('height_m', 0):g} 米，建议拆分为约 "
                    f"{project_scale.get('suggested_rows', 1)}×"
                    f"{project_scale.get('suggested_columns', 1)} 个施工分区。"
                    "当前已生成完整候选和预览；"
                    f"已确定性生成 {partition_summary.get('construction_zone_count', 0)} "
                    "个独立施工区，后续将按区域逐个规划和执行。"
                )
            else:
                scale_message = "下一步可提交 ROS2 规划预览，规划不会启动小车。"
            return self._result(
                f"已创建创意项目“{project['name']}”和一个候选方案。"
                + scale_message,
                self._empty_usage(),
            )
        match = re.search(r"(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)", normalized)
        if match is None:
            return None
        width = float(match.group(1))
        height = float(match.group(2))
        if not (0.1 <= width <= 5000 and 0.1 <= height <= 5000):
            return self._result(
                "矩形尺寸必须在 0.1 到 5000 米之间。", self._empty_usage()
            )
        width_mm = width * 1000.0
        height_mm = height * 1000.0
        geometries = [{
            "id": 1,
            "type": "polyline",
            "layer_id": 1,
            "vertices": [
                {"x": 0.0, "y": 0.0, "z": 0.0},
                {"x": width_mm, "y": 0.0, "z": 0.0},
                {"x": width_mm, "y": height_mm, "z": 0.0},
                {"x": 0.0, "y": height_mm, "z": 0.0},
            ],
            "closed": True,
        }]
        project = get_creative_project_store().create(
            f"{width:g}x{height:g}米矩形",
            message,
            {
                "shape": "rectangle",
                "dimensions": {"width_m": width, "height_m": height},
                "printer": "center",
                "origin": "current_robot_pose",
                "units": "m",
            },
            {},
            [],
        )
        assessment = score_design_variant(geometries)
        persisted_variant = persist_candidate_variant(
            project_id=str(project["id"]),
            name="快速矩形方案",
            geometries=geometries,
            rationale="按输入尺寸生成的闭合矩形喷墨路径",
            assessment=assessment,
            add_variant=get_creative_project_store().add_variant,
            get_project=get_creative_project_store().get,
            stored_preview=preview_paths({"lines": geometries}),
        )
        variant = persisted_variant.get("variant") if isinstance(persisted_variant, dict) else None
        if variant is not None:
            get_creative_project_store().select_variant(project["id"], variant["id"])
        project_scale = assessment.get("project_scale") or {}
        if project_scale.get("requires_partitioning") is True:
            partition_summary = (
                (variant or {}).get("spatial_partition") or {}
            ).get("summary") or {}
            scale_message = (
                f"该图纸跨度约 {project_scale.get('width_m', 0):g}×"
                f"{project_scale.get('height_m', 0):g} 米，建议拆分为约 "
                f"{project_scale.get('suggested_rows', 1)}×"
                f"{project_scale.get('suggested_columns', 1)} 个施工分区。"
                "当前已生成完整候选和预览；"
                f"已确定性生成 {partition_summary.get('construction_zone_count', 0)} "
                "个独立施工区，后续将按区域逐个规划和执行。"
            )
        else:
            scale_message = "下一步可提交 ROS2 规划预览，规划不会启动小车。"
        return self._result(
            f"已创建创意项目“{project['name']}”和一个候选方案。项目编号：{project['id']}。"
            + scale_message,
            self._empty_usage(),
        )

    @staticmethod
    def _local_spray_intent(message: str) -> tuple[bool, str] | None:
        """识别明确的喷墨开关指令，避免基础模式误触发喷墨。"""
        if not any(word in message for word in ("喷墨", "喷码", "喷头")):
            return None
        printer_name = "center"
        if "左" in message:
            printer_name = "left"
        elif "右" in message:
            printer_name = "right"
        stop_words = ("关闭", "停止", "关掉", "不要喷", "停喷", "关闭喷头")
        start_words = ("打开", "开启", "开始", "启用", "打开喷头", "边走边喷")
        if any(word in message for word in stop_words):
            return False, printer_name
        if any(word in message for word in start_words):
            return True, printer_name
        return None

    def _local_template_intent(
        self,
        *,
        raw_message: str,
        match: dict[str, Any],
        allow_design: bool,
    ) -> dict[str, Any] | None:
        """Handle drawing-editor template names without an LLM round trip."""
        label = str(match["label"])
        if not allow_design:
            steps = drawing_template_motion_steps(match)
            if len(steps) < 2:
                return self._result(
                    f"已识别{label}模板，但基础模式暂时无法将它转换为有效运动步骤。",
                    self._empty_usage(),
                )
            return self._result(
                f"基础模式已识别“{label}”模板，生成 {len(steps)} 段底盘运动演示。"
                "这是开环运动，不代表精确图纸或喷墨任务；请确认环境后执行。",
                self._empty_usage(),
                self._register_pending("drive_sequence", {"steps": steps}),
            )

        # Local-mode CAD is an adapter to the same production plan pipeline.
        return self._formal_cad_construction(
            "新建 CAD 图纸：" + raw_message,
            {"name": "drawing_design", "operation": "create"},
            mode="advanced",
        )

    def _local_turn_intent(self, normalized: str) -> dict[str, Any] | None:
        turn = re.search(r"(左转|右转)\s*(\d+(?:\.\d+)?)\s*度", normalized)
        if turn is None:
            return None
        angle_degrees = float(turn.group(2))
        if angle_degrees <= 0:
            return self._result("转向角度必须大于 0 度。", self._empty_usage())
        angular = 0.4 if turn.group(1) == "左转" else -0.4
        turn_duration = math.radians(angle_degrees) / abs(angular)
        turn_count = max(1, math.ceil(turn_duration / 30.0))
        steps = [
            {
                "linear": 0.0,
                "angular": angular,
                "duration_seconds": round(turn_duration / turn_count, 3),
            }
            for _ in range(turn_count)
        ]
        drive = re.search(r"(前进|向前|后退|向后)\s*(\d+(?:\.\d+)?)\s*(?:米|m)", normalized)
        if drive is not None:
            distance = float(drive.group(2))
            direction = 1.0 if drive.group(1) in {"前进", "向前"} else -1.0
            drive_duration = distance / 0.1
            drive_count = max(1, math.ceil(drive_duration / 30.0))
            steps.extend(
                {
                    "linear": direction * 0.1,
                    "angular": 0.0,
                    "duration_seconds": round(drive_duration / drive_count, 3),
                }
                for _ in range(drive_count)
            )
        if len(steps) == 1:
            return self._result(
                f"准备{turn.group(1)} {angle_degrees:g} 度。确认后执行，可随时停止。",
                self._empty_usage(),
                self._register_pending("drive_robot", steps[0]),
            )
        arguments = {"steps": steps}
        return self._result(
            f"准备执行 {len(steps)} 段组合运动：先{turn.group(1)} {angle_degrees:g} 度"
            + (f"，再{drive.group(1)} {float(drive.group(2)):g} 米。" if drive else "。")
            + "确认后按顺序执行，可随时停止。",
            self._empty_usage(),
            self._register_pending("drive_sequence", arguments),
        )

    def _local_circular_motion_intent(
        self, normalized: str
    ) -> dict[str, Any] | None:
        """Create a real pending action for an explicit open-loop circle request."""
        if not any(word in normalized for word in ("圆", "circle")) and not re.search(r"画.{0,30}圆", normalized) and not any(marker in normalized for marker in (
            "画圆", "绕圈", "转圈", "一圈", "圆周", "走一圈", "绕圆", "圆形运动",
        )):
            return None

        def number(pattern: str) -> float | None:
            match = re.search(pattern, normalized)
            return float(match.group(1)) if match else None

        linear = number(r"(?:线速度|速度)\s*(?:为|是|[:：])?\s*(\d+(?:\.\d+)?)\s*m/s")
        angular = number(r"角速度\s*(?:为|是|[:：])?\s*(\d+(?:\.\d+)?)\s*rad/s")
        radius = number(
            r"(?:半径|边长)\s*(?:为|是|[:：])?\s*"
            r"(\d+(?:\.\d+)?)\s*(?:米|m)?"
        )
        duration = number(r"(?:持续|运行|前进)?\s*(\d+(?:\.\d+)?)\s*秒")
        used_side_as_radius = radius is not None and "边长" in normalized and "半径" not in normalized
        if radius is not None and linear is None and angular is None:
            linear = 0.15
        if linear is None and angular is not None and radius is not None:
            linear = angular * radius
        if angular is None and linear is not None and radius is not None and radius > 0:
            angular = linear / radius
        if linear is None or angular is None or linear <= 0 or angular <= 0:
            return self._result(
                "请提供圆的半径，例如“半径 1 米”。基础模式会自动使用低速参数生成运动演示。",
                self._empty_usage(),
            )
        if radius is not None and abs(linear / angular - radius) > max(0.05, radius * 0.15):
            return self._result(
                "输入的线速度、角速度与半径不一致，请确认其中两个参数。",
                self._empty_usage(),
            )
        duration = duration or (2 * math.pi / angular)
        if not math.isfinite(duration) or duration <= 0 or duration > 120:
            return self._result(
                "单次圆周运动演示最长 120 秒，请提高角速度或缩短演示时长。",
                self._empty_usage(),
            )
        direction = -1.0 if any(word in normalized for word in ("右转", "顺时针")) else 1.0
        count = max(1, math.ceil(duration / 30.0))
        step = {
            "linear": round(linear, 3),
            "angular": round(direction * angular, 3),
            "duration_seconds": round(duration / count, 3),
        }
        name = "drive_robot" if count == 1 else "drive_sequence"
        raw_arguments = step if count == 1 else {"steps": [dict(step) for _ in range(count)]}
        arguments, error = validate_tool_arguments(name, raw_arguments)
        if arguments is None:
            return self._result(f"圆周运动参数不符合当前安全限制：{error}", self._empty_usage())
        radius_value = linear / angular
        direction_text = "顺时针" if direction < 0 else "逆时针"
        interpretation = "圆没有边长，已按半径理解；" if used_side_as_radius else ""
        return self._result(
            f"已准备圆周运动演示：{interpretation}半径 {radius_value:g} 米，线速度 "
            f"{linear:g} m/s，默认{direction_text}，预计约 {duration:.1f} 秒。"
            "本次不喷墨；基础模式为开环演示，精度不作保证。"
            "当前未接入障碍检测，请人工确认作业区域和急停装置后确认执行。",
            self._empty_usage(),
            self._register_pending(name, arguments, mode="base"),
        )

    def _local_polygonal_motion_intent(
        self, normalized: str
    ) -> dict[str, Any] | None:
        """Build a confirmed open-loop preview for a simple regular polygon."""
        if not any(
            marker in normalized
            for marker in ("等边三角形", "正三角形", "equilateral triangle")
        ):
            return None
        if any(
            marker in normalized
            for marker in ("图纸", "cad", "喷墨", "划线", "标线", "设计")
        ):
            return None
        side_match = re.search(
            r"(?:边长|side)\s*(?:为|是|[:：])?\s*"
            r"(\d+(?:\.\d+)?)\s*(?:米|m)?",
            normalized,
        )
        if side_match is None:
            return self._result(
                "请提供等边三角形的边长，例如“边长 1 米”。",
                self._empty_usage(),
            )
        side = float(side_match.group(1))
        if not 0.1 <= side <= 3.0:
            return self._result(
                "基础模式等边三角形运动演示的边长必须在 0.1 到 3 米之间。",
                self._empty_usage(),
            )
        linear_speed = 0.1
        angular_speed = 0.4
        forward_seconds = side / linear_speed
        turn_seconds = math.radians(120.0) / angular_speed
        steps: list[dict[str, float]] = []
        for _ in range(3):
            steps.extend([
                {
                    "linear": linear_speed,
                    "angular": 0.0,
                    "duration_seconds": round(forward_seconds, 3),
                },
                {
                    "linear": 0.0,
                    "angular": angular_speed,
                    "duration_seconds": round(turn_seconds, 3),
                },
            ])
        arguments, error = validate_tool_arguments(
            "drive_sequence", {"steps": steps}
        )
        if arguments is None:
            return self._result(
                f"三角形运动参数不符合当前安全限制：{error}",
                self._empty_usage(),
            )
        return self._result(
            f"已生成边长约 {side:g} 米的等边三角形运动路径预览，共 {len(steps)} 段。"
            f"小车将以 {linear_speed:g} m/s 低速行驶，喷墨保持关闭。"
            "基础模式使用里程计和定时转向，边长、120 度转角及最终闭合位置会有累计误差，"
            "仅适合运动演示，不适合作为施工精度结果。请检查周围环境和急停装置后确认执行。",
            self._empty_usage(),
            self._register_pending("drive_sequence", arguments, mode="base"),
        )

    def _discarded_mojibake_drive_intent(self, normalized: str) -> dict[str, Any] | None:
        directions = {
            "前进": 1.0,
            "向前": 1.0,
            "后退": -1.0,
            "向后": -1.0,
        }
        direction = next(
            (sign for keyword, sign in directions.items() if keyword in normalized),
            None,
        )
        if direction is None:
            return None
        match = re.search(r"(\d+(?:\.\d+)?)\s*(米|m)\b?", normalized)
        if match is None:
            return None
        distance = float(match.group(1))
        speed = 0.1
        duration = distance / speed
        if distance <= 0 or duration > 30.0:
            return self._result(
                "单次 AI 直线运动最多 3 米（安全上限 0.1 m/s、30 秒），请缩短距离或分段执行。",
                self._empty_usage(),
            )
        arguments = {
            "linear": round(direction * speed, 3),
            "angular": 0.0,
            "duration_seconds": round(duration, 3),
        }
        direction_label = "前进" if direction > 0 else "后退"
        return self._result(
            f"准备以 {speed:g} m/s {direction_label} {distance:g} 米，预计持续 {duration:g} 秒。确认后才会执行，可随时停止。",
            self._empty_usage(),
            self._register_pending("drive_robot", arguments),
        )

    def _local_motion_sequence_intent(
        self, normalized: str
    ) -> dict[str, Any] | None:
        """Preserve every ordered movement phrase in a base-mode request."""
        pattern = re.compile(
            r"(?P<drive>前进|向前|后退|向后)\s*(?P<distance>\d+(?:\.\d+)?)\s*(?:米|m)"
            r"|(?P<turn>左转|右转)\s*(?P<angle>\d+(?:\.\d+)?)\s*度"
        )
        matches = list(pattern.finditer(normalized))
        if len(matches) < 2:
            return None
        steps: list[dict[str, float]] = []
        labels: list[str] = []
        for match in matches:
            if match.group("drive"):
                distance = float(match.group("distance"))
                if distance <= 0:
                    return self._result("运动距离必须大于 0 米。", self._empty_usage())
                direction = 1.0 if match.group("drive") in {"前进", "向前"} else -1.0
                duration = distance / 0.1
                count = max(1, math.ceil(duration / 30.0))
                steps.extend({
                    "linear": round(direction * 0.1, 3),
                    "angular": 0.0,
                    "duration_seconds": round(duration / count, 3),
                } for _ in range(count))
                labels.append(f"{match.group('drive')}{distance:g}米")
            else:
                angle = float(match.group("angle"))
                if angle <= 0:
                    return self._result("转向角度必须大于 0 度。", self._empty_usage())
                angular = 0.4 if match.group("turn") == "左转" else -0.4
                duration = math.radians(angle) / abs(angular)
                count = max(1, math.ceil(duration / 30.0))
                steps.extend({
                    "linear": 0.0,
                    "angular": angular,
                    "duration_seconds": round(duration / count, 3),
                } for _ in range(count))
                labels.append(f"{match.group('turn')}{angle:g}度")
        if not steps:
            return None
        return self._result(
            f"准备按顺序执行 {len(steps)} 段组合运动：{'，'.join(labels)}。"
            "已完整保留用户输入的运动步骤；确认后执行，可随时停止。",
            self._empty_usage(),
            self._register_pending("drive_sequence", {"steps": steps}),
        )

    def _local_drive_intent(self, normalized: str) -> dict[str, Any] | None:
        directions = {
            "\u524d\u8fdb": 1.0,
            "\u5411\u524d": 1.0,
            "\u540e\u9000": -1.0,
            "\u5411\u540e": -1.0,
        }
        direction = next(
            (sign for keyword, sign in directions.items() if keyword in normalized),
            None,
        )
        if direction is None:
            return None
        match = re.search(r"(\d+(?:\.\d+)?)\s*(\u7c73|m)", normalized)
        if match is None:
            return None
        distance = float(match.group(1))
        speed = 0.1
        duration = distance / speed
        if distance <= 0:
            return self._result(
                "\u8fd0\u52a8\u8ddd\u79bb\u5fc5\u987b\u5927\u4e8e 0 \u7c73\u3002",
                self._empty_usage(),
            )
        step_count = max(1, math.ceil(duration / 30.0))
        step_duration = duration / step_count
        step = {
            "linear": round(direction * speed, 3),
            "angular": 0.0,
            "duration_seconds": round(step_duration, 3),
        }
        direction_label = "\u524d\u8fdb" if direction > 0 else "\u540e\u9000"
        if step_count > 1:
            arguments = {"steps": [dict(step) for _ in range(step_count)]}
            return self._result(
                f"\u51c6\u5907\u4ee5 {speed:g} m/s {direction_label} {distance:g} \u7c73\uff0c"
                f"\u5c06\u81ea\u52a8\u62c6\u5206\u4e3a {step_count} \u6bb5\uff0c\u603b\u8ba1\u7ea6 {duration:g} \u79d2\u3002"
                "\u786e\u8ba4\u540e\u6309\u987a\u5e8f\u6267\u884c\uff0c\u53ef\u968f\u65f6\u505c\u6b62\u3002",
                self._empty_usage(),
                self._register_pending("drive_sequence", arguments),
            )
        arguments = step
        return self._result(
            f"\u51c6\u5907\u4ee5 {speed:g} m/s {direction_label} {distance:g} \u7c73\uff0c\u9884\u8ba1\u6301\u7eed {duration:g} \u79d2\u3002\u786e\u8ba4\u540e\u624d\u4f1a\u6267\u884c\uff0c\u53ef\u968f\u65f6\u505c\u6b62\u3002",
            self._empty_usage(),
            self._register_pending("drive_robot", arguments),
        )

    def confirm(
        self, action_id: str, approved: bool, client_id: str | None = None
    ) -> dict[str, Any]:
        result = self._confirm_impl(action_id, approved, client_id)
        return agent_plan_runtime.complete_pending_action(
            action_id,
            approved=approved,
            result=result,
        )

    def _confirm_impl(
        self, action_id: str, approved: bool, client_id: str | None = None
    ) -> dict[str, Any]:
        pending_lock = getattr(self, "_pending_lock", None)
        if pending_lock is None:
            pending_lock = self._pending_lock = threading.RLock()
        with pending_lock:
            action = self.pending.pop(action_id, None)
            if (
                action is not None
                and action.owner_id != "local-default"
                and action.owner_id != str(client_id or "")
            ):
                self.pending[action_id] = action
                return {"ok": False, "message": "无权确认其他用户的操作。"}
        if action is None or action.expires_at < datetime.now():
            existing = agent_tasks.get(action_id)
            if existing and existing.get("state") in {
                "completed", "failed", "cancelled", "awaiting_verification", "interrupted",
            }:
                stored_result = existing.get("result")
                if isinstance(stored_result, dict):
                    return {
                        **stored_result,
                        "task_id": action_id,
                        "task_state": existing["state"],
                        "idempotent_replay": True,
                    }
                state = str(existing["state"])
                labels = {
                    "cancelled": "该操作已取消，不会执行。",
                    "failed": "该操作此前已失败，不会重复执行。",
                    "interrupted": "该操作已中断，不会自动重试。",
                    "awaiting_verification": "该操作仍在等待真实状态验证。",
                    "completed": "该操作已经完成，不会重复执行。",
                }
                return {
                    "ok": state in {"completed", "awaiting_verification"},
                    "message": labels.get(state, "该操作已结束，不会重复执行。"),
                    "task_id": action_id,
                    "task_state": state,
                    "idempotent_replay": True,
                }
            if existing and existing.get("state") in {"executing", "verifying"}:
                return {
                    "ok": True,
                    "message": "该操作正在执行或等待真实状态验证，请稍后查询任务状态。",
                    "task_id": action_id,
                    "task_state": existing["state"],
                    "idempotent_replay": True,
                    "in_progress": True,
                }
            agent_tasks.transition(action_id, "expired", "确认已过期")
            return {"ok": False, "message": "操作已失效，请重新向助手发出指令。"}
        if not approved:
            agent_tasks.transition(action_id, "cancelled", "用户取消操作")
            return {"ok": True, "message": "已取消操作。"}
        policy = agent_tool_policy(action.name, action.mode)
        if not policy["allowed"]:
            message = policy["reason"]
            failure = {"ok": False, "message": message, "policy": policy}
            agent_tasks.transition(action_id, "failed", message, failure)
            return {
                **failure,
                "task_id": action_id,
                "task_state": "failed",
                "agent_mode": action.mode,
            }
        preflight = build_action_preflight(action.name, action.arguments)
        if not preflight["ready"]:
            failed_checks = [
                item for item in preflight["checks"] if not item["ok"]
            ]
            message = "执行前检查未通过：" + "；".join(
                str(item["detail"]) for item in failed_checks
            )
            retryable_codes = {
                "control_owner",
                "ros_available",
                "emergency_stop",
                "control_ready",
                "localization",
                "mission_nodes",
                "printer",
                "ln150",
            }
            failure_codes = {
                str(item.get("code") or "") for item in failed_checks
            }
            retryable = bool(failure_codes) and failure_codes <= retryable_codes
            retry_pending = None
            if retryable:
                retry_pending = self._register_pending(
                    action.name, action.arguments, mode=action.mode
                )
                # The checklist is a snapshot from this failed attempt. Keep it
                # visible, but allow the user to trigger a fresh server-side
                # preflight after correcting the device state.
                retry_pending["retryable_preflight"] = True
                retry_pending["retry_of"] = action_id
                retry_pending["retry_reason_codes"] = sorted(failure_codes)
                message += (
                    "。动作已保留；处理上述状态并确认现场安全后，"
                    "请再次点击“确认执行”，系统会重新检查实时状态。"
                )
            failure = {
                "ok": False,
                "message": message,
                "preflight": preflight,
                "retryable": retryable,
                "retry_reason_codes": sorted(failure_codes),
                "pending_action": retry_pending,
                "agent_mode": action.mode,
            }
            agent_tasks.transition(action_id, "failed", message, failure)
            return {**failure, "task_id": action_id, "task_state": "failed"}
        before_snapshot = robot_state.snapshot()
        agent_tasks.transition(action_id, "executing", "用户已确认，开始执行")
        try:
            result = self._execute_confirmed(action, client_id=client_id)
        except Exception as error:
            failure = {"ok": False, "message": f"Agent 工具执行异常：{error}"}
            agent_tasks.transition(action_id, "failed", failure["message"], failure)
            robot_state.add_log(f"agent task {action_id} failed: {error}")
            return failure
        result = dict(result)
        result["agent_mode"] = action.mode
        agent_tasks.transition(action_id, "verifying", "工具已返回，读取真实设备状态进行验证")
        result["verification"] = self._validate_tool_result(
            action.name, action.arguments, result, before_snapshot
        )
        result.setdefault("tool_results", [self._tool_result_summary(action.name, result)])
        if result.get("ok") is not True:
            final_state = "failed"
        elif result["verification"]["status"] == "success":
            final_state = "completed"
        elif result["verification"]["status"] == "cancelled":
            final_state = "cancelled"
            result["message"] = str(
                result["verification"].get("message") or "已按你的要求停止小车运动。"
            )
        elif result["verification"]["status"] == "failed":
            final_state = "failed"
        else:
            final_state = "awaiting_verification"
            result["message"] = (
                str(result.get("message") or "工具已返回")
                + " 但暂未收到足够的真实遥测证据，请在监控页确认设备状态。"
            )
        agent_tasks.transition(action_id, final_state, str(result.get("message", "")), result)
        return {**result, "task_id": action_id, "task_state": final_state}

    def reconcile_verification_tasks(self) -> dict[str, Any]:
        """Re-check deferred hardware results when fresh telemetry is polled."""
        completed = 0
        failed = 0
        now = datetime.now(timezone.utc)
        for task in agent_tasks.by_state("awaiting_verification"):
            task_id = str(task.get("id") or "")
            name = str(task.get("tool") or "")
            arguments = task.get("arguments")
            stored = task.get("result")
            if not task_id or not isinstance(arguments, dict) or not isinstance(stored, dict):
                continue
            previous = stored.get("verification")
            previous_observed = (
                previous.get("observed") if isinstance(previous, dict) else {}
            )
            verification = self._validate_tool_result(
                name, arguments, stored,
                previous_observed if isinstance(previous_observed, dict) else {},
            )
            updated = dict(stored)
            updated["verification"] = verification
            if verification["status"] == "cancelled":
                message = str(
                    verification.get("message") or "已按你的要求停止小车运动。"
                )
                updated["message"] = message
                agent_tasks.transition(task_id, "cancelled", message, updated)
                continue
            if verification["verified"]:
                message = str(updated.get("message") or "工具状态已通过遥测确认")
                agent_tasks.transition(task_id, "completed", message, updated)
                completed += 1
                continue
            if verification["status"] == "failed":
                message = str(
                    verification.get("message") or "真实设备状态表明工具执行失败"
                )
                updated["message"] = message
                agent_tasks.transition(task_id, "failed", message, updated)
                failed += 1
                continue
            try:
                updated_at = datetime.fromisoformat(str(task["updated_at"]))
                if updated_at.tzinfo is None:
                    updated_at = updated_at.replace(tzinfo=timezone.utc)
                age = (now - updated_at).total_seconds()
            except (KeyError, TypeError, ValueError):
                age = 999
            estimated_duration = stored.get("estimated_duration_seconds")
            verification_timeout = (
                max(15.0, float(estimated_duration) + 15.0)
                if isinstance(estimated_duration, (int, float))
                else 15.0
            )
            if name in {"set_mission", "execute_prepared_mission"}:
                observed = verification.get("observed")
                observed = observed if isinstance(observed, dict) else {}
                observed_stage = str(observed.get("mission_stage") or "")
                observed_running = observed.get("mission_running") is True
                if observed_running or observed_stage in {
                    "planning", "executing", "paused"
                }:
                    # Construction duration is governed by mission progress,
                    # not the short acknowledgement timeout used by commands.
                    continue
            if age >= verification_timeout:
                expected = verification.get("expected") or "目标设备状态发生变化"
                message = (
                    f"实时遥测在 {verification_timeout:g} 秒内未证明工具执行成功；"
                    f"期望：{expected}"
                )
                verification.update({
                    "status": "failed",
                    "level": "timeout",
                    "reason_code": "verification_timeout",
                    "retryable": True,
                    "message": message,
                })
                updated["verification"] = verification
                updated["message"] = message
                agent_tasks.transition(task_id, "failed", message, updated)
                failed += 1
        return {"completed": completed, "failed": failed}

    def live_fault_evaluation(self) -> dict[str, Any]:
        return evaluate_live_vehicle(robot_state.snapshot())

    def request_confirmation(
        self, name: str, arguments: dict[str, Any], *, mode: str = "advanced"
    ) -> dict[str, Any]:
        policy = agent_tool_policy(name, mode)
        if not policy["allowed"]:
            return {
                "ok": False,
                "message": policy["reason"],
                "pending_action": None,
                "policy": policy,
            }
        validated, error = validate_tool_arguments(name, arguments)
        if validated is None:
            return {"ok": False, "message": error, "pending_action": None}
        return {
            "ok": True,
            "message": self._confirmation_text(name, validated),
            "pending_action": self._register_pending(name, validated, mode=mode),
        }

    def _request(
        self,
        input_items: list[dict[str, Any]],
        instructions: str,
        *,
        mode: str = "base",
    ) -> dict[str, Any]:
        tools = [
            tool for tool in TOOLS
            if agent_tool_allowed(str(tool.get("name") or ""), mode)
            and str(tool.get("name") or "") not in MODEL_HIDDEN_TOOLS
        ]
        payload = {
            "model": self.model,
            "instructions": instructions,
            "input": input_items,
            "tools": tools,
            "tool_choice": "auto",
            "max_output_tokens": int(os.getenv("OPENAI_MAX_OUTPUT_TOKENS", "600")),
            "store": False,
        }
        return request_openai_responses_json(
            api_key=self.api_key,
            payload=payload,
            timeout=self._env_timeout(
                "XLINE_AGENT_MODEL_REQUEST_TIMEOUT_SECONDS",
                45.0,
                maximum=900.0,
            ),
        )

    def _local_diagnosis(self) -> str:
        snapshot = robot_state.snapshot()
        missing = ", ".join(robot_state.missing_required_nodes) or "无"
        links = build_link_diagnosis(snapshot)
        live_context = self.runtime_context(self.route_intent("诊断小车当前状态"))
        blocked_domains = live_context["quality"]["blocked_domains"]
        lines = [
            "本地诊断结果：",
            f"- ROS2：{'可用' if robot_state.ros_available else '不可用'}",
            f"- 底盘控制：{'就绪' if robot_state.control_ready else '未就绪'}",
            f"- 定位：{'已收到 /robot_pose' if robot_state.robot_pose else '无 /robot_pose 数据'}",
            f"- 任务阶段：{robot_state.mission_stage}",
            f"- 缺少节点：{missing}",
            f"- 链路断点：{links['breakpoint'] or '无'}",
            f"- 可继续使用：{'、'.join(links['usable_features']) or '无'}",
            f"- 是否允许重试：{'是' if links['retry_allowed'] else '否'}",
            f"- 是否需要人工处理：{'是' if links['requires_human_action'] else '否'}",
        ]
        if blocked_domains:
            domain_labels = {
                "runtime": "运行连接", "motion": "底盘运动", "localization": "定位",
                "energy": "能源", "printer": "喷码机", "obstacles": "障碍物",
                "mission": "任务",
            }
            lines.append(
                "- 实时性门禁：以下数据缺失或已过期，不能作为当前事实："
                + "、".join(domain_labels.get(item, item) for item in blocked_domains)
            )
        if not robot_state.drive_device_connected:
            target = robot_state.drive_device_path or robot_state.drive_transport
            lines.append(f"- 建议：检查 CAN 通信接口 {target}、供电和总线连接。")
        if not robot_state.robot_pose:
            lines.append(
                "- 建议：检查当前定位节点、/robot_pose 与 /localization/valid；"
                "全站仪模式另需检查 LN150 和 /reflector_position。"
            )
        lines.append("本地模式只提供状态诊断，不执行自然语言工具调用。")
        return "\n".join(lines)

    @staticmethod
    def _requests_live_localization(message: str) -> bool:
        return bool(re.search(
            r"定位|全站仪|ln150|(?:小车|机器人|设备).{0,8}(?:坐标|位置)|"
            r"(?:当前|实时)(?:坐标|位置)|(?:坐标|位置).{0,5}(?:状态|有效|准确)", message.lower()
        ))

    @staticmethod
    def route_intent(message: str, mode: str = "base") -> dict[str, Any]:
        """Classify the workflow family without authorizing an operation."""
        text = message.strip().lower()
        normalized_mode = RobotAgentService.normalize_agent_mode(mode)
        if (
            normalized_mode == "advanced"
            and RobotAgentService._is_design_generation_confirmation(message)
        ):
            return {
                "schema_version": "1.1",
                "name": "drawing_design",
                "tool_family": "cad",
                "mode": normalized_mode,
                "confidence": 0.99,
                "operation": "create",
                "stage": "candidate_generation",
                "next_step": "生成候选方案并展示二维路径预览",
                "api_required": False,
                "safety_confirmation_required": False,
                "context_requirements": [],
                "requested_data_domains": [],
                "decision_source": "deterministic_design_confirmation",
                "review_required": False,
            }
        readiness_check = any(
            phrase in text
            for phrase in (
                "检查小车是否可以开始任务",
                "检查小车能否开始任务",
                "能否开始任务",
                "是否可以开始任务",
                "是否能开始任务",
                "开始任务前检查",
                "执行前检查",
                "任务准备检查",
                "任务是否可以开始",
            )
        )
        action_words = (
            "执行", "开始", "启动", "暂停", "恢复", "继续", "取消", "停止", "终止",
            "打开", "关闭", "初始化", "追踪", "调平",
        )
        mission_action = any(word in text for word in action_words) and any(
            word in text for word in ("任务", "规划", "划线")
        )
        printer_domain = any(word in text for word in ("喷墨", "喷码", "喷头", "墨量"))
        printer_action = printer_domain and any(word in text for word in action_words)
        localization_domain = any(word in text for word in ("ln150", "全站仪"))
        localization_action = localization_domain and any(
            word in text for word in action_words
        )
        explicit_status_query = any(word in text for word in (
            "状态", "当前", "查询", "查看", "是否连接", "电量", "电压", "电流",
            "温度", "速度", "定位", "墨量",
        ))
        drawing_capacity_query = (
            any(word in text for word in ("平方米", "平米", "面积", "场地", "土地"))
            and any(word in text for word in ("画", "容纳", "放下", "布置", "几个", "多少个"))
        )
        cad_object_edit = (
            normalized_mode == "advanced"
            and any(word in text for word in (
                "图形", "图纸", "场地", "实例", "对象", "外框", "边框",
                "中线", "中心线", "中心圆", "图层", "线段", "图元",
            ))
            and any(word in text for word in (
                "修改", "编辑", "调整", "移动", "平移", "偏移", "挪动",
                "旋转", "转动", "缩放", "扩大", "放大", "缩小", "复制",
                "拷贝", "对齐", "齐平", "删除", "移除", "只保留", "改宽",
                "改高", "宽度", "高度", "半径",
            ))
        )
        if readiness_check or any(
            word in text for word in ("故障", "异常", "报警", "烧坏", "诊断", "为什么")
        ):
            intent, confidence = "diagnosis", 0.94
        elif mission_action:
            intent, confidence = "mission_control", 0.94
        elif any(word in text for word in (
            "绕圈", "转圈", "走一圈", "绕圆", "圆周运动", "圆形运动",
        )) and not any(word in text for word in ("图纸", "设计", "画图", "喷墨")):
            intent, confidence = "motion_control", 0.95
        elif drawing_capacity_query or cad_object_edit or any(
            word in text
            for word in (
                "优化", "方案", "图纸", "图形", "线段", "边界", "cad", "标线",
                "设计", "扩大", "放大", "缩小", "矩形", "长方形", "正方形",
                "篮球场", "羽毛球场", "停车位", "车位", "椭圆", "圆形",
            )
        ):
            intent, confidence = "drawing_design", 0.9
        elif printer_action:
            intent, confidence = "printer_control", 0.95
        elif localization_action:
            intent, confidence = "localization_control", 0.95
        elif explicit_status_query or printer_domain or localization_domain:
            intent, confidence = "status_query", 0.91
        elif any(word in text for word in ("停止", "急停", "停车")):
            intent, confidence = "stop", 0.99
        elif any(word in text for word in ("执行", "开始任务", "启动任务", "暂停任务", "恢复任务")):
            intent, confidence = "mission_control", 0.9
        elif any(word in text for word in ("前进", "后退", "左转", "右转", "移动", "走", "速度")):
            intent, confidence = "motion_control", 0.92
        else:
            intent, confidence = "conversation", 0.6
        operation = "query"
        stage = "conversation"
        next_step = "回答用户问题"
        if intent == "drawing_design":
            if any(word in text for word in (
                "修改", "编辑", "调整", "优化已有", "导入", "改成",
                "增加", "添加", "删除", "缩短", "延长", "移动", "旋转",
                "减少", "扩大", "放大", "缩小", "平移", "偏移", "挪动",
                "转动", "缩放", "复制", "拷贝", "对齐", "齐平", "移除",
                "只保留", "改宽", "改高",
            )):
                operation = "modify"
            elif drawing_capacity_query or any(
                word in text for word in ("检查", "验证", "能不能", "是否可行")
            ):
                operation = "inspect"
            elif any(word in text for word in ("对比", "差异", "比较")):
                operation = "compare"
            elif any(word in text for word in ("导出", "输出", "保存文件")):
                operation = "export"
            else:
                operation = "create"
            stage = "requirements"
            next_step = "提取图形、尺寸和约束，只追问一个最关键的缺失参数"
        elif intent == "diagnosis":
            operation, stage, next_step = "diagnose", "observation", "读取实时状态并给出证据"
        elif intent == "status_query":
            operation, stage, next_step = "inspect", "observation", "读取实时遥测"
        elif intent in {
            "motion_control", "printer_control", "mission_control", "localization_control"
        }:
            operation, stage, next_step = "execute", "confirmation", "执行前检查并等待用户确认"
        elif intent == "stop":
            operation, stage, next_step = "stop", "execution", "立即停车并验证运动状态"
        tool_family = {
            "diagnosis": "telemetry",
            "status_query": "telemetry",
            "motion_control": "motion",
            "stop": "safety_stop",
            "mission_control": "mission",
            "printer_control": "printer",
            "localization_control": "localization",
            "drawing_design": "cad",
            "conversation": "conversation",
        }[intent]
        context_requirements = {
            "telemetry": ["online", "telemetry_age_ms"],
            "motion": ["online", "control_ready", "emergency_stopped"],
            "safety_stop": ["agent_motion_active", "emergency_stopped"],
            "mission": ["mission_stage", "localization_valid", "control_ready"],
            "printer": ["printer_status", "printer_ready"],
            "localization": ["localization_valid", "localization_source", "ln150_ready"],
            "cad": ["mission_stage"],
            "conversation": ["online"],
        }[tool_family]
        requested_data_domains: list[str] = []
        domain_words = {
            "energy": ("电量", "电池", "电压", "电流", "温度", "能源"),
            "localization": ("定位", "位置", "坐标", "全站仪", "ln150"),
            "motion": ("速度", "轮速", "底盘", "里程", "运动"),
            "printer": ("喷墨", "喷码", "喷头", "墨量"),
            "obstacles": ("障碍", "避障", "距离传感器"),
            "mission": ("任务", "执行阶段", "进度", "划线"),
            "runtime": ("连接", "在线", "ros", "后端", "控制就绪"),
        }
        for domain, words in domain_words.items():
            if domain == "localization" and tool_family == "cad":
                # Drawing coordinates describe geometry, not live robot pose.
                # Keep explicit localization/status requests subject to the
                # existing freshness gate; do not suppress answer validation.
                explicit_live_pose = RobotAgentService._requests_live_localization(text)
                if not explicit_live_pose:
                    continue
            if any(word in text for word in words):
                requested_data_domains.append(domain)
        if intent == "diagnosis" and not requested_data_domains:
            requested_data_domains = [
                "runtime", "motion", "localization", "energy", "printer"
            ]
        elif intent == "status_query" and not requested_data_domains:
            requested_data_domains = ["runtime"]
        if tool_family == "telemetry":
            freshness_fields = {
                "energy": "energy_age_ms",
                "localization": "telemetry_age_ms",
                "motion": "telemetry_age_ms",
                "printer": "printer_status_age_ms",
                "obstacles": "obstacle_age_ms",
                "mission": "online",
                "runtime": "online",
            }
            context_requirements = list(dict.fromkeys(
                freshness_fields[domain]
                for domain in requested_data_domains
                if domain in freshness_fields
            ))
        return {
            "schema_version": "1.1",
            "name": intent,
            "tool_family": tool_family,
            "mode": normalized_mode,
            "confidence": confidence,
            "operation": operation,
            "stage": stage,
            "next_step": next_step,
            "api_required": intent in {"diagnosis", "drawing_design", "conversation"},
            "safety_confirmation_required": intent in {
                "motion_control", "printer_control", "mission_control", "localization_control"
            },
            "context_requirements": context_requirements,
            "requested_data_domains": requested_data_domains,
        }

    @staticmethod
    def _intent_signals(message: str) -> set[str]:
        text = message.strip().lower()
        signals: set[str] = set()
        groups = {
            "diagnosis": ("故障", "异常", "报警", "烧坏", "诊断", "为什么"),
            "cad": ("图纸", "cad", "设计", "方案", "标线", "几何", "图层"),
            "printer": ("喷墨", "喷码", "喷头", "墨量"),
            "mission": ("任务", "规划", "划线", "执行阶段"),
            "localization": ("ln150", "全站仪", "调平", "追踪"),
            "motion": ("前进", "后退", "左转", "右转", "移动", "底盘", "速度", "绕圈", "转圈", "圆周运动"),
            "telemetry": ("状态", "电量", "电压", "电流", "温度", "连接", "定位"),
        }
        for family, words in groups.items():
            if any(word in text for word in words):
                signals.add(family)
        if RobotAgentService._contains_stop_command(text):
            signals.add("safety_stop")
        return signals

    @staticmethod
    def _contains_stop_command(message: str) -> bool:
        """Recognize stop commands without treating parking nouns as commands."""
        text = message.strip().lower()
        if any(word in text for word in ("急停", "停下", "立即停", "马上停")):
            return True
        return re.search(r"停车(?!位|场|区|库|线)", text) is not None

    @staticmethod
    def _route_needs_model_review(message: str, route: dict[str, Any]) -> bool:
        text = message.strip().lower()
        signals = RobotAgentService._intent_signals(text)
        if (
            route.get("name") == "drawing_design"
            and route.get("operation") == "create"
            and not RobotAgentService._physical_action_signals(text)
            and any(word in text for word in (
                "矩形", "长方形", "正方形", "篮球场", "羽毛球场", "停车位", "车位",
            ))
            and len(text) <= 80
        ):
            return False
        if float(route.get("confidence") or 0) < 0.8:
            return True
        if len(signals) > 1:
            return True
        if any(word in text for word in (
            "它", "这个", "那个", "刚才", "上一个", "继续", "照做", "按这个",
        )):
            return True
        return len(text) > 80 or any(
            word in text for word in ("同时", "并且", "然后", "如果", "但是", "还是")
        )

    @staticmethod
    def _physical_action_signals(message: str) -> set[str]:
        text = message.strip().lower()
        readiness = any(phrase in text for phrase in (
            "能否开始任务", "是否可以开始任务", "是否能开始任务",
            "任务准备检查", "执行前检查", "开始任务前检查",
        ))
        signals: set[str] = set()
        if RobotAgentService._contains_stop_command(text):
            signals.add("stop")
        if any(word in text for word in ("前进", "后退", "左转", "右转", "移动", "让它走", "绕圈", "转圈", "圆周运动")):
            signals.add("motion_control")
        action_words = ("执行", "启动", "暂停", "恢复", "继续", "取消", "终止", "打开", "关闭", "初始化", "追踪", "调平")
        if not readiness and any(word in text for word in ("任务", "规划", "划线")) and any(
            word in text for word in action_words
        ):
            signals.add("mission_control")
        if any(word in text for word in ("喷墨", "喷码", "喷头")) and any(
            word in text for word in action_words
        ):
            signals.add("printer_control")
        if any(word in text for word in ("ln150", "全站仪")) and any(
            word in text for word in action_words
        ):
            signals.add("localization_control")
        return signals

    @staticmethod
    def _json_object(text: str) -> dict[str, Any] | None:
        raw = text.strip()
        if raw.startswith("```"):
            raw = re.sub(
                r"^```(?:json)?\s*|\s*```$", "", raw,
                flags=re.IGNORECASE | re.DOTALL,
            ).strip()
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            value = json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None

    def resolve_intent(
        self,
        message: str,
        mode: str = "base",
        history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Use rules first and review only ambiguous routes with structured AI output."""
        route = dict(self.route_intent(message, mode))
        route["decision_source"] = "rules"
        constrained = self._constrained_addition_followup_route(
            message, mode, history
        )
        if constrained is not None:
            return constrained
        edit_chain = (
            parse_incremental_edit_chain(message)
            if self.normalize_agent_mode(mode) == "advanced" else None
        )
        if edit_chain is not None:
            route.update({
                "name": "drawing_design", "tool_family": "cad", "operation": "modify",
                "decision_source": "incremental_cad_edit_chain",
                "review_required": False, "clarification_required": False,
                "safety_confirmation_required": False,
                "edit_chain": edit_chain,
            })
            return route
        creation_markers = (
            "规划", "生成", "绘制", "绘画", "创建", "新建", "画出", "画一个", "设计"
        )
        has_creation_request = any(
            marker in message.strip().lower() for marker in creation_markers
        ) or bool(local_creation_objects(message))
        # Generic CAD nouns must be classified before the model-review route.
        # Otherwise colloquial requests such as “绘画一个爱心” (where neither
        # “图纸” nor a registered template is mentioned) become conversation
        # and receive the unrelated “请明确最先操作” question.
        generic_shape_words = (
            "爱心", "心形", "轮廓", "曲线", "闭合", "贝塞尔", "bezier",
            "样条", "圆弧", "椭圆", "多边形", "折线", "线段", "图形",
        )
        dimensioned_drawing_request = bool(
            local_creation_objects(message)
            and re.match(r"^(?:请|帮我|请帮我|给我|麻烦)?\s*(?:绘制|画出|画|设计)", message.strip())
            and re.search(r"\d+(?:\.\d+)?\s*(?:毫米|厘米|米|mm|cm|m)(?![A-Za-z])", message, re.I)
            and re.search(r"宽|高|长|半径|直径|角|连接|对称", message)
        )
        if (
            self.normalize_agent_mode(mode) == "advanced"
            and has_creation_request
            and (any(word in message.strip().lower() for word in generic_shape_words)
                 or dimensioned_drawing_request)
        ):
            route.update({
                "name": "drawing_design", "tool_family": "cad",
                "operation": "create", "stage": "requirements",
                "next_step": "澄清图形、尺寸和曲线约束后生成 CAD 候选",
                "decision_source": "deterministic_generic_cad_creation",
                "review_required": False, "clarification_required": False,
                "safety_confirmation_required": False,
            })
            return route
        incremental_edit = (
            None
            if has_creation_request
            else parse_incremental_edit(message)
            if self.normalize_agent_mode(mode) == "advanced"
            else None
        )
        if incremental_edit is not None:
            route.update({
                "name": "drawing_design", "tool_family": "cad", "operation": "modify",
                "decision_source": "incremental_cad_edit", "review_required": False,
                "clarification_required": False, "safety_confirmation_required": False,
                "edit_intent": build_cad_edit_intent(message, incremental_edit),
            })
            return route
        design_confirmation = self._design_generation_confirmation_followup_route(
            message, mode, history
        )
        if design_confirmation is not None:
            return design_confirmation
        rectangle_request = self._base_rectangular_motion_request_route(message, mode)
        if rectangle_request is not None:
            return rectangle_request
        polygon_request = self._base_polygonal_motion_request_route(message, mode)
        if polygon_request is not None:
            return polygon_request
        circle_request = self._base_circular_motion_request_route(message, mode)
        if circle_request is not None:
            return circle_request
        demo_followup = self._base_motion_demo_followup_route(message, mode, history)
        if demo_followup is not None:
            return demo_followup
        followup = self._affirmative_followup_route(message, mode, history)
        if followup is not None:
            return followup
        circle_followup = self._circular_motion_parameter_followup_route(
            message, mode, history
        )
        if circle_followup is not None:
            return circle_followup
        relative_addition = self._relative_template_addition_route(message, mode)
        if relative_addition is not None:
            return relative_addition
        layout_followup = self._drawing_layout_followup_route(message, mode, history)
        if layout_followup is not None:
            return layout_followup
        # A rule-recognized CAD modification that was not handled by the
        # deterministic parsers above is reviewed by the strict CAD
        # interpreter in chat(). Running the generic classifier first would
        # add a second serial model call without improving target grounding.
        if (
            self.normalize_agent_mode(mode) == "advanced"
            and self.mode != "local"
            and self.configured
            and route.get("name") == "drawing_design"
            and route.get("operation") == "modify"
            and not self._physical_action_signals(message)
        ):
            route["review_required"] = False
            route["review"] = {
                "attempted": False,
                "reason": "CAD 修改由严格结构化解释器复核",
            }
            return route
        route["review_required"] = self._route_needs_model_review(message, route)
        if not route["review_required"]:
            return route
        physical_signals = self._physical_action_signals(message)
        if len(physical_signals) > 1 or (
            physical_signals and route.get("name") not in physical_signals
        ):
            return {
                **route,
                "name": "conversation",
                "tool_family": "conversation",
                "operation": "query",
                "stage": "clarification",
                "next_step": "澄清查询和物理操作的优先顺序",
                "confidence": 0.0,
                "api_required": False,
                "safety_confirmation_required": False,
                "context_requirements": ["online"],
                "decision_source": "safety_clarification",
                "clarification_required": True,
                "clarification_question": "这条消息同时包含状态查询或多项控制操作。请说明本次只查询状态，还是要执行哪一项具体操作？",
                "review": {
                    "attempted": False,
                    "reason": "确定性安全规则检测到混合物理操作",
                    "physical_intents": sorted(physical_signals),
                },
            }
        if self.mode == "local" or not self.configured:
            route["decision_source"] = "rules_fallback"
            route["review"] = {
                "attempted": False,
                "reason": "本地模式或未配置时保持更保守的规则结果",
            }
            return route

        allowed_intents = (
            "conversation, diagnosis, status_query, drawing_design, motion_control, "
            "printer_control, mission_control, localization_control, stop"
        )
        recent = [
            {"role": item.get("role"), "content": item.get("content")}
            for item in (history or [])[-4:]
            if item.get("content")
        ]
        prompt = (
            "你是只负责分类的路由器，不回答用户问题，不调用工具。只输出一个 JSON 对象，字段必须为："
            "primary_intent、secondary_intents、confidence、requires_clarification、"
            "clarification_question、reason、cad_operation。primary_intent 只能是："
            f"{allowed_intents}。confidence 是 0 到 1。危险动作与查询必须区分；"
            "primary_intent=drawing_design 时 cad_operation 必须是 create、modify 或 inspect；"
            "其它意图的 cad_operation 必须为 null。"
            "按整句的主要目标分类，不把图形描述拆成设备操作。"
            "生成几何时的起点、终点、旋转圈数、方向、半径变化等是构造约束，"
            "不是 motion_control；即使图形没有本地模板也应归 drawing_design/create。"
            "例如‘生成一条线，从原点出发旋转三圈，半径逐渐增大’只有新建图形一个意图。"
            "只有用户明确要求设备执行动作（例如‘画完后让小车前进’）才记录物理操作。"
            "缺少几何尺寸交给 CAD 需求解析追问，不因缺少尺寸或不熟悉图形而澄清操作类型。"
            "多项危险动作或指代不明时 requires_clarification=true。\n"
            f"模式：{self.normalize_agent_mode(mode)}\n"
            f"规则初判：{json.dumps(route, ensure_ascii=False)}\n"
            f"最近上下文：{json.dumps(recent, ensure_ascii=False)}\n"
            f"用户消息：{message}"
        )
        review_messages = [
            {"role": "system", "content": "严格输出 JSON，禁止 Markdown。"},
            {"role": "user", "content": prompt},
        ]
        review_attempts = 0
        try:
            review_attempts = 1
            content = self._structured_review_text(review_messages, mode=mode)
            review = self._json_object(content)
            if not self._route_review_payload_usable(review):
                retry_messages = self._structured_review_retry_messages(
                    review_messages,
                    content,
                    reason="路由 JSON 缺失或意图字段无效",
                )
                review_attempts = 2
                content = self._structured_review_text(retry_messages, mode=mode)
                review = self._json_object(content)
        except (RuntimeError, ValueError, TypeError) as error:
            route["decision_source"] = "rules_fallback"
            route["review"] = {
                "attempted": True,
                "request_attempts": review_attempts or 1,
                "error": str(error),
            }
            return route
        reviewed_route = self._merge_route_review(route, review)
        reviewed_route.setdefault("review", {})["request_attempts"] = review_attempts
        return reviewed_route

    def _structured_cad_edit_fallback(
        self,
        message: str,
        history: list[dict[str, str]],
        route: dict[str, Any],
        mode: str,
    ) -> dict[str, Any]:
        """Interpret rule-missed CAD edits without allowing model geometry."""
        if (
            self.normalize_agent_mode(mode) != "advanced"
            or route.get("name") != "drawing_design"
            or route.get("operation") != "modify"
            or route.get("decision_source") in {
                "incremental_cad_edit", "incremental_cad_edit_chain",
                "constrained_cad_addition",
            }
            or getattr(self, "mode", "local") == "local"
            or not self.configured
            or self._physical_action_signals(message)
        ):
            return route
        recent = [
            {"role": item.get("role"), "content": item.get("content")}
            for item in history[-3:] if item.get("content")
        ]
        from .cad_construction import construction_geometry_bounds
        selected_context={}
        selected_project=get_creative_project_store().get(self._project_id_from_route(route))
        if isinstance(selected_project,dict):
            selection=route.get('drawing_selection') or {}
            variant_id=selection.get('variant_id') or route.get('selected_variant_id') or selected_project.get('design_base_variant_id')
            selected_variant=next((v for v in selected_project.get('variants') or [] if v.get('id')==variant_id),None)
            if selected_variant:
                chosen=set(selection.get('geometry_ids') or [])
                geometries=[g for g in selected_variant.get('geometries') or [] if not chosen or g.get('id') in chosen]
                selected_context={'project_id':selected_project['id'],'variant_id':variant_id,
                    'selection':selection,'logical_objects':selected_variant.get('logical_objects') or [],
                    'geometry_summaries':[{'id':g['id'],'type':g.get('type'),
                        'bounds_mm':construction_geometry_bounds([g]),
                        **({k:g[k] for k in ('center','radius') if k in g})} for g in geometries[:50]],
                    'total_geometry_count':len(geometries),'units':'mm'}
        prompt = (
            "你是 CAD 修改意图解释器，不回答用户，不生成图形或坐标。"
            "只输出单个 JSON 对象，schema_version 必须是 cad.language-interpretation.v1。"
            "顶层字段只能是 is_cad_edit、operation、target、parameters、assumptions、"
            "constraints、evidence_text、confidence 和 schema_version。"
            "operation 只能是 translate/rotate/scale/resize/duplicate/align/delete/retain/"
            "mirror/offset/array/constraint。"
            "target.scope 只能是 instance/logical_object/semantic/attribute/unresolved。"
            "scope=instance 时必须输出 instance_ids 整数数组，例如 [1]，禁止 instance_id；"
            "scope=logical_object 时必须输出 position，可选 count、object_type；"
            "scope=semantic 时必须输出 semantic；scope=attribute 时必须输出 attribute 和 value。"
            "parameters 只能使用 dx_mm、dy_mm、coordinate_frame、angle_degrees、pivot、factor、"
            "dimension、value_mm、direction、distance_mm、placement、alignment、"
            "reference_instance、mirror_axis、keep_source、offset_side、array_mode、rows、columns、"
            "row_spacing_mm、column_spacing_mm、count、constraint_type。"
            "evidence_text 必须是包含 1 到 6 个字符串的数组，每个字符串都必须逐字摘录用户原文。"
            "assumptions 必须是字符串数组，constraints 必须是对象数组。"
            "禁止 geometry_id 和任何 x/y/顶点；无法确定目标时使用 scope=unresolved，"
            "此时系统只会澄清，不会执行。"
            "所有距离转换成毫米。不能从原文确定的字段必须省略，不得猜测。"
            "semantic 使用 center_circle/outer_frame/center_line。"
            "position 使用 middle/left/right/top/bottom。"
            "dimension 使用 width/height/radius，方向使用 left/right/up/down。"
            "如果不是修改已有图纸，is_cad_edit=false。\n"
            f"最近上下文：{json.dumps(recent, ensure_ascii=False)}\n"
            f"后端当前选区（仅用于理解已有目标，不是新需求）：{json.dumps(selected_context, ensure_ascii=False)}\n"
            f"用户原文：{message}"
        )
        review_messages = [
            {"role": "system", "content": "严格输出单个 JSON 对象，禁止 Markdown。"},
            {"role": "user", "content": prompt},
        ]
        failure_reason = "invalid_json"
        interpreted = None
        review_attempts = 0
        for attempt in range(2):
            content = ""
            try:
                review_attempts = attempt + 1
                content = self._structured_review_text(review_messages, mode=mode)
                payload = self._json_object(content)
                if isinstance(payload, dict):
                    failure_reason = "invalid_schema_or_grounding"
                else:
                    failure_reason = "invalid_json"
                interpreted = (
                    parse_structured_cad_interpretation(payload, message)
                    if isinstance(payload, dict) else None
                )
            except RuntimeError:
                failure_reason = "provider_request_failed"
                break
            except (ValueError, TypeError):
                failure_reason = "invalid_schema_or_grounding"
                interpreted = None
            if interpreted is not None or attempt == 1:
                break
            review_messages = self._structured_review_retry_messages(
                review_messages,
                content,
                reason=(
                    "CAD JSON 不符合 schema 或无法由用户原文支撑"
                    if failure_reason == "invalid_schema_or_grounding"
                    else "CAD JSON 无法解析"
                ),
            )
        if interpreted is None:
            result = dict(route)
            result["cad_interpretation"] = {
                "attempted": True,
                "valid": False,
                "executable": False,
                "provider": self.mode,
                "reason": failure_reason,
                "request_attempts": review_attempts or 1,
            }
            return result
        edit, intent = interpreted
        result = dict(route)
        confidence = float(intent.get("confidence") or 0.0)
        if confidence < 0.75:
            result.update({
                "decision_source": "model_cad_clarification",
                "edit_parser": "model_structured_fallback",
                "edit_intent": intent,
                "review_required": False,
                "clarification_required": True,
                "clarification_question": (
                    "我不能可靠确定这次修改的目标或参数。"
                    "请在右侧点选目标，并用一句话说明要执行的修改。"
                ),
                "safety_confirmation_required": False,
                "cad_interpretation": {
                    "attempted": True,
                    "valid": True,
                    "executable": False,
                    "provider": self.mode,
                    "reason": "low_confidence_or_grounding_failed",
                    "request_attempts": review_attempts,
                },
            })
            return result
        result.update({
            "name": "drawing_design",
            "tool_family": "cad",
            "operation": "modify",
            "decision_source": "incremental_cad_edit",
            "edit_parser": "model_structured_fallback",
            "resolved_edit": edit,
            "edit_intent": intent,
            "review_required": False,
            "clarification_required": False,
            "safety_confirmation_required": False,
            "cad_interpretation": {
                "attempted": True,
                "valid": True,
                "executable": True,
                "provider": self.mode,
                "request_attempts": review_attempts,
            },
        })
        return result

    def _cad_construction_model_callback(
        self,
        *,
        mode: str = "advanced",
        alternatives: bool = False,
        repair_context: dict[str, Any] | None = None,
    ) -> tuple[Any | None, dict[str, Any]]:
        """Build the bounded model callback shared by production and evals."""
        state = {"provider_attempted": False, "request_attempts": 0}

        def structured_model_callback(
            source_text: str, schema: dict[str, Any],
        ) -> dict[str, Any]:
            state["provider_attempted"] = True
            candidate_instruction = (
                "输出2至3个真正不同的结构候选，每个候选必须包含独立的构造计划。"
                "候选差异必须来自拓扑、构造关系或约束差异，不得仅靠平移、重命名或"
                "调整无关字段伪造差异。每个 rationale 要简述该候选的结构差异。"
                if alternatives
                else "输出一个构造计划。"
            )
            prompt = (
                "你是二维 CAD 构造计划解释器，不回答用户，不输出 Markdown。"
                "只输出一个符合给定 JSON Schema 的 JSON 对象。"
                f"{candidate_instruction}"
                "把用户要求拆成有顺序的确定性二维构造原语；不得输出脚本、DXF、SVG 或解释文字。"
                "只能使用 Schema 中允许的操作和字段，不得猜测整体施工尺寸。"
                "多对象创建必须分别输出全部具名轮廓，不能把本句中‘它们’当成历史对象。"
                "若独立组成契约已给出每个对象宽高、左右顺序和间距，后端会将这些关系绑定到"
                "free_outline_layout并精确执行；请用semantic.label包含用户原对象名称。"
                "每个构造步骤的semantic必须说明整体归属：assembly_id是同一完整对象共享的稳定英文ID，"
                "assembly_label是该完整对象的用户名称；object_id和label标识它下面的部件。"
                "同一时钟的表盘刻度指针、同一笑脸的外圆眼睛嘴巴即使不相连也共享整体ID。"
                "用户明确要求两个独立对象时必须使用不同整体ID，接触或相交不能据此合并。"
                "不要因为手算缩放和排列困难而降低需求理解置信度；仍须生成正确形状，不能以矩形代替。"
                "用户给出函数关系、周期、圈数或半径变化规律时，优先用add_parametric_curve，"
                "输出x_expression、y_expression及字符串t_start、t_end，由后端计算采样点；"
                "禁止凭印象手填样条控制点代替数学关系。表达式仅支持t、pi、e、"
                "+ - * / **、括号和sin/cos/tan/sqrt/exp/log/abs等单参数函数；"
                "仅参数曲线表达式的三角函数与t区间使用弧度和显式乘号，区间端点不含t。"
                "add_arc、复合路径arc段的start_angle/end_angle以及rotation_deg始终使用度（半圆180度），不得填pi作为角度数值。max_sampling_error按plan.units计。"
                "螺距均匀意味着半径随角度线性变化；圈数决定角度跨度，不能把最大半径"
                "误当成精确宽高。不要为开放曲线添加闭合约束。"
                "已有整体尺寸的自由轮廓，内部控制点位置和比例属于建模选择，可在边界内设计并声明假设。"
                "对于平滑、单一、周期性闭合自由边界，也可优先使用现有add_parametric_curve表达整体周期关系，"
                "避免手算多个旋转贝塞尔扇区的端点与切线。公式属于建模假设，必须声明；"
                "须保证一个参数周期只遍历边界一次、端点及切线连续、内部无自交；"
                "闭合和重复数量由后端独立测量。后端可按明确整体宽高仿射调整自由轮廓，不适用于精确半径或固定坐标。"
                "如果请求属于 CAD 构造但存在必要参数缺失，设置 is_construction_request=true、"
                "plan=null，并降低 confidence。evidence_text 中每一项必须逐字摘录用户原文。"
                "缺少参数时必须填写clarification，question_key为shape、size、curve_constraints或standard_spec，"
                "question只追问真正缺少的一项；recognized_shape逐字摘录用户已说明的完整对象名称。"
                "多个独立对象不代表用户要求左右排列；原文未要求排列、布局或间距时，"
                "不得把左右排列及间距当成必填参数追问。缺少对象尺寸时先只追问尺寸和单位；"
                "布局需求若确实影响后续构造，应作为独立待确认项，不得伪装成用户已指定的左右排列。"
                "对象不在本地模板中不等于缺少图形类型。用户要求按标准尺寸但未指定规格时，"
                "追问具体规格或实际宽高，不能重新问要什么图形；不要未经核实宣称某个尺寸是最新标准。"
                "坐标和尺寸统一放在 plan.units 指定的单位中。每个构造步骤必须带可读语义标签，"
                "外径或外接圆直径约束径向距离，不代表轴对齐包围盒的宽高都等于该直径。"
                "仅当用户明确整体宽高，或已根据实际顶点计算出包围盒时，才添加bounds_size断言；不得用直径代替宽高，也不得为满足这种错误断言拉伸径向轮廓。"
                "不同笔画或部件的semantic.object_id必须全局唯一；同一整体只共享assembly_id，不能把assembly_id当作每个部件的object_id。"
                "若不确定部件ID可省略object_id，由后端根据唯一output_ref分配；不要重复填写outline等通用ID。"
                "收到logical_graph_validation或identity_conflicts时，须同时修正列出的对象归属与几何断言错误，保留所有用户要求的部件与尺寸。"
                "ConstructionPoint的x/y允许受限数学表达式字符串（不含t），支持sin、cos、sqrt、atan2(y,x)。"
                "涉及角度和比例时输出数学表达式，让后端精确计算，禁止凭印象手编近似顶点。"
                "以下内外顶点规则仅适用于用户明确要求的星形、花瓣或波瓣，不适用于普通正多边形。"
                "带内外顶点的规则径向多边形复用add_rotational_path：一周期仅两条line，"
                "add_rotational_path.center必须是该部件实际旋转中心；即使中心不在原点也必须显式填写，"
                "segments中的点使用与center一致的全局坐标，不能把偏移后的点绕默认原点旋转。"
                "起点在外半径R和角度theta，转pi/N到内半径r，再转pi/N到下一个外顶点。"
                "点坐标用cx+R*cos(theta)等表达式；theta若指向另一中心，可用atan2(dy,dx)。"
                "上述cx、R、theta仅为说明符号，实际输出必须代入具体数值或完整展开表达式；"
                "禁止输出r_in、R、cx、theta等未定义变量。坐标表达式仅允许数字、pi/e及白名单函数；参数曲线才额外允许t。"
                "设置count=N、direction=counterclockwise、continuity=C0、constrain_sector_end=true，"
                "不要为尖角轮廓声明C1，不要对有精确半径约束的组成使用fit_width/fit_height。"
                "radial_pattern默认校验平滑轮廓；尖角径向多边形若添加该断言必须设置profile=polygonal。"
                "普通正多边形所有顶点同一外接半径，优先add_polyline表达有序角点；若用旋转构造，一个周期是一条边，不能添加内谷或第二条回折边。"
                "复杂图形应拆成多个具名逻辑对象，并加入可验证的尺寸、闭合或图元数量断言。\n"
                "自由轮廓若已给出整体宽高、闭合性和重复结构数量，即具备建模条件；"
                "无需用户逐点提供控制点。可选择规则对称、等距重复和自然比例作为建模假设，"
                "在 assumptions 中明确说明，并使用 Schema 支持的曲线或足够密的闭合多段线表达。"
                "必须保留用户指定的结构数量和整体尺寸；如果确实无法表达，返回具体限制。\n"
                "仅当用户明确只要单一外边界、且结构契约不要求内孔或内部笔画时，才限制为一条连续闭合外边界。"
                "结构所需内孔、横笔和独立部件不是装饰，不能因用户用了‘轮廓’一词而删除。"
                "外边界与内边界必须分别输出独立路径，不得用连接桥、重复顶点或回走边拼成单一闭合路径。"
                "不要添加未要求的装饰；每条边界不得自相交，曲线段端点必须依次连续。\n"
                "开放分割线同样必须是一条连续路径：先计算各段起终点，再核对连接。"
                "圆弧角度按x轴正向为0度、逆时针递增，端点=center+radius*(cos(angle),sin(angle))。"
                "S形路径须由两个相反弯曲段首尾相接，不能用两个互不连接的半圆冒充；"
                "独立闭合小圆不参与分割线连接。分割线两端须落在所分割的外边界上。\n"
                "需要用分段控制点描述中心旋转重复闭合轮廓时，使用add_rotational_path："
                "只设计一个周期的开放曲线单元segments，给出center和count=N。"
                "后端将单元旋转360/N度重复N次，并拼接成一条闭合边界。"
                "direction=auto时后端依据起点相对中心及曲线切向确定顺逆时针；"
                "也可明确clockwise或counterclockwise，必须与单元曲线前进方向一致。"
                "单元终点必须等于其起点绕center旋转360/N度的位置；"
                "对没有固定控制点的自由轮廓设置constrain_sector_end=true，"
                "由后端精确施加上述端点关系，避免手算旋转端点的舍入误差；"
                "单元内部应恰好包含一个外凸峰值，不得回到中心或形成独立闭合图元。"
                "平滑重复轮廓优先用单段三次贝塞尔表达一个周期，并设置continuity=C1；"
                "通过起点处切线方向和控制柄长度设计单元外形，后端施加周期端点及切向约束。"
                "确有复杂结构时才使用多段曲线，避免引入不必要的内部接点。"
                "例如从一个内凹点出发，经过一个圆滑外凸峰，结束于下一个内凹点；"
                "只输出该单元的控制点，不要手算其余N-1个单元。"
                "非重复平滑自由外轮廓使用 add_composite_path，由少量三次贝塞尔段表达，closed=true；"
                "每段4个控制点，相邻段端点完全相同，最后一段终点等于第一段起点。"
                "用控制点描述曲线，让后端采样，不要手工枚举数百个近似顶点。"
                "曲线段数乘samples_per_curve必须不超过480；一般每段用16或32次采样。"
                "确保相邻段切线连续，每个凸瓣通常可用两段曲线描述。"
                "只有花瓣或波瓣重复轮廓才交替排列外凸端点与内凹端点：先确定同一中心及360/N度的角间隔，"
                "再用贝塞尔控制点连接；禁止沿某个方向不断累加坐标。"
                "所有端点必须围绕中心完整转过一周，不能用圆或椭圆冒充指定数量的凸瓣。"
                "坐标建议保留6位小数；若未精确证明连接处的一阶导数关系，使用continuity=C0，"
                "不要声明无法满足的C1断言。"
                "径向重复结构必须符合用户指定数量，例如N个凸瓣必须恰好有N个径向峰值；"
                "若选择多段线，轮廓至少使用每个重复单元12个有序采样点，保持圆滑，禁止用多角星替代曲线轮廓。"
                "当结构契约确认为单一闭合外边界时，整个计划只输出一个闭合路径步骤；"
                "带内孔、多笔画或多个部件的结构不适用该限制，必须遵守结构契约的独立路径要求。"
                "不要把重复结构拆成多个独立图元，也不要在计划中添加布局阵列。"
                "顶点沿外边界依次排列，不重复首点，不交叉连接不同部位。"
                "整体宽高按所有顶点的实际极值计算，控制点外包框不等于曲线实际边界。\n"
                "用户明确给出平方米/平米面积时，该面积已经是完整尺度约束，不得再索要宽高；"
                "为封闭轮廓给出自然比例并在 assumptions 说明，优先使用可验证的闭合复合路径。"
                "entity_count 统计 CAD 图元数量，不统计多段线顶点；一个 add_polyline "
                "无论包含多少顶点都只算1个图元，禁止用 entity_count 断言顶点数。"
                "若输入含[确定性需求规范化]，其内容是后端依据用户原文计算的单位、阵列和拓扑事实，"
                "应直接用于构造计划；其中标明的规范化约定必须写入 assumptions。"
                "evidence_text 只能逐字摘录标记之前的用户原文，不能引用规范化提示。\n"
                f"JSON Schema：{json.dumps(schema, ensure_ascii=False)}\n"
                f"用户原文：{source_text}\n"
                "evidence_text 请逐字复制以下原文片段，不要改写单位、标点或数字："
                + json.dumps([source_text.split("\n", 1)[0]], ensure_ascii=False)
            )
            if repair_context is not None:
                from .cad_local_repair import coordinate_patch_schema, coordinate_patch_example
                patch_schema=coordinate_patch_schema(repair_context)
                prompt=("你只负责修复二维CAD计划中指定的坐标字段。严格输出cad.coordinate-patch.v2补丁，每个edits条目直接包含output_ref与坐标字段，不要fields包装。禁止输出plan或重写整份计划。"
                        "对闭合多段线的简单开口，可优先提交subtract_rectangle（min_x,min_y,max_x,max_y）表达从原边界区域减去矩形；四个数均使用original_plan.units，不能混用诊断的毫米单位。"
                        "后端计算相交和裁剪顶点，无需手写整条轮廓。每个条目只能选择直接坐标或subtract_rectangle一种方式。"
                        "裁剪不得触及受保护路径；结果必须仍是一个无内孔的完整边界，删除、拆分或新内孔会被拒绝。"
                        "若local_repair_scope提供cut_windows_by_ref，应优先使用subtract_relative_rectangle，给出left_fraction、right_fraction、height_fraction三项比例（严格0到1且左小于右）。"
                        "后端依据已测量的可行窗口换算矩形位置和高度，不需手算绝对坐标；不要取0或1以触及窗口边界。"
                        "不能修改未列出的步骤、身份、闭合性、断言、单位或其他全局参数。后端将复制原计划并合并补丁，再独立验收全部几何。"
                        "顶点必须沿真实边界有序排列，不重复首点，不用回走边或自相交掩盖结构错误。"
                        "提交前按顶点坐标的最小值、最大值核对原计划的宽高断言；不能只修出半个结构或靠缩放其他路径补足尺寸。"
                        "format_example只展示合法JSON嵌套，坐标原样取自失败计划，并非正确答案；必须修改失败坐标，照抄会被拒绝。"
                        "若无法在范围内修复，也不能改动其他部件来伪造成功。\n"
                        +json.dumps({'user_source':source_text.split('\n后端试算反馈：',1)[0],
                            'original_plan':repair_context.get('plan') or repair_context.get('rejected_plan'),
                            'measured_failure':repair_context['construction_error'],'patch_schema':patch_schema,
                            'format_example':coordinate_patch_example(repair_context)},ensure_ascii=False))
            messages = [
                {"role": "system", "content": "严格输出单个 JSON 对象，禁止 Markdown。"},
                {"role": "user", "content": prompt},
            ]
            token_budget = self._construction_review_max_tokens()
            if repair_context is not None:token_budget=min(token_budget,4096)
            planning_options = ({"model_override": self.cad_planning_model} if self.mode == "deepseek" else {})
            if alternatives:
                token_budget = min(8192, token_budget * 2)
            state["request_attempts"] += 1
            raw = self._structured_review_text(
                messages,
                mode=mode,
                max_tokens_override=token_budget,
                **planning_options,
            )
            payload = self._json_object(raw)
            if not isinstance(payload, dict):
                retry_messages = self._structured_review_retry_messages(
                    messages,
                    raw,
                    reason="响应不是可解析的单个 JSON 对象",
                )
                state["request_attempts"] += 1
                raw = self._structured_review_text(
                    retry_messages,
                    mode=mode,
                    max_tokens_override=token_budget,
                    **planning_options,
                )
                payload = self._json_object(raw)
                if not isinstance(payload, dict):
                    raise ValueError("模型连续两次未返回可解析的 JSON 对象")
            if repair_context is not None:
                from .cad_local_repair import apply_coordinate_patch
                merged=apply_coordinate_patch(repair_context,payload)
                state['coordinate_patch']={'schema':payload['schema_version'],'source_plan_sha256':payload['source_plan_sha256'],
                    'patched_refs':[e['output_ref'] for e in payload['edits']],
                    'operations':[{'output_ref':e['output_ref'],'kind':('subtract_relative_rectangle' if 'subtract_relative_rectangle' in e else 'subtract_rectangle' if 'subtract_rectangle' in e else 'coordinates'),
                                   **({'rectangle':deepcopy(e['subtract_rectangle'])} if 'subtract_rectangle' in e else {}),
                                   **({'fractions':deepcopy(e['subtract_relative_rectangle'])} if 'subtract_relative_rectangle' in e else {})} for e in payload['edits']]}
                return {'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
                    'plan':merged,'confidence':payload['confidence'],'assumptions':repair_context.get('assumptions') or [],
                    'evidence_text':[source_text.split('\n',1)[0]]}
            return payload

        callback = None
        if (
            self.normalize_agent_mode(mode) == "advanced"
            and getattr(self, "mode", "local") != "local"
            and self.configured
        ):
            callback = structured_model_callback
        return callback, state

    def _interpret_cad_construction_plan(
        self,
        message: str,
        *,
        mode: str = "advanced",
        repair_context: dict[str, Any] | None = None,
        component_repair_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Produce one verified CadConstructionPlan without persistence.

        This is the only production construction interpreter. Deterministic
        rules run first; on a rule miss, the configured structured model gets
        one bounded attempt (plus one JSON-format repair retry).
        """
        callback, state = self._cad_construction_model_callback(mode=mode,**({'repair_context':repair_context} if repair_context is not None else {}))
        if callback is not None and component_repair_context is not None:
            original_callback = callback
            def callback(source, schema):
                original_plan = component_repair_context.get('plan') or component_repair_context.get('rejected_plan') or {}
                affected = ((component_repair_context.get('construction_error') or {}).get('details') or {}).get('affected_output_refs') or []
                failed_assertion = (component_repair_context.get('construction_error') or {}).get('assertion_id')
                identity_only=bool(((component_repair_context.get('construction_error') or {}).get('details') or {}).get('identity_only_repair'))
                payload = original_callback(
                    source + '\n后端部件合并协议：本次仅输出 affected_output_refs 对应的步骤，'
                    + ('本次仅修复重复身份：保持每个output_ref，给出semantic.object_id的互不重复标识，不得重新规划几何。后端只采用object_id，其他字段全部使用原计划。' if identity_only else '') +
                    '其他部件、布局和断言由后端保留，禁止重新生成；不要添加辅助占位图形。'
                    'plan.units必须保持原单位。此精简计划仅用于合并，合并后仍执行全部验收。'
                    + (f'唯一允许同步修正的模型自拟错误断言是{failed_assertion}，放入assertions并保持原ID及target_ref；不可修改其他断言或用户原始要求。' if failed_assertion else '') + '\n'
                    + json.dumps({'affected_output_refs': affected,
                                  'required_units': original_plan.get('units', 'm')}, ensure_ascii=False),
                    schema,
                )
                from .cad_plan_component_repair import merge_component_repair
                return merge_component_repair(component_repair_context, payload)
        result = interpret_construction_request(message, callback)
        if state.get('coordinate_patch'):result['coordinate_patch']=deepcopy(state['coordinate_patch'])
        attempted = bool(state["provider_attempted"])
        attempts = int(state["request_attempts"])
        result["provider"] = self.mode if attempted else None
        result["provider_attempted"] = attempted
        result["request_attempts"] = attempts
        result["structured_retry_used"] = attempts > 1
        result["persisted"] = False
        result["production_interpreter"] = True
        return result

    @staticmethod
    def _project_construction_prompt(project: dict[str, Any]) -> str:
        """Include confirmed follow-ups when compiling a project's CAD plan."""
        original = str(project.get("original_prompt") or project.get("name") or "").strip()
        requirements = deepcopy(project.get("requirements") or {})
        ledger=project_requirement_ledger(original,requirements.get('source_followups') or [])
        contract=ledger['requirement_contract']
        requirements['user_dimension_contract']={
            'schema':contract['schema'],
            'effective_requirements':[f for f in contract['facts'] if f['status']=='effective'],
            'conflicts':contract['conflicts'],'coverage':contract['coverage']}
        # Keep the complete, reproducible contract in the model snapshot. The
        # model must reason from this ledger rather than reconstructing state
        # by replaying chat history.
        requirements['requirement_contract_snapshot'] = deepcopy(contract)
        requirements['project_constraints'] = deepcopy(project.get('constraints') or {})
        source_text=original+'\n'+'\n'.join(requirements.get('source_followups') or [])
        if (re.search(r'\d+\s*(?:列|行).*?\d+\s*(?:行|列)', source_text)
                or re.search(r'每(?:条|个|段|块|级)[^；;\n]{0,40}(?:宽|高|长)',source_text)):
            # Legacy parameterizers indexed a cell side/radius as overall
            # array width/height. Only source-owned overall dimensions may
            # be presented to the model as confirmed array extents.
            supported={f['field'] for f in contract['facts'] if f['status']=='effective'
                and f['field'] in {'width','height'} and f['binding']=='single_subject'}
            for field in ('width','height'):
                if field not in supported:
                    requirements.get('dimensions',{}).pop(field+'_m',None)
        if len(contract['subjects'])==1:
            fields={'width':'width_m','height':'height_m','radius':'radius_m','diameter':'diameter_m'}
            for fact in contract['facts']:
                if fact['status']=='effective' and fact['operator']=='eq' and fact['field'] in fields:
                    requirements.setdefault('dimensions',{})[fields[fact['field']]]=fact['value_mm']/1000
        scoped = explicit_composition(original+'\n'+'\n'.join(requirements.get('source_followups') or []))
        if scoped and scoped.get('kind')=='named_components' and scoped.get('component_dimensions'):
            # The numeric index may contain a local part's size. It must not
            # be promoted into a latest whole-drawing instruction.
            requirements['dimensions']=deepcopy(scoped.get('dimensions') or {})
            requirements['component_dimensions']=deepcopy(scoped['component_dimensions'])
        dimensions = requirements.get("dimensions") or {}
        size = []
        if dimensions.get("width_m") is not None:
            size.append(f"宽度{dimensions['width_m']}米")
        if dimensions.get("height_m") is not None:
            size.append(f"高度{dimensions['height_m']}米")
        if dimensions.get("radius_m") is not None:
            size.append(f"半径{dimensions['radius_m']}米")
        if dimensions.get("diameter_m") is not None:
            size.append(f"直径{dimensions['diameter_m']}米")
        return (
            original + "\n[CAD_REQUIREMENT_CONTRACT_SNAPSHOT.v1]\n新建 CAD 图纸：" + original + "\n最新已确认要求（覆盖原描述中同名参数）："
            + "，".join(size) + "\n"
            + json.dumps({"original_prompt": original,
                          "requirements": {k:v for k,v in requirements.items() if k != "requirement_ledger"}},
                         ensure_ascii=False)
            + "\n用户逐轮补充的原文约束（按时间排序，后文覆盖同名约束；必须保留全部组成）：\n"
            + "\n".join(requirements.get("source_followups") or [])
        )

    @staticmethod
    def _construction_input_snapshot(
        message: str, project: dict[str, Any] | None,
    ) -> str:
        """Return the sole model input for construction planning.

        Once a project exists, the model must never receive the raw current
        turn or an independently concatenated chat history.  The persisted
        project requirements (including the requirement ledger and follow-ups)
        are the canonical snapshot.  A project-less first turn gets an
        explicit snapshot wrapper so it follows the same contract shape.
        """
        if isinstance(project, dict):
            return RobotAgentService._project_construction_prompt(project)
        text = str(message or "").strip()
        return (
            text + "\n[CAD_REQUIREMENT_CONTRACT_SNAPSHOT.v1]\n"
            + json.dumps({
                "original_prompt": text,
                "requirements": {},
                "source_followups": [],
                "status": "unpersisted_initial_request",
            }, ensure_ascii=False)
        )

    @staticmethod
    def _is_generic_cad_construction_request(
        message: str, route: dict[str, Any]
    ) -> bool:
        """Gate the shared template/rule/model constructor to CAD creation."""
        if route.get("name") != "drawing_design" or route.get("operation") != "create":
            return False
        text = message.strip()
        if not text:
            return False
        if not re.search(
            r"(?:创建|新建|生成|绘制|画|构造|规划|设计(?:一个|一张|图纸)|做一个)",
            text,
            re.IGNORECASE,
        ):
            return False
        if reference_contract(text) or explicit_composition(text):
            return True
        return True

    def _formal_cad_construction(
        self,
        message: str,
        route: dict[str, Any],
        *,
        mode: str,
    ) -> dict[str, Any] | None:
        """One production entry for template, rule and structured-model creation."""
        if route.get("name") != "drawing_design" or route.get("operation") != "create":
            return None
        raw_followup = str(route.get("user_message") or message).strip()
        project_id = self._project_id_from_route(route)
        if not project_id and not local_creation_objects(raw_followup):
            project_id = str(route.get("selected_project_id") or "").strip() or None
        project = get_creative_project_store().get(project_id) if project_id else None
        clarification_followup = bool(
            project and not project.get("variants")
            and project.get("status") in {"draft", "clarifying", "ready_for_design"}
            and raw_followup and not local_creation_objects(raw_followup)
            and not self._is_design_generation_confirmation(raw_followup)
        )
        if clarification_followup:
            # A parameter answer belongs to the selected unfinished creation.
            # Merge it into the persisted requirement contract first; the model
            # must never receive a separately concatenated chat turn.
            self._apply_design_requirement_followup(
                raw_followup,
                {**route, "selected_project_id": str(project.get("id") or project_id or "")},
            )
            project = get_creative_project_store().get(str(project.get("id") or project_id or "")) or project
            # Routing eligibility is evaluated against the persisted original
            # request, never against the short parameter-only answer.
            message = str(project.get("original_prompt") or message)
            route = {**route, "stage": "candidate_generation"}
        explicit_confirmation = self._is_design_generation_confirmation(message)
        # A complete new drawing command (including explicit coordinate
        # geometry) is already the construction request.  An unfinished
        # project created by the router must not turn that same command into a
        # second confirmation round; confirmation gates apply to short
        # confirmation/follow-up messages only.
        coordinate_defined_creation = bool(
            local_creation_objects(message)
            and len(re.findall(r"[（(]\s*[-+]?\d", message)) >= 2
            and re.search(
                r"坐标单位(?:为|是)?\s*(?:米|厘米|毫米|m|cm|mm)",
                message,
                re.I,
            )
        )
        gate_message = message if (explicit_confirmation or not local_creation_objects(message)) else ""
        # A coordinate-defined command is already an executable, complete
        # construction request.  It must not be converted into the generic
        # "confirm a new drawing" gate merely because the router created an
        # unfinished project shell before reaching the formal constructor.
        gate = ({"should_handle": False}
                if coordinate_defined_creation and not explicit_confirmation
                else design_confirmation_gate(
                    gate_message, project, explicit_confirmation=explicit_confirmation
                ))
        if gate.get("should_handle"):
            if gate.get('error'):
                return {**self._result(str(gate['error']),self._empty_usage()),
                    'ok':False,'error_code':'candidate_generation_failed'}
            preflight=candidate_preflight(project,candidate_generation_context(project,route))
            if preflight.get('ok') is not True:
                return {**self._result(str(preflight['message']),self._empty_usage()),
                    'ok':False,'error_code':'candidate_requirements_incomplete',
                    'project_id':project_id,'project':project,'readiness':preflight.get('readiness')}
            confirmed = self._confirm_parameterized_project(message, route)
            if confirmed is not None:
                return confirmed
            if project is not None:
                # The project snapshot is the only source of truth after
                # confirmation. Do not rebuild a second prompt from history.
                project = get_creative_project_store().get(str(project.get("id") or project_id or "")) or project
        if not self._is_generic_cad_construction_request(message, route):
            return None

        # Every creation request uses this construction-plan producer.
        # Templates and rules are deterministic strategies inside the interpreter; a
        # rule miss uses one structured-model plan. SketchGraph alternatives
        # are reserved for offline evaluation.
        model_input = self._construction_input_snapshot(message, project)
        interpretation = self._interpret_cad_construction_plan(model_input, mode=mode)
        if (interpretation.get("status") == "clarification_required"
                and interpretation.get("provider_attempted")
                and isinstance(project, dict)
                and not project.get("missing_parameters")
                and (interpretation.get("clarification") or {}).get("question_key") == "curve_constraints"):
            # A complete persisted contract already authorizes free-contour
            # modelling assumptions.  A model request for hand-supplied
            # control points is a planning miss, not a new user requirement.
            # Retry once from the identical snapshot with that specific
            # failure; do not replace the contract with a short chat turn.
            retry = self._interpret_cad_construction_plan(
                model_input + "\n后端试算反馈：需求契约已完整。用户没有义务提供曲线控制点；"
                "请根据已确认尺寸、部件数量和关系，使用通用构造原语提出可验证计划，"
                "必要的内部曲线比例写入assumptions。不得省略已有部件。",
                mode=mode,
            )
            if isinstance(retry, dict):
                interpretation = retry
        # Coordinate-defined primitive commands are complete when their unit
        # is explicit. If an earlier clarification route supplied a stale
        # scope response, re-evaluate the persisted command snapshot once
        # before surfacing that stale question.
        if (interpretation.get("status") == "clarification_required"
                and len(re.findall(r"[（(]\\s*[-+]?\\d", message)) >= 2
                and re.search(r"坐标单位(?:为|是)?\\s*(?:米|厘米|毫米|m|cm|mm)", message, re.I)):
            from .cad_construction_interpreter import interpret_construction_request
            refreshed = interpret_construction_request(raw_followup)
            if isinstance(refreshed, dict):
                interpretation = refreshed
        if (interpretation.get("status") == "invalid"
                and interpretation.get("model_required")
                and not route.get("construction_retry")):
            # A single bounded retry belongs inside the production formal
            # path because App confirmations do not call generate_project_candidate.
            retry = self._interpret_cad_construction_plan(model_input, mode=mode)
            if isinstance(retry, dict):
                interpretation = retry
        construction_attempts = [deepcopy(interpretation)]
        while (should_repair(interpretation)
               and bounded_repair_available(construction_attempts, max_repairs=2)):
            failed_attempt=deepcopy(interpretation)
            repair_details=(failed_attempt.get('construction_error') or {}).get('details') or {}
            failed_refs=set(repair_details.get('affected_output_refs') or [])
            plan_refs={s.get('output_ref') for s in (failed_attempt.get('plan') or failed_attempt.get('rejected_plan') or {}).get('steps',[])}
            structural_replan=bool(repair_details.get('requires_structural_replan')
                and plan_refs and plan_refs.issubset(failed_refs))
            failure = interpretation.get("error") or {}
            feedback = str(failure.get("message") or "构造计划未通过验证")
            if isinstance(interpretation.get("construction_error"), dict):
                feedback += "\n结构化验证证据：" + json.dumps(
                    interpretation["construction_error"], ensure_ascii=False
                )
                if (interpretation['construction_error'].get('details') or {}).get('local_repair_scope'):
                    feedback += "\n本次是受保护的局部修复：仅可修改editable_fields_by_ref列出的坐标字段。必须保留全部步骤及其顺序、标识、语义和全局参数；不得增删步骤、重命名或改变其他部件。修复后会逐项比较并校验受保护几何。"
            rejected_plan = interpretation.get("plan") or interpretation.get("rejected_plan")
            previous_plan = (
                "\n前次未通过的计划（仅供修正，禁止当成用户要求）："
                + json.dumps(rejected_plan, ensure_ascii=False)
                if isinstance(rejected_plan, dict) else ""
            )
            interpretation = self._interpret_cad_construction_plan(
                model_input + "\n后端试算反馈：前一次计划未通过验证：" + feedback
                + ("。全部构造步骤均未通过结构验收，允许重新编译这些失败步骤的组成、数量和模型自拟断言，删除错误的多余部件。旧计划不是需求，禁止机械保留错误内外边界。必须保留原始用户尺寸、数量和连接要求，后端独立验收不变。"
                   if structural_replan else "。请修正具体错误，不要无关重建；保留原始尺寸、数量和闭合要求。不能只提高confidence或修改断言来绕过检查。")
                + "若确有缺少的必要参数，请返回具体缺参澄清。"
                + previous_plan,
                mode=mode,
                **({} if structural_replan else {'repair_context':deepcopy(failed_attempt)}
                   if ((failed_attempt.get('construction_error') or {}).get('details') or {}).get('local_repair_scope')
                   else {'component_repair_context':deepcopy(failed_attempt)}
                   if ((failed_attempt.get('construction_error') or {}).get('details') or {}).get('affected_output_refs') else {}),
            )
            from .cad_local_repair import validate_local_repair
            local_validation=validate_local_repair(failed_attempt,interpretation)
            if local_validation['enforced']:
                interpretation['local_repair_validation']=local_validation
                if interpretation.get('status')=='ready' and local_validation['verified'] is not True:
                    interpretation={'schema':'cad.construction-interpretation-result.v1','status':'invalid',
                        'parser':interpretation.get('parser'),'provider_attempted':interpretation.get('provider_attempted'),
                        'rejected_plan':deepcopy(interpretation.get('plan')),'confidence':interpretation.get('confidence'),
                        'local_repair_validation':local_validation,
                        'error':{'code':'local_repair_scope_violation','message':'本次修复超出已确认的局部范围，未保存候选；请明确是否重新生成整体方案。'}}
            if confidence_only_repair(failed_attempt,interpretation):
                interpretation={
                    'schema':'cad.construction-interpretation-result.v1','status':'invalid',
                    'parser':interpretation.get('parser'),'provider_attempted':interpretation.get('provider_attempted'),
                    'confidence':interpretation.get('confidence'),'rejected_plan':deepcopy(interpretation.get('plan')),
                    'construction_request_recognized':True,
                    'error':{'code':'confidence_only_repair','message':'模型仅提高置信度，未修正原计划或获得新的用户约束，本次不保存候选。'}}
            interpretation["construction_retry_used"] = True
            construction_attempts.append(deepcopy(interpretation))
        if (interpretation.get("status") != "ready"
                and interpretation.get("provider_attempted")
                and not (project or {}).get("missing_parameters")
                and len((explicit_composition(
                    model_input.split("\n[CAD_REQUIREMENT_CONTRACT_SNAPSHOT.v1]", 1)[0]
                ) or {}).get("names") or []) > 1):
            # Local coordinate repair cannot always recover a wrong topology.
            # Trial separate model plans against the same immutable contract,
            # then apply the *full* source acceptance to each before use.
            from .cad_construction_interpreter import (
                interpret_construction_request, interpret_sketch_graph_candidates,
            )
            alternative_callback, alternative_state = self._cad_construction_model_callback(
                mode=mode, alternatives=True,
            )
            if alternative_callback is not None:
                alternatives = interpret_sketch_graph_candidates(model_input, alternative_callback)
                alternative_trials = []
                for candidate in (alternatives.get("candidate_set") or {}).get("candidates") or []:
                    plan = candidate.get("plan") if isinstance(candidate, dict) else None
                    if not isinstance(plan, dict):
                        continue
                    def fixed_plan(source: str, schema: dict[str, Any], *, value=plan) -> dict[str, Any]:
                        return {
                            "schema_version": "cad.construction-interpretation.v1",
                            "is_construction_request": True,
                            "plan": deepcopy(value),
                            "confidence": alternatives.get("confidence", 0),
                            "assumptions": alternatives.get("assumptions") or [],
                            "evidence_text": alternatives.get("evidence_text") or [],
                        }
                    trial = interpret_construction_request(
                        model_input, fixed_plan, force_structured_model=True,
                    )
                    alternative_trials.append({
                        "candidate_id": candidate.get("candidate_id"),
                        "status": trial.get("status"),
                        "acceptance_status": (trial.get("acceptance_summary") or {}).get("status"),
                        "error": deepcopy(trial.get("construction_error") or trial.get("error")),
                    })
                    if (trial.get("status") == "ready"
                            and (trial.get("acceptance_summary") or {}).get("status") == "passed"):
                        interpretation = trial
                        interpretation["provider_attempted"] = True
                        interpretation["provider"] = self.mode
                        interpretation["alternative_selection"] = {
                            "candidate_id": candidate.get("candidate_id"),
                            "trials": alternative_trials,
                        }
                        break
                if interpretation.get("status") != "ready":
                    interpretation["alternative_selection"] = {
                        "status": alternatives.get("status"),
                        "error": deepcopy(alternatives.get("error")),
                        "trials": alternative_trials,
                        "request_attempts": alternative_state.get("request_attempts", 0),
                    }
        interpretation["recovery"] = recovery_record(
            message,construction_attempts,max_repairs=2)
        if interpretation.get("status") != "ready":
            error = interpretation.get("error")
            error_message = (
                str(error.get("message") or "")
                if isinstance(error, dict)
                else ""
            )
            agent_audit.append(
                "cad_clarification_required" if interpretation.get("status") == "clarification_required" else "cad_construction_failed",
                "cad_construction",
                {"project_id": self._project_id_from_route(route)},
                {"ok": False, "message": error_message,
                 "status": interpretation.get("status"),
                 "error": deepcopy(error),
                 "provider_attempted": interpretation.get("provider_attempted", False),
                 "construction_retry_used": interpretation.get("construction_retry_used", False)},
            )
            model_clarification = interpretation.get("clarification")
            clarification = (
                model_clarification if isinstance(model_clarification, dict)
                else clarify_construction_request(message)
            )
            # Composite drawings are owned by the structured constructor. Do
            # not downgrade a failed model attempt into a single-shape
            # clarification that loses the component inventory.
            if has_compound_primitives(message) and not isinstance(model_clarification, dict):
                clarification = None
            # A grounded model plan can fail its confidence gate even for an
            # unfamiliar but explicitly named curve. That is a generation
            # failure, not evidence that the user omitted the shape.
            recognized_model_request = bool(
                (interpretation.get("construction_request_recognized")
                 or (interpretation.get("status") == "invalid"
                     and interpretation.get("provider_attempted")))
                and isinstance(clarification, dict)
                and clarification.get("recognized_size")
            )
            if recognized_model_request:
                clarification = {**clarification, "question_key": "construction_scope"}
            # 补齐完整需求（如"长宽均为5m"）时，结构化模型仍可能
            # low_confidence 触发澄清。先按落库同口径解析并落库，再读
            # 落库后的 requirements 判定完整性：shape/dimensions 任一完整
            # → 不再重复追问确认，由统一构造计划入口返回明确失败。
            selected_id = self._project_id_from_route(route)
            selected = get_creative_project_store().get(selected_id) if selected_id else None
            if (interpretation.get('model_required') and isinstance(selected,dict)
                    and not selected.get('missing_parameters')):
                # The requirements are complete, so keep the project in the
                # candidate-generation phase. A failed structured response is
                # retryable construction failure; it must not be rewritten as
                # a missing model or a new clarification round.
                return {**self._result(
                    '需求已完整，但本次结构化构造未返回可执行计划。需求已保留，请重试生成候选。',
                    self._empty_usage()),'ok':False,
                    'error_code': ('candidate_generation_failed'
                                   if interpretation.get('provider_attempted')
                                   else 'construction_model_unavailable'),
                    'project_id':selected_id,'project':selected,'retryable':True,
                    'construction_retry_available':True,
                    'construction_interpretation':interpretation}
            # A model failure must not turn confirmed requirements back into
            # missing parameters or overwrite dimensions supplied in follow-ups.
            if isinstance(selected, dict) and not selected.get("missing_parameters") and not model_clarification:
                persisted = selected
            else:
                persisted = self._persist_clarification_requirements(
                    raw_followup if clarification_followup else message, clarification, route
                )
            if persisted is not None:
                persisted_req = (
                    persisted.get("requirements")
                    if isinstance(persisted.get("requirements"), dict)
                    else {}
                )
                p_shape = str(persisted_req.get("shape") or "").strip()
                p_dims = (
                    persisted_req.get("dimensions")
                    if isinstance(persisted_req.get("dimensions"), dict)
                    else {}
                )
                has_complete_shape = bool(p_shape) and p_shape != "generic_2d_cad"
                has_complete_dims = bool(
                    p_dims.get("width_m") or p_dims.get("height_m")
                )
                confirmed_requirements = bool(
                    isinstance(selected, dict) and not selected.get("missing_parameters")
                )
                if (has_complete_shape or has_complete_dims or recognized_model_request or confirmed_requirements) and interpretation.get("provider_attempted") and not model_clarification:
                    # The one structured-plan attempt has already failed.
                    # Keep the confirmed requirements and surface a retryable
                    # failure; do not open a second geometry-producing path.
                    return {
                        **self._result(
                            "本次 CAD 构造失败：" + (error_message or "模型未返回有效构造计划")
                            .rstrip("。") + "。需求已保留，可重试生成。",
                            self._empty_usage(),
                        ),
                        "project_id": str(persisted["id"]),
                        "project": persisted,
                        "clarification_persisted": True,
                        "ok": False,
                        "error_code": ("candidate_generation_failed"
                                       if interpretation.get("provider_attempted")
                                       else "construction_model_unavailable"),
                        "next_action": "retry_candidate_generation",
                        "construction_interpretation": {
                            "recovery": deepcopy(interpretation.get("recovery")),
                            "alternative_selection": deepcopy(interpretation.get("alternative_selection")),
                            "status": interpretation.get("status"),
                            "error": deepcopy(error),
                            "provider_attempted": interpretation.get("provider_attempted", False),
                        },
                    }
            if not isinstance(clarification, dict):
                selected_id = self._project_id_from_route(route)
                selected = get_creative_project_store().get(selected_id) if selected_id else None
                return {
                    **self._result(
                        "本次 CAD 构造失败：模型未返回可执行的构造计划。需求已保留，可重试生成。",
                        self._empty_usage(),
                    ),
                    "ok": False,
                    "error_code": "candidate_generation_failed",
                    "retryable": True,
                    "construction_retry_available": True,
                    "project_id": selected_id,
                    "project": selected,
                    "construction_interpretation": {
                        "status": interpretation.get("status"),
                        "error": deepcopy(error) if isinstance(error, dict) else None,
                        "provider_attempted": bool(interpretation.get("provider_attempted")),
                    },
                }
            result = self._result(
                str(clarification["question"]) + (
                    "\n示例：" + str(clarification["suggested_prompt"])
                    if clarification.get("suggested_prompt") != clarification["question"] else ""
                ),
                self._empty_usage(),
            )
            # 澄清 = 红框（产品语义：澄清需要用户注意并回答，前端
            # isError: result['ok'] != true 渲染红框）。此处的 ok=False
            # 不代表"失败"，而是澄清标记；非澄清的正常回答保持 ok=True 绿框。
            result["ok"] = False
            result["clarification"] = clarification
            result["suggested_prompt"] = clarification["suggested_prompt"]
            result["construction_interpretation"] = {
                "status": interpretation.get("status"),
                "parser": interpretation.get("parser"),
                "error": deepcopy(error) if isinstance(error, dict) else None,
                "clarification_required": bool(
                    interpretation.get("clarification_required")
                ),
                "question_key": clarification["question_key"],
            }
            # 澄清结论已在上方落库（理解即落库）：已识别出的图形/尺寸/曲线
            # 要求写入 creative project，避免"已收到图形和尺寸"但下一轮确认
            # 时项目不存在、只能要求用户重新描述需求。项目 id 同时绑定到
            # 会话记忆，供后续"确认生成候选方案"按会话级 project_id 命中。
            if persisted is not None:
                result["project_id"] = str(persisted["id"])
                result["project"] = persisted
                result["clarification_persisted"] = True
            return result

        if clarification_followup:
            self._persist_clarification_requirements(raw_followup, {
                "question_key": "construction_scope", "recognized_size": True,
                "recognized_shape": str((project.get("requirements") or {}).get("shape") or "generic_2d_cad"),
            }, route)
        try:
            committed = commit_construction_interpretation(
                message,
                interpretation,
                store=get_creative_project_store(),
                owner_conversation_id=(get_creative_project_store().get(str(route.get("selected_project_id") or "")) or {}).get("owner_conversation_id") or self._conversation_id_from_route(route),
                project_id=(
                    self._project_id_from_route(route)
                    if route.get("stage") == "candidate_generation"
                    or route.get("decision_source") == "design_confirmation_followup"
                    else None
                ),
            )
        except ConstructionCommitError as exc:
            result = self._result(
                f"图纸已通过试算，但保存候选方案失败：{exc}",
                self._empty_usage(),
            )
            result["ok"] = False
            result["error_code"] = "candidate_persistence_failed"
            result["failure_category"] = "persistence_failure"
            result["retryable"] = True
            result["retry_limit"] = 3
            result["next_action"] = "retry_candidate_generation"
            result["cad_generation_failure"]={"category":"persistence_failure","automatic_retry":False,
                "background_job":None,"recovery":deepcopy(interpretation.get("recovery")),
                "retryable":True,"retry_limit":3}
            return result

        project = committed["project"]
        variant = committed["recommended_variant"]
        preview = self._preview_contract_from_points(
            variant.get("preview_paths"), namespace="design_variant"
        )
        count = int(committed["persisted_candidate_count"])
        acceptance = variant.get("acceptance_summary") or {}
        acceptance_text = (
            "需求独立验收已通过，已验证的尺寸、结构和语义证据随候选保存。"
            if acceptance.get("status") == "passed"
            and acceptance.get("review_required") is not True
            else "需求独立验收仍为部分覆盖，未覆盖的外观与语义要求请检查预览确认。"
        )
        message_text = (
            f"已生成 {count} 个候选方案，并完成几何执行校验。"
            + "右侧已显示评分最高的候选；原始构造计划、约束求解和几何断言已随候选保存。"
            + acceptance_text
            + "请选择满意方案后再进行路径规划，本次不会启动小车。"
        )
        composition = interpretation.get("composition_contract") or {}
        if composition.get("kind") == "named_components" and composition.get("gap_m") is not None:
            reference = "中心间距" if composition.get("gap_reference") == "center" else "边缘净距"
            message_text += f"本次间距按{reference}{composition['gap_m']:g}米校验。"
        tool_result = {
            "ok": True,
            "kind": "candidate_commit",
            "project_id": str(project["id"]),
            "project_status": str(project.get("status") or "designing"),
            "variant_id": str(variant["id"]),
            "preview_paths": preview,
            "persisted_candidate_count": count,
        }
        return {
            **self._result(
                message_text,
                self._empty_usage(),
                tool_results=[tool_result],
            ),
            "project_id": str(project["id"]),
            "project": project,
            "variants": list(project.get("variants") or []),
            "variant": variant,
            "preview_paths": preview,
            "drawing_json": self._drawing_payload({
                "geometries": list(variant.get("geometries") or []),
                "logical_objects": list(variant.get("logical_objects") or []),
                "topology": dict(variant.get("topology") or {}),
            }),
            "construction_commit": {
                "recovery": deepcopy(interpretation.get("recovery")),
                "schema": committed["schema"],
                "recommended_candidate_id": committed.get(
                    "recommended_candidate_id"
                ),
                "persisted_candidate_count": count,
            },
            "next_action": "select_design_variant",
        }

    def _persist_clarification_requirements(
        self,
        message: str,
        clarification: dict[str, Any],
        route: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Persist clarified-but-unconfirmed construction intent so a follow-up
        confirmation can bind to it (understanding must not be lost between
        turns). Reuses the project the conversation already references when it
        is still in a mutable state; otherwise creates a fresh clarifying
        project. The project id is bound to conversation memory."""
        question_key = str(clarification.get("question_key") or "shape")
        recognized_shape = str(clarification.get("recognized_shape") or "")
        recognized_size = bool(clarification.get("recognized_size"))
        # 用参数化器把原文里的具体尺寸和可生成形状提取出来，避免落库
        # 只有 recognized_size=True 而缺少 dimensions、确认时被生成器判为
        # "还缺少图形类型和关键尺寸"。
        inferred = parameterize_design(message)
        inferred_shape = str((inferred or {}).get("shape") or "").strip()
        inferred_dimensions = (inferred or {}).get("dimensions")
        from .cad_template_plan import template_covers_request
        declined_template = bool(recognize_drawing_template(message)
                and not template_covers_request({'name':message,'original_prompt':message,
                    'requirements':inferred or {}}, {}))
        if declined_template:
            # A declined template's default dimensions are not user facts.
            inferred_shape = "generic_2d_cad"
            inferred_dimensions = {}
        if not isinstance(inferred_dimensions, dict) or not inferred_dimensions:
            inferred_dimensions = {}
        if not inferred_dimensions and not declined_template:
            # 兜底：parameterize_design 对"宽不超过5米/最多3米/上限4米"这类
            # 范围性尺寸提取不到数值（实测爱心场景 dimensions={}），这里补
            # 一个上限尺寸提取，避免同类表达在确认闸仍被判缺关键尺寸。
            inferred_dimensions = _extract_upper_bound_dimensions(message)
        abstract_shape_words = {
            "轮廓", "曲线", "闭合", "线段", "折线", "图形", "多边形", "样条",
            "圆弧", "椭圆",
        }
        if inferred_shape:
            effective_shape = inferred_shape
        elif recognized_shape and recognized_shape not in abstract_shape_words:
            effective_shape = recognized_shape
        else:
            effective_shape = "generic_2d_cad"
        requirements: dict[str, Any] = {
            "shape": effective_shape,
            "construction_mode": "clarified_scope",
            "units": "m",
            "recognized_size": recognized_size,
        }
        reference = reference_contract(message)
        if reference is not None:
            requirements["structure_contract"] = reference
        if inferred_dimensions:
            requirements["dimensions"] = deepcopy(inferred_dimensions)
        if question_key == "construction_scope":
            missing: list[str] = []
            requirements["construction_scope"] = "awaiting_confirmation"
        elif question_key == "curve_constraints":
            missing = ["curve_constraints"]
            requirements["curve_constraints"] = "pending"
        elif question_key == "standard_spec" and inferred_dimensions.get("width_m") and inferred_dimensions.get("height_m"):
            missing = ["standard_spec"]
        elif question_key in {"size", "standard_spec"}:
            missing = ["dimensions"]
        else:
            missing = ["shape"]

        project_id = self._project_id_from_route(route)
        project = get_creative_project_store().get(project_id) if project_id else None
        if (project is not None and route.get("operation") == "create"
            and route.get("stage") != "candidate_generation"
            and route.get("decision_source") != "design_confirmation_followup"
            and local_creation_objects(message)
            and str(project.get("original_prompt") or "").strip() != message.strip()):
            # Selecting an old project is not authorization to replace its
            # requirements when the user explicitly describes a new drawing.
            project = None
        if (
            project is not None
            and str(project.get("status") or "")
            in {"draft", "clarifying", "ready_for_design"}
        ):
            old_requirements = project.get("requirements") or {}
            saved_followups = list(old_requirements.get("source_followups") or [])
            original = str(project.get("original_prompt") or message)
            if message != original and "\n最新已确认要求（" not in message and message not in saved_followups:
                saved_followups.append(message)
            requirements["source_followups"] = saved_followups
            requirements["requirement_ledger"] = project_requirement_ledger(
                original, saved_followups, missing=missing,
                previous=old_requirements.get("requirement_ledger"))
            updated = get_creative_project_store().update(
                str(project["id"]),
                requirements=requirements,
                missing_parameters=missing,
                event_message="澄清需求已落库，等待确认生成候选方案",
            )
            project = updated if updated is not None else project
        else:
            name = " ".join(message.split())[:40] or "未命名图形需求"
            requirements["requirement_ledger"] = project_requirement_ledger(message, missing=missing)
            project = get_creative_project_store().create(
                name,
                message,
                requirements=requirements,
                missing_parameters=missing,
            )
        if project is None:
            return None
        conversation_id = self._conversation_id_from_route(route)
        if conversation_id:
            conversation_memory.remember(
                conversation_id,
                message,
                {"project_id": str(project["id"]), "project": project},
                route=route,
            )
        return project

    @classmethod
    def _base_rectangular_motion_request_route(
        cls, message: str, mode: str
    ) -> dict[str, Any] | None:
        text = message.strip().lower().replace("*", "x").replace("×", "x")
        if cls.normalize_agent_mode(mode) != "base":
            return None
        if any(word in text for word in ("图纸", "cad", "喷墨", "划线", "标线", "设计")):
            return None
        if not any(
            word in text
            for word in (
                "控制小车", "让小车", "小车走", "底盘", "机器人走",
                "走一个", "走一圈", "运动演示",
            )
        ):
            return None
        square_size = re.search(
            r"(?:边长|边长为|side)\s*(?:为|是|[:：])?\s*"
            r"\d+(?:\.\d+)?\s*(?:米|m)?(?:的)?\s*(?:正方形|方形|square)",
            text,
        )
        rectangle_size = re.search(
            r"\d+(?:\.\d+)?\s*x\s*\d+(?:\.\d+)?\s*(?:米|m)?"
            r"(?:的)?\s*(?:矩形|长方形|正方形|rectangle|square)",
            text,
        )
        if square_size is None and rectangle_size is None:
            return None
        route = dict(cls.route_intent("控制小车运动", mode))
        route.update({
            "name": "motion_control",
            "tool_family": "motion",
            "operation": "execute",
            "stage": "confirmation",
            "next_step": "生成方形开环运动演示并等待用户确认",
            "confidence": 0.99,
            "api_required": False,
            "safety_confirmation_required": True,
            "context_requirements": ["online", "control_ready", "emergency_stopped"],
            "requested_data_domains": ["motion"],
            "decision_source": "base_rectangular_motion_request",
            "review_required": False,
            "clarification_required": False,
        })
        return route

    @classmethod
    def _constrained_addition_followup_route(
        cls,
        message: str,
        mode: str,
        history: list[dict[str, str]] | None,
    ) -> dict[str, Any] | None:
        if cls.normalize_agent_mode(mode) != "advanced":
            return None
        resolved = message
        parsed = parse_constrained_addition(resolved)
        if parsed is None and any(
            marker in message for marker in ("自己判断", "由你判断", "你判断", "大小合适", "自动确定")
        ):
            previous = next(
                (
                    str(item.get("content") or "")
                    for item in reversed(history or [])
                    if item.get("role") == "user" and item.get("content")
                ),
                "",
            )
            resolved = f"{previous}；{message}" if previous else message
            parsed = parse_constrained_addition(resolved)
        if parsed is None:
            return None
        route = dict(cls.route_intent("修改当前图纸候选方案", mode))
        route.update({
            "name": "drawing_design",
            "tool_family": "cad",
            "operation": "modify",
            "stage": "candidate_edit",
            "next_step": "求解几何约束并生成新候选方案",
            "confidence": 0.99,
            "decision_source": "constrained_cad_addition",
            "review_required": False,
            "clarification_required": False,
            "safety_confirmation_required": False,
            "resolved_message": resolved,
            "constraint_edit": parsed,
            "edit_intent": build_cad_edit_intent(resolved, parsed),
        })
        return route

    @classmethod
    def _base_circular_motion_request_route(
        cls, message: str, mode: str
    ) -> dict[str, Any] | None:
        text = message.strip().lower()
        if cls.normalize_agent_mode(mode) != "base":
            return None
        if any(word in text for word in ("图纸", "cad", "喷墨", "划线", "标线", "设计")):
            return None
        if not re.search(
            r"(?:半径|边长)\s*(?:为|是|[:：])?\s*"
            r"\d+(?:\.\d+)?\s*(?:米|m)?", text
        ) or not ("圆" in text or "circle" in text or re.search(r"画.{0,30}圆", text) or any(marker in text for marker in (
            "画圆", "圆走", "绕圆", "绕圈", "转圈", "圆周", "走一圈", "圆形运动",
        ))):
            return None
        route = dict(cls.route_intent("控制小车走一圈", mode))
        route.update({
            "name": "motion_control",
            "tool_family": "motion",
            "operation": "execute",
            "stage": "confirmation",
            "next_step": "使用低速默认参数生成圆周运动并等待确认",
            "confidence": 0.99,
            "api_required": False,
            "safety_confirmation_required": True,
            # Building a basic-mode preview must also work without a connected
            # rover. Readiness is validated when the user confirms execution.
            "context_requirements": [],
            "requested_data_domains": [],
            "decision_source": "base_circular_motion_request",
            "review_required": False,
            "clarification_required": False,
        })
        return route

    @classmethod
    def _base_polygonal_motion_request_route(
        cls, message: str, mode: str
    ) -> dict[str, Any] | None:
        """Keep simple closed-shape demos inside base mode."""
        text = message.strip().lower()
        if cls.normalize_agent_mode(mode) != "base":
            return None
        if any(word in text for word in ("图纸", "cad", "喷墨", "划线", "标线", "设计")):
            return None
        if not any(word in text for word in ("等边三角形", "正三角形", "equilateral triangle")):
            return None
        if not any(
            word in text
            for word in (
                "控制小车", "让小车", "小车走", "底盘", "机器人走",
                "走一个", "走一圈", "运动演示",
            )
        ):
            return None
        if re.search(
            r"(?:边长|side)\s*(?:为|是|[:：])?\s*\d+(?:\.\d+)?\s*(?:米|m)?",
            text,
        ) is None:
            return None
        route = dict(cls.route_intent("控制小车运动", mode))
        route.update({
            "name": "motion_control",
            "tool_family": "motion",
            "operation": "execute",
            "stage": "confirmation",
            "next_step": "生成三角形开环运动预览并等待用户确认",
            "confidence": 0.99,
            "api_required": False,
            "safety_confirmation_required": True,
            "context_requirements": ["online", "control_ready", "emergency_stopped"],
            "requested_data_domains": ["motion"],
            "decision_source": "base_polygonal_motion_request",
            "review_required": False,
            "clarification_required": False,
        })
        return route

    @classmethod
    def _base_motion_demo_followup_route(
        cls,
        message: str,
        mode: str,
        history: list[dict[str, str]] | None,
    ) -> dict[str, Any] | None:
        """Resolve short demo choices against the preceding motion request."""
        if cls.normalize_agent_mode(mode) != "base":
            return None
        normalized = re.sub(r"[\s，。！？、,.!?；;：:]+", "", message.strip().lower())
        choices = {
            "只进行运动演示", "只运动演示", "进行运动演示", "运动演示",
            "只做运动演示", "只演示", "不喷墨只运动", "不画线只运动",
        }
        if normalized not in choices:
            return None
        recent = [
            str(item.get("content") or "") for item in (history or [])[-8:]
            if item.get("content")
        ]
        context = "\n".join(recent)
        radius = re.search(
            r"半径\s*(?:为|是|[:：])?\s*(\d+(?:\.\d+)?)\s*(?:米|m)",
            context.lower(),
        )
        pair = re.search(
            r"(\d+(?:\.\d+)?)\s*[x×*]\s*(\d+(?:\.\d+)?)\s*(?:米|m)",
            context.lower(),
        )
        direction = (
            "顺时针" if "顺时针" in context else
            "逆时针" if "逆时针" in context else ""
        )
        if radius and any(word in context.lower() for word in ("圆", "circle")):
            resolved = f"底盘按半径 {float(radius.group(1)):g} 米的圆{direction}走一圈，只进行运动演示"
        elif pair and any(word in context.lower() for word in ("矩形", "长方形")):
            resolved = (
                f"底盘按 {float(pair.group(1)):g}×{float(pair.group(2)):g} 米矩形"
                "走一圈，只进行运动演示"
            )
        else:
            route = dict(cls.route_intent("运动演示", mode))
            route.update({
                "name": "motion_control", "tool_family": "motion",
                "operation": "execute", "stage": "requirements",
                "next_step": "补充演示路径形状和尺寸", "confidence": 0.95,
                "api_required": False, "safety_confirmation_required": True,
                "context_requirements": [], "requested_data_domains": [],
                "decision_source": "base_motion_demo_followup",
                "review_required": False, "clarification_required": True,
                "clarification_question": "请告诉我要演示的路径形状和尺寸，例如“半径 1 米的圆”。",
            })
            return route
        route = dict(cls.route_intent(resolved, mode))
        route.update({
            "name": "motion_control", "tool_family": "motion",
            "operation": "execute", "stage": "requirements",
            "next_step": "补充缺少的运动参数并等待确认", "confidence": 0.99,
            "api_required": False, "safety_confirmation_required": True,
            "context_requirements": [], "requested_data_domains": [],
            "decision_source": "base_motion_demo_followup",
            "review_required": False, "clarification_required": False,
            "resolved_message": resolved,
        })
        return route

    @classmethod
    def _circular_motion_parameter_followup_route(
        cls,
        message: str,
        mode: str,
        history: list[dict[str, str]] | None,
    ) -> dict[str, Any] | None:
        """Complete a circle-demo request across short conversational turns.

        Users commonly answer the follow-up with only "线速度 0.2m/s，半径 1m".
        Do not let the generic speed/status route consume that answer. Recover
        the numeric context from recent user turns and default the direction to
        counterclockwise so basic mode can immediately show a confirmation.
        """
        if cls.normalize_agent_mode(mode) != "base":
            return None
        recent = [
            str(item.get("content") or "")
            for item in (history or [])[-8:]
            if item.get("content")
        ]
        context = "\n".join([*recent, message])
        has_circle_context = any(
            marker in context for marker in ("画圆", "圆周", "绕圈", "转圈", "半径", "圆形")
        )
        has_circle_parameters = bool(
            re.search(
                r"半径\s*(?:为|是|[:：])?\s*"
                r"\d+(?:\.\d+)?\s*(?:米|m)?",
                context,
            )
            and re.search(r"\d+(?:\.\d+)?\s*(?:m/s|rad/s)", context)
        )
        if not has_circle_context or not has_circle_parameters:
            return None

        # Prefer the current user turn, then the latest user turns.  Assistant
        # replies may contain an example or a stale value such as "0m/s" and
        # must never override the value the user just entered.
        parameter_sources = [message]
        parameter_sources.extend(
            str(item.get("content") or "")
            for item in reversed(history or [])
            if item.get("role") == "user" and item.get("content")
        )

        def number(pattern: str) -> float | None:
            for source in parameter_sources:
                match = re.search(pattern, source.lower())
                if match:
                    return float(match.group(1))
            return None

        radius = number(
            r"半径\s*(?:为|是|[:：])?\s*"
            r"(\d+(?:\.\d+)?)\s*(?:米|m)?",
        )
        linear = number(
            r"(?:线速度\s*(?:为|是|[:：])?\s*)?(\d+(?:\.\d+)?)\s*m/s",
        )
        angular = number(
            r"(?:角速度\s*(?:为|是|[:：])?\s*)?(\d+(?:\.\d+)?)\s*rad/s",
        )
        if radius is None or (linear is None and angular is None):
            return None
        parts = [f"半径 {radius:g} 米"]
        if linear is not None:
            parts.append(f"线速度 {linear:g} m/s")
        if angular is not None:
            parts.append(f"角速度 {angular:g} rad/s")
        direction = (
            "顺时针" if "顺时针" in message or "顺时针" in context
            else "逆时针" if "逆时针" in message or "逆时针" in context
            else "逆时针"
        )
        resolved = "，".join(parts) + f"，{direction}走一圈"
        route = dict(cls.route_intent(resolved, mode))
        route.update({
            "name": "motion_control",
            "tool_family": "motion",
            "operation": "execute",
            "stage": "confirmation",
            "next_step": "生成圆周运动并等待用户确认",
            "confidence": 0.99,
            "api_required": False,
            "safety_confirmation_required": True,
            # Do not block a deterministic preview on live telemetry. The
            # confirmation/execution gate remains responsible for readiness.
            "context_requirements": [],
            "requested_data_domains": [],
            "decision_source": "circular_motion_parameter_followup",
            "review_required": False,
            "clarification_required": False,
            "resolved_message": resolved,
        })
        return route

    @classmethod
    def _drawing_layout_followup_route(
        cls, message: str, mode: str, history: list[dict[str, str]] | None
    ) -> dict[str, Any] | None:
        if cls.normalize_agent_mode(mode) != "advanced" or cls._physical_action_signals(message):
            return None
        text = message.strip().lower()
        # Layout words also occur in new-design requests such as
        # "规划两个并排相连的篮球场".  Those must create a project; this
        # follow-up route is reserved for editing an existing candidate.
        creation_markers = ("规划", "生成", "绘制", "创建", "新建", "画出", "画一个", "设计")
        edit_markers = ("修改", "调整", "移动", "平移", "挪动", "间距改", "间隔改", "扩大", "缩小")
        if (any(marker in text for marker in creation_markers) or local_creation_objects(message)) and not any(
            marker in text for marker in edit_markers
        ):
            return None
        layout = _template_layout_requirements(text)
        if not layout or not any(
            marker in text for marker in ("并排", "并列", "相邻", "排列", "间距", "连续")
        ):
            return None
        recent = (history or [])[-4:]
        if not any(
            item.get("role") == "user" and any(
                shape in str(item.get("content") or "").lower()
                for shape in ("篮球场", "羽毛球场", "车位", "停车位", "图纸", "图形")
            )
            for item in recent
        ) and not any(shape in text for shape in ("篮球场", "羽毛球场", "车位", "停车位", "图纸", "图形", "方案")):
            return None
        route = dict(cls.route_intent("设计图纸的排列方式和间距", mode))
        route.update({
            "operation": "modify",
            "confidence": 0.95,
            "decision_source": "drawing_layout_followup",
            "review_required": False,
            "clarification_required": False,
        })
        return route

    def _apply_project_addition_plan(
        self, message: str, route: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Execute explicit relative additions through CadConstructionPlan.

        The parent variant is read from the bound selection, retained byte for
        byte, and the added primitives undergo separate measured acceptance.
        """
        contract = route.get("relative_addition_contract")
        if not isinstance(contract, dict):
            return None
        project_id = self._project_id_from_route(route)
        store = get_creative_project_store()
        project = store.get(project_id) if project_id else None
        if not isinstance(project, dict):
            return {**self._result("当前项目不存在，请重新选择图形。", self._empty_usage()), "ok": False}
        project, parent, error = self._activate_preview_variant_for_edit(project, route)
        if error or not isinstance(parent, dict):
            return {**self._result(error or "当前候选不能作为修改基线。", self._empty_usage()), "ok": False}
        source = list(parent.get("geometries") or [])
        selection = route.get("drawing_selection") or {}
        if (str(selection.get("project_id") or "") != str(project["id"])
                or str(selection.get("variant_id") or "") != str(parent["id"])):
            return {**self._result("项目、版本与选区不一致，请重新选择图形。", self._empty_usage()), "ok": False}
        selected = {int(value) for value in selection.get("geometry_ids") or [] if str(value).isdigit()}
        actual = {int(item["id"]) for item in source if str(item.get("id", "")).isdigit()}
        if selected != actual:
            return {**self._result("相对整个图形的新增要求需选中完整图形。", self._empty_usage()), "ok": False}
        try:
            constructed = execute_relative_additions(source, contract)
        except (ValueError, TypeError) as exc:
            return {**self._result(f"新增部件构造失败：{exc}", self._empty_usage()), "ok": False}
        added = constructed["added"]
        parent_objects = deepcopy(parent.get("logical_objects") or [])
        new_objects = deepcopy(constructed["logical_objects"])
        existing_object_ids = {str(item.get("object_id")) for item in parent_objects if isinstance(item, dict)}
        for index, obj in enumerate(new_objects, 1):
            object_id = f"addition-{added[index - 1]['id']}"
            if object_id in existing_object_ids:
                return {**self._result("新增部件对象标识与原图冲突。", self._empty_usage()), "ok": False}
            obj["object_id"] = object_id
            obj["assembly_id"] = object_id
        canonical = {"shape": contract["shape"], "count": contract["count"],
                     "width_mm": contract["width_mm"], "height_mm": contract["height_mm"],
                     "offsets_mm": contract["offsets_mm"], "reference": contract["reference"],
                     "source_text": contract["source_text"]}
        edit = {
            "operation": "add_geometry", "geometry_ids": sorted(actual),
            "created_geometry_ids": [int(item["id"]) for item in added],
            "created_object_ids": [str(item["object_id"]) for item in new_objects],
            "project_id": str(project["id"]), "parent_variant_id": str(parent["id"]),
            "addition_contract": canonical,
        }
        try:
            edit_contract = build_cad_edit_contract(edit, source_text=message)
        except ValueError as exc:
            return {**self._result(f"新增部件编辑契约无效：{exc}", self._empty_usage()), "ok": False}
        updated = store.update(str(project["id"]), requirements={"additions": [canonical]},
                               event_message="已确认相对新增部件需求")
        if not isinstance(updated, dict):
            return {**self._result("新增需求未能保存，未创建候选。", self._empty_usage()), "ok": False}
        return self._persist_candidate_edit(
            updated, parent, constructed["geometries"], "按已确认关系新增图形",
            cad_edit_contract=edit_contract,
            logical_objects_override=parent_objects + new_objects,
            topology_override=deepcopy(parent.get("topology") or {}),
            independent_acceptance=constructed["acceptance"],
        )

    def _persist_candidate_edit(
        self, project: dict[str, Any], parent: dict[str, Any],
        geometries: list[dict[str, Any]], description: str,
        expected_quantity: int | None = None,
        instance_edit_operation: str | None = None,
        cad_edit_contract: dict[str, Any] | None = None,
        edit_preview: dict[str, Any] | None = None,
        logical_objects_override: list[dict[str, Any]] | None = None,
        topology_override: dict[str, Any] | None = None,
        independent_acceptance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Validate, preview and persist every candidate-edit result."""
        if independent_acceptance is not None and (
            independent_acceptance.get("status") != "passed"
            or any(check.get("passed") is not True for check in independent_acceptance.get("checks") or [])
        ):
            return {**self._result("新增部件未通过独立几何验收，未保存候选。", self._empty_usage()), "ok": False}
        if logical_objects_override is not None and topology_override is not None:
            logical_objects = deepcopy(logical_objects_override)
            topology = deepcopy(topology_override)
        else:
            logical_objects, topology = evolve_logical_graph_for_edit(
                list(parent.get("geometries") or []),
                geometries,
                list(parent.get("logical_objects") or []),
                dict(parent.get("topology") or {}),
                cad_edit_contract,
            )
        source = list(parent.get("geometries") or [])
        difference = build_geometry_diff(source, geometries)
        counts = difference.get("counts") or {}
        if not any(int(counts.get(key) or 0) for key in ("added", "removed", "modified")):
            output = {"ok": False, "message": "新方案与优化基准没有几何差异，未创建候选方案。"}
        else:
            assessment = score_design_variant(geometries)
            feasibility = assessment.get("feasibility") or {}
            stored_preview = preview_paths({"lines": geometries})
            preview = self._preview_contract_from_points(
                stored_preview, namespace="design_variant"
            )
            if feasibility.get("ok") is not True or not preview:
                output = {"ok": False, "message": "候选方案未通过几何或预览校验。"}
            else:
                shape = str(
                    (project.get("requirements") or {}).get("shape")
                    or (project.get("requirements") or {}).get("drawing_type")
                    or ""
                ).lower()
                instance_contract = template_instance_assessment(
                    geometries,
                    shape,
                    source_drawing=(
                        project.get("source_drawing")
                        if isinstance(project.get("source_drawing"), dict) else None
                    ),
                )
                generated_quantity = int(instance_contract.get("count") or 0)
                if (
                    expected_quantity is not None
                    and (
                        generated_quantity != expected_quantity
                        or instance_contract.get("authoritative") is not True
                    )
                ):
                    output = {
                        "ok": False,
                        "message": "实例数量修改与当前图纸不一致，候选方案未保存。",
                    }
                else:
                    edit_plan = (
                        build_cad_edit_plan(source, geometries, cad_edit_contract)
                        if isinstance(cad_edit_contract, dict) else None
                    )
                    resolved_preview = (
                        dict(edit_preview) if isinstance(edit_preview, dict) else None
                    )
                    machine_assertions = None
                    edit_repair = None
                    if isinstance(cad_edit_contract, dict) and isinstance(edit_plan, dict):
                        if resolved_preview is None:
                            resolved_preview = build_cad_edit_preview(
                                source, geometries, cad_edit_contract
                            )
                        machine_assertions = build_cad_machine_assertions(
                            source, geometries, cad_edit_contract,
                            edit_plan, resolved_preview,
                        )
                        if machine_assertions.get("verified") is not True:
                            (
                                geometries, edit_plan, resolved_preview,
                                machine_assertions, edit_repair,
                            ) = repair_cad_machine_assertions_once(
                                source, geometries, cad_edit_contract,
                                edit_plan, resolved_preview, machine_assertions,
                            )
                        if machine_assertions.get("verified") is not True:
                            output = {
                                "ok": False,
                                "message": "验证未通过，系统已停止修改并保留原图。",
                                "machine_assertions": machine_assertions,
                                "edit_repair": edit_repair,
                            }
                        else:
                            edit_acceptance = {
                                "status": "passed",
                                "review_required": False,
                                "authority": "backend_measured_geometry",
                                "source": "cad_edit_machine_assertions",
                                "verified_checks": len(machine_assertions.get("checks") or []),
                            }
                            if independent_acceptance is not None:
                                edit_acceptance["independent_addition"] = deepcopy(independent_acceptance)
                            persisted = persist_candidate_variant(
                                project_id=str(project["id"]),
                                name=f"{parent.get('name') or '候选方案'} · {description}",
                                geometries=geometries,
                                rationale=f"仅修改指定图元：{description}；其他图元保持不变。",
                                assessment=score_design_variant(geometries),
                                add_variant=get_creative_project_store().add_variant,
                                get_project=get_creative_project_store().get,
                                stored_preview=preview_paths({"lines": geometries}),
                                parent_variant_id=str(parent["id"]),
                                instance_contract=instance_contract,
                                expected_quantity=expected_quantity,
                                edit_contract=cad_edit_contract,
                                logical_objects=logical_objects,
                                topology=topology,
                                edit_plan=edit_plan,
                                edit_preview=resolved_preview,
                                machine_assertions=machine_assertions,
                                acceptance_summary=edit_acceptance,
                            )
                            output = {
                                **persisted,
                                **({"edit_repair": edit_repair}
                                   if isinstance(edit_repair, dict) else {}),
                            }
                    else:
                        output = persist_candidate_variant(
                            project_id=str(project["id"]),
                            name=f"{parent.get('name') or '候选方案'} · {description}",
                            geometries=geometries,
                            rationale=f"仅修改指定图元：{description}；其他图元保持不变。",
                            assessment=assessment,
                            add_variant=get_creative_project_store().add_variant,
                            get_project=get_creative_project_store().get,
                            stored_preview=stored_preview,
                            parent_variant_id=str(parent["id"]),
                            instance_contract=instance_contract,
                            expected_quantity=expected_quantity,
                            logical_objects=logical_objects,
                            topology=topology,
                        )
        if output.get("ok") is not True:
            result = self._result(str(output.get("message") or "图纸修改失败。"), self._empty_usage())
            result["ok"] = False
            return result
        updated = output["project"]
        return {
            **self._result(
                f"新候选方案已生成：{description}。原方案保留，可在方案区对比修改前后图形。",
                self._empty_usage(),
                tool_results=[self._tool_result_summary("persist_candidate_variant", output)],
            ),
            "project_id": str(project["id"]), "project": updated,
            "variants": updated["variants"], "variant": output["variant"],
            "preview_paths": output["preview_paths"],
            "drawing_json": self._drawing_payload({
                "geometries": geometries,
                "logical_objects": list(output["variant"].get("logical_objects") or []),
                "topology": dict(output["variant"].get("topology") or {}),
            }),
            "cad_revision": output["variant"].get("revision_contract"),
            **({"edit_preview": output["variant"].get("edit_preview")}
               if isinstance(output["variant"].get("edit_preview"), dict) else {}),
            **({"machine_assertions": output["variant"].get("machine_assertions")}
               if isinstance(output["variant"].get("machine_assertions"), dict)
               else {}),
            **({"edit_repair": output.get("edit_repair")}
               if isinstance(output.get("edit_repair"), dict) else {}),
            "next_action": "select_design_variant",
        }

    def _apply_constrained_candidate_addition(
        self, message: str, route: dict[str, Any]
    ) -> dict[str, Any] | None:
        constraint_edit = route.get("constraint_edit")
        if (
            route.get("decision_source") != "constrained_cad_addition"
            or not isinstance(constraint_edit, dict)
        ):
            return None
        project_id = self._project_id_from_route(route)
        project = get_creative_project_store().get(project_id) if project_id else None
        if project is None:
            result = self._result(
                "请先在候选方案中点击“继续优化”，再添加约束图形。",
                self._empty_usage(),
            )
            result["ok"] = False
            return result
        project, parent, activation_error = self._activate_preview_variant_for_edit(
            project, route
        )
        if activation_error:
            result = self._result(activation_error, self._empty_usage())
            result["ok"] = False
            return result
        if project.get("status") != "designing" or not isinstance(parent, dict):
            result = self._result(
                "请先选择当前候选方案并点击“继续优化”。",
                self._empty_usage(),
            )
            result["ok"] = False
            return result
        source_geometries = parent.get("geometries")
        if not isinstance(source_geometries, list) or not source_geometries:
            result = self._result("当前候选没有可修改的图形。", self._empty_usage())
            result["ok"] = False
            return result
        solved = add_symmetric_rectangles_on_circle(source_geometries)
        if solved.get("ok") is not True:
            result = self._result(
                str(solved.get("message") or "无法求解新增矩形约束。"),
                self._empty_usage(),
            )
            result["ok"] = False
            result["constraint_validation"] = solved.get("validation")
            return result

        added = list(solved.get("added_geometries") or [])
        geometries = list(solved.get("geometries") or [])
        if len(added) != 2 or len(geometries) != len(source_geometries) + 2:
            result = self._result(
                "约束求解结果不完整，未创建候选方案。", self._empty_usage()
            )
            result["ok"] = False
            return result
        parent_objects = [
            deepcopy(item) for item in parent.get("logical_objects") or []
            if isinstance(item, dict)
        ]
        target_geometry_id = int(solved["target_geometry_id"])
        target_object = next(
            (
                item for item in parent_objects
                if target_geometry_id in {
                    int(value) for value in item.get("geometry_refs") or []
                    if str(value).isdigit()
                }
            ),
            None,
        )
        if target_object is None:
            result = self._result(
                "当前篮球场缺少稳定逻辑对象，无法安全添加关联矩形。",
                self._empty_usage(),
            )
            result["ok"] = False
            return result
        target_object_id = str(target_object["object_id"])
        created_object_ids = ["constrained-rectangle-top", "constrained-rectangle-bottom"]
        existing_ids = {str(item.get("object_id") or "") for item in parent_objects}
        if any(value in existing_ids for value in created_object_ids):
            suffix = len([value for value in existing_ids if value.startswith("constrained-rectangle-")]) + 1
            created_object_ids = [
                f"constrained-rectangle-top-{suffix}",
                f"constrained-rectangle-bottom-{suffix}",
            ]
        logical_objects = [*parent_objects]
        for index, geometry in enumerate(added):
            vertices = geometry.get("vertices") or []
            xs = [float(point["x"]) for point in vertices]
            ys = [float(point["y"]) for point in vertices]
            logical_objects.append({
                "object_id": created_object_ids[index],
                "object_type": "rectangle",
                "label": "上方约束矩形" if index == 0 else "下方约束矩形",
                "geometry_refs": [int(geometry["id"])],
                "bounds": {
                    "min_x": min(xs), "min_y": min(ys),
                    "max_x": max(xs), "max_y": max(ys),
                },
                "confirmed": True,
                "confidence": 1.0,
            })
        topology = deepcopy(parent.get("topology") or {})
        topology.setdefault("schema_version", "cad.topology.v1")
        topology.setdefault("shared_geometries", [])
        relations = list(topology.get("relations") or [])
        relations.extend([
            {
                "source_object_id": created_object_ids[0],
                "target_object_id": target_object_id,
                "relation": "above",
            },
            {
                "source_object_id": created_object_ids[0],
                "target_object_id": target_object_id,
                "relation": "adjacent",
            },
            {
                "source_object_id": created_object_ids[1],
                "target_object_id": target_object_id,
                "relation": "below",
            },
            {
                "source_object_id": created_object_ids[1],
                "target_object_id": target_object_id,
                "relation": "adjacent",
            },
        ])
        topology["relations"] = relations
        created_geometry_ids = [int(item["id"]) for item in added]
        resolved_intent = build_cad_edit_intent(
            str(route.get("resolved_message") or message),
            {
                **constraint_edit,
                "geometry_ids": list(target_object.get("geometry_refs") or []),
                "logical_object_id": target_object_id,
                "created_geometry_ids": created_geometry_ids,
                "created_object_ids": created_object_ids,
                "constraint_kind": "symmetric_rectangles_on_circle",
                "solved_width_mm": float(solved["width_mm"]),
                "solved_height_mm": float(solved["height_mm"]),
            },
            inherited=route.get("edit_intent"),
        )
        edit = apply_intent_metadata({
            "operation": "add_constrained",
            "geometry_ids": list(target_object.get("geometry_refs") or []),
            "logical_object_id": target_object_id,
            "created_geometry_ids": created_geometry_ids,
            "created_object_ids": created_object_ids,
            "constraint_kind": "symmetric_rectangles_on_circle",
            "solved_width_mm": float(solved["width_mm"]),
            "solved_height_mm": float(solved["height_mm"]),
            "assumptions": list(constraint_edit.get("assumptions") or []),
            "project_id": str(project["id"]),
            "parent_variant_id": str(parent["id"]),
        }, resolved_intent)
        contract = build_cad_edit_contract(
            edit, source_text=str(route.get("resolved_message") or message)
        )
        width_m = float(solved["width_mm"]) / 1000.0
        height_m = float(solved["height_mm"]) / 1000.0
        result = self._persist_candidate_edit(
            project,
            parent,
            geometries,
            f"上下各新增 1 个 {width_m:.2f}×{height_m:.2f} 米约束矩形",
            cad_edit_contract=contract,
            logical_objects_override=logical_objects,
            topology_override=topology,
        )
        result.update({
            "constraint_plan": constraint_edit,
            "edit_intent": resolved_intent,
            "constraint_validation": solved["validation"],
            "cad_edit_contract": contract,
        })
        if result.get("ok") is True:
            result["message"] = (
                f"已生成新候选方案：上下各新增 1 个 {width_m:.2f}×{height_m:.2f} 米矩形，"
                "均与篮球场相接，外侧两个顶点已验证位于外圆上。原方案保持不变。"
            )
        return result

    def _apply_incremental_candidate_edit(
        self, message: str, route: dict[str, Any]
    ) -> dict[str, Any] | None:
        route = self._with_edit_domain(route)
        if route.get("edit_domain") != "candidate_variant":
            return None
        if route.get("decision_source") == "conversation_pending_cad_edit":
            from .cad_edit_session import binding_key, selection_binding
            context_binding = route.get("cad_context_binding")
            selection = route.get("drawing_selection")
            command = route.get("resolved_edit")
            current_key = binding_key(selection_binding(selection))
            command_key = binding_key(command.get("binding")) if isinstance(command, dict) else None
            project_id = str(route.get("selected_project_id") or "")
            variant_id = str(route.get("selected_variant_id") or "")
            if (not isinstance(context_binding, dict)
                    or current_key is None
                    or not isinstance(command, dict)
                    or str(command.get("project_id") or "") != project_id
                    or str(command.get("variant_id") or "") != variant_id
                    or command_key != current_key
                    or binding_key(context_binding.get("selection")) != current_key
                    or binding_key(context_binding.get("pending_command_binding")) != current_key):
                result = self._result(
                    "项目、版本、选区与待确认命令不一致，请重新选择图形后再确认。",
                    self._empty_usage(),
                )
                result.update({
                    "ok": False,
                    "error_code": "cad_context_binding_mismatch",
                    "clarification_required": True,
                })
                return result
        parse_message = (
            message + " 图形"
            if isinstance(route.get("drawing_selection"), dict)
            else message
        )
        edit = (
            deepcopy(route.get("resolved_edit"))
            if isinstance(route.get("resolved_edit"), dict)
            else parse_incremental_edit(parse_message)
        )
        if route.get("decision_source") not in {
            "incremental_cad_edit", "conversation_pending_cad_edit",
        } or edit is None:
            return None
        parsed_intent = build_cad_edit_intent(
            parse_message, edit, inherited=route.get("edit_intent")
        )
        project_id = self._project_id_from_route(route)
        project = get_creative_project_store().get(project_id) if project_id else None
        selection = route.get("drawing_selection")
        if project is None:
            result = self._result("请先选择要修改的图纸项目。", self._empty_usage())
            result["ok"] = False
            return result
        project, parent, activation_error = self._activate_preview_variant_for_edit(
            project, route
        )
        if activation_error:
            result = self._result(activation_error, self._empty_usage())
            result["ok"] = False
            return result
        if isinstance(selection, dict) and isinstance(parent, dict):
            selection_project_id = str(selection.get("project_id") or "")
            selection_variant_id = str(selection.get("variant_id") or "")
            if selection_project_id or selection_variant_id:
                if (
                    selection_project_id != str(project.get("id") or "")
                    or selection_variant_id != str(parent.get("id") or "")
                ):
                    result = self._result(
                        "当前点选目标属于旧的项目或候选方案，请重新点选后再修改。",
                        self._empty_usage(),
                    )
                    result["ok"] = False
                    return result
            else:
                source = project.get("source_drawing")
                if (
                    not isinstance(source, dict)
                    or selection.get("source_file_name") != source.get("file_name")
                    or parent.get("geometries") != source.get("geometries")
                ):
                    # A file-bound editor selection may only edit the matching
                    # imported source snapshot. Project-candidate selections
                    # are bound above by project and variant identity instead.
                    return None
        if project.get("status") != "designing" or not isinstance(parent, dict):
            result = self._result("请先在候选方案中点击“继续优化”，再指定要修改的图形。", self._empty_usage())
            result["ok"] = False
            return result
        # The parser represents an explicit phrase such as “整个篮球场” as
        # instances=all. Resolve that phrase against the current candidate
        # before target binding. Imported CAD commonly has no template
        # instances, so the complete drawing becomes an explicit geometry
        # target instead of being treated as an ambiguous request.
        if edit.get("instances") == "all":
            parent_geometries = [
                item for item in parent.get("geometries") or []
                if isinstance(item, dict) and isinstance(item.get("id"), int)
            ]
            grouped_instances = sorted({
                int(item["template_instance"])
                for item in parent_geometries
                if isinstance(item.get("template_instance"), int)
                and item["template_instance"] > 0
            })
            edit.pop("instances", None)
            if not grouped_instances:
                edit["geometry_ids"] = [int(item["id"]) for item in parent_geometries]
            elif len(grouped_instances) == 1:
                edit["instance"] = grouped_instances[0]
            else:
                # “整个” applies to the visible composite when several
                # stable instances are present; use their group center for
                # operations that support a combined target.
                edit["instances"] = grouped_instances
                if edit.get("operation") in {"scale", "rotate"}:
                    edit["pivot"] = "group_center"
        object_memory = route.get("object_memory")
        active_context = (
            object_memory.get("active_cad_context")
            if isinstance(object_memory, dict)
            else None
        )
        # Bind pronouns to the persisted selection only while the project and
        # candidate version still match.  A stale context must never guess.
        if (
            not isinstance(edit.get("logical_object_selector"), dict)
            and not edit.get("logical_object_id")
            and not edit.get("logical_object_ids")
            and isinstance(active_context, dict)
            and str(active_context.get("project_id") or "") == str(project.get("id") or "")
            and str(active_context.get("variant_id") or "") == str(parent.get("id") or "")
            and re.search(r"(?:它|这个(?:图形|对象|方案)|刚才(?:那个|的)|该(?:图形|对象))", message)
        ):
            remembered_ids = [
                str(value) for value in active_context.get("selected_object_ids") or []
                if value
            ]
            remembered_objects = [
                item for item in parent.get("logical_objects") or []
                if isinstance(item, dict)
                and str(item.get("object_id") or "") in set(remembered_ids)
            ]
            if remembered_objects and len(remembered_objects) == len(remembered_ids):
                edit["geometry_ids"] = sorted({
                    int(value)
                    for item in remembered_objects
                    for value in item.get("geometry_refs") or []
                    if str(value).isdigit()
                })
                if len(remembered_objects) == 1:
                    edit["logical_object_id"] = str(remembered_objects[0]["object_id"])
                else:
                    edit["logical_object_ids"] = [
                        str(item["object_id"]) for item in remembered_objects
                    ]
        # Geometry / instance level pronoun binding: "刚才选中的那条线",
        # "刚才修改的图形". Only fires when the edit carries no target at all
        # and the remembered context still matches the current candidate.
        if (
            not edit.get("geometry_ids")
            and not edit.get("instance")
            and not edit.get("instances")
            and not edit.get("logical_object_id")
            and not edit.get("logical_object_ids")
            and isinstance(active_context, dict)
            and str(active_context.get("project_id") or "") == str(project.get("id") or "")
            and str(active_context.get("variant_id") or "") == str(parent.get("id") or "")
            and re.search(r"(?:它|这个(?:图形|对象|方案)|刚才(?:那个|的|选中)|该(?:图形|对象)|选中的)", message)
        ):
            valid_geometry_ids = {
                int(item.get("id")) for item in parent.get("geometries") or []
                if isinstance(item, dict) and str(item.get("id", "")).isdigit()
            }
            remembered_geometry_ids = [
                int(value) for value in active_context.get("selected_geometry_ids") or []
                if isinstance(value, int) and value > 0
            ]
            if remembered_geometry_ids and all(
                value in valid_geometry_ids for value in remembered_geometry_ids
            ):
                edit["geometry_ids"] = sorted(set(remembered_geometry_ids))
            else:
                active_target = active_context.get("active_target")
                if (
                    isinstance(active_target, dict)
                    and active_target.get("scope") == "instance"
                    and str(active_target.get("variant_id") or "") == str(parent.get("id") or "")
                ):
                    remembered_instances = [
                        int(value) for value in active_target.get("ids") or []
                        if str(value).isdigit()
                    ]
                    valid_instances = {
                        item.get("template_instance") for item in parent.get("geometries") or []
                        if isinstance(item, dict) and isinstance(item.get("template_instance"), int)
                    }
                    if remembered_instances and all(
                        value in valid_instances for value in remembered_instances
                    ):
                        if len(remembered_instances) == 1:
                            edit["instance"] = remembered_instances[0]
                        else:
                            edit["instances"] = sorted(set(remembered_instances))
        selection_error = self._bind_incremental_selection(edit, route, parent)
        if selection_error is not None:
            result = self._result(selection_error, self._empty_usage())
            result["ok"] = False
            return result
        if edit.get("logical_object_id") or edit.get("logical_object_ids"):
            self._remember_active_cad_target(
                route,
                project_id=str(project.get("id") or ""),
                variant_id=str(parent.get("id") or ""),
                scope="logical_object",
                ids=[value for value in [edit.get("logical_object_id"), *(edit.get("logical_object_ids") or [])] if value],
                confidence=1.0,
                reason="canvas_logical_object",
            )
        elif edit.get("instance") is not None or edit.get("instances"):
            self._remember_active_cad_target(
                route,
                project_id=str(project.get("id") or ""),
                variant_id=str(parent.get("id") or ""),
                scope="instance",
                ids=[value for value in [edit.get("instance"), *(edit.get("instances") or [])] if isinstance(value, int)],
                confidence=1.0,
                reason="canvas_group",
            )
        elif edit.get("geometry_ids"):
            self._remember_active_cad_target(
                route,
                project_id=str(project.get("id") or ""),
                variant_id=str(parent.get("id") or ""),
                scope="geometry",
                ids=[int(value) for value in edit.get("geometry_ids") or [] if isinstance(value, int)],
                confidence=1.0,
                reason="canvas_entity",
            )
        logical_selector = edit.get("logical_object_selector")
        # 标准整场地模板（篮球场/羽毛球场）默认按实例（template_instance）解析，
        # 与旧链路一致；只有明确拆分共享边界时才走逻辑对象解析。
        _WHOLE_TEMPLATE_TYPES = {"basketball", "badminton"}
        if (
            isinstance(logical_selector, dict)
            and not (
                logical_selector.get("object_type") in _WHOLE_TEMPLATE_TYPES
                and edit.get("boundary_policy") != "split_shared"
            )
        ):
            resolution = resolve_logical_object_target(
                logical_selector, list(parent.get("logical_objects") or [])
            )
            if resolution.get("status") != "resolved":
                question = str(
                    resolution.get("question") or "不能唯一确定目标对象。"
                )
                result = self._result(question, self._empty_usage())
                result.update({
                    "ok": True,
                    "clarification_required": True,
                    "clarification_question": question,
                    "logical_target_resolution": resolution,
                })
                clarification = self._cad_target_clarification(
                    message,
                    edit,
                    parent.get("geometries") or [],
                    failure_message=question,
                )
                if clarification is not None:
                    result["target_clarification"] = clarification
                    result["preview_paths"] = list(
                        clarification.get("preview_paths") or []
                    )
                    result["variant"] = {
                        "id": parent.get("id"),
                        "file_name": parent.get("file_name"),
                        "logical_objects": list(parent.get("logical_objects") or []),
                    }
                    result["project_id"] = str(project.get("id") or "")
                return result
            resolved_object_ids = list(resolution.get("object_ids") or [])
            if not resolved_object_ids and resolution.get("object_id"):
                resolved_object_ids = [str(resolution["object_id"])]
            self._remember_active_cad_target(
                route,
                project_id=str(project.get("id") or ""),
                variant_id=str(parent.get("id") or ""),
                scope="logical_object",
                ids=resolved_object_ids,
                label=resolution.get("label"),
                confidence=float(resolution.get("confidence") or 1.0),
                reason=str(resolution.get("reason") or "resolved_logical_object"),
            )
            resolved_objects = [
                item for item in parent.get("logical_objects") or []
                if isinstance(item, dict)
                and str(item.get("object_id") or "") in set(resolved_object_ids)
            ]
            if (
                edit.get("operation") == "translate"
                and edit.get("coordinate_frame") == "vehicle"
                and re.search(r"(?:向|往)?(?:前|后)(?:方)?(?:平移|移动|挪动|挪|移)", message)
                and resolved_objects
                and all(item.get("object_type") == "parking_space" for item in resolved_objects)
            ):
                bounds = resolved_objects[0].get("bounds") or {}
                width = float(bounds.get("max_x", 0.0)) - float(bounds.get("min_x", 0.0))
                height = float(bounds.get("max_y", 0.0)) - float(bounds.get("min_y", 0.0))
                distance = math.hypot(float(edit.get("dx_mm") or 0.0),
                                      float(edit.get("dy_mm") or 0.0))
                direction = -1.0 if float(edit.get("dx_mm") or 0.0) < 0 else 1.0
                if height >= width:
                    edit["dx_mm"], edit["dy_mm"] = 0.0, direction * distance
                else:
                    edit["dx_mm"], edit["dy_mm"] = direction * distance, 0.0
                edit["coordinate_frame"] = "drawing"
                edit.setdefault("assumptions", []).append("车位前后方向按车位长轴解释")
            conflict = logical_object_topology_conflict(
                resolved_object_ids, dict(parent.get("topology") or {})
            )
            boundary_policy = edit.get("boundary_policy")
            if conflict is not None and boundary_policy != "split_shared":
                result = self._result(conflict["question"], self._empty_usage())
                result.update({
                    "ok": True,
                    "clarification_required": True,
                    "clarification_question": conflict["question"],
                    "logical_target_resolution": resolution,
                    "topology_conflict": conflict,
                })
                return result
            if conflict is not None and boundary_policy == "split_shared":
                if any(len(item.get("geometry_refs") or []) < 4 for item in resolved_objects):
                    question = (
                        "当前候选仍是旧版总外框结构，不能完整拆分单个车位。"
                        "请重新生成一次标准车位候选，再执行独立移动。"
                    )
                    result = self._result(question, self._empty_usage())
                    result.update({
                        "ok": True,
                        "clarification_required": True,
                        "clarification_question": question,
                        "logical_target_resolution": resolution,
                        "topology_conflict": conflict,
                    })
                    return result
                edit["shared_geometry_ids"] = list(conflict.get("shared_geometry_ids") or [])
                edit["logical_object_ids"] = resolved_object_ids
            edit["geometry_ids"] = list(resolution.get("geometry_ids") or [])
            edit["target_resolution"] = deepcopy(resolution)
            if len(resolved_object_ids) == 1:
                edit["logical_object_id"] = resolved_object_ids[0]
                edit.pop("logical_object_ids", None)
            else:
                edit["logical_object_ids"] = resolved_object_ids
                edit.pop("logical_object_id", None)
            edit.pop("instance", None)
            edit.pop("instances", None)
            edit.pop("logical_object_selector", None)
        from .cad_object_constraints import compile_object_constraint
        edit, constraint_error = compile_object_constraint(
            edit, parent.get("logical_objects") or [], parent.get("geometries") or [], parse_message
        )
        if constraint_error:
            result = self._result(constraint_error, self._empty_usage())
            result.update(ok=True, clarification_required=True, clarification_question=constraint_error)
            return result
        if edit.get('_measured_relation_satisfied'):
            result = self._result(str(edit['_measured_relation_satisfied']), self._empty_usage())
            result.update(ok=True, project_id=project['id'], source_variant_id=parent['id'],
                          cad_edit_outcome='already_satisfied', variant_saved=False,
                          relation_verification={'verified': True, 'authority': 'backend_measured_geometry'})
            return result
        resolved_intent = build_cad_edit_intent(
            parse_message, edit, inherited=parsed_intent
        )
        clarification = cad_edit_intent_clarification(resolved_intent)
        if clarification is not None:
            result = self._result(clarification, self._empty_usage())
            result.update({
                "ok": True,
                "clarification_required": True,
                "clarification_question": clarification,
                "edit_intent": resolved_intent,
            })
            return result
        geometries, error = edit_candidate_geometries(parent.get("geometries") or [], edit)
        if geometries is None:
            result = self._result(error or "不能确定本次修改。", self._empty_usage())
            result["ok"] = False
            clarification = self._cad_target_clarification(
                message,
                edit,
                parent.get("geometries") or [],
                failure_message=str(error or "不能确定本次修改目标。"),
            )
            if clarification is not None:
                result["target_clarification"] = clarification
                result["preview_paths"] = list(
                    clarification.get("preview_paths") or []
                )
                result["variant"] = {
                    "id": parent.get("id"),
                    "file_name": parent.get("file_name"),
                    "logical_objects": list(parent.get("logical_objects") or []),
                }
                result["project_id"] = str(project.get("id") or "")
                result["ok"] = True
            if any(marker in str(error or "") for marker in (
                "请明确", "请说明", "请重新选择", "请重新点选", "请在右侧",
                "位置相同", "无法判断", "不能直接作为图纸施工方向",
            )):
                result["clarification_required"] = True
                result["clarification_question"] = str(error)
            return result
        geometry_ids = edit.get("geometry_ids")
        instances = edit.get("instances")
        resulting_instance_ids = {
            int(value)
            for item in geometries
            if isinstance(item, dict)
            and isinstance((value := item.get("template_instance")), int)
            and value > 0
        }
        instance = edit.get("instance") or (
            instances[0] if isinstance(instances, list) and instances
            else next(iter(resulting_instance_ids), None)
        )
        target_label = (
            "、".join(str(value) for value in instances)
            if isinstance(instances, list) and instances else str(instance)
        )
        descriptions = {
            "translate": f"第 {target_label} 个图形平移",
            "resize": f"第 {instance} 个图形{edit.get('dimension')}调整",
            "rotate": (
                f"第 {target_label} 个图形"
                f"{'分别绕各自中心' if edit.get('pivot') == 'each_instance_center' else '作为整体绕组合中心' if edit.get('pivot') == 'group_center' else ''}"
                f"旋转 {edit.get('angle_degrees')} 度"
            ),
            "scale": (
                f"第 {target_label} 个图形"
                f"{'分别以各自中心' if edit.get('pivot') == 'each_instance_center' else '以组合中心整体' if edit.get('pivot') == 'group_center' else '以自身中心'}"
                f"等比例缩放到 {edit.get('factor')} 倍"
            ),
            "duplicate": f"复制第 {instance} 个图形为第 {edit.get('new_instance')} 个",
            "align": f"第 {instance} 个图形与第 {edit.get('reference_instance')} 个{edit.get('alignment')}对齐",
            "mirror": (
                f"第 {target_label} 个图形"
                f"{'左右' if edit.get('mirror_axis') == 'vertical' else '上下'}镜像"
                f"{'，保留原图' if edit.get('keep_source', True) else '，不保留原图'}"
            ),
            "offset": (
                f"第 {target_label} 个图形"
                f"{'向内' if edit.get('offset_side') == 'inside' else '向外'}偏移 "
                f"{edit.get('distance_mm')} 毫米"
            ),
            "array": (
                f"第 {target_label} 个图形"
                f"{'矩形阵列' if edit.get('array_mode') == 'rectangular' else '环形阵列'}"
            ),
            "constraint": (
                f"第 {instance} 个图形与第 {edit.get('reference_instance')} 个图形"
                f"{'同心' if edit.get('constraint_type') == 'concentric' else edit.get('constraint_type')}约束"
            ),
            "delete": f"删除第 {target_label} 个图形",
            "retain": f"仅保留第 {target_label} 个图形",
        }
        if isinstance(geometry_ids, list) and geometry_ids:
            selected_label = "、".join(str(value) for value in geometry_ids)
            descriptions.update({
                "translate": f"选中图元 {selected_label} 平移",
                "resize": f"选中图元 {selected_label} 的{edit.get('dimension')}调整",
                "rotate": f"选中图元 {selected_label} 旋转 {edit.get('angle_degrees')} 度",
                "scale": f"选中图元 {selected_label} 等比例缩放到 {edit.get('factor')} 倍",
                "delete": f"删除选中图元 {selected_label}",
                "retain": f"仅保留选中图元 {selected_label}",
                "duplicate":f"复制选中图形 {selected_label}",
                "mirror":f"镜像选中图形 {selected_label}",
                "offset":f"等距偏移选中图形 {selected_label}",
                "array":f"阵列选中图形 {selected_label}",
            })
        parent_groups = {
            item.get("template_instance") for item in parent.get("geometries") or []
            if isinstance(item, dict)
            and isinstance(item.get("template_instance"), int)
            and item.get("template_instance") > 0
        }
        resulting_groups = resulting_instance_ids
        changes_quantity = (
            edit["operation"] in {"duplicate", "delete", "retain", "mirror", "offset", "array"}
            and (not isinstance(geometry_ids, list)
                 or parent_groups != resulting_groups)
        )
        edit["project_id"] = str(project["id"])
        edit["parent_variant_id"] = str(parent["id"])
        resolved_intent = build_cad_edit_intent(
            parse_message, edit, inherited=resolved_intent
        )
        edit = apply_intent_metadata(edit, resolved_intent)
        contract = build_cad_edit_contract(edit, source_text=message)
        previous_contract = (
            object_memory.get("last_cad_edit")
            if isinstance(object_memory, dict) else None
        )
        counterfactual_guard = validate_counterfactual_followup(
            previous_contract if isinstance(previous_contract, dict) else None,
            contract,
            str(route.get("user_message") or message),
        )
        if counterfactual_guard["verified"] is not True:
            reason = "本轮指令与上一轮修改存在未明确的变化。请明确要修改的对象或参数。"
            result = self._result(reason, self._empty_usage())
            result.update({
                "ok": True,
                "clarification_required": True,
                "clarification_question": reason,
                "counterfactual_guard": counterfactual_guard,
                "rollback_evidence": build_rejection_rollback_evidence(
                    parent.get("geometries") or [], reason
                ),
            })
            return result
        grounding = dict(contract.get("intent_grounding") or {})
        grounding["counterfactual_guard"] = counterfactual_guard
        if isinstance(route.get('cad_edit_session'),dict):
            grounding['source_turns']=list(route['cad_edit_session'].get('source_turns') or [])
        contract["intent_grounding"] = grounding
        cad_preflight = build_cad_edit_preflight(
            parent.get("geometries") or [], geometries, contract
        )
        if not cad_preflight["ready"]:
            failed_checks = [
                item["detail"] for item in cad_preflight["checks"]
                if item.get("ok") is not True
            ]
            result = self._result(
                "图纸修改执行前检查未通过：" + "；".join(failed_checks),
                self._empty_usage(),
            )
            reason = str(result["message"])
            result.update({
                "ok": False,
                "cad_preflight": cad_preflight,
                "rollback_evidence": build_rejection_rollback_evidence(
                    parent.get("geometries") or [], reason
                ),
            })
            return result
        edit_preview = build_cad_edit_preview(
            parent.get("geometries") or [],
            geometries,
            contract,
            preflight=cad_preflight,
            target_resolution=edit.get("target_resolution"),
        )
        if cad_preflight.get("already_satisfied"):
            result = self._result("当前图形已满足该约束，无需修改；继续使用当前方案。", self._empty_usage())
            result.update({"project_id": str(project["id"]), "project": project,
                           "variant": parent, "preview_paths": geometry_preview_paths({"lines": geometries}),
                           "cad_edit_outcome": "already_satisfied", "variant_saved": False,
                           "cad_edit_contract": contract, "cad_preflight": cad_preflight,
                           "edit_intent": resolved_intent, "edit_preview": edit_preview})
            return result
        if cad_preflight["requires_confirmation"]:
            pending = self._register_pending(
                "apply_cad_candidate_edit",
                {
                    "project_id": str(project["id"]),
                    "parent_variant_id": str(parent["id"]),
                    "parent_geometry_sha256": cad_preflight["source_fingerprint"],
                    "edit_contract": contract,
                    "edit_preview": edit_preview,
                },
                mode="advanced",
            )
            pending["preflight"] = {
                "ready": True,
                "checks": cad_preflight["checks"],
            }
            pending["cad_preflight"] = cad_preflight
            pending["edit_preview"] = edit_preview
            pending["preview_paths"] = geometry_preview_paths({"lines": geometries})
            pending["cancel_preview_paths"] = geometry_preview_paths({
                "lines": parent.get("geometries") or []
            })
            pending["diff_preview_paths"] = build_diff_preview_paths(
                cad_preflight["diff"]
            )
            reason = "；".join(cad_preflight["risk_reasons"])
            result = self._result(
                f"本次图纸修改影响较大：{reason}。请核对右侧预览后确认应用；原候选不会被覆盖。",
                self._empty_usage(),
                pending,
            )
            result.update({
                "cad_edit_contract": contract,
                "edit_intent": resolved_intent,
                "cad_preflight": cad_preflight,
                "edit_preview": (
                    result.get("variant", {}).get("edit_preview")
                    if isinstance(result.get("variant"), dict)
                    else edit_preview
                ) or edit_preview,
                "preview_paths": pending["preview_paths"],
                "diff_preview_paths": pending["diff_preview_paths"],
                "next_action": "confirm_cad_edit",
            })
            return result
        result = self._persist_candidate_edit(
            project, parent, geometries, descriptions[edit["operation"]],
            expected_quantity=len(resulting_instance_ids)
            if changes_quantity else None,
            instance_edit_operation=edit["operation"] if changes_quantity else None,
            cad_edit_contract=contract,
            edit_preview=edit_preview,
        )
        if result.get("ok") is not False:
            result["cad_edit_contract"] = contract
            result["edit_intent"] = resolved_intent
            result["cad_preflight"] = cad_preflight
            result["edit_preview"] = (
                result.get("variant", {}).get("edit_preview")
                if isinstance(result.get("variant"), dict)
                else edit_preview
            ) or edit_preview
            result["cad_edit_command"] = {
                "schema": (
                    "cad.geometry_edit.v1"
                    if isinstance(geometry_ids, list) and geometry_ids
                    else "cad.instance_edit.v1"
                ),
                "operation": edit["operation"],
                **({"target_geometry_ids": geometry_ids}
                   if isinstance(geometry_ids, list) and geometry_ids
                   else {"target_instance_ids": instances}
                   if isinstance(instances, list) and instances
                   else {"target_instance_id": instance}),
                **({"reference_instance_id": edit["reference_instance"]}
                   if edit.get("reference_instance") is not None else {}),
                **({"created_instance_id": edit["new_instance"]}
                   if edit.get("new_instance") is not None else {}),
                "parameters": {
                    key: value for key, value in edit.items()
                    if key not in {
                        "operation", "instance", "instances", "geometry_ids",
                        "reference_instance", "new_instance",
                    }
                },
            }
        return result

    def _apply_incremental_candidate_chain(
        self, message: str, route: dict[str, Any]
    ) -> dict[str, Any] | None:
        edits = route.get("edit_chain")
        if (
            route.get("decision_source") != "incremental_cad_edit_chain"
            or not isinstance(edits, list)
        ):
            return None
        project_id = self._project_id_from_route(route)
        project = get_creative_project_store().get(project_id) if project_id else None
        activation_error = None
        parent = None
        if isinstance(project, dict):
            project, parent, activation_error = self._activate_preview_variant_for_edit(
                project, route
            )
        if activation_error:
            result = self._result(activation_error, self._empty_usage())
            result["ok"] = False
            return result
        if (
            not isinstance(project, dict)
            or project.get("status") != "designing"
            or not isinstance(parent, dict)
        ):
            result = self._result(
                "请先选择当前候选并点击“继续优化”，再执行复合修改。",
                self._empty_usage(),
            )
            result["ok"] = False
            return result
        source = parent.get("geometries")
        if not isinstance(source, list) or not source:
            result = self._result("当前候选没有可修改的图形。", self._empty_usage())
            result["ok"] = False
            return result
        prepared: list[dict[str, Any]] = []
        target_resolutions: list[dict[str, Any]] = []
        for raw in edits:
            if not isinstance(raw, dict):
                return None
            edit = deepcopy(raw)
            if route.get('drawing_selection'):
                selection_error=self._bind_incremental_selection(edit,route,parent)
                if selection_error:
                    return {**self._result(selection_error,self._empty_usage()),'ok':False}
            step_intent=build_cad_edit_intent(message,edit)
            question=cad_edit_intent_clarification(step_intent)
            if question and question!='请在右侧图纸中点选要修改的对象，或说明是第几个图形。':
                return {**self._result(question,self._empty_usage()),'ok':True,
                    'clarification_required':True,'clarification_question':question,'edit_intent':step_intent}
            resolution = resolve_cad_target(edit, source)
            if resolution.get("status") != "resolved":
                question = str(resolution.get("question") or "不能唯一确定复合修改目标。")
                result = self._result(question, self._empty_usage())
                result.update({
                    "ok": True, "clarification_required": True,
                    "clarification_question": question,
                    "target_resolution": resolution,
                })
                clarification = self._cad_target_clarification(
                    message, edit, source, failure_message=question,
                )
                if clarification is not None:
                    result["target_clarification"] = clarification
                    result["preview_paths"] = list(
                        clarification.get("preview_paths") or []
                    )
                    result["variant"] = {
                        "id": parent.get("id"),
                        "file_name": parent.get("file_name"),
                        "logical_objects": list(parent.get("logical_objects") or []),
                    }
                    result["project_id"] = str(project.get("id") or "")
                return result
            bind_resolved_target(edit, resolution)
            self._remember_active_cad_target(
                route,
                project_id=str(project["id"]),
                variant_id=str(parent["id"]),
                scope=str(resolution.get("scope") or "instance"),
                ids=(
                    list(resolution.get("instance_ids") or [])
                    if resolution.get("scope") == "instance"
                    else list(resolution.get("geometry_ids") or [])
                    if resolution.get("scope") == "geometry"
                    else [value for value in [resolution.get("object_id"), *(resolution.get("object_ids") or [])] if value]
                ),
                label=resolution.get("label"),
                confidence=float(resolution.get("confidence") or 1.0),
                reason=str(resolution.get("reason") or "resolved_chain_target"),
            )
            target_resolutions.append(deepcopy(resolution))
            edit["project_id"] = str(project["id"])
            edit["parent_variant_id"] = str(parent["id"])
            prepared.append(edit)
        try:
            contract = build_cad_edit_chain_contract(prepared, source_text=message)
        except (TypeError, ValueError) as error:
            result = self._result(f"复合修改协议无效：{error}", self._empty_usage())
            result["ok"] = False
            return result
        chain_guard = validate_counterfactual_followup(
            None,
            contract,
            str(route.get("user_message") or message),
        )
        chain_grounding = dict(contract.get("intent_grounding") or {})
        chain_grounding["counterfactual_guard"] = chain_guard
        if isinstance(route.get('cad_edit_session'),dict):
            chain_grounding['source_turns']=list(route['cad_edit_session'].get('source_turns') or [])
        contract["intent_grounding"] = chain_grounding
        geometries, error, replay = replay_cad_edit_chain(source, contract)
        if geometries is None:
            reason = error or "复合修改无法执行。"
            result = self._result(reason, self._empty_usage())
            result.update({
                "ok": False,
                "rollback_evidence": build_rejection_rollback_evidence(source, reason),
                "chain_replay": replay,
            })
            return result
        preflight = build_cad_edit_preflight(source, geometries, contract)
        if not preflight["ready"]:
            details = "；".join(
                item["detail"] for item in preflight["checks"]
                if item.get("ok") is not True
            )
            reason = "复合修改执行前检查未通过：" + details
            result = self._result(reason, self._empty_usage())
            result.update({
                "ok": False, "cad_preflight": preflight,
                "rollback_evidence": build_rejection_rollback_evidence(source, reason),
                "chain_replay": replay,
            })
            return result
        edit_preview = build_cad_edit_preview(
            source,
            geometries,
            contract,
            preflight=preflight,
            target_resolution=target_resolutions,
        )
        if preflight["requires_confirmation"]:
            pending = self._register_pending(
                "apply_cad_candidate_edit",
                {
                    "project_id": str(project["id"]),
                    "parent_variant_id": str(parent["id"]),
                    "parent_geometry_sha256": preflight["source_fingerprint"],
                    "edit_contract": contract,
                    "edit_preview": edit_preview,
                },
                mode="advanced",
            )
            pending["preflight"] = {
                "ready": True,
                "checks": preflight["checks"],
            }
            pending["cad_preflight"] = preflight
            pending["edit_preview"] = edit_preview
            pending["preview_paths"] = geometry_preview_paths({"lines": geometries})
            pending["cancel_preview_paths"] = geometry_preview_paths({"lines": source})
            pending["diff_preview_paths"] = build_diff_preview_paths(
                preflight["diff"]
            )
            reason = "；".join(preflight["risk_reasons"])
            result = self._result(
                f"本次复合修改影响较大：{reason}。请核对右侧预览后确认应用；"
                "确认时会从当前候选重新执行全部步骤，原候选不会被覆盖。",
                self._empty_usage(),
                pending,
            )
            result.update({
                "cad_edit_contract": contract,
                "cad_preflight": preflight,
                "edit_preview": (
                    result.get("variant", {}).get("edit_preview")
                    if isinstance(result.get("variant"), dict)
                    else edit_preview
                ) or edit_preview,
                "chain_replay": replay,
                "edit_chain": {
                    "schema": "cad.edit-chain.v1",
                    "atomic": True,
                    "step_count": len(prepared),
                    "steps": contract["chain_steps"],
                },
                "preview_paths": pending["preview_paths"],
                "diff_preview_paths": pending["diff_preview_paths"],
                "next_action": "confirm_cad_edit",
            })
            return result
        description = "按顺序完成 " + "、".join(
            {
                "translate": "平移", "rotate": "旋转", "scale": "缩放",
                "resize": "尺寸调整", "align": "对齐",
            }.get(str(item.get("operation") or ""), "修改")
            for item in prepared
        )
        result = self._persist_candidate_edit(
            project, parent, geometries, description,
            cad_edit_contract=contract,
            edit_preview=edit_preview,
        )
        if result.get("ok") is not False:
            result.update({
                "cad_edit_contract": contract,
                "cad_preflight": preflight,
                "edit_preview": (
                    result.get("variant", {}).get("edit_preview")
                    if isinstance(result.get("variant"), dict)
                    else edit_preview
                ) or edit_preview,
                "chain_replay": replay,
                "edit_chain": {
                    "schema": "cad.edit-chain.v1",
                    "atomic": True,
                    "step_count": len(prepared),
                    "steps": contract["chain_steps"],
                },
            })
        return result

    @staticmethod
    def _cad_target_reply(edit: dict[str, Any], instance_id: int) -> str | None:
        """Build an explicit replayable instruction for one chosen instance."""
        prefix = f"第{instance_id}个图形"
        operation = str(edit.get("operation") or "")
        if operation == "translate":
            dx, dy = edit.get("dx_mm"), edit.get("dy_mm")
            if not isinstance(dx, (int, float)) or not isinstance(dy, (int, float)):
                return None
            parts = []
            if dx:
                parts.append(f"向{'右' if dx > 0 else '左'}移动{abs(dx):g}毫米")
            if dy:
                parts.append(f"向{'上' if dy > 0 else '下'}移动{abs(dy):g}毫米")
            return f"{prefix}{'并'.join(parts)}" if parts else None
        if operation == "rotate":
            angle = edit.get("angle_degrees")
            if not isinstance(angle, (int, float)) or angle == 0:
                return None
            direction = "顺时针" if angle < 0 else "逆时针"
            return f"{prefix}绕自身中心{direction}旋转{abs(angle):g}度"
        if operation == "scale":
            factor = edit.get("factor")
            if not isinstance(factor, (int, float)) or factor <= 0:
                return None
            return f"{prefix}以自身中心等比例缩放到{factor:g}倍"
        if operation == "resize":
            dimension, value = edit.get("dimension"), edit.get("value_mm")
            if dimension not in {"宽度", "高度", "半径"} or not isinstance(value, (int, float)):
                return None
            return f"{prefix}的{dimension}改为{value:g}毫米"
        if operation == "delete":
            return f"删除{prefix}"
        if operation == "retain":
            return f"只保留{prefix}"
        return None

    def _remember_active_cad_target(
        self,
        route: dict[str, Any],
        *,
        project_id: str,
        variant_id: str,
        scope: str,
        ids: list[Any],
        label: Any = None,
        confidence: float = 1.0,
        reason: str = "resolved_target",
    ) -> None:
        """Persist a confirmed CAD target so follow-up pronouns bind to it."""
        conversation_id = self._conversation_id_from_route(route)
        if not conversation_id:
            return
        conversation_memory.set_active_cad_target(
            conversation_id,
            project_id=project_id,
            variant_id=variant_id,
            scope=scope,
            ids=ids,
            label=label,
            confidence=confidence,
            reason=reason,
        )

    def _cad_target_clarification(
        self,
        message: str,
        edit: dict[str, Any],
        geometries: list[dict[str, Any]],
        failure_message: str | None = None,
    ) -> dict[str, Any] | None:
        """Return semantic choices when the deterministic resolver refuses to guess."""
        catalog = build_geometry_catalog(geometries)

        def candidate_preview(
            geometry_ids: list[int] | None,
        ) -> list[dict[str, Any]]:
            paths: list[dict[str, Any]] = []
            selected_ids = set(geometry_ids or [])
            show_complete_drawing = geometry_ids is None
            for item in geometries:
                if not isinstance(item, dict):
                    continue
                raw_paths = geometry_preview_paths({
                    "lines": [{**item, "role": "printing", "selected": True}]
                })
                for raw_path in raw_paths:
                    points = raw_path.get("points")
                    if not isinstance(points, list):
                        continue
                    paths.append({
                        **raw_path,
                        "namespace": "cad_target_clarification",
                        "frame_id": "map",
                        "route_type": (
                            "drawing"
                            if show_complete_drawing or item.get("id") in selected_ids
                            else "reference"
                        ),
                        "selection_state": (
                            "candidate"
                            if not show_complete_drawing and item.get("id") in selected_ids
                            else "context"
                        ),
                        "geometry_id": item.get("id"),
                        "points": points,
                    })
            return paths

        complete_preview = candidate_preview(None)

        def clarification_contract(
            *,
            reason: str,
            question: str | None,
            options: list[dict[str, Any]],
            scoring: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            contract: dict[str, Any] = {
                "schema": "cad.target-clarification.v1",
                "reason": reason,
                "original_request": message,
                "question": question or failure_message or "请在右侧图纸中点选修改目标。",
                "selection_mode": "canvas",
                "selection_scopes": (
                    ["logical_object", "instance", "geometry"]
                    if any(
                        isinstance(item, dict)
                        and isinstance(item.get("template_instance"), int)
                        and item["template_instance"] > 0
                        for item in geometries
                    )
                    else ["logical_object", "geometry"]
                ),
                "preview_paths": complete_preview,
                "options": options,
            }
            if isinstance(scoring, dict):
                contract["scoring"] = scoring
            return contract

        semantic_candidates = edit.get("_semantic_candidates")
        if isinstance(semantic_candidates, list) and semantic_candidates:
            options: list[dict[str, Any]] = []
            ordered = sorted(
                (item for item in semantic_candidates if isinstance(item, dict)),
                key=lambda item: int(item.get("geometry_id") or 0),
            )
            for index, item in enumerate(ordered, 1):
                geometry_id = item.get("geometry_id")
                instance_id = item.get("instance_id")
                if not isinstance(geometry_id, int) or not isinstance(instance_id, int):
                    continue
                replay = self._cad_target_reply(edit, instance_id)
                semantic = str(item.get("semantic") or "局部图元")
                option = {
                    "scope": "geometry",
                    "instance_id": instance_id,
                    "label": f"{semantic} · 候选 {index}",
                    "geometry_ids": [geometry_id],
                    "target_selection": {
                        "scope": "entity",
                        "geometry_ids": [geometry_id],
                    },
                    "center_m": item.get("center_m"),
                    "bounds_m": item.get("bounds_m"),
                    "preview_paths": candidate_preview([geometry_id]),
                }
                if replay is not None:
                    option["reply"] = f"选择图元ID:{geometry_id}，{replay}"
                options.append(option)
            if options:
                return clarification_contract(
                    reason="semantic_target_ambiguous",
                    question="找到多个同名局部图元，请选择本次要修改的一个。",
                    options=options,
                )

        resolution = resolve_cad_target(edit, geometries)
        if resolution.get("status") != "needs_clarification":
            return clarification_contract(
                reason="geometry_target_unresolved",
                question=failure_message,
                options=[],
            )
        candidates = {
            int(value) for value in resolution.get("candidate_instance_ids") or []
            if isinstance(value, int) and value > 0
        }
        options: list[dict[str, Any]] = []
        for instance in catalog.get("instances") or []:
            instance_id = instance.get("instance_id")
            if instance_id not in candidates:
                continue
            reply = self._cad_target_reply(edit, int(instance_id))
            geometry_ids = [
                int(value) for value in instance.get("geometry_ids") or []
            ]
            option = {
                "scope": "instance",
                "instance_id": instance_id,
                "label": str(instance.get("semantic") or f"第 {instance_id} 个图形"),
                "geometry_ids": geometry_ids,
                "target_selection": {
                    "scope": "group",
                    "geometry_ids": geometry_ids,
                },
                "center_m": instance.get("center_m"),
                "bounds_m": instance.get("bounds_m"),
                "preview_paths": candidate_preview(geometry_ids),
            }
            if reply is not None:
                option["reply"] = reply
            options.append(option)
        if not options:
            # Imported or manually drawn CAD may have stable geometry IDs but
            # no confirmed template_instance grouping. Offer a bounded set of
            # entity choices while the complete canvas remains authoritative.
            for index, element in enumerate(catalog.get("elements") or [], 1):
                geometry_id = element.get("geometry_id")
                if not isinstance(geometry_id, int) or geometry_id <= 0:
                    continue
                semantic = str(element.get("semantic") or element.get("type") or "图元")
                options.append({
                    "scope": "geometry",
                    "label": f"{semantic} · 图元 {geometry_id}",
                    "geometry_ids": [geometry_id],
                    "target_selection": {
                        "scope": "entity",
                        "geometry_ids": [geometry_id],
                    },
                    "center_m": element.get("center_m"),
                    "bounds_m": element.get("bounds_m"),
                    "preview_paths": candidate_preview([geometry_id]),
                })
                if len(options) >= 12:
                    break
        return clarification_contract(
            reason=str(resolution.get("reason") or "target_ambiguous"),
            question=str(
                failure_message
                or resolution.get("question")
                or "请在右侧图纸中点选修改目标。"
            ),
            options=options,
            scoring=(
                resolution.get("scoring")
                if isinstance(resolution.get("scoring"), dict)
                else None
            ),
        )

    @staticmethod
    def _bind_incremental_selection(
        edit: dict[str, Any], route: dict[str, Any], parent: dict[str, Any]
    ) -> str | None:
        """Convert the editor selection into deterministic CAD targets.

        Group selections target complete stable instances. An entity selection
        remains geometry-scoped so a single picked segment cannot accidentally
        transform its containing drawing.
        """
        selection = route.get("drawing_selection")
        if not isinstance(selection, dict):
            return None
        # The canvas is authoritative even when the prompt also contains a
        # different attribute or spatial selector.
        edit.pop("selector", None)
        raw_ids = selection.get("geometry_ids")
        geometries = parent.get("geometries")
        if not isinstance(raw_ids, list) or not raw_ids or not isinstance(geometries, list):
            return "当前画布选区无效，请重新选择图形后再修改。"
        try:
            selected_ids = {int(value) for value in raw_ids}
        except (TypeError, ValueError):
            return "当前画布选区包含无效图元 ID，请重新载入图纸。"
        by_id = {
            int(item.get("id")): item
            for item in geometries
            if isinstance(item, dict) and str(item.get("id", "")).isdigit()
        }
        missing = selected_ids - set(by_id)
        if missing:
            return "当前画布选区已过期，请重新载入最新候选方案后再修改。"
        selected = [by_id[value] for value in selected_ids]
        groups = {
            item.get("template_instance") for item in selected
            if isinstance(item.get("template_instance"), int)
        }
        operation = str(edit.get("operation") or "")
        if selection.get('scope')=='group':
            # Older App versions serialized a picked part as group+object_id.
            # Recover that identity only when its complete geometry matches;
            # anonymous partial groups must still fail the whole-group check.
            wanted={str(v) for v in [selection.get('object_id'),*(selection.get('object_ids') or [])] if v}
            members=[o for o in parent.get('logical_objects') or [] if str(o.get('object_id')) in wanted]
            expected={int(ref) for o in members for ref in o.get('geometry_refs') or []}
            if wanted and len(members)==len(wanted) and expected==selected_ids:
                selection={**selection,'scope':'logical_object'}
        if selection.get("scope") == "logical_object":
            object_ids = [value for value in [
                selection.get("object_id"), *(selection.get("object_ids") or [])
            ] if value]
            if not object_ids:
                return "当前逻辑对象缺少稳定身份，请重新在图纸中点选。"
            logical_objects = list(parent.get("logical_objects") or [])
            wanted = {str(value) for value in object_ids}
            expected_ids = sorted({
                int(ref)
                for item in logical_objects
                if isinstance(item, dict) and str(item.get("object_id")) in wanted
                for ref in item.get("geometry_refs") or []
                if str(ref).isdigit()
            })
            if not expected_ids or sorted(selected_ids) != expected_ids:
                return "当前逻辑对象选区已过期或不完整，请重新点选完整图形。"
            edit.pop("instance", None)
            edit.pop("instances", None)
            edit["geometry_ids"] = expected_ids
            if len(object_ids) == 1:
                edit["logical_object_id"] = str(object_ids[0])
                edit.pop("logical_object_ids", None)
            else:
                edit["logical_object_ids"] = [str(value) for value in object_ids]
                edit.pop("logical_object_id", None)
            return None
        if selection.get("scope") == "group":
            assemblies: dict[str,list[dict[str,Any]]] = {}
            for obj in parent.get("logical_objects") or []:
                if obj.get("assembly_id"):
                    assemblies.setdefault(str(obj["assembly_id"]),[]).append(obj)
            matching=[members for members in assemblies.values() if {
                int(ref) for obj in members for ref in obj.get("geometry_refs") or []
            }==set(selected_ids)]
            if len(matching)==1:
                edit.pop("instance",None)
                edit.pop("instances",None)
                edit["geometry_ids"]=sorted(selected_ids)
                ids=[str(o["object_id"]) for o in matching[0]]
                if len(ids)==1:edit["logical_object_id"]=ids[0]
                else:edit["logical_object_ids"]=ids
                return None
            payload_instance = selection.get("instance_id")
            if isinstance(payload_instance, int) and payload_instance > 0:
                # The canvas already resolved a stable instance identity; prefer
                # it over re-deriving the group from geometry IDs.
                if payload_instance not in groups:
                    return "当前整组选区的实例编号已失效，请重新选择完整图形。"
                selected_group = payload_instance
            else:
                # Imported CAD may intentionally have no instance groups yet.
                # When the canvas selected every geometry, the selection is
                # still deterministic for geometry-local edits such as scale
                # and translate. Do not force the user through a grouping
                # confirmation just to enlarge the currently displayed CAD.
                geometry_safe_operations = {
                    "translate", "rotate", "scale", "resize", "delete", "retain",
                }
                if selection.get('project_id') and selection.get('variant_id'):
                    geometry_safe_operations.update({'duplicate','mirror','offset','array','align','constraint'})
                all_geometry_ids = set(by_id)
                if (
                    not groups
                    and selected_ids == all_geometry_ids
                    and operation in geometry_safe_operations
                ):
                    edit.pop("instance", None)
                    edit.pop("instances", None)
                    edit["geometry_ids"] = sorted(selected_ids)
                    return None
                if not groups or len(groups) != 1 or any(
                    item.get("template_instance") not in groups for item in selected
                ):
                    return "当前整组选区缺少稳定实例编号，请先确认图纸实例分组。"
                selected_group = next(iter(groups))
            group_ids = {
                int(item.get("id")) for item in geometries
                if item.get("template_instance") == selected_group
                and str(item.get("id", "")).isdigit()
            }
            if selected_ids != group_ids:
                return "当前整组选区不完整，请双击图形重新选择全部线段。"
            edit.pop("geometry_ids", None)
            edit.pop("instances", None)
            edit["instance"] = selected_group
            return None
        if selection.get("scope") != "entity":
            return "当前画布选区范围无效，请重新选择线段或整个图形。"
        if operation in {
            "align", "duplicate", "mirror", "offset", "array", "constraint"
        }:
            return "该操作需要选择完整图形（整个图形），请切换到“完整图形”后重新点选。"
        edit.pop("instance", None)
        edit.pop("instances", None)
        edit["geometry_ids"] = sorted(selected_ids)
        return None

    def _apply_drawing_layout_followup(
        self, message: str, route: dict[str, Any]
    ) -> dict[str, Any] | None:
        layout = _template_layout_requirements(message)
        if route.get("decision_source") != "drawing_layout_followup" or not layout:
            return None
        project_id = self._project_id_from_route(route)
        project = get_creative_project_store().get(project_id) if project_id else None
        if project is None:
            return self._result(
                "请先选择要调整的图纸项目，我不会修改其他项目。",
                self._empty_usage(),
            )
        project_prompt = str(project.get("original_prompt") or project.get("name") or "")
        layout_matches = recognize_drawing_template_set(project_prompt)
        layout = normalize_template_layout_for_matches(layout_matches, layout)
        layout_conflicts = list(layout.get("layout_conflicts") or [])
        if layout_conflicts:
            result = self._result(
                "当前排列要求存在冲突，本次没有修改图纸："
                + "、".join(str(item) for item in layout_conflicts)
                + "。请明确选择上下排列或左右排列，并只保留一个间距值。",
                self._empty_usage(),
            )
            result["ok"] = False
            result["layout_conflicts"] = layout_conflicts
            return result
        if project.get("status") not in {"draft", "clarifying", "ready_for_design", "designing"}:
            return self._result(
                "当前图纸已进入规划或执行阶段，请先创建新方案再调整排列方式。",
                self._empty_usage(),
            )
        # The canvas preview is the user's explicit working context. Prefer
        # it over project defaults so multiple candidates cannot make the AI
        # ask the user to choose again after every simple follow-up.
        requested_variant_id = str(route.get("selected_variant_id") or "") or None
        parent = self._effective_parent_variant(
            project, preferred_variant_id=requested_variant_id
        )
        if requested_variant_id and parent is None:
            result = self._result(
                "当前预览方案已失效，请先刷新候选方案后再修改。", self._empty_usage()
            )
            result["ok"] = False
            return result
        if project.get("variants") and parent is None:
            return self._result(
                "请先在候选方案中选择要继续优化的方案。", self._empty_usage()
            )
        missing = [
            item for item in project.get("missing_parameters", [])
            if item not in {"arrangement", "spacing_m", "spacing"}
        ]
        # Resolve inherited spacing before saving the new requirements. The
        # project requirement is preferred; the geometry check is the
        # deterministic fallback for imported/legacy projects.
        if layout.get("preserve_spacing") and "spacing_m" not in layout:
            inherited_spacing = (project.get("requirements") or {}).get("spacing_m")
            if not isinstance(inherited_spacing, (int, float)) and parent is not None:
                inherited_check = validate_template_layout(
                    parent.get("geometries") or [],
                    arrangement=(project.get("requirements") or {}).get("arrangement"),
                    peer_placement=(project.get("requirements") or {}).get("peer_placement"),
                )
                inherited_spacing = inherited_check.get("actual_spacing_m")
            if isinstance(inherited_spacing, (int, float)) and inherited_spacing >= 0:
                layout["spacing_m"] = round(float(inherited_spacing), 4)
            else:
                result = self._result(
                    "当前预览方案没有可确认的原间距，请给出具体间距后再修改。",
                    self._empty_usage(),
                )
                result["ok"] = False
                return result
        layout_update = {
            key: value for key, value in layout.items()
            if key != "preserve_spacing"
        }
        layout_update["layout_override"] = True
        # A corrected follow-up must clear a conflict left by an earlier
        # failed turn; otherwise the stale project requirement would keep
        # blocking every later candidate generation.
        if (project.get("requirements") or {}).get("layout_conflicts"):
            layout_update["layout_conflicts"] = []
        # A newer edge-based instruction replaces an older absolute
        # left/right placement. Likewise, a numeric gap replaces a previous
        # domain-derived spacing label such as "one parking-space width".
        if "arrangement" in layout and "peer_placement" not in layout:
            layout_update["peer_placement"] = None
        if "spacing_m" in layout and "spacing_reference" not in layout:
            layout_update["spacing_reference"] = None
        update_arguments: dict[str, Any] = {
            "requirements": layout_update,
            "event_message": "已确认图纸排列方式和间距",
        }
        if project.get("status") != "designing":
            update_arguments["missing_parameters"] = missing
        if parent is not None and not missing:
            proposed = deepcopy(project)
            proposed["requirements"] = {
                **(project.get("requirements") or {}), **layout_update,
            }
            incremental = (
                "spacing_m" in layout and "arrangement" not in layout
                and {item.get("template_instance") for item in parent.get("geometries", [])} == {1, 2}
            )
            if incremental:
                geometries, error = space_two_instances(
                    parent["geometries"], float(layout["spacing_m"]) * 1000,
                    str((project.get("requirements") or {}).get("arrangement") or "long_side_adjacent"),
                )
                missing_geometry = [error] if error else []
            else:
                geometries, missing_geometry = design_geometries_for_project(proposed, route)
            if geometries is None:
                result = self._result(
                    "无法按新的排列要求生成图纸：" + "、".join(str(item) for item in missing_geometry),
                    self._empty_usage(),
                )
                result["ok"] = False
                return result
            validation_arrangement = (
                layout.get("arrangement")
                or (project.get("requirements") or {}).get("arrangement")
                or ("long_side_adjacent" if incremental else None)
            )
            layout_validation = validate_template_layout(
                geometries,
                arrangement=validation_arrangement,
                spacing_m=(
                    float(layout["spacing_m"])
                    if isinstance(layout.get("spacing_m"), (int, float))
                    else (
                        float((project.get("requirements") or {}).get("spacing_m"))
                        if isinstance((project.get("requirements") or {}).get("spacing_m"), (int, float))
                        else None
                    )
                ),
                # An explicit arrangement update supersedes the old peer
                # direction. In particular, "长边并排" must not inherit a
                # stale horizontal "right" placement from the previous
                # candidate.
                peer_placement=(
                    layout.get("peer_placement")
                    if "peer_placement" in layout
                    else (
                        None
                        if "arrangement" in layout
                        else (project.get("requirements") or {}).get("peer_placement")
                    )
                ),
            )
            if layout_validation.get("ok") is not True:
                errors = "、".join(str(item) for item in layout_validation.get("errors") or [])
                result = self._result(
                    "新的排列结果未通过几何校验，本次错误方案未保存。" + (errors or "请重新描述排列方向。"),
                    self._empty_usage(),
                )
                result["ok"] = False
                result["layout_validation"] = layout_validation
                return result
            source_ids = sorted(
                int(item["id"])
                for item in parent.get("geometries") or []
                if str(item.get("id", "")).isdigit()
            )
            source_id_set = set(source_ids)
            created_ids = sorted(
                int(item["id"])
                for item in geometries
                if str(item.get("id", "")).isdigit()
                and int(item["id"]) not in source_id_set
            )
            contract = build_cad_edit_contract({
                "operation": "rearrange_layout",
                "geometry_ids": source_ids,
                "arrangement": str(validation_arrangement),
                "gap_mm": float(layout_validation.get("actual_spacing_m", 0.0)) * 1000.0,
                "peer_placement": (
                    str(layout["peer_placement"])
                    if layout.get("peer_placement") in {"above", "below", "left", "right"}
                    else None
                ),
                "layout_strategy": (
                    "move_secondary" if incremental else "rebuild_templates"
                ),
                "count": len({
                    item.get("template_instance") for item in geometries
                    if isinstance(item.get("template_instance"), int)
                }),
                "created_geometry_ids": created_ids,
                "project_id": str(project["id"]),
                "parent_variant_id": str(parent["id"]),
                "assumptions": ["保持模板内部尺寸，仅修改模板实例的排列和间距"],
            }, source_text=message)
            result = self._persist_candidate_edit(
                project, parent, geometries,
                f"实例间距调整为 {layout['spacing_m']:g} 米" if incremental
                else "按新排列重新生成标准模板",
                cad_edit_contract=contract,
            )
            if result.get("ok"):
                result["layout_validation"] = layout_validation
                for item in result.get("tool_results") or []:
                    if isinstance(item, dict) and item.get("name") == "persist_candidate_variant":
                        item["layout_validation"] = layout_validation
                updated = get_creative_project_store().update(str(project["id"]), **update_arguments)
                if updated is not None:
                    result["project"] = updated
                    result["variants"] = updated["variants"]
                else:
                    result["message"] += " 项目需求未能同步，请刷新后核对。"
            if not incremental and result.get("ok"):
                result["message"] = (
                    "标准模板已按新排列重建，原候选保留，可在方案区查看几何差异。"
                    + (" 项目需求未能同步，请刷新后核对。" if updated is None else "")
                )
            if result.get("ok"):
                result["cad_edit_contract"] = contract
            return result
        updated = get_creative_project_store().update(str(project["id"]), **update_arguments)
        if updated is None:
            result = self._result("图纸需求更新失败，请刷新项目后重试。", self._empty_usage())
            result["ok"] = False
            return result
        if not missing and str(updated.get('original_prompt') or '').strip():
            generated = self.generate_project_candidate(str(updated["id"]))
            if generated.get("ok") is True and generated.get("preview_paths"):
                generated["message"] = (
                    "已按明确的排列方式和间距生成新候选方案，"
                    "右侧与“查看图纸”均已更新为本次图纸。"
                )
                return generated
        spacing = layout.get("spacing_m")
        description = (
            "并排排列" if layout.get("arrangement") == "long_side_adjacent"
            else "短边相邻" if layout.get("arrangement") == "short_side_adjacent"
            else "间距"
        )
        if spacing is not None:
            description += f" {spacing:g} 米" if description == "间距" else f"，间距 {spacing:g} 米"
        return {
            **self._result(
                f"已将{description}保存到当前图纸需求。"
                + ("现在可以生成候选方案。" if not missing else "请继续补充其余参数。"),
                self._empty_usage(),
            ),
            "project_id": str(updated["id"]),
            "project": updated,
        }

    @staticmethod
    def _relative_template_addition_route(
        message: str, mode: str,
    ) -> dict[str, Any] | None:
        if RobotAgentService.normalize_agent_mode(mode) != "advanced":
            return None
        text = message.strip().lower()
        if not ("上下方" in text or ("上方" in text and "下方" in text)):
            return None
        if not any(marker in text for marker in ("添加", "增加", "各加", "各添加", "各放")):
            return None
        source = next((item for item in ("篮球场", "羽毛球场", "车位", "停车位") if item in text), None)
        target = next((item for item in ("羽毛球场", "篮球场", "车位", "停车位") if item in text), None)
        if source is None or target is None:
            return None
        route = dict(RobotAgentService.route_intent("修改当前图纸", mode))
        route.update({
            "name": "drawing_design",
            "tool_family": "cad",
            "operation": "modify",
            "stage": "candidate_edit",
            "decision_source": "drawing_relative_template_addition",
            "confidence": 0.99,
            "review_required": False,
            "clarification_required": False,
            "relative_addition": {
                "source_label": source,
                "target_label": target,
                "positions": ["above", "below"],
            },
        })
        return route

    def _apply_relative_template_addition(
        self, message: str, route: dict[str, Any]
    ) -> dict[str, Any] | None:
        if route.get("decision_source") != "drawing_relative_template_addition":
            return None
        request = route.get("relative_addition")
        if not isinstance(request, dict):
            return None
        project_id = self._project_id_from_route(route)
        project = get_creative_project_store().get(project_id) if project_id else None
        if not isinstance(project, dict):
            return self._result("请先选择要修改的图纸项目。", self._empty_usage())
        project, parent, activation_error = self._activate_preview_variant_for_edit(
            project, route
        )
        if activation_error:
            result = self._result(activation_error, self._empty_usage())
            result["ok"] = False
            return result
        if not isinstance(parent, dict):
            return self._result("请先生成并选择当前候选方案，再添加场地。", self._empty_usage())
        source = list(parent.get("geometries") or [])
        source_label = str(request.get("source_label") or "")
        target_label = str(request.get("target_label") or "")
        source_template = {"篮球场": "basketball", "羽毛球场": "badminton", "车位": "parking"}.get(source_label)
        target_template = {"篮球场": "basketball", "羽毛球场": "badminton", "车位": "parking"}.get(target_label)
        if not source_template or not target_template:
            return self._result("当前场地类型暂不支持上下方增量添加。", self._empty_usage())
        dimensions = {"basketball": (28.0, 15.0), "badminton": (13.4, 6.1), "parking": (2.5, 5.0)}
        target_width, target_height = dimensions[target_template]
        gap_mm = 0.0
        next_instance = max((int(item.get("template_instance") or 0) for item in source if str(item.get("template_instance", "")).isdigit()), default=0)
        next_id = max((int(item.get("id") or 0) for item in source if str(item.get("id", "")).isdigit()), default=0)
        positions = list(request.get("positions") or ["above", "below"])
        prototype = drawing_template_geometries({
            "template": target_template,
            "width_m": target_width,
            "height_m": target_height,
            "quantity": 1,
        })
        created_geometry_ids = list(range(
            next_id + 1,
            next_id + len(prototype) * len(positions) + 1,
        ))
        contract = build_cad_edit_contract({
            "operation": "add_template",
            "geometry_ids": sorted(
                int(item["id"]) for item in source
                if str(item.get("id", "")).isdigit()
            ),
            "source_template": source_template,
            "target_template": target_template,
            "relative_positions": positions,
            "gap_mm": gap_mm,
            "created_geometry_ids": created_geometry_ids,
            "project_id": str(project["id"]),
            "parent_variant_id": str(parent["id"]),
        }, source_text=message)
        command = cad_edit_contract_to_edit(contract)
        geometries, execution_error = edit_candidate_geometries(source, command)
        if geometries is None:
            result = self._result(
                execution_error or "相对新增模板执行失败。", self._empty_usage()
            )
            result["ok"] = False
            result["cad_edit_contract"] = contract
            return result
        next_instance += len(positions)
        result = self._persist_candidate_edit(
            project,
            parent,
            geometries,
            f"在{source_label}上下方各添加一个{target_label}",
            expected_quantity=next_instance,
            instance_edit_operation="relative_addition",
            cad_edit_contract=contract,
        )
        if result.get("ok") is not True:
            return result
        updated = get_creative_project_store().update(
            str(project["id"]),
            requirements={
                **dict(project.get("requirements") or {}),
                "relative_addition": {
                    "source": source_template,
                    "target": target_template,
                    "positions": ["above", "below"],
                },
            },
            event_message=f"已在{source_label}上下方各添加一个{target_label}",
        )
        if updated is not None:
            result["project"] = updated
            result["variants"] = updated.get("variants", [])
        result["message"] = f"已在{source_label}上方和下方各添加一个{target_label}，原候选已保留。"
        result["relative_addition"] = request
        result["cad_edit_contract"] = contract
        return result

    @classmethod
    def _affirmative_followup_route(
        cls,
        message: str,
        mode: str,
        history: list[dict[str, str]] | None,
    ) -> dict[str, Any] | None:
        """Keep short confirmations attached to the immediately prior question.

        A reply such as “没错” has no standalone intent. When the previous
        assistant message asked to confirm a movement-only demonstration, the
        router must retain that context instead of sending the generic
        “请明确本次最先要处理的操作” question back to the user.
        """
        normalized = re.sub(r"[\s，。！？、,.!?；;：:]+", "", message.strip().lower())
        if normalized not in {"是的", "没错", "对", "正确", "是", "yes", "y"}:
            return None
        previous = next(
            (
                str(item.get("content") or "")
                for item in reversed(history or [])
                if item.get("role") == "assistant" and item.get("content")
            ),
            "",
        )
        movement_markers = (
            "只进行运动演示",
            "不喷墨",
            "不画线",
            "矩形路径走一遍",
            "机器人按",
        )
        if not previous or not any(marker in previous for marker in movement_markers):
            return None
        route = dict(cls.route_intent("走一段运动演示路径", mode))
        route.update(
            {
                "name": "motion_control",
                "tool_family": "motion",
                "operation": "execute",
                "stage": "confirmation",
                "next_step": "等待用户明确确认执行",
                "confidence": 0.98,
                "api_required": True,
                "safety_confirmation_required": True,
                "context_requirements": [
                    "online",
                    "control_ready",
                    "emergency_stopped",
                ],
                "decision_source": "affirmative_followup",
                "review_required": False,
                "clarification_required": False,
            }
        )
        size = re.search(
            r"(\d+(?:\.\d+)?)\s*[x×*]\s*(\d+(?:\.\d+)?)\s*(?:米|m)",
            previous.lower(),
        )
        if size is not None:
            route["followup_dimensions"] = {
                "width_m": float(size.group(1)),
                "height_m": float(size.group(2)),
            }
        return route

    def _confirmed_movement_followup(
        self, route: dict[str, Any], mode: str
    ) -> dict[str, Any] | None:
        dimensions = route.get("followup_dimensions")
        if not isinstance(dimensions, dict):
            return self._result(
                "已确认只进行运动演示、不喷墨。请补充路径尺寸。",
                self._empty_usage(),
            )
        width = dimensions.get("width_m")
        height = dimensions.get("height_m")
        if not isinstance(width, (int, float)) or not isinstance(height, (int, float)):
            return None
        if not (0.1 <= float(width) <= 50 and 0.1 <= float(height) <= 50):
            return self._result("矩形尺寸必须在 0.1 到 50 米之间。", self._empty_usage())
        steps = drawing_template_motion_steps(
            {
                "template": "room",
                "width_m": float(width),
                "height_m": float(height),
            }
        )
        if len(steps) < 2:
            return self._result("无法生成有效的矩形运动演示。", self._empty_usage())
        return self._result(
            f"已确认：只进行运动演示，不喷墨、不画线。"
            f"已准备 {float(width):g}×{float(height):g} 米矩形路径，共 {len(steps)} 段；"
            "这是开环演示，请检查周围环境后在下方确认执行。",
            self._empty_usage(),
            self._register_pending("drive_sequence", {"steps": steps}, mode=mode),
        )

    @staticmethod
    def _merge_route_review(
        rule_route: dict[str, Any], review: dict[str, Any] | None
    ) -> dict[str, Any]:
        result = dict(rule_route)
        result["review"] = {"attempted": True, "valid": review is not None}
        valid_intents = {
            "conversation", "diagnosis", "status_query", "drawing_design",
            "motion_control", "printer_control", "mission_control",
            "localization_control", "stop",
        }
        if not review or review.get("primary_intent") not in valid_intents:
            result["decision_source"] = "rules_fallback"
            return result
        primary = str(review["primary_intent"])
        confidence = RobotAgentService._review_confidence(review, 0.0)
        cad_operation = review.get("cad_operation")
        if cad_operation not in {"create", "modify", "inspect"}:
            cad_operation = None
        secondary = review.get("secondary_intents")
        if not isinstance(secondary, list):
            secondary = []
        secondary = [
            str(item)
            for item in secondary
            if item in valid_intents and item != primary
        ]
        physical = {
            "motion_control", "printer_control", "mission_control",
            "localization_control", "stop",
        }
        rule_primary = str(rule_route.get("name") or "conversation")
        # A model may request clarification, but it may neither invent a
        # physical action nor reclassify a deterministic physical action.
        if primary != rule_primary and (
            primary in physical or rule_primary in physical
        ):
            result.update({
                "name": "conversation",
                "tool_family": "conversation",
                "operation": "query",
                "stage": "clarification",
                "next_step": "澄清用户要执行的具体操作",
                "confidence": 0.0,
                "safety_confirmation_required": False,
                "context_requirements": ["online"],
                "decision_source": "safety_clarification",
                "clarification_required": True,
                "clarification_question": "请明确要操作的设备和具体动作。",
            })
            result["review"].update(review)
            result["review"]["safety_downgraded"] = True
            return result
        if (
            review.get("requires_clarification") is True
            or confidence < 0.65
            or any(intent in physical for intent in secondary)
        ):
            result.update({
                "name": "conversation",
                "tool_family": "conversation",
                "operation": "query",
                "stage": "clarification",
                "next_step": "只追问一个关键澄清问题",
                "confidence": confidence,
                "safety_confirmation_required": False,
                "context_requirements": ["online"],
                "decision_source": "model_clarification",
                "clarification_required": True,
                "clarification_question": str(
                    review.get("clarification_question") or "请明确本次最先要处理的操作。"
                ),
            })
        elif (
            primary == "drawing_design"
            and rule_primary != "drawing_design"
            and cad_operation is None
        ):
            result.update({
                "name": "conversation",
                "tool_family": "conversation",
                "operation": "query",
                "stage": "clarification",
                "next_step": "确认是新建、修改还是检查图纸",
                "confidence": confidence,
                "safety_confirmation_required": False,
                "context_requirements": ["online"],
                "decision_source": "model_clarification",
                "clarification_required": True,
                "clarification_question": "请确认这次是新建图纸、修改当前图纸，还是只检查图纸？",
            })
        elif primary != rule_route.get("name") and primary not in physical:
            result.update(RobotAgentService._reviewed_route_fields(primary))
            if primary == "drawing_design" and cad_operation is not None:
                result.update(
                    RobotAgentService._reviewed_cad_operation_fields(cad_operation)
                )
            result.update({
                "confidence": confidence,
                "decision_source": "model_review",
            })
        else:
            result["confidence"] = confidence
            result["decision_source"] = "model_review"
        result["secondary_intents"] = [
            item for item in secondary if item != result["name"]
        ]
        result["review"].update(review)
        return result

    @staticmethod
    def _review_confidence(review: dict[str, Any], fallback: float) -> float:
        try:
            value = float(review.get("confidence", fallback))
        except (TypeError, ValueError):
            value = fallback
        if not math.isfinite(value):
            value = fallback
        return max(0.0, min(1.0, value))

    @staticmethod
    def _reviewed_route_fields(intent: str) -> dict[str, Any]:
        profiles: dict[str, dict[str, Any]] = {
            "conversation": {
                "tool_family": "conversation",
                "operation": "query",
                "stage": "conversation",
                "next_step": "回答用户问题",
                "api_required": True,
                "context_requirements": ["online"],
            },
            "diagnosis": {
                "tool_family": "telemetry",
                "operation": "diagnose",
                "stage": "observation",
                "next_step": "读取实时状态并给出证据",
                "api_required": True,
                "context_requirements": ["online", "telemetry_age_ms"],
            },
            "status_query": {
                "tool_family": "telemetry",
                "operation": "inspect",
                "stage": "observation",
                "next_step": "读取实时遥测",
                "api_required": False,
                "context_requirements": ["online", "telemetry_age_ms"],
            },
            "drawing_design": {
                "tool_family": "cad",
                "operation": "create",
                "stage": "requirements",
                "next_step": "提取图形、尺寸和约束，只追问一个最关键的缺失参数",
                "api_required": True,
                "context_requirements": ["mission_stage"],
            },
        }
        return {
            "name": intent,
            **profiles[intent],
            "safety_confirmation_required": False,
        }

    @staticmethod
    def _reviewed_cad_operation_fields(operation: str) -> dict[str, Any]:
        profiles = {
            "create": {
                "operation": "create",
                "stage": "requirements",
                "next_step": "提取图形、尺寸和约束，只追问一个最关键的缺失参数",
            },
            "modify": {
                "operation": "modify",
                "stage": "editing",
                "next_step": "解析修改目标和参数并进行确定性校验",
            },
            "inspect": {
                "operation": "inspect",
                "stage": "inspection",
                "next_step": "读取当前图纸并返回检查结果",
            },
        }
        return dict(profiles[operation])

    @staticmethod
    def runtime_context(route: dict[str, Any] | None = None) -> dict[str, Any]:
        snapshot = robot_state.snapshot()
        captured_at = datetime.now(timezone.utc).isoformat()
        telemetry = build_telemetry_contract(snapshot)
        telemetry.pop("obstacles", None)
        telemetry_age = snapshot.get("telemetry_age_ms")
        printer = build_printer_contract(snapshot)
        mission = build_mission_contract(snapshot)
        active_route = route or {}
        required = list(active_route.get("context_requirements") or [])
        missing = [
            key for key in required
            if snapshot.get(key) is None
            or (isinstance(snapshot.get(key), dict) and not snapshot.get(key))
        ]
        requested_domains = list(active_route.get("requested_data_domains") or [])
        # Follow-up resolution may promote an initial conversation route to
        # CAD after its data-domain list was built. Recheck the final route.
        user_text = str(active_route.get("user_message") or "")
        if (active_route.get("tool_family") == "cad" and user_text
                and not RobotAgentService._requests_live_localization(user_text)):
            requested_domains = [d for d in requested_domains if d != "localization"]
        domain_quality = {
            "runtime": telemetry["runtime"]["quality"],
            "motion": telemetry["drive"]["quality"],
            "localization": telemetry["localization"]["quality"],
            "energy": telemetry["energy"]["quality"],
            "printer": printer["quality"],
            "obstacles": {"available": False, "fresh": False, "reason": "not_supported"},
            "mission": {
                "available": snapshot.get("online") is True,
                "fresh": snapshot.get("online") is True,
                "age_ms": None,
                "limit_ms": None,
                "reason": None if snapshot.get("online") is True else "unavailable",
            },
        }
        blocked_domains = [
            domain for domain in requested_domains
            if domain in domain_quality and not domain_quality[domain]["fresh"]
        ]
        fresh = bool(requested_domains) and not blocked_domains
        if not requested_domains:
            fresh = telemetry["runtime"]["quality"]["fresh"]
        return {
            "schema_version": "1.1",
            "captured_at": captured_at,
            "source": "robot_state_snapshot",
            "fresh": fresh,
            "quality": {
                "telemetry_age_ms": telemetry_age,
                "required_fields": required,
                "missing_fields": missing,
                "usable_for_decision": fresh and not missing,
                "requested_domains": requested_domains,
                "domain_quality": domain_quality,
                "blocked_domains": blocked_domains,
                "freshness_gate": "allow" if fresh and not missing else "block",
            },
            "route": active_route,
            "telemetry": telemetry,
            "printer": printer,
            "mission": mission,
        }

    @staticmethod
    def knowledge_context(
        message: str, route: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        active_route = route or {}
        if active_route.get("tool_family") not in {
            "conversation", "telemetry", "cad", "mission", "printer", "localization",
        }:
            return {"query": message, "matches": [], "indexed_chunks": 0}
        return project_knowledge.search(message, limit=4)

    @staticmethod
    def reconcile_creative_projects(project_id: str | None = None) -> int:
        """Repair legacy template projects created before template parameterization.

        Only projects that are still in the requirement stage are eligible.
        Designed, planned, or executed projects are never rewritten here.
        """
        candidates = (
            [get_creative_project_store().get(project_id)]
            if project_id
            else get_creative_project_store().list(limit=200)
        )
        repaired = 0
        for project in candidates:
            if not isinstance(project, dict):
                continue
            project_status = str(project.get("status") or "")
            source_drawing = project.get("source_drawing")
            if isinstance(source_drawing, dict):
                graph_prompt = " ".join(
                    value for value in (
                        str(project.get("original_prompt") or "").strip(),
                        str(project.get("name") or "").strip(),
                    )
                    if value
                )
                template_match = recognize_drawing_template(graph_prompt)
                graph_match = dict(template_match or {
                    "template": "imported_cad", "quantity": 1,
                })
                for variant in list(project.get("variants") or []):
                    if (
                        not isinstance(variant, dict)
                        or list(variant.get("logical_objects") or [])
                        or not isinstance(variant.get("geometries"), list)
                        or not variant.get("geometries")
                    ):
                        continue
                    graph = project_logical_graph(
                        project, graph_match, list(variant["geometries"])
                    )
                    migrated = get_creative_project_store().migrate_variant_logical_graph(
                        str(project["id"]),
                        str(variant.get("id") or ""),
                        list(graph.get("logical_objects") or []),
                        dict(graph.get("topology") or {}),
                    )
                    if migrated is not None:
                        repaired += 1
                project = get_creative_project_store().get(str(project["id"])) or project
            if project_status not in {
                "draft", "clarifying", "ready_for_design", "designing"
            }:
                continue
            original_prompt = str(project.get("original_prompt") or "").strip()
            project_name = str(project.get("name") or "").strip()
            prompt = (
                original_prompt
                if original_prompt and recognize_drawing_template(original_prompt) is not None
                else project_name or original_prompt
            )
            if recognize_drawing_template(prompt) is None:
                continue
            normalized = parameterize_design(prompt)
            requirements = project.get("requirements")
            current = dict(requirements) if isinstance(requirements, dict) else {}
            merged = {**current, **{
                key: normalized.get(key)
                for key in (
                    "shape", "dimensions", "quantity", "printer", "origin",
                    "units", "assumptions", "template_components",
                    "arrangement", "spacing_m", "spacing_reference",
                )
                if normalized.get(key) is not None
            }}
            missing = list(normalized.get("missing") or [])
            if merged == current and missing == list(project.get("missing_parameters") or []):
                continue
            update_arguments: dict[str, Any] = {
                "requirements": merged,
                "event_message": "已自动补全标准图纸模板参数",
            }
            if project_status != "designing":
                update_arguments["missing_parameters"] = missing
            updated = get_creative_project_store().update(str(project["id"]), **update_arguments)
            if updated is not None:
                repaired += 1
        return repaired

    @staticmethod
    def enrich_result(
        result: dict[str, Any],
        route: dict[str, Any],
        knowledge: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from .agent_response_builder import normalize_acceptance_response
        enriched = normalize_acceptance_response(result)
        merge_structured_usage(enriched)
        # Creating a project only records the request. It is not evidence that
        # a design or executable path exists. Keep the user-facing answer in
        # sync with the durable project state returned by the tool.
        tool_results = enriched.get("tool_results")
        if isinstance(tool_results, list):
            for tool in tool_results:
                if not isinstance(tool, dict):
                    continue
                if tool.get("name") != "create_creative_project":
                    continue
                project_status = str(tool.get("project_status") or "")
                missing = [str(item) for item in tool.get("missing_parameters", [])]
                if project_status == "clarifying" or missing:
                    labels = {
                        "shape": "图形类型",
                        "dimensions": "关键尺寸",
                        "origin": "起点",
                        "printer": "喷码机",
                    }
                    missing_text = "、".join(labels.get(item, item) for item in missing)
                    enriched["message"] = (
                        "需求已记录，但还不能生成路径规划图纸。"
                        + (f"还缺少：{missing_text}。" if missing_text else "请补充图形和尺寸。")
                    )
                    enriched["design_ready"] = False
                    break
        live_context = RobotAgentService.runtime_context(route)
        enriched["agent_context"] = live_context
        message = str(enriched.get("message") or "")
        corrected, validation = validate_agent_answer(
            message,
            route,
            live_context,
            enriched.get("tool_results") if isinstance(enriched.get("tool_results"), list) else None,
            enriched.get("pending_action") if isinstance(enriched.get("pending_action"), dict) else None,
            {
                str(item.get("id"))
                for item in (knowledge or {}).get("matches", [])
                if isinstance(item, dict) and item.get("id")
            },
        )
        enriched["message"] = corrected
        enriched["answer_validation"] = validation
        if knowledge and knowledge.get("matches"):
            enriched["knowledge_sources"] = [
                {
                    key: item.get(key)
                    for key in (
                        "id", "title", "source", "line_start", "line_end", "score"
                    )
                }
                for item in knowledge["matches"]
            ]
        return enriched

    @staticmethod
    def _tool_result_summary(name: str, output: dict[str, Any]) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "name": name,
            "ok": output.get("ok") is True,
            "message": str(output.get("message") or ""),
        }
        for key in ("task_id", "task_state", "file_name", "project_id"):
            if output.get(key) is not None:
                summary[key] = output[key]
        if isinstance(output.get("layout_validation"), dict):
            summary["layout_validation"] = output["layout_validation"]
        if isinstance(output.get("path_preview"), dict):
            summary["path_preview"] = output["path_preview"]
            printing = output["path_preview"].get("printing_paths")
            if isinstance(printing, list) and printing:
                summary["preview_paths"] = printing
        project = output.get("project")
        if isinstance(project, dict) and project.get("id"):
            summary["project_id"] = project["id"]
            summary["project_name"] = project.get("name")
            summary["project_status"] = project.get("status")
            summary["missing_parameters"] = list(project.get("missing_parameters") or [])
            if project.get("selected_variant_id"):
                summary["variant_id"] = project["selected_variant_id"]
        variant = output.get("variant")
        if isinstance(variant, dict) and variant.get("id"):
            summary["variant_id"] = variant["id"]
            summary["variant_name"] = variant.get("name")
            preview = RobotAgentService._preview_contract_from_points(
                variant.get("preview_paths"), namespace="design_variant"
            )
            if preview:
                summary["preview_paths"] = preview
        if name == "get_robot_status":
            snapshot = output.get("status") if isinstance(output.get("status"), dict) else output
            summary["status"] = {
                key: snapshot.get(key)
                for key in (
                    "online", "control_ready", "emergency_stopped", "battery",
                    "localization_valid", "mission_stage", "printer_ready",
                )
                if key in snapshot
            }
        if isinstance(output.get("verification"), dict):
            verification = output["verification"]
            summary["verification"] = {
                "verified": verification.get("verified") is True,
                "status": verification.get("status", "unverified"),
                "reason_code": verification.get("reason_code"),
                "expected": verification.get("expected"),
                "retryable": verification.get("retryable"),
                "evidence": verification.get("evidence", []),
            }
        return summary

    @staticmethod
    def _verify_execution(
        name: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
        before: dict[str, Any],
    ) -> dict[str, Any]:
        """Validate a tool acknowledgement against live state, not text alone."""
        after = robot_state.snapshot()
        observed = RobotAgentService._verification_snapshot(after)
        evidence: list[str] = []
        if result.get("ok") is not True:
            return {
                "verified": False,
                "level": "failed",
                "evidence": ["工具返回失败"],
                "observed": observed,
            }
        if name == "get_robot_status":
            status = result.get("status") if isinstance(result.get("status"), dict) else result
            return {
                "verified": isinstance(status, dict),
                "level": "telemetry" if isinstance(status, dict) else "unverified",
                "evidence": ["已读取当前 robot_state 快照"] if isinstance(status, dict)
                else ["工具未返回状态对象"],
                "observed": observed,
            }
        if name in {
            "parameterize_design",
            "clarify_requirements",
            "create_creative_project",
            "update_creative_project",
            "select_design_variant",
            "prepare_project_plan",
            "refresh_project_plan",
            "refresh_project_execution",
            "assess_project_recovery",
            "prepare_project_recovery",
            "generate_project_report",
            "check_drawing_feasibility",
            "inspect_drawing",
            "list_elements",
            "diff_drawing",
            "validate_drawing",
            "snapshot_drawing",
            "analyze_geometry_topology",
            "layer_drawing_paths",
            "validate_preview_paths",
            "modify_drawing",
            "apply_cad_candidate_edit",
            "recommend_recovery",
        }:
            return {
                "verified": True,
                "level": "deterministic_result",
                "evidence": ["后端工具返回成功结果，属于本地确定性操作"],
                "observed": observed,
            }
        if name in {"drive_robot", "drive_sequence"}:
            command_changed = bool(
                after.get("last_velocity_command_at")
                and after.get("last_velocity_command_at")
                != before.get("last_velocity_command_at")
            )
            active = after.get("agent_motion_active") is True
            outcome = str(after.get("agent_motion_outcome") or "")
            if active:
                evidence.append("agent_motion_active=true")
            if command_changed:
                evidence.append("last_velocity_command_at 已更新")
            if outcome == "completed":
                evidence.append("agent_motion_outcome=completed")
                return {
                    "verified": True,
                    "level": "telemetry",
                    "evidence": evidence,
                    "observed": observed,
                }
            if outcome == "stopped":
                reason = str(after.get("agent_motion_completion_reason") or "运动被安全中止")
                operator_stop_reasons = {
                    "AI motion stopped by operator",
                    "AI stop tool requested",
                    "manual App control takeover",
                    "manual REST control takeover",
                }
                if reason in operator_stop_reasons:
                    return {
                        "verified": False,
                        "level": "cancelled",
                        "reason_code": "operator_cancelled",
                        "message": "已按你的要求停止小车运动。",
                        "evidence": evidence + ["agent_motion_outcome=stopped_by_operator"],
                        "observed": observed,
                    }
                return {
                    "verified": False,
                    "level": "failed",
                    "message": reason,
                    "evidence": evidence + [f"agent_motion_outcome=stopped：{reason}"],
                    "observed": observed,
                }
            return {
                "verified": False,
                "level": "in_progress" if active or command_changed else "unverified",
                "evidence": evidence or ["未观察到新的速度指令或运动状态"],
                "observed": observed,
            }
        if name == "printer_spray":
            printer = after.get("printer_status", {}).get(
                f"printer_{arguments.get('printer_name', 'center')}", {}
            )
            spraying = isinstance(printer, dict) and printer.get("spraying") is True
            state = printer.get("spray_state") if isinstance(printer, dict) else None
            if spraying:
                evidence.append("printer.spraying=true")
            if state:
                evidence.append(f"printer.spray_state={state}")
            expected = arguments.get("spraying") is True
            has_observation = isinstance(printer, dict) and (
                "spraying" in printer or state is not None
            )
            verified = (
                spraying
                if expected
                else has_observation and not spraying and state in {None, "idle", "stopped"}
            )
            return {
                "verified": verified,
                "level": "telemetry" if verified else "unverified",
                "evidence": evidence or ["未观察到喷码机状态变化"],
                "observed": observed,
            }
        if name == "control_printer":
            printer_name = str(arguments.get("printer_name") or "center")
            key = f"printer_{printer_name}"
            printer = after.get("printer_status", {}).get(key, {})
            previous = before.get("printer_status", {}).get(key, {})
            action = str(arguments.get("action") or "")
            if not isinstance(printer, dict) or printer.get("connected") is not True:
                return {
                    "verified": False,
                    "level": "failed",
                    "reason_code": "printer_disconnected",
                    "retryable": True,
                    "message": "喷码机未连接，无法验证操作结果。",
                    "expected": f"{key}.connected=true",
                    "evidence": ["喷码机实时状态为未连接或缺失"],
                    "observed": observed,
                }
            state = str(printer.get("spray_state") or "")
            if state == "error" or printer.get("error") or printer.get("spray_error"):
                error = str(printer.get("spray_error") or printer.get("error") or "未知错误")
                return {
                    "verified": False,
                    "level": "failed",
                    "reason_code": "printer_reported_error",
                    "retryable": False,
                    "message": f"喷码机报告错误：{error}",
                    "expected": "喷码机无错误并达到目标状态",
                    "evidence": [f"printer.error={error}"],
                    "observed": observed,
                }
            current_count = printer.get("print_count")
            previous_count = previous.get("print_count") if isinstance(previous, dict) else None
            count_increased = (
                isinstance(current_count, int)
                and isinstance(previous_count, int)
                and current_count > previous_count
            )
            if action in {"start_print", "test_print"}:
                active = printer.get("device_state") == 1
                verified = active and count_increased
                return {
                    "verified": verified,
                    "level": "telemetry" if verified else "unverified",
                    "expected": "device_state=1 且 print_count 增长",
                    "evidence": [
                        f"device_state={printer.get('device_state')}",
                        f"print_count={previous_count}->{current_count}",
                    ],
                    "observed": observed,
                }
            if action == "stop_print":
                stopped = printer.get("spraying") is not True and state in {
                    "", "idle", "stopped"
                }
                return {
                    "verified": stopped,
                    "level": "telemetry" if stopped else "unverified",
                    "expected": "spraying=false 且 spray_state=idle/stopped",
                    "evidence": [
                        f"spraying={printer.get('spraying')}",
                        f"spray_state={state or 'unknown'}",
                    ],
                    "observed": observed,
                }
            if action == "ink_level":
                level = printer.get("ink_level")
                verified = isinstance(level, (int, float))
                return {
                    "verified": verified,
                    "level": "telemetry" if verified else "unverified",
                    "expected": "喷码机返回数值型 ink_level",
                    "evidence": [f"ink_level={level}"],
                    "observed": observed,
                }
            return {
                "verified": False,
                "level": "acknowledged",
                "expected": f"喷码机为 {action} 返回可观测状态",
                "evidence": ["当前固件没有为该操作提供可验证反馈字段"],
                "observed": observed,
            }
        if name == "control_ln150":
            if after.get("ln150_ready") is not True:
                return {
                    "verified": False,
                    "level": "failed",
                    "reason_code": "ln150_unavailable",
                    "retryable": True,
                    "message": "全站仪节点未就绪，无法验证操作结果。",
                    "expected": "ln150_ready=true",
                    "evidence": ["ln150_ready=false"],
                    "observed": observed,
                }
            command_type = int(arguments.get("command_type") or 0)
            raw_status = str(after.get("ln150_status") or "")
            status = raw_status.lower()
            status_tokens = RobotAgentService._normalize_ln150_status(raw_status)
            source = str(after.get("localization_source") or "").lower()
            if command_type == 2:
                verified = bool(status_tokens & {"tracking", "auto_tracking"}) or (
                    after.get("localization_valid") is True and "ln150" in source
                )
                expected = "ln150_status=tracking/自动跟踪中 或有效的 LN150 定位"
            elif command_type == 3:
                verified = bool(status_tokens & {"leveled", "ready", "tracking"})
                expected = "ln150_status=leveled/ready/tracking/自动调平已完成"
            else:
                verified = bool(status_tokens & {"initialized", "ready", "tracking"})
                expected = "ln150_status=initialized/ready/tracking/设备已初始化"
            return {
                "verified": verified,
                "level": "telemetry" if verified else "unverified",
                "expected": expected,
                "evidence": [
                    f"ln150_ready={after.get('ln150_ready')}",
                    f"ln150_status={raw_status or 'unknown'}",
                    f"ln150_status_normalized={','.join(sorted(status_tokens)) or 'unknown'}",
                    f"localization_source={source or 'unknown'}",
                ],
                "observed": observed,
            }
        if name in {"set_mission", "execute_prepared_mission"}:
            running = after.get("mission_running") is True
            stage = str(after.get("mission_stage") or "")
            expected_running = name == "execute_prepared_mission" or arguments.get("running") is True
            has_observation = "mission_running" in after or bool(stage)
            expected_file = str(arguments.get("file_name") or "")
            observed_file = str(after.get("mission_file") or "")
            same_file = not expected_file or observed_file == expected_file
            if expected_running:
                if same_file and not running and stage == "cancelled":
                    return {
                        "verified": False,
                        "level": "cancelled",
                        "reason_code": "user_cancelled",
                        "retryable": False,
                        "message": "任务已由用户取消，未继续执行。",
                        "expected": (
                            f"任务 {expected_file or '当前图纸'} 执行结束，"
                            "mission_stage=completed 且 mission_running=false"
                        ),
                        "evidence": [
                            f"mission_file={observed_file or 'unknown'}",
                            "mission_stage=cancelled",
                            "mission_running=false",
                        ],
                        "observed": observed,
                    }
                verified = same_file and not running and stage == "completed"
                failed = stage in {"failed", "error"} or (
                    bool(observed_file)
                    and not same_file
                    and stage in {"executing", "paused", "completed"}
                )
                expected = (
                    f"任务 {expected_file or '当前图纸'} 执行结束，"
                    "mission_stage=completed 且 mission_running=false"
                )
            else:
                verified = (
                    has_observation
                    and not running
                    and stage in {"idle", "cancelled", "completed"}
                )
                failed = False
                expected = "任务停止，mission_running=false"
            return {
                "verified": verified,
                "level": "failed" if failed else "telemetry" if verified else "unverified",
                "expected": expected,
                "evidence": [
                    f"mission_file={observed_file or 'unknown'}",
                    f"mission_stage={stage or 'unknown'}",
                    f"mission_running={running}",
                ],
                "observed": observed,
            }
        if name == "stop_robot":
            stopped = after.get("agent_motion_active") is False
            return {
                "verified": stopped,
                "level": "telemetry" if stopped else "unverified",
                "evidence": ["agent_motion_active=false"] if stopped else ["运动状态仍为 active"],
                "observed": observed,
            }
        return {
            "verified": False,
            "level": "acknowledged",
            "evidence": ["工具返回已接受，但没有对应的状态字段可核验"],
            "observed": observed,
        }

    @staticmethod
    def _normalize_ln150_status(raw_status: str) -> set[str]:
        status = str(raw_status or "").strip().lower()
        if not status:
            return set()
        failure_markers = (
            "失败", "中断", "丢失", "超限", "异常", "错误",
            "请先初始化", "not ready", "failed", "error", "lost",
        )
        if any(marker in status for marker in failure_markers):
            return set()

        tokens: set[str] = set()
        if any(
            marker in status
            for marker in (
                "initialized", "设备已初始化", "初始化成功", "初始化完成",
                "设备初始化完成", "等待跟踪指令",
            )
        ):
            tokens.update({"initialized", "ready"})
        if any(
            marker in status
            for marker in (
                "leveled", "levelled", "自动调平已完成", "调平完成",
                "自动调平：完成",
            )
        ):
            tokens.update({"leveled", "ready"})
        if any(
            marker in status
            for marker in (
                "tracking", "auto_tracking", "自动跟踪中", "跟踪功能正常",
                "请使用棱镜或靶球作为照准目标", "开启自动跟踪",
            )
        ):
            tokens.update({"tracking", "auto_tracking", "ready"})
        if "ready" in status or "就绪" in status:
            tokens.add("ready")
        return tokens

    @staticmethod
    def _validate_tool_result(
        name: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
        before: dict[str, Any],
    ) -> dict[str, Any]:
        verification = RobotAgentService._verify_execution(
            name, arguments, result, before
        )
        physical = name in {
            "drive_robot", "drive_sequence", "stop_robot", "set_mission",
            "execute_prepared_mission", "control_ln150", "control_printer",
            "printer_spray",
        }
        if result.get("ok") is not True:
            status = "failed"
        elif verification.get("level") == "cancelled":
            status = "cancelled"
        elif verification.get("level") == "failed":
            status = "failed"
        elif verification.get("verified") is True:
            status = "success"
        elif physical:
            status = "pending"
        else:
            status = "unverified"
        return {
            **verification,
            "status": status,
            "tool": name,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _verification_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
        """Persist only evidence fields; maps and logs do not prove tool success."""
        return {
            key: snapshot.get(key)
            for key in (
                "online", "ros_available", "control_ready", "emergency_stopped",
                "agent_motion_active", "agent_motion_remaining_ms",
                "agent_motion_started_at", "agent_motion_completed_at",
                "agent_motion_completion_reason", "agent_motion_outcome",
                "last_velocity_command_at", "mission_running", "mission_stage",
                "mission_file", "mission_completed", "mission_total",
                "mission_current_id", "printer_ready", "printer_status",
                "printer_status_age_ms", "ln150_ready", "ln150_status",
                "localization_valid", "localization_source",
            )
        }

    def _execute_safe(
        self, name: str, arguments: dict[str, Any], *, mode: str = "base"
    ) -> dict[str, Any]:
        # Keep every model-visible tool result on the same verification path.
        # Resolve the repository dynamically at the tool boundary.
        project_store = get_creative_project_store()
        # The confirmation path already does this; safe/read-only tools must not
        # silently become an unverified exception.
        before_snapshot = robot_state.snapshot()
        policy = agent_tool_policy(name, mode)
        if not policy["allowed"]:
            result = {"ok": False, "message": policy["reason"], "policy": policy}
            agent_audit.append("mode_policy_blocked", name, arguments, result)
            return result
        decision = authorize_tool(name, arguments, confirmed=True)
        if not decision.allowed:
            result = {"ok": False, "message": decision.message}
            agent_audit.append("safe_tool_blocked", name, arguments, result)
            return result
        if name == "get_robot_status":
            result = {
                "ok": True,
                "message": "已读取小车实时状态。",
                "status": {
                    key: value for key, value in robot_state.snapshot().items()
                    if not key.startswith("obstacle_")
                },
            }
        elif name == "stop_robot":
            ok = ros_adapter.stop_agent_motion("AI stop tool requested")
            result = {"ok": ok, "message": "停车指令已发送"}
        elif name == "parameterize_design":
            result = parameterize_design(str(arguments["prompt"]))
        elif name == "clarify_requirements":
            result = clarify_requirements(str(arguments["prompt"]))
        elif name == "create_creative_project":
            requirements = parameterize_design(str(arguments["prompt"]))
            requirements, missing = normalize_design_requirements(
                requirements, str(arguments["prompt"])
            )
            project = get_creative_project_store().create(
                str(arguments["name"]),
                str(arguments["prompt"]),
                requirements,
                dict(arguments.get("constraints") or {}),
                missing,
            )
            result = {"ok": True, "project": project}
        elif name == "update_creative_project":
            project_id = str(arguments["project_id"])
            # Models can echo a project id from an earlier conversation turn.
            # When the active isolated store contains exactly one copied
            # project, preserve the routed project context instead of turning
            # a valid template edit into a false "project not found" and a
            # second create operation.
            raw_requirements = (
                dict(arguments["requirements"])
                if isinstance(arguments.get("requirements"), dict)
                else None
            )
            existing_project = get_creative_project_store().get(project_id)
            if not isinstance(existing_project, dict):
                return {"ok": False, "message": "创意项目不存在", "project_id": project_id}
            # Tool arguments are a partial update. Validate the merged state,
            # otherwise an orientation-only follow-up erases saved dimensions
            # from the completeness decision even though storage retains them.
            previous_requirements = dict(existing_project.get("requirements") or {})
            incoming_requirements = raw_requirements or {}
            raw_requirements = {**previous_requirements, **incoming_requirements}
            for field in ("dimensions", "dimension_bounds"):
                if isinstance(incoming_requirements.get(field), dict):
                    raw_requirements[field] = {
                        **dict(previous_requirements.get(field) or {}),
                        **incoming_requirements[field],
                    }
            prompt = str(arguments.get("prompt") or "")
            if not prompt:
                existing_project = get_creative_project_store().get(project_id)
                if isinstance(existing_project, dict):
                    prompt = str(existing_project.get("original_prompt") or "")
            requirements, normalized_missing = normalize_design_requirements(
                raw_requirements, prompt
            )
            model_missing = (
                list(arguments["missing_parameters"])
                if isinstance(arguments.get("missing_parameters"), list)
                else []
            )
            preserved = [
                item
                for item in model_missing
                if str(item) not in {"shape", "dimensions"}
            ]
            # 模型显式声明 missing_parameters 时尊重其确认（模型已与用户
            # 确认图形/参数完整，构造或直投类图形的 shape 可能不是枚举值）；
            # 但 shape/dimensions 在 requirements 中确实缺失时仍保留，
            # 防止模型误清导致假就绪。未显式声明时维持原逻辑
            # （规范化结果 + 模型要求项原样保留）。
            if "missing_parameters" in arguments:
                model_missing = [
                    str(item) for item in model_missing
                    if str(item) not in {"shape", "dimensions"}
                ]
                still_missing = [
                    key for key in ("shape", "dimensions")
                    if not requirements.get(key)
                ]
                missing = list(
                    dict.fromkeys(model_missing + still_missing)
                )
            else:
                missing = list(
                    dict.fromkeys(
                        [str(item) for item in normalized_missing]
                        + [str(item) for item in preserved]
                    )
                )
            project = get_creative_project_store().update(
                project_id,
                requirements=requirements,
                constraints=(dict(arguments["constraints"])
                             if isinstance(arguments.get("constraints"), dict) else None),
                missing_parameters=missing,
                event_message="AI 补充了项目需求",
            )
            result = ({"ok": True, "project": project} if project is not None
                      else {"ok": False, "message": "创意项目不存在"})
        elif name == "select_design_variant":
            project = get_creative_project_store().select_variant(
                str(arguments["project_id"]), str(arguments["variant_id"])
            )
            result = ({"ok": True, "project": project} if project is not None
                      else {"ok": False, "message": "项目或候选方案不存在"})
        elif name == "prepare_project_plan":
            result = prepare_project_plan(str(arguments["project_id"]))
        elif name == "refresh_project_plan":
            result = refresh_project_plan(str(arguments["project_id"]))
        elif name == "refresh_project_execution":
            result = refresh_project_execution(str(arguments["project_id"]))
        elif name == "assess_project_recovery":
            result = project_recovery_assessment(str(arguments["project_id"]))
        elif name == "prepare_project_recovery":
            result = prepare_project_recovery(str(arguments["project_id"]))
        elif name == "generate_project_report":
            result = build_project_acceptance_report(str(arguments["project_id"]))
        elif name == "check_drawing_feasibility":
            result = check_drawing_feasibility(list(arguments["geometries"]))
        elif name == "inspect_drawing":
            result = inspect_drawing(list(arguments["geometries"]))
        elif name == "list_elements":
            result = list_elements(
                list(arguments["geometries"]),
                instance_ids=list(arguments.get("instance_ids") or []),
                semantic=arguments.get("semantic"),
            )
        elif name == "diff_drawing":
            result = diff_drawings(
                list(arguments["source_geometries"]),
                list(arguments["target_geometries"]),
            )
        elif name == "validate_drawing":
            result = validate_drawing(list(arguments["geometries"]))
        elif name == "snapshot_drawing":
            result = snapshot_drawing(
                list(arguments["geometries"]), str(arguments.get("label") or "")
            )
        elif name == "inspect_drawing_metadata":
            file_name = str(arguments["file_name"])
            target = resolve_drawing(file_name)
            if target is None:
                result = {"ok": False, "message": "图纸不存在或文件名无效。"}
            else:
                try:
                    payload = json.loads(target.read_text(encoding="utf-8"))
                    geometries = payload.get("lines") if isinstance(payload, dict) else []
                    result = {
                        "ok": True,
                        "file_name": file_name,
                        "schema_version": payload.get("schema_version"),
                        "source_format": payload.get("source_format", "xline_json"),
                        "unit": payload.get("unit", "mm"),
                        "layers": payload.get("layers", []),
                        "cad_analysis": payload.get("cad_analysis", {}),
                        "feasibility": check_drawing_feasibility(
                            geometries if isinstance(geometries, list) else []
                        ),
                        "topology": analyze_geometry_topology(
                            geometries if isinstance(geometries, list) else []
                        ),
                    }
                except (OSError, ValueError, TypeError) as exc:
                    result = {"ok": False, "message": f"图纸元数据读取失败：{exc}"}
        elif name == "analyze_geometry_topology":
            result = analyze_geometry_topology(list(arguments["geometries"]))
        elif name == "layer_drawing_paths":
            result = layer_drawing_paths(
                list(arguments["geometries"]), str(arguments["printer"])
            )
            result["ok"] = True
        elif name == "validate_preview_paths":
            result = validate_preview_paths(list(arguments["paths"]))
        elif name == "recommend_recovery":
            result = recommend_recovery(robot_state.snapshot())
        else:
            result = {"ok": False, "message": f"安全工具尚未实现：{name}"}
        if not isinstance(result, dict):
            result = {"ok": False, "message": "工具返回了无效结果。"}
        # A tool acknowledgement is never enough for a hardware operation.
        # Deterministic local operations are marked verified by the same
        # verifier, while hardware operations require fresh state evidence.
        result["verification"] = self._validate_tool_result(
            name, arguments, result, before_snapshot
        )
        agent_audit.append("safe_tool_executed", name, arguments, result)
        self._remember_advanced_case(name, arguments, result)
        return result

    @staticmethod
    def _remember_advanced_case(
        name: str, arguments: dict[str, Any], result: dict[str, Any]
    ) -> None:
        """Store only project-scoped advanced-agent outcomes, never base motion demos."""
        if name in {"drive_robot", "drive_sequence", "stop_robot"}:
            return
        project_id = arguments.get("project_id")
        if not project_id and isinstance(result.get("project"), dict):
            project_id = result["project"].get("id")
        if not project_id:
            project_id = result.get("project_id")
        if not project_id:
            return
        category = (
            "design" if any(word in name for word in ("design", "drawing", "variant", "parameter"))
            else "planning" if "plan" in name
            else "recovery" if "recover" in name
            else "execution" if "execution" in name or name == "request_execution"
            else "acceptance" if "report" in name or "accept" in name
            else "project"
        )
        try:
            xline_database.record_ai_case(
                str(project_id), category, name, arguments, result
            )
        except Exception:
            # Case memory must never break a tool result or motion safety path.
            return

    def _execute_confirmed(
        self, action: PendingAction, *, client_id: str | None = None
    ) -> dict[str, Any]:
        raw_arguments = action.arguments
        if action.name == "modify_drawing":
            raw_arguments = self._normalize_legacy_modify_arguments(raw_arguments)
        args, validation_error = validate_tool_arguments(action.name, raw_arguments)
        if args is None:
            return {"ok": False, "message": validation_error}
        if action.name == "modify_drawing":
            args = self._drop_none_values(args)
        decision = authorize_tool(
            action.name, args, confirmed=True, client_id=client_id
        )
        if not decision.allowed:
            return {"ok": False, "message": decision.message}
        if action.name == "apply_cad_candidate_edit":
            project_id = str(args["project_id"])
            parent_variant_id = str(args["parent_variant_id"])
            project = get_creative_project_store().get(project_id)
            if not isinstance(project, dict) or project.get("status") != "designing":
                return {"ok": False, "message": "图纸项目已不在编辑状态，请重新打开候选方案。"}
            if str(project.get("design_base_variant_id") or "") != parent_variant_id:
                return {"ok": False, "message": "当前优化基准已变化，本次确认已失效，请重新发出修改指令。"}
            parent = next((
                item for item in project.get("variants") or []
                if isinstance(item, dict) and str(item.get("id") or "") == parent_variant_id
            ), None)
            source = parent.get("geometries") if isinstance(parent, dict) else None
            if not isinstance(source, list):
                return {"ok": False, "message": "父候选图纸不存在，不能应用修改。"}
            if geometry_fingerprint(source) != str(args["parent_geometry_sha256"]):
                return {"ok": False, "message": "父候选内容已变化，本次确认已失效，请重新预览修改。"}
            split_target_validation = validate_split_shared_boundary_target(
                dict(args["edit_contract"]),
                source,
                list(parent.get("logical_objects") or []),
                dict(parent.get("topology") or {}),
            )
            if split_target_validation.get("ok") is not True:
                return {
                    "ok": False,
                    "message": str(split_target_validation.get("message") or "共享边界拆分目标复核失败。"),
                    "split_target_validation": split_target_validation,
                }
            submitted_contract = dict(args["edit_contract"])
            counterfactual_validation = validate_counterfactual_guard_report(
                submitted_contract
            )
            if counterfactual_validation["verified"] is not True:
                return {
                    "ok": False,
                    "message": "反事实保护证据缺失或已变化，请重新发出修改指令并预览。",
                    "counterfactual_validation": counterfactual_validation,
                }
            chain_replay: list[dict[str, Any]] | None = None
            edit: dict[str, Any] | None = None
            if submitted_contract.get("operation") == "chain":
                geometries, error, chain_replay = replay_cad_edit_chain(
                    source, submitted_contract
                )
                if geometries is None:
                    return {
                        "ok": False,
                        "message": error or "确认后的复合图纸修改无法执行。",
                        "chain_replay": chain_replay,
                        "rollback_evidence": build_rejection_rollback_evidence(
                            source, error or "复合修改重放失败"
                        ),
                    }
                contract = submitted_contract
            else:
                try:
                    edit = cad_edit_contract_to_edit(submitted_contract)
                except (TypeError, ValueError) as error:
                    return {"ok": False, "message": f"CAD 修改协议无效：{error}"}
                geometries, error = edit_candidate_geometries(source, edit)
                if geometries is None:
                    return {"ok": False, "message": error or "确认后的图纸修改无法执行。"}
                contract = build_cad_edit_contract(
                    edit,
                    source_text=str(submitted_contract.get("source_text") or ""),
                )
            preflight = build_cad_edit_preflight(source, geometries, contract)
            if not preflight["ready"]:
                details = "；".join(
                    item["detail"] for item in preflight["checks"]
                    if item.get("ok") is not True
                )
                reason = f"确认后复核未通过：{details}"
                return {
                    "ok": False,
                    "message": reason,
                    "cad_preflight": preflight,
                    "rollback_evidence": build_rejection_rollback_evidence(
                        source, reason
                    ),
                }
            if not isinstance(args.get("edit_preview"), dict):
                return {
                    "ok": False,
                    "message": "该确认请求缺少修改前预演，请重新发出修改指令。",
                }
            preview_validation = validate_cad_edit_preview(
                dict(args["edit_preview"]),
                source,
                geometries,
                contract,
                preflight=preflight,
            )
            if preview_validation["verified"] is not True:
                reason = "确认结果与修改前预演不一致，本次确认已失效，请重新预览修改。"
                return {
                    "ok": False,
                    "message": reason,
                    "preview_validation": preview_validation,
                    "rollback_evidence": build_rejection_rollback_evidence(source, reason),
                }
            edit_preview = dict(preview_validation["preview"])
            operation = str(contract.get("operation") or "")
            targets = (
                list((contract.get("target") or {}).get("instance_ids") or [])
                if operation == "chain"
                else edit.get("instances") or (
                    [edit["instance"]] if isinstance(edit.get("instance"), int) else []
                )
            )
            target_text = "、".join(str(value) for value in targets) or "选中"
            edit_payload = edit or {}
            description = {
                "delete": f"删除第 {target_text} 个图形",
                "retain": f"仅保留第 {target_text} 个图形",
                "scale": f"第 {target_text} 个图形缩放到 {edit_payload.get('factor')} 倍",
                "translate": f"第 {target_text} 个图形平移",
                "rotate": f"第 {target_text} 个图形旋转 {edit_payload.get('angle_degrees')} 度",
                "resize": f"第 {target_text} 个图形尺寸调整",
                "duplicate": f"复制第 {target_text} 个图形",
                "align": f"第 {target_text} 个图形对齐",
                "chain": "按顺序应用复合图纸修改",
            }.get(operation, "应用图纸修改")
            source_groups = {
                item.get("template_instance") for item in source
                if isinstance(item.get("template_instance"), int)
            }
            result_groups = {
                item.get("template_instance") for item in geometries
                if isinstance(item.get("template_instance"), int)
            }
            changes_quantity = operation in {"duplicate", "delete", "retain"} and (
                source_groups != result_groups
            )
            result = self._persist_candidate_edit(
                project, parent, geometries, description,
                expected_quantity=len(result_groups) if changes_quantity else None,
                instance_edit_operation=operation if changes_quantity else None,
                cad_edit_contract=contract,
                edit_preview=edit_preview,
            )
            if result.get("ok") is True:
                result.update({
                    "cad_edit_contract": contract,
                    "cad_preflight": preflight,
                    "edit_preview": (
                        result.get("variant", {}).get("edit_preview")
                        if isinstance(result.get("variant"), dict)
                        else edit_preview
                    ) or edit_preview,
                    "preview_validation": preview_validation,
                    "counterfactual_validation": counterfactual_validation,
                    "confirmed_high_risk_edit": True,
                })
                if chain_replay is not None:
                    result.update({
                        "chain_replay": chain_replay,
                        "edit_chain": {
                            "schema": "cad.edit-chain.v1",
                            "atomic": True,
                            "step_count": len(contract.get("chain_steps") or []),
                            "steps": contract.get("chain_steps") or [],
                        },
                    })
            return result
        if action.name == "modify_drawing":
            prepared = self._prepare_drawing_modification(args)
            if prepared.get("ok") is not True:
                return prepared
            source_file_name = str(prepared["source_file_name"])
            source_sha256 = str(prepared["source_sha256"])
            source_lines = list(prepared["source_lines"])
            tracked_latest = prepared.get("tracked_latest")
            operation_id = str(prepared.get("operation_id") or "")
            modification = dict(prepared["modification"])
            geometries = list(prepared["geometries"])
            feasibility = dict(prepared["feasibility"])
            diff = dict(prepared["geometry_diff"])
            path_impact = dict(prepared["path_impact"])
            scope_validation = prepared.get("scope_validation")
            payload = dict(prepared["payload"])
            preview = list(prepared["final_preview_paths"])
            try:
                version = drawing_versions.save(
                    cad_directory(), source_file_name, payload, "agent_modify",
                    f"基于 {source_file_name} 局部修改：新增 {diff['counts']['added']}，删除 {diff['counts']['removed']}，修改 {diff['counts']['modified']}",
                    {
                        "parent_file_name": source_file_name,
                        "source_sha256": source_sha256,
                        "source_version": int(tracked_latest["version"]) if tracked_latest else None,
                        "operation_id": operation_id or None,
                        "geometry_diff": diff,
                        "path_impact": path_impact,
                        "scope_validation": scope_validation,
                    },
                )
            except DuplicateDrawingOperationError as duplicate:
                return {
                    "ok": False,
                    "message": f"该修改操作已处理，未重复创建版本：{duplicate.item['file_name']}",
                    "duplicate": True,
                    "version": duplicate.item,
                }
            file_name = str(version["file_name"])
            affected_paths = path_impact["affected_paths"]
            review = build_drawing_change_review(
                source_file_name,
                file_name,
                diff,
                path_impact,
                feasibility,
                source_sha256=source_sha256,
                source_version=int(tracked_latest["version"]) if tracked_latest else None,
            )
            review["scope_validation"] = scope_validation
            path_preview = build_path_preview_contract(
                payload,
                file_name=file_name,
                source_file_name=source_file_name,
            )
            robot_state.add_log(f"agent modified drawing {source_file_name} -> {file_name}")
            return {
                "ok": True,
                "message": f"已基于 {source_file_name} 保存修改版本 {file_name}。请复核差异和路径后再规划。",
                "file_name": file_name,
                "source_file_name": source_file_name,
                "source_sha256": source_sha256,
                "drawing_json": payload,
                "commands": modification.get("commands", []),
                "command_batch": modification.get("command_batch"),
                "path_preview": path_preview,
                "preview_paths": preview,
                "geometry_diff": diff,
                "path_impact": path_impact,
                "scope_validation": scope_validation,
                "review": review,
                "affected_paths": affected_paths,
                "risks": list(dict.fromkeys(
                    feasibility["warnings"]
                    + (["图纸修改影响喷印路径，必须重新规划后才能执行"] if path_impact["requires_replan"] else [])
                    + (["存在删除的喷印路径，执行前必须人工确认任务顺序"] if path_impact["risk_level"] == "high" else [])
                )),
                "feasibility": feasibility,
                "version": version,
                "next_action": "plan_preview",
            }
        if action.name == "drive_robot":
            if not robot_state.control_ready:
                return {"ok": False, "message": "CAN 接口或电机节点未就绪，操作已阻止。"}
            semantic_linear = float(args["linear"])
            semantic_angular = float(args["angular"])
            ok = ros_adapter.publish_timed_velocity(
                semantic_linear,
                semantic_angular,
                float(args["duration_seconds"]),
            )
            duration = float(args["duration_seconds"])
            return {
                "ok": ok,
                "agent_motion_active": ok,
                "estimated_duration_seconds": duration,
                "motion_started_at": robot_state.agent_motion_started_at,
                "message": f"AI 运动指令已提交；将持续 {duration:.1f} 秒后自动停车，可随时手动停止。",
            }
        if action.name == "drive_sequence":
            steps = [
                {
                    "linear": float(step["linear"]),
                    "angular": float(step["angular"]),
                    "duration_seconds": float(step["duration_seconds"]),
                }
                for step in args["steps"]
            ]
            ok = ros_adapter.publish_velocity_sequence(steps)
            duration = sum(step["duration_seconds"] for step in steps)
            return {
                "ok": ok,
                "agent_motion_active": ok,
                "estimated_duration_seconds": duration,
                "motion_started_at": robot_state.agent_motion_started_at,
                "message": (
                    f"AI 多段运动已提交，共 {len(steps)} 段、约 {duration:.1f} 秒；"
                    "将按顺序执行，可随时手动停止。"
                ),
            }
        if action.name == "set_mission":
            if bool(args["running"]) and not robot_state.mission_nodes_ready:
                return {"ok": False, "message": "任务节点未全部就绪，启动已阻止。"}
            file_name = str(args["file_name"])
            if bool(args["running"]) and resolve_drawing(file_name) is None:
                return {"ok": False, "message": f"图纸不存在或文件名无效：{file_name}"}
            if bool(args["running"]):
                ready, reason = drawing_execution_ready(file_name)
                if not ready:
                    return {"ok": False, "message": reason}
            ok = ros_adapter.control_mission(bool(args["running"]), file_name)
            return {"ok": ok, "message": "任务指令已发送。" if ok else robot_state.mission_error or "任务请求被拒绝。"}
        if action.name == "execute_prepared_mission":
            file_name = str(args["file_name"])
            ok = ros_adapter.execute_prepared_mission(file_name)
            return {
                "ok": ok,
                "message": "已开始执行确认过的规划路径。" if ok else robot_state.mission_error,
            }
        if action.name == "control_ln150":
            ok = ros_adapter.call_ln150(int(args["command_type"]))
            return {"ok": ok, "message": "LN150 指令已提交。" if ok else "LN150 服务不可用。"}
        if action.name == "control_printer":
            ok = ros_adapter.call_printer(
                str(args["printer_name"]),
                str(args["action"]),
                int(args["param"]),
            )
            return {"ok": ok, "message": "喷码机指令已提交。" if ok else "喷码机服务不可用。"}
        if action.name == "printer_spray":
            printer_name = str(args["printer_name"])
            spraying = bool(args["spraying"])
            if spraying:
                if not ros_adapter.ensure_printer_active(printer_name, timeout=3.0):
                    return {"ok": False, "message": "喷码机激活服务不可用。"}
                ok = ros_adapter.call_printer(
                    printer_name,
                    "test_print",
                    0,
                    allow_activation_race=True,
                    auto_stop_test_print=False,
                    manual_spray=True,
                )
                return {
                    "ok": ok,
                    "message": "已打开持续喷墨，可同时控制小车移动。"
                    if ok
                    else "喷墨启动失败，请检查喷码机连接和墨路。",
                }
            stop_ok = ros_adapter.call_printer(printer_name, "stop_print", 0)
            return {
                "ok": stop_ok,
                "message": "已停止喷墨。" if stop_ok else "停止喷墨失败。",
            }
        return {"ok": False, "message": "不支持的 Agent 操作。"}

    @staticmethod
    def _arguments(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        try:
            parsed = json.loads(str(value or "{}"))
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _advanced_project_context(
        self, project_id: str | None = None, *, allow_latest: bool = True
    ) -> str:
        """Return a small, deterministic workflow context for advanced mode."""
        project = get_creative_project_store().get(project_id) if project_id else None
        if project is None and project_id:
            return f"当前会话记忆中的项目 {project_id} 已不存在，请用户重新选择项目。"
        if project is None and allow_latest:
            projects = get_creative_project_store().list(limit=1)
            project = projects[0] if projects else None
        if project is None:
            return (
                "当前进阶流程：需求采集。还没有项目；先理解用户目标，最多追问一个"
                "最关键的缺失参数，不要检查急停或要求执行确认。"
            )
        status = str(project.get("status") or "draft")
        missing = [str(item) for item in (project.get("missing_parameters") or [])]
        variants = project.get("variants") or []
        selected = project.get("selected_variant_id")
        design_base = project.get("design_base_variant_id")
        selected_variant = next(
            (item for item in variants if item.get("id") == selected),
            None,
        )
        design_base_variant = next(
            (item for item in variants if item.get("id") == design_base),
            None,
        )
        plan = project.get("plan") or {}
        if status in {"draft", "clarifying"} or missing:
            stage = "需求采集"
            next_step = "只询问一个最关键的缺失参数，并说明用途"
        elif status == "ready_for_design" or not variants:
            stage = "候选方案"
            next_step = "根据完整参数自动生成至少一个候选方案，并展示可修改项"
        elif not selected or status == "designing":
            stage = "方案选择或修改"
            next_step = "请用户选择候选方案，或确认要修改的尺寸/形状"
        elif not plan or status in {"ready_for_planning", "planning"}:
            stage = "图纸检查与路径规划"
            next_step = "检查图纸完整性后生成 xline_ws3 规划预览，不启动小车"
        elif status == "planning_ready" or status == "pending_execution":
            stage = "执行确认"
            next_step = "展示规划摘要并等待用户明确确认；此时才检查急停、定位和设备"
        elif status in {"executing", "paused"}:
            stage = "任务执行"
            next_step = "同步当前分段状态；异常时提供恢复选项，不重复执行已完成分段"
        else:
            stage = "验收与归档"
            next_step = "对比规划轨迹与实测轨迹，生成验收报告并允许复盘"
        context = (
            f"当前进阶项目：{project.get('name') or '未命名项目'}；项目状态：{status}；"
            f"当前步骤：{stage}；下一步只能是：{next_step}。"
            f"缺失参数：{', '.join(missing) if missing else '无'}；候选方案数：{len(variants)}。"
            f"当前选中方案：{selected_variant.get('name') if selected_variant else '无'}"
            f"（ID：{selected or '无'}）；当前优化基准：{design_base_variant.get('name') if design_base_variant else '无'}"
            f"（ID：{design_base or '无'}）。若当前优化基准存在，新增方案会由后端自动继承该方案。"
            "不要跳过当前步骤，不要在设计阶段提示急停或要求用户确认执行。"
            "已有候选方案时，复制、平移、并排、再加一个相同图形等增量请求"
            "只需表达结构化修改意图；候选几何和保存由后端 CAD 管线完成。"
            "用户补充参数时，即使还有其他参数缺失，也必须立即调用 "
            "update_creative_project 把已理解并确定的部分（shape、dimensions/"
            "dimension_bounds、units 等）写入 requirements，并用 "
            "missing_parameters 声明仍缺的项；禁止只在聊天文本里复述已确定的"
            "图形与尺寸而不落库。用户确认图形与参数（含坐标单位）后，必须调用 "
            "update_creative_project 把完整 requirements（shape/dimensions/units 等）"
            "写入项目并传 missing_parameters=[]，把项目推进到 ready_for_design；"
            "单位确认（坐标单位为米/毫米等）也要写入 requirements.units。"
        )
        active_variant = self._effective_parent_variant(project)
        geometries = active_variant.get("geometries") if isinstance(active_variant, dict) else None
        if isinstance(geometries, list) and geometries:
            catalog = build_geometry_catalog(
                geometries,
                source={
                    "kind": "project_variant",
                    "project_id": project.get("id"),
                    "variant_id": active_variant.get("id"),
                    "variant_name": active_variant.get("name"),
                },
                topology=(
                    active_variant.get("topology")
                    if isinstance(active_variant, dict) else None
                ),
            )
            context += (
                "\n当前优化基准的图元语义目录如下。修改前必须先从目录定位目标，"
                "最终工具参数仍使用稳定 geometry_id 或 instance_id；"
                "semantic_source 不是 explicit 时只是确定性辅助描述，存在多个同名候选必须追问或要求画布点选。\n"
                + json.dumps(catalog, ensure_ascii=False, separators=(",", ":"))
            )
        return context

    @staticmethod
    def _selected_drawing_catalog(selection: dict[str, Any]) -> dict[str, Any] | None:
        file_name = str(selection.get("source_file_name") or "")
        source_path = resolve_drawing(file_name)
        if source_path is None:
            return None
        try:
            payload = json.loads(source_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        geometries = payload.get("lines") if isinstance(payload, dict) else None
        if not isinstance(geometries, list) or not geometries:
            return None
        layer_names = None
        layers = payload.get("layers")
        if isinstance(layers, list):
            layer_names = {
                int(record["id"]): str(record["name"])
                for record in layers
                if isinstance(record, dict)
                and isinstance(record.get("id"), int)
                and str(record.get("name") or "").strip()
            } or None
        return build_geometry_catalog(
            geometries,
            source={
                "kind": "drawing_file",
                "file_name": file_name,
                "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
                "selected_geometry_ids": list(selection.get("geometry_ids") or []),
                "selection_scope": selection.get("scope"),
            },
            layer_names=layer_names,
            topology=payload.get("topology"),
        )

    def _system_context(
        self,
        message: str = "",
        *,
        mode: str = "base",
        route: dict[str, Any] | None = None,
    ) -> str:
        snapshot = robot_state.snapshot()
        text = message.lower()
        active_route = route or self.route_intent(message, mode)
        live_context = self.runtime_context(active_route)
        knowledge = self.knowledge_context(message, active_route)
        context = (
            SYSTEM_PROMPT
            + "\n只回答当前问题，先给结论，避免重复说明。"
            + "\n这是本次请求开始时读取的实时设备上下文；null 表示后端没有收到该数据，禁止猜测：\n"
            + json.dumps(live_context, ensure_ascii=False)
        )
        retrieved_memory = active_route.get("retrieved_memory")
        if isinstance(retrieved_memory, dict) and retrieved_memory.get("relevant"):
            context += (
                "\n以下是当前会话中与本轮问题相关的持久化记忆。"
                "confirmed_requirements 已由用户确认，可以沿用；pending_requirements 尚未确认，"
                "只能用于请求用户确认，禁止据此执行或覆盖已确认值。"
                "摘要仅用于保持上下文，不得向用户复述内部字段：\n"
                + json.dumps(retrieved_memory, ensure_ascii=False)
            )
        object_memory = active_route.get("object_memory")
        workflow_state = (
            object_memory.get("workflow_state")
            if isinstance(object_memory, dict) else None
        )
        if isinstance(workflow_state, dict):
            context += (
                "\n以下是后端维护的结构化会话状态，是当前阶段、活动对象和待回答事项的"
                "权威记录。优先按 active 中的稳定 ID 和 pending.expected_response 理解‘确认’、"
                "‘继续’、‘它’等短回复；不得从旧聊天文本恢复与该状态冲突的目标。"
                "不得向用户展示内部字段名或哈希：\n"
                + json.dumps(workflow_state, ensure_ascii=False)
            )
        drawing_selection = active_route.get("drawing_selection")
        if isinstance(drawing_selection, dict):
            context += (
                "\n以下图纸选区由图纸编辑器提供，是本轮修改的唯一权威目标。"
                "source_file_name、scope 和 geometry_ids 不得改写或猜测；"
                "用户所说的‘这个’、‘选中的线段’或‘当前图形’只指这些 ID。"
                "调用 modify_drawing 时必须使用 target + operations 协议，target 只能绑定这些 ID；"
                "update 必须提供 geometry_id 和最小 patch，禁止为了局部修改重写整张图纸；"
                "只能更新或删除选区内图元；"
                "若要新增图元，必须同时实际修改至少一个选中图元：\n"
                + json.dumps(drawing_selection, ensure_ascii=False)
            )
            selection_catalog = self._selected_drawing_catalog(drawing_selection)
            if selection_catalog is not None:
                context += (
                    "\n当前源图纸的图元语义目录如下。选区仍是唯一权威修改范围；"
                    "目录仅用于理解选中 ID 的类型、语义和实例归属，禁止借此扩大目标范围：\n"
                    + json.dumps(selection_catalog, ensure_ascii=False, separators=(",", ":"))
                )
        live_quality = live_context.get("quality")
        freshness_gate = (
            live_quality.get("freshness_gate")
            if isinstance(live_quality, dict) else None
        )
        if freshness_gate == "block" and active_route.get("tool_family") in {
            "telemetry", "motion", "printer", "localization", "mission"
        }:
            context += (
                "\n实时数据新鲜度门禁未通过。禁止把 blocked_domains 中的值描述为当前事实；"
                "必须逐项说明数据缺失或已过期，并建议检查对应遥测源。"
                "其他通过门禁的数据仍可正常回答。"
            )
        if knowledge.get("matches"):
            context += (
                "\n以下是本地项目知识检索结果。只能依据片段内容回答静态项目事实；"
                "引用时保留来源编号。若片段不足以支持结论，明确说明需要检查的文件或接口：\n"
                + json.dumps(knowledge["matches"], ensure_ascii=False)
            )
        if "进阶" in message or "工作" in message or any(
            word in text for word in ("设计", "图纸", "候选方案", "规划")
        ):
            object_memory = active_route.get("object_memory")
            fresh_design = self._is_fresh_design_request(active_route)
            remembered_project_id = None if fresh_design else (
                str(active_route.get("selected_project_id") or "").strip() or None
            )
            memory_enabled = False
            if (
                not fresh_design
                and isinstance(object_memory, dict)
                and remembered_project_id is None
            ):
                memory_enabled = object_memory.get("enabled") is True
                objects = object_memory.get("objects")
                projects = objects.get("project") if isinstance(objects, dict) else None
                if isinstance(projects, list) and projects and isinstance(projects[0], dict):
                    remembered_project_id = str(projects[0].get("id") or "") or None
            context += "\n进阶工作流状态：\n" + self._advanced_project_context(
                remembered_project_id,
                allow_latest=(
                    not fresh_design
                    and remembered_project_id is None
                    and not memory_enabled
                ),
            )
            if (
                active_route.get("name") == "drawing_design"
                and active_route.get("operation") == "modify"
                and not isinstance(drawing_selection, dict)
            ):
                context += (
                    "\n本轮是当前图纸/候选方案的修改请求，不是知识问答。"
                    "如果已有当前优化基准，必须输出结构化修改意图；后端会绑定项目与"
                    "parent_variant_id，执行并验证几何，再保存新候选。"
                )
        if any(word in text for word in ("图", "cad", "任务", "规划", "执行", "划线")):
            context += (
                "\n当前可用图纸文件：\n"
                + json.dumps(available_drawings(), ensure_ascii=False)
                + "\n启动任务时 file_name 必须从列表中原样选择。"
            )
        return context

    @staticmethod
    def _output_text(response: dict[str, Any]) -> str:
        for item in response.get("output", []):
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    return str(content.get("text", ""))
        return "已完成分析，但模型没有返回文本内容。"

    @staticmethod
    def _usage(response: dict[str, Any]) -> dict[str, int]:
        usage = response.get("usage") or {}
        return {
            "input_tokens": int(usage.get("input_tokens", 0)),
            "output_tokens": int(usage.get("output_tokens", 0)),
            "total_tokens": int(usage.get("total_tokens", 0)),
        }

    @staticmethod
    def _empty_usage() -> dict[str, int]:
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    @staticmethod
    def _add_usage(left: dict[str, int], right: dict[str, int]) -> dict[str, int]:
        return {key: left[key] + right[key] for key in left}

    def _result(
        self,
        message: str,
        usage: dict[str, int],
        pending_action: dict[str, Any] | None = None,
        *,
        tool_results: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        result = {
            "ok": True,
            "configured": True,
            "message": message or "AI API 返回了空内容，请重试；如果持续发生，请检查当前模型配置。",
            "usage": usage,
            "pending_action": pending_action,
        }
        if tool_results:
            result["tool_results"] = tool_results
            previews = [
                item.get("preview_paths")
                for item in reversed(tool_results)
                if isinstance(item, dict)
                and item.get("ok") is True
                and isinstance(item.get("preview_paths"), list)
                and item.get("preview_paths")
            ]
            if previews:
                result["preview_paths"] = previews[0]
            path_previews = [
                item.get("path_preview")
                for item in reversed(tool_results)
                if isinstance(item, dict)
                and isinstance(item.get("path_preview"), dict)
            ]
            if path_previews:
                result["path_preview"] = path_previews[0]
            projects = [
                item for item in reversed(tool_results)
                if isinstance(item, dict) and item.get("project_id")
            ]
            if projects:
                result["project_id"] = projects[0]["project_id"]
                if projects[0].get("project_status"):
                    result["project_status"] = projects[0]["project_status"]
                if projects[0].get("ok") is True:
                    project = get_creative_project_store().get(str(projects[0]["project_id"]))
                    if project is not None:
                        result["project"] = project
                        result["variants"] = list(project.get("variants") or [])
                        variant_id = projects[0].get("variant_id")
                        variant = next((v for v in result["variants"] if v.get("id") == variant_id), None)
                        if variant is not None:
                            result["variant"] = variant
                            result["preview_paths"] = self._preview_contract_from_points(
                                variant.get("preview_paths"), namespace="design_variant"
                            )
                            result["drawing_json"] = self._drawing_payload({"geometries": variant.get("geometries") or []})
        from .agent_response_builder import normalize_acceptance_response
        return normalize_acceptance_response(result)

    @staticmethod
    def _action_label(name: str, arguments: dict[str, Any]) -> str:
        labels = {
            "drive_robot": "执行短时底盘移动",
            "drive_sequence": "执行多段底盘移动",
            "set_mission": "启动划线任务" if arguments.get("running") else "停止划线任务",
            "execute_prepared_mission": "执行已预览的规划路径",
            "control_ln150": "执行 LN150 操作",
            "control_printer": "执行喷码机操作",
            "printer_spray": "打开持续喷墨" if arguments.get("spraying") else "关闭持续喷墨",
            "modify_drawing": "基于原图纸修改并保存新版本",
            "apply_cad_candidate_edit": "应用高风险候选图纸修改",
        }
        return labels.get(name, name)

    def _confirmation_text(self, name: str, arguments: dict[str, Any]) -> str:
        if name == "modify_drawing":
            return "修改预览已生成。请在右侧核对新增、删除和修改位置，确认后才会保存新图纸版本。"
        if name == "apply_cad_candidate_edit":
            return "高风险修改预览已生成。请核对目标和修改范围，确认后才会创建新候选方案。"
        if name in {"drive_robot", "drive_sequence", "execute_prepared_mission", "set_mission"}:
            return (
                f"我准备{self._action_label(name, arguments)}。这是实际运动操作，"
                "请确认周围环境、定位状态和急停装置可用，然后在下方确认执行。"
            )
        if name == "printer_spray":
            return (
                f"我准备{self._action_label(name, arguments)}。"
                "请确认喷头前方有安全测试材料，并在下方确认。"
            )
        return f"我准备{self._action_label(name, arguments)}。请检查周围环境和急停装置，然后在下方确认。"


robot_agent = RobotAgentService()
