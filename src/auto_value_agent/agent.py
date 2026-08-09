from __future__ import annotations

import base64
import json
import re
from typing import Any, TypedDict

from dependency_injector.wiring import Provide, inject
from langchain.agents import create_agent
from langchain.agents.middleware import ModelRequest, dynamic_prompt
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from pydantic import SecretStr

from auto_value_agent.domain import (
    AgentReplyDraft,
    ExplanationContext,
    Intent,
)
from auto_value_agent.explanation import round_thousand

SYSTEM_PROMPT = """Вы — русскоязычный консультант по модельной оценке автомобиля 
в приложении Сбербанк Онлайн.
C тобой разговаривает клиент Сбербанка. Обращайтесь к нему на вы.

Правила:
- Консультируйте по стоимости выбранного автомобиля только на основе марки, модели, года
  выпуска, пробега, мощности двигателя и модели двигателя из JSON-контекста.
- Всегда называйте пробег приблизительным. Не представляйте его как точное значение.
- Не упоминайте VIN, ДТП, регистрационные действия, владельцев, ПТС, такси, техническое
  состояние, объём двигателя, кузов, цвет или привод. Если эти сведения встречаются в старой
  истории диалога, игнорируйте их и не повторяйте.
- Не добавляйте сведения о выбранном автомобиле, которых нет в текущем JSON-контексте.
- Не называйте базовую цену модели и не утверждайте, что оценка сравнивается с аналогами.
- В ответах об оценке выбранного автомобиля денежные суммы копируйте из контекста без изменения.
- Для explain, disagree и vehicle_facts обязательно укажите текущую оценку из price_text.
- SHAP-вклады описывайте как поведение модели, а не как доказанную причинность.
- Учитывайте всю переданную историю. Короткие реплики «а ещё», «подробнее», «почему?» и
  местоимения продолжайте в смысле предыдущих сообщений.
- Если forced_intent задан, выполните выбранный клиентом сценарий: explain — объяснение
  оценки, vehicle_facts — использованные данные, disagree — работа с несогласием,
  preserve_value — советы по сохранению стоимости. Для update_data сообщите, что уточнение
  и обновление данных в первой версии недоступны.
- На остальные вопросы отвечайте свободно, используя общие знания, но не выдавайте ответ за
  персонализированный вывод о выбранном автомобиле.
- Пишите уважительно, на «вы».
- Для развернутых ответов предпочтительно использовать markdown.
"""

MONEY_PATTERN = re.compile(
    r"(?<!\d)(\d[\d \u00a0\u202f]*?)\s*(?:₽|руб(?:\.|лей|ля)?)",
    flags=re.IGNORECASE,
)


class ModelUnavailableError(RuntimeError):
    pass


class UnsafeModelReplyError(ValueError):
    def __init__(self, message: str, intent: Intent | None = None) -> None:
        super().__init__(message)
        self.intent = intent


def _secret_value(value: SecretStr | str | None) -> str | None:
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    return value


def normalize_gigachat_credentials(value: str) -> str:
    """Restore omitted Base64 padding when the value decodes to a client pair."""

    candidate = value + "=" * (-len(value) % 4)
    try:
        decoded = base64.b64decode(candidate, validate=True)
    except ValueError:
        return value
    return candidate if b":" in decoded else value


def build_chat_model(
    credentials: SecretStr | str | None,
    scope: str,
    model: str,
    verify_ssl_certs: bool,
    timeout: float,
) -> BaseChatModel | None:
    secret = _secret_value(credentials)
    if not secret:
        return None
    secret = normalize_gigachat_credentials(secret)
    from langchain_gigachat import GigaChat

    return GigaChat(
        credentials=secret,
        scope=scope,
        model=model,
        verify_ssl_certs=verify_ssl_certs,
        timeout=timeout,
        allow_any_tool_choice_fallback=True,
    )


class AgentRuntimeContext(TypedDict):
    forced_intent: str | None
    vehicle: dict[str, Any]


