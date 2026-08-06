from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from conftest import FixedClock

from auto_value_agent.config import Settings
from auto_value_agent.domain import Action, ActionId, ConsultationResponse, Intent
from auto_value_agent.mappings import FeatureMappingRepository
from auto_value_agent.repositories import CsvScoreRepository
from auto_value_agent.telegram import ACTION_DEMO_TEXT, BOT_COMMANDS, TelegramController


def repository(settings: Settings) -> CsvScoreRepository:
    return CsvScoreRepository(
        csv_path=settings.score_csv_path,
        mappings=FeatureMappingRepository(path=settings.feature_mapping_path),
        clock=FixedClock(),
    )


@pytest.mark.asyncio
async def test_bot_ui_registers_commands_and_menu_button() -> None:
    bot = SimpleNamespace(
        set_my_commands=AsyncMock(),
        set_chat_menu_button=AsyncMock(),
    )

    await TelegramController.configure_bot_ui(SimpleNamespace(bot=bot))

    bot.set_my_commands.assert_awaited_once_with(BOT_COMMANDS)
    bot.set_chat_menu_button.assert_awaited_once()
    assert [command.command for command in BOT_COMMANDS] == ["start", "car", "help", "reset"]


@pytest.mark.asyncio
async def test_sample_callback_selects_vehicle(settings: Settings) -> None:
    controller = TelegramController()
    score = repository(settings).get("demo-03")
    service = MagicMock()
    service.select_sample = AsyncMock(return_value=score)
    query = SimpleNamespace(
        data="sample:demo-03",
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(
        callback_query=query,
        effective_message=message,
        effective_chat=SimpleNamespace(id=10),
        effective_user=SimpleNamespace(id=20),
    )

    await controller.on_sample(update, object(), service=service)

    service.select_sample.assert_awaited_once_with("telegram", "10:20", "demo-03")
    query.answer.assert_awaited_once()
    query.edit_message_text.assert_not_awaited()
    assert "JMB***3212" in message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_reset_and_action_callbacks(settings: Settings) -> None:
    controller = TelegramController()
    service = MagicMock()
    service.reset = AsyncMock()
    service.list_samples.return_value = repository(settings).list_samples()
    message = SimpleNamespace(reply_text=AsyncMock())
    reset_update = SimpleNamespace(
        callback_query=None,
        effective_message=message,
        effective_chat=SimpleNamespace(id=10),
        effective_user=SimpleNamespace(id=20),
    )

    await controller.reset(reset_update, object(), service=service)

    service.reset.assert_awaited_once_with("telegram", "10:20")
    assert message.reply_text.await_count == 2

    query = SimpleNamespace(
        data="action:update_mileage",
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    action_message = SimpleNamespace(reply_text=AsyncMock())
    action_update = SimpleNamespace(
        callback_query=query,
        effective_message=action_message,
    )
    await controller.on_action(action_update, object())
    query.edit_message_text.assert_not_awaited()
    assert (
        action_message.reply_text.await_args.args[0]
        == ACTION_DEMO_TEXT[ActionId.UPDATE_MILEAGE]
    )


@pytest.mark.asyncio
async def test_intent_callback_replies_below_with_typing_action() -> None:
    controller = TelegramController()
    response = ConsultationResponse(
        text="Новый ответ",
        score_date="2026-06-30",
        intent=Intent.EXPLAIN,
    )
    service = MagicMock()
    service.consult_selected = AsyncMock(return_value=response)
    query = SimpleNamespace(
        data="intent:explain",
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(
        callback_query=query,
        effective_message=message,
        effective_chat=SimpleNamespace(id=10),
        effective_user=SimpleNamespace(id=20),
    )
    bot = SimpleNamespace(send_chat_action=AsyncMock())
    context = SimpleNamespace(bot=bot)

    await controller.on_intent(update, context, service=service)

    bot.send_chat_action.assert_awaited_once_with(chat_id=10, action="typing")
    query.edit_message_text.assert_not_awaited()
    assert message.reply_text.await_args.args[0] == "Новый ответ"


def test_response_actions_keep_shared_business_ids() -> None:
    response = ConsultationResponse(
        text="Ответ",
        actions=[Action(id=ActionId.UPDATE_ACCIDENTS, label="Обновить информацию о ДТП")],
        score_date="2026-06-30",
        intent=Intent.UPDATE_DATA,
    )
    keyboard = TelegramController._response_keyboard(response)

    assert keyboard is not None
    assert keyboard.inline_keyboard[0][0].callback_data == "action:update_accidents"
