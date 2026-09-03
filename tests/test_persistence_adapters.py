from __future__ import annotations

import unittest

from persistence.persistence_adapters import (
    PostgresConversationRepository,
    RedisUserProfileStore,
)
from persistence.storage import HistoryMessage, UserProfile
from runtime.taskboard import AgentRunBoard, AgentRunTrace, Artifact, ArtifactType, RunStatus


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.ttls = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, *, ex):
        self.values[key] = value.encode() if isinstance(value, str) else value
        self.ttls[key] = ex

    async def delete(self, key):
        return int(self.values.pop(key, None) is not None)

    async def aclose(self):
        self.closed = True


class FakeAsyncDatabase:
    def __init__(self):
        self.blackboards = {}
        self.history = []
        self.traces = {}
        self.statements = []

        self.engine = FakeAsyncEngine(self)


class FakeResult:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows


class FakeAsyncConnection:
    def __init__(self, database):
        self.database = database

    async def execute(self, sql, params=None):
        params = params or {}
        sql_text = str(sql)
        self.database.statements.append((sql_text, params))
        normalized = " ".join(sql_text.split())
        if normalized.startswith("INSERT INTO lawagent_history"):
            self.database.history.append(
                (params["session_id"], params["created_at"], params["payload"])
            )
            return FakeResult()
        if normalized.startswith("SELECT payload FROM lawagent_history"):
            matches = [item for item in self.database.history if item[0] == params["session_id"]]
            return FakeResult((item[2],) for item in reversed(matches[-params["limit"]:]))
        elif normalized.startswith("INSERT INTO lawagent_traces"):
            self.database.traces[params["run_id"]] = dict(params)
            return FakeResult()
        if normalized.startswith("SELECT payload FROM lawagent_traces"):
            stored = self.database.traces.get(params["run_id"])
            return FakeResult([(stored["payload"],)] if stored else [])
        return FakeResult()


class FakeTransactionContext:
    def __init__(self, database):
        self.connection = FakeAsyncConnection(database)

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class FakeAsyncEngine:
    def __init__(self, database):
        self.database = database
        self.disposed = False

    def begin(self):
        return FakeTransactionContext(self.database)

    async def dispose(self):
        self.disposed = True


class RedisAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_profile_round_trip_version_ttl_and_delete(self):
        client = FakeRedis()
        store = RedisUserProfileStore(client, ttl_seconds=60)
        first = await store.upsert(UserProfile(pseudonymous_user_id="user-1"))
        second = await store.upsert(first)

        self.assertEqual(second.version, 2)
        self.assertEqual((await store.get("user-1")).version, 2)
        self.assertEqual(client.ttls["lawagent:profile:user-1"], 60)
        self.assertTrue(await store.delete("user-1"))
        self.assertIsNone(await store.get("user-1"))
        await store.close()
        self.assertTrue(client.closed)


class PostgresAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_history_uses_parameterized_sql_and_preserves_order(self):
        database = FakeAsyncDatabase()
        repository = PostgresConversationRepository(database.engine)
        await repository.append_history(
            HistoryMessage(session_id="s1", run_id="r1", role="user", content="一")
        )
        await repository.append_history(
            HistoryMessage(session_id="s1", run_id="r2", role="assistant", content="二")
        )

        history = await repository.list_history("s1", limit=2)

        self.assertEqual([item.content for item in history], ["一", "二"])
        select_sql, select_params = database.statements[-1]
        self.assertIn("session_id=:session_id", select_sql)
        self.assertEqual(select_params, {"session_id": "s1", "limit": 2})

    async def test_trace_writes_filter_columns_and_round_trips_details(self):
        database = FakeAsyncDatabase()
        repository = PostgresConversationRepository(database.engine)
        board = AgentRunBoard(sanitized_input="已脱敏输入")
        board.status = RunStatus.COMPLETED
        board.model_usage.cost_usd = 0.125
        final = Artifact(
            run_id=board.run_id,
            task_id="review",
            artifact_type=ArtifactType.FINAL_RESPONSE,
            producer_agent="review",
            content={"decision": "limited_answer"},
        )
        board.artifacts.append(final)
        board.accepted_artifact_id = final.artifact_id
        trace = AgentRunTrace.from_board(board)

        await repository.save_trace(trace)
        restored = await repository.get_trace(trace.run_id)

        stored = database.traces[trace.run_id]
        self.assertEqual(stored["status"], "completed")
        self.assertEqual(stored["decision"], "limited_answer")
        self.assertTrue(stored["delivery_approved"])
        self.assertEqual(stored["total_cost_usd"], 0.125)
        self.assertEqual(stored["total_latency_ms"], 0)
        self.assertEqual(restored, trace)

    async def test_schema_initialization_and_engine_disposal_are_async(self):
        database = FakeAsyncDatabase()
        repository = PostgresConversationRepository(database.engine)

        await repository.initialize_schema()
        await repository.close()

        schema_sql = " ".join(sql for sql, _ in database.statements)
        self.assertIn("delivery_approved BOOLEAN", schema_sql)
        self.assertIn("lawagent_traces_audit_filter", schema_sql)
        self.assertTrue(database.engine.disposed)

    async def test_rejects_unsafe_schema_identifier(self):
        with self.assertRaisesRegex(ValueError, "invalid PostgreSQL schema"):
            PostgresConversationRepository(FakeAsyncDatabase().engine, schema="public; DROP")


if __name__ == "__main__":
    unittest.main()
