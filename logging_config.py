"""JSON structured logs for CloudWatch. No JWTs, passwords, file bytes, or SAP secrets."""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

_REDACT_KEYS = {
    "authorization",
    "cookie",
    "password",
    "password_hash",
    "token",
    "jwt",
    "secret",
    "bedrock_access_key",
    "aws_secret_access_key",
    "aws_access_key_id",
    "sap_password",
    "sap_user",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in (
            "request_id",
            "user_id",
            "route",
            "duration_ms",
            "error_code",
            "job_id",
            "model",
            "input_tokens",
            "output_tokens",
            "estimated_usd",
            "cache_hit",
            "latency_ms",
        ):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
        return json.dumps(payload, default=str)


def configure_logging(*, json_logs: bool = True) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if json_logs else logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    ))
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def extra(**fields: Any) -> dict[str, Any]:
    return {"extra": {k: v for k, v in fields.items() if v is not None}}
