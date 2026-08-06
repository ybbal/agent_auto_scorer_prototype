from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager, suppress
from typing import Any

from dependency_injector.wiring import Provide, inject
from pydantic import SecretStr
from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonCommands,
    Update,
)
from telegram.constants import ChatAction
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from auto_value_agent.domain import ActionId, ConsultationResponse, Intent
from auto_value_agent.service import ConsultationService, NoVehicleSelectedError

LifecycleCallback = Callable[[Application], Coroutine[Any, Any, None]]

INTENT_LABELS = {
    Intent.EXPLAIN: "Почему такая стоимость?",
    Intent.VEHICLE_FACTS: "Какие данные использованы?",
    Intent.DISAGREE: "Не согласен с оценкой",
    Intent.UPDATE_DATA: "Как обновить данные?",
    Intent.PRESERVE_VALUE: "Как сохранить стоимость?",
}

INTENT_MESSAGES = {
    Intent.EXPLAIN: "Почему такая стоимость автомобиля?",
    Intent.VEHICLE_FACTS: "Какие данные использованы в оценке?",
    Intent.DISAGREE: "Не согласен с оценкой",
    Intent.UPDATE_DATA: "Как обновить данные об автомобиле?",
    Intent.PRESERVE_VALUE: "Как не потерять в стоимости автомобиля?",
}

ACTION_DEMO_TEXT = {
    ActionId.UPDATE_MILEAGE: "Демо обновления пробега запущено. Реальные данные не изменены.",
    ActionId.UPDATE_CONDITION: (
        "Демо уточнения технического состояния запущено. Реальные данные не изменены."
    ),
    ActionId.UPDATE_ACCIDENTS: (
        "Демо обновления сведений о ДТП запущено. Реальные данные не изменены."
    ),
}

BOT_COMMANDS = (
    BotCommand("start", "Запустить консультанта"),
    BotCommand("car", "Выбрать автомобиль"),
    BotCommand("help", "Показать справку"),
    BotCommand("reset", "Удалить сессию и историю"),
)


def _secret_value(value: SecretStr | str | None) -> str | None:
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    return value


