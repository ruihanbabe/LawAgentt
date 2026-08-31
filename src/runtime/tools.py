from __future__ import annotations

from enum import StrEnum
from time import perf_counter
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from knowledge.evidence_views import CaseEvidenceView, LawEvidenceView
from runtime.identifiers import new_id
from safety.pii import PIIPolicy

ToolMetadataValue = str | int | float | bool | list[str] | dict[str, str | int | float | bool | list[str] | None] | None


class ToolPermission(StrEnum):
    SEARCH_PUBLIC_LAW = "search_public_law"
    SEARCH_SANITIZED_CASES = "search_sanitized_cases"
    FETCH_CASE_EVIDENCE = "fetch_case_evidence"


class ToolResultStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    EMPTY = "empty"
    BLOCKED = "blocked"
    FAILED = "failed"


class ToolSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    description: str = Field(min_length=1)
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    permissions: list[ToolPermission] = Field(default_factory=list)
    timeout_ms: int = Field(default=30_000, ge=1)
    max_retries: int = Field(default=1, ge=0, le=5)
    pii_policy: PIIPolicy = PIIPolicy.MASK


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_id: str = Field(default_factory=lambda: new_id("toolcall"))
    trace_id: str = Field(default_factory=lambda: new_id("trace"))
    tool_name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    status: ToolResultStatus
    items: list[CaseEvidenceView | LawEvidenceView] = Field(default_factory=list)
    pii_blocked_count: int = Field(default=0, ge=0)
    warnings: list[str] = Field(default_factory=list)
    latency_ms: int | None = Field(default=None, ge=0)
    error: str | None = None
    metadata: dict[str, ToolMetadataValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def status_matches_content(self) -> ToolResult:
        if self.status == ToolResultStatus.FAILED and not self.error:
            raise ValueError("failed tool results require error")
        if self.status != ToolResultStatus.FAILED and self.error:
            raise ValueError("only failed tool results may include error")
        if self.status == ToolResultStatus.EMPTY and self.items:
            raise ValueError("empty tool results cannot include items")
        if self.status == ToolResultStatus.BLOCKED and self.pii_blocked_count < 1:
            raise ValueError("blocked tool results require pii_blocked_count")
        return self


class ToolExecutionError(ValueError):
    pass


class ToolInputError(ToolExecutionError):
    pass


class ToolPermissionError(ToolExecutionError):
    pass


class ToolAdapter(Protocol):
    spec: ToolSpec

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        ...


class ToolRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, ToolAdapter] = {}

    def register(self, adapter: ToolAdapter) -> None:
        name = adapter.spec.name
        if name in self._adapters:
            raise ValueError(f"tool already registered: {name}")
        self._adapters[name] = adapter

    def get(self, name: str) -> ToolAdapter:
        try:
            return self._adapters[name]
        except KeyError as exc:
            raise KeyError(f"tool is not registered: {name}") from exc

    def specs(self) -> list[ToolSpec]:
        return [self._adapters[name].spec for name in sorted(self._adapters)]


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, granted_permissions: set[ToolPermission] | None = None) -> None:
        self.registry = registry
        self.granted_permissions = granted_permissions or set()

    def execute(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        started = perf_counter()
        try:
            adapter = self.registry.get(tool_name)
            _assert_permissions(adapter.spec, self.granted_permissions)
            _validate_json_object(arguments, adapter.spec.input_schema)
            result = adapter.execute(arguments)
            if result.tool_name != tool_name:
                raise ToolExecutionError(f"adapter returned mismatched tool_name: {result.tool_name}")
            if result.latency_ms is None:
                result.latency_ms = int((perf_counter() - started) * 1000)
            return result
        except ToolPermissionError as exc:
            return _failed_tool_result(tool_name, "permission_denied", exc, started)
        except ToolInputError as exc:
            return _failed_tool_result(tool_name, "invalid_input", exc, started)
        except Exception as exc:
            return _failed_tool_result(tool_name, "tool_execution_error", exc, started)


def _assert_permissions(spec: ToolSpec, granted: set[ToolPermission]) -> None:
    missing = set(spec.permissions) - granted
    if missing:
        names = ", ".join(sorted(item.value for item in missing))
        raise ToolPermissionError(f"missing tool permissions: {names}")


def _failed_tool_result(tool_name: str, code: str, error: Exception, started: float) -> ToolResult:
    return ToolResult(
        tool_name=tool_name,
        status=ToolResultStatus.FAILED,
        warnings=[code],
        latency_ms=int((perf_counter() - started) * 1000),
        error=str(error),
        metadata={"error_code": code},
    )


def _validate_json_object(arguments: dict[str, Any], schema: dict[str, Any]) -> None:
    if schema.get("type") != "object":
        raise ToolInputError("v0 tool input_schema must have type=object")
    required = schema.get("required") or []
    for name in required:
        if name not in arguments:
            raise ToolInputError(f"missing required argument: {name}")
    properties = schema.get("properties") or {}
    additional_allowed = schema.get("additionalProperties", True)
    if not additional_allowed:
        extra = set(arguments) - set(properties)
        if extra:
            raise ToolInputError(f"unexpected arguments: {sorted(extra)}")
    for name, value in arguments.items():
        if name in properties:
            _validate_json_value(name, value, properties[name])


def _validate_json_value(name: str, value: Any, schema: dict[str, Any]) -> None:
    expected = schema.get("type")
    if expected is None:
        return
    allowed = expected if isinstance(expected, list) else [expected]
    if value is None and "null" in allowed:
        return
    validators = {
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: (isinstance(item, int | float) and not isinstance(item, bool)),
        "boolean": lambda item: isinstance(item, bool),
        "array": lambda item: isinstance(item, list),
        "object": lambda item: isinstance(item, dict),
    }
    if not any(validators[kind](value) for kind in allowed if kind in validators):
        raise ToolInputError(f"argument {name} has invalid type, expected {allowed}")
    if "enum" in schema and value not in schema["enum"]:
        raise ToolInputError(f"argument {name} must be one of {schema['enum']}")
    if isinstance(value, list) and schema.get("items"):
        for index, item in enumerate(value):
            _validate_json_value(f"{name}[{index}]", item, schema["items"])
