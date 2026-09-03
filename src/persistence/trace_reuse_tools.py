"""Trace 范例池的 ToolExecutor Adapter；返回值永远不是 Evidence。"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

from persistence.storage import TraceReusePool
from runtime.tools import (
    ToolPermission,
    ToolResult,
    ToolResultStatus,
    ToolSpec,
    TraceReuseExampleView,
)


class TraceReuseSearchAdapter:
    def __init__(self, pool: TraceReusePool) -> None:
        self.pool = pool
        self.spec = ToolSpec(
            name="search_trace_examples",
            description="按场景与已确认事实检索通过门禁的结构化范例",
            input_schema={
                "type": "object",
                "required": ["scenario_id", "facts"],
                "properties": {
                    "scenario_id": {"type": "string"},
                    "facts": {"type": "object"},
                    "top_k": {"type": "integer"},
                },
                "additionalProperties": False,
            },
            output_schema=TraceReuseExampleView.model_json_schema(),
            permissions=[ToolPermission.SEARCH_TRACE_EXAMPLES],
        )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        result = self.pool.search_examples(
            str(arguments["scenario_id"]),
            {str(key): str(value) for key, value in arguments["facts"].items()},
            limit=max(1, min(20, int(arguments.get("top_k", 5)))),
        )
        examples = asyncio.run(result) if inspect.isawaitable(result) else result
        views = [TraceReuseExampleView(
            example_id=item.example_id,
            scenario_id=item.scenario_id,
            confirmed_facts_summary=dict(item.confirmed_facts_summary),
            claim_items=tuple(entry.model_dump(mode="json") for entry in item.claim_items),
            action_template_condition_key=item.action_template_condition_key,
        ) for item in examples]
        return ToolResult(
            tool_name=self.spec.name,
            status=ToolResultStatus.SUCCESS if views else ToolResultStatus.EMPTY,
            items=views,
            metadata={"result_kind": "auxiliary_trace_example", "is_evidence": False},
        )
