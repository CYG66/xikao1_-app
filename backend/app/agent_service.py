from __future__ import annotations

import json
import math
import os
import re
import http.client
import threading
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .audit_store import agent_audit
from .agent_skills import (
    check_drawing_feasibility,
    clarify_requirements,
    drawing_template_geometries,
    drawing_template_motion_steps,
    layer_drawing_paths,
    parameterize_design,
    recommend_recovery,
    recognize_drawing_template,
    score_design_variant,
)
from .creative_projects import creative_projects
from .database import xline_database
from .creative_workflow import (
    build_project_acceptance_report,
    prepare_project_plan,
    prepare_project_recovery,
    project_recovery_assessment,
    refresh_project_execution,
    refresh_project_plan,
)
from .drawing_store import available_drawings, cad_directory, preview_paths, resolve_drawing
from .drawing_versions import drawing_versions
from .ros_adapter import ros_adapter
from .state import robot_state
from .task_store import agent_tasks
from .tooling import (
    OPENAI_TOOLS,
    authorize_tool,
    validate_tool_arguments,
)


SYSTEM_PROMPT = """你是 XLine 划线机器人现场助手。请使用简洁中文回答。
你的职责是解释机器人状态、诊断未就绪原因、提出安全操作建议，并在必要时调用工具。
不得声称未上报的传感器数据已经正常。不得绕过 CAN 通信、电机、定位、喷码和任务联锁。
移动、启动任务、LN150 和喷码操作都必须通过工具提出，由用户在 App 中再次确认。
工作模式必须按以下顺序推进：需求采集、参数确认、候选方案、路径规划、安全检查、用户确认、执行、验收。
每轮最多追问一个最关键的缺失参数，并说明为什么需要它；参数齐全后先复述任务摘要，再询问是否生成候选方案。
候选方案和真实规划完成后，分别说明喷墨路径、转场路径、定位要求、风险和预计偏差。
任何运动或喷墨执行前必须明确显示“确认执行”，没有用户确认不得调用对应工具。
如果设备未就绪，先指出最先要处理的阻断项，并给出下一步操作；不要只回复“无法执行”。
任务暂停、失败或定位丢失时，先解释当前状态，再提供重新规划、避免重复喷墨和再次确认的恢复路径，不得自动恢复运动。
包含转向后前进等多个连续动作时，必须使用一次 drive_sequence 工具调用，禁止连续调用多个 drive_robot。
但 drive_sequence 只是有限时速度演示，不能用于声称精确的正方形、矩形、闭合路线或按尺寸验收的路径。
用户提出正方形、矩形、边长、闭合路线或要求角度/距离准确时，必须进入工作项目流程，生成图纸并交给 xline_cyg 路径规划器；
不得用固定时间直行和固定时间转向替代真实路径规划。Chat 模式的 movement_demo 仅用于低速短时演示，必须明确告知它不是精确定位运动。
停止机器人可以直接调用。路径建议必须给出尺寸、速度、风险和执行前检查项。
设计前必须参数化需求；喷码机未由用户指定时，先使用 get_robot_status 返回的已连接且在线喷码机。只有没有可用喷码机或存在多个可选喷码机时才询问用户。缺少图形或尺寸时先询问。保存图纸前必须检查可制造性并标记喷墨层。
用户提出新的设计目标时，应先创建创意项目；后续补充参数应更新同一项目，避免只保留在聊天文本中。
转场路径只能由 xline_cyg 规划器生成。发生异常时先判断是否需要停车，禁止自动恢复运动。
"""

SAFE_TOOL_NAMES = {
    "get_robot_status",
    "stop_robot",
    "parameterize_design",
    "clarify_requirements",
    "create_creative_project",
    "update_creative_project",
    "add_design_variant",
    "select_design_variant",
    "prepare_project_plan",
    "refresh_project_plan",
    "refresh_project_execution",
    "assess_project_recovery",
    "prepare_project_recovery",
    "generate_project_report",
    "check_drawing_feasibility",
    "layer_drawing_paths",
    "recommend_recovery",
}


# Generated from Pydantic models in tooling.py.
TOOLS = OPENAI_TOOLS
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


