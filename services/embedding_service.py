"""Local text vectors for field matching — no model download / no HF SSL.

Uses character + word n-gram TF-IDF with numpy only. Swap back to
fastembed / Cohere later by replacing embed_texts() while keeping the signature.
"""
from __future__ import annotations

import re
from collections import Counter

import numpy as np

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    text = (text or "").lower().replace("_", " ").replace(".", " ")
    # Split CamelCase: CustomerName -> customer name
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text).lower()
    words = _TOKEN_RE.findall(text)
    tokens = list(words)
    # char trigrams help fuzzy field-name matches
    compact = "".join(words)
    if len(compact) >= 3:
        tokens.extend(compact[i : i + 3] for i in range(len(compact) - 2))
    # word bigrams
    tokens.extend(f"{a}_{b}" for a, b in zip(words, words[1:]))
    return tokens


def embed_texts(texts: list[str]) -> np.ndarray:
    """Returns an (n_texts, dim) float32 TF-IDF matrix (L2-normalized rows)."""
    if not texts:
        return np.empty((0, 0), dtype=np.float32)

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
