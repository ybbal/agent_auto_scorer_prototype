from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from conftest import FixedClock

from auto_value_agent.config import Settings
from auto_value_agent.domain import ConsultationResponse, Intent
from auto_value_agent.mappings import FeatureMappingRepository
from auto_value_agent.repositories import CsvScoreRepository
from auto_value_agent.telegram import BOT_COMMANDS, TelegramController


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
async def test_reset_callback(settings: Settings) -> None:
    controller = TelegramController()
    service = MagicMock()
    service.reset = AsyncMock()
    service.list_samples.return_value = repository(settings).list_samples()
    message = SimpleNamespace(reply_text=AsyncMock())
    reset_update = SimpleNamespace(
        callback_query=None,
        effective_message=message,
        effective_chat=SimpleNamespace(id=10),
        effective_user=SimpleNamespace(id=20, username="test_user"),
    )

    await controller.reset(reset_update, object(), service=service)

    service.reset.assert_awaited_once_with("telegram", "10:20")
    assert message.reply_text.await_count == 2


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


def test_intent_keyboard_has_no_update_or_clarification_buttons() -> None:
    keyboard = TelegramController._intent_keyboard()
    buttons = [button for row in keyboard.inline_keyboard for button in row]

    assert [button.callback_data for button in buttons] == [
        "intent:explain",
        "intent:vehicle_facts",
        "intent:disagree",
        "intent:preserve_value",
    ]
    assert not any("обнов" in button.text.lower() for button in buttons)
    assert not any("уточ" in button.text.lower() for button in buttons)


@pytest.mark.asyncio
async def test_text_request_and_response_are_logged_with_masked_vin(
    caplog: pytest.LogCaptureFixture,
) -> None:
    controller = TelegramController()
    full_vin = "WVWZZZ1JZXW000001"
    response = ConsultationResponse(
        text=f"Проверен VIN {full_vin}.",
        score_date="2026-06-30",
        intent=Intent.UNSUPPORTED,
    )
    service = MagicMock()
    service.consult_selected = AsyncMock(return_value=response)
    message = SimpleNamespace(
        text=f"Проверьте VIN {full_vin}",
        reply_text=AsyncMock(),
    )
    update = SimpleNamespace(
        update_id=123,
        callback_query=None,
        effective_message=message,
        effective_chat=SimpleNamespace(id=10),
        effective_user=SimpleNamespace(id=20, username="test_user"),
    )
    context = SimpleNamespace(bot=SimpleNamespace(send_chat_action=AsyncMock()))
    caplog.set_level(logging.INFO, logger="auto_value_agent.telegram")

    await controller.on_text(update, context, service=service)

    assert "telegram request update_id=123 username=@test_user kind=text" in caplog.text
    assert (
        "telegram response update_id=123 username=@test_user intent=unsupported"
        in caplog.text
    )
    assert "user_id=" not in caplog.text
    assert full_vin not in caplog.text
    assert "WVW***0001" in caplog.text
