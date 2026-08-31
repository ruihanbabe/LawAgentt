"""模型 Provider、Profile 路由与 Run 级成本治理契约。"""

from __future__ import annotations

from enum import StrEnum
from time import perf_counter
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .state import new_id


class ModelProfile(StrEnum):
    SAFETY_FAST = "safety_fast"
    UNDERSTANDING_STRUCTURED = "understanding_structured"
    RETRIEVAL_PLANNER = "retrieval_planner"
    LEGAL_ANALYSIS = "legal_analysis"
    RESPONSE_GENERATION = "response_generation"
    INDEPENDENT_REVIEW = "independent_review"


class ModelErrorCode(StrEnum):
    PROFILE_NOT_CONFIGURED = "profile_not_configured"
    PROVIDER_NOT_CONFIGURED = "provider_not_configured"
    BUDGET_EXHAUSTED = "budget_exhausted"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    INVALID_RESPONSE = "invalid_response"
    CONTEXT_LIMIT = "context_limit"
    POLICY_BLOCKED = "policy_blocked"
    CANCELLED = "cancelled"


class ModelBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_calls: int = Field(default=12, ge=0)
    max_input_tokens: int = Field(default=60_000, ge=0)
    max_output_tokens: int = Field(default=12_000, ge=0)
    max_cost_usd: float = Field(default=0.50, ge=0.0)


class ModelUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_count: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0.0)


class ModelProfileConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: ModelProfile
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    max_output_tokens: int = Field(ge=1)
    timeout_ms: int = Field(default=30_000, ge=1)
    input_cost_per_million: float = Field(default=0.0, ge=0.0)
    output_cost_per_million: float = Field(default=0.0, ge=0.0)
    fallback_profile: ModelProfile | None = None


class ModelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(default_factory=lambda: new_id("modelreq"))
    run_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    profile: ModelProfile
    system_prompt: str = ""
    user_prompt: str = Field(min_length=1)
    context: dict[str, Any] = Field(default_factory=dict)
    response_schema: dict[str, Any] | None = None
    requested_max_output_tokens: int | None = Field(default=None, ge=1)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)


class ProviderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    model: str
    system_prompt: str
    user_prompt: str
    context: dict[str, Any]
    response_schema: dict[str, Any] | None
    max_output_tokens: int
    temperature: float
    timeout_ms: int


class ProviderResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = ""
    structured_output: dict[str, Any] | None = None
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    finish_reason: str = "stop"


class ModelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    profile: ModelProfile
    provider: str
    model: str
    text: str = ""
    structured_output: dict[str, Any] | None = None
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0.0)
    latency_ms: int = Field(ge=0)
    finish_reason: str


class ModelError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    profile: ModelProfile
    code: ModelErrorCode
    message: str
    retryable: bool = False


class ModelCallResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response: ModelResponse | None = None
    error: ModelError | None = None

    @model_validator(mode="after")
    def exactly_one_result(self) -> ModelCallResult:
        if (self.response is None) == (self.error is None):
            raise ValueError("exactly one of response or error is required")
        return self


class ModelProvider(Protocol):
    provider_name: str

    def generate(self, request: ProviderRequest) -> ProviderResponse: ...


