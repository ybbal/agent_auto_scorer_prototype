from __future__ import annotations

import logging

from dependency_injector.wiring import Provide, inject

from auto_value_agent.agent import ConsultationAgent, UnsafeModelReplyError
from auto_value_agent.domain import (
    ConsultationRequest,
    ConsultationResponse,
    Intent,
    SampleSummary,
    Session,
    VehicleScore,
)
from auto_value_agent.explanation import ExplanationPolicy
from auto_value_agent.repositories import CsvScoreRepository
from auto_value_agent.storage import LangGraphSessionStore

LOGGER = logging.getLogger(__name__)


class NoVehicleSelectedError(RuntimeError):
    pass


class ConsultationService:
    @inject
    def __init__(
        self,
        score_repository: CsvScoreRepository = Provide["score_repository"],
        conversation_store: LangGraphSessionStore = Provide["conversation_store"],
        explanation_policy: ExplanationPolicy = Provide["explanation_policy"],
        agent: ConsultationAgent = Provide["compiled_agent"],
    ) -> None:
        self._scores = score_repository
        self._store = conversation_store
        self._policy = explanation_policy
        self._agent = agent

    def list_samples(self) -> list[SampleSummary]:
        return self._scores.list_samples()

    async def session(self, channel: str, external_id: str) -> Session:
        return await self._store.get_or_create_session(channel, external_id)

    async def select_sample(self, channel: str, external_id: str, sample_id: str) -> VehicleScore:
        score = self._scores.get(sample_id)
        await self._store.set_sample(channel, external_id, sample_id)
        return score

    async def reset(self, channel: str, external_id: str) -> None:
        await self._store.reset(channel, external_id)

    async def consult_selected(
        self,
        channel: str,
        external_id: str,
        message: str,
        forced_intent: Intent | None = None,
    ) -> ConsultationResponse:
        session = await self.session(channel, external_id)
        if session.sample_id is None:
            raise NoVehicleSelectedError("Select a demo vehicle first")
        score = self._scores.get(session.sample_id)
        return await self._consult(session, score, message, forced_intent)

    async def consult_payload(self, request: ConsultationRequest) -> ConsultationResponse:
        session = await self.session("http", request.session_id)
        score = self._scores.from_payload(request.score, sample_id="external")
        return await self._consult(session, score, request.message, forced_intent=None)

    async def _consult(
        self,
        session: Session,
        score: VehicleScore,
        message: str,
        forced_intent: Intent | None,
    ) -> ConsultationResponse:
        clean_message = message.strip()[:2000]
        context = self._policy.context(score)

        fallback_used = False
        try:
            draft = await self._agent.generate(
                clean_message,
                context,
                forced_intent,
                thread_id=session.thread_id,
            )
            intent = draft.intent
            text = draft.text
            catalog = {action.id: action for action in context.allowed_actions}
            actions = [catalog[action_id] for action_id in draft.action_ids]
        except Exception as error:  # the user-facing fallback must cover all provider failures
            LOGGER.warning(
                "LLM response failed; using a safe fallback: %s: %s",
                type(error).__name__,
                error,
            )
            fallback_used = True
            recoverable_intent = error.intent if isinstance(error, UnsafeModelReplyError) else None
            if forced_intent is None and recoverable_intent is not None:
                intent = recoverable_intent
                text = self._policy.fallback_text(intent, context)
                actions = self._policy.actions_for(intent)
            elif forced_intent is None:
                intent = Intent.UNSUPPORTED
                text = (
                    "Сервис формулирования ответа временно недоступен. "
                    "Попробуйте повторить вопрос позже."
                )
                actions = []
            else:
                intent = forced_intent
                text = self._policy.fallback_text(intent, context)
                actions = self._policy.actions_for(intent)

        return ConsultationResponse(
            text=text,
            actions=actions,
            score_date=score.payload.report_dt,
            fallback_used=fallback_used,
            intent=intent,
        )
