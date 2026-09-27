from __future__ import annotations

import json
import logging
import sys

import pytest

from dsec_metrics.logs import JsonFormatter, configure_logging, security_event


def test_json_formatter_includes_extra_fields() -> None:
    record = logging.makeLogRecord(
        {"name": "t", "levelname": "INFO", "msg": "hello %s", "args": ("world",), "event": "e1"}
    )
    payload = json.loads(JsonFormatter().format(record))
    assert payload["msg"] == "hello world"
    assert payload["event"] == "e1"
    assert payload["level"] == "info"
    assert payload["ts"].endswith("+00:00")


def test_exception_type_is_logged_without_traceback() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.makeLogRecord({"msg": "failed", "exc_info": sys.exc_info()})
    payload = json.loads(JsonFormatter().format(record))
    assert payload["exc_type"] == "ValueError"
    assert "Traceback" not in json.dumps(payload)


def test_security_event_goes_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    try:
        configure_logging("INFO")
        security_event(logging.getLogger("sec"), "login_failed", username="u")
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
    line = capsys.readouterr().out.strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["event"] == "login_failed"
    assert payload["username"] == "u"
