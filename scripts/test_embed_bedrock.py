"""Live Cohere Embed v4 check against Bedrock.

Usage (from backend root, venv active):
    python scripts/test_embed_bedrock.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings
from services import embedding_service


def main() -> int:
    print("Cohere Embed v4 (Bedrock) live test")
    print("=" * 50)
    print("model:", settings.bedrock_embed_model_id)
    print("region:", settings.bedrock_region)
    print("embedding_backend:", settings.embedding_backend)
    print("using_bedrock:", embedding_service._use_bedrock())

    texts = [
        "Customer Name: legal name of the customer",
        "KNA1.NAME1: Name 1 of customer",
        "Order Date: date the sales order was created",
    ]
    try:
        matrix = embedding_service.embed_texts(texts)
    except Exception as exc:
        print("FAIL:", exc)
        return 1

    print("shape:", matrix.shape)
    sims = matrix @ matrix.T
    print("cosine name vs NAME1:     ", round(float(sims[0, 1]), 4))
    print("cosine name vs Order Date:", round(float(sims[0, 2]), 4))
    if sims[0, 1] <= sims[0, 2]:
        print("WARN: expected customer-name pair to be closer than name vs date")
    else:
        print("OK: related fields rank closer than unrelated ones")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
