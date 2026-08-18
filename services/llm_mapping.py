import json

from config import settings
from services import bedrock_llm

HIGH_CONFIDENCE = 0.92
BATCH_SIZE = 20

SYSTEM_PROMPT = (
    "You are an SAP data migration expert who maps legacy source fields to SAP "
    "target fields. You are given several source fields. Each has up to 3 candidate "
    "SAP target fields, already scored by embedding similarity. Re-rank and re-score "
    "them using your own domain judgement. "
    "Candidate 1 is highest priority when marked preferred_org_standard; prefer it "
    "unless datatype or the field clearly contradicts it. "
    "Reasoning must be <=12 words. "
    'Respond with ONLY a JSON object: {"results":[{"source_field":"...",'
    '"candidates":[{"sap_table":"...","sap_field":"...","confidence_score":<0-100>,'
    '"reasoning":"..."}]}]}. '
    "Include every source field you were given, and every candidate for that field, "
    "no more, no fewer. No markdown fences, no extra keys."
)


def _combined_score(candidate: dict) -> float:
    embed = float(candidate.get("embedding_score") or 0)
    dtype = float(candidate.get("datatype_match_score") or 0)
    return max(embed, 0.7 * embed + 0.3 * dtype)


def skip_llm(candidates: list[dict]) -> bool:
    if not candidates:
        return False
    top = candidates[0]
    return _combined_score(top) >= HIGH_CONFIDENCE


def from_embeddings(candidates: list[dict], reasoning: str) -> list[dict]:
    out = []
    for c in candidates:
        out.append({
            "sap_table": c["sap_table"],
            "sap_field": c["sap_field"],
            "target_description": c.get("target_description"),
            "embedding_score": c.get("embedding_score"),
            "datatype_match_score": c.get("datatype_match_score"),
            "confidence_score": round(_combined_score(c) * 100, 2),
            "reasoning": reasoning,
        })
    return out


def rank_candidates(source_field: str, source_description: str | None, candidates: list[dict]) -> list[dict]:
    ranked = rank_candidates_batch([{
        "source_field": source_field,
        "source_description": source_description or "",
        "candidates": candidates,
    }])
    if not ranked or not ranked[0]:
        raise ValueError("LLM returned no usable candidates")
    return ranked[0]


def rank_candidates_batch(items: list[dict]) -> list[list[dict]]:
    """Batch 15–25 source fields per Sonnet call. Same contract, array in / array out."""
    results: list[list[dict] | None] = [None] * len(items)
    pending_idx: list[int] = []
    pending_items: list[dict] = []

    for i, item in enumerate(items):
        cands = item.get("candidates") or []
        if item.get("skip_llm") or skip_llm(cands):
            results[i] = from_embeddings(
                cands,
                item.get("skip_reason") or "High-confidence embedding match; LLM skipped.",
            )
        else:
            pending_idx.append(i)
            pending_items.append(item)

    for start in range(0, len(pending_items), BATCH_SIZE):
        chunk = pending_items[start : start + BATCH_SIZE]
        chunk_idx = pending_idx[start : start + BATCH_SIZE]
        try:
            ranked_chunk = _invoke_batch(chunk)
        except Exception:
            ranked_chunk = [None] * len(chunk)
        for local_i, ranked in enumerate(ranked_chunk):
            orig = chunk_idx[local_i]
            results[orig] = ranked or from_embeddings(
                chunk[local_i]["candidates"],
                "LLM ranking unavailable; ranked by embedding similarity only.",
            )

    return [row or [] for row in results]


def _invoke_batch(items: list[dict]) -> list[list[dict]]:
    payload = {
        "fields": [
            {
                "source_field": item["source_field"],
                "source_description": item.get("source_description") or "",
                "preferred_org_standard": bool(item.get("preferred_org_standard")),
                "candidates": [{
                    "sap_table": c["sap_table"],
                    "sap_field": c["sap_field"],
                    "description": c.get("target_description") or "",
                    "table_description": c.get("table_description") or "",
                    "embedding_similarity": round(float(c.get("embedding_score") or 0), 4),
                    "preferred": bool(c.get("preferred")),
                } for c in item["candidates"]],
            }
            for item in items
        ]
    }
    raw = bedrock_llm.chat(
        SYSTEM_PROMPT,
        json.dumps(payload),
        max_tokens=1500,
        purpose="mapping_batch",
        model_id=settings.bedrock_model_id,
    )
    raw = bedrock_llm.strip_markdown_fences(raw)
    data = json.loads(raw)
    if isinstance(data, list) and items and data and isinstance(data[0], dict) and "sap_table" in data[0]:
        data = {"results": [{"source_field": items[0]["source_field"], "candidates": data}]}
    rows = data.get("results") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise ValueError("LLM returned no results array")

    by_source = {}
    for row in rows:
        if isinstance(row, dict) and row.get("source_field"):
            by_source[row["source_field"]] = row.get("candidates") or []

    out: list[list[dict]] = []
    for item in items:
        by_key = {(c["sap_table"], c["sap_field"]): c for c in item["candidates"]}
        ranked = by_source.get(item["source_field"]) or []
        mapped = []
        for r in ranked:
            if not isinstance(r, dict):
                continue
            base = by_key.get((r.get("sap_table"), r.get("sap_field")))
            if base is None:
                continue
            mapped.append({
                "sap_table": r["sap_table"],
                "sap_field": r["sap_field"],
                "target_description": base.get("target_description"),
                "embedding_score": base.get("embedding_score"),
                "datatype_match_score": base.get("datatype_match_score"),
                "confidence_score": float(r.get("confidence_score") or 0),
                "reasoning": (r.get("reasoning") or "")[:80],
            })
        if not mapped:
            raise ValueError("LLM returned no usable candidates")
        out.append(mapped)
    return out
