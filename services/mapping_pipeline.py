"""Background field-mapping pipeline (embed → top-3 → batched LLM rank)."""
from __future__ import annotations

import logging
import uuid

from db.database import SessionLocal
from db.models import Mapping, MappingTemp
from services import datatype_matcher, file_parser, learned_rules, llm_mapping, mapping_engine, s3_service

logger = logging.getLogger(__name__)


def _pin_learned(match: dict, learned) -> dict:
    """Put the org-confirmed SAP field first; skip LLM unless datatype conflicts."""
    sap_table = learned.sap_table
    sap_field = learned.sap_field
    candidates = list(match.get("candidates") or [])
    pinned = None
    rest = []
    for c in candidates:
        if c.get("sap_table") == sap_table and c.get("sap_field") == sap_field:
            pinned = {**c, "preferred": True, "embedding_score": max(float(c.get("embedding_score") or 0), 0.99)}
        else:
            rest.append(c)
    if pinned is None:
        pinned = {
            "sap_table": sap_table,
            "sap_field": sap_field,
            "target_description": "",
            "table_description": "",
            "embedding_score": 0.99,
            "datatype_match_score": 1.0,
            "preferred": True,
        }
    match["candidates"] = [pinned, *rest][:3]
    dtype = float(pinned.get("datatype_match_score") or 1)
    if dtype >= 0.5:
        match["skip_llm"] = True
        match["skip_reason"] = (
            f"Org-confirmed mapping {sap_table}.{sap_field}; samples/datatype agree."
        )
    else:
        match["preferred_org_standard"] = True
    return match


def run_mapping_job(mapping_id: uuid.UUID) -> None:
    db = SessionLocal()
    try:
        mapping = db.get(Mapping, mapping_id)
        if not mapping or not mapping.source_s3_key or not mapping.target_s3_key:
            return

        source_bytes = s3_service.download_bytes(mapping.source_s3_key)
        target_bytes = s3_service.download_bytes(mapping.target_s3_key)
        source_fields = file_parser.parse_source_fields(
            source_bytes, mapping.source_filename or "source.xlsx",
        )
        target_fields = file_parser.parse_target_fields(
            target_bytes, mapping.target_filename or "target.xlsx",
        )
        if not source_fields:
            raise ValueError("Source field list is empty")
        if not target_fields:
            raise ValueError("Target SAP field list is empty")

        raw_matches = mapping_engine.top_candidates(source_fields, target_fields)
        db.query(MappingTemp).filter_by(mapping_id=mapping.id).delete(
            synchronize_session=False
        )
        mapped_fields = 0
        number_range_type = mapping.number_range_type

        llm_items: list[tuple[int, dict]] = []
        prepared: list[dict | None] = [None] * len(raw_matches)

        for i, match in enumerate(raw_matches):
            is_manual_key = number_range_type == "internal" and match["key_field"]
            if is_manual_key:
                prepared[i] = {
                    "source_field": match["source_field"],
                    "key_field": match["key_field"],
                    "candidates": [{
                        "sap_table": t["sap_table"],
                        "sap_field": t["sap_field"],
                        "target_description": t.get("description"),
                        "embedding_score": None,
                        "datatype_match_score": datatype_matcher.datatype_match_score(
                            match["datatype"], t.get("datatype")
                        ),
                        "confidence_score": None,
                        "reasoning": "Key field under an internal number range — map this manually.",
                    } for t in target_fields],
                }
                continue

            learned = learned_rules.lookup_mapping(db, match["source_field"])
            if learned:
                match = _pin_learned(match, learned)

            llm_items.append((i, {
                "source_field": match["source_field"],
                "source_description": match.get("source_description"),
                "candidates": match["candidates"],
                "skip_llm": match.get("skip_llm"),
                "skip_reason": match.get("skip_reason"),
                "preferred_org_standard": match.get("preferred_org_standard"),
                "key_field": match["key_field"],
            }))

        ranked_list = llm_mapping.rank_candidates_batch(
            [{k: v for k, v in item.items() if k != "key_field"} for _, item in llm_items]
        ) if llm_items else []

        for (orig_i, item), ranked in zip(llm_items, ranked_list):
            prepared[orig_i] = {
                "source_field": item["source_field"],
                "key_field": item["key_field"],
                "candidates": ranked,
            }
            if ranked:
                mapped_fields += 1

        for row in prepared:
            if not row:
                continue
            db.add(MappingTemp(
                mapping_id=mapping.id,
                source_field=row["source_field"],
                key_field=row["key_field"],
                mapping=row["candidates"],
            ))

        mapping.total_source_fields = len(source_fields)
        mapping.mapped_fields = mapped_fields
        mapping.status = "awaiting_approval"
        db.commit()
    except Exception as exc:
        db.rollback()
        mapping = db.get(Mapping, mapping_id)
        if mapping:
            mapping.status = "failed"
            db.commit()
        logger.exception("Mapping job failed for run %s: %s", mapping_id, exc)
    finally:
        db.close()
