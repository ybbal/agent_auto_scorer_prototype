from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from conftest import FakeChatModel, FixedClock
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from auto_value_agent.agent import ConsultationAgent, build_compiled_agent
from auto_value_agent.config import Settings
from auto_value_agent.domain import AgentReplyDraft, Intent
from auto_value_agent.explanation import ExplanationPolicy
from auto_value_agent.mappings import FeatureMappingRepository
from auto_value_agent.repositories import CsvScoreRepository
from auto_value_agent.service import ConsultationService, NoVehicleSelectedError
from auto_value_agent.storage import LangGraphSessionStore


async def build_service(
    settings: Settings,
    tmp_path: Path,
    response: Any,
) -> tuple[ConsultationService, LangGraphSessionStore]:
    repository = CsvScoreRepository(
        csv_path=settings.score_csv_path,
        mappings=FeatureMappingRepository(path=settings.feature_mapping_path),
        clock=FixedClock(),
    )
    store = LangGraphSessionStore(path=tmp_path / "service.db")
    await store.open()
    agent = ConsultationAgent(
        compiled_agent=build_compiled_agent(
            FakeChatModel(response=response),
            checkpointer=store.checkpointer,
            store=store.store,
        )
    )
    service = ConsultationService(
        score_repository=repository,
        conversation_store=store,
        explanation_policy=ExplanationPolicy(max_factors_per_direction=3),
        agent=agent,
    )
    return service, store


@pytest.mark.asyncio
async def test_valid_model_reply_is_used(settings: Settings, tmp_path: Path) -> None:
    draft = AgentReplyDraft(
        intent=Intent.EXPLAIN,
        text="Текущая оценка — примерно 1 318 000 ₽.",
        action_ids=[],
    )
    service, store = await build_service(settings, tmp_path, draft)
    try:
        await service.select_sample("test", "user", "demo-03")
        response = await service.consult_selected(
            "test", "user", "Почему такая цена?", forced_intent=Intent.EXPLAIN
        )
        assert response.fallback_used is False
        assert response.text == draft.text
        assert response.actions == []
        session = await service.session("test", "user")
        config = RunnableConfig(configurable={"thread_id": session.thread_id})
        checkpoint = await store.checkpointer.aget_tuple(config)
        assert checkpoint is not None
        messages = checkpoint.checkpoint["channel_values"]["messages"]
        assert [type(message) for message in messages] == [HumanMessage, AIMessage]
        assert messages[0].content == "Почему такая цена?"
        assert messages[1].content == draft.text

        await service.reset("test", "user")
        assert await store.checkpointer.aget_tuple(config) is None
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_free_form_model_reply_is_used(settings: Settings, tmp_path: Path) -> None:
    draft = AgentReplyDraft(
        intent=Intent.UNSUPPORTED,
        text=(
            "VIN — это уникальный идентификатор автомобиля. "
            "Стоимость его проверки может составлять 1 000 ₽."
        ),
        action_ids=[],
    )
    service, store = await build_service(settings, tmp_path, draft)
    try:
        await service.select_sample("test", "free-form", "demo-03")
        response = await service.consult_selected(
            "test",
            "free-form",
            "Что такое VIN?",
        )
        assert response.intent is Intent.UNSUPPORTED
        assert response.fallback_used is False
        assert response.text == draft.text
        assert response.actions == []
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_invented_amount_triggers_grounded_fallback(
    settings: Settings, tmp_path: Path
) -> None:
    draft = AgentReplyDraft(
        intent=Intent.EXPLAIN,
        text="Текущая оценка — 9 999 000 ₽.",
        action_ids=[],
    )
    service, store = await build_service(settings, tmp_path, draft)
    try:
        await service.select_sample("test", "user", "demo-03")
        response = await service.consult_selected(
            "test", "user", "Почему такая цена?", forced_intent=Intent.EXPLAIN
        )
        assert response.fallback_used is True
        assert "1 318 000 ₽" in response.text
        assert "9 999 000" not in response.text
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_model_failure_and_missing_selection(settings: Settings, tmp_path: Path) -> None:
    service, store = await build_service(settings, tmp_path, RuntimeError("offline"))
    try:
        with pytest.raises(NoVehicleSelectedError):
            await service.consult_selected("test", "user", "Вопрос")
        await service.select_sample("test", "user", "demo-03")
        response = await service.consult_selected("test", "user", "Свободный вопрос")
        assert response.fallback_used is True
        assert "временно недоступен" in response.text
    finally:
        await store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("intent", "expected_text", "expected_actions"),
    [
        (Intent.EXPLAIN, "Повышающие модельные факторы", 0),
        (Intent.VEHICLE_FACTS, "Данные, использованные в оценке", 0),
        (Intent.DISAGREE, "может отличаться от ваших ожиданий", 0),
        (Intent.UPDATE_DATA, "первой версии пока недоступны", 0),
        (Intent.PRESERVE_VALUE, "GAP-страхование", 0),
        (Intent.UNSUPPORTED, "Не удалось сформировать свободный ответ", 0),
    ],
)
async def test_golden_button_fallback_scenarios(
    settings: Settings,
    tmp_path: Path,
    intent: Intent,
    expected_text: str,
    expected_actions: int,
) -> None:
    service, store = await build_service(settings, tmp_path, RuntimeError("offline"))
    try:
        await service.select_sample("test", intent.value, "demo-03")
        response = await service.consult_selected(
            "test",
            intent.value,
            "Кнопочный сценарий",
            forced_intent=intent,
        )
        assert response.intent is intent
        assert response.fallback_used is True
        assert expected_text in response.text
        assert len(response.actions) == expected_actions
    finally:
        await store.close()
