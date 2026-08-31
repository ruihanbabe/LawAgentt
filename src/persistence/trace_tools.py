"""Trace Viewer 的最小脱敏投影。"""

from __future__ import annotations

from typing import Any

from runtime.taskboard import AgentRunTrace


def trace_view(trace: AgentRunTrace) -> dict[str, Any]:
    """返回调试所需结构，避免再次暴露产物正文和消息正文。"""

    return {
        "run_id": trace.run_id,
        "session_id": trace.session_id,
        "runtime_profile": trace.runtime_profile,
        "status": trace.status.value,
        "pii_status": trace.pii_status.value,
        "accepted_artifact_id": trace.accepted_artifact_id,
        "model_usage": trace.model_usage.model_dump(mode="json"),
        "created_at": trace.created_at.isoformat(),
        "completed_at": trace.completed_at.isoformat(),
        "tasks": [
            {
                "task_id": item.task_id,
                "task_type": item.task_type,
                "status": item.status.value,
                "claimed_by": item.claimed_by,
                "failure_code": item.failure_code,
            }
            for item in trace.tasks
        ],
        "events": [
            {
                "sequence": item.sequence,
                "event_type": item.event_type.value,
                "actor_type": item.actor_type,
                "actor_id": item.actor_id,
                "task_id": item.task_id,
                "artifact_id": item.artifact_id,
                "payload": item.payload,
            }
            for item in trace.events
        ],
        "artifacts": [
            {
                "artifact_id": item.artifact_id,
                "artifact_type": item.artifact_type.value,
                "producer_agent": item.producer_agent,
                "evidence_refs": item.evidence_refs,
                "source_artifact_ids": item.source_artifact_ids,
                "validation_status": item.validation_status,
                "review_status": item.review_status,
            }
            for item in trace.artifacts
        ],
    }
