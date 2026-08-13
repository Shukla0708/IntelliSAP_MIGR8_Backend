import numpy as np
from services import embedding_service, datatype_matcher

TOP_K = 3


def _cosine_sim_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a_norm = a / np.linalg.norm(a, axis=1, keepdims=True)
    b_norm = b / np.linalg.norm(b, axis=1, keepdims=True)
    return a_norm @ b_norm.T


def top_candidates(source_fields: list[dict], target_fields: list[dict], top_k: int = TOP_K) -> list[dict]:
    """
    source_fields: [{field_name, description, key_field, datatype}]
    target_fields: [{sap_table, sap_field, description, table_description, datatype}]

    Returns one entry per source field, each with up to top_k target
    candidates ranked by raw embedding cosine similarity (pre-LLM).
    """
    source_texts = [f"{f['field_name']}: {f.get('description') or ''}".strip() for f in source_fields]
    target_texts = [
        f"{t['sap_table']}.{t['sap_field']}: {t.get('description') or ''}".strip() for t in target_fields
    ]

    all_emb = embedding_service.embed_texts(source_texts + target_texts)
    source_emb = all_emb[: len(source_texts)]
    target_emb = all_emb[len(source_texts) :]
    sims = _cosine_sim_matrix(source_emb, target_emb)

    k = min(top_k, len(target_fields))
    results = []
    for i, field in enumerate(source_fields):
        row = sims[i]
        top_idx = np.argsort(-row)[:k]
        candidates = [{
            "sap_table": target_fields[j]["sap_table"],
            "sap_field": target_fields[j]["sap_field"],
            "target_description": target_fields[j].get("description"),
            "table_description": target_fields[j].get("table_description"),
            "embedding_score": float(row[j]),
            "datatype_match_score": datatype_matcher.datatype_match_score(
                field.get("datatype"), target_fields[j].get("datatype")
            ),
        } for j in top_idx]
        results.append({
            "source_field": field["field_name"],
            "source_description": field.get("description"),
            "key_field": field.get("key_field", False),
            "datatype": field.get("datatype"),
            "candidates": candidates,
        })
    return results