class TelegramController:
    @staticmethod
    async def configure_bot_ui(application: Application) -> None:
        await application.bot.set_my_commands(BOT_COMMANDS)
        await application.bot.set_chat_menu_button(menu_button=MenuButtonCommands())

    @staticmethod
    def _session_key(update: Update) -> tuple[str, str]:
        if update.effective_chat is None or update.effective_user is None:
            raise RuntimeError("Telegram update has no chat or user")
        return "telegram", f"{update.effective_chat.id}:{update.effective_user.id}"

    @staticmethod
    def _intent_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(label, callback_data=f"intent:{intent.value}")]
                for intent, label in INTENT_LABELS.items()
            ]
        )

    @staticmethod
    def _response_keyboard(response: ConsultationResponse) -> InlineKeyboardMarkup | None:
        if not response.actions:
            return None
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(action.label, callback_data=f"action:{action.id.value}")]
                for action in response.actions
            ]
        )

    @staticmethod
    @asynccontextmanager
    async def _typing(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> AsyncIterator[None]:
        chat = update.effective_chat
        if chat is None:
            yield
            return

        async def pulse() -> None:
            while True:
                try:
                    await context.bot.send_chat_action(
                        chat_id=chat.id,
                        action=ChatAction.TYPING,
                    )
                except TelegramError:
                    return
                await asyncio.sleep(4)

        task = asyncio.create_task(pulse())
        await asyncio.sleep(0)
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    @staticmethod
    async def _show_car(update: Update, service: ConsultationService) -> None:
        samples = service.list_samples()
        keyboard = [
            [InlineKeyboardButton(sample.label, callback_data=f"sample:{sample.sample_id}")]
            for sample in samples
        ]
        if update.effective_message is not None:
            await update.effective_message.reply_text(
                "Выберите демонстрационный автомобиль:",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )

    @inject
    async def start(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        service: ConsultationService = Provide["consultation_service"],
    ) -> None:
        del context
        await service.session(*self._session_key(update))
        if update.effective_message is not None:
            await update.effective_message.reply_text(
                "Консультант по стоимости автомобиля на связи. Оценка ориентировочная. "
                "Выберите автомобиль."
            )
        await self._show_car(update, service)

    @inject
    async def car(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        service: ConsultationService = Provide["consultation_service"],
    ) -> None:
        del context
        await self._show_car(update, service)

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if update.effective_message is not None:
            await update.effective_message.reply_text(
                "/car — выбрать автомобиль\n/reset — удалить сессию\n"
                "После выбора используйте кнопки или задайте вопрос текстом."
            )

    @inject
    async def reset(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        service: ConsultationService = Provide["consultation_service"],
    ) -> None:
        del context
        await service.reset(*self._session_key(update))
        if update.effective_message is not None:
            await update.effective_message.reply_text("Сессия и история диалога удалены.")
        await self._show_car(update, service)

    @inject
    async def on_sample(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        service: ConsultationService = Provide["consultation_service"],
    ) -> None:
        del context
        query = update.callback_query
        if query is None or query.data is None:
            return
        await query.answer()
        sample_id = query.data.removeprefix("sample:")
        score = await service.select_sample(*self._session_key(update), sample_id)
        if update.effective_message is not None:
            await update.effective_message.reply_text(
                f"Выбран {score.display_name}, VIN {score.masked_vin}.",
                reply_markup=self._intent_keyboard(),
            )

    @inject
    async def on_intent(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        service: ConsultationService = Provide["consultation_service"],
    ) -> None:
        query = update.callback_query
        if query is None or query.data is None:
            return
        await query.answer()
        intent = Intent(query.data.removeprefix("intent:"))
        try:
            async with self._typing(update, context):
                response = await service.consult_selected(
                    *self._session_key(update),
                    INTENT_MESSAGES[intent],
                    forced_intent=intent,
                )
        except NoVehicleSelectedError:
            if update.effective_message is not None:
                await update.effective_message.reply_text(
                    "Сначала выберите автомобиль командой /car."
                )
            return
        if update.effective_message is not None:
            await update.effective_message.reply_text(
                response.text,
                reply_markup=self._response_keyboard(response) or self._intent_keyboard(),
            )

    async def on_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        query = update.callback_query
        if query is None or query.data is None:
            return
        await query.answer()
        action = ActionId(query.data.removeprefix("action:"))
        if update.effective_message is not None:
            await update.effective_message.reply_text(
                ACTION_DEMO_TEXT[action],
                reply_markup=self._intent_keyboard(),
            )

    @inject
    async def on_text(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        service: ConsultationService = Provide["consultation_service"],
    ) -> None:
        if update.effective_message is None or update.effective_message.text is None:
            return
        try:
            async with self._typing(update, context):
                response = await service.consult_selected(
                    *self._session_key(update),
                    update.effective_message.text,
                )
        except NoVehicleSelectedError:
            await update.effective_message.reply_text("Сначала выберите автомобиль командой /car.")
            return
        await update.effective_message.reply_text(
            response.text,
            reply_markup=self._response_keyboard(response) or self._intent_keyboard(),
        )

    @inject
    def build_application(
        self,
        token: SecretStr | str | None = Provide["config.telegram_bot_token"],
        timeout: float = Provide["config.telegram_timeout_seconds"],
        post_init: LifecycleCallback | None = None,
        post_shutdown: LifecycleCallback | None = None,
    ) -> Application:
        raw_token = _secret_value(token)
        if not raw_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
        builder = (
            Application.builder()
            .token(raw_token)
            .connect_timeout(timeout)
            .read_timeout(timeout)
            .write_timeout(timeout)
            .get_updates_connect_timeout(timeout)
            .get_updates_read_timeout(timeout)
        )
        if post_init is not None:
            builder = builder.post_init(post_init)
        if post_shutdown is not None:
            builder = builder.post_shutdown(post_shutdown)
        application = builder.build()
        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(CommandHandler("car", self.car))
        application.add_handler(CommandHandler("help", self.help))
        application.add_handler(CommandHandler("reset", self.reset))
        application.add_handler(CallbackQueryHandler(self.on_sample, pattern=r"^sample:"))
        application.add_handler(CallbackQueryHandler(self.on_intent, pattern=r"^intent:"))
        application.add_handler(CallbackQueryHandler(self.on_action, pattern=r"^action:"))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_text))
        return application

    def run(
        self,
        post_init: LifecycleCallback | None = None,
        post_shutdown: LifecycleCallback | None = None,
    ) -> None:
        self.build_application(
            post_init=post_init,
            post_shutdown=post_shutdown,
        ).run_polling(allowed_updates=Update.ALL_TYPES)
