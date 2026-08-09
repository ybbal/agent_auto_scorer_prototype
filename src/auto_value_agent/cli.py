from __future__ import annotations

from dependency_injector.wiring import Provide, inject
from rich.console import Console
from rich.table import Table

from auto_value_agent.domain import Intent
from auto_value_agent.service import ConsultationService, NoVehicleSelectedError

SHORTCUTS = {
    "1": (Intent.EXPLAIN, "Почему такая стоимость автомобиля?"),
    "2": (Intent.VEHICLE_FACTS, "Какие данные использованы в оценке?"),
    "3": (Intent.DISAGREE, "Не согласен с оценкой"),
    "4": (Intent.PRESERVE_VALUE, "Как не потерять в стоимости автомобиля?"),
}

HELP_TEXT = """Команды:
  /car    выбрать другой автомобиль
  /reset  удалить текущую локальную сессию
  /help   показать справку
  /exit   выйти

Сценарии: 1 — объяснение, 2 — данные, 3 — несогласие, 4 — советы.
Любой другой текст отправляется в GigaChat как свободный вопрос."""


class CliController:
    @staticmethod
    def _session_id() -> tuple[str, str]:
        return "cli", "local"

    @inject
    async def _choose_vehicle(
        self,
        service: ConsultationService = Provide["consultation_service"],
        console: Console = Provide["console"],
    ) -> None:
        table = Table(title="Демонстрационные автомобили")
        table.add_column("№", justify="right")
        table.add_column("Автомобиль")
        table.add_column("VIN")
        samples = service.list_samples()
        for index, sample in enumerate(samples, start=1):
            table.add_row(str(index), sample.label, sample.masked_vin)
        console.print(table)
        while True:
            answer = console.input("Выберите номер: ").strip()
            if answer.isdigit() and 1 <= int(answer) <= len(samples):
                selected = samples[int(answer) - 1]
                score = await service.select_sample(*self._session_id(), selected.sample_id)
                console.print(f"Выбран: [bold]{score.display_name}[/bold], VIN {score.masked_vin}")
                return
            console.print("Введите номер из таблицы.", style="yellow")

    @inject
    async def run(
        self,
        service: ConsultationService = Provide["consultation_service"],
        console: Console = Provide["console"],
    ) -> None:
        console.print("[bold green]Консультант по стоимости автомобиля[/bold green]")
        console.print(
            "Оценка носит ориентировочный характер. "
            "TLS-проверка GigaChat отключена для прототипа."
        )
        session = await service.session(*self._session_id())
        if session.sample_id is None:
            await self._choose_vehicle()
        console.print(HELP_TEXT)

        while True:
            message = console.input("\n[bold cyan]Вы[/bold cyan]: ").strip()
            if not message:
                continue
            if message == "/exit":
                return
            if message == "/help":
                console.print(HELP_TEXT)
                continue
            if message == "/car":
                await self._choose_vehicle()
                continue
            if message == "/reset":
                await service.reset(*self._session_id())
                console.print("Сессия удалена. Выберите автомобиль заново.")
                await self._choose_vehicle()
                continue
            forced_intent, user_message = SHORTCUTS.get(message, (None, message))
            try:
                response = await service.consult_selected(
                    *self._session_id(),
                    user_message,
                    forced_intent=forced_intent,
                )
            except NoVehicleSelectedError:
                await self._choose_vehicle()
                continue
            console.print(f"\n[bold green]Консультант[/bold green]: {response.text}")
