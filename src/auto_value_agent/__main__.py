from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable
from typing import Any

import typer
from dependency_injector.wiring import Provide, inject
from rich.console import Console

from auto_value_agent.cli import CliController
from auto_value_agent.config import Settings
from auto_value_agent.container import ApplicationContainer, create_container
from auto_value_agent.logging_config import configure_logging
from auto_value_agent.repositories import CsvScoreRepository
from auto_value_agent.telegram import TelegramController

app = typer.Typer(no_args_is_help=True, help="Консультант по стоимости автомобиля")


async def _await_if_needed(value: Awaitable[Any] | Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _init_resources(container: ApplicationContainer) -> None:
    await _await_if_needed(container.init_resources())


async def _shutdown_resources(container: ApplicationContainer) -> None:
    await _await_if_needed(container.shutdown_resources())


@inject
async def _run_cli(controller: CliController = Provide["cli_controller"]) -> None:
    await controller.run()


@inject
def _validate_data(
    repository: CsvScoreRepository = Provide["score_repository"],
    console: Console = Provide["console"],
) -> None:
    report = repository.validate()
    console.print_json(data=report.model_dump(mode="json"))


@app.command("cli")
def cli_command() -> None:
    """Run an interactive terminal consultation."""

    container = create_container()

    async def runner() -> None:
        await _init_resources(container)
        try:
            await _run_cli()
        finally:
            await _shutdown_resources(container)

    try:
        asyncio.run(runner())
    finally:
        container.unwire()


@app.command("telegram")
def telegram_command() -> None:
    """Run the Telegram bot using long polling."""

    container = create_container()
    controller: TelegramController = container.telegram_controller()

    async def post_init(application: Any) -> None:
        await _init_resources(container)
        await controller.configure_bot_ui(application)

    async def post_shutdown(_application: Any) -> None:
        await _shutdown_resources(container)

    try:
        controller.run(post_init=post_init, post_shutdown=post_shutdown)
    finally:
        container.unwire()


@app.command("validate-data")
def validate_data_command() -> None:
    """Validate the supplied model export and print a compact report."""

    container = create_container()
    try:
        _validate_data()
    finally:
        container.unwire()


def main() -> None:
    configure_logging(Settings())
    app()


if __name__ == "__main__":
    main()