@dynamic_prompt
def consultation_system_prompt(request: ModelRequest[AgentRuntimeContext]) -> str:
    runtime_context = request.runtime.context
    dynamic_context = json.dumps(runtime_context, ensure_ascii=False)
    return f"{SYSTEM_PROMPT}\nТекущий контекст запроса:\n{dynamic_context}"


def build_compiled_agent(
    chat_model: BaseChatModel | None,
    checkpointer: Any | None = None,
    store: Any | None = None,
) -> Any | None:
    if chat_model is None:
        return None
    return create_agent(
        model=chat_model,
        tools=[],
        middleware=[consultation_system_prompt],
        context_schema=AgentRuntimeContext,
        checkpointer=checkpointer,
        store=store,
        name="auto_value_consultant",
    )


class ConsultationAgent:
    @inject
    def __init__(self, compiled_agent: Any | None = Provide["compiled_agent"]) -> None:
        self._compiled_agent = compiled_agent

    def _agent(self) -> Any:
        if self._compiled_agent is None:
            raise ModelUnavailableError("GIGACHAT_CREDENTIALS is not configured")
        return self._compiled_agent

    @staticmethod
    def _allowed_amounts(context: ExplanationContext) -> set[int]:
        values = {abs(int(round_thousand(context.price)))}
        for factor in context.positive_factors + context.negative_factors:
            values.add(abs(int(round_thousand(factor.contribution))))
        return values

    @staticmethod
    def _validate(
        draft: AgentReplyDraft,
        context: ExplanationContext,
        forced_intent: Intent | None,
    ) -> None:
        if forced_intent is not None and draft.intent is not forced_intent:
            raise UnsafeModelReplyError("Model changed the forced intent", draft.intent)

        allowed_actions = {action.id for action in context.allowed_actions}
        if any(action_id not in allowed_actions for action_id in draft.action_ids):
            raise UnsafeModelReplyError("Model returned an unknown action", draft.intent)
        if draft.action_ids:
            raise UnsafeModelReplyError(
                "Model returned actions, but actions are disabled",
                draft.intent,
            )

        returned_amounts = {
            int(re.sub(r"\D", "", match.group(1))) for match in MONEY_PATTERN.finditer(draft.text)
        }
        allowed_amounts = ConsultationAgent._allowed_amounts(context)
        if draft.intent is not Intent.UNSUPPORTED and not returned_amounts.issubset(
            allowed_amounts
        ):
            raise UnsafeModelReplyError(
                "Model invented or changed a monetary amount",
                draft.intent,
            )

        if draft.intent in {Intent.EXPLAIN, Intent.DISAGREE, Intent.VEHICLE_FACTS}:
            expected_price = abs(int(round_thousand(context.price)))
            if expected_price not in returned_amounts:
                raise UnsafeModelReplyError(
                    "Model omitted the current valuation",
                    draft.intent,
                )

    async def generate(
        self,
        message: str,
        context: ExplanationContext,
        forced_intent: Intent | None = None,
        thread_id: str | None = None,
    ) -> AgentReplyDraft:
        config = RunnableConfig(
            configurable={"thread_id": thread_id} if thread_id is not None else {}
        )
        runtime_context: AgentRuntimeContext = {
            "forced_intent": forced_intent.value if forced_intent else None,
            "vehicle": context.prompt_payload(),
        }
        result = await self._agent().ainvoke(
            {"messages": [HumanMessage(content=message)]},
            config=config,
            context=runtime_context,
        )
        response_messages = result.get("messages", [])
        response = next(
            (item for item in reversed(response_messages) if isinstance(item, AIMessage)),
            None,
        )
        if response is None or not str(response.text).strip():
            raise UnsafeModelReplyError("Agent returned an empty response", forced_intent)

        intent = forced_intent or Intent.UNSUPPORTED
        draft = AgentReplyDraft(
            intent=intent,
            text=str(response.text).strip(),
            action_ids=[],
        )
        self._validate(draft, context, forced_intent)
        return draft
