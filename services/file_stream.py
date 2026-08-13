"""Stream CSV/XLSX without loading a full openpyxl workbook into memory."""
from __future__ import annotations

import csv
import io
import logging
import tempfile
from collections.abc import Iterator
from pathlib import Path

from openpyxl import load_workbook

logger = logging.getLogger(__name__)

CHUNK_SIZE = 25_000


def sniff_kind(filename: str) -> str:
    lower = (filename or "").lower()
    if lower.endswith(".csv"):
        return "csv"
    if lower.endswith(".xlsx"):
        return "xlsx"
    raise ValueError("Unsupported file type. Upload a .csv or .xlsx file.")


def extract_headers(file_bytes: bytes, filename: str = "source.xlsx") -> list[str]:
    kind = sniff_kind(filename)
    if kind == "csv":
        text = file_bytes[:16384].decode("utf-8-sig", errors="replace")
        first = next((line for line in text.splitlines() if line.strip()), "")
        if not first:
            return []
        header = next(csv.reader([first]))
        return [str(h).strip() for h in header if h is not None and str(h).strip()]
    wb = load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    ws = wb.active
    header_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True))
    wb.close()
    return [str(h).strip() for h in header_row if h is not None and str(h).strip()]


def extract_headers_from_path(path: Path, filename: str) -> list[str]:
    kind = sniff_kind(filename)
    if kind == "csv":
        with path.open("r", encoding="utf-8-sig", newline="", errors="replace") as handle:
            reader = csv.reader(handle)
            for row in reader:
                return [str(h).strip() for h in row if h is not None and str(h).strip()]
        return []
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    header_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True))
    wb.close()
    return [str(h).strip() for h in header_row if h is not None and str(h).strip()]


def iter_data_rows(path: Path, filename: str) -> Iterator[tuple[int, list]]:
    """Yield (1-based Excel row number, values) for data rows. Header is row 1."""
    csv_path = path
    tmp_csv: Path | None = None
    if sniff_kind(filename) == "xlsx":
        tmp_csv = _xlsx_to_csv(path)
        csv_path = tmp_csv
    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="", errors="replace") as handle:
            reader = csv.reader(handle)
            header = next(reader, None)
            if header is None:
                return
            excel_row = 1
            for raw in reader:
                excel_row += 1
                if not any(cell not in (None, "") for cell in raw):
                    continue
                yield excel_row, list(raw)
    finally:
        if tmp_csv is not None:
            tmp_csv.unlink(missing_ok=True)


def _xlsx_to_csv(path: Path) -> Path:
    handle, name = tempfile.mkstemp(suffix=".csv")
    out = Path(name)
    import os
    os.close(handle)
    try:
        import polars as pl

        frame = pl.read_excel(str(path), engine="calamine", infer_schema_length=0)
        frame.write_csv(out)
        return out
    except Exception:
        logger.exception("calamine/polars XLSX convert failed; falling back to openpyxl read_only")
        return _xlsx_to_csv_openpyxl(path, out)


def _xlsx_to_csv_openpyxl(src: Path, dest: Path) -> Path:
    wb = load_workbook(src, read_only=True, data_only=True)
    ws = wb.active
    with dest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        for row in ws.iter_rows(values_only=True):
            writer.writerow(["" if cell is None else cell for cell in row])
    wb.close()
    return dest
