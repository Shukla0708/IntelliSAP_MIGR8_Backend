"""Preload vs postload reconciliation.

The postload file is indexed once on its composite business key, then the
preload file is streamed a single time: mapped fields are compared, stats are
counted, the worst 50 discrepancies are kept, and the annotated preload report
is written in the same pass so no more than one file is ever held in memory.
"""

import heapq
import re
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import NamedTuple

from services.comparison_file_service import AnnotatedResultWriter, iter_data_rows

MAX_DISCREPANCIES = 50
KEY_DELIMITER = "\x1f"
ENTIRE_RECORD_LABEL = "Entire Record"
NOT_FOUND_LABEL = "NULL (Not Found)"

_SEVERITY_BY_TYPE = {
    "DROPPED_RECORD": "error",
    "EXTRA_RECORD": "error",
    "VALUE_MISMATCH": "warning",
    "FORMAT_CHANGE": "info",
}
_SEVERITY_RANK = {"error": 0, "warning": 1, "info": 2}


@dataclass(frozen=True)
class ColumnPair:
    """One preload column matched to its postload counterpart."""

    label: str
    preload_index: int
    postload_index: int


@dataclass(frozen=True)
class ComparePlan:
    preload_header: list[str]
    key_pairs: list[ColumnPair]
    value_pairs: list[ColumnPair]


class _PostloadRow(NamedTuple):
    row_number: int
    display_key: str
    values: tuple[str, ...]


