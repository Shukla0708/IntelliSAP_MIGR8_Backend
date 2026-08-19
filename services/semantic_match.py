"""Semantic near-match for comparison discrepancies.

Cheap legal-form / abbreviation heuristics run on the row path. A single
batched LLM call may reclassify remaining VALUE_MISMATCH rows in the stored
top-50 only — never every row in the file.
"""
from __future__ import annotations

import json
import logging
import re

from config import settings
from services import bedrock_llm

logger = logging.getLogger(__name__)

LEGAL_FORMS = frozenset({
    "inc", "incorporated", "ltd", "limited", "llc", "gmbh", "ag", "sa", "sas",
    "bv", "nv", "oy", "ab", "plc", "corp", "corporation", "co", "company",
    "pty", "pvt", "private", "llp", "kg", "ohg", "llc.", "inc.",
})
ABBREVS = {
    "inc": "incorporated",
    "intl": "international",
    "corp": "corporation",
    "co": "company",
    "ltd": "limited",
    "st": "street",
    "rd": "road",
    "ave": "avenue",
    "blvd": "boulevard",
    "dept": "department",
    "mfg": "manufacturing",
}
_TOKEN = re.compile(r"[a-z0-9]+")

_LLM_SYSTEM = (
    "You decide whether two SAP preload/postload cell values are the same "
    "entity written differently (legal form, abbreviation, Incorporated vs Inc, "
    "GmbH vs LLC). Return ONLY JSON: "
    '{"matches":[{"index":0,"match":true}]}. '
    "match=true only when a human would treat them as the same organisation or "
    "place. Different companies, ids, amounts, or dates are false. "
    "Include every index you were given."
)


def is_semantic_match(preload: str, postload: str) -> bool:
    """True when two strings differ only by legal form or known abbreviations."""
    left = _canonical(preload)
    right = _canonical(postload)
    if not left or not right:
        return False
    return left == right


def reclassify_discrepancies(entries: list[dict]) -> list[dict]:
    """Upgrade remaining VALUE_MISMATCH rows in the top-50 via one LLM batch."""
    candidates = [
        (idx, entry)
        for idx, entry in enumerate(entries)
        if entry.get("difference_type") == "VALUE_MISMATCH"
        and _looks_like_text(entry.get("preload_value"), entry.get("postload_value"))
    ]
    if not candidates:
        return entries

    payload = [
        {
            "index": i,
            "preload": (entry.get("preload_value") or "")[:80],
            "postload": (entry.get("postload_value") or "")[:80],
            "field": entry.get("field_name"),
        }
        for i, (_, entry) in enumerate(candidates)
    ]
    try:
        raw = bedrock_llm.chat(
            _LLM_SYSTEM,
            json.dumps({"pairs": payload}),
            max_tokens=400,
            model_id=settings.bedrock_haiku_model_id,
            purpose="semantic_match",
            use_cache=True,
        )
        parsed = json.loads(bedrock_llm.strip_markdown_fences(raw or ""))
        hits = {
            int(item["index"])
            for item in (parsed.get("matches") or [])
            if item.get("match") is True
        }
    except Exception:
        logger.info("semantic-match LLM skipped; keeping VALUE_MISMATCH")
        return entries

    for i, (entry_index, entry) in enumerate(candidates):
        if i in hits:
            entry["difference_type"] = "SEMANTIC_MATCH"
            entry["severity"] = "info"
            entries[entry_index] = entry
    return entries


def _canonical(value: str) -> str:
    tokens = _TOKEN.findall((value or "").lower())
    expanded: list[str] = []
    for token in tokens:
        if token in LEGAL_FORMS:
            continue
        expanded.append(ABBREVS.get(token, token))
    return "".join(expanded)


def _looks_like_text(preload, postload) -> bool:
    left = str(preload or "")
    right = str(postload or "")
    if not left or not right:
        return False
    if left.replace(".", "", 1).replace("-", "", 1).isdigit():
        return False
    if right.replace(".", "", 1).replace("-", "", 1).isdigit():
        return False
    return any(ch.isalpha() for ch in left) and any(ch.isalpha() for ch in right)
