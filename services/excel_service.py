"""Validate source files by streaming rows and writing an annotated XLSX."""
from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Callable
from datetime import date, datetime, time
from pathlib import Path

import xlsxwriter

from services import file_stream
from services.rules_engine import is_empty_raw, normalize_key, validate_cell

MAX_STORED_EXCEPTIONS = 20
MAX_EXCEPTIONS_PER_TYPE = 5
PROGRESS_EVERY = 10_000

_WORKBOOK_OPTIONS = {
    "constant_memory": True,
    "strings_to_urls": False,
    "strings_to_numbers": False,
    "strings_to_formulas": False,
}

ProgressCallback = Callable[[int, int | None], None]


def extract_headers(file_bytes: bytes, filename: str = "source.xlsx") -> list[str]:
    """Read only the header row — used right after upload to populate the
    'Validation Rules Configuration' UI with real column names."""
    return file_stream.extract_headers(file_bytes, filename)


def run_validation(
    file_bytes: bytes,
    field_configs: list[dict],
    filename: str = "source.xlsx",
    on_progress: ProgressCallback | None = None,
):
    """
    field_configs: one dict per field, matching ValidationField columns.

    If two or more fields have flag_key, uniqueness is checked on the
    combined values (composite key), not independently per column.

    Returns (annotated_workbook_bytes, stats_dict, exceptions_list).
    """
    suffix = ".csv" if (filename or "").lower().endswith(".csv") else ".xlsx"
    handle, name = tempfile.mkstemp(suffix=suffix)
    os.close(handle)
    path = Path(name)
    path.write_bytes(file_bytes)
    try:
        return run_validation_from_path(path, filename, field_configs, on_progress)
    finally:
        path.unlink(missing_ok=True)


