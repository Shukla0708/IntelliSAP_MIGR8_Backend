"""CSV streaming validation for large files."""
import csv
import io

from openpyxl import load_workbook

from services.excel_service import run_validation
from tests.test_composite_keys import _cfg


def _csv(headers, rows) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def test_csv_composite_duplicate():
    data = _csv(
        ["CustomerID", "OrderID", "Name"],
        [
            [1, "A", "Ann"],
            [1, "B", "Bob"],
            [1, "A", "Dee"],
        ],
    )
    result_bytes, stats, exceptions = run_validation(
        data,
        [_cfg("CustomerID", True), _cfg("OrderID", True), _cfg("Name")],
        filename="source.csv",
    )
    assert stats["invalid_rows"] == 1
    assert stats["valid_rows"] == 2
    wb = load_workbook(io.BytesIO(result_bytes))
    ws = wb.active
    assert ws.cell(row=1, column=4).value == "Validation_Failure_Reason"
    assert "Duplicate composite key" in (ws.cell(row=4, column=4).value or "")
