from __future__ import annotations

from pathlib import Path

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.store.sqlite import AsyncSqliteStore

from auto_value_agent.storage import LangGraphSessionStore


@pytest.mark.asyncio
async def test_langgraph_sqlite_session_restore_and_reset(tmp_path: Path) -> None:
    database_path = tmp_path / "state.db"
    store = LangGraphSessionStore(path=database_path)
    await store.open()
    try:
        assert isinstance(store.store, AsyncSqliteStore)
        assert isinstance(store.checkpointer, AsyncSqliteSaver)
        session = await store.get_or_create_session("telegram", "10:20")
        assert session.sample_id is None

        selected = await store.set_sample("telegram", "10:20", "demo-03")
        assert selected.sample_id == "demo-03"
        switched = await store.set_sample("telegram", "10:20", "demo-04")
        assert switched.thread_id == selected.thread_id
        stored_item = await store.store.aget(("sessions", "telegram"), "10:20")
        assert stored_item is not None
        assert stored_item.value["thread_id"] == switched.thread_id
    finally:
        await store.close()

    restored_store = LangGraphSessionStore(path=database_path)
    await restored_store.open()
    try:
        restored = await restored_store.get_or_create_session("telegram", "10:20")
        assert restored.thread_id == switched.thread_id
        assert restored.sample_id == "demo-04"

        await restored_store.reset("telegram", "10:20")
        replacement = await restored_store.get_or_create_session("telegram", "10:20")
        assert replacement.thread_id != selected.thread_id
        assert replacement.sample_id is None
    finally:
        await restored_store.close()
