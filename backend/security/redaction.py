"""Keep API keys out of logs and error messages.

redact() replaces any configured key value in a piece of text. protect_logs()
installs a log record factory so every log line in the process, including
error tracebacks, passes through redact() before any handler writes it.
"""

import logging
import traceback

from backend import config

REPLACEMENT = "[hidden key]"
_KEY_NAMES = ("OPENROUTER_API_KEY", "SERPAPI_API_KEY", "GOOGLE_MAPS_API_KEY")


def _secrets() -> list[str]:
    values = (getattr(config, name, "") for name in _KEY_NAMES)
    return [value for value in values if value and len(value) >= 8]


def redact(text: object) -> str:
    result = str(text)
    for secret in _secrets():
        result = result.replace(secret, REPLACEMENT)
    return result


def protect_logs() -> None:
    """Redact every log record when it is created. Safe to call more than once."""
    previous = logging.getLogRecordFactory()
    if getattr(previous, "redacts_secrets", False):
        return

    def factory(*args, **kwargs) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        record.msg, record.args = redact(record.getMessage()), ()
        if record.exc_info:
            record.exc_text = redact("".join(traceback.format_exception(*record.exc_info)).rstrip())
            record.exc_info = None
        return record

    factory.redacts_secrets = True
    logging.setLogRecordFactory(factory)
