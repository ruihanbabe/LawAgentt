"""真实 Redis/PostgreSQL 持久化 Adapter 的最小 smoke。"""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from persistence.persistence_adapters import (
    PostgresConversationRepository,
    RedisUserProfileStore,
)
from persistence.storage import (
    HistoryMessage,
    TraceReuseClaimItem,
    TraceReuseExample,
    UserProfile,
)


async def main() -> None:
    redis_url = os.getenv("REDIS_URL", "redis://:lawagent-dev@127.0.0.1:6379/0")
    postgres_dsn = os.getenv(
        "POSTGRES_DSN",
        "postgresql://lawagent:lawagent-dev@127.0.0.1:5432/lawagent",
    )
    marker = uuid4().hex

    redis_client = Redis.from_url(redis_url, socket_connect_timeout=3, socket_timeout=3)
    if not await redis_client.ping():
        raise RuntimeError("Redis ping failed")
    redis_prefix = f"lawagent:test:{marker}:profile:"
    profile_store = RedisUserProfileStore(
        redis_client,
        key_prefix=redis_prefix,
        ttl_seconds=60,
    )
    user_id = f"smoke-{marker}"
    stored = await profile_store.upsert(UserProfile(pseudonymous_user_id=user_id))
    ttl = await redis_client.ttl(f"{redis_prefix}{user_id}")
    if stored.version != 1 or await profile_store.get(user_id) is None or not 0 < ttl <= 60:
        raise RuntimeError("Redis adapter TTL/round-trip failed")
    if not await profile_store.delete(user_id) or await profile_store.get(user_id) is not None:
        raise RuntimeError("Redis adapter delete failed")
    await profile_store.close()

    async_dsn = postgres_dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
    admin_engine = create_async_engine(async_dsn)
    test_schema = f"lawagent_test_{marker}"
    async with admin_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{test_schema}"'))
    repository = PostgresConversationRepository(postgres_dsn, schema=test_schema)
    try:
        await repository.initialize_schema()
        session_id = f"smoke-{marker}"
        message = HistoryMessage(
            session_id=session_id,
            run_id=f"run-{marker}",
            role="user",
            content="smoke",
        )
        await repository.append_history(message)
        history = await repository.list_history(session_id, limit=1)
        if len(history) != 1 or history[0].content != "smoke":
            raise RuntimeError("PostgreSQL adapter transaction/round-trip failed")
        example = TraceReuseExample(
            run_id=f"run-{marker}",
            session_id=session_id,
            contributor_user_id=user_id,
            scenario_id="smoke-scenario",
            confirmed_facts_summary={"status": "confirmed"},
            claim_items=(TraceReuseClaimItem(
                item_key="smoke-item",
                applicability="applicable",
                evidence_ids=("law:smoke",),
            ),),
            action_template_condition_key="smoke-branch",
        )
        await repository.save_example(example)
        examples = await repository.search_examples(
            "smoke-scenario", {"status": "confirmed"}, limit=1
        )
        if len(examples) != 1 or examples[0].run_id != example.run_id:
            raise RuntimeError("PostgreSQL trace reuse round-trip failed")
        if await repository.delete_examples_by_user(user_id) != 1:
            raise RuntimeError("PostgreSQL trace reuse delete failed")
        async with repository.engine.begin() as connection:
            result = await connection.execute(text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema=:schema AND table_name='lawagent_traces'
                  AND column_name IN (
                    'status','decision','delivery_approved','total_cost_usd','total_latency_ms'
                  )
            """), {"schema": test_schema})
            trace_columns = {row[0] for row in result.all()}
            if trace_columns != {
                "status", "decision", "delivery_approved", "total_cost_usd", "total_latency_ms",
            }:
                raise RuntimeError("PostgreSQL trace audit columns are incomplete")
            await connection.execute(
                text("DELETE FROM lawagent_history WHERE session_id=:session_id"),
                {"session_id": session_id},
            )
    finally:
        await repository.close()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{test_schema}" CASCADE'))
        await admin_engine.dispose()

    print("PASS redis ping + adapter TTL/round-trip/delete")
    print("PASS postgres connect + schema + transaction/round-trip/cleanup")
    print("PASS postgres trace audit filter columns")
    print("PASS postgres trace reuse round-trip/search/delete")


if __name__ == "__main__":
    asyncio.run(main())
