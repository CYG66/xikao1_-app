from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any

from .agent_skills import _template_layout_requirements
from .cad_creation_intent import has_local_plural_reference


OBJECT_TYPES = ("project", "drawing", "variant", "mission", "printer", "task", "action")
MAX_OBJECTS_PER_TYPE = 12
MAX_CONVERSATIONS = 100
MAX_RECENT_REQUESTS = 8
MAX_PROFILE_HISTORY = 30
MAX_STATE_TRANSITIONS = 30

REFERENCE_WORDS = (
    "它", "这个", "那个", "刚才", "上一个", "上一版", "当前的", "之前的",
    "该图纸", "这个图纸", "这个项目", "这个方案", "该方案", "继续修改",
)

TYPE_HINTS = {
    "drawing": ("图纸", "cad", "文件", "版本", "上一版"),
    "variant": ("方案", "候选"),
    "project": ("项目", "设计需求"),
    "mission": ("任务", "执行", "规划", "进度", "恢复"),
    "printer": ("喷码", "喷墨", "喷头", "墨量"),
    "task": ("待确认", "操作记录", "agent任务"),
}

DESIGN_MEMORY_WORDS = (
    "图纸", "设计", "cad", "划线", "线宽", "尺寸", "颜色", "喷墨", "喷码机",
    "方案", "路径", "定位", "全站仪", "速度", "车位", "篮球场", "羽毛球场",
    "房间", "走廊", "停车场", "仓库", "轴网", "网格", "圆形基础",
    "数量", "并排", "相邻", "间距", "长边", "短边", "其他不变", "按之前", "继续",
)

REQUIREMENT_LABELS = {
    "drawing_type": "图纸类型",
    "width_m": "宽度",
    "height_m": "高度",
    "radius_m": "半径",
    "diameter_m": "直径",
    "line_width_mm": "线宽",
    "ink_color": "喷墨颜色",
    "localization": "定位方式",
    "speed_preference": "速度偏好",
    "linear_speed_mps": "线速度",
    "printer": "喷码机",
    "quantity": "数量",
    "arrangement": "排列方式",
    "spacing_m": "间距",
}

