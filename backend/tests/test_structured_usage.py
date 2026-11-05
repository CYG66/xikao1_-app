from contextvars import Context
import io
import json
import pytest
from unittest.mock import patch, PropertyMock

from app.agent_service import RobotAgentService
from app.structured_usage import structured_usage_scope, record_structured_usage, merge_structured_usage, usage_scoped_events


def record(n):
    record_structured_usage({"usage": {"prompt_tokens": n, "completion_tokens": 2}}, "deepseek")


def test_accumulates_retries_without_double_counting_enrichment():
    with structured_usage_scope():
        record(10); record(20)
        result = {"usage": {"input_tokens": 5, "output_tokens": 1, "total_tokens": 6}}
        merge_structured_usage(result)
        merge_structured_usage(result)
        assert result["usage"] == {"input_tokens": 35, "output_tokens": 5, "total_tokens": 40}
        assert result["structured_usage"]["calls"] == 2


def test_missing_provider_usage_is_marked_incomplete():
    with structured_usage_scope():
        record_structured_usage({}, "deepseek")
        result = {}; merge_structured_usage(result)
        assert not result["structured_usage"]["complete"]
        assert result["structured_usage"]["missing_usage_calls"] == 1


@pytest.mark.parametrize("provider,response", [
    ("openai", {"usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}}),
    ("anthropic", {"usage": {"input_tokens": 10, "output_tokens": 2}}),
    ("gemini", {"usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 2, "totalTokenCount": 12}}),
])
def test_vendor_usage_field_normalization(provider, response):
    with structured_usage_scope():
        record_structured_usage(response, provider)
        result = {}; merge_structured_usage(result)
    assert result["usage"]["total_tokens"] == 12
    assert result["structured_usage"]["complete"]


def test_nested_requests_do_not_share_totals():
    with structured_usage_scope():
        record(10)
        with structured_usage_scope():
            record(50)
            inner = {}; merge_structured_usage(inner)
        outer = {}; merge_structured_usage(outer)
    assert inner["usage"]["input_tokens"] == 50
    assert outer["usage"]["input_tokens"] == 10
    outside = {}; merge_structured_usage(outside)
    assert outside == {}


def test_stream_rebinds_ledger_across_worker_contexts_and_interleaved_requests():
    def events(n):
        record(n)
        yield "context"
        record(n)
        result = {}; merge_structured_usage(result)
        yield result
    a, b = usage_scoped_events(events(10)), usage_scoped_events(events(100))
    assert Context().run(next, a) == "context"
    assert Context().run(next, b) == "context"
    assert Context().run(next, a)["usage"]["input_tokens"] == 20
    assert Context().run(next, b)["usage"]["input_tokens"] == 200


def test_deepseek_usage_only_terminal_chunk_is_preserved():
    chunks = [{"choices": [{"delta": {"content": "{}"}, "finish_reason": "stop"}]},
              {"choices": [], "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}}]
    response = io.BytesIO(("".join("data: "+json.dumps(c)+"\n\n" for c in chunks)+"data: [DONE]\n\n").encode())
    response.status = 200
    service = RobotAgentService(restore_pending_actions=False)
    with patch.object(service, "_deepseek_response", return_value=(None, response)) as request:
        result = service._deepseek_request([], tools=[], stream_structured=True, json_output=True)
    assert request.call_args.args[0]["stream_options"] == {"include_usage": True}
    assert result["usage"]["total_tokens"] == 18


def test_structured_reasoning_retry_counts_both_provider_responses():
    service = RobotAgentService(restore_pending_actions=False)
    service.mode = "deepseek"
    responses = [{"choices": [{"finish_reason": "length"}], "usage": {"prompt_tokens": 10, "completion_tokens": 20}},
                 {"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}], "usage": {"prompt_tokens": 30, "completion_tokens": 40}}]
    with structured_usage_scope(), patch.object(RobotAgentService, "configured", new_callable=PropertyMock, return_value=True), patch.object(service, "_model_for_agent_mode", return_value="deepseek-reasoner"), patch.object(service, "_deepseek_request", side_effect=responses), patch("app.agent_service.agent_audit.append"):
        assert service._structured_review_text([], mode="advanced") == "{}"
        result = {}; merge_structured_usage(result)
    assert result["usage"]["total_tokens"] == 100
    assert result["structured_usage"]["calls"] == 2


def test_successful_truncation_fallback_is_reused_only_within_same_request():
    service = RobotAgentService(restore_pending_actions=False)
    service.mode = "deepseek"
    stop = {"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2}}
    truncated = {"choices": [{"finish_reason": "length"}], "usage": {"prompt_tokens": 10, "completion_tokens": 20}}
    with patch.object(RobotAgentService, "configured", new_callable=PropertyMock, return_value=True), patch.object(service, "_model_for_agent_mode", return_value="deepseek-reasoner"), patch.object(service, "_deepseek_request", side_effect=[truncated, stop, stop, stop]) as provider, patch("app.agent_service.agent_audit.append"):
        with structured_usage_scope():
            service._structured_review_text([], mode="advanced")
            service._structured_review_text([], mode="advanced", max_tokens_override=16384)
            result = {}; merge_structured_usage(result)
        assert result["structured_usage"]["calls"] == 3
        assert provider.call_args_list[2].kwargs["model_override"] == "deepseek-chat"
        assert provider.call_args_list[2].kwargs["stream_structured"] is False
        assert provider.call_args_list[2].kwargs["max_tokens_override"] == 8192
        with structured_usage_scope():
            service._structured_review_text([], mode="advanced")
        assert "model_override" not in provider.call_args_list[3].kwargs
        assert provider.call_args_list[3].kwargs["stream_structured"] is True


def test_unsuccessful_fallback_does_not_change_later_model_selection():
    from app.structured_usage import structured_model_fallback
    service = RobotAgentService(restore_pending_actions=False); service.mode = "deepseek"
    truncated = {"choices": [{"finish_reason": "length"}]}
    with structured_usage_scope(), patch.object(RobotAgentService, "configured", new_callable=PropertyMock, return_value=True), patch.object(service, "_model_for_agent_mode", return_value="deepseek-reasoner"), patch.object(service, "_deepseek_request", side_effect=[truncated, truncated]), patch("app.agent_service.agent_audit.append"):
        with pytest.raises(RuntimeError):
            service._structured_review_text([], mode="advanced")
        assert structured_model_fallback("deepseek", "deepseek-reasoner") is None
