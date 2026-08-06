from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ConfigDict

from auto_value_agent.clock import Clock
from auto_value_agent.config import PROJECT_ROOT, Settings
from auto_value_agent.domain import AgentReplyDraft


class FixedClock(Clock):
    def today(self) -> date:
        return date(2026, 8, 6)


class FakeChatModel(BaseChatModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    response: Any

    @property
    def _llm_type(self) -> str:
        return "fake-chat"

    def _generate(
        self,
        messages: list[Any],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        del messages, stop, run_manager, kwargs
        if isinstance(self.response, Exception):
            raise self.response
        content = (
            self.response.text
            if isinstance(self.response, AgentReplyDraft)
            else str(self.response)
        )
        message = AIMessage(content=content)
        return ChatResult(generations=[ChatGeneration(message=message)])


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        state_db_path=tmp_path / "agent.db",
        score_csv_path=PROJECT_ROOT / "resources" / "sample_scores_table_auto_349653.csv",
        feature_mapping_path=PROJECT_ROOT / "resources" / "feature_mappings.json",
        gigachat_credentials=None,
        telegram_bot_token=None,
    )
