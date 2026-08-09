from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

from auto_value_agent.config import Settings
from auto_value_agent.logging_config import build_log_handlers


def test_rotating_file_handler_writes_utf8_log(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "agent.log"
    settings = Settings(
        log_file_path=log_path,
        log_max_bytes=2048,
        log_backup_count=2,
    )
    handlers = build_log_handlers(settings)
    file_handler = next(
        handler for handler in handlers if isinstance(handler, RotatingFileHandler)
    )
    logger = logging.Logger("auto-value-agent-test", level=logging.INFO)
    logger.addHandler(file_handler)

    try:
        logger.info("Проверка файлового журнала")
        file_handler.flush()
        log_text = log_path.read_text(encoding="utf-8")
        assert "Проверка файлового журнала" in log_text
        assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \+0300", log_text)
        assert file_handler.maxBytes == 2048
        assert file_handler.backupCount == 2
    finally:
        for handler in handlers:
            handler.close()