FILE_PATTERN = re.compile(r"(?<![\w.-])([\w\-\u4e00-\u9fff]+\.json)(?![\w.-])", re.IGNORECASE)
UUID_PATTERN = re.compile(
    r"(?<![0-9a-f])([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})(?![0-9a-f])",
    re.IGNORECASE,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConversationMemoryStore:
    """Small project-object memory isolated by the App's conversation id."""

    def __init__(self, path: Path | None = None) -> None:
        configured = os.getenv("XLINE_AGENT_MEMORY_STORE", "").strip()
        root = (
            Path(tempfile.gettempdir()) / "xline-agent"
            if os.name == "nt"
            else Path(os.getenv("XDG_STATE_HOME", Path.home() / ".local" / "state"))
            / "xline-agent"
        )
        self.path = path or (Path(configured) if configured else root / "conversation_memory.json")
        self._lock = threading.RLock()
        self._conversations: dict[str, dict[str, Any]] = {}
        self._load()

    @staticmethod
    def valid_conversation_id(value: str | None) -> str | None:
        raw = str(value or "").strip()
        if not raw or len(raw) > 100 or not re.fullmatch(r"[A-Za-z0-9_.:-]+", raw):
            return None
        return raw

    def context(
        self, conversation_id: str | None, history: list[dict[str, str]] | None = None
    ) -> dict[str, Any]:
        key = self.valid_conversation_id(conversation_id)
        if key is None:
            return {"enabled": False, "conversation_id": None, "objects": {}, "focus": None}
        with self._lock:
            memory = self._conversations.setdefault(key, self._empty(key))
            self._ensure(memory)
            if history:
                changed = False
                if not memory["objects"]:
                    self._learn_text(memory, "\n".join(
                        str(item.get("content") or "") for item in history[-12:]
                    ))
                    changed = True
                summary = memory["summary"]
                profile = memory["requirement_profile"]
                bootstrap_requests = not summary["recent_requests"]
                bootstrap_profile = (
                    profile.get("status") == "empty"
                    and not profile["confirmed"]
                    and not profile["pending"]
                )
                if bootstrap_requests or bootstrap_profile:
                    for item in history[-12:]:
                        if item.get("role") != "user":
                            continue
                        content = str(item.get("content") or "")
                        if bootstrap_requests:
                            self._remember_request(memory, content)
                        if bootstrap_profile:
                            self._update_pending_requirements(memory, content)
                    self._refresh_summary(memory)
                    changed = True
                if not summary["last_answer"]:
                    for item in reversed(history[-12:]):
                        if item.get("role") == "assistant" and item.get("content"):
                            summary["last_answer"] = self._safe_text(
                                str(item["content"])
                            )
                            summary["updated_at"] = _now()
                            changed = True
                            break
                if changed:
                    self._save()
            return self._public(memory)

    def retrieve(self, conversation_id: str | None, message: str) -> dict[str, Any]:
        key = self.valid_conversation_id(conversation_id)
        if key is None:
            return {"enabled": False, "relevant": False}
        with self._lock:
            memory = self._conversations.setdefault(key, self._empty(key))
            self._ensure(memory)
            lowered = message.lower()
            relevant = any(word in lowered for word in DESIGN_MEMORY_WORDS + REFERENCE_WORDS)
            profile = memory["requirement_profile"]
            object_matches: dict[str, list[dict[str, Any]]] = {}
            for object_type, words in TYPE_HINTS.items():
                if any(word in lowered for word in words):
                    values = memory.get("objects", {}).get(object_type, [])
                    if values:
                        object_matches[object_type] = deepcopy(values[:3])
            if not relevant and not object_matches:
                return {"enabled": True, "relevant": False}
            return {
                "enabled": True,
                "relevant": True,
                "summary": deepcopy(memory.get("summary", {})),
                "confirmed_requirements": deepcopy(profile.get("confirmed", {})),
                "pending_requirements": deepcopy(profile.get("pending", {})),
                "profile_version": int(profile.get("version", 0)),
                "workflow_state": self._public_workflow_state(memory),
                "objects": object_matches,
            }

    def decide_requirements(
        self, conversation_id: str | None, accepted: bool
    ) -> dict[str, Any]:
        key = self.valid_conversation_id(conversation_id)
        if key is None:
            return {"ok": False, "message": "会话无效，无法保存需求。"}
        with self._lock:
            memory = self._conversations.setdefault(key, self._empty(key))
            self._ensure(memory)
            profile = memory["requirement_profile"]
            pending = dict(profile.get("pending", {}))
            if not pending:
                return {
                    "ok": False,
                    "message": "当前没有待确认的需求。",
                    "memory": self._public(memory),
                }
            before = deepcopy(profile.get("confirmed", {}))
            if accepted:
                profile["confirmed"].update(pending)
                profile["version"] = int(profile.get("version", 0)) + 1
                message = "需求已确认，后续设计将按这些条件继续。"
            else:
                message = "未采用这次需求变更，请直接说明需要修改的内容。"
            profile["history"].append({
                "version": int(profile.get("version", 0)),
                "accepted": accepted,
                "changes": pending,
                "before": before,
                "recorded_at": _now(),
            })
            del profile["history"][:-MAX_PROFILE_HISTORY]
            profile["pending"] = {}
            profile["status"] = "confirmed" if accepted else "needs_revision"
            profile["updated_at"] = _now()
            self._commit_workflow_state(
                memory,
                phase="designing" if accepted else "requirements",
                pending=None,
                last_outcome={
                    "ok": True,
                    "next_action": "continue_design" if accepted else "revise_requirements",
                    "task_state": None,
                    "message": message,
                },
                event=(
                    "requirements_confirmed" if accepted
                    else "requirements_rejected"
                ),
            )
            memory["updated_at"] = _now()
            self._refresh_summary(memory)
            self._save()
            return {"ok": True, "message": message, "memory": self._public(memory)}

    def resolve(
        self,
        conversation_id: str | None,
        message: str,
        history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        context = self.context(conversation_id, history)
        if not context["enabled"]:
            return {
                "message": message,
                "resolved": False,
                "required": False,
                "memory": context,
                "retrieved": self.retrieve(conversation_id, message),
            }
        lowered = message.lower()
        local_plural = has_local_plural_reference(message)
        reference_text = lowered.replace("它们", "") if local_plural else lowered
        required = any(word in reference_text for word in REFERENCE_WORDS)
        if not required:
            return {
                "message": message,
                "resolved": False,
                "required": False,
                "memory": context,
                "retrieved": self.retrieve(conversation_id, message),
            }

        hinted = [
            object_type for object_type, words in TYPE_HINTS.items()
            if any(word in lowered for word in words)
        ]
        objects = context.get("objects", {})
        workflow = context.get("workflow_state")
        active = workflow.get("active") if isinstance(workflow, dict) else {}
        active_keys = {
            "project": "project_id",
            "variant": "variant_id",
            "drawing": "drawing_id",
            "action": "action_id",
        }
        candidates: list[dict[str, Any]] = []
        for object_type in hinted:
            values = objects.get(object_type, [])
            active_id = str(active.get(active_keys.get(object_type, "")) or "")
            active_value = next((
                item for item in values
                if str(item.get("id") or "") == active_id
            ), None) if active_id and isinstance(values, list) else None
            if active_value is not None and "上一个" not in lowered:
                candidates.append(active_value)
            elif active_id and not values and "上一个" not in lowered:
                candidates.append({
                    "type": object_type,
                    "id": active_id,
                    "label": active_id,
                    "source": "workflow_state",
                })
            elif values:
                candidates.append(values[1] if "上一个" in lowered and len(values) > 1 else values[0])
        if not candidates and isinstance(context.get("focus"), dict):
            candidates = [context["focus"]]
        unique = {(item["type"], item["id"]): item for item in candidates}.values()
        candidates = list(unique)
        if len(candidates) != 1:
            labels = "、".join(
                f"{item.get('label') or item['id']}（{item['type']}）"
                for item in candidates[:4]
            ) or "无可用对象"
            return {
                "message": message,
                "resolved": False,
                "required": True,
                "ambiguous": True,
                "question": f"请明确你指的是哪个对象。当前候选：{labels}。",
                "candidates": candidates,
                "memory": context,
                "retrieved": self.retrieve(conversation_id, message),
            }
        target = candidates[0]
        suffix = f"\n[已解析指代：{target['type']}={target['id']}，名称={target.get('label') or target['id']}]"
        return {
            "message": message + suffix,
            "resolved": True,
            "required": True,
            "ambiguous": False,
            "target": target,
            "memory": context,
            "retrieved": self.retrieve(conversation_id, message),
        }

    def remember(
        self,
        conversation_id: str | None,
        message: str,
        result: dict[str, Any],
        route: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        key = self.valid_conversation_id(conversation_id)
        if key is None:
            return {"enabled": False, "conversation_id": None, "objects": {}, "focus": None}
        with self._lock:
            memory = self._conversations.setdefault(key, self._empty(key))
            self._ensure(memory)
            self._learn_text(memory, message)
            self._learn_result(memory, result, route={**route,'user_message':message} if isinstance(route,dict) else route)
            self._remember_answer(memory, result)
            self._update_pending_requirements(memory, message)
            self._update_workflow_state(memory, message, result, route)
            self._refresh_summary(memory)
            memory["updated_at"] = _now()
            self._prune()
            self._save()
        return self._public(memory)

    def observe(self, conversation_id: str | None, message: str) -> dict[str, Any]:
        """Persist the request before inference so retrieval sees current changes."""
        key = self.valid_conversation_id(conversation_id)
        if key is None:
            return {"enabled": False, "conversation_id": None}
        with self._lock:
            memory = self._conversations.setdefault(key, self._empty(key))
            self._ensure(memory)
            self._learn_text(memory, message)
            self._remember_request(memory, message)
            self._update_pending_requirements(memory, message)
            self._record_state_input(memory, message)
            self._refresh_summary(memory)
            memory["updated_at"] = _now()
            self._prune()
            self._save()
            return self._public(memory)

    def clear_pending_cad_edit(
        self, conversation_id: str | None, *, reason: str = "cad_context_binding_mismatch"
    ) -> dict[str, Any]:
        """Atomically invalidate a stale CAD edit continuation.

        A mismatched project/version/selection must never leave the old
        command available for a later confirmation.  This method is kept on
        the memory store so all HTTP and streaming entry points perform the
        same durable clear instead of mutating a local snapshot only.
        """
        key = self.valid_conversation_id(conversation_id)
        if key is None:
            return {"enabled": False, "conversation_id": None}
        with self._lock:
            memory = self._conversations.setdefault(key, self._empty(key))
            self._ensure(memory)
            memory["pending_cad_edit"] = None
            memory.setdefault("workflow_state", {}).setdefault("events", []).append({
                "at": _now(),
                "event": "pending_cad_edit_cleared",
                "reason": reason,
            })
            memory["updated_at"] = _now()
            self._prune()
            self._save()
            return self._public(memory)

    def set_candidate_navigation(
        self, conversation_id: str | None, navigation: dict[str, Any] | None
    ) -> dict[str, Any]:
        key = self.valid_conversation_id(conversation_id)
        if key is None:
            return {"enabled": False, "conversation_id": None}
        with self._lock:
            memory = self._conversations.setdefault(key, self._empty(key))
            self._ensure(memory)
            memory["candidate_navigation"] = deepcopy(navigation)
            active: dict[str, Any] = {}
            if isinstance(navigation, dict):
                if navigation.get("project_id"):
                    active["project_id"] = str(navigation["project_id"])
                target_id = navigation.get("current_variant_id") or navigation.get(
                    "to_variant_id"
                )
                if target_id:
                    active["variant_id"] = str(target_id)
            self._commit_workflow_state(
                memory,
                phase="candidate_review" if navigation else None,
                active=active,
                event="candidate_navigation_updated",
            )
            memory["updated_at"] = _now()
            self._save()
            return self._public(memory)

    def set_active_cad_target(
        self,
        conversation_id: str | None,
        *,
        project_id: str,
        variant_id: str,
        scope: str,
        ids: list[Any],
        label: str | None = None,
        confidence: float = 1.0,
        reason: str = "resolved_target",
    ) -> dict[str, Any]:
        """Persist a confirmed CAD target for follow-up pronoun binding.

        Unlike ``active_cad_context`` (refreshed only after a successful
        edit), this writes as soon as a target is resolved by the resolver or
        confirmed on the canvas, for any granularity (logical_object /
        instance / geometry).
        """
        key = self.valid_conversation_id(conversation_id)
        if key is None or scope not in {"logical_object", "instance", "geometry"}:
            return {"enabled": False, "conversation_id": None}
        with self._lock:
            memory = self._conversations.setdefault(key, self._empty(key))
            self._ensure(memory)
            context = memory.get("active_cad_context")
            if not isinstance(context, dict):
                context = {"schema": "cad.active-context.v1", "updated_at": _now()}
            context.setdefault("parent_variant_id", "")
            context.setdefault("selected_object_ids", [])
            context.setdefault("selected_geometry_ids", [])
            context.setdefault("selected_instances", [])
            context.setdefault("logical_object_ids", [])
            context.setdefault("geometry_ids", [])
            context.setdefault("identity_contract", None)
            context["project_id"] = str(project_id)
            context["variant_id"] = str(variant_id)
            numeric_ids = sorted({
                int(value) for value in ids
                if isinstance(value, int) and value > 0
            })
            if scope == "logical_object":
                context["selected_object_ids"] = [str(value) for value in ids if value]
                context["selected_geometry_ids"] = numeric_ids
                context.pop("selected_instances", None)
            elif scope == "instance":
                context["selected_instances"] = numeric_ids
                context["selected_geometry_ids"] = []
            else:
                context["selected_geometry_ids"] = numeric_ids
                context.pop("selected_instances", None)
            context["active_target"] = {
                "scope": scope,
                "ids": [str(value) for value in ids],
                "label": str(label or "")[:160],
                "confidence": round(float(confidence), 6),
                "reason": str(reason),
                "project_id": str(project_id),
                "variant_id": str(variant_id),
                "updated_at": _now(),
            }
            memory["active_cad_context"] = context
            memory["updated_at"] = _now()
            self._save()
            return self._public(memory)

    def delete(self, conversation_id: str | None) -> bool:
        key = self.valid_conversation_id(conversation_id)
        if key is None:
            return False
        with self._lock:
            removed = self._conversations.pop(key, None) is not None
            if removed:
                self._save()
            return removed

    def forget_object(
        self, conversation_id: str | None, object_type: str, identifier: str
    ) -> bool:
        """Remove a stale object reference (e.g. a deleted project) from memory.

        Clears the matching entry in ``objects[object_type]`` and, when the
        focused object is the one being forgotten, clears ``focus`` as well.
        """
        key = self.valid_conversation_id(conversation_id)
        if key is None or object_type not in OBJECT_TYPES or not identifier:
            return False
        with self._lock:
            memory = self._conversations.get(key)
            if not memory:
                return False
            self._ensure(memory)
            objects = memory["objects"]
            values = objects.get(object_type, [])
            before = len(values)
            filtered = [
                item
                for item in values
                if str(item.get("id") or "") != str(identifier)
            ]
            focus = memory.get("focus")
            focus_was_target = (
                isinstance(focus, dict)
                and str(focus.get("id") or "") == str(identifier)
            )
            removed = len(filtered) != before or focus_was_target
            if not removed:
                return False
            if filtered:
                objects[object_type] = filtered
            else:
                objects.pop(object_type, None)
            if focus_was_target:
                memory["focus"] = None
            active_key = {
                "project": "project_id",
                "variant": "variant_id",
                "drawing": "drawing_id",
                "action": "action_id",
            }.get(object_type)
            if active_key and str(
                memory["workflow_state"]["active"].get(active_key) or ""
            ) == str(identifier):
                self._commit_workflow_state(
                    memory,
                    active={active_key: None},
                    event="stale_object_forgotten",
                )
            memory["updated_at"] = _now()
            self._refresh_summary(memory)
            self._save()
            return True

    @staticmethod
    def _empty(key: str) -> dict[str, Any]:
        return {
            "conversation_id": key,
            "objects": {},
            "focus": None,
            "summary": {
                "last_user_request": "",
                "recent_requests": [],
                "last_answer": "",
                "turn_count": 0,
                "text": "",
                "updated_at": _now(),
            },
            "requirement_profile": {
                "version": 0,
                "status": "empty",
                "confirmed": {},
                "pending": {},
                "history": [],
                "updated_at": _now(),
            },
            "last_cad_edit": None,
            "active_cad_context": None,
            "candidate_navigation": None,
            "workflow_state": ConversationMemoryStore._empty_workflow_state(),
            "updated_at": _now(),
        }

    @staticmethod
    def _empty_workflow_state() -> dict[str, Any]:
        return {
            "schema": "agent.conversation-state.v1",
            "version": 0,
            "phase": "idle",
            "active": {
                "project_id": None,
                "variant_id": None,
                "parent_variant_id": None,
                "drawing_id": None,
                "action_id": None,
            },
            "pending": None,
            "last_input": "",
            "last_outcome": None,
            "transition_history": [],
            "updated_at": _now(),
        }

    @staticmethod
    def _ensure(memory: dict[str, Any]) -> None:
        empty = ConversationMemoryStore._empty(str(memory.get("conversation_id") or ""))
        for key in ("objects", "summary", "requirement_profile"):
            if not isinstance(memory.get(key), dict):
                memory[key] = deepcopy(empty[key])
        memory.setdefault("focus", None)
        memory.setdefault("last_cad_edit", None)
        memory.setdefault("active_cad_context", None)
        memory.setdefault("candidate_navigation", None)
        if not isinstance(memory.get("workflow_state"), dict):
            memory["workflow_state"] = deepcopy(empty["workflow_state"])
        summary = memory["summary"]
        for key, value in empty["summary"].items():
            summary.setdefault(key, deepcopy(value))
        profile = memory["requirement_profile"]
        for key, value in empty["requirement_profile"].items():
            profile.setdefault(key, deepcopy(value))
        state = memory["workflow_state"]
        for key, value in empty["workflow_state"].items():
            state.setdefault(key, deepcopy(value))
        if not isinstance(state.get("active"), dict):
            state["active"] = deepcopy(empty["workflow_state"]["active"])
        for key, value in empty["workflow_state"]["active"].items():
            state["active"].setdefault(key, value)
        if not isinstance(state.get("transition_history"), list):
            state["transition_history"] = []

    @staticmethod
    def _safe_text(value: str, limit: int = 300) -> str:
        text = re.sub(r"\bsk-[A-Za-z0-9_-]{12,}\b", "[已隐藏密钥]", value)
        text = re.sub(
            r"(?i)((?:api[_ -]?key|token|password|密码)\s*[:=：]\s*)\S+",
            r"\1[已隐藏]",
            text,
        )
        text = re.sub(r"\s+", " ", text).strip()
        return text[:limit]

    @staticmethod
    def _state_signature(state: dict[str, Any]) -> str:
        core = {
            "schema": state.get("schema"),
            "version": state.get("version"),
            "phase": state.get("phase"),
            "active": state.get("active"),
            "pending": state.get("pending"),
            "last_input": state.get("last_input"),
            "last_outcome": state.get("last_outcome"),
        }
        return hashlib.sha256(json.dumps(
            core, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()

    def _commit_workflow_state(
        self,
        memory: dict[str, Any],
        *,
        phase: str | None = None,
        active: dict[str, Any] | None = None,
        pending: dict[str, Any] | None | object = ...,
        last_input: str | None = None,
        last_outcome: dict[str, Any] | None | object = ...,
        event: str,
    ) -> None:
        state = memory["workflow_state"]
        before = {
            "phase": state.get("phase"),
            "active": deepcopy(state.get("active") or {}),
            "pending": deepcopy(state.get("pending")),
            "last_input": state.get("last_input"),
            "last_outcome": deepcopy(state.get("last_outcome")),
        }
        if phase is not None:
            state["phase"] = phase
        if isinstance(active, dict):
            state["active"].update({
                key: value for key, value in active.items()
                if key in state["active"]
            })
        if pending is not ...:
            state["pending"] = deepcopy(pending)
        if last_input is not None:
            state["last_input"] = self._safe_text(last_input)
        if last_outcome is not ...:
            state["last_outcome"] = deepcopy(last_outcome)
        after = {
            "phase": state.get("phase"),
            "active": state.get("active"),
            "pending": state.get("pending"),
            "last_input": state.get("last_input"),
            "last_outcome": state.get("last_outcome"),
        }
        if before == after:
            return
        state["version"] = int(state.get("version") or 0) + 1
        state["updated_at"] = _now()
        state["transition_history"].append({
            "version": state["version"],
            "event": event,
            "from_phase": before["phase"],
            "to_phase": state["phase"],
            "recorded_at": state["updated_at"],
        })
        del state["transition_history"][:-MAX_STATE_TRANSITIONS]

    def _record_state_input(self, memory: dict[str, Any], message: str) -> None:
        self._commit_workflow_state(
            memory,
            last_input=message,
            event="user_input_observed",
        )

    def _update_workflow_state(
        self,
        memory: dict[str, Any],
        message: str,
        result: dict[str, Any],
        route: dict[str, Any] | None,
    ) -> None:
        active: dict[str, Any] = {}
        project = result.get("project")
        variant = result.get("variant")
        if isinstance(project, dict) and project.get("id"):
            active["project_id"] = str(project["id"])
        elif result.get("project_id"):
            active["project_id"] = str(result["project_id"])
        if isinstance(variant, dict) and variant.get("id"):
            active["variant_id"] = str(variant["id"])
            if variant.get("parent_variant_id"):
                active["parent_variant_id"] = str(variant["parent_variant_id"])
        elif result.get("variant_id"):
            active["variant_id"] = str(result["variant_id"])
        for key in ("file_name", "source_file_name", "mission_file"):
            if result.get(key):
                active["drawing_id"] = str(result[key])
                break

        route = route if isinstance(route, dict) else {}
        pending_action = result.get("pending_action")
        previous_pending = memory["workflow_state"].get("pending")
        pending: dict[str, Any] | None | object = ...
        phase: str | None = None
        event = "result_recorded"
        task_state = str(result.get("task_state") or "")
        if task_state in {"completed", "cancelled", "failed", "rejected"}:
            active["action_id"] = None
            pending = None
            phase = "failed" if task_state == "rejected" else task_state
            event = "action_terminal_state"
        elif isinstance(pending_action, dict):
            action_id = str(
                pending_action.get("id") or pending_action.get("action_id") or ""
            ).strip()
            if action_id:
                active["action_id"] = action_id
            pending = {
                "kind": "action_confirmation",
                "id": action_id or None,
                "tool": str(pending_action.get("name") or "") or None,
                "expected_response": "confirm_or_cancel",
                "created_at": _now(),
            }
            phase = "awaiting_confirmation"
            event = "action_confirmation_requested"
        elif result.get("requirements_confirmation_required") is True:
            pending = {
                "kind": "requirement_confirmation",
                "profile_version": int(
                    memory["requirement_profile"].get("version") or 0
                ),
                "expected_response": "accept_or_revise",
                "created_at": _now(),
            }
            phase = "requirements"
            event = "requirement_confirmation_requested"
        elif route.get("clarification_required") is True:
            pending = {
                "kind": "clarification",
                "question": self._safe_text(str(
                    route.get("clarification_question")
                    or result.get("message") or "请补充缺少的信息。"
                )),
                "expected_response": "answer",
                "created_at": _now(),
            }
            phase = "awaiting_clarification"
            event = "clarification_requested"
        else:
            next_action = str(result.get("next_action") or "")
            project_status = str(
                project.get("status") if isinstance(project, dict) else ""
            )
            if next_action == "select_design_variant":
                phase = "candidate_review"
                pending = {
                    "kind": "candidate_selection",
                    "expected_response": "select_or_modify",
                    "created_at": _now(),
                }
                event = "candidate_ready"
            elif project_status in {"clarifying", "ready_for_design"}:
                phase = "requirements"
                pending = None
            elif project_status == "designing":
                phase = "designing"
                pending = None
            elif project_status in {"ready_for_planning", "planning"}:
                phase = "planning"
                pending = None
            elif project_status in {"pending_execution", "ready_for_execution"}:
                phase = "awaiting_confirmation"
            elif project_status in {"executing", "paused", "completed", "failed"}:
                phase = project_status
                pending = None
            elif result.get("cad_history_navigation"):
                phase = "candidate_review"
                pending = {
                    "kind": "candidate_selection",
                    "expected_response": "select_or_modify",
                    "created_at": _now(),
                }
            elif (
                isinstance(previous_pending, dict)
                and previous_pending.get("kind") == "clarification"
            ):
                pending = None
                phase = {
                    "requirements": "requirements",
                    "design": "designing",
                    "candidates": "candidate_review",
                    "planning": "planning",
                    "confirmation": "awaiting_confirmation",
                    "execution": "executing",
                }.get(str(route.get("stage") or ""), "idle")
                event = "clarification_answered"

        outcome = {
            "ok": result.get("ok") is not False,
            "next_action": result.get("next_action"),
            "task_state": result.get("task_state"),
            "message": self._safe_text(str(result.get("message") or ""), 180),
        }
        self._commit_workflow_state(
            memory,
            phase=phase,
            active=active,
            pending=pending,
            last_input=message,
            last_outcome=outcome,
            event=event,
        )

    def _remember_request(self, memory: dict[str, Any], message: str) -> None:
        summary = memory["summary"]
        request = self._safe_text(message)
        if request:
            recent = summary["recent_requests"]
            if not recent or recent[-1] != request:
                recent.append(request)
                del recent[:-MAX_RECENT_REQUESTS]
            summary["last_user_request"] = request
            summary["turn_count"] = int(summary.get("turn_count", 0)) + 1
        summary["updated_at"] = _now()

    def _remember_answer(self, memory: dict[str, Any], result: dict[str, Any]) -> None:
        answer = self._safe_text(str(result.get("message") or ""))
        if answer:
            memory["summary"]["last_answer"] = answer
            memory["summary"]["updated_at"] = _now()

    def _update_pending_requirements(self, memory: dict[str, Any], message: str) -> None:
        changes = self._extract_requirements(message)
        if not changes:
            return
        profile = memory["requirement_profile"]
        confirmed = profile["confirmed"]
        pending = profile["pending"]
        for key, value in changes.items():
            if confirmed.get(key) == value:
                pending.pop(key, None)
            else:
                pending[key] = value
        profile["status"] = "pending_confirmation" if pending else "confirmed"
        profile["updated_at"] = _now()

    @staticmethod
    def _extract_requirements(message: str) -> dict[str, Any]:
        text = message.lower().replace("，", ",")
        shape_names = {
            "篮球场": "basketball_court", "足球场": "football_field",
            "羽毛球场": "badminton_court",
            "停车位": "parking_space", "车位": "parking_space",
            "停车场": "parking_lot", "停车区": "parking_lot",
            "矩形房间": "room", "房间": "room",
            "两室布局": "two_rooms", "双房间": "two_rooms",
            "长走廊": "corridor", "走廊": "corridor",
            "仓库网格": "warehouse", "仓储网格": "warehouse", "仓库": "warehouse",
            "施工轴网": "grid", "轴网": "grid", "网格": "grid",
            "圆形基础": "foundation", "圆基础": "foundation", "基础圆": "foundation",
            "矩形": "rectangle", "正方形": "square",
            "圆形": "circle", "圆": "circle", "直线": "line", "折线": "polyline",
        }
        colors = ("黄色", "白色", "红色", "蓝色", "绿色", "黑色")
        explicit_change = any(
            word in text for word in ("改成", "改为", "换成", "换为", "调整成", "调整为", "使用", "采用")
        )
        has_known_value = any(word in text for word in (*shape_names, *colors))
        parameter_only = bool(re.search(
            r"(?:宽高|宽度和高度|宽度高度)\s*(?:均|都)?\s*(?:为|是|改为|改成|调整为|调整成)?\s*"
            r"\d+(?:\.\d+)?\s*(?:米|m|厘米|cm|毫米|mm)",
            text,
        )) or bool(re.search(
            r"(?:宽度|高度|半径|直径|线宽|数量|间距)\s*(?:为|是|改为|改成|调整为|调整成|[:：])?\s*"
            r"\d+(?:\.\d+)?\s*(?:米|m|厘米|cm|毫米|mm|个)?",
            text,
        ))
        if not any(word in text for word in DESIGN_MEMORY_WORDS) and not parameter_only and not (
            explicit_change and has_known_value
        ):
            return {}
        result: dict[str, Any] = {}
        drawing_type = ConversationMemoryStore._last_positive_choice(text, shape_names)
        if drawing_type is not None:
            result["drawing_type"] = drawing_type
        quantity_matches = list(re.finditer(
            r"(?P<count>\d+|[一二两三四五六七八九十]+)\s*"
            r"(?:个|组)?\s*(?:并排|相邻|连续)?\s*(?:标准)?"
            r"(?:停车位|车位|停车场|停车区|篮球场|篮球场地|羽毛球场|羽毛球场地|"
            r"矩形房间|房间|两室布局|双房间|长走廊|走廊|仓库网格|仓储网格|仓库|"
            r"施工轴网|轴网|网格|圆形基础|圆基础|基础圆)",
            text,
        ))
        quantity = next(
            (
                match for match in reversed(quantity_matches)
                if not re.match(r"\s*(?:大小|宽度|尺寸)", text[match.end():])
            ),
            None,
        )
        if quantity:
            raw = quantity.group("count")
            digits = {
                "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
                "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
            }
            if raw.isdigit():
                parsed_quantity = int(raw)
            elif raw == "十":
                parsed_quantity = 10
            elif "十" in raw:
                left, right = raw.split("十", 1)
                parsed_quantity = digits.get(left, 1) * 10 + digits.get(right, 0)
            else:
                parsed_quantity = digits.get(raw, 1)
            result["quantity"] = max(1, min(50, parsed_quantity))
        result.update(_template_layout_requirements(text))
        pair = re.search(r"(\d+(?:\.\d+)?)\s*[x×*]\s*(\d+(?:\.\d+)?)\s*(米|m|厘米|cm|毫米|mm)?", text)
        if pair:
            factor = {"厘米": 0.01, "cm": 0.01, "毫米": 0.001, "mm": 0.001}.get(pair.group(3) or "米", 1.0)
            result["width_m"] = round(float(pair.group(1)) * factor, 4)
            result["height_m"] = round(float(pair.group(2)) * factor, 4)
        same_size = re.search(
            r"(?:宽高|宽度和高度|宽度高度)\s*(?:均|都)?\s*"
            r"(?:为|是|改为|改成|调整为|调整成|[:：])?\s*"
            r"(\d+(?:\.\d+)?)\s*(米|m|厘米|cm|毫米|mm)",
            text,
        )
        if same_size:
            factor = {"厘米": 0.01, "cm": 0.01, "毫米": 0.001, "mm": 0.001}.get(
                same_size.group(2), 1.0
            )
            value = round(float(same_size.group(1)) * factor, 4)
            result["width_m"] = value
            result["height_m"] = value
        for key, label in (("width_m", "宽度"), ("height_m", "高度")):
            single_size = re.search(
                rf"{label}\s*(?:为|是|改为|改成|调整为|调整成|[:：])?\s*"
                r"(\d+(?:\.\d+)?)\s*(米|m|厘米|cm|毫米|mm)",
                text,
            )
            if single_size:
                factor = {"厘米": 0.01, "cm": 0.01, "毫米": 0.001, "mm": 0.001}.get(
                    single_size.group(2), 1.0
                )
                result[key] = round(float(single_size.group(1)) * factor, 4)
        line_width = re.search(
            r"线宽\s*(?:(?:改|设|调整)(?:成|为)|为|是|[:：])?\s*"
            r"(\d+(?:\.\d+)?)\s*(mm|毫米|cm|厘米)",
            text,
        )
        if line_width:
            value = float(line_width.group(1))
            result["line_width_mm"] = round(value * (10 if line_width.group(2) in {"cm", "厘米"} else 1), 2)
        for key, label in (("radius_m", "半径"), ("diameter_m", "直径")):
            match = re.search(rf"{label}\s*(?:为|是|[:：])?\s*(\d+(?:\.\d+)?)\s*(米|m|厘米|cm|毫米|mm)", text)
            if match:
                factor = {"厘米": 0.01, "cm": 0.01, "毫米": 0.001, "mm": 0.001}.get(match.group(2), 1.0)
                result[key] = round(float(match.group(1)) * factor, 4)
        color = ConversationMemoryStore._last_positive_choice(
            text,
            {item: item for item in colors},
        )
        if color is not None:
            result["ink_color"] = color
        if "不使用全站仪" in text or "不用全站仪" in text or "相对定位" in text:
            result["localization"] = "relative"
        elif "全站仪" in text:
            result["localization"] = "total_station"
        speed = re.search(r"(?:线)?速度\s*(?:为|是|[:：])?\s*(\d+(?:\.\d+)?)\s*m/s", text)
        if speed:
            result["linear_speed_mps"] = float(speed.group(1))
        elif any(word in text for word in ("低速", "慢速", "尽量慢")):
            result["speed_preference"] = "low"
        elif any(word in text for word in ("高速", "快速", "尽量快")):
            result["speed_preference"] = "high"
        for word, value in (("左喷码机", "left"), ("右喷码机", "right"), ("中间喷码机", "center"), ("中央喷码机", "center")):
            if word in text:
                result["printer"] = value
                break
        return result

    @staticmethod
    def _last_positive_choice(text: str, choices: dict[str, str]) -> str | None:
        matches: list[tuple[int, int, str]] = []
        for word, value in choices.items():
            for match in re.finditer(re.escape(word), text):
                prefix = text[max(0, match.start() - 5):match.start()]
                if re.search(r"(?:不要|不用|取消|排除|不使用)\s*$", prefix):
                    continue
                matches.append((match.start(), match.end(), value))
        independent = [
            item for item in matches
            if not any(
                other[0] <= item[0]
                and other[1] >= item[1]
                and (other[1] - other[0]) > (item[1] - item[0])
                for other in matches
            )
        ]
        return max(
            independent,
            default=(-1, -1, None),
            key=lambda item: (item[0], item[1] - item[0]),
        )[2]

    @staticmethod
    def _format_requirement(key: str, value: Any) -> str:
        label = REQUIREMENT_LABELS.get(key, key)
        if key in {"width_m", "height_m", "radius_m", "diameter_m"}:
            return f"{label}{value}米"
        if key == "line_width_mm":
            return f"{label}{value}毫米"
        if key == "linear_speed_mps":
            return f"{label}{value}米/秒"
        if key == "quantity":
            return f"{label}{value}个"
        names = {
            "relative": "相对定位", "total_station": "全站仪定位",
            "low": "低速", "high": "高速", "center": "中间喷码机",
            "left": "左喷码机", "right": "右喷码机",
        }
        return f"{label}{names.get(str(value), value)}"

    def _refresh_summary(self, memory: dict[str, Any]) -> None:
        summary = memory["summary"]
        profile = memory["requirement_profile"]
        parts: list[str] = []
        confirmed = profile.get("confirmed", {})
        pending = profile.get("pending", {})
        if confirmed:
            parts.append("已确认：" + "、".join(
                self._format_requirement(key, value) for key, value in confirmed.items()
            ))
        if pending:
            parts.append("待确认：" + "、".join(
                self._format_requirement(key, value) for key, value in pending.items()
            ))
        last_request = summary.get("last_user_request")
        if last_request:
            parts.append(f"最近请求：{last_request}")
        summary["text"] = "；".join(parts)[:1200]
        summary["updated_at"] = _now()

    def _learn_text(self, memory: dict[str, Any], text: str) -> None:
        for file_name in FILE_PATTERN.findall(text):
            self._add(memory, "drawing", file_name, file_name, "conversation_text")
        for identifier in UUID_PATTERN.findall(text):
            lowered = text.lower()
            object_type = "project" if "项目" in lowered else "variant" if "方案" in lowered else "task"
            self._add(memory, object_type, identifier, identifier, "conversation_text")

    def _learn_result(
        self,
        memory: dict[str, Any],
        result: dict[str, Any],
        route: dict[str, Any] | None = None,
    ) -> None:
        from .cad_edit_session import remember_edit
        memory['pending_cad_edit']=remember_edit(memory.get('pending_cad_edit'),
            str((route or {}).get('user_message') or ''),result,route)
        v2_command = result.get("cad_edit_contract")
        legacy_command = result.get("cad_edit_command")
        command = (
            v2_command if isinstance(v2_command, dict)
            and v2_command.get("schema") == "cad.edit.v2"
            else legacy_command
        )
        variant = result.get("variant")
        project_id = str(result.get("project_id") or "").strip()
        if (
            result.get("ok") is True
            and isinstance(command, dict)
            and command.get("schema") in {
                "cad.edit.v2", "cad.instance_edit.v1", "cad.geometry_edit.v1",
            }
            and isinstance(variant, dict)
            and variant.get("id")
            and project_id
        ):
            memory["last_cad_edit"] = {
                **deepcopy(command),
                "project_id": project_id,
                "variant_id": str(variant["id"]),
                "parent_variant_id": str(variant.get("parent_variant_id") or ""),
                "recorded_at": _now(),
            }
            # A new persisted edit invalidates the old redo branch, while the
            # active CAD context below remains available for follow-up turns.
            memory["candidate_navigation"] = None
        project = result.get("project")
        if not isinstance(project, dict):
            project = None
        variant_id = str(
            (variant or {}).get("id") if isinstance(variant, dict) else ""
        ).strip() or str(result.get("variant_id") or "").strip()
        project_id = project_id or str(result.get("project_id") or "").strip()
        if project_id and variant_id:
            target = command.get("target") if isinstance(command, dict) else None
            target = target if isinstance(target, dict) else {}
            selected_object_ids = [
                str(value) for value in [target.get("object_id"), *(target.get("object_ids") or [])]
                if value
            ]
            selected_geometry_ids = [
                int(value) for value in target.get("geometry_ids") or []
                if isinstance(value, int) and value > 0
            ]
            drawing_selection = route.get("drawing_selection") if isinstance(route, dict) else None
            if isinstance(drawing_selection, dict):
                selected_object_ids.extend(
                    str(value) for value in [drawing_selection.get("object_id")]
                    if value
                )
                selected_geometry_ids.extend(
                    int(value) for value in drawing_selection.get("geometry_ids") or []
                    if isinstance(value, int) and value > 0
                )
            logical_object_ids = [
                str(item.get("object_id")) for item in (variant.get("logical_objects") or [])
                if isinstance(item, dict) and item.get("object_id")
            ] if isinstance(variant, dict) else []
            identity_contract = variant.get("identity_contract") if isinstance(variant, dict) else None
            active_target: dict[str, Any] | None = None
            if isinstance(target, dict):
                target_scope = None
                target_ids: list[Any] = []
                if target.get("object_id") or target.get("object_ids"):
                    target_scope = "logical_object"
                    target_ids = [value for value in [target.get("object_id"), *(target.get("object_ids") or [])] if value]
                elif target.get("instance_ids") or target.get("instance"):
                    target_scope = "instance"
                    target_ids = [value for value in [target.get("instance"), *(target.get("instance_ids") or [])] if isinstance(value, int)]
                elif target.get("geometry_ids"):
                    target_scope = "geometry"
                    target_ids = [int(value) for value in target.get("geometry_ids") or [] if isinstance(value, int)]
                if target_scope and target_ids:
                    active_target = {
                        "scope": target_scope,
                        "ids": [str(value) for value in target_ids],
                        "label": str(target.get("label") or "")[:160],
                        "confidence": 1.0,
                        "reason": "applied_cad_edit",
                        "project_id": project_id,
                        "variant_id": variant_id,
                        "updated_at": _now(),
                    }
            memory["active_cad_context"] = {
                "schema": "cad.active-context.v1",
                "project_id": project_id,
                "variant_id": variant_id,
                "parent_variant_id": str((variant or {}).get("parent_variant_id") or "") if isinstance(variant, dict) else "",
                "selected_object_ids": sorted(set(selected_object_ids)),
                "selected_geometry_ids": sorted(set(selected_geometry_ids)),
                "logical_object_ids": sorted(set(logical_object_ids)),
                "geometry_ids": sorted({
                    int(item.get("id")) for item in (variant.get("geometries") or [])
                    if isinstance(item, dict) and isinstance(item.get("id"), int)
                }) if isinstance(variant, dict) else [],
                "identity_contract": deepcopy(identity_contract) if isinstance(identity_contract, dict) else None,
                "active_target": active_target,
                "updated_at": _now(),
            }
        pending = result.get("pending_action")
        if isinstance(pending, dict):
            identifier = str(pending.get("id") or pending.get("action_id") or "").strip()
            if identifier:
                self._add(memory, "action", identifier, str(pending.get("name") or identifier), "pending_action")
            self._learn_mapping(memory, pending, "pending_action")
        self._learn_mapping(memory, result, "agent_result")
        for tool in result.get("tool_results", []) if isinstance(result.get("tool_results"), list) else []:
            if isinstance(tool, dict):
                self._learn_mapping(memory, tool, "tool_result")

    def _learn_mapping(self, memory: dict[str, Any], value: dict[str, Any], source: str) -> None:
        arguments = value.get("arguments")
        if isinstance(arguments, dict):
            self._learn_mapping(memory, arguments, source)
        project = value.get("project")
        if isinstance(project, dict) and project.get("id"):
            self._add(memory, "project", str(project["id"]), str(project.get("name") or project["id"]), source)
            for variant in project.get("variants", []) if isinstance(project.get("variants"), list) else []:
                if isinstance(variant, dict) and variant.get("id"):
                    self._add(memory, "variant", str(variant["id"]), str(variant.get("name") or variant["id"]), source)
        key_types = {
            "project_id": "project", "variant_id": "variant", "parent_variant_id": "variant",
            "file_name": "drawing", "source_file_name": "drawing", "task_id": "task",
            "printer_name": "printer", "mission_file": "drawing",
        }
        for key, object_type in key_types.items():
            identifier = str(value.get(key) or "").strip()
            if identifier:
                self._add(memory, object_type, identifier, identifier, source)

    @staticmethod
    def _add(
        memory: dict[str, Any], object_type: str, identifier: str, label: str, source: str
    ) -> None:
        if object_type not in OBJECT_TYPES or not identifier or len(identifier) > 255:
            return
        item = {
            "type": object_type,
            "id": identifier,
            "label": label[:160],
            "source": source,
            "mentioned_at": _now(),
        }
        values = memory["objects"].setdefault(object_type, [])
        values[:] = [existing for existing in values if existing.get("id") != identifier]
        values.insert(0, item)
        del values[MAX_OBJECTS_PER_TYPE:]
        memory["focus"] = item

    def _prune(self) -> None:
        if len(self._conversations) <= MAX_CONVERSATIONS:
            return
        ordered = sorted(
            self._conversations.values(), key=lambda item: str(item.get("updated_at") or ""), reverse=True
        )
        self._conversations = {item["conversation_id"]: item for item in ordered[:MAX_CONVERSATIONS]}

    @staticmethod
    def _public_workflow_state(memory: dict[str, Any]) -> dict[str, Any]:
        state = deepcopy(memory.get("workflow_state") or {})
        state["state_sha256"] = ConversationMemoryStore._state_signature(state)
        return state

    @staticmethod
    def _public(memory: dict[str, Any]) -> dict[str, Any]:
        return {
            "enabled": True,
            "conversation_id": memory["conversation_id"],
            "objects": deepcopy(memory.get("objects", {})),
            "focus": deepcopy(memory.get("focus")),
            "summary": deepcopy(memory.get("summary", {})),
            "requirement_profile": deepcopy(memory.get("requirement_profile", {})),
            "last_cad_edit": deepcopy(memory.get("last_cad_edit")),
            "active_cad_context": deepcopy(memory.get("active_cad_context")),
            "pending_cad_edit": deepcopy(memory.get("pending_cad_edit")),
            "candidate_navigation": deepcopy(memory.get("candidate_navigation")),
            "workflow_state": ConversationMemoryStore._public_workflow_state(memory),
            "updated_at": memory.get("updated_at"),
        }

    def _load(self) -> None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            conversations = payload.get("conversations") if isinstance(payload, dict) else None
            if isinstance(conversations, dict):
                self._conversations = {
                    key: value for key, value in conversations.items()
                    if self.valid_conversation_id(key) and isinstance(value, dict)
                }
        except (OSError, ValueError, TypeError):
            self._conversations = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps({"schema_version": "2.0", "conversations": self._conversations}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)


conversation_memory = ConversationMemoryStore()
