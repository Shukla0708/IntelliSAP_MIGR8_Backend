"""Text vectors for field matching.

Default: Cohere Embed v4 on Bedrock (`cohere.embed-v4:0`), same credential
path as Claude (BEDROCK_ACCESS_KEY or IAM). Falls back to local TF-IDF when
EMBEDDING_BACKEND=local or no Bedrock credentials are configured.

embed_texts(list[str]) -> (n, dim) float32 L2-normalized matrix.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from urllib.parse import quote

import certifi
import httpx
import numpy as np

from config import settings
from services.aws_client import (
    _has_bedrock_api_key,
    _has_explicit_credentials,
    get_bedrock_runtime_client,
)
from services import llm_cache, llm_usage

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_COHERE_BATCH = 96


def _use_bedrock() -> bool:
    backend = (settings.embedding_backend or "auto").lower()
    if backend == "local":
        return False
    if backend == "bedrock":
        return True
    return _has_bedrock_api_key() or _has_explicit_credentials()


def embed_texts(texts: list[str]) -> np.ndarray:
    """Returns an (n_texts, dim) float32 matrix (L2-normalized rows)."""
    if not texts:
        return np.empty((0, 0), dtype=np.float32)
    if _use_bedrock():
        return _embed_texts_cohere(texts)
    return _embed_texts_local(texts)


def _embed_texts_cohere(texts: list[str]) -> np.ndarray:
    model_id = settings.bedrock_embed_model_id
    cached, missing = llm_cache.get_embeddings(model_id, texts)
    if missing:
        to_embed = [texts[i] for i in missing]
        fresh = _embed_texts_cohere_uncached(to_embed)
        llm_cache.put_embeddings(model_id, to_embed, fresh)
        llm_usage.record(
            model_id=model_id,
            purpose="embed",
            input_tokens=sum(max(len(t), 1) for t in to_embed),
        )
        for idx, vec in zip(missing, fresh):
            cached[idx] = vec
    dim = next((v.shape[0] for v in cached if v is not None), 0)
    rows = []
    for vec in cached:
        if vec is None:
            rows.append(np.zeros(dim, dtype=np.float32))
        else:
            rows.append(vec)
    return np.vstack(rows) if rows else np.empty((0, 0), dtype=np.float32)


def _embed_texts_cohere_uncached(texts: list[str]) -> np.ndarray:
    chunks: list[np.ndarray] = []
    for start in range(0, len(texts), _COHERE_BATCH):
        batch = [t if (t or "").strip() else " " for t in texts[start : start + _COHERE_BATCH]]
        payload = {
            "texts": batch,
            "input_type": "search_document",
            "embedding_types": ["float"],
        }
        if _has_bedrock_api_key():
            data = _invoke_embed_via_api_key(payload)
        else:
            data = _invoke_embed_via_boto3(payload)
        vectors = _vectors_from_response(data)
        if len(vectors) != len(batch):
            raise ValueError(
                f"Cohere returned {len(vectors)} embeddings for {len(batch)} texts"
            )
        chunks.append(np.asarray(vectors, dtype=np.float32))
    matrix = np.vstack(chunks)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.maximum(norms, 1e-8)
    return matrix / norms


def _invoke_url() -> str:
    region = settings.bedrock_region
    model_id = quote(settings.bedrock_embed_model_id, safe="")
    return f"https://bedrock-runtime.{region}.amazonaws.com/model/{model_id}/invoke"


def _invoke_embed_via_api_key(payload: dict) -> dict:
    headers = {
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Authorization": f"Bearer {settings.bedrock_access_key.strip()}",
    }
    try:
        with httpx.Client(timeout=60.0, verify=certifi.where()) as client:
            resp = client.post(_invoke_url(), json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:500]
        raise ValueError(
            f"Bedrock embed error {exc.response.status_code} for model "
            f"{settings.bedrock_embed_model_id}: {body}"
        ) from exc
    except Exception as exc:
        raise ValueError(
            f"Bedrock embed failed for model {settings.bedrock_embed_model_id}: {exc}"
        ) from exc


def _invoke_embed_via_boto3(payload: dict) -> dict:
    client = get_bedrock_runtime_client()
    try:
        resp = client.invoke_model(
            modelId=settings.bedrock_embed_model_id,
            body=json.dumps(payload),
            accept="*/*",
            contentType="application/json",
        )
        return json.loads(resp["body"].read())
    except Exception as exc:
        raise ValueError(
            f"Bedrock embed failed for model {settings.bedrock_embed_model_id}: {exc}"
        ) from exc


def _vectors_from_response(data: dict) -> list[list[float]]:
    emb = data.get("embeddings")
    if isinstance(emb, dict):
        floats = emb.get("float")
        if floats:
            return floats
    if isinstance(emb, list) and emb:
        return emb
    raise ValueError(f"Unexpected Cohere embed response keys: {list(data)}")


def _tokenize(text: str) -> list[str]:
    text = (text or "").lower().replace("_", " ").replace(".", " ")
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text).lower()
    words = _TOKEN_RE.findall(text)
    tokens = list(words)
    compact = "".join(words)
    if len(compact) >= 3:
        tokens.extend(compact[i : i + 3] for i in range(len(compact) - 2))
    tokens.extend(f"{a}_{b}" for a, b in zip(words, words[1:]))
    return tokens


def _embed_texts_local(texts: list[str]) -> np.ndarray:
    """Character-trigram + word-bigram TF-IDF (offline fallback)."""
    docs = [_tokenize(t) for t in texts]
    df: Counter[str] = Counter()
    for toks in docs:
        df.update(set(toks))

    vocab = {tok: i for i, tok in enumerate(sorted(df))}
    n_docs = len(docs)
    dim = len(vocab)
    if dim == 0:
        return np.zeros((n_docs, 1), dtype=np.float32)

    matrix = np.zeros((n_docs, dim), dtype=np.float32)
    idf = np.zeros(dim, dtype=np.float32)
    for tok, idx in vocab.items():
        idf[idx] = np.log((1.0 + n_docs) / (1.0 + df[tok])) + 1.0

    for row, toks in enumerate(docs):
        if not toks:
            continue
        tf = Counter(toks)
        max_tf = max(tf.values())
        for tok, count in tf.items():
            idx = vocab[tok]
            matrix[row, idx] = (count / max_tf) * idf[idx]

    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.maximum(norms, 1e-8)
    return matrix / norms