def run_validation_from_path(
    path: Path,
    filename: str,
    field_configs: list[dict],
    on_progress: ProgressCallback | None = None,
):
    header = file_stream.extract_headers_from_path(path, filename)
    name_to_col = _header_index(header)

    compiled_configs = []
    for cfg in field_configs:
        item = dict(cfg)
        pattern = cfg.get("regex")
        if pattern:
            try:
                item["_compiled_regex"] = re.compile(pattern)
            except re.error:
                item["_compiled_regex"] = None
        else:
            item["_compiled_regex"] = None
        compiled_configs.append(item)

    ruled_columns: list[tuple[int, str, dict]] = []
    for cfg in compiled_configs:
        col_idx = _col_index(name_to_col, cfg["field_name"])
        if col_idx is not None:
            ruled_columns.append((col_idx, cfg["field_name"], cfg))

    key_field_names = [c["field_name"] for c in compiled_configs if c["flag_key"]]
    composite_keys = len(key_field_names) >= 2
    seen_keys_by_field = (
        {} if composite_keys
        else {c["field_name"]: set() for c in compiled_configs if c["flag_key"]}
    )
    seen_composites: dict[tuple[str, ...], int] = {}

    total_rows = valid_rows = invalid_rows = total_errors = critical_errors = 0
    errors_by_field: dict[str, int] = {}
    errors_by_type: dict[str, int] = {}
    exceptions: list[dict] = []
    stored_rows_by_type: dict[str, set[int]] = {}

    out_handle, out_name = tempfile.mkstemp(suffix=".xlsx")
    os.close(out_handle)
    out_path = Path(out_name)
    workbook = xlsxwriter.Workbook(str(out_path), _WORKBOOK_OPTIONS)
    worksheet = workbook.add_worksheet("Validation")
    red = workbook.add_format({"bg_color": "FFC7CE"})
    header_fmt = workbook.add_format({"bold": True})

    for col, name in enumerate(header):
        worksheet.write_string(0, col, str(name), header_fmt)
    reason_col_idx = len(header)
    worksheet.write_string(0, reason_col_idx, "Validation_Failure_Reason", header_fmt)

    write_row = 1
    for excel_row, values in file_stream.iter_data_rows(path, filename):
        # Pad / trim to header width so column indexes stay stable.
        if len(values) < len(header):
            values = values + [""] * (len(header) - len(values))
        elif len(values) > len(header):
            values = values[: len(header)]

        total_rows += 1
        row_reasons: list[str] = []
        row_has_error = False
        failing_cols: set[int] = set()

        for col_idx, field_name, cfg in ruled_columns:
            if col_idx >= len(values):
                continue
            cell_value = _empty_to_none(values[col_idx])
            seen_keys = None if composite_keys else seen_keys_by_field.get(field_name)
            reasons = validate_cell(cell_value, cfg, seen_keys)
            if reasons:
                row_has_error = True
                failing_cols.add(col_idx)
                is_critical = cfg["flag_mandatory"] or cfg["flag_key"]
                for reason in reasons:
                    row_reasons.append(f"{field_name}: {reason}")
                    total_errors += 1
                    errors_by_field[field_name] = errors_by_field.get(field_name, 0) + 1
                    bucket = reason.split(" ")[0]
                    errors_by_type[bucket] = errors_by_type.get(bucket, 0) + 1
                    if is_critical:
                        critical_errors += 1
                    _try_store_exception(exceptions, stored_rows_by_type, {
                        "row_number": excel_row,
                        "field_name": field_name,
                        "actual_value": str(cell_value) if cell_value is not None else "",
                        "expected_value": _expected_label(cfg),
                        "error_type": reason,
                        "severity": "error" if is_critical else "warning",
                    })

        if composite_keys:
            dup_count, key_cols = _flag_duplicate_composite_values(
                values, excel_row, key_field_names, name_to_col, seen_composites,
                row_reasons, exceptions, stored_rows_by_type,
                errors_by_field, errors_by_type,
            )
            if dup_count:
                row_has_error = True
                failing_cols.update(key_cols)
                total_errors += dup_count
                critical_errors += dup_count

        for col_idx, value in enumerate(values):
            cell_format = red if col_idx in failing_cols else None
            _write_cell(worksheet, write_row, col_idx, value, cell_format)
        if row_has_error:
            invalid_rows += 1
            worksheet.write_string(write_row, reason_col_idx, "; ".join(row_reasons))
        else:
            valid_rows += 1
            worksheet.write_blank(write_row, reason_col_idx, None)

        write_row += 1
        if on_progress and total_rows % PROGRESS_EVERY == 0:
            on_progress(total_rows, None)

    workbook.close()
    if on_progress:
        on_progress(total_rows, total_rows)

    result_bytes = out_path.read_bytes()
    out_path.unlink(missing_ok=True)

    health_score = round((valid_rows / total_rows) * 100, 2) if total_rows else 100.0

    PALETTE = ["#004da4", "#6063ee", "#8a3500", "#c2c6d5", "#0f9d58", "#d93025"]
    type_total = sum(errors_by_type.values()) or 1
    errors_by_type_chart = [
        {
            "label": label,
            "value": round((count / type_total) * 100),
            "color": PALETTE[i % len(PALETTE)],
        }
        for i, (label, count) in enumerate(errors_by_type.items())
    ]

    stats = {
        "total_records": total_rows,
        "valid_rows": valid_rows,
        "invalid_rows": invalid_rows,
        "total_errors": total_errors,
        "critical_errors": critical_errors,
        "health_score": health_score,
        "errors_by_field": [{"field": k, "count": v} for k, v in errors_by_field.items()],
        "errors_by_type": errors_by_type_chart,
    }
    return result_bytes, stats, exceptions


def _empty_to_none(value):
    if value is None:
        return None
    if isinstance(value, str) and value == "":
        return None
    return value


def _write_cell(worksheet, row: int, col: int, value, cell_format=None) -> None:
    """Typed writes skip xlsxwriter's per-cell token detection."""
    if value is None or value == "":
        worksheet.write_blank(row, col, None, cell_format)
        return
    if isinstance(value, str):
        worksheet.write_string(row, col, value, cell_format)
        return
    if isinstance(value, bool):
        worksheet.write_boolean(row, col, value, cell_format)
        return
    if isinstance(value, (int, float)):
        worksheet.write_number(row, col, value, cell_format)
        return
    if isinstance(value, (datetime, date, time)):
        worksheet.write_datetime(row, col, value, cell_format)
        return
    worksheet.write_string(row, col, str(value), cell_format)


