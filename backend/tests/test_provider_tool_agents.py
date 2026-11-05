from __future__ import annotations

import json
import os
import unittest
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

from app.agent_service import RobotAgentService, DEEPSEEK_TOOLS


def _make_service(mode: str, model: str = "test-model") -> RobotAgentService:
    service = object.__new__(RobotAgentService)
    service.mode = mode
    service.api_keys = {mode: "test-key"}
    service.model = model
    service.base_model = model
    service.advanced_model = model
    return service


def _plain_response(text: str) -> dict:
    return {
        "choices": [
            {"message": {"role": "assistant", "content": text, "tool_calls": None}}
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def _tool_response(calls: list[dict]) -> dict:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": calls,
                }
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def _http_json_response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return response


def _structured_resize_json() -> str:
    return json.dumps(
        {
            "schema_version": "cad.language-interpretation.v1",
            "is_cad_edit": True,
            "operation": "resize",
            "target": {"scope": "instance", "instance_ids": [1]},
            "parameters": {"dimension": "width", "value_mm": 30000},
            "assumptions": [],
            "constraints": [],
            "evidence_text": ["第1个篮球场", "宽度改为30米"],
            "confidence": 0.92,
        },
        ensure_ascii=False,
    )


def _conversation_review_json() -> str:
    return json.dumps(
        {
            "primary_intent": "conversation",
            "cad_operation": None,
            "secondary_intents": [],
            "confidence": 0.95,
            "requires_clarification": False,
            "clarification_question": None,
            "reason": "普通对话",
        },
        ensure_ascii=False,
    )


class ProviderToolAgentTest(unittest.TestCase):
    """Every configured provider must be able to run the full agent:
    tool calls, CAD edits, project generation and robot control."""

    def test_qwen_chat_uses_full_agent_path(self) -> None:
        service = _make_service("qwen", "qwen3.7-max")
        with patch.object(
            service,
            "_openai_compatible_request",
            side_effect=[
                _plain_response(_conversation_review_json()),
                _plain_response("你好"),
            ],
        ) as request:
            result = service.chat("你好", [], mode="advanced")
        # 1 intent-review call + 1 main conversation call
        self.assertEqual(request.call_count, 2)
        self.assertEqual(result["message"], "你好")
        self.assertIsNone(result["pending_action"])

    def test_kimi_chat_routes_to_full_agent(self) -> None:
        service = _make_service("kimi", "kimi-k2.5")
        with patch.object(
            service,
            "_openai_compatible_request",
            side_effect=[
                _plain_response(_conversation_review_json()),
                _plain_response("已收到"),
            ],
        ) as request:
            result = service.chat("你好", [], mode="advanced")
        # 1 intent-review call + 1 main conversation call
        self.assertEqual(request.call_count, 2)
        self.assertEqual(result["message"], "已收到")

    def test_openai_compatible_providers_complete_tool_loop(self) -> None:
        """GLM/Kimi/MiniMax must complete the same tool protocol as Qwen."""
        for provider in ("glm", "kimi", "minimax"):
            with self.subTest(provider=provider):
                service = _make_service(provider)
                first = _tool_response(
                    [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "stop_robot",
                                "arguments": "{}",
                            },
                        }
                    ]
                )
                with patch.object(
                    service,
                    "_openai_compatible_request",
                    side_effect=[first, _plain_response("已安全停车。")],
                ) as request:
                    with patch.object(
                        service,
                        "_execute_safe",
                        return_value={"ok": True, "message": "停车命令已发布"},
                    ) as execute:
                        result = service.chat("立即停车", [], mode="advanced")
                self.assertEqual(request.call_count, 2)
                execute.assert_called_once_with("stop_robot", {}, mode="advanced")
                self.assertEqual(result["message"], "已安全停车。")

    def test_openai_compatible_providers_use_real_adapter_transport(self) -> None:
        for provider in ("glm", "kimi", "minimax"):
            with self.subTest(provider=provider):
                service = _make_service(provider)
                first = _tool_response(
                    [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "stop_robot", "arguments": "{}"},
                        }
                    ]
                )
                with (
                    patch.dict(
                        os.environ,
                        {"XLINE_AGENT_MODEL_REQUEST_TIMEOUT_SECONDS": "19"},
                    ),
                    patch(
                        "app.model_providers.urllib.request.urlopen",
                        side_effect=[
                            _http_json_response(first),
                            _http_json_response(_plain_response("已安全停车。")),
                        ],
                    ) as urlopen,
                    patch.object(
                        service,
                        "_execute_safe",
                        return_value={"ok": True, "message": "停车命令已发布"},
                    ),
                ):
                    result = service.chat("立即停车", [], mode="advanced")

                self.assertEqual("已安全停车。", result["message"])
                self.assertEqual(2, urlopen.call_count)
                first_request = urlopen.call_args_list[0].args[0]
                second_request = urlopen.call_args_list[1].args[0]
                first_payload = json.loads(first_request.data.decode("utf-8"))
                second_payload = json.loads(second_request.data.decode("utf-8"))
                self.assertTrue(first_request.full_url.endswith("/chat/completions"))
                self.assertNotIn("test-key", first_request.full_url)
                self.assertEqual(
                    "Bearer test-key", first_request.headers["Authorization"]
                )
                self.assertIn("tools", first_payload)
                self.assertTrue(
                    any(item.get("role") == "tool" for item in second_payload["messages"])
                )
                self.assertTrue(
                    all(call.kwargs["timeout"] == 19.0 for call in urlopen.call_args_list)
                )

    def test_openai_responses_completes_tool_loop(self) -> None:
        service = _make_service("openai", "gpt-test")
        first = {
            "output": [
                {
                    "type": "function_call",
                    "name": "stop_robot",
                    "call_id": "call_1",
                    "arguments": "{}",
                }
            ],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        second = {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "已安全停车。"}],
                }
            ],
            "usage": {"input_tokens": 20, "output_tokens": 6},
        }
        with patch.object(service, "_request", side_effect=[first, second]) as request:
            with patch.object(
                service,
                "_execute_safe",
                return_value={"ok": True, "message": "停车命令已发布"},
            ) as execute:
                result = service.chat("立即停车", [], mode="advanced")
        self.assertEqual(request.call_count, 2)
        execute.assert_called_once_with("stop_robot", {}, mode="advanced")
        followup = request.call_args_list[1].args[0]
        self.assertTrue(
            any(item.get("type") == "function_call_output" for item in followup)
        )
        self.assertEqual(result["message"], "已安全停车。")

    def test_qwen_executes_safe_tool_and_forwards_results(self) -> None:
        service = _make_service("qwen")
        first = _tool_response(
            [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "stop_robot", "arguments": "{}"},
                }
            ]
        )
        second = _plain_response("已安全停车。")
        with patch.object(
            service,
            "_openai_compatible_request",
            side_effect=[first, second],
        ) as request:
            with patch.object(
                service,
                "_execute_safe",
                return_value={"ok": True, "message": "停车命令已发布"},
            ) as execute:
                result = service.chat("立即停车", [], mode="advanced")
        self.assertEqual(request.call_count, 2)
        execute.assert_called_once_with("stop_robot", {}, mode="advanced")
        # 工具结果必须回填到第二轮请求
        second_messages = request.call_args_list[1].args[1]
        self.assertTrue(
            any(
                item.get("role") == "tool"
                and item.get("tool_call_id") == "call_1"
                for item in second_messages
            )
        )
        self.assertEqual(result["message"], "已安全停车。")

    def test_qwen_advanced_drive_sequence_rejected_by_policy(self) -> None:
        # The existing safety policy excludes drive tools from the advanced
        # whitelist; the gate must surface that reason instead of executing.
        service = _make_service("qwen")
        drive_step = {"linear": 0.5, "angular": 0.0, "duration_seconds": 2}
        first = _tool_response(
            [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {
                        "name": "drive_robot",
                        "arguments": json.dumps(drive_step, ensure_ascii=False),
                    },
                },
                {
                    "id": "c2",
                    "type": "function",
                    "function": {
                        "name": "drive_robot",
                        "arguments": json.dumps(drive_step, ensure_ascii=False),
                    },
                },
            ]
        )
        motion_review = json.dumps(
            {
                "primary_intent": "motion_control",
                "cad_operation": None,
                "secondary_intents": [],
                "confidence": 0.95,
                "requires_clarification": False,
                "clarification_question": None,
                "reason": "连续底盘运动",
            },
            ensure_ascii=False,
        )
        with patch.object(
            service,
            "_openai_compatible_request",
            side_effect=[_plain_response(motion_review), first],
        ) as request:
            result = service.chat("前进两米然后左转", [], mode="advanced")
        # 1 intent-review call ("然后" triggers review) + 1 main tool-loop call
        self.assertEqual(request.call_count, 2)
        self.assertIn("不允许调用 drive_sequence", result["message"])
        self.assertIsNone(result["pending_action"])

    def test_dispatch_tool_calls_returns_pending_confirmation(self) -> None:
        service = _make_service("qwen")
        calls = [
            {
                "id": "c1",
                "name": "drive_robot",
                "arguments": {"linear": 0.5, "angular": 0.0, "duration_seconds": 2},
            }
        ]
        usage = {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}
        with patch.object(
            service,
            "_register_pending",
            return_value={"name": "drive_robot", "mode": "base"},
        ) as pending:
            with patch.object(
                service, "_confirmation_text", return_value="确认执行"
            ) as confirm:
                early, tool_results = service._dispatch_tool_calls(
                    calls,
                    usage,
                    None,
                    "base",
                    append_result=lambda call, output: None,
                )
        pending.assert_called_once()
        confirm.assert_called_once()
        self.assertIsNotNone(early)
        self.assertEqual(early["message"], "确认执行")
        self.assertEqual(early["pending_action"]["name"], "drive_robot")
        self.assertEqual(tool_results, [])

    def test_dispatch_create_project_binds_id_for_following_update(self) -> None:
        service = _make_service("qwen")
        route = {}
        calls = [
            {
                "id": "c1", "name": "create_creative_project",
                "arguments": {
                    "name": "房屋", "prompt": "房屋正视图",
                    "constraints": {},
                },
            },
            {
                "id": "c2", "name": "update_creative_project",
                "arguments": {
                    "project_id": "generated-project-id",
                    "requirements": {"shape": "house_front_elevation"},
                    "missing_parameters": [],
                },
            },
        ]
        outputs = [
            {"ok": True, "project": {"id": "generated-project-id"}},
            {"ok": True, "project": {"id": "generated-project-id"}},
        ]
        seen: list[tuple[str, dict]] = []

        def execute(name, arguments, *, mode):
            seen.append((name, dict(arguments)))
            return outputs.pop(0)

        with patch.object(service, "_execute_safe", side_effect=execute):
            early, tool_results = service._dispatch_tool_calls(
                calls, {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                route, "advanced", append_result=lambda call, output: None,
            )
        self.assertIsNone(early)
        self.assertEqual(route["selected_project_id"], "generated-project-id")
        self.assertEqual(route["project_id"], "generated-project-id")
        self.assertEqual(seen[1][1]["project_id"], "generated-project-id")

    def test_minimax_request_carries_tools_without_strict(self) -> None:
        service = _make_service("minimax", "MiniMax-M2.7")
        captured: list[dict] = []

        def fake_request(provider, messages, tools=None, *, model, max_tokens):
            captured.append(tools or [])
            return _tool_response(
                [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "stop_robot", "arguments": "{}"},
                    }
                ]
            )

        with patch.object(
            service, "_openai_compatible_request", side_effect=fake_request
        ):
            with patch.object(
                service,
                "_execute_safe",
                return_value={"ok": True, "message": "ok"},
            ):
                service.chat("立即停车", [], mode="advanced")
        self.assertTrue(captured)
        for tool in captured[0]:
            self.assertNotIn("strict", tool["function"])
            self.assertEqual(tool["type"], "function")

    def test_anthropic_native_tool_schema_and_tool_result(self) -> None:
        service = _make_service("anthropic", "claude-sonnet-4-20250514")
        first = {
            "content": [
                {"type": "tool_use", "id": "tu_1", "name": "stop_robot", "input": {}}
            ],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        second = {
            "content": [{"type": "text", "text": "已停止。"}],
            "usage": {"input_tokens": 20, "output_tokens": 6},
        }
        with patch.object(
            service, "_anthropic_request", side_effect=[first, second]
        ) as request:
            with patch.object(
                service,
                "_execute_safe",
                return_value={"ok": True, "message": "ok"},
            ) as execute:
                result = service.chat("立即停车", [], mode="advanced")
        self.assertEqual(request.call_count, 2)
        execute.assert_called_once()
        payload = request.call_args_list[0].args[0]
        self.assertIn("tools", payload)
        self.assertIn("input_schema", payload["tools"][0])
        second_payload = request.call_args_list[1].args[0]
        self.assertTrue(
            any(
                message.get("role") == "user"
                and isinstance(message.get("content"), list)
                and message["content"]
                and message["content"][0].get("type") == "tool_result"
                for message in second_payload["messages"]
            )
        )
        self.assertEqual(result["message"], "已停止。")

    def test_gemini_function_declaration_and_response(self) -> None:
        service = _make_service("gemini", "gemini-2.5-flash")
        first = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"functionCall": {"name": "stop_robot", "args": {}}}
                        ]
                    }
                }
            ],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
        }
        second = {
            "candidates": [{"content": {"parts": [{"text": "已停止。"}]}}],
            "usageMetadata": {"promptTokenCount": 20, "candidatesTokenCount": 6},
        }
        with patch.object(
            service, "_gemini_request", side_effect=[first, second]
        ) as request:
            with patch.object(
                service,
                "_execute_safe",
                return_value={"ok": True, "message": "ok"},
            ) as execute:
                result = service.chat("立即停车", [], mode="advanced")
        self.assertEqual(request.call_count, 2)
        execute.assert_called_once()
        payload = request.call_args_list[0].args[1]
        self.assertIn("tools", payload)
        self.assertIn("functionDeclarations", payload["tools"][0])
        second_payload = request.call_args_list[1].args[1]
        self.assertTrue(
            any(
                "functionResponse" in part
                for message in second_payload["contents"]
                for part in message.get("parts", [])
            )
        )
        self.assertEqual(result["message"], "已停止。")

    def test_tool_schema_adapters(self) -> None:
        service = _make_service("qwen")
        sample = [DEEPSEEK_TOOLS[0]]
        stripped = service._strip_strict_tools(sample)
        self.assertNotIn("strict", stripped[0]["function"])
        self.assertEqual(stripped[0]["function"]["name"], sample[0]["function"]["name"])
        anthropic = service._anthropic_tools(sample)
        self.assertIn("input_schema", anthropic[0])
        gemini = service._gemini_tools(sample)
        self.assertIn("functionDeclarations", gemini[0])
        self.assertIn("name", gemini[0]["functionDeclarations"][0])

    def test_unconfigured_provider_still_requires_api_key(self) -> None:
        service = _make_service("glm")
        service.api_keys = {}
        result = service.chat("你好", [], mode="advanced")
        self.assertFalse(result["configured"])
        self.assertIn("API Key", result["message"])

    def test_openai_responses_request_uses_user_limit_and_shared_timeout(self) -> None:
        service = _make_service("openai", "gpt-test")
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b'{"output": [], "usage": {}}'
        lease = MagicMock()
        with (
            patch.dict(os.environ, {
                "XLINE_AGENT_MODEL_REQUEST_TIMEOUT_SECONDS": "12",
            }),
            patch("app.model_request_gateway.user_request_limiter.acquire", return_value=lease) as acquire,
            patch("app.model_request_gateway.urllib.request.urlopen", return_value=response) as urlopen,
        ):
            service._request([], "system", mode="advanced")

        acquire.assert_called_once()
        self.assertEqual(12.0, urlopen.call_args.kwargs["timeout"])
        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual("https://api.openai.com/v1/responses", request.full_url)
        self.assertEqual("gpt-test", payload["model"])
        self.assertIn("tools", payload)
        self.assertNotIn("test-key", request.full_url)
        lease.__enter__.assert_called_once()
        lease.__exit__.assert_called_once()

    def test_compatible_chat_uses_adapter_and_user_timeout(self) -> None:
        service = _make_service("qwen", "qwen-test")
        with (
            patch.dict(
                os.environ,
                {"XLINE_AGENT_MODEL_REQUEST_TIMEOUT_SECONDS": "17"},
            ),
            patch.object(service, "_system_context", return_value="system"),
            patch(
                "app.model_providers.urllib.request.urlopen",
                return_value=_http_json_response(_plain_response("普通回复")),
            ) as urlopen,
        ):
            result = service._compatible_chat("你好", [], mode="base")
        self.assertEqual("普通回复", result["message"])
        self.assertEqual(17.0, urlopen.call_args.kwargs["timeout"])

    def test_openai_diagnostic_request_uses_user_timeout(self) -> None:
        service = _make_service("openai", "gpt-test")
        with (
            patch.dict(
                os.environ,
                {"XLINE_AGENT_MODEL_REQUEST_TIMEOUT_SECONDS": "18"},
            ),
            patch.object(service, "_system_context", return_value="system"),
            patch(
                "app.model_request_gateway.urllib.request.urlopen",
                return_value=_http_json_response(
                    {"output": [{"type": "message", "content": [{"type": "output_text", "text": "诊断完成"}]}]}
                ),
            ) as urlopen,
        ):
            result = service.analyze_diagnostic_snapshot({"mission_stage": "idle"})
        self.assertEqual("诊断完成", result["message"])
        self.assertEqual(18.0, urlopen.call_args.kwargs["timeout"])


