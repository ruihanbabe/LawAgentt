#!/usr/bin/env python3
"""运行隔离于实时Qdrant的六角色GLM smoke，并输出质量矩阵JSON。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from knowledge.evidence_views import CaseEvidenceView, LawEvidenceView
from infrastructure.env import load_project_env
from infrastructure.glm_provider import build_glm_gateway_from_env
from conversation.harness import build_default_harness
from runtime.model_provider import ModelProfile
from runtime.taskboard import EventType
from runtime.tools import (
    ToolExecutor,
    ToolPermission,
    ToolRegistry,
    ToolResult,
    ToolResultStatus,
    ToolSpec,
)


class StaticEvidenceAdapter:
    def __init__(self, name: str, permission: ToolPermission, item: object) -> None:
        self.spec = ToolSpec(
            name=name,
            description=f"six-role smoke fixture: {name}",
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {"query": {"type": "string"}, "top_k": {"type": "integer"}},
                "additionalProperties": False,
            },
            output_schema={},
            permissions=[permission],
        )
        self.item = item

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(tool_name=self.spec.name, status=ToolResultStatus.SUCCESS, items=[self.item])


def build_static_executor() -> ToolExecutor:
    registry = ToolRegistry()
    registry.register(StaticEvidenceAdapter(
        "search_statutes",
        ToolPermission.SEARCH_PUBLIC_LAW,
        LawEvidenceView(
            chunk_id="smoke-law-509",
            law_family_id="civil-code",
            law_version_id="smoke-snapshot-v1",
            title="民法典",
            article_no="509",
            content="当事人应当按照约定全面履行自己的义务。",
            validity_status="current",
            warnings=["quality_matrix_fixture_not_product_evidence"],
        ),
    ))
    registry.register(StaticEvidenceAdapter(
        "search_cases",
        ToolPermission.SEARCH_SANITIZED_CASES,
        CaseEvidenceView(
            case_id="smoke-case-1",
            title="租赁合同纠纷质量矩阵夹具",
            warnings=["quality_matrix_fixture_not_product_evidence"],
        ),
    ))
    return ToolExecutor(
        registry,
        {ToolPermission.SEARCH_PUBLIC_LAW, ToolPermission.SEARCH_SANITIZED_CASES},
    )


def quality_matrix(board) -> dict[str, Any]:
    called = [item for item in board.events if item.event_type == EventType.MODEL_CALLED]
    degraded = [item for item in board.events if item.event_type == EventType.MODEL_DEGRADED]
    by_profile = {
        profile.value: {
            "called": False,
            "degraded": False,
            "model": None,
            "input_tokens": 0,
            "output_tokens": 0,
            "latency_ms": 0,
            "error_code": None,
            "safe_message": None,
        }
        for profile in ModelProfile
    }
    for event in called:
        row = by_profile[str(event.payload["profile"])]
        row.update({
            "called": True,
            "model": event.payload.get("model"),
            "input_tokens": event.payload.get("input_tokens", 0),
            "output_tokens": event.payload.get("output_tokens", 0),
            "latency_ms": event.payload.get("latency_ms", 0),
        })
    for event in degraded:
        row = by_profile[str(event.payload["profile"])]
        row["degraded"] = True
        row["error_code"] = event.payload.get("error_code")
        row["safe_message"] = event.payload.get("safe_message")
    return {
        "run_id": board.run_id,
        "status": board.status.value,
        "accepted_decision": (
            board.artifact(board.accepted_artifact_id).content.get("decision")
            if board.accepted_artifact_id else None
        ),
        "all_six_called": len(called) == len(ModelProfile),
        "model_usage": board.model_usage.model_dump(mode="json"),
        "profiles": by_profile,
        "delivery_events": [
            item.event_type.value for item in board.events
            if item.event_type in {EventType.DELIVERY_ACCEPTED, EventType.DELIVERY_BLOCKED}
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="可选JSON报告路径")
    args = parser.parse_args()
    load_project_env()
    if not (os.getenv("GLM_API_KEY") or os.getenv("ZAI_API_KEY")):
        parser.error("GLM_API_KEY or ZAI_API_KEY must be set in project .env or process environment")
    harness = build_default_harness(build_static_executor(), build_glm_gateway_from_env())
    result = harness.handle(
        "我已退租并交还钥匙，房东以墙面损坏为由扣押金；合同有押金返还条款，我有转账、照片和聊天记录。",
        session_id="glm-six-role-smoke",
        pseudonymous_user_id="glm-six-role-smoke",
    )
    report = quality_matrix(result.board)
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["all_six_called"] and report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
