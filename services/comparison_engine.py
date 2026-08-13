"""Preload vs postload reconciliation via a Polars hash-join."""
from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Callable
from pathlib import Path

import polars as pl
import xlsxwriter

from services import file_stream
from services.excel_service import (
    MAX_EXCEPTIONS_PER_TYPE,
    MAX_STORED_EXCEPTIONS,
    PROGRESS_EVERY,
)
from services.rules_engine import normalize_key, normalize_raw

ProgressCallback = Callable[[int, int | None], None]
_PUNCT_RE = re.compile(r"[^a-zA-Z0-9]+")


def run_comparison(
    preload_path: Path,
    preload_filename: str,
    postload_path: Path,
    postload_filename: str,
    join_keys: list[tuple[str, str]],
    compare_fields: list[tuple[str, str]],
    on_progress: ProgressCallback | None = None,
):
    """
    join_keys / compare_fields: list of (preload_column, postload_column).
    Returns (annotated_xlsx_bytes, stats_dict, exceptions_list).
    """
    if not join_keys:
        raise ValueError("Select at least one join key that exists in both files.")

    preload = _load_frame(preload_path, preload_filename)
    postload = _load_frame(postload_path, postload_filename)
    if on_progress:
        on_progress(0, preload.height + postload.height)

    pre_keys = [pre for pre, _ in join_keys]
    post_keys = [post for _, post in join_keys]
    _require_columns(preload, pre_keys, "preload")
    _require_columns(postload, post_keys, "postload")

    preload = preload.with_row_index("_pre_row", offset=2)
    postload = postload.with_row_index("_post_row", offset=2)
    preload = preload.with_columns(_join_expr(preload, pre_keys).alias("_join_key"))
    postload = postload.with_columns(_join_expr(postload, post_keys).alias("_join_key"))

    joined = preload.join(postload, on="_join_key", how="full", suffix="_post")

    matched = different = missing = extra = 0
    exceptions: list[dict] = []
    stored_rows_by_type: dict[str, set[int]] = {}
    output_rows: list[dict] = []

    pre_cols = [c for c in preload.columns if not c.startswith("_")]
    total = joined.height or 1
    for idx, rec in enumerate(joined.iter_rows(named=True), start=1):
        if on_progress and idx % PROGRESS_EVERY == 0:
            on_progress(idx, total)

        pre_present = rec.get("_pre_row") is not None
        post_present = rec.get("_post_row") is not None
        business_key = rec.get("_join_key") or ""
        row_num = int(rec["_pre_row"] or rec["_post_row"] or idx)

        if pre_present and not post_present:
            missing += 1
            reason = "Dropped during load"
            output_rows.append(_output_row(rec, pre_cols, join_keys, compare_fields, "DROPPED_RECORD", reason, True))
            _store_exception(exceptions, stored_rows_by_type, {
                "row_number": row_num,
                "business_key": f"ID: {business_key}",
                "field_name": "Entire Record",
                "preload_value": "PRESENT",
                "postload_value": "NULL (Not Found)",
                "difference_type": "DROPPED_RECORD",
                "severity": "error",
            })
            continue

        if post_present and not pre_present:
            extra += 1
            reason = "Extra record in postload"
            output_rows.append(_output_row(rec, pre_cols, join_keys, compare_fields, "EXTRA_RECORD", reason, True))
            _store_exception(exceptions, stored_rows_by_type, {
                "row_number": row_num,
                "business_key": f"ID: {business_key}",
                "field_name": "Entire Record",
                "preload_value": "NULL (Not Found)",
                "postload_value": "PRESENT",
                "difference_type": "EXTRA_RECORD",
                "severity": "warning",
            })
            continue

        field_reasons: list[str] = []
        diffs: list[tuple[str, str, str, str]] = []
        for pre_col, post_col in compare_fields:
            pre_val = rec.get(pre_col)
            post_val = rec.get(f"{post_col}_post") if post_col in pre_cols or f"{post_col}_post" in rec else rec.get(post_col)
            if post_col == pre_col:
                post_val = rec.get(f"{post_col}_post", rec.get(post_col))
            kind = _diff_kind(pre_val, post_val)
            if not kind:
                continue
            field_reasons.append(f"{pre_col}: {kind}")
            diffs.append((pre_col, kind, normalize_raw(pre_val), normalize_raw(post_val)))

        if diffs:
            different += 1
            reason = "; ".join(field_reasons)
            output_rows.append(_output_row(rec, pre_cols, join_keys, compare_fields, diffs[0][1], reason, True))
            for field_name, kind, pre_s, post_s in diffs:
                _store_exception(exceptions, stored_rows_by_type, {
                    "row_number": row_num,
                    "business_key": f"ID: {business_key}",
                    "field_name": field_name,
                    "preload_value": pre_s,
                    "postload_value": post_s,
                    "difference_type": kind,
                    "severity": "info" if kind == "FORMAT_CHANGE" else "warning",
                })
        else:
            matched += 1
            output_rows.append(_output_row(rec, pre_cols, join_keys, compare_fields, "MATCHED", "", False))

    compared = matched + different + missing
    match_rate = round((matched / compared) * 100, 2) if compared else 100.0
    if on_progress:
        on_progress(total, total)

    result_bytes = _write_xlsx(pre_cols, join_keys, compare_fields, output_rows)
    stats = {
        "matched_records": matched,
        "different_count": different,
        "missing_count": missing,
        "extra_count": extra,
        "match_rate": match_rate,
        "total_rows": matched + different + missing + extra,
    }
    return result_bytes, stats, exceptions


