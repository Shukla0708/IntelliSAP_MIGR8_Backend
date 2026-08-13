"""Background field-mapping pipeline (embed → top-3 → LLM rank)."""
from __future__ import annotations

import logging
import uuid

from db.database import SessionLocal
from db.models import Mapping, MappingTemp
from services import datatype_matcher, file_parser, llm_mapping, mapping_engine, s3_service

logger = logging.getLogger(__name__)


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
        db.query(MappingTemp).filter_by(mapping_id=mapping.id).delete()
        mapped_fields = 0
        number_range_type = mapping.number_range_type

        for match in raw_matches:
            is_manual_key = number_range_type == "internal" and match["key_field"]
            if is_manual_key:
                final_candidates = [{
                    "sap_table": t["sap_table"],
                    "sap_field": t["sap_field"],
                    "target_description": t.get("description"),
                    "embedding_score": None,
                    "datatype_match_score": datatype_matcher.datatype_match_score(
                        match["datatype"], t.get("datatype")
                    ),
                    "confidence_score": None,
                    "reasoning": "Key field under an internal number range — map this manually.",
                } for t in target_fields]
            else:
                try:
                    final_candidates = llm_mapping.rank_candidates(
                        match["source_field"], match["source_description"], match["candidates"]
                    )
                except Exception:
                    final_candidates = [{
                        "sap_table": c["sap_table"],
                        "sap_field": c["sap_field"],
                        "target_description": c.get("target_description"),
                        "embedding_score": c["embedding_score"],
                        "datatype_match_score": c.get("datatype_match_score"),
                        "confidence_score": round(c["embedding_score"] * 100, 2),
                        "reasoning": "LLM ranking unavailable; ranked by embedding similarity only.",
                    } for c in match["candidates"]]
                if final_candidates:
                    mapped_fields += 1

            db.add(MappingTemp(
                mapping_id=mapping.id,
                source_field=match["source_field"],
                key_field=match["key_field"],
                mapping=final_candidates,
            ))
            mapping.mapped_fields = mapped_fields
            mapping.total_source_fields = len(source_fields)
            db.commit()

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
