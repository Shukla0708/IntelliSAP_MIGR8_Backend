"""In-process job queue for long validation and comparison runs."""
from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from db.database import SessionLocal
from db.models import (
    ComparisonException,
    ComparisonRun,
    FinalMapping,
    ValidationException,
    ValidationField,
    ValidationRun,
)
from services import comparison_engine, excel_service, s3_service

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


def submit_comparison(run_id: uuid.UUID) -> None:
    if _executor is None:
        start()
    assert _executor is not None
    _executor.submit(_safe_comparison, run_id)


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
    try:
        db.query(ComparisonRun).filter(ComparisonRun.status == "running").update(
            {"status": "failed", "error_message": interrupted},
            synchronize_session=False,
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Could not mark stale comparison jobs as failed")
    finally:
        db.close()


def _safe_validation(run_id: uuid.UUID) -> None:
    try:
        _run_validation_job(run_id)
    except Exception:
        logger.exception("Validation job crashed for run %s", run_id)


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
        if not run:
            return
        if not run.preload_s3_key or not run.postload_s3_key:
            raise ValueError("Both preload and postload files are required")

        preload_headers = _headers_for_key(run.preload_s3_key, run.preload_filename or "preload.xlsx")
        postload_headers = _headers_for_key(run.postload_s3_key, run.postload_filename or "postload.xlsx")
        join_keys, compare_fields = _resolve_compare_spec(
            db, run, preload_headers, postload_headers,
        )

        def on_progress(processed: int, total: int | None) -> None:
            run.processed_rows = processed
            if total is not None:
                run.total_rows = total
            db.commit()

        pre_tmp = s3_service.download_to_temp(
            run.preload_s3_key,
            suffix=_suffix(run.preload_filename),
        )
        post_tmp = s3_service.download_to_temp(
            run.postload_s3_key,
            suffix=_suffix(run.postload_filename),
        )
        try:
            result_bytes, stats, exceptions = comparison_engine.run_comparison(
                pre_tmp,
                run.preload_filename or "preload.xlsx",
                post_tmp,
                run.postload_filename or "postload.xlsx",
                join_keys,
                compare_fields,
                on_progress,
            )
        finally:
            pre_tmp.unlink(missing_ok=True)
            post_tmp.unlink(missing_ok=True)

        result_key = f"comparisons/{run_id}/result/reconciliation.xlsx"
        s3_service.upload_bytes(
            result_key,
            result_bytes,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        db.query(ComparisonException).filter_by(run_id=run_id).delete()
        for item in exceptions:
            db.add(ComparisonException(run_id=run_id, **item))

        run.matched_records = stats["matched_records"]
        run.different_count = stats["different_count"]
        run.missing_count = stats["missing_count"]
        run.extra_count = stats["extra_count"]
        run.match_rate = stats["match_rate"]
        run.total_rows = stats["total_rows"]
        run.processed_rows = stats["total_rows"]
        run.result_s3_key = result_key
        run.status = "completed"
        run.completed_at = datetime.utcnow()
        run.error_message = None
        db.commit()
    except Exception as exc:
        db.rollback()
        run = db.get(ComparisonRun, run_id)
        if run:
            run.status = "failed"
            run.error_message = str(exc)[:2000]
            db.commit()
        logger.exception("Comparison job failed for run %s", run_id)
    finally:
        db.close()


def _suffix(filename: str | None) -> str:
    return ".csv" if (filename or "").lower().endswith(".csv") else ".xlsx"


def _headers_for_key(key: str, filename: str) -> list[str]:
    tmp = s3_service.download_to_temp(key, suffix=_suffix(filename))
    try:
        from services import file_stream
        return file_stream.extract_headers_from_path(tmp, filename)
    finally:
        tmp.unlink(missing_ok=True)


def _resolve_compare_spec(db, run: ComparisonRun, preload_headers: list[str], postload_headers: list[str]):
    from services.comparison_engine import resolve_postload_column

    join_keys: list[tuple[str, str]] = []
    compare_fields: list[tuple[str, str]] = []

    if run.mapping_id:
        mapped = (
            db.query(FinalMapping)
            .filter(FinalMapping.mapping_id == run.mapping_id)
            .all()
        )
        if not mapped:
            raise ValueError("The selected field mapping has no confirmed fields yet.")
        for row in mapped:
            post_col = resolve_postload_column(row.target_field, postload_headers)
            if not post_col or row.source_field not in preload_headers:
                continue
            pair = (row.source_field, post_col)
            if row.key:
                join_keys.append(pair)
            else:
                compare_fields.append(pair)
        if not join_keys:
            raise ValueError("Confirmed mapping has no key fields that exist in both files.")
        return join_keys, compare_fields

    selected = list(run.join_keys or [])
    if not selected:
        raise ValueError("Select at least one join key that exists in both files.")
    preload_lookup = {h.lower(): h for h in preload_headers}
    postload_lookup = {h.lower(): h for h in postload_headers}
    for name in selected:
        pre = preload_lookup.get(str(name).lower())
        post = postload_lookup.get(str(name).lower())
        if not pre or not post:
            raise ValueError(f"Join key '{name}' was not found in both files.")
        join_keys.append((pre, post))
    join_pre = {pre for pre, _ in join_keys}
    for pre in preload_headers:
        post = postload_lookup.get(pre.lower())
        if post and pre not in join_pre:
            compare_fields.append((pre, post))
    return join_keys, compare_fields