class ReviewGeneralizationTest(unittest.TestCase):
    """Intent routing review and CAD edit interpretation must run for every
    configured cloud provider, not just DeepSeek.  Local mode stays rule-only."""

    def test_structured_review_text_dispatches_openai_compatible(self) -> None:
        for provider in ("qwen", "kimi", "glm", "minimax"):
            with self.subTest(provider=provider):
                service = _make_service(provider)
                with patch.object(
                    service,
                    "_openai_compatible_request",
                    return_value=_plain_response('{"primary_intent": "stop"}'),
                ) as request:
                    text = service._structured_review_text(
                        [
                            {"role": "system", "content": "严格输出 JSON"},
                            {"role": "user", "content": "快停车"},
                        ],
                        mode="base",
                    )
                request.assert_called_once()
                self.assertEqual(text, '{"primary_intent": "stop"}')

    def test_structured_review_text_dispatches_deepseek(self) -> None:
        service = _make_service("deepseek")
        with patch.object(
            service,
            "_deepseek_request",
            return_value=_plain_response("deepseek-ok"),
        ) as request:
            text = service._structured_review_text(
                [{"role": "user", "content": "hi"}], mode="advanced"
            )
        request.assert_called_once()
        self.assertEqual(text, "deepseek-ok")

    def test_structured_review_text_dispatches_anthropic(self) -> None:
        service = _make_service("anthropic")
        response = {
            "content": [
                {"type": "text", "text": '{"primary_intent": "status_query"}'}
            ],
            "usage": {"input_tokens": 5, "output_tokens": 3},
        }
        with patch.object(
            service, "_anthropic_request", return_value=response
        ) as request:
            text = service._structured_review_text(
                [
                    {"role": "system", "content": "严格输出 JSON"},
                    {"role": "user", "content": "查状态"},
                ],
                mode="base",
            )
        request.assert_called_once()
        self.assertEqual(text, '{"primary_intent": "status_query"}')

    def test_structured_review_text_dispatches_gemini(self) -> None:
        service = _make_service("gemini")
        response = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": '{"primary_intent": "diagnosis"}'}]
                    }
                }
            ],
            "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 3},
        }
        with patch.object(
            service, "_gemini_request", return_value=response
        ) as request:
            text = service._structured_review_text(
                [{"role": "user", "content": "诊断"}], mode="advanced"
            )
        request.assert_called_once()
        self.assertEqual(text, '{"primary_intent": "diagnosis"}')

    def test_gemini_structured_retry_preserves_assistant_role(self) -> None:
        service = _make_service("gemini")
        response = {
            "candidates": [
                {"content": {"parts": [{"text": '{"primary_intent":"conversation"}'}]}}
            ]
        }
        messages = service._structured_review_retry_messages(
            [
                {"role": "system", "content": "严格输出 JSON"},
                {"role": "user", "content": "判断意图"},
            ],
            "无效输出",
            reason="JSON 无法解析",
        )
        with patch.object(
            service, "_gemini_request", return_value=response
        ) as request:
            service._structured_review_text(messages, mode="advanced")

        contents = request.call_args.args[1]["contents"]
        self.assertEqual(["user", "model", "user"], [item["role"] for item in contents])

    def test_structured_review_text_dispatches_openai_responses(self) -> None:
        service = _make_service("openai")
        payload = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": '{"primary_intent": "motion_control"}',
                        }
                    ],
                }
            ]
        }
        with patch(
            "app.model_request_gateway.urllib.request.urlopen",
            return_value=_http_json_response(payload),
        ):
            text = service._structured_review_text(
                [{"role": "user", "content": "前进"}], mode="base"
            )
        self.assertEqual(text, '{"primary_intent": "motion_control"}')

    def test_structured_review_uses_dedicated_token_budget(self) -> None:
        messages = [{"role": "user", "content": "复核意图"}]
        with patch.dict(
            os.environ, {"XLINE_AGENT_REVIEW_MAX_TOKENS": "333"}
        ):
            deepseek = _make_service("deepseek")
            with patch.object(
                deepseek,
                "_deepseek_request",
                return_value=_plain_response("{}"),
            ) as request:
                deepseek._structured_review_text(messages, mode="advanced")
            self.assertEqual(
                333, request.call_args.kwargs["max_tokens_override"]
            )

            anthropic = _make_service("anthropic")
            with patch.object(
                anthropic,
                "_anthropic_request",
                return_value={"content": [{"type": "text", "text": "{}"}]},
            ) as request:
                anthropic._structured_review_text(messages, mode="advanced")
            self.assertEqual(333, request.call_args.args[0]["max_tokens"])

            gemini = _make_service("gemini")
            with patch.object(
                gemini,
                "_gemini_request",
                return_value={
                    "candidates": [{"content": {"parts": [{"text": "{}"}]}}]
                },
            ) as request:
                gemini._structured_review_text(messages, mode="advanced")
            self.assertEqual(
                333,
                request.call_args.args[1]["generationConfig"]["maxOutputTokens"],
            )

            qwen = _make_service("qwen")
            with patch.object(
                qwen,
                "_openai_compatible_request",
                return_value=_plain_response("{}"),
            ) as request:
                qwen._structured_review_text(messages, mode="advanced")
            self.assertEqual(333, request.call_args.kwargs["max_tokens"])

            openai = _make_service("openai")
            response = {
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "{}"}],
                    }
                ]
            }
            with patch(
                "app.model_request_gateway.urllib.request.urlopen",
                return_value=_http_json_response(response),
            ) as urlopen:
                openai._structured_review_text(messages, mode="advanced")
            payload = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
            self.assertEqual(333, payload["max_output_tokens"])

    def test_structured_review_token_budget_is_bounded(self) -> None:
        cases = {
            "invalid": ("not-a-number", 700),
            "too-small": ("1", 128),
            "too-large": ("99999", 4096),
        }
        for label, (configured, expected) in cases.items():
            with self.subTest(case=label), patch.dict(
                os.environ, {"XLINE_AGENT_REVIEW_MAX_TOKENS": configured}
            ):
                self.assertEqual(
                    expected, RobotAgentService._structured_review_max_tokens()
                )

    def test_structured_review_text_raises_for_local_and_unconfigured(
        self,
    ) -> None:
        local = _make_service("local")
        with self.assertRaises(RuntimeError):
            local._structured_review_text(
                [{"role": "user", "content": "hi"}], mode="base"
            )
        unconfigured = _make_service("qwen")
        unconfigured.api_keys = {}
        with self.assertRaises(RuntimeError):
            unconfigured._structured_review_text(
                [{"role": "user", "content": "hi"}], mode="base"
            )

    def test_resolve_intent_review_runs_for_non_deepseek_provider(
        self,
    ) -> None:
        service = _make_service("qwen")
        review_json = json.dumps(
            {
                "primary_intent": "drawing_design",
                "cad_operation": "modify",
                "secondary_intents": [],
                "confidence": 0.9,
                "requires_clarification": False,
                "clarification_question": None,
                "reason": "复合 CAD 修改",
            },
            ensure_ascii=False,
        )
        with (
            patch.object(service, "_route_needs_model_review", return_value=True),
            patch.object(
                service, "_structured_review_text", return_value=review_json
            ) as review_call,
        ):
            route = service.resolve_intent(
                "请判断刚才那个方案接下来应该如何处理，并说明原因",
                "advanced",
                [],
            )
        review_call.assert_called_once()
        self.assertNotEqual(route["decision_source"], "rules_fallback")
        self.assertTrue(route["review"]["valid"])
        self.assertEqual(route["name"], "drawing_design")

    def test_route_review_retries_invalid_structure_once(self) -> None:
        service = _make_service("qwen")
        valid_review = json.dumps(
            {
                "primary_intent": "drawing_design",
                "cad_operation": "modify",
                "secondary_intents": [],
                "confidence": 0.92,
                "requires_clarification": False,
                "clarification_question": None,
                "reason": "修改当前图纸",
            },
            ensure_ascii=False,
        )
        with (
            patch.object(service, "_route_needs_model_review", return_value=True),
            patch.object(
                service,
                "_structured_review_text",
                side_effect=["不是 JSON", valid_review],
            ) as review_call,
        ):
            route = service.resolve_intent(
                "请判断这条复杂请求应该如何处理并说明原因",
                "advanced",
                [],
            )

        self.assertEqual(2, review_call.call_count)
        self.assertEqual("drawing_design", route["name"])
        self.assertEqual("modify", route["operation"])
        self.assertEqual(2, route["review"]["request_attempts"])

    def test_route_review_does_not_retry_provider_failure(self) -> None:
        service = _make_service("qwen")
        with (
            patch.object(service, "_route_needs_model_review", return_value=True),
            patch.object(
                service,
                "_structured_review_text",
                side_effect=RuntimeError("provider unavailable"),
            ) as review_call,
        ):
            route = service.resolve_intent(
                "请判断这条复杂请求应该如何处理并说明原因",
                "advanced",
                [],
            )

        review_call.assert_called_once()
        self.assertEqual("rules_fallback", route["decision_source"])
        self.assertEqual(1, route["review"]["request_attempts"])

    def test_rule_recognized_cad_modify_skips_generic_model_review(self) -> None:
        service = _make_service("qwen")
        with patch.object(service, "_structured_review_text") as review_call:
            route = service.resolve_intent(
                "请修改当前图纸的中心圆",
                "advanced",
                [],
            )

        review_call.assert_not_called()
        self.assertEqual("drawing_design", route["name"])
        self.assertEqual("modify", route["operation"])
        self.assertFalse(route["review_required"])
        self.assertEqual(
            "CAD 修改由严格结构化解释器复核",
            route["review"]["reason"],
        )

    def test_review_recovers_rule_missed_cad_modification(self) -> None:
        rule_route = {
            "name": "conversation",
            "tool_family": "conversation",
            "operation": "query",
            "stage": "conversation",
            "confidence": 0.6,
        }
        review = {
            "primary_intent": "drawing_design",
            "cad_operation": "modify",
            "secondary_intents": [],
            "confidence": 0.94,
            "requires_clarification": False,
            "clarification_question": None,
            "reason": "用户要求修改当前对象",
        }

        result = RobotAgentService._merge_route_review(rule_route, review)

        self.assertEqual("drawing_design", result["name"])
        self.assertEqual("modify", result["operation"])
        self.assertEqual("editing", result["stage"])
        self.assertEqual("model_review", result["decision_source"])

    def test_rule_missed_cad_review_without_operation_requires_clarification(self) -> None:
        rule_route = {
            "name": "conversation",
            "tool_family": "conversation",
            "operation": "query",
            "stage": "conversation",
            "confidence": 0.6,
        }
        review = {
            "primary_intent": "drawing_design",
            "secondary_intents": [],
            "confidence": 0.9,
            "requires_clarification": False,
            "clarification_question": None,
            "reason": "只判断出与 CAD 有关",
        }

        result = RobotAgentService._merge_route_review(rule_route, review)

        self.assertTrue(result["clarification_required"])
        self.assertEqual("conversation", result["name"])
        self.assertEqual("model_clarification", result["decision_source"])

    def test_resolve_intent_local_mode_stays_rules_fallback(self) -> None:
        service = _make_service("local")
        with (
            patch.object(service, "_route_needs_model_review", return_value=True),
            patch.object(service, "_structured_review_text") as review_call,
        ):
            route = service.resolve_intent(
                "把右边的篮球场整体放大到 30 米宽并保持中线不变",
                "advanced",
                [],
            )
        review_call.assert_not_called()
        self.assertEqual(route["decision_source"], "rules_fallback")

    def test_cad_edit_fallback_runs_for_non_deepseek_provider(self) -> None:
        service = _make_service("anthropic")
        route = {
            "name": "drawing_design",
            "tool_family": "cad",
            "operation": "modify",
            "confidence": 0.9,
            "decision_source": "rules",
        }
        intent = {
            "schema_version": "cad.language-interpretation.v1",
            "is_cad_edit": True,
            "operation": "resize",
            "target": {"scope": "instance", "instance_ids": [1]},
            "parameters": {"dimension": "width", "value_mm": 30000},
            "assumptions": [],
            "constraints": [],
            "evidence_text": ["第1个篮球场", "宽度改为30米"],
            "confidence": 0.9,
        }
        with patch.object(
            service,
            "_structured_review_text",
            return_value=json.dumps(intent, ensure_ascii=False),
        ) as review_call:
            result = service._structured_cad_edit_fallback(
                "把第1个篮球场宽度改为30米",
                [],
                route,
                "advanced",
            )
        review_call.assert_called_once()
        self.assertEqual(result["edit_parser"], "model_structured_fallback")
        self.assertEqual(result["decision_source"], "incremental_cad_edit")
        self.assertFalse(result["clarification_required"])
        self.assertEqual(result["resolved_edit"]["instance"], 1)
        self.assertEqual(result["resolved_edit"]["value_mm"], 30000.0)

    def test_all_cloud_providers_reach_real_cad_parser(self) -> None:
        message = "把第1个篮球场宽度改为30米"
        route = {
            "name": "drawing_design",
            "tool_family": "cad",
            "operation": "modify",
            "confidence": 0.9,
            "decision_source": "rules",
        }
        text = _structured_resize_json()

        for provider in (
            "deepseek", "openai", "anthropic", "gemini",
            "qwen", "kimi", "glm", "minimax",
        ):
            with self.subTest(provider=provider), ExitStack() as stack:
                service = _make_service(provider)
                if provider == "deepseek":
                    stack.enter_context(
                        patch.object(
                            service,
                            "_deepseek_request",
                            return_value=_plain_response(text),
                        )
                    )
                elif provider == "openai":
                    stack.enter_context(
                        patch(
                            "app.model_request_gateway.urllib.request.urlopen",
                            return_value=_http_json_response(
                                {
                                    "output": [
                                        {
                                            "type": "message",
                                            "content": [
                                                {"type": "output_text", "text": text}
                                            ],
                                        }
                                    ]
                                }
                            ),
                        )
                    )
                elif provider == "anthropic":
                    stack.enter_context(
                        patch.object(
                            service,
                            "_anthropic_request",
                            return_value={
                                "content": [{"type": "text", "text": text}]
                            },
                        )
                    )
                elif provider == "gemini":
                    stack.enter_context(
                        patch.object(
                            service,
                            "_gemini_request",
                            return_value={
                                "candidates": [
                                    {"content": {"parts": [{"text": text}]}}
                                ]
                            },
                        )
                    )
                else:
                    stack.enter_context(
                        patch.object(
                            service,
                            "_openai_compatible_request",
                            return_value=_plain_response(text),
                        )
                    )

                result = service._structured_cad_edit_fallback(
                    message, [], route, "advanced"
                )

                self.assertEqual("incremental_cad_edit", result["decision_source"])
                self.assertEqual(1, result["resolved_edit"]["instance"])
                self.assertEqual(30000.0, result["resolved_edit"]["value_mm"])
                self.assertTrue(result["edit_intent"]["grounding"]["verified"])

    def test_cad_interpretation_retries_invalid_schema_once(self) -> None:
        service = _make_service("qwen")
        route = {
            "name": "drawing_design",
            "tool_family": "cad",
            "operation": "modify",
            "confidence": 0.9,
            "decision_source": "rules",
        }
        with patch.object(
            service,
            "_structured_review_text",
            side_effect=['{"operation":"resize"}', _structured_resize_json()],
        ) as review_call:
            result = service._structured_cad_edit_fallback(
                "把第1个篮球场宽度改为30米", [], route, "advanced"
            )

        self.assertEqual(2, review_call.call_count)
        self.assertEqual("incremental_cad_edit", result["decision_source"])
        self.assertTrue(result["cad_interpretation"]["executable"])
        self.assertEqual(2, result["cad_interpretation"]["request_attempts"])

    def test_cad_interpretation_does_not_retry_provider_failure(self) -> None:
        service = _make_service("qwen")
        route = {
            "name": "drawing_design",
            "tool_family": "cad",
            "operation": "modify",
            "confidence": 0.9,
            "decision_source": "rules",
        }
        with patch.object(
            service,
            "_structured_review_text",
            side_effect=RuntimeError("provider unavailable"),
        ) as review_call:
            result = service._structured_cad_edit_fallback(
                "把第1个篮球场宽度改为30米", [], route, "advanced"
            )

        review_call.assert_called_once()
        self.assertFalse(result["cad_interpretation"]["executable"])
        self.assertEqual("provider_request_failed", result["cad_interpretation"]["reason"])
        self.assertEqual(1, result["cad_interpretation"]["request_attempts"])

    def test_invalid_cad_model_outputs_downgrade_without_execution(self) -> None:
        route = {
            "name": "drawing_design",
            "tool_family": "cad",
            "operation": "modify",
            "confidence": 0.9,
            "decision_source": "rules",
        }
        cases = {
            "empty": ("", "invalid_json"),
            "not_json": ("我认为应该修改第一个篮球场", "invalid_json"),
            "invalid_schema": (
                json.dumps(
                    {
                        "schema_version": "cad.language-interpretation.v1",
                        "is_cad_edit": True,
                        "operation": "resize",
                        "target": {"scope": "instance", "instance_id": 1},
                        "parameters": {"width": 30000},
                        "evidence_text": "宽度改为30米",
                        "confidence": 0.99,
                    },
                    ensure_ascii=False,
                ),
                "invalid_schema_or_grounding",
            ),
        }

        for label, (model_text, expected_reason) in cases.items():
            with self.subTest(case=label):
                service = _make_service("qwen")
                with patch.object(
                    service, "_structured_review_text", return_value=model_text
                ):
                    result = service._structured_cad_edit_fallback(
                        "把第1个篮球场宽度改为30米",
                        [],
                        route,
                        "advanced",
                    )

                self.assertEqual("modify", result["operation"])
                self.assertNotIn("resolved_edit", result)
                self.assertFalse(result["cad_interpretation"]["valid"])
                self.assertEqual(
                    expected_reason, result["cad_interpretation"]["reason"]
                )

    def test_cad_edit_fallback_local_mode_returns_route(self) -> None:
        service = _make_service("local")
        route = {
            "name": "drawing_design",
            "tool_family": "cad",
            "operation": "modify",
            "confidence": 0.9,
            "decision_source": "rules",
        }
        with patch.object(service, "_structured_review_text") as review_call:
            result = service._structured_cad_edit_fallback(
                "把右边的篮球场放大", [], route, "advanced"
            )
        review_call.assert_not_called()
        self.assertEqual(result, route)


if __name__ == "__main__":
    unittest.main()
