from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from conftest import FakeChatModel, FixedClock
from dependency_injector import providers

from auto_value_agent.container import create_container
from auto_value_agent.domain import AgentReplyDraft, Intent, SampleSummary, VehicleScore
from auto_value_agent.storage import LangGraphSessionStore, init_conversation_store
from auto_value_agent.telegram import TelegramController


async def await_if_needed(value: object) -> object:
    if inspect.isawaitable(value):
        return await value
    return value


class InMemoryScoreRepository:
    def __init__(self, score: VehicleScore) -> None:
        self._score = score

    def get(self, sample_id: str) -> VehicleScore:
        if sample_id != self._score.sample_id:
            raise KeyError(sample_id)
        return self._score

    def list_samples(self) -> list[SampleSummary]:
        payload = self._score.payload
        return [
            SampleSummary(
                sample_id=self._score.sample_id,
                label=self._score.display_name,
                masked_vin=self._score.masked_vin,
                model_name=self._score.model_name,
                year=payload.year_production,
                market_price=payload.market_price,
            )
        ]


@pytest.mark.asyncio
async def test_container_scopes_resources_and_overrides(settings: object, tmp_path: Path) -> None:
    container = create_container(settings)  # type: ignore[arg-type]
    memory_repository = InMemoryScoreRepository(container.score_repository().get("demo-03"))
    fake_model = FakeChatModel(
        response=AgentReplyDraft(intent=Intent.UNSUPPORTED, text="fallback", action_ids=[])
    )
    container.clock.override(providers.Object(FixedClock()))
    container.chat_model.override(providers.Object(fake_model))
    container.score_repository.override(providers.Object(memory_repository))
    container.conversation_store.override(
        providers.Resource(init_conversation_store, path=tmp_path / "override.db")
    )

    store: object | None = None
    try:
        await await_if_needed(container.init_resources())
        store = await await_if_needed(container.conversation_store())
        assert isinstance(store, LangGraphSessionStore)
        assert store.is_open is True
        assert container.score_repository() is container.score_repository()
        compiled_one = await await_if_needed(container.compiled_agent())
        compiled_two = await await_if_needed(container.compiled_agent())
        assert compiled_one is compiled_two
        assert container.cli_controller() is not container.cli_controller()
        assert isinstance(container.telegram_controller(), TelegramController)
        service_one = await await_if_needed(container.consultation_service())
        service_two = await await_if_needed(container.consultation_service())
        assert service_one is not service_two
        assert service_one.list_samples()[0].sample_id == "demo-03"  # type: ignore[attr-defined]
    finally:
        await await_if_needed(container.shutdown_resources())
        if isinstance(store, LangGraphSessionStore):
            assert store.is_open is False
        container.unwire()


def test_telegram_application_builds_without_network() -> None:
    async def lifecycle_callback(_application: object) -> None:
        return None

    application = TelegramController().build_application(
        token="123456:TEST_TOKEN",
        timeout=30,
        post_init=lifecycle_callback,
        post_shutdown=lifecycle_callback,
    )
    assert application.bot.token == "123456:TEST_TOKEN"
    assert sum(len(group) for group in application.handlers.values()) == 7
    assert application.post_init is lifecycle_callback
    assert application.post_shutdown is lifecycle_callback


def test_provider_override_does_not_leak_to_a_new_container(settings: object) -> None:
    first = create_container(settings)  # type: ignore[arg-type]
    first.clock.override(providers.Object(FixedClock()))
    second = create_container(settings)  # type: ignore[arg-type]
    try:
        assert isinstance(first.clock(), FixedClock)
        assert not isinstance(second.clock(), FixedClock)
    finally:
        first.unwire()
        second.unwire()
