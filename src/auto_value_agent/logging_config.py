from __future__ import annotations

import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler
from zoneinfo import ZoneInfo

from auto_value_agent.config import Settings

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S %z"


class ZonedFormatter(logging.Formatter):
    def __init__(self, timezone: ZoneInfo, fmt: str, datefmt: str) -> None:
        super().__init__(fmt=fmt, datefmt=datefmt)
        self._timezone = timezone

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        timestamp = datetime.fromtimestamp(record.created, tz=self._timezone)
        return timestamp.strftime(datefmt) if datefmt else timestamp.isoformat()


def build_log_handlers(settings: Settings) -> list[logging.Handler]:
    settings.log_file_path.parent.mkdir(parents=True, exist_ok=True)
    formatter = ZonedFormatter(
        ZoneInfo(settings.log_timezone),
        LOG_FORMAT,
        LOG_DATE_FORMAT,
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        settings.log_file_path,
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    return [console_handler, file_handler]


def configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        handlers=build_log_handlers(settings),
        force=True,
    )
    # httpx logs full Telegram Bot API URLs, which contain the bot token.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
