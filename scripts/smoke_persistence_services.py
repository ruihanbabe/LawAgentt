"""真实 Redis/PostgreSQL 持久化 Adapter 的最小 smoke。"""

from __future__ import annotations

import os
from uuid import uuid4

import psycopg
from redis import Redis

from persistence.persistence_adapters import (
    PostgresConversationRepository,
    RedisUserProfileStore,
)
from persistence.storage import HistoryMessage, UserProfile


def main() -> None:
    redis_url = os.getenv("REDIS_URL", "redis://:lawagent-dev@127.0.0.1:6379/0")
    postgres_dsn = os.getenv(
        "POSTGRES_DSN",
        "postgresql://lawagent:lawagent-dev@127.0.0.1:5432/lawagent",
    )
    marker = uuid4().hex

    redis_client = Redis.from_url(redis_url, socket_connect_timeout=3, socket_timeout=3)
    if not redis_client.ping():
        raise RuntimeError("Redis ping failed")
    profile_store = RedisUserProfileStore(redis_client, ttl_seconds=60)
    user_id = f"smoke-{marker}"
    stored = profile_store.upsert(UserProfile(pseudonymous_user_id=user_id))
    ttl = redis_client.ttl(f"lawagent:profile:{user_id}")
    if stored.version != 1 or profile_store.get(user_id) is None or not 0 < ttl <= 60:
        raise RuntimeError("Redis adapter TTL/round-trip failed")
    if not profile_store.delete(user_id) or profile_store.get(user_id) is not None:
        raise RuntimeError("Redis adapter delete failed")

    repository = PostgresConversationRepository(lambda: psycopg.connect(postgres_dsn))
    repository.initialize_schema()
    session_id = f"smoke-{marker}"
    message = HistoryMessage(session_id=session_id, run_id=f"run-{marker}", role="user", content="smoke")
    repository.append_history(message)
    history = repository.list_history(session_id, limit=1)
    if len(history) != 1 or history[0].content != "smoke":
        raise RuntimeError("PostgreSQL adapter transaction/round-trip failed")
    with psycopg.connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM lawagent_history WHERE session_id=%s", (session_id,))

    print("PASS redis ping + adapter TTL/round-trip/delete")
    print("PASS postgres connect + schema + transaction/round-trip/cleanup")


if __name__ == "__main__":
    main()
