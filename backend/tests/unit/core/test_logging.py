"""Tests for structured logging (spec 10 §3.7).

Why: the logs are how a stuck interview is diagnosed, and they must never carry what people wrote.
What: checks the JSON line, the correlation id and the refusal of text fields. AC-10.11, AC-10.12.
"""

import json
import logging

import pytest

from app.core.logging import JsonFormatter, correlation_id, log_event


def capture(caplog_records):
    return [json.loads(JsonFormatter().format(r)) for r in caplog_records]


def test_log_event_writes_one_json_line_with_its_fields(caplog):
    logger = logging.getLogger("app.test")
    token = correlation_id.set("abc-123")
    try:
        with caplog.at_level(logging.INFO, logger="app.test"):
            log_event(logger, "turn", phase="measure", asks=2)
    finally:
        correlation_id.reset(token)
    [line] = capture(caplog.records)
    assert line["msg"] == "turn"
    assert line["phase"] == "measure" and line["asks"] == 2
    assert line["correlationId"] == "abc-123"
    assert line["level"] == "INFO" and line["logger"] == "app.test"


@pytest.mark.parametrize("field", ["text", "message", "content"])
def test_text_fields_are_refused(field):
    """AC-10.12: what people wrote never reaches a log."""
    with pytest.raises(ValueError):
        log_event(logging.getLogger("app.test"), "turn", **{field: "secret words"})