def _load_frame(path: Path, filename: str) -> pl.DataFrame:
    if file_stream.sniff_kind(filename) == "csv":
        return pl.read_csv(path, infer_schema_length=0)
    rows = list(file_stream.iter_data_rows(path, filename))
    header = file_stream.extract_headers_from_path(path, filename)
    if not rows:
        return pl.DataFrame({col: [] for col in header})
    data = {col: [(_pad(row, header)[i] if i < len(_pad(row, header)) else "") for _, row in rows] for i, col in enumerate(header)}
    return pl.DataFrame(data)


def _pad(row: list, header: list) -> list:
    if len(row) < len(header):
        return row + [""] * (len(header) - len(row))
    return row[: len(header)]


def _require_columns(frame: pl.DataFrame, columns: list[str], side: str) -> None:
    missing = [c for c in columns if c not in frame.columns]
    if missing:
        raise ValueError(f"{side} file is missing join/compare columns: {', '.join(missing)}")


def _join_expr(frame: pl.DataFrame, columns: list[str]) -> pl.Expr:
    parts = [_normalize_expr(pl.col(c)) for c in columns]
    if len(parts) == 1:
        return parts[0]
    return pl.concat_str(parts, separator="|")


def _normalize_expr(expr: pl.Expr) -> pl.Expr:
    return (
        expr.cast(pl.Utf8, strict=False)
        .fill_null("")
        .str.strip_chars()
        .str.replace(r"\.0$", "")
    )


def _diff_kind(pre_val, post_val) -> str | None:
    pre = normalize_raw(pre_val)
    post = normalize_raw(post_val)
    if pre == post:
        return None
    if _alnum(pre) == _alnum(post) and _alnum(pre):
        return "FORMAT_CHANGE"
    return "VALUE_MISMATCH"


def _alnum(value: str) -> str:
    return _PUNCT_RE.sub("", value).lower()


def _output_row(
    rec: dict,
    pre_cols: list[str],
    join_keys: list[tuple[str, str]],
    compare_fields: list[tuple[str, str]],
    status: str,
    reason: str,
    failing: bool,
) -> dict:
    row = {col: rec.get(col) for col in pre_cols}
    for pre_col, post_col in compare_fields:
        post_val = rec.get(f"{post_col}_post", rec.get(post_col))
        row[f"{pre_col}__postload"] = post_val
    row["_status"] = status
    row["_reason"] = reason
    row["_failing"] = failing
    row["_join_key"] = rec.get("_join_key")
    return row


def _store_exception(exceptions: list[dict], stored_rows_by_type: dict[str, set[int]], item: dict) -> None:
    if len(exceptions) >= MAX_STORED_EXCEPTIONS:
        return
    key = item["difference_type"]
    rows = stored_rows_by_type.setdefault(key, set())
    row_num = item["row_number"]
    if row_num not in rows and len(rows) >= MAX_EXCEPTIONS_PER_TYPE:
        return
    exceptions.append(item)
    rows.add(row_num)


def _write_xlsx(
    pre_cols: list[str],
    join_keys: list[tuple[str, str]],
    compare_fields: list[tuple[str, str]],
    rows: list[dict],
) -> bytes:
    handle, name = tempfile.mkstemp(suffix=".xlsx")
    os.close(handle)
    path = Path(name)
    workbook = xlsxwriter.Workbook(str(path), {"constant_memory": True})
    worksheet = workbook.add_worksheet("Reconciliation")
    red = workbook.add_format({"bg_color": "FFC7CE"})
    header_fmt = workbook.add_format({"bold": True})

    headers = list(pre_cols)
    for pre_col, _ in compare_fields:
        headers.append(f"{pre_col} (postload)")
    headers.extend(["Status", "Reason"])
    for col, title in enumerate(headers):
        worksheet.write(0, col, title, header_fmt)

    for r, rec in enumerate(rows, start=1):
        failing = bool(rec.get("_failing"))
        for c, col in enumerate(pre_cols):
            fmt = red if failing and rec.get("_status") in ("DROPPED_RECORD", "EXTRA_RECORD") else None
            _write(worksheet, r, c, rec.get(col), fmt)
        offset = len(pre_cols)
        for i, (pre_col, _) in enumerate(compare_fields):
            post_val = rec.get(f"{pre_col}__postload")
            pre_val = rec.get(pre_col)
            fmt = red if failing and _diff_kind(pre_val, post_val) else None
            _write(worksheet, r, offset + i, post_val, fmt)
        status_col = offset + len(compare_fields)
        worksheet.write(r, status_col, rec.get("_status") or "")
        worksheet.write(r, status_col + 1, rec.get("_reason") or "")

    workbook.close()
    data = path.read_bytes()
    path.unlink(missing_ok=True)
    return data


def _write(worksheet, row: int, col: int, value, cell_format=None) -> None:
    if value is None or value == "":
        worksheet.write_blank(row, col, None, cell_format)
        return
    worksheet.write(row, col, value, cell_format)


def resolve_postload_column(target_field: str, postload_headers: list[str]) -> str | None:
    lookup = {h.lower(): h for h in postload_headers}
    if target_field in postload_headers:
        return target_field
    if target_field.lower() in lookup:
        return lookup[target_field.lower()]
    sap = target_field.split(".")[-1]
    if sap in postload_headers:
        return sap
    if sap.lower() in lookup:
        return lookup[sap.lower()]
    return None
