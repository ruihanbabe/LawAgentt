"""Redis 用户画像与 PostgreSQL 会话/Trace 的可注入持久化适配器。"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from intake.blackboard import MatterBlackboard
from runtime.messages import AgentMessage
from persistence.storage import (
    ConversationRepository,
    HistoryMessage,
    TraceReuseExample,
    UserProfile,
    UserProfileStore,
)
from runtime.taskboard import AgentRunBoard, AgentRunTrace


class RedisUserProfileStore(UserProfileStore):
    """基于 ``redis.asyncio`` client 的异步画像 Adapter。"""

    def __init__(self, client: Any, *, key_prefix: str = "lawagent:profile:", ttl_seconds: int = 604_800):
        if ttl_seconds < 1:
            raise ValueError("ttl_seconds must be positive")
        self.client = client
        self.key_prefix = key_prefix
        self.ttl_seconds = ttl_seconds

    def _key(self, user_id: str) -> str:
        return f"{self.key_prefix}{user_id}"

    async def get(self, pseudonymous_user_id: str) -> UserProfile | None:
        payload = await self.client.get(self._key(pseudonymous_user_id))
        if payload is None:
            return None
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        return UserProfile.model_validate_json(payload)

    async def upsert(self, profile: UserProfile) -> UserProfile:
        current = await self.get(profile.pseudonymous_user_id)
        stored = profile.model_copy(
            update={"version": current.version + 1 if current else profile.version},
            deep=True,
        )
        await self.client.set(
            self._key(stored.pseudonymous_user_id),
            stored.model_dump_json(),
            ex=self.ttl_seconds,
        )
        return stored

    async def delete(self, pseudonymous_user_id: str) -> bool:
        return bool(await self.client.delete(self._key(pseudonymous_user_id)))

    async def close(self) -> None:
        close = getattr(self.client, "aclose", None)
        if close is not None:
            await close()


POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS lawagent_runs (
  run_id TEXT PRIMARY KEY, session_id TEXT, payload JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS lawagent_blackboards (
  session_id TEXT PRIMARY KEY, payload JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS lawagent_history (
  message_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, run_id TEXT NOT NULL,
  payload JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS lawagent_history_session_created
  ON lawagent_history(session_id, created_at);
CREATE TABLE IF NOT EXISTS lawagent_agent_messages (
  message_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, payload JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS lawagent_traces (
  run_id TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  decision TEXT,
  delivery_approved BOOLEAN NOT NULL,
  total_cost_usd DOUBLE PRECISION NOT NULL,
  total_latency_ms BIGINT NOT NULL,
  payload JSONB NOT NULL,
  completed_at TIMESTAMPTZ NOT NULL
);
ALTER TABLE lawagent_traces ADD COLUMN IF NOT EXISTS status TEXT;
ALTER TABLE lawagent_traces ADD COLUMN IF NOT EXISTS decision TEXT;
ALTER TABLE lawagent_traces ADD COLUMN IF NOT EXISTS delivery_approved BOOLEAN;
ALTER TABLE lawagent_traces ADD COLUMN IF NOT EXISTS total_cost_usd DOUBLE PRECISION;
ALTER TABLE lawagent_traces ADD COLUMN IF NOT EXISTS total_latency_ms BIGINT;
UPDATE lawagent_traces SET
  status = COALESCE(status, payload->>'status', 'failed'),
  decision = COALESCE(decision, payload#>>'{artifacts,-1,content,decision}'),
  delivery_approved = COALESCE(delivery_approved, (payload->>'accepted_artifact_id') IS NOT NULL),
  total_cost_usd = COALESCE(total_cost_usd, (payload#>>'{model_usage,cost_usd}')::DOUBLE PRECISION, 0),
  total_latency_ms = COALESCE(total_latency_ms, 0);
ALTER TABLE lawagent_traces ALTER COLUMN status SET NOT NULL;
ALTER TABLE lawagent_traces ALTER COLUMN delivery_approved SET NOT NULL;
ALTER TABLE lawagent_traces ALTER COLUMN total_cost_usd SET NOT NULL;
ALTER TABLE lawagent_traces ALTER COLUMN total_latency_ms SET NOT NULL;
CREATE INDEX IF NOT EXISTS lawagent_traces_audit_filter
  ON lawagent_traces(status, decision, delivery_approved);
CREATE INDEX IF NOT EXISTS lawagent_traces_cost_latency
  ON lawagent_traces(total_cost_usd, total_latency_ms);
CREATE TABLE IF NOT EXISTS lawagent_trace_reuse_examples (
  example_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL UNIQUE,
  session_id TEXT NOT NULL,
  contributor_user_id TEXT,
  scenario_id TEXT NOT NULL,
  confirmed_facts_summary JSONB NOT NULL,
  payload JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS lawagent_trace_reuse_scenario_created
  ON lawagent_trace_reuse_examples(scenario_id, created_at DESC);
CREATE INDEX IF NOT EXISTS lawagent_trace_reuse_contributor
  ON lawagent_trace_reuse_examples(contributor_user_id);
"""

