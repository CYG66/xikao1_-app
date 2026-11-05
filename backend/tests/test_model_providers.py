from __future__ import annotations

import json
import unittest

from app.model_providers import provider_adapter


class ModelProviderAdapterTest(unittest.TestCase):
    def test_openai_compatible_request_and_usage_are_normalized(self) -> None:
        adapter = provider_adapter("qwen")
        request = adapter.build_request(
            base_url="https://example.test/v1",
            model="qwen-test",
            api_key="secret",
            system="system",
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=100,
        )
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual("qwen-test", payload["model"])
        self.assertEqual("system", payload["messages"][0]["content"])
        self.assertEqual("Bearer secret", request.headers["Authorization"])
        reply = adapter.parse_reply({
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2},
        })
        self.assertEqual("ok", reply.text)
        self.assertEqual(5, reply.usage["total_tokens"])

    def test_anthropic_and_gemini_keep_native_payload_shapes(self) -> None:
        anthropic = provider_adapter("anthropic")
        request = anthropic.build_request(
            base_url="https://example.test",
            model="claude-test",
            api_key="secret",
            system="system",
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=100,
        )
        self.assertEqual("/messages", request.selector)
        self.assertEqual("system", json.loads(request.data)["system"])

        gemini = provider_adapter("gemini")
        request = gemini.build_request(
            base_url="https://example.test",
            model="gemini-test",
            api_key="secret",
            system="system",
            messages=[{"role": "assistant", "content": "hello"}],
            max_tokens=100,
        )
        payload = json.loads(request.data)
        self.assertEqual("model", payload["contents"][0]["role"])
        self.assertEqual("system", payload["systemInstruction"]["parts"][0]["text"])
        self.assertNotIn("secret", request.full_url)
        self.assertEqual("secret", request.headers["X-goog-api-key"])


if __name__ == "__main__":
    unittest.main()
