"""Redis 用户画像与 PostgreSQL 会话/Trace 的可注入持久化适配器。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from intake.blackboard import MatterBlackboard
from runtime.messages import AgentMessage
from persistence.storage import ConversationRepository, HistoryMessage, UserProfile, UserProfileStore
from runtime.taskboard import AgentRunBoard, AgentRunTrace


class RedisUserProfileStore(UserProfileStore):
    """兼容 redis-py 的最小 Adapter；客户端由组装层注入。"""

    def __init__(self, client: Any, *, key_prefix: str = "lawagent:profile:", ttl_seconds: int = 604_800):
        if ttl_seconds < 1:
            raise ValueError("ttl_seconds must be positive")
        self.client = client
        self.key_prefix = key_prefix
        self.ttl_seconds = ttl_seconds

    def _key(self, user_id: str) -> str:
        return f"{self.key_prefix}{user_id}"

    def get(self, pseudonymous_user_id: str) -> UserProfile | None:
        payload = self.client.get(self._key(pseudonymous_user_id))
        if payload is None:
            return None
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        return UserProfile.model_validate_json(payload)

    def upsert(self, profile: UserProfile) -> UserProfile:
        current = self.get(profile.pseudonymous_user_id)
        stored = profile.model_copy(
            update={"version": current.version + 1 if current else profile.version},
            deep=True,
        )
        self.client.set(
            self._key(stored.pseudonymous_user_id),
            stored.model_dump_json(),
            ex=self.ttl_seconds,
        )
        return stored

    def delete(self, pseudonymous_user_id: str) -> bool:
        return bool(self.client.delete(self._key(pseudonymous_user_id)))


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
  run_id TEXT PRIMARY KEY, payload JSONB NOT NULL, completed_at TIMESTAMPTZ NOT NULL
);
"""


class PostgresConversationRepository(ConversationRepository):
    """同步 DB-API/psycopg Adapter；每次操作使用独立短连接。"""

    def __init__(self, connection_factory: Callable[[], Any]):
        self.connection_factory = connection_factory

    @staticmethod
    def _json(model: Any) -> str:
        return model.model_dump_json()

    def _execute(self, sql: str, params: tuple[Any, ...] = (), *, fetch: bool = False) -> Any:
        connection = self.connection_factory()
        try:
            cursor = connection.cursor()
            try:
                cursor.execute(sql, params)
                result = cursor.fetchone() if fetch else None
                connection.commit()
                return result
            finally:
                cursor.close()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize_schema(self) -> None:
        self._execute(POSTGRES_SCHEMA)

    def create_run(self, board: AgentRunBoard) -> None:
        self._execute(
            "INSERT INTO lawagent_runs(run_id, session_id, payload, created_at) VALUES (%s,%s,%s::jsonb,%s)",
            (board.run_id, board.session_id, self._json(board), board.created_at),
        )

    def get_blackboard(self, session_id: str) -> MatterBlackboard | None:
        row = self._execute(
            "SELECT payload::text FROM lawagent_blackboards WHERE session_id=%s", (session_id,), fetch=True
        )
        return MatterBlackboard.model_validate_json(row[0]) if row else None

    def save_blackboard(self, blackboard: MatterBlackboard) -> None:
        self._execute(
            """INSERT INTO lawagent_blackboards(session_id,payload) VALUES (%s,%s::jsonb)
            ON CONFLICT(session_id) DO UPDATE SET payload=EXCLUDED.payload, updated_at=NOW()""",
            (blackboard.session_id, self._json(blackboard)),
        )

    def append_history(self, message: HistoryMessage) -> None:
        self._execute(
            "INSERT INTO lawagent_history(message_id,session_id,run_id,payload,created_at) VALUES (%s,%s,%s,%s::jsonb,%s)",
            (message.message_id, message.session_id, message.run_id, self._json(message), message.created_at),
        )

    def append_agent_message(self, message: AgentMessage) -> None:
        self._execute(
            "INSERT INTO lawagent_agent_messages(message_id,run_id,payload) VALUES (%s,%s,%s::jsonb)",
            (message.message_id, message.run_id, self._json(message)),
        )

    def save_trace(self, trace: AgentRunTrace) -> None:
        self._execute(
            """INSERT INTO lawagent_traces(run_id,payload,completed_at) VALUES (%s,%s::jsonb,%s)
            ON CONFLICT(run_id) DO UPDATE SET payload=EXCLUDED.payload, completed_at=EXCLUDED.completed_at""",
            (trace.run_id, self._json(trace), trace.completed_at),
        )

    def list_history(self, session_id: str, *, limit: int = 20) -> list[HistoryMessage]:
        if limit < 1:
            return []
        connection = self.connection_factory()
        try:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """SELECT payload::text FROM lawagent_history WHERE session_id=%s
                    ORDER BY created_at DESC LIMIT %s""",
                    (session_id, limit),
                )
                rows = cursor.fetchall()
                connection.commit()
            finally:
                cursor.close()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return [HistoryMessage.model_validate_json(row[0]) for row in reversed(rows)]

    def get_trace(self, run_id: str) -> AgentRunTrace | None:
        row = self._execute(
            "SELECT payload::text FROM lawagent_traces WHERE run_id=%s", (run_id,), fetch=True
        )
        return AgentRunTrace.model_validate_json(row[0]) if row else None