_POSTGRES_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


class PostgresConversationRepository(ConversationRepository):
    """基于 SQLAlchemy async engine/asyncpg 的会话与审计 Adapter。"""

    def __init__(
        self,
        engine_or_dsn: AsyncEngine | str,
        *,
        pool_size: int = 5,
        max_overflow: int = 5,
        schema: str = "public",
    ) -> None:
        if pool_size < 1 or max_overflow < 0:
            raise ValueError("invalid PostgreSQL pool configuration")
        if not _POSTGRES_IDENTIFIER.fullmatch(schema):
            raise ValueError("invalid PostgreSQL schema name")
        self.schema = schema
        if isinstance(engine_or_dsn, str):
            dsn = engine_or_dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
            self.engine = create_async_engine(
                dsn,
                pool_size=pool_size,
                max_overflow=max_overflow,
                pool_pre_ping=True,
                connect_args={"server_settings": {"search_path": schema}},
            )
        else:
            self.engine = engine_or_dsn

    async def _execute(
        self,
        sql: str,
        params: dict[str, Any] | None = None,
        *,
        fetch: str | None = None,
    ) -> Any:
        async with self.engine.begin() as connection:
            result = await connection.execute(text(sql), params or {})
            if fetch == "one":
                return result.first()
            if fetch == "all":
                return result.all()
            return None

    async def initialize_schema(self) -> None:
        async with self.engine.begin() as connection:
            for statement in (item.strip() for item in POSTGRES_SCHEMA.split(";") if item.strip()):
                await connection.execute(text(statement))

    async def create_run(self, board: AgentRunBoard) -> None:
        await self._execute(
            """INSERT INTO lawagent_runs(run_id, session_id, payload, created_at)
            VALUES (:run_id,:session_id,CAST(:payload AS JSONB),:created_at)""",
            {"run_id": board.run_id, "session_id": board.session_id,
             "payload": board.model_dump_json(), "created_at": board.created_at},
        )

    async def get_blackboard(self, session_id: str) -> MatterBlackboard | None:
        row = await self._execute(
            "SELECT payload FROM lawagent_blackboards WHERE session_id=:session_id",
            {"session_id": session_id}, fetch="one",
        )
        return self._model(MatterBlackboard, row[0]) if row else None

    async def save_blackboard(self, blackboard: MatterBlackboard) -> None:
        await self._execute(
            """INSERT INTO lawagent_blackboards(session_id,payload)
            VALUES (:session_id,CAST(:payload AS JSONB))
            ON CONFLICT(session_id) DO UPDATE SET payload=EXCLUDED.payload, updated_at=NOW()""",
            {"session_id": blackboard.session_id, "payload": blackboard.model_dump_json()},
        )

    async def append_history(self, message: HistoryMessage) -> None:
        await self._execute(
            """INSERT INTO lawagent_history(message_id,session_id,run_id,payload,created_at)
            VALUES (:message_id,:session_id,:run_id,CAST(:payload AS JSONB),:created_at)""",
            {"message_id": message.message_id, "session_id": message.session_id,
             "run_id": message.run_id, "payload": message.model_dump_json(),
             "created_at": message.created_at},
        )

    async def append_agent_message(self, message: AgentMessage) -> None:
        await self._execute(
            """INSERT INTO lawagent_agent_messages(message_id,run_id,payload)
            VALUES (:message_id,:run_id,CAST(:payload AS JSONB))""",
            {"message_id": message.message_id, "run_id": message.run_id,
             "payload": message.model_dump_json()},
        )

    async def save_trace(self, trace: AgentRunTrace) -> None:
        audit = self._trace_audit_fields(trace)
        await self._execute(
            """INSERT INTO lawagent_traces(
              run_id,status,decision,delivery_approved,total_cost_usd,total_latency_ms,payload,completed_at
            ) VALUES (
              :run_id,:status,:decision,:delivery_approved,:total_cost_usd,:total_latency_ms,
              CAST(:payload AS JSONB),:completed_at
            ) ON CONFLICT(run_id) DO UPDATE SET
              status=EXCLUDED.status, decision=EXCLUDED.decision,
              delivery_approved=EXCLUDED.delivery_approved,
              total_cost_usd=EXCLUDED.total_cost_usd,
              total_latency_ms=EXCLUDED.total_latency_ms,
              payload=EXCLUDED.payload, completed_at=EXCLUDED.completed_at""",
            {**audit, "run_id": trace.run_id, "payload": trace.model_dump_json(),
             "completed_at": trace.completed_at},
        )

    async def list_history(self, session_id: str, *, limit: int = 20) -> list[HistoryMessage]:
        if limit < 1:
            return []
        rows = await self._execute(
            """SELECT payload FROM lawagent_history WHERE session_id=:session_id
            ORDER BY created_at DESC LIMIT :limit""",
            {"session_id": session_id, "limit": limit}, fetch="all",
        )
        return [self._model(HistoryMessage, row[0]) for row in reversed(rows)]

    async def get_trace(self, run_id: str) -> AgentRunTrace | None:
        row = await self._execute(
            "SELECT payload FROM lawagent_traces WHERE run_id=:run_id",
            {"run_id": run_id}, fetch="one",
        )
        return self._model(AgentRunTrace, row[0]) if row else None

    async def save_example(self, example: TraceReuseExample) -> None:
        await self._execute(
            """INSERT INTO lawagent_trace_reuse_examples(
              example_id,run_id,session_id,contributor_user_id,scenario_id,
              confirmed_facts_summary,payload,created_at
            ) VALUES (
              :example_id,:run_id,:session_id,:contributor_user_id,:scenario_id,
              CAST(:confirmed_facts_summary AS JSONB),CAST(:payload AS JSONB),:created_at
            ) ON CONFLICT(run_id) DO NOTHING""",
            {
                "example_id": example.example_id,
                "run_id": example.run_id,
                "session_id": example.session_id,
                "contributor_user_id": example.contributor_user_id,
                "scenario_id": example.scenario_id,
                "confirmed_facts_summary": json.dumps(
                    example.confirmed_facts_summary, ensure_ascii=False
                ),
                "payload": example.model_dump_json(),
                "created_at": example.created_at,
            },
        )

    async def search_examples(
        self, scenario_id: str, facts: dict[str, str], *, limit: int = 5
    ) -> list[TraceReuseExample]:
        if limit < 1:
            return []
        rows = await self._execute(
            """SELECT payload FROM lawagent_trace_reuse_examples
            WHERE scenario_id=:scenario_id ORDER BY created_at DESC LIMIT 100""",
            {"scenario_id": scenario_id},
            fetch="all",
        )
        examples = [self._model(TraceReuseExample, row[0]) for row in rows]
        query_pairs = set(facts.items())
        examples.sort(key=lambda item: (
            -len(query_pairs & set(item.confirmed_facts_summary.items())),
            -item.created_at.timestamp(),
            item.example_id,
        ))
        return examples[:limit]

    async def delete_examples_by_user(self, contributor_user_id: str) -> int:
        async with self.engine.begin() as connection:
            result = await connection.execute(
                text("""DELETE FROM lawagent_trace_reuse_examples
                WHERE contributor_user_id=:contributor_user_id"""),
                {"contributor_user_id": contributor_user_id},
            )
            return int(result.rowcount or 0)

    async def close(self) -> None:
        await self.engine.dispose()

    @staticmethod
    def _model(model_type: Any, payload: Any) -> Any:
        if isinstance(payload, str | bytes):
            return model_type.model_validate_json(payload)
        return model_type.model_validate(payload)

    @staticmethod
    def _trace_audit_fields(trace: AgentRunTrace) -> dict[str, Any]:
        accepted = next(
            (item for item in trace.artifacts if item.artifact_id == trace.accepted_artifact_id),
            None,
        )
        decision = accepted.content.get("decision") if accepted is not None else None
        total_latency_ms = sum(
            int(event.payload.get("latency_ms", 0))
            for event in trace.events
            if isinstance(event.payload.get("latency_ms", 0), int | float)
        )
        return {
            "status": trace.status.value,
            "decision": str(decision) if decision is not None else None,
            "delivery_approved": accepted is not None,
            "total_cost_usd": trace.model_usage.cost_usd,
            "total_latency_ms": total_latency_ms,
        }
