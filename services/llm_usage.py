"""Persist Bedrock token counts for the admin spend view. Never stores prompts."""
from __future__ import annotations

import logging
from decimal import Decimal
from uuid import UUID

from db.database import SessionLocal
from db.models import LlmUsageLog
from logging_config import extra

logger = logging.getLogger("migr8.llm")

# Rough on-demand USD / 1M tokens (Sonnet 5 + Haiku 4.5 ballpark; override later).
_RATES = {
    "sonnet": (Decimal("3.00"), Decimal("15.00")),
    "haiku": (Decimal("0.80"), Decimal("4.00")),
    "embed": (Decimal("0.10"), Decimal("0.00")),
}


def _rate_for(model_id: str) -> tuple[Decimal, Decimal]:
    mid = (model_id or "").lower()
    if "haiku" in mid:
        return _RATES["haiku"]
    if "embed" in mid or "cohere" in mid:
        return _RATES["embed"]
    return _RATES["sonnet"]


def estimate_usd(model_id: str, input_tokens: int, output_tokens: int) -> Decimal:
    inp, out = _rate_for(model_id)
    return (Decimal(input_tokens) * inp + Decimal(output_tokens) * out) / Decimal(1_000_000)


def record(
    *,
    model_id: str,
    purpose: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    latency_ms: int = 0,
    cache_hit: bool = False,
    user_id: UUID | str | None = None,
) -> None:
    usd = estimate_usd(model_id, input_tokens, output_tokens)
    logger.info(
        "llm_call",
        **extra(
            model=model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            estimated_usd=float(usd),
            cache_hit=cache_hit,
        ),
    )
    db = SessionLocal()
    try:
        uid = UUID(str(user_id)) if user_id else None
        db.add(LlmUsageLog(
            user_id=uid,
            purpose=purpose,
            model_id=model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            cache_hit=cache_hit,
            estimated_usd=usd,
        ))
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("could not persist llm usage")
    finally:
        db.close()
