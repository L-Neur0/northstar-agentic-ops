"""Structured JSON logging with a correlation id (spec 10 §3.7; product F-24).

Why: a stuck interview is diagnosed from the logs (one line per turn, spec 14), so log lines must
be machine-readable and tied to the request that produced them. The logs must also never carry
what an expert said or uploaded: that is personal and business content.
What: `JsonFormatter` writes one JSON object per line; `correlation_id` holds the id of the
current request; `log_event` is the one way modules write structured events, and it refuses
fields that could hold text (`text`, `message`, `content`).
Must not: log message, document or profile text.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")

FORBIDDEN_FIELDS = frozenset({"text", "message", "content"})
_RESERVED = frozenset(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    """Format a record as one JSON line: ts, level, logger, msg, correlationId and extra fields."""

    def format(self, record: logging.LogRecord) -> str:
        line: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "correlationId": getattr(record, "correlationId", None) or correlation_id.get(),
        }
        for key, value in vars(record).items():
            if key not in _RESERVED and key != "correlationId" and not key.startswith("_"):
                line[key] = value
        if record.exc_info:
            line["error"] = self.formatException(record.exc_info)
        return json.dumps(line, default=str, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    """JSON lines on stdout; `app.*` at `level`, libraries at WARNING."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.WARNING)
    logging.getLogger("app").setLevel(level)


def log_event(logger: logging.Logger, event: str, **fields: object) -> None:
    """Write one structured event. Raises `ValueError` on a field that could carry text."""
    bad = FORBIDDEN_FIELDS.intersection(fields)
    if bad:
        raise ValueError(f"log fields {sorted(bad)} could carry user text; log counts or ids instead")
    logger.info(event, extra={"correlationId": correlation_id.get(), **fields})
