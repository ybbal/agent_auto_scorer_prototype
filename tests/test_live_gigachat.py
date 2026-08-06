from __future__ import annotations

from pathlib import Path

import pytest

from auto_value_agent.agent import ConsultationAgent, build_chat_model, build_compiled_agent
from auto_value_agent.clock import SystemClock
from auto_value_agent.config import Settings
from auto_value_agent.domain import Intent
from auto_value_agent.explanation import ExplanationPolicy
from auto_value_agent.mappings import FeatureMappingRepository
from auto_value_agent.repositories import CsvScoreRepository
from auto_value_agent.storage import LangGraphSessionStore


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_gigachat_response_with_history(tmp_path: Path) -> None:
    settings = Settings()
    if settings.gigachat_credentials is None:
        pytest.skip("GIGACHAT_CREDENTIALS is not configured")

    model = build_chat_model(
        settings.gigachat_credentials,
        settings.gigachat_scope,
        settings.gigachat_model,
        settings.gigachat_verify_ssl_certs,
        settings.gigachat_timeout_seconds,
    )
    assert model is not None
    repository = CsvScoreRepository(
        csv_path=settings.score_csv_path,
        mappings=FeatureMappingRepository(path=settings.feature_mapping_path),
        clock=SystemClock(),
    )
    context = ExplanationPolicy(
        max_factors_per_direction=settings.max_factors_per_direction
    ).context(
        repository.get("demo-03")
    )

    persistence = LangGraphSessionStore(path=tmp_path / "live.db")
    await persistence.open()
    try:
        response = await ConsultationAgent(
            compiled_agent=build_compiled_agent(
                model,
                checkpointer=persistence.checkpointer,
                store=persistence.store,
            )
        ).generate(
            "Почему такая стоимость?",
            context,
            forced_intent=Intent.EXPLAIN,
            thread_id="live-smoke-thread",
        )
    finally:
        await persistence.close()

    assert response.intent is Intent.EXPLAIN
    assert response.text


@pytest.mark.live
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "forced_intent"),
    [
        ("Почему так дешево оценили?", None),
        ("Не согласен с оценкой", Intent.DISAGREE),
    ],
)
async def test_live_gigachat_real_user_scenarios(
    message: str,
    forced_intent: Intent | None,
) -> None:
    settings = Settings()
    if settings.gigachat_credentials is None:
        pytest.skip("GIGACHAT_CREDENTIALS is not configured")
    model = build_chat_model(
        settings.gigachat_credentials,
        settings.gigachat_scope,
        settings.gigachat_model,
        settings.gigachat_verify_ssl_certs,
        settings.gigachat_timeout_seconds,
    )
    assert model is not None
    repository = CsvScoreRepository(
        csv_path=settings.score_csv_path,
        mappings=FeatureMappingRepository(path=settings.feature_mapping_path),
        clock=SystemClock(),
    )
    context = ExplanationPolicy(
        max_factors_per_direction=settings.max_factors_per_direction
    ).context(repository.get("demo-04"))

    response = await ConsultationAgent(compiled_agent=build_compiled_agent(model)).generate(
        message,
        context,
        forced_intent=forced_intent,
    )

    assert response.intent is (forced_intent or Intent.UNSUPPORTED)
    assert response.text


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_gigachat_answers_general_question() -> None:
    settings = Settings()
    if settings.gigachat_credentials is None:
        pytest.skip("GIGACHAT_CREDENTIALS is not configured")
    model = build_chat_model(
        settings.gigachat_credentials,
        settings.gigachat_scope,
        settings.gigachat_model,
        settings.gigachat_verify_ssl_certs,
        settings.gigachat_timeout_seconds,
    )
    assert model is not None
    repository = CsvScoreRepository(
        csv_path=settings.score_csv_path,
        mappings=FeatureMappingRepository(path=settings.feature_mapping_path),
        clock=SystemClock(),
    )
    context = ExplanationPolicy(
        max_factors_per_direction=settings.max_factors_per_direction
    ).context(repository.get("demo-04"))

    response = await ConsultationAgent(compiled_agent=build_compiled_agent(model)).generate(
        "Как подготовить автомобиль к дальней поездке?",
        context,
    )

    assert response.intent is Intent.UNSUPPORTED
    assert len(response.text) > 20


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_gigachat_understands_short_follow_up(tmp_path: Path) -> None:
    settings = Settings()
    if settings.gigachat_credentials is None:
        pytest.skip("GIGACHAT_CREDENTIALS is not configured")
    model = build_chat_model(
        settings.gigachat_credentials,
        settings.gigachat_scope,
        settings.gigachat_model,
        settings.gigachat_verify_ssl_certs,
        settings.gigachat_timeout_seconds,
    )
    assert model is not None
    repository = CsvScoreRepository(
        csv_path=settings.score_csv_path,
        mappings=FeatureMappingRepository(path=settings.feature_mapping_path),
        clock=SystemClock(),
    )
    context = ExplanationPolicy(
        max_factors_per_direction=settings.max_factors_per_direction
    ).context(repository.get("demo-02"))
    persistence = LangGraphSessionStore(path=tmp_path / "follow-up.db")
    await persistence.open()
    try:
        agent = ConsultationAgent(
            compiled_agent=build_compiled_agent(
                model,
                checkpointer=persistence.checkpointer,
                store=persistence.store,
            )
        )
        first = await agent.generate(
            "Почему такая стоимость?",
            context,
            forced_intent=Intent.EXPLAIN,
            thread_id="follow-up-thread",
        )
        second = await agent.generate(
            "А ещё?",
            context,
            thread_id="follow-up-thread",
        )
    finally:
        await persistence.close()

    assert first.intent is Intent.EXPLAIN
    assert second.intent is Intent.UNSUPPORTED
    assert second.text
    assert "не поддерживается" not in second.text.casefold()
