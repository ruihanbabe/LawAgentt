from __future__ import annotations

import unittest

from lawagent_runtime.persistence_adapters import (
    PostgresConversationRepository,
    RedisUserProfileStore,
)
from lawagent_runtime.storage import HistoryMessage, UserProfile


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.ttls = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, *, ex):
        self.values[key] = value.encode() if isinstance(value, str) else value
        self.ttls[key] = ex

    def delete(self, key):
        return int(self.values.pop(key, None) is not None)


class FakeDatabase:
    def __init__(self):
        self.blackboards = {}
        self.history = []
        self.traces = {}
        self.statements = []

    def connect(self):
        return FakeConnection(self)


class FakeCursor:
    def __init__(self, database):
        self.database = database
        self.rows = []

    def execute(self, sql, params=()):
        self.database.statements.append((sql, params))
        normalized = " ".join(sql.split())
        if normalized.startswith("INSERT INTO lawagent_history"):
            self.database.history.append((params[1], params[4], params[3]))
        elif normalized.startswith("SELECT payload::text FROM lawagent_history"):
            matches = [item for item in self.database.history if item[0] == params[0]]
            self.rows = [(item[2],) for item in reversed(matches[-params[1]:])]
        elif normalized.startswith("INSERT INTO lawagent_traces"):
            self.database.traces[params[0]] = params[1]
        elif normalized.startswith("SELECT payload::text FROM lawagent_traces"):
            payload = self.database.traces.get(params[0])
            self.rows = [(payload,)] if payload else []

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows

    def close(self):
        pass


class FakeConnection:
    def __init__(self, database):
        self.database = database
        self.committed = False

    def cursor(self):
        return FakeCursor(self.database)

    def commit(self):
        self.committed = True

    def rollback(self):
        pass

    def close(self):
        pass


class RedisAdapterTests(unittest.TestCase):
    def test_profile_round_trip_version_ttl_and_delete(self):
        client = FakeRedis()
        store = RedisUserProfileStore(client, ttl_seconds=60)
        first = store.upsert(UserProfile(pseudonymous_user_id="user-1"))
        second = store.upsert(first)

        self.assertEqual(second.version, 2)
        self.assertEqual(store.get("user-1").version, 2)
        self.assertEqual(client.ttls["lawagent:profile:user-1"], 60)
        self.assertTrue(store.delete("user-1"))
        self.assertIsNone(store.get("user-1"))


class PostgresAdapterTests(unittest.TestCase):
    def test_history_uses_parameterized_sql_and_preserves_order(self):
        database = FakeDatabase()
        repository = PostgresConversationRepository(database.connect)
        repository.append_history(HistoryMessage(session_id="s1", run_id="r1", role="user", content="一"))
        repository.append_history(HistoryMessage(session_id="s1", run_id="r2", role="assistant", content="二"))

        history = repository.list_history("s1", limit=2)

        self.assertEqual([item.content for item in history], ["一", "二"])
        select_sql, select_params = database.statements[-1]
        self.assertIn("session_id=%s", select_sql)
        self.assertEqual(select_params, ("s1", 2))


if __name__ == "__main__":
    unittest.main()
