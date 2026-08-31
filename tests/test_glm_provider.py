from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from lawagent_runtime.glm_provider import (
    GLM_DEFAULT_FREE_MODEL,
    GLMProvider,
    build_glm_profile_configs,
)
from lawagent_runtime.model_provider import ModelProfile, ProviderRequest


class FakeCompletions:
    def __init__(self, content='{"ok":true}'):
        self.content = content
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content=self.content),
                finish_reason="stop",
            )],
            usage=SimpleNamespace(prompt_tokens=12, completion_tokens=4),
        )


class GLMProviderTests(unittest.TestCase):
    def request(self, *, structured=True):
        return ProviderRequest(
            request_id="request-1",
            model=GLM_DEFAULT_FREE_MODEL,
            system_prompt="只返回 JSON",
            user_prompt="分析",
            context={"safe": "context"},
            response_schema={"type": "object"} if structured else None,
            max_output_tokens=128,
            temperature=0.0,
            timeout_ms=3_000,
        )

    def test_adapter_uses_openai_compatible_contract_and_parses_json(self):
        completions = FakeCompletions()
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        response = GLMProvider(client=client).generate(self.request())

        self.assertEqual(response.structured_output, {"ok": True})
        self.assertEqual(response.input_tokens, 12)
        call = completions.calls[0]
        self.assertEqual(call["model"], GLM_DEFAULT_FREE_MODEL)
        self.assertEqual(call["response_format"], {"type": "json_object"})
        self.assertEqual(call["timeout"], 3.0)
        context_block = call["messages"][-1]["content"].split("<context_json>\n", 1)[1].split("\n</context_json>", 1)[0]
        self.assertEqual(json.loads(context_block), {"safe": "context"})

    def test_missing_key_fails_without_leaking_secret_details(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(ValueError, "GLM_API_KEY is not configured"):
                GLMProvider()

    def test_real_client_does_not_inherit_host_proxy_environment(self):
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("openai.OpenAI") as openai_client,
            patch("httpx.Client") as http_client,
        ):
            GLMProvider(api_key="test-key")
        http_client.assert_called_once_with(trust_env=False)
        self.assertIs(openai_client.call_args.kwargs["http_client"], http_client.return_value)

    def test_real_client_uses_https_proxy_without_inheriting_socks_all_proxy(self):
        with (
            patch.dict("os.environ", {
                "HTTPS_PROXY": "http://proxy.example:8080",
                "ALL_PROXY": "socks5://socks.example:1080",
            }, clear=True),
            patch("openai.OpenAI") as openai_client,
            patch("httpx.Client") as http_client,
        ):
            GLMProvider(api_key="test-key")
        http_client.assert_called_once_with(proxy="http://proxy.example:8080", trust_env=False)
        self.assertIs(openai_client.call_args.kwargs["http_client"], http_client.return_value)

    def test_all_six_profiles_use_configurable_free_model(self):
        configs = build_glm_profile_configs(model="glm-free-test")
        self.assertEqual({item.profile for item in configs}, set(ModelProfile))
        self.assertEqual({item.model for item in configs}, {"glm-free-test"})
        self.assertEqual({item.provider for item in configs}, {"glm"})
        self.assertEqual({item.input_cost_per_million for item in configs}, {0.0})

    def test_minimum_call_interval_throttles_repeated_calls(self):
        completions = FakeCompletions()
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        with (
            patch.dict("os.environ", {"GLM_MIN_CALL_INTERVAL_SECONDS": "5"}, clear=True),
            patch("lawagent_runtime.glm_provider.monotonic", side_effect=[10.0, 11.0, 15.0]),
            patch("lawagent_runtime.glm_provider.sleep") as sleeper,
        ):
            provider = GLMProvider(client=client)
            provider.generate(self.request())
            provider.generate(self.request())
        sleeper.assert_called_once_with(4.0)


if __name__ == "__main__":
    unittest.main()
