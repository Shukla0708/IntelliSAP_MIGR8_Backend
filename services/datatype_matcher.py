"""Rule-based datatype compatibility scoring for source -> SAP target fields.

Hardcoded SAP-type compatibility matrix as a first pass. Swap target: a
maintainable config-driven matrix, if the hardcoded groups below stop being
enough.
"""
from __future__ import annotations

# Each group is a set of type tokens (after normalization) considered
# compatible with each other. A pair found in the same group scores
# PARTIAL_MATCH_SCORE; an exact token match scores 100.
COMPATIBLE_GROUPS: list[set[str]] = [
    {"char", "string", "text", "varchar", "char1", "c"},
    {"numc", "int", "integer", "number", "num", "n"},
    {"dats", "date", "datetime", "timestamp"},
    {"curr", "dec", "decimal", "float", "numeric", "double", "p"},
    {"flag", "boolean", "bool", "x"},
]

PARTIAL_MATCH_SCORE = 60.0
NO_MATCH_SCORE = 0.0
EXACT_MATCH_SCORE = 100.0


def _normalize(datatype: str) -> str:
    return "".join(str(datatype).strip().lower().split())


def datatype_match_score(source_datatype: str | None, target_datatype: str | None) -> float | None:
    """Returns 0-100, or None if either datatype is unknown/missing."""
    if not source_datatype or not target_datatype:
        return None

    source = _normalize(source_datatype)
    target = _normalize(target_datatype)

    if source == target:
        return EXACT_MATCH_SCORE

    for group in COMPATIBLE_GROUPS:
        if source in group and target in group:
            return PARTIAL_MATCH_SCORE

    return NO_MATCH_SCORE