def _header_index(header: list) -> dict[str, int]:
    """Map header names to 0-based indexes (exact and lowercase)."""
    mapping: dict[str, int] = {}
    for idx, name in enumerate(header):
        if name is None:
            continue
        label = str(name).strip()
        if not label:
            continue
        mapping[label] = idx
        mapping[label.lower()] = idx
    return mapping


def _col_index(name_to_col: dict[str, int], field_name: str) -> int | None:
    if field_name in name_to_col:
        return name_to_col[field_name]
    return name_to_col.get(field_name.lower())


def _exception_type_key(reason: str) -> str:
    """Group composite-key duplicates as one type regardless of first-row text."""
    if reason.startswith("Duplicate composite key value"):
        return "Duplicate composite key value"
    return reason


def _try_store_exception(
    exceptions: list[dict],
    stored_rows_by_type: dict[str, set[int]],
    item: dict,
) -> None:
    """Keep a mixed sample: up to N rows per error type, and an overall cap."""
    if len(exceptions) >= MAX_STORED_EXCEPTIONS:
        return
    key = _exception_type_key(item["error_type"])
    rows = stored_rows_by_type.setdefault(key, set())
    row_num = item["row_number"]
    if row_num not in rows and len(rows) >= MAX_EXCEPTIONS_PER_TYPE:
        return
    exceptions.append(item)
    rows.add(row_num)


def _flag_duplicate_composite_values(
    values: list,
    row_num: int,
    key_field_names: list[str],
    name_to_col: dict[str, int],
    seen_composites: dict[tuple[str, ...], int],
    row_reasons: list[str],
    exceptions: list[dict],
    stored_rows_by_type: dict[str, set[int]],
    errors_by_field: dict[str, int],
    errors_by_type: dict[str, int],
) -> tuple[int, list[int]]:
    """Flag a duplicate composite key. Returns (error count, failing column indexes)."""
    parts: list[str] = []
    key_cells: list[tuple[str, int, str]] = []
    for field_name in key_field_names:
        col_idx = _col_index(name_to_col, field_name)
        if col_idx is None or col_idx >= len(values):
            return 0, []
        raw = normalize_key(_empty_to_none(values[col_idx]))
        parts.append(raw)
        key_cells.append((field_name, col_idx, raw))

    if any(is_empty_raw(p) for p in parts):
        return 0, []

    composite = tuple(parts)
    first_row = seen_composites.get(composite)
    if first_row is None:
        seen_composites[composite] = row_num
        return 0, []

    reason = f"Duplicate composite key value (same as row {first_row})"
    label = " + ".join(key_field_names)
    failing_cols: list[int] = []
    for field_name, col_idx, raw in key_cells:
        failing_cols.append(col_idx)
        row_reasons.append(f"{field_name}: {reason}")
        errors_by_field[field_name] = errors_by_field.get(field_name, 0) + 1
        errors_by_type["Duplicate"] = errors_by_type.get("Duplicate", 0) + 1
        _try_store_exception(exceptions, stored_rows_by_type, {
            "row_number": row_num,
            "field_name": field_name,
            "actual_value": raw,
            "expected_value": f"Unique composite ({label})",
            "error_type": reason,
            "severity": "error",
        })
    return len(key_cells), failing_cols


def _expected_label(cfg: dict) -> str:
    if cfg["flag_key"]:
        return "Non-empty unique key"
    if cfg["flag_email"]:
        return "Valid email format"
    if cfg["flag_mobile"]:
        return "Valid mobile number"
    if cfg["flag_date"]:
        return "Valid date"
    if cfg["max_length"]:
        return f"Max length {cfg['max_length']}"
    return cfg["data_type"]
