"""In-process job queue for long validation, mapping, and comparison runs."""
from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from sqlalchemy import text

from db.database import SessionLocal, engine
from db.models import (
    ComparisonDiscrepancy,
    ComparisonRun,
    FinalMapping,
    Mapping,
    ValidationException,
    ValidationField,
    ValidationRun,
)
from services import comparison_engine, comparison_file_service, excel_service, s3_service
from services.mapping_pipeline import run_mapping_job

logger = logging.getLogger(__name__)

_executor: ThreadPoolExecutor | None = None


def start(*, recover_stale: bool = True) -> None:
    global _executor
    _ensure_runtime_columns()
    if recover_stale:
        _fail_stale_jobs()
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="migr8-job")


def stop() -> None:
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=False, cancel_futures=True)
        _executor = None


def submit_validation(run_id: uuid.UUID) -> None:
    _submit(_safe_validation, run_id)


def submit_mapping(run_id: uuid.UUID) -> None:
    _submit(_safe_mapping, run_id)


def submit_comparison(run_id: uuid.UUID) -> None:
    _submit(_safe_comparison, run_id)


def _submit(fn, run_id: uuid.UUID) -> None:
    if _executor is None:
        start(recover_stale=False)
    assert _executor is not None
    _executor.submit(fn, run_id)


def _ensure_runtime_columns() -> None:
    statements = [
        "ALTER TABLE validation_runs ADD COLUMN IF NOT EXISTS processed_rows INT DEFAULT 0",
        "ALTER TABLE validation_runs ADD COLUMN IF NOT EXISTS total_rows INT DEFAULT 0",
        "ALTER TABLE validation_runs ADD COLUMN IF NOT EXISTS error_message TEXT",
    ]
    try:
        with engine.begin() as conn:
            for sql in statements:
                conn.execute(text(sql))
    except Exception:
        logger.exception("Could not ensure large-file progress columns")


def _fail_stale_jobs() -> None:
    interrupted = "Interrupted by server restart. Run again."
    db = SessionLocal()
    try:
        db.query(ValidationRun).filter(ValidationRun.status == "running").update(
            {"status": "failed", "error_message": interrupted},
            synchronize_session=False,
        )
        db.query(Mapping).filter(Mapping.status == "processing").update(
            {"status": "failed"},
            synchronize_session=False,
        )
        db.query(ComparisonRun).filter(ComparisonRun.status == "running").update(
            {"status": "failed"},
            synchronize_session=False,
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Could not mark stale jobs as failed")
    finally:
        db.close()


def _safe_validation(run_id: uuid.UUID) -> None:
    try:
        _run_validation_job(run_id)
    except Exception:
        logger.exception("Validation job crashed for run %s", run_id)


def _safe_mapping(run_id: uuid.UUID) -> None:
    try:
        run_mapping_job(run_id)
    except Exception:
        logger.exception("Mapping job crashed for run %s", run_id)


def _safe_comparison(run_id: uuid.UUID) -> None:
    try:
        _run_comparison_job(run_id)
    except Exception:
        logger.exception("Comparison job crashed for run %s", run_id)


def _run_validation_job(run_id: uuid.UUID) -> None:
    db = SessionLocal()
    try:
        run = db.get(ValidationRun, run_id)
        if not run:
            return
        field_rows = db.query(ValidationField).filter_by(run_id=run_id).all()
        field_configs = [{
            "field_name": f.field_name,
            "flag_key": f.flag_key, "flag_mandatory": f.flag_mandatory,
            "flag_null": f.flag_null, "flag_email": f.flag_email,
            "flag_mobile": f.flag_mobile, "flag_date": f.flag_date,
            "flag_special_chars": f.flag_special_chars,
            "case_format": f.case_format, "data_type": f.data_type,
            "max_length": f.max_length, "decimal_length": f.decimal_length,
            "regex": f.regex,
        } for f in field_rows]

        def on_progress(processed: int, total: int | None) -> None:
            run.processed_rows = processed
            if total is not None:
                run.total_rows = total
            db.commit()

        suffix = ".csv" if (run.source_filename or "").lower().endswith(".csv") else ".xlsx"
        tmp = s3_service.download_to_temp(run.source_s3_key, suffix=suffix)
        try:
            result_bytes, stats, exceptions = excel_service.run_validation_from_path(
                tmp,
                run.source_filename or "source.xlsx",
                field_configs,
                on_progress,
            )
        finally:
            tmp.unlink(missing_ok=True)

        stem = Path(run.source_filename or "result").stem
        result_key = f"validations/{run_id}/result/{stem}.xlsx"
        s3_service.upload_bytes(
            result_key,
            result_bytes,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        db.query(ValidationException).filter_by(run_id=run_id).delete()
        for item in exceptions:
            db.add(ValidationException(run_id=run_id, **item))

        for key, value in stats.items():
            setattr(run, key, value)
        run.total_rows = stats.get("total_records", run.total_rows)
        run.processed_rows = stats.get("total_records", run.processed_rows)
        run.result_s3_key = result_key
        run.status = "completed"
        run.completed_at = datetime.utcnow()
        run.error_message = None
        db.commit()
    except Exception as exc:
        db.rollback()
        run = db.get(ValidationRun, run_id)
        if run:
            run.status = "failed"
            run.error_message = str(exc)[:2000]
            db.commit()
        logger.exception("Validation job failed for run %s", run_id)
    finally:
        db.close()


def _run_comparison_job(run_id: uuid.UUID) -> None:
    db = SessionLocal()
    try:
        run = db.get(ComparisonRun, run_id)
        if not run or not run.preload_s3_key or not run.postload_s3_key:
            return

        mapping_rows = None
        if run.mapping_id:
            confirmed = db.query(FinalMapping).filter_by(mapping_id=run.mapping_id).all()
            mapping_rows = [
                {
                    "source_field": row.source_field,
                    "target_field": row.target_field,
                    "is_key": bool(row.key),
                }
                for row in confirmed
            ]

        preload_bytes = s3_service.download_bytes(run.preload_s3_key)
        postload_bytes = s3_service.download_bytes(run.postload_s3_key)
        plan = comparison_engine.build_plan(
            comparison_file_service.read_header(preload_bytes),
            comparison_file_service.read_header(postload_bytes),
            mapping_rows=mapping_rows,
            business_key_preload=run.business_key_columns_preload or [],
            business_key_postload=run.business_key_columns_postload or [],
        )
        result_bytes, stats, discrepancies = comparison_engine.run_comparison(
            preload_bytes, postload_bytes, plan,
        )

        result_key = f"comparisons/{run_id}/result/comparison_{run.preload_filename}"
        s3_service.upload_bytes(
            result_key, result_bytes, comparison_file_service.XLSX_CONTENT_TYPE,
        )

        db.query(ComparisonDiscrepancy).filter_by(run_id=run_id).delete()
        for entry in discrepancies:
            db.add(ComparisonDiscrepancy(run_id=run_id, **entry))

        for key, value in stats.items():
            setattr(run, key, value)
        run.result_s3_key = result_key
        run.status = "completed"
        run.completed_at = datetime.utcnow()
        db.commit()
    except Exception as exc:
        db.rollback()
        run = db.get(ComparisonRun, run_id)
        if run:
            run.status = "failed"
            db.commit()
        logger.exception("Comparison job failed for run %s: %s", run_id, exc)
    finally:
        db.close()
