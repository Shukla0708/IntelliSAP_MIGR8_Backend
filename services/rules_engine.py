import re
from datetime import date, datetime

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MOBILE_RE = re.compile(r"^\+?[0-9]{7,15}$")
SPECIAL_CHARS_RE = re.compile(r"[^a-zA-Z0-9\s]")

DATE_FORMATS = (
    "%Y-%m-%d",
    "%d-%m-%Y",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%Y-%m-%d %H:%M:%S",  # openpyxl datetime → str(value)
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y%m%d",
    "%d%m%y" 
)


def normalize_raw(value) -> str:
    """Stable string form for comparisons (dates, blanks, Excel cells)."""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.isoformat()
    return "" if value is None else str(value).strip()


def normalize_key(value) -> str:
    """Canonical key form so Excel ints/floats match the same ID (1 and 1.0)."""
    if isinstance(value, bool):
        return normalize_raw(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return format(value, "g")
    raw = normalize_raw(value)
    if raw and raw[0].isdigit() or (raw.startswith("-") and len(raw) > 1):
        try:
            number = float(raw)
            if number.is_integer():
                return str(int(number))
            return format(number, "g")
        except ValueError:
            pass
    return raw


def is_empty_raw(raw: str) -> bool:
    return raw == "" or raw.lower() in ("null", "n/a", "none")


def validate_cell(value, field_cfg: dict, seen_keys: set | None) -> list[str]:
    """Returns a list of human-readable failure reasons for a single cell.

    Pass seen_keys=None to skip per-field uniqueness (used for composite keys).
    """
    reasons: list[str] = []

    # Excel date cells arrive as datetime/date, not "21-05-2024".
    # Normalize early so date + regex checks see a stable string.
    raw = normalize_raw(value)
    key_raw = normalize_key(value)

    is_empty = is_empty_raw(raw)

    if field_cfg["flag_key"] and is_empty:
        reasons.append("Key value is empty")
    elif field_cfg["flag_mandatory"] and is_empty:
        reasons.append("Mandatory field is empty")

    if field_cfg["flag_null"] and raw.lower() in ("null", "n/a"):
        reasons.append("Literal null/N-A value not allowed")

    if is_empty:
        return reasons  # nothing further to check on an empty cell

    dt = field_cfg["data_type"]
    if dt == "int" and not raw.lstrip("-").isdigit():
        reasons.append(f"Expected integer, got '{raw}'")
    elif dt == "decimal":
        try:
            float(raw)
        except ValueError:
            reasons.append(f"Expected decimal, got '{raw}'")
    elif dt == "boolean" and raw.lower() not in ("true", "false", "0", "1", "yes", "no"):
        reasons.append(f"Expected boolean, got '{raw}'")

    if field_cfg["max_length"] and len(raw) > field_cfg["max_length"]:
        reasons.append(f"Exceeds max length {field_cfg['max_length']}")

    if field_cfg["decimal_length"] is not None and dt == "decimal" and "." in raw:
        decimals = raw.split(".")[1]
        if len(decimals) > field_cfg["decimal_length"]:
            reasons.append(f"Exceeds decimal precision {field_cfg['decimal_length']}")

    cf = field_cfg["case_format"]
    if cf == "uppercase" and raw != raw.upper():
        reasons.append("Expected UPPERCASE")
    elif cf == "lowercase" and raw != raw.lower():
        reasons.append("Expected lowercase")
    elif cf == "camelCase" and (raw[:1].isupper() or " " in raw):
        reasons.append("Expected camelCase")

    if field_cfg["flag_email"] and not EMAIL_RE.match(raw):
        reasons.append("Invalid email format")

    if field_cfg["flag_mobile"] and not MOBILE_RE.match(raw):
        reasons.append("Invalid mobile number format")

    if field_cfg["flag_date"]:
        if not _is_valid_date(value, raw):
            reasons.append("Invalid date format")

    # Hyphens/slashes in dates are separators, not "special characters"
    if (
        field_cfg["flag_special_chars"]
        and not (field_cfg["flag_date"] and _is_valid_date(value, raw))
        and SPECIAL_CHARS_RE.search(raw)
    ):
        reasons.append("Contains disallowed special characters")

    compiled = field_cfg.get("_compiled_regex")
    pattern = field_cfg.get("regex")
    if compiled is not None or pattern:
        try:
            # fullmatch: entire cell must match (re.match only anchors at start).
            # Excel date cells are datetime objects — also try common display forms
            # so a DD-MM-YYYY regex still passes a real date cell.
            candidates = _string_forms_for_regex(value, raw)
            matcher = compiled.fullmatch if compiled is not None else (
                lambda c, p=pattern: re.fullmatch(p, c)
            )
            if not any(matcher(c) for c in candidates):
                reasons.append("Does not match configured rule")
        except re.error:
            pass  # malformed regex should never have been saved, but don't crash the run

    if field_cfg["flag_key"] and seen_keys is not None:
        if key_raw in seen_keys:
            reasons.append("Duplicate key value")
        else:
            seen_keys.add(key_raw)

    return reasons


def _is_valid_date(value, raw: str) -> bool:
    """Accept real date/datetime cells from Excel, or strings in known formats."""
    if isinstance(value, (datetime, date)):
        return True
    return any(_try_parse_date(raw, fmt) for fmt in DATE_FORMATS)


def _string_forms_for_regex(value, raw: str) -> list[str]:
    """String shapes to test a regex against (handles Excel datetime cells)."""
    if isinstance(value, datetime):
        d = value.date()
    elif isinstance(value, date):
        d = value
    else:
        return [raw]
    return list(dict.fromkeys([
        raw,
        d.isoformat(),
        d.strftime("%d-%m-%Y"),
        d.strftime("%m/%d/%Y"),
        d.strftime("%d/%m/%Y"),
        d.strftime("%Y-%m-%d %H:%M:%S"),
    ]))


def _try_parse_date(raw: str, fmt: str) -> bool:
    try:
        datetime.strptime(raw, fmt)
        return True
    except ValueError:
        return False