class ModelGateway:
    """Agent 调用模型的唯一入口；路由、硬上限、计费和记账集中在此。"""

    def __init__(
        self,
        *,
        providers: list[ModelProvider],
        profiles: list[ModelProfileConfig],
    ) -> None:
        self._providers = {item.provider_name: item for item in providers}
        if len(self._providers) != len(providers):
            raise ValueError("provider_name must be unique")
        self._profiles = {item.profile: item for item in profiles}
        if len(self._profiles) != len(profiles):
            raise ValueError("model profile must be unique")

    def generate(
        self,
        request: ModelRequest,
        *,
        budget: ModelBudget,
        usage: ModelUsage,
    ) -> ModelCallResult:
        config = self._profiles.get(request.profile)
        if config is None:
            return self._error(request, ModelErrorCode.PROFILE_NOT_CONFIGURED, "model profile is not configured")
        provider = self._providers.get(config.provider)
        if provider is None:
            return self._error(request, ModelErrorCode.PROVIDER_NOT_CONFIGURED, "model provider is not configured")
        output_cap = min(request.requested_max_output_tokens or config.max_output_tokens, config.max_output_tokens)
        budget_error = _preflight_budget_error(budget, usage, output_cap)
        if budget_error:
            return self._error(request, ModelErrorCode.BUDGET_EXHAUSTED, budget_error)

        started = perf_counter()
        try:
            raw = provider.generate(
                ProviderRequest(
                    request_id=request.request_id,
                    model=config.model,
                    system_prompt=request.system_prompt,
                    user_prompt=request.user_prompt,
                    context=request.context,
                    response_schema=request.response_schema,
                    max_output_tokens=output_cap,
                    temperature=request.temperature,
                    timeout_ms=config.timeout_ms,
                )
            )
        except Exception as exc:
            error_name = type(exc).__name__
            error_code = {
                "RateLimitError": ModelErrorCode.RATE_LIMITED,
                "APITimeoutError": ModelErrorCode.TIMEOUT,
                "TimeoutException": ModelErrorCode.TIMEOUT,
            }.get(error_name, ModelErrorCode.UNAVAILABLE)
            return self._error(
                request,
                error_code,
                f"provider call failed: {error_name}",
                retryable=True,
            )

        cost = _cost_usd(raw, config)
        exceeds_budget = _would_exceed_budget(budget, usage, raw, cost)
        exceeds_output_cap = raw.output_tokens > output_cap
        usage.call_count += 1
        usage.input_tokens += raw.input_tokens
        usage.output_tokens += raw.output_tokens
        usage.cost_usd = round(usage.cost_usd + cost, 8)
        if exceeds_budget:
            return self._error(
                request,
                ModelErrorCode.BUDGET_EXHAUSTED,
                "provider usage would exceed run model budget",
            )
        if exceeds_output_cap:
            return self._error(
                request,
                ModelErrorCode.INVALID_RESPONSE,
                "provider output exceeded configured token cap",
            )
        return ModelCallResult(
            response=ModelResponse(
                request_id=request.request_id,
                profile=request.profile,
                provider=config.provider,
                model=config.model,
                text=raw.text,
                structured_output=raw.structured_output,
                input_tokens=raw.input_tokens,
                output_tokens=raw.output_tokens,
                cost_usd=cost,
                latency_ms=int((perf_counter() - started) * 1000),
                finish_reason=raw.finish_reason,
            )
        )

    @staticmethod
    def _error(
        request: ModelRequest,
        code: ModelErrorCode,
        message: str,
        *,
        retryable: bool = False,
    ) -> ModelCallResult:
        return ModelCallResult(
            error=ModelError(
                request_id=request.request_id,
                profile=request.profile,
                code=code,
                message=message,
                retryable=retryable,
            )
        )


def _preflight_budget_error(budget: ModelBudget, usage: ModelUsage, output_cap: int) -> str | None:
    if usage.call_count >= budget.max_calls:
        return "model call budget exhausted"
    if usage.input_tokens >= budget.max_input_tokens:
        return "model input token budget exhausted"
    if usage.output_tokens + output_cap > budget.max_output_tokens:
        return "requested output exceeds remaining model token budget"
    if usage.cost_usd >= budget.max_cost_usd:
        return "model cost budget exhausted"
    return None


def _cost_usd(response: ProviderResponse, config: ModelProfileConfig) -> float:
    value = (
        response.input_tokens * config.input_cost_per_million
        + response.output_tokens * config.output_cost_per_million
    ) / 1_000_000
    return round(value, 8)


def _would_exceed_budget(
    budget: ModelBudget,
    usage: ModelUsage,
    response: ProviderResponse,
    cost: float,
) -> bool:
    return (
        usage.input_tokens + response.input_tokens > budget.max_input_tokens
        or usage.output_tokens + response.output_tokens > budget.max_output_tokens
        or usage.cost_usd + cost > budget.max_cost_usd
    )
