import json

from services import bedrock_llm

SYSTEM_PROMPT = (
    "You are an SAP data migration expert who maps legacy source fields to SAP "
    "target fields. You are given one source field (name + description) and up "
    "to 3 candidate SAP target fields, each already scored by embedding "
    "similarity. Re-rank and re-score them using your own domain judgement. "
    'Respond with ONLY a JSON array of objects, best match first, each: '
    '{"sap_table": "...", "sap_field": "...", "confidence_score": <0-100 number>, '
    '"reasoning": "<20-30 words explaining why this SAP field matches the source field>"}. '
    "Include every candidate you were given, no more, no fewer. "
    "No markdown fences, no extra keys, no explanation outside the JSON array."
)


def rank_candidates(source_field: str, source_description: str | None, candidates: list[dict]) -> list[dict]:
    """
    candidates: [{sap_table, sap_field, target_description, table_description, embedding_score, datatype_match_score}]
    Returns the same candidates, re-ordered/re-scored, each with added
    confidence_score (0-100) and reasoning (~20-30 words).
    """
    user_payload = {
        "source_field": source_field,
        "source_description": source_description or "",
        "candidates": [{
            "sap_table": c["sap_table"],
            "sap_field": c["sap_field"],
            "description": c.get("target_description") or "",
            "table_description": c.get("table_description") or "",
            "embedding_similarity": round(c["embedding_score"], 4),
        } for c in candidates],
    }

    raw = bedrock_llm.chat(
        SYSTEM_PROMPT,
        json.dumps(user_payload),
        max_tokens=600,
    )
    raw = bedrock_llm.strip_markdown_fences(raw)
    ranked = json.loads(raw)

    by_key = {(c["sap_table"], c["sap_field"]): c for c in candidates}
    out = []
    for r in ranked:
        base = by_key.get((r["sap_table"], r["sap_field"]))
        if base is None:
            continue
        out.append({
            "sap_table": r["sap_table"],
            "sap_field": r["sap_field"],
            "target_description": base.get("target_description"),
            "embedding_score": base["embedding_score"],
            "datatype_match_score": base.get("datatype_match_score"),
            "confidence_score": float(r["confidence_score"]),
            "reasoning": r["reasoning"],
        })

    if not out:
        raise ValueError("LLM returned no usable candidates")
    return out
