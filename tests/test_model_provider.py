from __future__ import annotations

import unittest

from runtime.model_provider import (
    ModelBudget,
    ModelErrorCode,
    ModelGateway,
    ModelProfile,
    ModelProfileConfig,
    ModelRequest,
    ModelUsage,
    ProviderResponse,
)
from runtime.taskboard import AgentRunBoard, AgentRunTrace


class FakeProvider:
    def __init__(self, provider_name: str, *, input_tokens: int = 100, output_tokens: int = 20):
        self.provider_name = provider_name
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        return ProviderResponse(
            text=f"{self.provider_name}:{request.model}",
            structured_output={"ok": True},
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
        )


class RateLimitError(Exception):
    pass


class RaisingProvider:
    provider_name = "raising"

    def generate(self, request):
        raise RateLimitError("raw upstream details must not escape")


def request(profile: ModelProfile, *, max_output_tokens: int | None = None) -> ModelRequest:
    return ModelRequest(
        run_id="run-1",
        task_id="task-1",
        agent_id="agent-1",
        profile=profile,
        user_prompt="测试",
        requested_max_output_tokens=max_output_tokens,
    )


class ModelGatewayTests(unittest.TestCase):
    def test_rate_limit_is_classified_without_raw_error_details(self):
        gateway = ModelGateway(
            providers=[RaisingProvider()],
            profiles=[ModelProfileConfig(
                profile=ModelProfile.SAFETY_FAST,
                provider="raising",
                model="limited",
                max_output_tokens=64,
            )],
        )
        result = gateway.generate(
            request(ModelProfile.SAFETY_FAST),
            budget=ModelBudget(),
            usage=ModelUsage(),
        )
        self.assertEqual(result.error.code, ModelErrorCode.RATE_LIMITED)
        self.assertEqual(result.error.message, "provider call failed: RateLimitError")
    def test_profiles_route_to_different_providers_and_models(self):
        cheap = FakeProvider("cheap")
        strong = FakeProvider("strong")
        gateway = ModelGateway(
            providers=[cheap, strong],
            profiles=[
                ModelProfileConfig(
                    profile=ModelProfile.SAFETY_FAST,
                    provider="cheap",
                    model="fast-model",
                    max_output_tokens=128,
                ),
                ModelProfileConfig(
                    profile=ModelProfile.LEGAL_ANALYSIS,
                    provider="strong",
                    model="reasoning-model",
                    max_output_tokens=1024,
                ),
            ],
        )
        usage = ModelUsage()
        budget = ModelBudget()

        first = gateway.generate(request(ModelProfile.SAFETY_FAST), budget=budget, usage=usage)
        second = gateway.generate(request(ModelProfile.LEGAL_ANALYSIS), budget=budget, usage=usage)

        self.assertEqual(first.response.model, "fast-model")
        self.assertEqual(second.response.model, "reasoning-model")
        self.assertEqual(len(cheap.requests), 1)
        self.assertEqual(len(strong.requests), 1)
        self.assertEqual(usage.call_count, 2)

    def test_profile_output_cap_overrides_agent_request(self):
        provider = FakeProvider("cheap")
        gateway = ModelGateway(
            providers=[provider],
            profiles=[ModelProfileConfig(
                profile=ModelProfile.RESPONSE_GENERATION,
                provider="cheap",
                model="writer",
                max_output_tokens=256,
            )],
        )

        gateway.generate(
            request(ModelProfile.RESPONSE_GENERATION, max_output_tokens=10_000),
            budget=ModelBudget(),
            usage=ModelUsage(),
        )

        self.assertEqual(provider.requests[0].max_output_tokens, 256)

    def test_exhausted_call_budget_blocks_provider(self):
        provider = FakeProvider("cheap")
        gateway = ModelGateway(
            providers=[provider],
            profiles=[ModelProfileConfig(
                profile=ModelProfile.SAFETY_FAST,
                provider="cheap",
                model="fast",
                max_output_tokens=64,
            )],
        )
        usage = ModelUsage(call_count=1)

        result = gateway.generate(
            request(ModelProfile.SAFETY_FAST),
            budget=ModelBudget(max_calls=1),
            usage=usage,
        )

        self.assertEqual(result.error.code, ModelErrorCode.BUDGET_EXHAUSTED)
        self.assertEqual(provider.requests, [])
        self.assertEqual(usage.call_count, 1)

    def test_cost_is_calculated_and_run_trace_keeps_usage(self):
        provider = FakeProvider("metered", input_tokens=1_000, output_tokens=500)
        gateway = ModelGateway(
            providers=[provider],
            profiles=[ModelProfileConfig(
                profile=ModelProfile.INDEPENDENT_REVIEW,
                provider="metered",
                model="reviewer",
                max_output_tokens=500,
                input_cost_per_million=1.0,
                output_cost_per_million=2.0,
            )],
        )
        board = AgentRunBoard(sanitized_input="测试")

        result = gateway.generate(
            request(ModelProfile.INDEPENDENT_REVIEW),
            budget=board.model_budget,
            usage=board.model_usage,
        )
        trace = AgentRunTrace.from_board(board)

        self.assertEqual(result.response.cost_usd, 0.002)
        self.assertEqual(trace.model_usage.call_count, 1)
        self.assertEqual(trace.model_usage.input_tokens, 1_000)
        self.assertEqual(trace.model_usage.output_tokens, 500)
        self.assertEqual(trace.model_usage.cost_usd, 0.002)

    def test_unconfigured_profile_fails_without_provider_call(self):
        provider = FakeProvider("cheap")
        gateway = ModelGateway(providers=[provider], profiles=[])

        result = gateway.generate(
            request(ModelProfile.LEGAL_ANALYSIS),
            budget=ModelBudget(),
            usage=ModelUsage(),
        )

        self.assertEqual(result.error.code, ModelErrorCode.PROFILE_NOT_CONFIGURED)
        self.assertEqual(provider.requests, [])

    def test_post_call_budget_rejection_still_records_real_cost(self):
        provider = FakeProvider("expensive", input_tokens=2_000, output_tokens=100)
        gateway = ModelGateway(
            providers=[provider],
            profiles=[ModelProfileConfig(
                profile=ModelProfile.LEGAL_ANALYSIS,
                provider="expensive",
                model="reasoner",
                max_output_tokens=100,
                input_cost_per_million=10.0,
                output_cost_per_million=10.0,
            )],
        )
        usage = ModelUsage()

        result = gateway.generate(
            request(ModelProfile.LEGAL_ANALYSIS),
            budget=ModelBudget(max_cost_usd=0.001),
            usage=usage,
        )

        self.assertEqual(result.error.code, ModelErrorCode.BUDGET_EXHAUSTED)
        self.assertEqual(usage.call_count, 1)
        self.assertEqual(usage.input_tokens, 2_000)
        self.assertGreater(usage.cost_usd, 0.001)


if __name__ == "__main__":
    unittest.main()
