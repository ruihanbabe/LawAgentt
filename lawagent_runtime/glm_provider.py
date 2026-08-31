"""GLM OpenAI 兼容 Provider Adapter 与免费模型 Profile 装配。"""

from __future__ import annotations

import json
import os
from time import monotonic, sleep
from typing import Any, Protocol

import httpx

from .model_provider import (
    ModelGateway,
    ModelProfile,
    ModelProfileConfig,
    ProviderRequest,
    ProviderResponse,
)
from .env import load_project_env


GLM_PROVIDER_NAME = "glm"
GLM_DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
GLM_DEFAULT_FREE_MODEL = "glm-4.7-flash"


class _ChatCompletions(Protocol):
    def create(self, **kwargs: Any) -> Any: ...


class _Chat(Protocol):
    completions: _ChatCompletions


class _OpenAICompatibleClient(Protocol):
    chat: _Chat


class GLMProvider:
    """只负责 SDK 边界转换；密钥不进入请求 DTO、Trace 或异常文本。"""

    provider_name = GLM_PROVIDER_NAME

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        client: _OpenAICompatibleClient | None = None,
    ) -> None:
        resolved_key = api_key or os.getenv("GLM_API_KEY") or os.getenv("ZAI_API_KEY")
        if client is None and not resolved_key:
            raise ValueError("GLM_API_KEY is not configured")
        self.base_url = base_url or os.getenv("GLM_BASE_URL") or GLM_DEFAULT_BASE_URL
        self.min_call_interval_seconds = max(
            0.0,
            float(os.getenv("GLM_MIN_CALL_INTERVAL_SECONDS", "0") or 0),
        )
        self._last_call_started_at: float | None = None
        if client is None:
            from openai import OpenAI

            https_proxy = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")
            http_client = (
                httpx.Client(proxy=https_proxy, trust_env=False)
                if https_proxy
                else httpx.Client(trust_env=False)
            )
            client = OpenAI(
                api_key=resolved_key,
                base_url=self.base_url,
                http_client=http_client,
            )
        self._client = client

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        if self._last_call_started_at is not None and self.min_call_interval_seconds:
            remaining = self.min_call_interval_seconds - (monotonic() - self._last_call_started_at)
            if remaining > 0:
                sleep(remaining)
        self._last_call_started_at = monotonic()
        messages: list[dict[str, Any]] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        user_content = request.user_prompt
        if request.context:
            user_content += "\n\n<context_json>\n" + json.dumps(
                request.context,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ) + "\n</context_json>"
        messages.append({"role": "user", "content": user_content})
        kwargs: dict[str, Any] = {
            "model": request.model,
            "messages": messages,
            "max_tokens": request.max_output_tokens,
            "temperature": request.temperature,
            "timeout": request.timeout_ms / 1_000,
        }
        if request.response_schema is not None:
            kwargs["response_format"] = {"type": "json_object"}
        raw = self._client.chat.completions.create(**kwargs)
        choice = raw.choices[0]
        text = choice.message.content or ""
        structured_output = None
        if request.response_schema is not None:
            parsed = json.loads(text)
            if not isinstance(parsed, dict):
                raise ValueError("structured GLM response must be a JSON object")
            structured_output = parsed
        usage = getattr(raw, "usage", None)
        return ProviderResponse(
            text=text,
            structured_output=structured_output,
            input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            finish_reason=str(getattr(choice, "finish_reason", "stop") or "stop"),
        )


def build_glm_profile_configs(*, model: str | None = None) -> list[ModelProfileConfig]:
    selected_model = model or os.getenv("GLM_MODEL") or GLM_DEFAULT_FREE_MODEL
    output_caps = {
        ModelProfile.SAFETY_FAST: 512,
        ModelProfile.UNDERSTANDING_STRUCTURED: 1_024,
        ModelProfile.RETRIEVAL_PLANNER: 1_024,
        ModelProfile.LEGAL_ANALYSIS: 2_048,
        ModelProfile.RESPONSE_GENERATION: 2_048,
        ModelProfile.INDEPENDENT_REVIEW: 1_024,
    }
    return [
        ModelProfileConfig(
            profile=profile,
            provider=GLM_PROVIDER_NAME,
            model=selected_model,
            max_output_tokens=max_output_tokens,
            timeout_ms=60_000,
            input_cost_per_million=0.0,
            output_cost_per_million=0.0,
        )
        for profile, max_output_tokens in output_caps.items()
    ]


def build_glm_gateway_from_env(*, model: str | None = None) -> ModelGateway:
    load_project_env()
    return ModelGateway(
        providers=[GLMProvider()],
        profiles=build_glm_profile_configs(model=model),
    )
