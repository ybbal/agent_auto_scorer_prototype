from __future__ import annotations

from dependency_injector import containers, providers
from rich.console import Console

from auto_value_agent.agent import ConsultationAgent, build_chat_model, build_compiled_agent
from auto_value_agent.cli import CliController
from auto_value_agent.clock import SystemClock
from auto_value_agent.config import Settings
from auto_value_agent.explanation import ExplanationPolicy
from auto_value_agent.mappings import FeatureMappingRepository
from auto_value_agent.repositories import CsvScoreRepository
from auto_value_agent.service import ConsultationService
from auto_value_agent.storage import init_conversation_store
from auto_value_agent.telegram import TelegramController


class ApplicationContainer(containers.DeclarativeContainer):
    wiring_config = containers.WiringConfiguration(
        packages=["auto_value_agent"],
        warn_unresolved=True,
    )

    config = providers.Configuration(strict=True)

    console = providers.Singleton(Console)
    clock = providers.Singleton(SystemClock)
    feature_mapping = providers.Singleton(
        FeatureMappingRepository,
        path=config.feature_mapping_path,
    )
    score_repository = providers.Singleton(
        CsvScoreRepository,
        csv_path=config.score_csv_path,
        mappings=feature_mapping,
        clock=clock,
    )
    conversation_store = providers.Resource(
        init_conversation_store,
        path=config.state_db_path,
    )
    chat_model = providers.Singleton(
        build_chat_model,
        credentials=config.gigachat_credentials,
        scope=config.gigachat_scope,
        model=config.gigachat_model,
        verify_ssl_certs=config.gigachat_verify_ssl_certs,
        timeout=config.gigachat_timeout_seconds,
    )
    explanation_policy = providers.Singleton(
        ExplanationPolicy,
        max_factors_per_direction=config.max_factors_per_direction,
    )
    compiled_agent = providers.Singleton(
        build_compiled_agent,
        chat_model=chat_model,
        checkpointer=conversation_store.provided.checkpointer,
        store=conversation_store.provided.store,
    )
    consultation_agent = providers.Singleton(
        ConsultationAgent,
        compiled_agent=compiled_agent,
    )
    consultation_service = providers.Factory(
        ConsultationService,
        score_repository=score_repository,
        conversation_store=conversation_store,
        explanation_policy=explanation_policy,
        agent=consultation_agent,
    )
    cli_controller = providers.Factory(CliController)
    telegram_controller = providers.Factory(TelegramController)


def create_container(settings: Settings | None = None) -> ApplicationContainer:
    container = ApplicationContainer()
    runtime_settings = settings or Settings()
    container.config.from_pydantic(runtime_settings, required=True)
    return container
