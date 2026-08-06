from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from uuid import uuid4

import aiosqlite
from dependency_injector.wiring import Provide, inject
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.store.sqlite import AsyncSqliteStore

from auto_value_agent.domain import Session


class LangGraphSessionStore:
    """Persistent app sessions backed by LangGraph Store and Checkpointer."""

    @inject
    def __init__(self, path: Path = Provide["config.state_db_path"]) -> None:
        self._path = Path(path)
        self._stack: AsyncExitStack | None = None
        self._store: AsyncSqliteStore | None = None
        self._checkpointer: AsyncSqliteSaver | None = None

    async def open(self) -> None:
        if self.is_open:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        stack = AsyncExitStack()
        try:
            store = await stack.enter_async_context(
                AsyncSqliteStore.from_conn_string(str(self._path))
            )
            checkpointer = await stack.enter_async_context(
                AsyncSqliteSaver.from_conn_string(str(self._path))
            )
            await store.setup()
            await checkpointer.setup()
            self._stack = stack
            self._store = store
            self._checkpointer = checkpointer
            await self._migrate_legacy_sessions()
        except Exception:
            await stack.aclose()
            self._stack = None
            self._store = None
            self._checkpointer = None
            raise

    async def close(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = None
        self._store = None
        self._checkpointer = None

    @property
    def is_open(self) -> bool:
        return self._store is not None and self._checkpointer is not None

    @property
    def store(self) -> AsyncSqliteStore:
        self._ensure_open()
        assert self._store is not None
        return self._store

    @property
    def checkpointer(self) -> AsyncSqliteSaver:
        self._ensure_open()
        assert self._checkpointer is not None
        return self._checkpointer

    def _ensure_open(self) -> None:
        if not self.is_open:
            raise RuntimeError("LangGraph persistence resource is not initialized")

    @staticmethod
    def _namespace(channel: str) -> tuple[str, ...]:
        return ("sessions", channel)

    async def _migrate_legacy_sessions(self) -> None:
        """Import session mappings from the prototype's former custom table once needed."""

        async with aiosqlite.connect(self._path) as connection:
            connection.row_factory = aiosqlite.Row
            cursor = await connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'sessions'"
            )
            if await cursor.fetchone() is None:
                return
            cursor = await connection.execute(
                "SELECT channel, external_id, thread_id, sample_id FROM sessions"
            )
            rows = await cursor.fetchall()

        for row in rows:
            channel = str(row["channel"])
            external_id = str(row["external_id"])
            namespace = self._namespace(channel)
            if await self.store.aget(namespace, external_id) is None:
                session = Session.model_validate(dict(row))
                await self.store.aput(
                    namespace,
                    external_id,
                    session.model_dump(mode="json"),
                    index=False,
                )

    async def get_or_create_session(self, channel: str, external_id: str) -> Session:
        namespace = self._namespace(channel)
        item = await self.store.aget(namespace, external_id)
        if item is not None:
            return Session.model_validate(item.value)

        session = Session(
            channel=channel,
            external_id=external_id,
            thread_id=str(uuid4()),
        )
        await self.store.aput(
            namespace,
            external_id,
            session.model_dump(mode="json"),
            index=False,
        )
        return session

    async def set_sample(self, channel: str, external_id: str, sample_id: str) -> Session:
        session = await self.get_or_create_session(channel, external_id)
        updated = session.model_copy(update={"sample_id": sample_id})
        await self.store.aput(
            self._namespace(channel),
            external_id,
            updated.model_dump(mode="json"),
            index=False,
        )
        return updated

    async def reset(self, channel: str, external_id: str) -> None:
        namespace = self._namespace(channel)
        item = await self.store.aget(namespace, external_id)
        if item is not None:
            session = Session.model_validate(item.value)
            await self.checkpointer.adelete_thread(session.thread_id)
        await self.store.adelete(namespace, external_id)
        await self._reset_legacy_session(channel, external_id)

    async def _reset_legacy_session(self, channel: str, external_id: str) -> None:
        """Honor /reset for data written by versions before LangGraph Store migration."""

        async with aiosqlite.connect(self._path) as connection:
            cursor = await connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name IN ('sessions', 'messages')"
            )
            tables = {str(row[0]) for row in await cursor.fetchall()}
            if "sessions" not in tables:
                return
            cursor = await connection.execute(
                "SELECT thread_id FROM sessions WHERE channel = ? AND external_id = ?",
                (channel, external_id),
            )
            row = await cursor.fetchone()
            if row is not None and "messages" in tables:
                await connection.execute(
                    "DELETE FROM messages WHERE thread_id = ?",
                    (row[0],),
                )
            await connection.execute(
                "DELETE FROM sessions WHERE channel = ? AND external_id = ?",
                (channel, external_id),
            )
            await connection.commit()


@asynccontextmanager
@inject
async def init_conversation_store(
    path: Path = Provide["config.state_db_path"],
) -> AsyncIterator[LangGraphSessionStore]:
    store = LangGraphSessionStore(path=path)
    await store.open()
    try:
        yield store
    finally:
        await store.close()
