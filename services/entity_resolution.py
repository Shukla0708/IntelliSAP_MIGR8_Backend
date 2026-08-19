"""Duplicate / entity resolution before SAP load.

Fuzzy-matches source rows against each other on name + city + tax id using
blocking keys and character n-gram similarity. LLM stays off the row path.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from services import file_stream

MAX_ROWS = 50_000
MAX_GROUPS = 50
MAX_BLOCK = 80
MAX_MEMBERS = 8
HIGH_SIM = 0.88
LIKELY_SIM = 0.74

_LEGAL = frozenset({
    "inc", "incorporated", "ltd", "limited", "llc", "gmbh", "ag", "sa", "sas",
    "bv", "nv", "oy", "ab", "plc", "corp", "corporation", "co", "company",
    "pty", "pvt", "private", "llp", "kg", "ohg",
})
_NAME_ALIASES = frozenset({
    "name", "name1", "name2", "customername", "custname", "company",
    "companyname", "vendorname", "partnername", "businessname", "legalname",
    "accountname", "soldtoname", "customer",
})
_CITY_ALIASES = frozenset({
    "city", "ort01", "ort", "town", "place", "locality", "stadt",
})
_TAX_ALIASES = frozenset({
    "tax", "taxid", "taxnumber", "stcd1", "stcd2", "vat", "vatid", "vatno",
    "gstin", "pan", "tin", "ein", "abn", "siren", "cif",
})
_ALNUM = re.compile(r"[^a-z0-9]+")


def scan_file(path: Path, filename: str) -> dict:
    headers = file_stream.extract_headers_from_path(path, filename)
    return find_duplicate_groups(headers, file_stream.iter_data_rows(path, filename))


def resolve_columns(headers: list[str]) -> dict:
    found: dict[str, str | None] = {"name": None, "city": None, "taxId": None}
    for header in headers:
        key = _alnum(header)
        if not found["name"] and (key in _NAME_ALIASES or key.endswith("name")):
            found["name"] = header
        elif not found["city"] and key in _CITY_ALIASES:
            found["city"] = header
        elif not found["taxId"] and (
            key in _TAX_ALIASES or "tax" in key or key.startswith("stcd") or "vat" in key
        ):
            found["taxId"] = header
    return found


def find_duplicate_groups(
    headers: list[str],
    rows: Iterable[tuple[int, list]],
) -> dict:
    """Return a review payload of likely duplicate groups.

    `rows` are `(1-based excel row number, values)` data rows (header already skipped).
    """
    columns = resolve_columns(headers)
    index = {_alnum(h): i for i, h in enumerate(headers)}

    def cell(values: list, header: str | None) -> str:
        if not header:
            return ""
        pos = index.get(_alnum(header))
        if pos is None or pos >= len(values) or values[pos] is None:
            return ""
        return str(values[pos]).strip()

    if not columns.get("name") and not columns.get("taxId"):
        return {
            "scannedRows": 0,
            "skippedReason": (
                "No name or tax-id column found. Add a Name / NAME1 or Tax / STCD1 "
                "column to scan for KNA1 duplicates."
            ),
            "columns": columns,
            "groupCount": 0,
            "rowCount": 0,
            "groups": [],
        }

    records: list[dict] = []
    for row_number, values in rows:
        if len(records) >= MAX_ROWS:
            break
        name = cell(values, columns.get("name"))
        city = cell(values, columns.get("city"))
        tax = cell(values, columns.get("taxId"))
        if not name and not tax:
            continue
        records.append({
            "row": row_number,
            "name": name,
            "city": city,
            "taxId": tax,
            "block": _block_key(name, city, tax),
            "nameKey": _entity_key(name),
            "cityKey": _alnum(city),
            "taxKey": _alnum(tax),
        })

    groups = _cluster(records)
    groups.sort(key=lambda g: (0 if g["confidence"] == "high" else 1, -len(g["rows"])))
    groups = groups[:MAX_GROUPS]
    return {
        "scannedRows": len(records),
        "skippedReason": None,
        "columns": columns,
        "groupCount": len(groups),
        "rowCount": sum(len(g["rows"]) for g in groups),
        "groups": groups,
    }


def ngram_similarity(left: str, right: str, n: int = 3) -> float:
    """Cosine of character n-grams — a local embedding stand-in."""
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    a = _ngrams(left, n)
    b = _ngrams(right, n)
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / math.sqrt(len(a) * len(b))


def _cluster(records: list[dict]) -> list[dict]:
    parent = list(range(len(records)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    buckets: dict[str, list[int]] = defaultdict(list)
    tax_index: dict[str, list[int]] = defaultdict(list)
    for idx, rec in enumerate(records):
        buckets[rec["block"]].append(idx)
        if rec["taxKey"]:
            tax_index[rec["taxKey"]].append(idx)

    pair_reason: dict[tuple[int, int], tuple[str, str]] = {}

    for ids in tax_index.values():
        if len(ids) < 2:
            continue
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a, b = ids[i], ids[j]
                union(a, b)
                pair_reason[_pair(a, b)] = ("high", "Same tax id")

    for ids in buckets.values():
        if len(ids) < 2:
            continue
        limited = ids[:MAX_BLOCK]
        for i in range(len(limited)):
            for j in range(i + 1, len(limited)):
                a, b = limited[i], limited[j]
                reason = _pair_match(records[a], records[b])
                if reason is None:
                    continue
                union(a, b)
                key = _pair(a, b)
                if key not in pair_reason or reason[0] == "high":
                    pair_reason[key] = reason

    clustered: dict[int, list[int]] = defaultdict(list)
    for idx in range(len(records)):
        clustered[find(idx)].append(idx)

    groups: list[dict] = []
    for members in clustered.values():
        if len(members) < 2:
            continue
        confidence = "likely"
        reason = "Similar name and city"
        for i, a in enumerate(members):
            for b in members[i + 1 :]:
                tagged = pair_reason.get(_pair(a, b))
                if tagged and tagged[0] == "high":
                    confidence = "high"
                    reason = tagged[1]
        groups.append({
            "reason": reason,
            "confidence": confidence,
            "rows": [
                {
                    "row": records[i]["row"],
                    "name": records[i]["name"],
                    "city": records[i]["city"],
                    "taxId": records[i]["taxId"],
                }
                for i in members[:MAX_MEMBERS]
            ],
        })
    return groups


def _pair_match(left: dict, right: dict) -> tuple[str, str] | None:
    if left["taxKey"] and left["taxKey"] == right["taxKey"]:
        return "high", "Same tax id"
    name_sim = ngram_similarity(left["nameKey"], right["nameKey"])
    if not left["nameKey"] or not right["nameKey"] or name_sim < LIKELY_SIM:
        return None
    same_city = bool(left["cityKey"] and left["cityKey"] == right["cityKey"])
    if name_sim >= HIGH_SIM and (same_city or not left["cityKey"] or not right["cityKey"]):
        return "high", "Near-identical name"
    if name_sim >= LIKELY_SIM and same_city:
        return "likely", "Similar name in the same city"
    if name_sim >= HIGH_SIM:
        return "likely", "Similar name"
    return None


def _ngrams(text: str, n: int) -> set[str]:
    padded = f"  {text}  "
    return {padded[i : i + n] for i in range(max(len(padded) - n + 1, 0))}


def _block_key(name: str, city: str, tax: str) -> str:
    tax_key = _alnum(tax)
    if tax_key:
        return f"tax:{tax_key}"
    return f"{_alnum(name)[:4]}|{_alnum(city)[:4]}"


def _entity_key(name: str) -> str:
    tokens = [t for t in _ALNUM.split(name.lower()) if t and t not in _LEGAL]
    return "".join(tokens)


def _alnum(value: str) -> str:
    return "".join(ch for ch in (value or "").lower() if ch.isalnum())


def _pair(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)
