from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from market_data_pipeline.config import LoggingConfig


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        for key, value in record.__dict__.items():
            if key.startswith("_") and key not in {"_event"}:
                continue
            if key in _RESERVED_LOG_RECORD_ATTRS:
                continue
            if key == "_event":
                payload["event"] = value
            elif _is_json_safe(value):
                payload[key] = value
            else:
                payload[key] = repr(value)

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, sort_keys=True)


def configure_logging(config: LoggingConfig) -> None:
    level = getattr(logging, config.level.upper(), logging.INFO)
    formatter: logging.Formatter
    if config.json:
        formatter = JsonFormatter()
    else:
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if config.file_path:
        config.file_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(config.file_path, encoding="utf-8"))

    for handler in handlers:
        handler.setFormatter(formatter)

    logging.basicConfig(level=level, handlers=handlers, force=True)


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    message: str,
    **fields: Any,
) -> None:
    logger.log(level, message, extra={"_event": event, **fields})


def _is_json_safe(value: Any) -> bool:
    try:
        json.dumps(value)
    except TypeError:
        return False
    return True


_RESERVED_LOG_RECORD_ATTRS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
}
