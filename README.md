# Auto Value Agent

Прототип русскоязычного агента-консультанта по модельной стоимости автомобиля.
Одна бизнес-логика используется терминальным интерфейсом и Telegram-ботом. Оценки
берутся из демонстрационного CSV, а свободный текст обрабатывается GigaChat через
абстракцию LangChain `BaseChatModel`.

## Ограничения прототипа

- Оценка ориентировочная и не является предложением о покупке или продаже.
- История оценок, прогноз стоимости, RAG и реальное обновление данных не реализованы.
- Технического состояния нет во входной выгрузке, поэтому агент его не придумывает.
- `expected_value` и `shap_diff` сохраняются как в исходном CSV. Из-за несходимости
  SHAP-база не показывается клиенту.
- Telegram-бот открыт всем и не имеет rate limit.
- Проверка TLS GigaChat намеренно отключена в согласованном локальном прототипе.
  Такой режим нельзя использовать в production.

## Установка

```bash
uv python install 3.12
uv sync --all-groups
cp .env.example .env
```

Заполните в `.env` как минимум:

```dotenv
GIGACHAT_CREDENTIALS=<authorization-key>
GIGACHAT_SCOPE=GIGACHAT_API_CORP
GIGACHAT_MODEL=GigaChat-2
GIGACHAT_VERIFY_SSL_CERTS=false
TELEGRAM_BOT_TOKEN=<telegram-token>
```

Справочник для runtime уже находится в `resources/feature_mappings.json`. Повторная
безопасная конвертация исходного PKL выполняется командой:

```bash
uv run python scripts/export_feature_mappings.py \
  resources/feature_mappings_extended_20260619_142008.pkl \
  resources/feature_mappings.json
```

## Запуск

```bash
uv run auto-value-agent validate-data
uv run auto-value-agent cli
uv run auto-value-agent telegram
```

В CLI доступны `/car`, `/reset`, `/help`, `/exit` и сценарии `1`–`5`. Telegram
поддерживает `/start`, `/car`, `/help`, `/reset`, inline-выбор автомобиля и
демонстрационные callbacks обновления данных. Markdown в ответах преобразуется в
безопасный Telegram HTML; при ошибке разметки бот автоматически отправляет plain text.

Без `GIGACHAT_CREDENTIALS` кнопочные сценарии продолжают работать через безопасные
шаблоны, а свободный вопрос получает сообщение о временной недоступности модели.

Логи одновременно выводятся в терминал и записываются в `var/logs/agent.log`.
По умолчанию файл ротируется при достижении 10 МБ, хранится до пяти архивов.
Параметры `LOG_LEVEL`, `LOG_FILE_PATH`, `LOG_TIMEZONE`, `LOG_MAX_BYTES` и
`LOG_BACKUP_COUNT` можно переопределить в `.env`. По умолчанию время записывается в
`Europe/Moscow` с явным смещением `+0300`. Telegram-запросы и ответы пишутся на уровне
`INFO` с `update_id` и Telegram `username`; числовые user/chat ID не логируются, полные
VIN маскируются. Для пользователей без username записывается `username=None`.

## Архитектура

Единый `ApplicationContainer` из `dependency-injector` содержит configuration,
singleton-репозитории, GigaChat, политику объяснений, compiled LangChain agent,
SQLite resource и factory-провайдеры сервисов/UI. Согласно принятому архитектурному
решению зависимости внедряются через `@inject` и строковые `Provide[...]` во всех
сервисах и обработчиках. В тестах providers заменяются через `.override()`.
Это сознательный компромисс прототипа: бизнес-сервисы напрямую зависят от wiring
API `dependency-injector`, поэтому замена DI-фреймворка потребует изменить эти модули.

Диалог обрабатывает один `create_agent` без `ToolStrategy` и ручной нормализации
истории. `AsyncSqliteSaver` передаёт ему полную последовательность обычных
`HumanMessage`/`AIMessage`, а актуальный контекст выбранного автомобиля добавляется
через динамический system prompt и не сохраняется отдельным сообщением на каждом ходе.

SQLite хранит сообщения, Telegram user/chat ID, LangChain thread ID и ID выбранного
демо-примера. `AsyncSqliteStore` содержит прикладную session mapping, а
`AsyncSqliteSaver` — LangGraph checkpoints и историю сообщений. Полный VIN и score
payload отдельно не сохраняются. `/reset` удаляет session и checkpoint thread.

## Проверки

```bash
uv run pytest
uv run ruff check .
uv run mypy src
uv build
```

Live-тесты по умолчанию исключены. При наличии реальных секретов и разрешённого
сетевого доступа они запускаются отдельно:

```bash
uv run pytest -m live tests/test_live_gigachat.py
```
