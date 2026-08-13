"""In-process job queue for long validation runs."""
from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from db.database import SessionLocal
from db.models import ValidationException, ValidationField, ValidationRun
from services import excel_service, s3_service

logger = logging.getLogger(__name__)

_executor: ThreadPoolExecutor | None = None


def start() -> None:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="migr8-job")
    _fail_stale_jobs()


def stop() -> None:
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=False, cancel_futures=True)
        _executor = None


def submit_validation(run_id: uuid.UUID) -> None:
    if _executor is None:
        start()
    assert _executor is not None
    _executor.submit(_safe_validation, run_id)


def _fail_stale_jobs() -> None:
    interrupted = "Interrupted by server restart. Run again."
    db = SessionLocal()
    try:
        db.query(ValidationRun).filter(ValidationRun.status == "running").update(
            {"status": "failed", "error_message": interrupted},
            synchronize_session=False,
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Could not mark stale validation jobs as failed")
    finally:
        db.close()


def _safe_validation(run_id: uuid.UUID) -> None:
    try:
        _run_validation_job(run_id)
    except Exception:
        logger.exception("Validation job crashed for run %s", run_id)


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
