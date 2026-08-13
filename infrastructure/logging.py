"""Structured logging, shared by every application (api, worker, scraper).

Two guarantees this module exists to provide (spec §79): logs are structured
JSON, and sensitive values never reach them.

The redaction mechanism only covers what code can pass through it: log calls that
attach structured `extra={...}` data, and any dict passed through `redact()`
before being embedded in a message. It cannot rewrite an arbitrary interpolated
string like `logger.info(f"password is {password}")` — nothing can, short of
banning string interpolation outright. The actual guarantee is procedural: no code
in this project ever interpolates a credential into a log message, and `redact()`
is the tool that makes doing it correctly easier than doing it wrong when logging
a request body, a form payload, or any other dict of user-controlled data.
"""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

SENSITIVE_KEYS = frozenset(
    {
        "password",
        "password_hash",
        "token",
        "access_token",
        "refresh_token",
        "secret",
        "secret_key",
        "api_key",
        "authorization",
        "cookie",
        "session_id",
        "account_number",
        "telegram_bot_token",
    }
)
REDACTED = "***REDACTED***"


def redact(data: dict[str, Any]) -> dict[str, Any]:
    """Mask known-sensitive keys in a dict before it is logged. Recurses into
    nested dicts; leaves lists and scalars alone beyond that, which is enough for
    the request-body and config-dump shapes this is actually used on.
    """
    result: dict[str, Any] = {}
    for key, value in data.items():
        if key.lower() in SENSITIVE_KEYS:
            result[key] = REDACTED
        elif isinstance(value, dict):
            result[key] = redact(value)
        else:
            result[key] = value
    return result


class RedactingFilter(logging.Filter):
    """Masks sensitive keys carried in a LogRecord's structured `extra` fields.

    Standard LogRecord attributes (name, msg, levelname, ...) are left untouched;
    only attributes added via `extra=` are inspected, since those are where
    application code attaches structured data such as request payloads.
    """

    _standard_attrs = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None)))

    def filter(self, record: logging.LogRecord) -> bool:
        for key in list(vars(record)):
            if key in self._standard_attrs:
                continue
            value = getattr(record, key)
            if key.lower() in SENSITIVE_KEYS:
                setattr(record, key, REDACTED)
            elif isinstance(value, dict):
                setattr(record, key, redact(value))
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in vars(record).items():
            if key in RedactingFilter._standard_attrs or key in ("message", "asctime"):
                continue
            payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactingFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
