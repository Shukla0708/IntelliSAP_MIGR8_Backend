import json
from groq import Groq
from config import settings

# Groq for now; swap for Claude Sonnet 4.5 / Sonnet 5 via Bedrock later by
# replacing rank_candidates()'s body while keeping its signature.
client = Groq(api_key=settings.groq_api_key)

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

    resp = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user_payload)},
        ],
        temperature=0,
        max_tokens=600,
    )
    raw = resp.choices[0].message.content.strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    ranked = json.loads(raw)

    by_key = {(c["sap_table"], c["sap_field"]): c for c in candidates}
    out = []
    for r in ranked:
        base = by_key.get((r["sap_table"], r["sap_field"]))
        if base is None:
            continue  # LLM hallucinated a table/field we never offered it
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