def normalize_value(value) -> str:
    """Renders a cell the way it is compared and shown in the report."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, datetime):
        if value.time() == time.min:
            return value.date().isoformat()
        return value.isoformat(sep=" ")
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def values_equivalent(preload: str, postload: str) -> bool:
    """True when two rendered cells carry the same value, spelled differently.

    A load rewrites how a value is written without changing what it is: SAP's
    ALPHA conversion returns keys zero-padded (`100045` → `0000100045`), Excel
    may prefix an apostrophe to keep those zeros (`'0000100045`), amounts come
    back with decimals, grouping separators, a currency symbol or the minus
    sign trailing (`1000` → `$1,000.00`, `-100` → `100-`), and dates switch
    format. Those are the same value, so they are not reported as differences.

    Deliberately *not* covered: a numeric value against a blank, and case or
    punctuation differences in text — those stay visible (see
    `classify_difference`).
    """
    if preload == postload:
        return True

    preload_number = _as_decimal(preload)
    postload_number = _as_decimal(postload)
    if preload_number is not None or postload_number is not None:
        return (
            preload_number is not None
            and postload_number is not None
            and preload_number == postload_number
        )

    preload_dates = _temporal_forms(preload)
    if preload_dates:
        # Slash dates are ambiguous (05/01 is both Jan 5 and May 1), so each side
        # keeps every reading that parses and any shared one means agreement.
        return bool(preload_dates & _temporal_forms(postload))
    return False


def classify_difference(preload: str, postload: str) -> str | None:
    """None when the values agree, otherwise the difference type."""
    if values_equivalent(preload, postload):
        return None
    stripped = _alphanumeric(preload)
    if stripped and stripped == _alphanumeric(postload):
        return "FORMAT_CHANGE"
    return "VALUE_MISMATCH"


def canonical_key_part(text: str) -> str:
    """Join form of one business key column.

    Zero-padding has to be ignored here too, otherwise a preload `100045` and a
    postload `0000100045` never meet and both rows are reported missing. Only
    the numeric rule applies: keys are matched case-insensitively but otherwise
    literally, so an ambiguous date can never silently join two rows.
    """
    if text.isdigit():
        return text.lstrip("0") or "0"
    number = _as_decimal(text)
    if number is not None:
        return _decimal_text(number)
    return text.upper()


def build_plan(
    preload_header: list[str],
    postload_header: list[str],
    mapping_rows: list[dict] | None = None,
    business_key_preload: list[str] | None = None,
    business_key_postload: list[str] | None = None,
) -> ComparePlan:
    """Decides which columns are compared and which ones join the two files."""
    preload_index = _index_header(preload_header)
    postload_index = _index_header(postload_header)

    if mapping_rows:
        return _plan_from_mapping(preload_header, preload_index, postload_index, mapping_rows)
    return _plan_from_common_columns(
        preload_header,
        preload_index,
        postload_index,
        business_key_preload,
        business_key_postload,
    )


def run_comparison(
    preload_bytes: bytes, postload_bytes: bytes, plan: ComparePlan
) -> tuple[bytes, dict, list[dict]]:
    """Returns (annotated_report_bytes, stats, up to 50 discrepancies)."""
    postload_rows, total_postload_rows = _index_postload(postload_bytes, plan)

    writer = AnnotatedResultWriter(plan.preload_header)
    discrepancies = _TopDiscrepancies()
    matched_keys: set[str] = set()
    total_preload_rows = matched_records = different_count = dropped_count = 0

    for row_number, values in iter_data_rows(preload_bytes):
        total_preload_rows += 1
        key, display_key = _row_key(values, plan.key_pairs, side="preload")
        postload = postload_rows.get(key)
        red_columns: set[int] = set()
        details: list[str] = []

        if postload is None:
            dropped_count += 1
            red_columns = {pair.preload_index for pair in plan.key_pairs}
            details.append(f"{ENTIRE_RECORD_LABEL}: no postload record for this business key")
            discrepancies.add({
                "row_number": row_number,
                "business_key": display_key,
                "field_name": ENTIRE_RECORD_LABEL,
                "field_italic": True,
                "preload_value": "Present in preload",
                "postload_value": NOT_FOUND_LABEL,
                "difference_type": "DROPPED_RECORD",
                "severity": "error",
            })
        else:
            matched_keys.add(key)
            for position, pair in enumerate(plan.value_pairs):
                preload_value = normalize_value(_cell(values, pair.preload_index))
                postload_value = postload.values[position]
                difference = classify_difference(preload_value, postload_value)
                if difference is None:
                    continue
                red_columns.add(pair.preload_index)
                details.append(
                    f"{pair.label}: preload={preload_value} | postload={postload_value}"
                )
                discrepancies.add({
                    "row_number": row_number,
                    "business_key": display_key,
                    "field_name": pair.label,
                    "field_italic": False,
                    "preload_value": preload_value,
                    "postload_value": postload_value,
                    "difference_type": difference,
                    "severity": _SEVERITY_BY_TYPE[difference],
                })
            if red_columns:
                different_count += 1
            else:
                matched_records += 1

        writer.write_row(values, red_columns, "; ".join(details))

    extra_count = 0
    for key, row in postload_rows.items():
        if key in matched_keys:
            continue
        extra_count += 1
        discrepancies.add({
            "row_number": row.row_number,
            "business_key": row.display_key,
            "field_name": ENTIRE_RECORD_LABEL,
            "field_italic": True,
            "preload_value": NOT_FOUND_LABEL,
            "postload_value": "Present in postload",
            "difference_type": "EXTRA_RECORD",
            "severity": "error",
        })

    stats = {
        "total_preload_rows": total_preload_rows,
        "total_postload_rows": total_postload_rows,
        "matched_records": matched_records,
        "different_count": different_count,
        "missing_count": dropped_count + extra_count,
        "match_rate": (
            round((matched_records / total_preload_rows) * 100, 2)
            if total_preload_rows
            else 0.0
        ),
    }
    return writer.finish(), stats, discrepancies.results()


class _TopDiscrepancies:
    """Keeps the worst entries only: errors first, then warnings, then by row."""

    def __init__(self, limit: int = MAX_DISCREPANCIES):
        self._limit = limit
        self._heap: list[tuple[tuple[int, int, int], dict]] = []
        self._seq = 0

    def add(self, entry: dict) -> None:
        self._seq += 1
        # Inverted so the heap root is always the entry we would drop first.
        rank = (-_SEVERITY_RANK[entry["severity"]], -entry["row_number"], -self._seq)
        if len(self._heap) < self._limit:
            heapq.heappush(self._heap, (rank, entry))
        elif rank > self._heap[0][0]:
            heapq.heapreplace(self._heap, (rank, entry))

    def results(self) -> list[dict]:
        return [entry for _, entry in sorted(self._heap, key=lambda item: item[0], reverse=True)]


def _alphanumeric(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


_NUMERIC_CHARS = frozenset("0123456789.,+-() \u00a0'$€£¥₹\u2212\u2013")
_CURRENCY_CHARS = frozenset("$€£¥₹")
_GROUPED_THOUSANDS = re.compile(r"\d{1,3}(,\d{3})+")
# Cheap gate before strptime: text has to look like a date for parsing to be worth it.
_DATE_LIKE = re.compile(
    r"\d{1,4}[-./]\d{1,2}[-./]\d{1,4}([ T]\d{1,2}:\d{2}(:\d{2}(\.\d+)?)?)?"
)
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d.%m.%Y",   # SAP's classic output format
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%Y/%m/%d",
    "%d-%m-%Y",
    "%m-%d-%Y",
)
_TIME_SUFFIXES = ("", " %H:%M:%S", "T%H:%M:%S", " %H:%M", "T%H:%M", " %H:%M:%S.%f", "T%H:%M:%S.%f")


def _as_decimal(text: str) -> Decimal | None:
    """Parses a cell as a number, or None when it isn't one.

    Handles what loads do to numbers: zero padding, an Excel apostrophe that
    forces text, currency symbols, decimal noise, grouping separators, and a
    sign written in front, trailing (SAP), as accounting parentheses, or as a
    unicode minus. Exponent notation is left out on purpose so an id like `1E5`
    stays text.
    """
    if not text:
        return None
    if text[0] == "'":
        text = text[1:]
        if not text:
            return None
    if text.isdigit():  # fast path: the zero-padded key case
        return Decimal(text)
    if not _NUMERIC_CHARS.issuperset(text):
        return None

    body = (
        text.replace(" ", "")
        .replace("\u00a0", "")
        .replace("\u2212", "-")
        .replace("\u2013", "-")
    )
    body = body.strip("".join(_CURRENCY_CHARS))
    negative = False
    if body.startswith("(") and body.endswith(")"):
        negative = True
        body = body[1:-1]
    for sign_position in (-1, 0):  # trailing sign first, then leading
        if not body:
            return None
        sign = body[sign_position]
        if sign in "+-":
            negative ^= sign == "-"
            body = body[:-1] if sign_position == -1 else body[1:]

    if "," in body:
        if "." in body:
            if body.rfind(",") > body.rfind("."):  # 1.234,56 — comma is the decimal point
                body = body.replace(".", "").replace(",", ".")
            else:
                body = body.replace(",", "")
        elif _GROUPED_THOUSANDS.fullmatch(body):
            body = body.replace(",", "")
        else:
            body = body.replace(",", ".")

    if not body or body.count(".") > 1 or not body.replace(".", "").isdigit():
        return None
    try:
        value = Decimal(body)
    except InvalidOperation:
        return None
    return -value if negative else value


def _decimal_text(value: Decimal) -> str:
    """One spelling per numeric value: no padding, no trailing zeros, no exponent."""
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _temporal_forms(text: str) -> frozenset[str]:
    """Every date/datetime this cell could be, as ISO strings (empty if it isn't one)."""
    if not _DATE_LIKE.fullmatch(text):
        return frozenset()
    forms: set[str] = set()
    for date_format in _DATE_FORMATS:
        for suffix in _TIME_SUFFIXES:
            try:
                parsed = datetime.strptime(text, date_format + suffix)
            except ValueError:
                continue
            forms.add(
                parsed.date().isoformat()
                if parsed.time() == time.min
                else parsed.isoformat(sep=" ")
            )
            break
    return frozenset(forms)


def _normalize_column(name) -> str:
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def _index_header(header: list[str]) -> dict[str, int]:
    index: dict[str, int] = {}
    for position, name in enumerate(header):
        key = _normalize_column(name)
        if key and key not in index:
            index[key] = position
    return index


def _resolve_target_column(target_field: str, postload_index: dict[str, int]) -> int | None:
    """`target_field` is "{sap_table}.{sap_field}"; postload headers may use either form."""
    position = postload_index.get(_normalize_column(target_field))
    if position is not None:
        return position
    return postload_index.get(_normalize_column(target_field.rsplit(".", 1)[-1]))


def _plan_from_mapping(
    preload_header: list[str],
    preload_index: dict[str, int],
    postload_index: dict[str, int],
    mapping_rows: list[dict],
) -> ComparePlan:
    key_pairs: list[ColumnPair] = []
    value_pairs: list[ColumnPair] = []

    for row in mapping_rows:
        preload_position = preload_index.get(_normalize_column(row["source_field"]))
        postload_position = _resolve_target_column(row["target_field"], postload_index)
        if preload_position is None or postload_position is None:
            continue
        pair = ColumnPair(preload_header[preload_position], preload_position, postload_position)
        if row.get("is_key"):
            key_pairs.append(pair)
        else:
            value_pairs.append(pair)

    # Follow preload column order so composite keys read the way the file does.
    key_pairs.sort(key=lambda pair: pair.preload_index)
    value_pairs.sort(key=lambda pair: pair.preload_index)

    if not key_pairs:
        flagged = [row["source_field"] for row in mapping_rows if row.get("is_key")]
        if flagged:
            raise ValueError(
                "The mapping's key fields (" + ", ".join(flagged) + ") are missing from the "
                "uploaded files"
            )
        raise ValueError(
            "The selected mapping has no key field. Key fields come from the key column "
            "of the uploaded source schema, so re-run the mapping with keys flagged there."
        )
    if not value_pairs:
        raise ValueError(
            "The selected mapping has no non-key fields present in both uploaded files"
        )
    return ComparePlan(preload_header, key_pairs, value_pairs)


def _plan_from_common_columns(
    preload_header: list[str],
    preload_index: dict[str, int],
    postload_index: dict[str, int],
    business_key_preload: list[str] | None,
    business_key_postload: list[str] | None,
) -> ComparePlan:
    common: list[ColumnPair] = []
    for position, name in enumerate(preload_header):
        normalized = _normalize_column(name)
        if not normalized or preload_index.get(normalized) != position:
            continue
        postload_position = postload_index.get(normalized)
        if postload_position is None:
            continue
        common.append(ColumnPair(name, position, postload_position))

    if not common:
        raise ValueError(
            "The preload and postload files share no column names. Select a field mapping instead."
        )

    if business_key_preload:
        key_pairs = _explicit_key_pairs(
            preload_header,
            preload_index,
            postload_index,
            business_key_preload,
            business_key_postload,
        )
    else:
        key_pairs = [common[0]]

    key_positions = {pair.preload_index for pair in key_pairs}
    value_pairs = [pair for pair in common if pair.preload_index not in key_positions]
    if not value_pairs:
        raise ValueError("Every shared column is part of the business key, so nothing to compare")
    return ComparePlan(preload_header, key_pairs, value_pairs)


def _explicit_key_pairs(
    preload_header: list[str],
    preload_index: dict[str, int],
    postload_index: dict[str, int],
    keys_preload: list[str],
    keys_postload: list[str] | None,
) -> list[ColumnPair]:
    keys_postload = keys_postload or list(keys_preload)
    if len(keys_preload) != len(keys_postload):
        raise ValueError("The preload and postload business key lists must be the same length")

    pairs: list[ColumnPair] = []
    for preload_name, postload_name in zip(keys_preload, keys_postload):
        preload_position = preload_index.get(_normalize_column(preload_name))
        postload_position = postload_index.get(_normalize_column(postload_name))
        if preload_position is None:
            raise ValueError(f"Business key column '{preload_name}' is not in the preload file")
        if postload_position is None:
            raise ValueError(f"Business key column '{postload_name}' is not in the postload file")
        pairs.append(ColumnPair(preload_header[preload_position], preload_position, postload_position))
    return pairs


def _index_postload(postload_bytes: bytes, plan: ComparePlan) -> tuple[dict[str, _PostloadRow], int]:
    rows: dict[str, _PostloadRow] = {}
    total = 0
    for row_number, values in iter_data_rows(postload_bytes):
        total += 1
        key, display_key = _row_key(values, plan.key_pairs, side="postload")
        # Duplicate business keys in the postload file: the last row wins.
        rows[key] = _PostloadRow(
            row_number,
            display_key,
            tuple(normalize_value(_cell(values, pair.postload_index)) for pair in plan.value_pairs),
        )
    return rows, total


def _row_key(values: tuple, pairs: list[ColumnPair], *, side: str) -> tuple[str, str]:
    parts: list[str] = []
    display: list[str] = []
    for pair in pairs:
        index = pair.preload_index if side == "preload" else pair.postload_index
        text = normalize_value(_cell(values, index))
        parts.append(canonical_key_part(text))
        display.append(f"{pair.label}: {text}")
    return KEY_DELIMITER.join(parts), " | ".join(display)


def _cell(values: tuple, index: int):
    return values[index] if index < len(values) else None
