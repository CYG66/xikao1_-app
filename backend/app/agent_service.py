from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .ros_adapter import ros_adapter
from .state import robot_state


SYSTEM_PROMPT = """你是 XLine 划线机器人现场助手。请使用简洁中文回答。
你的职责是解释机器人状态、诊断未就绪原因、提出安全操作建议，并在必要时调用工具。
不得声称未上报的传感器数据已经正常。不得绕过 USB2CAN、电机、定位、喷码和任务联锁。
移动、启动任务、LN150 和喷码操作都必须通过工具提出，由用户在 App 中再次确认。
停止机器人可以直接调用。路径建议必须给出尺寸、速度、风险和执行前检查项。
"""


TOOLS = [
    {
        "type": "function",
        "name": "get_robot_status",
        "description": "读取当前机器人、ROS2、USB2CAN、定位、喷码和任务状态。",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function",
        "name": "stop_robot",
        "description": "立即向底盘发布零速度停车指令。该安全操作无需二次确认。",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function",
        "name": "drive_robot",
        "description": "提出短距离人工驾驶操作，执行前必须由用户确认。",
        "parameters": {
            "type": "object",
            "properties": {
                "linear": {"type": "number", "minimum": -0.1, "maximum": 0.1},
                "angular": {"type": "number", "minimum": -0.4, "maximum": 0.4},
                "duration_seconds": {"type": "number", "minimum": 0.1, "maximum": 0.3},
            },
            "required": ["linear", "angular", "duration_seconds"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "set_mission",
        "description": "提出启动或停止完整划线任务，执行前必须由用户确认。",
        "parameters": {
            "type": "object",
            "properties": {
                "running": {"type": "boolean"},
                "file_name": {
                    "type": "string",
                    "enum": ["test_pattern.json", "huanong_skeleton.json", "square_image.json"],
                },
            },
            "required": ["running", "file_name"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "control_ln150",
        "description": "提出 LN150 初始化、自动追踪或自动调平操作。1=初始化，2=自动追踪，3=自动调平。",
        "parameters": {
            "type": "object",
            "properties": {"command_type": {"type": "integer", "minimum": 1, "maximum": 3}},
            "required": ["command_type"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "control_printer",
        "description": "提出喷码机操作，执行前必须由用户确认。",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["beep", "start_print", "stop_print"]}
            },
            "required": ["action"],
            "additionalProperties": False,
        },
        "strict": True,
    },
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
    def __init__(self) -> None:
        self.pending: dict[str, PendingAction] = {}
        self.config_path = Path.home() / ".config" / "xline-agent.json"
        self.mode = "openai"
        self.model = os.getenv("OPENAI_MODEL", "gpt-5-mini")
        self.api_keys: dict[str, str] = {}
        if os.getenv("OPENAI_API_KEY"):
            self.api_keys["openai"] = os.environ["OPENAI_API_KEY"]
        self._load_config()

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

    def chat(self, message: str, history: list[dict[str, str]]) -> dict[str, Any]:
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
        if self.mode != "openai":
            return self._compatible_chat(message, history)

        conversation = [
            {"role": item.get("role", "user"), "content": item.get("content", "")}
            for item in history[-8:]
            if item.get("content")
        ]
        conversation.append({"role": "user", "content": message})
        status = robot_state.snapshot()
        instructions = SYSTEM_PROMPT + "\n当前机器人状态：\n" + json.dumps(status, ensure_ascii=False)
        first = self._request(conversation, instructions)
        usage = self._usage(first)
        calls = [item for item in first.get("output", []) if item.get("type") == "function_call"]

        if not calls:
            return self._result(self._output_text(first), usage)

        followup_items: list[dict[str, Any]] = list(conversation)
        followup_items.extend(first.get("output", []))
        for call in calls:
            name = str(call.get("name", ""))
            arguments = self._arguments(call.get("arguments"))
            if name in {"get_robot_status", "stop_robot"}:
                output = self._execute_safe(name)
                followup_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": call.get("call_id"),
                        "output": json.dumps(output, ensure_ascii=False),
                    }
                )
                continue

            action_id = uuid.uuid4().hex
            self.pending[action_id] = PendingAction(
                name=name,
                arguments=arguments,
                expires_at=datetime.now() + timedelta(minutes=2),
            )
            return self._result(
                self._confirmation_text(name, arguments),
                usage,
                {
                    "id": action_id,
                    "name": name,
                    "label": self._action_label(name, arguments),
                    "arguments": arguments,
                    "expires_in_seconds": 120,
                },
            )

        second = self._request(followup_items, instructions)
        usage = self._add_usage(usage, self._usage(second))
        return self._result(self._output_text(second), usage)

    def _compatible_chat(
        self, message: str, history: list[dict[str, str]]
    ) -> dict[str, Any]:
        provider_name, base_url = PROVIDERS[self.mode]
        status = json.dumps(robot_state.snapshot(), ensure_ascii=False)
        system = SYSTEM_PROMPT + "\n当前机器人状态：\n" + status
        messages = [
            {"role": item.get("role", "user"), "content": item.get("content", "")}
            for item in history[-8:]
            if item.get("content")
        ]
        messages.append({"role": "user", "content": message})
        if self.mode == "anthropic":
            url = f"{base_url}/messages"
            payload = {
                "model": self.model,
                "system": system,
                "messages": messages,
                "max_tokens": 600,
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
                "generationConfig": {"maxOutputTokens": 600},
            }
            headers = {"Content-Type": "application/json"}
        else:
            url = f"{base_url}/chat/completions"
            payload = {
                "model": self.model,
                "messages": [{"role": "system", "content": system}, *messages],
                "max_tokens": 600,
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
            text = str(choices[0].get("message", {}).get("content", "")) if choices else ""
            raw = result.get("usage") or {}
            input_tokens = int(raw.get("prompt_tokens", 0))
            output_tokens = int(raw.get("completion_tokens", 0))
        usage = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }
        return self._result(text or "模型没有返回文本内容。", usage)

    def confirm(self, action_id: str, approved: bool) -> dict[str, Any]:
        action = self.pending.pop(action_id, None)
        if action is None or action.expires_at < datetime.now():
            return {"ok": False, "message": "操作已失效，请重新向助手发出指令。"}
        if not approved:
            return {"ok": True, "message": "已取消操作。"}
        return self._execute_confirmed(action)

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
            lines.append("- 建议：检查 HDSC USB2CAN 设备和串口映射。")
        if not robot_state.robot_pose:
            lines.append("- 建议：检查 LN150、/reflector_position 与 localization 节点。")
        lines.append("本地模式只提供状态诊断，不执行自然语言工具调用。")
        return "\n".join(lines)

    def _execute_safe(self, name: str) -> dict[str, Any]:
        if name == "stop_robot":
            ok = ros_adapter.publish_velocity(0.0, 0.0)
            return {"ok": ok, "message": "停车指令已发送"}
        return robot_state.snapshot()

    def _execute_confirmed(self, action: PendingAction) -> dict[str, Any]:
        args = action.arguments
        if action.name == "drive_robot":
            if not robot_state.control_ready:
                return {"ok": False, "message": "USB2CAN 或电机节点未就绪，操作已阻止。"}
            ok = ros_adapter.publish_timed_velocity(
                float(args["linear"]),
                float(args["angular"]),
                float(args["duration_seconds"]),
            )
            duration = float(args["duration_seconds"])
            return {"ok": ok, "message": f"短时速度指令已发送；{duration:.1f} 秒后自动停车。"}
        if action.name == "set_mission":
            if bool(args["running"]) and not robot_state.mission_nodes_ready:
                return {"ok": False, "message": "任务节点未全部就绪，启动已阻止。"}
            ok = ros_adapter.control_mission(bool(args["running"]), str(args["file_name"]))
            return {"ok": ok, "message": "任务指令已发送。" if ok else robot_state.mission_error or "任务请求被拒绝。"}
        if action.name == "control_ln150":
            ok = ros_adapter.call_ln150(int(args["command_type"]))
            return {"ok": ok, "message": "LN150 指令已提交。" if ok else "LN150 服务不可用。"}
        if action.name == "control_printer":
            ok = ros_adapter.call_printer("center", str(args["action"]), 0)
            return {"ok": ok, "message": "喷码机指令已提交。" if ok else "喷码机服务不可用。"}
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
            "set_mission": "启动划线任务" if arguments.get("running") else "停止划线任务",
            "control_ln150": "执行 LN150 操作",
            "control_printer": "执行喷码机操作",
        }
        return labels.get(name, name)

    def _confirmation_text(self, name: str, arguments: dict[str, Any]) -> str:
        return f"我准备{self._action_label(name, arguments)}。请检查周围环境和急停装置，然后在下方确认。"


robot_agent = RobotAgentService()