PROVIDERS = {
    "openai": ("OpenAI", "https://api.openai.com/v1"),
    "anthropic": ("Claude", "https://api.anthropic.com/v1"),
    "gemini": ("Gemini", "https://generativelanguage.googleapis.com/v1beta"),
    "deepseek": ("DeepSeek", "https://api.deepseek.com"),
    "qwen": ("通义千问", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    "kimi": ("Kimi", "https://api.moonshot.cn/v1"),
    "glm": ("智谱 GLM", "https://open.bigmodel.cn/api/paas/v4"),
    "minimax": ("MiniMax", "https://api.minimaxi.com/v1"),
}


class RobotAgentService:
    @staticmethod
    def normalize_agent_mode(mode: str | None) -> str:
        return "advanced" if mode in {"advanced", "work"} else "base"

    def __init__(self) -> None:
        self.pending: dict[str, PendingAction] = {}
        self.config_path = Path.home() / ".config" / "xline-agent.json"
        self.mode = os.getenv("XLINE_AGENT_PROVIDER", "deepseek").strip()
        if self.mode not in {*PROVIDERS, "local"}:
            self.mode = "deepseek"
        self.model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        self.api_keys: dict[str, str] = {}
        self._deepseek_lock = threading.Lock()
        self._deepseek_connection: http.client.HTTPSConnection | None = None
        if os.getenv("OPENAI_API_KEY"):
            self.api_keys["openai"] = os.environ["OPENAI_API_KEY"]
        self._load_config()
        self._restore_pending_actions()

    def _restore_pending_actions(self) -> None:
        for task in agent_tasks.recoverable_pending():
            try:
                expires_at = (
                    datetime.fromisoformat(str(task["expires_at"]))
                    .astimezone()
                    .replace(tzinfo=None)
                )
                self.pending[str(task["id"])] = PendingAction(
                    name=str(task["tool"]),
                    arguments=dict(task["arguments"]),
                    expires_at=expires_at,
                )
            except (KeyError, TypeError, ValueError):
                continue

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
    ) -> dict[str, Any]:
        self.mode = mode
        self.model = model.strip()
        if clear_api_key:
            self.api_keys.pop(self.mode, None)
        elif api_key is not None and api_key.strip():
            self.api_keys[self.mode] = api_key.strip()
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(
                {"mode": self.mode, "model": self.model, "api_keys": self.api_keys},
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
            if isinstance(payload.get("model"), str) and payload["model"].strip():
                self.model = payload["model"].strip()
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
        if self.mode == "anthropic":
            url = f"{base_url}/models/{self.model}"
            headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}
        elif self.mode == "gemini":
            url = f"{base_url}/models/{self.model}?key={self.api_key}"
            headers = {}
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

    def chat(
        self, message: str, history: list[dict[str, str]], *, mode: str = "chat"
    ) -> dict[str, Any]:
        mode = self.normalize_agent_mode(mode)
        raw_message = message
        if mode == "base":
            json_action = self._chat_json_movement(raw_message)
            if json_action is not None:
                return json_action
        local_action = self._local_intent(
            raw_message, allow_design=mode == "advanced"
        )
        if local_action is not None:
            return local_action
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
                "message": "智能助手尚未配置 API Key。请在小车后端设置 OPENAI_API_KEY 后重启服务。",
                "usage": self._empty_usage(),
                "pending_action": None,
            }
        if self.mode == "deepseek":
            return self._deepseek_chat(message, history, mode=mode)
        if self.mode != "openai":
            return self._compatible_chat(message, history)

        conversation = [
            {"role": item.get("role", "user"), "content": item.get("content", "")}
            for item in history[-4:]
            if item.get("content")
        ]
        conversation.append({"role": "user", "content": message})
        instructions = self._system_context()
        first = self._request(conversation, instructions)
        usage = self._usage(first)
        calls = [item for item in first.get("output", []) if item.get("type") == "function_call"]

        if not calls:
            return self._result(self._output_text(first), usage)

        followup_items: list[dict[str, Any]] = list(conversation)
        followup_items.extend(first.get("output", []))
        for call in calls:
            name = str(call.get("name", ""))
            raw_arguments = self._arguments(call.get("arguments"))
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
            if name in SAFE_TOOL_NAMES:
                output = self._execute_safe(name, arguments)
                followup_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": call.get("call_id"),
                        "output": json.dumps(output, ensure_ascii=False),
                    }
                )
                continue

            pending_action = self._register_pending(name, arguments)
            return self._result(
                self._confirmation_text(name, arguments),
                usage,
                pending_action,
            )

        second = self._request(followup_items, instructions)
        usage = self._add_usage(usage, self._usage(second))
        return self._result(self._output_text(second), usage)

    def _deepseek_chat(
        self, message: str, history: list[dict[str, str]], *, mode: str = "chat"
    ) -> dict[str, Any]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_context(message)},
            *[
                {"role": item.get("role", "user"), "content": item.get("content", "")}
                for item in history[-4:]
                if item.get("content")
            ],
            {"role": "user", "content": message},
        ]
        selected_tools = self._selected_deepseek_tools(message, mode=mode)
        first = self._deepseek_request(messages, selected_tools)
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
            return self._result(content, usage)

        drive_steps: list[dict[str, Any]] = []
        for call in calls:
            function = call.get("function") or {}
            if str(function.get("name", "")) != "drive_robot":
                continue
            step, _ = validate_tool_arguments(
                "drive_robot", self._arguments(function.get("arguments"))
            )
            if step is not None:
                drive_steps.append(step)
        if len(drive_steps) >= 2:
            sequence, error = validate_tool_arguments(
                "drive_sequence", {"steps": drive_steps}
            )
            if sequence is None:
                return self._result(error, usage)
            pending_action = self._register_pending("drive_sequence", sequence)
            return self._result(
                self._confirmation_text("drive_sequence", sequence),
                usage,
                pending_action,
            )

        messages.append(model_message)
        for call in calls:
            function = call.get("function") or {}
            name = str(function.get("name", ""))
            arguments, error = validate_tool_arguments(
                name, self._arguments(function.get("arguments"))
            )
            if arguments is None:
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.get("id"),
                    "content": json.dumps({"ok": False, "message": error}, ensure_ascii=False),
                })
                continue
            if name in SAFE_TOOL_NAMES:
                output = self._execute_safe(name, arguments)
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.get("id"),
                    "content": json.dumps(output, ensure_ascii=False),
                })
                continue
            pending_action = self._register_pending(name, arguments)
            return self._result(
                self._confirmation_text(name, arguments), usage, pending_action
            )

        second = self._deepseek_request(messages, selected_tools)
        usage = self._add_usage(usage, self._chat_usage(second))
        choices = second.get("choices") or []
        text = str(choices[0].get("message", {}).get("content") or "") if choices else ""
        return self._result(text or "工具调用已完成。", usage)

    def _deepseek_request(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": tools or DEEPSEEK_TOOLS,
            "tool_choice": "auto",
            "max_tokens": 1200,
        }
        with self._deepseek_lock:
            response = self._deepseek_response(payload)
            data = response.read().decode("utf-8")
        if response.status >= 400:
            raise RuntimeError(f"DeepSeek API 请求失败（{response.status}）：{data[:300]}")
        return json.loads(data)

    @staticmethod
    def _mode_message(message: str, mode: str) -> str:
        mode = RobotAgentService.normalize_agent_mode(mode)
        if mode == "base":
            return (
                "【当前模式：基础】这是底盘运动控制模式。用户描述前进、后退、转弯、绕圈、"
                "正方形、圆形、折线或任意运动图形时，必须生成合法运动 JSON，并调用 drive_robot 或 drive_sequence；"
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
            "必须创建项目并调用 xline_cyg 路径规划，禁止用 drive_sequence 的时间估算冒充精确路径。\n"
            + message
        )

    def chat_stream(
        self, message: str, history: list[dict[str, str]], *, mode: str = "chat"
    ):
        mode = self.normalize_agent_mode(mode)
        raw_message = message
        if mode == "base":
            json_action = self._chat_json_movement(raw_message)
            if json_action is not None:
                yield {"type": "result", **json_action}
                return
        local_action = self._local_intent(
            raw_message, allow_design=mode == "advanced"
        )
        if local_action is not None:
            yield {"type": "result", **local_action}
            return
        if self.mode != "deepseek" or not self.configured:
            yield {
                "type": "result",
                **self.chat(raw_message, history, mode=mode),
            }
            return

        message = self._mode_message(raw_message, mode)

        tools = self._selected_deepseek_tools(message, mode=mode)
        messages = [
            {"role": "system", "content": self._system_context(message)},
            *[
                {"role": item.get("role", "user"), "content": item.get("content", "")}
                for item in history[-4:]
                if item.get("content")
            ],
            {"role": "user", "content": message},
        ]
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "max_tokens": 600,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        content_parts: list[str] = []
        streamed_calls: dict[int, dict[str, str]] = {}
        usage = self._empty_usage()
        with self._deepseek_lock:
            response = self._deepseek_response(payload)
            if response.status >= 400:
                detail = response.read().decode("utf-8", errors="replace")
                raise RuntimeError(
                    f"DeepSeek API 请求失败（{response.status}）：{detail[:300]}"
                )
            while True:
                raw_line = response.readline()
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

        calls = [streamed_calls[index] for index in sorted(streamed_calls)]
        if calls:
            result = self._streamed_tool_result(calls, usage)
        else:
            content = "".join(content_parts).strip()
            result = self._chat_json_movement(content) if mode == "base" else None
            result = result or self._result(content, usage)
        yield {"type": "result", **result}

    def _streamed_tool_result(
        self, calls: list[dict[str, str]], usage: dict[str, int]
    ) -> dict[str, Any]:
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
            sequence, error = validate_tool_arguments(
                "drive_sequence", {"steps": drive_steps}
            )
            if sequence is None:
                return self._result(error, usage)
            pending = self._register_pending("drive_sequence", sequence)
            return self._result(
                self._confirmation_text("drive_sequence", sequence), usage, pending
            )

        safe_results: list[str] = []
        for call in calls:
            arguments, error = validate_tool_arguments(
                call["name"], self._arguments(call["arguments"])
            )
            if arguments is None:
                return self._result(error, usage)
            if call["name"] in SAFE_TOOL_NAMES:
                output = self._execute_safe(call["name"], arguments)
                safe_results.append(str(output.get("message") or json.dumps(output, ensure_ascii=False)))
                continue
            pending = self._register_pending(call["name"], arguments)
            return self._result(
                self._confirmation_text(call["name"], arguments), usage, pending
            )
        return self._result("\n".join(safe_results) or "工具调用已完成。", usage)

    def _deepseek_response(self, payload: dict[str, Any]) -> http.client.HTTPResponse:
        parsed = urlparse(PROVIDERS["deepseek"][1])
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if payload.get("stream") else "application/json",
            "Connection": "keep-alive",
        }
        for attempt in range(2):
            try:
                if self._deepseek_connection is None:
                    self._deepseek_connection = http.client.HTTPSConnection(
                        parsed.hostname, parsed.port or 443, timeout=45
                    )
                self._deepseek_connection.request(
                    "POST", "/chat/completions", body=body, headers=headers
                )
                return self._deepseek_connection.getresponse()
            except (OSError, http.client.HTTPException) as error:
                if self._deepseek_connection is not None:
                    self._deepseek_connection.close()
                self._deepseek_connection = None
                if attempt == 1:
                    raise RuntimeError(f"无法连接 DeepSeek：{error}") from error
        raise RuntimeError("无法连接 DeepSeek")

    @staticmethod
    def _selected_deepseek_tools(message: str, *, mode: str = "work") -> list[dict[str, Any]]:
        mode = RobotAgentService.normalize_agent_mode(mode)
        text = message.lower()
        names = {"get_robot_status", "stop_robot"}
        if any(word in text for word in (
            "走", "前进", "后退", "转", "绕圈", "圆形", "圆", "正方形",
            "矩形", "折线", "轨迹", "移动", "运动", "movement_demo",
            "movement_command", "linear", "angular",
        )):
            names.update({"drive_robot", "drive_sequence"})
        if mode == "advanced" and any(word in text for word in ("图", "cad", "矩形", "圆", "路径", "设计", "尺寸")):
            names.update({
                "parameterize_design",
                "clarify_requirements",
                "create_creative_project",
                "update_creative_project",
                "add_design_variant",
                "select_design_variant",
                "prepare_project_plan",
                "refresh_project_plan",
                "refresh_project_execution",
                "assess_project_recovery",
                "generate_project_report",
                "check_drawing_feasibility",
                "layer_drawing_paths",
            })
        if mode == "advanced" and any(word in text for word in ("任务", "规划", "执行", "划线")):
            names.update({
                "set_mission", "execute_prepared_mission",
                "refresh_project_plan", "refresh_project_execution",
            })
        if mode == "advanced" and any(word in text for word in ("喷码", "喷墨", "喷头", "墨量")):
            names.add("control_printer")
        if mode == "base" and any(
            word in text for word in ("喷码", "喷墨", "喷头", "墨量")
        ):
            names.add("printer_spray")
        if mode == "advanced" and any(word in text for word in ("ln150", "全站仪", "追踪", "调平")):
            names.add("control_ln150")
        if mode == "advanced" and any(word in text for word in ("故障", "异常", "恢复", "怎么办")):
            names.update({
                "recommend_recovery", "assess_project_recovery",
                "prepare_project_recovery",
            })
        if mode == "advanced" and any(word in text for word in ("报告", "验收", "偏差", "轨迹对比")):
            names.update({"refresh_project_execution", "generate_project_report"})
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

    def _register_pending(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        action_id = uuid.uuid4().hex
        action = PendingAction(
            name=name,
            arguments=arguments,
            expires_at=datetime.now() + timedelta(minutes=2),
        )
        self.pending[action_id] = action
        agent_tasks.create_pending(action_id, name, arguments, action.expires_at)
        result = {
            "id": action_id,
            "name": name,
            "label": self._action_label(name, arguments),
            "arguments": arguments,
            "expires_in_seconds": 120,
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
        preview = self._drawing_preview(name, arguments)
        if preview:
            result["preview_paths"] = preview
        return result

    @staticmethod
    def _drawing_payload(arguments: dict[str, Any]) -> dict[str, Any]:
        geometries = arguments.get("geometries")
        layered = layer_drawing_paths(
            geometries if isinstance(geometries, list) else [], "center"
        )
        return {
            "schema_version": "1.0",
            "unit": "mm",
            **layered,
        }

    def _drawing_preview(self, name: str, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        if name == "create_drawing":
            points = preview_paths(self._drawing_payload(arguments))
        elif name == "create_rectangle_drawing":
            width = float(arguments["width_m"])
            height = float(arguments["height_m"])
            points = [[[0.0, 0.0], [width, 0.0], [width, height], [0.0, height], [0.0, 0.0]]]
        else:
            return []
        return [
            {
                "namespace": "path_lines",
                "frame_id": "map",
                "route_type": "drawing",
                "color": {"r": 0.0, "g": 0.5, "b": 1.0, "a": 1.0},
                "points": path,
            }
            for path in points
            if len(path) >= 2
        ]

    def _compatible_chat(
        self, message: str, history: list[dict[str, str]]
    ) -> dict[str, Any]:
        provider_name, base_url = PROVIDERS[self.mode]
        system = self._system_context()
        messages = [
            {"role": item.get("role", "user"), "content": item.get("content", "")}
            for item in history[-4:]
            if item.get("content")
        ]
        messages.append({"role": "user", "content": message})
        if self.mode == "anthropic":
            url = f"{base_url}/messages"
            payload = {
                "model": self.model,
                "system": system,
                "messages": messages,
                "max_tokens": 1200,
            }
            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            }
        elif self.mode == "gemini":
            url = f"{base_url}/models/{self.model}:generateContent?key={self.api_key}"
            payload = {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [
                    {
                        "role": "model" if item["role"] == "assistant" else "user",
                        "parts": [{"text": item["content"]}],
                    }
                    for item in messages
                ],
                "generationConfig": {"maxOutputTokens": 1200},
            }
            headers = {"Content-Type": "application/json"}
        else:
            url = f"{base_url}/chat/completions"
            payload = {
                "model": self.model,
                "messages": [{"role": "system", "content": system}, *messages],
                "max_tokens": 1200,
            }
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"{provider_name} API 请求失败（{error.code}）：{detail[:200]}"
            ) from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"无法连接 {provider_name}：{error.reason}") from error

        if self.mode == "anthropic":
            text = "".join(str(item.get("text", "")) for item in result.get("content", []))
            raw = result.get("usage") or {}
            input_tokens = int(raw.get("input_tokens", 0))
            output_tokens = int(raw.get("output_tokens", 0))
        elif self.mode == "gemini":
            candidates = result.get("candidates") or []
            parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
            text = "".join(str(item.get("text", "")) for item in parts)
            raw = result.get("usageMetadata") or {}
            input_tokens = int(raw.get("promptTokenCount", 0))
            output_tokens = int(raw.get("candidatesTokenCount", 0))
        else:
            choices = result.get("choices") or []
            message_data = choices[0].get("message", {}) if choices else {}
            text = str(message_data.get("content") or "")
            raw = result.get("usage") or {}
            input_tokens = int(raw.get("prompt_tokens", 0))
            output_tokens = int(raw.get("completion_tokens", 0))
        usage = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }
        if not text.strip():
            finish_reason = choices[0].get("finish_reason") if choices else None
            raise RuntimeError(
                f"{provider_name} 未返回正文（finish_reason={finish_reason or 'unknown'}）。"
                "请确认模型名称有效，或改用该服务商的标准对话模型。"
            )
        return self._result(text, usage)

    def _local_intent(
        self, message: str, *, allow_design: bool = True
    ) -> dict[str, Any] | None:
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
                self._register_pending("printer_spray", arguments),
            )
        if any(word in normalized for word in ("当前状态", "小车状态", "是否就绪", "能否控制")):
            return self._result(self._local_diagnosis(), self._empty_usage())
        if normalized.strip() in {"停车", "停止", "立即停车", "停下"}:
            output = self._execute_safe("stop_robot", {})
            return self._result(str(output["message"]), self._empty_usage())
        template_match = recognize_drawing_template(normalized)
        if template_match is not None:
            template_action = self._local_template_intent(
                raw_message=message,
                match=template_match,
                allow_design=allow_design,
            )
            if template_action is not None:
                return template_action
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
            square_match = re.search(
                r"(?:边长|边长为|side)\s*(\d+(?:\.\d+)?)\s*(?:米|m)",
                normalized,
            )
            if square_match is not None and any(
                word in normalized for word in ("正方形", "方形", "square")
            ):
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
                    f"已生成 Chat 正方形移动演示，共 {len(steps)} 段，边长约 {side:g} 米。"
                    "这是开环演示，不保证边长和 90 度角精度；请确认后执行。",
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
            if not (0.1 <= radius <= 25):
                return self._result("圆的半径必须在 0.1 到 25 米之间。", self._empty_usage())
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
            project = creative_projects.create(
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
            variant = creative_projects.add_variant(
                project["id"], "快速圆形方案", geometries,
                "按输入半径生成的闭合圆形喷墨路径", assessment,
                preview_paths({"lines": geometries}),
            )
            if variant is not None:
                creative_projects.select_variant(project["id"], variant["id"])
            return self._result(
                f"已创建创意项目“{project['name']}”和一个候选方案，已进入待规划状态。"
                "下一步可提交 ROS2 规划预览，规划不会启动小车。",
                self._empty_usage(),
            )
        match = re.search(r"(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)", normalized)
        if match is None:
            return None
        width = float(match.group(1))
        height = float(match.group(2))
        if not (0.1 <= width <= 50 and 0.1 <= height <= 50):
            return self._result(
                "矩形尺寸必须在 0.1 到 50 米之间。", self._empty_usage()
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
        project = creative_projects.create(
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
        variant = creative_projects.add_variant(
            project["id"], "快速矩形方案", geometries,
            "按输入尺寸生成的闭合矩形喷墨路径", assessment,
            preview_paths({"lines": geometries}),
        )
        if variant is not None:
            creative_projects.select_variant(project["id"], variant["id"])
        return self._result(
            f"已创建创意项目“{project['name']}”和一个候选方案。项目编号：{project['id']}。"
            "下一步可提交 ROS2 规划预览，规划不会启动小车。",
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

        geometries = drawing_template_geometries(match)
        project = creative_projects.create(
            f"{label}快速方案",
            raw_message,
            {
                "shape": match["template"],
                "template": match["template"],
                "dimensions": {
                    key: value
                    for key, value in match.items()
                    if key.endswith("_m") and isinstance(value, (int, float))
                },
                "printer": "center",
                "origin": "current_robot_pose",
                "units": "m",
            },
            {},
            [],
        )
        assessment = score_design_variant(geometries)
        variant = creative_projects.add_variant(
            project["id"],
            f"{label}候选方案",
            geometries,
            f"根据图纸模板“{label}”本地快速生成",
            assessment,
            preview_paths({"lines": geometries}),
        )
        if variant is not None:
            creative_projects.select_variant(project["id"], variant["id"])
        return self._result(
            f"已本地识别“{label}”模板，创建项目“{project['name']}”和候选方案。"
            "下一步将进入 xline_cyg 路径规划预览，不会直接启动小车。",
            self._empty_usage(),
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
        action = self.pending.pop(action_id, None)
        if action is None or action.expires_at < datetime.now():
            agent_tasks.transition(action_id, "expired", "确认已过期")
            return {"ok": False, "message": "操作已失效，请重新向助手发出指令。"}
        if not approved:
            agent_tasks.transition(action_id, "cancelled", "用户取消操作")
            return {"ok": True, "message": "已取消操作。"}
        agent_tasks.transition(action_id, "executing", "用户已确认，开始执行")
        try:
            result = self._execute_confirmed(action, client_id=client_id)
        except Exception as error:
            failure = {"ok": False, "message": f"Agent 工具执行异常：{error}"}
            agent_tasks.transition(action_id, "failed", failure["message"], failure)
            robot_state.add_log(f"agent task {action_id} failed: {error}")
            return failure
        final_state = "completed" if result.get("ok") is True else "failed"
        agent_tasks.transition(action_id, final_state, str(result.get("message", "")), result)
        return {**result, "task_id": action_id, "task_state": final_state}

    def request_confirmation(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        validated, error = validate_tool_arguments(name, arguments)
        if validated is None:
            return {"ok": False, "message": error, "pending_action": None}
        return {
            "ok": True,
            "message": self._confirmation_text(name, validated),
            "pending_action": self._register_pending(name, validated),
        }

    def _request(self, input_items: list[dict[str, Any]], instructions: str) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "instructions": instructions,
            "input": input_items,
            "tools": TOOLS,
            "tool_choice": "auto",
            "max_output_tokens": int(os.getenv("OPENAI_MAX_OUTPUT_TOKENS", "600")),
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
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI API 请求失败 ({error.code}): {detail[:300]}") from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"无法连接 OpenAI API: {error.reason}") from error

    def _local_diagnosis(self) -> str:
        missing = ", ".join(robot_state.missing_required_nodes) or "无"
        lines = [
            "本地诊断结果：",
            f"- ROS2：{'可用' if robot_state.ros_available else '不可用'}",
            f"- 底盘控制：{'就绪' if robot_state.control_ready else '未就绪'}",
            f"- 定位：{'已收到 /robot_pose' if robot_state.robot_pose else '无 /robot_pose 数据'}",
            f"- 任务阶段：{robot_state.mission_stage}",
            f"- 缺少节点：{missing}",
        ]
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

    def _execute_safe(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        decision = authorize_tool(name, arguments, confirmed=True)
        if not decision.allowed:
            result = {"ok": False, "message": decision.message}
            agent_audit.append("safe_tool_blocked", name, arguments, result)
            return result
        if name == "stop_robot":
            ok = ros_adapter.stop_agent_motion("AI stop tool requested")
            result = {"ok": ok, "message": "停车指令已发送"}
        elif name == "parameterize_design":
            result = parameterize_design(str(arguments["prompt"]))
        elif name == "clarify_requirements":
            result = clarify_requirements(str(arguments["prompt"]))
        elif name == "create_creative_project":
            requirements = parameterize_design(str(arguments["prompt"]))
            project = creative_projects.create(
                str(arguments["name"]),
                str(arguments["prompt"]),
                requirements,
                dict(arguments.get("constraints") or {}),
                list(requirements["missing"]),
            )
            result = {"ok": True, "project": project}
        elif name == "update_creative_project":
            project = creative_projects.update(
                str(arguments["project_id"]),
                requirements=(dict(arguments["requirements"])
                              if isinstance(arguments.get("requirements"), dict) else None),
                constraints=(dict(arguments["constraints"])
                             if isinstance(arguments.get("constraints"), dict) else None),
                missing_parameters=(list(arguments["missing_parameters"])
                                    if isinstance(arguments.get("missing_parameters"), list) else None),
                event_message="AI 补充了项目需求",
            )
            result = ({"ok": True, "project": project} if project is not None
                      else {"ok": False, "message": "创意项目不存在"})
        elif name == "add_design_variant":
            geometries = list(arguments["geometries"])
            assessment = score_design_variant(geometries)
            variant = creative_projects.add_variant(
                str(arguments["project_id"]), str(arguments["name"]), geometries,
                str(arguments.get("rationale") or ""), assessment,
                preview_paths({"lines": geometries}),
            )
            result = ({"ok": True, "variant": variant} if variant is not None
                      else {"ok": False, "message": "创意项目不存在"})
        elif name == "select_design_variant":
            project = creative_projects.select_variant(
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
        elif name == "layer_drawing_paths":
            result = layer_drawing_paths(
                list(arguments["geometries"]), str(arguments["printer"])
            )
            result["ok"] = True
        elif name == "recommend_recovery":
            result = recommend_recovery(robot_state.snapshot())
        else:
            result = robot_state.snapshot()
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
        args, validation_error = validate_tool_arguments(action.name, action.arguments)
        if args is None:
            return {"ok": False, "message": validation_error}
        decision = authorize_tool(
            action.name, args, confirmed=True, client_id=client_id
        )
        if not decision.allowed:
            return {"ok": False, "message": decision.message}
        if action.name == "create_drawing":
            geometries = list(args["geometries"])
            ids = [int(item["id"]) for item in geometries]
            if len(ids) != len(set(ids)):
                return {"ok": False, "message": "图纸几何 ID 不能重复。"}
            feasibility = check_drawing_feasibility(geometries)
            if feasibility["ok"] is not True:
                return {
                    "ok": False,
                    "message": "图纸可制造性检查未通过：" + "；".join(feasibility["errors"]),
                    "feasibility": feasibility,
                }
            payload = self._drawing_payload(args)
            preview = self._drawing_preview(action.name, args)
            if not preview:
                return {"ok": False, "message": "图纸没有可预览的有效几何。"}
            file_name = str(args["file_name"])
            directory = cad_directory()
            directory.mkdir(parents=True, exist_ok=True)
            version = drawing_versions.save(directory, file_name, payload, "agent", "AI 生成图纸")
            file_name = str(version["file_name"])
            robot_state.add_log(f"agent created drawing {file_name}")
            return {
                "ok": True,
                "message": f"已保存 AI 图纸 {file_name}。请检查预览，再单独确认是否规划和执行。",
                "file_name": file_name,
                "drawing_json": payload,
                "preview_paths": preview,
                "next_action": "plan_preview",
                "feasibility": feasibility,
                "path_layers": payload["layers"],
                "version": version,
            }
        if action.name == "create_rectangle_drawing":
            width = float(args["width_m"])
            height = float(args["height_m"])
            width_mm = round(width * 1000, 3)
            height_mm = round(height * 1000, 3)
            size_name = f"{width:g}x{height:g}".replace(".", "_")
            file_name = f"agent_rectangle_{size_name}m.json"
            payload = {
                "layers": [{"layer_id": 1, "name": "agent_rectangle"}],
                "lines": [
                    {
                        "id": 1,
                        "type": "polyline",
                        "layer_id": 1,
                        "closed": True,
                        "vertices": [
                            {"x": 0, "y": 0, "z": 0},
                            {"x": width_mm, "y": 0, "z": 0},
                            {"x": width_mm, "y": height_mm, "z": 0},
                            {"x": 0, "y": height_mm, "z": 0},
                        ],
                    }
                ],
            }
            directory = cad_directory()
            directory.mkdir(parents=True, exist_ok=True)
            version = drawing_versions.save(directory, file_name, payload, "agent", "AI 生成矩形")
            file_name = str(version["file_name"])
            robot_state.add_log(f"agent created drawing {file_name}")
            return {
                "ok": True,
                "message": f"已保存图纸 {file_name}。请在任务页预览并检查后再启动。",
                "file_name": file_name,
                "version": version,
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
                if not ros_adapter.set_printer_active(printer_name, True):
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
            active_ok = ros_adapter.set_printer_active(printer_name, False)
            return {
                "ok": stop_ok and active_ok,
                "message": "已停止喷墨。" if stop_ok and active_ok else "停止喷墨失败。",
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

    @staticmethod
    def _system_context(message: str = "") -> str:
        snapshot = robot_state.snapshot()
        text = message.lower()
        status_keys = {
            "online",
            "emergency_stopped",
            "control_ready",
            "control_owner",
            "drive_device_connected",
            "motor_driver_ready",
            "mission_running",
            "localization_valid",
            "localization_source",
        }
        if any(word in text for word in ("喷码", "喷墨", "喷头", "墨量")):
            status_keys.update({"printer_ready", "printer_status"})
        if any(word in text for word in ("任务", "规划", "执行", "划线", "路径")):
            status_keys.update({
                "mission_nodes_ready",
                "mission_stage",
                "mission_file",
                "mission_error",
            })
        if any(word in text for word in ("定位", "地图", "全站仪", "ln150", "位姿")):
            status_keys.update({"robot_pose", "odometry", "ln150_ready"})
        compact_status = {
            key: snapshot.get(key) for key in status_keys if key in snapshot
        }
        context = (
            SYSTEM_PROMPT
            + "\n只回答当前问题，先给结论，避免重复说明。"
            + "\n相关机器人状态：\n"
            + json.dumps(compact_status, ensure_ascii=False)
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
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "configured": True,
            "message": message,
            "usage": usage,
            "pending_action": pending_action,
        }

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
            "create_rectangle_drawing": "创建矩形 JSON 图纸",
            "create_drawing": "生成并保存 CAD JSON 图纸草稿",
        }
        return labels.get(name, name)

    def _confirmation_text(self, name: str, arguments: dict[str, Any]) -> str:
        return f"我准备{self._action_label(name, arguments)}。请检查周围环境和急停装置，然后在下方确认。"


robot_agent = RobotAgentService()
