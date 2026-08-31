from __future__ import annotations

import unittest
from unittest.mock import patch

from api.sse import build_configured_harness
from lawagent_runtime.model_provider import ModelProfile
from lawagent_runtime.taskboard import AgentRunBoard, EventType
from scripts.smoke_glm_six_roles import quality_matrix


class GlmSmokeMatrixTests(unittest.TestCase):
    def test_quality_matrix_requires_every_profile(self):
        board = AgentRunBoard(sanitized_input="test")
        for profile in ModelProfile:
            board.append_event(
                EventType.MODEL_CALLED,
                actor_type="model_gateway",
                actor_id="glm",
                payload={
                    "profile": profile.value,
                    "model": "glm-test",
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "latency_ms": 20,
                },
            )
        report = quality_matrix(board)
        self.assertTrue(report["all_six_called"])
        self.assertEqual(set(report["profiles"]), {item.value for item in ModelProfile})

    def test_configured_harness_injects_glm_gateway_when_enabled(self):
        sentinel = object()
        with (
            patch.dict("os.environ", {"LAWAGENT_GLM_ENABLED": "true", "LAWAGENT_RAG_ENABLED": "false"}),
            patch("api.sse.build_glm_gateway_from_env", return_value=sentinel) as builder,
            patch("api.sse.build_default_harness", return_value="harness") as build_harness,
        ):
            self.assertEqual(build_configured_harness(), "harness")
        builder.assert_called_once_with()
        build_harness.assert_called_once_with(model_gateway=sentinel)


if __name__ == "__main__":
    unittest.main()
