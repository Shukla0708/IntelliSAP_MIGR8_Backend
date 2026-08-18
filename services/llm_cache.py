"""Postgres cache for identical LLM prompts and embedding vectors."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy.orm import Session

from db.database import SessionLocal
from db.models import EmbeddingCache, LlmResponseCache

logger = logging.getLogger(__name__)
LLM_TTL_DAYS = 30


def prompt_hash(model_id: str, system: str, user: str) -> str:
    raw = f"{model_id}\n{system}\n{user}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def text_hash(model_id: str, text: str) -> str:
    return hashlib.sha256(f"{model_id}\n{text}".encode("utf-8")).hexdigest()


def get_llm(model_id: str, system: str, user: str) -> str | None:
    key = prompt_hash(model_id, system, user)
    db = SessionLocal()
    try:
        row = db.get(LlmResponseCache, key)
        if not row:
            return None
        cutoff = datetime.now(timezone.utc) - timedelta(days=LLM_TTL_DAYS)
        created = row.created_at
        if created and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if created and created < cutoff:
            db.delete(row)
            db.commit()
            return None
        return row.response_text
    except Exception:
        logger.exception("llm cache read failed")
        return None
    finally:
        db.close()


def put_llm(model_id: str, system: str, user: str, response_text: str) -> None:
    key = prompt_hash(model_id, system, user)
    db = SessionLocal()
    try:
        row = db.get(LlmResponseCache, key)
        if row:
            row.response_text = response_text
            row.model_id = model_id
        else:
            db.add(LlmResponseCache(
                prompt_hash=key,
                model_id=model_id,
                response_text=response_text,
            ))
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("llm cache write failed")
    finally:
        db.close()


def get_embeddings(model_id: str, texts: list[str]) -> tuple[list[np.ndarray | None], list[int]]:
    """Return cached vectors (or None) per text, plus indexes that still need embedding."""
    db = SessionLocal()
    found: list[np.ndarray | None] = [None] * len(texts)
    missing: list[int] = []
    try:
        for i, text in enumerate(texts):
            row = db.get(EmbeddingCache, text_hash(model_id, text))
            if row and isinstance(row.vector, list):
                found[i] = np.asarray(row.vector, dtype=np.float32)
            else:
                missing.append(i)
    except Exception:
        logger.exception("embedding cache read failed")
        return [None] * len(texts), list(range(len(texts)))
    finally:
        db.close()
    return found, missing


def put_embeddings(model_id: str, texts: list[str], vectors: np.ndarray) -> None:
    if vectors.size == 0:
        return
    db = SessionLocal()
    try:
        for text, vec in zip(texts, vectors):
            key = text_hash(model_id, text)
            payload = json.loads(json.dumps(vec.astype(float).tolist()))
            row = db.get(EmbeddingCache, key)
            if row:
                row.vector = payload
                row.model_id = model_id
            else:
                db.add(EmbeddingCache(text_hash=key, model_id=model_id, vector=payload))
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("embedding cache write failed")
    finally:
        db.close()
