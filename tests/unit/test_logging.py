"""Verifies the redaction mechanism actually redacts (spec §79)."""

import json
import logging

from infrastructure.logging import REDACTED, JsonFormatter, RedactingFilter, redact


def test_redact_masks_known_sensitive_keys() -> None:
    data = {"username": "luca", "password": "hunter2", "nested": {"api_key": "abc123"}}
    result = redact(data)
    assert result["username"] == "luca"
    assert result["password"] == REDACTED
    assert result["nested"]["api_key"] == REDACTED


def test_redacting_filter_masks_extra_fields_on_log_records() -> None:
    logger = logging.getLogger("test.redaction")
    logger.setLevel(logging.INFO)
    logger.addFilter(RedactingFilter())

    formatter = JsonFormatter()
    record = logger.makeRecord(
        logger.name,
        logging.INFO,
        __file__,
        0,
        "login attempt",
        (),
        None,
        extra={"username": "luca", "password": "hunter2"},
    )
    for f in logger.filters:
        assert f.filter(record)
    formatted = json.loads(formatter.format(record))

    assert formatted["username"] == "luca"
    assert formatted["password"] == REDACTED
