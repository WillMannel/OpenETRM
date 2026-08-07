"""Structured (JSON) logging with a per-request correlation id.

Every log line goes out as one JSON object (timestamp, level, logger name, message,
plus `request_id` when one is bound) so it's directly greppable/parseable by a log
aggregator -- the plain-text formatter this replaced was fine for a terminal, not for
anything downstream. `request_id_ctx` is set by app.core.middleware.RequestContextMiddleware
for the lifetime of a request and read here via a logging.Filter, so any log call made
anywhere during that request picks it up without threading a request object through
every function signature.
"""

import contextvars
import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

request_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None)
        if request_id is not None:
            payload["request_id"] = request_id
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(_JsonFormatter())
    handler.addFilter(_RequestIdFilter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
