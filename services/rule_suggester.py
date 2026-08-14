"""Suggest validation rules from column names + sample values.

Pipeline: heuristics → catalog cosine (if silent) → one batched LLM call for
ambiguous leftovers → constraint pass. Never sets flag_key. Never writes DB.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable

import numpy as np

from services import bedrock_llm, embedding_service, regex_generator
from services.rule_templates import SEED_TEMPLATES, embed_text

logger = logging.getLogger(__name__)

SIM_FLOOR = 0.45
SIM_CONFIDENT = 0.65
TOP_K = 3
MAX_SAMPLES = 20
MAX_LLM_FIELDS = 40
LLM_SAMPLE_CHARS = 40

_EMAIL_NAME = re.compile(r"(e[\s_-]*mail|smtp\s*addr|smtpaddr)")
_MOBILE_NAME = re.compile(
    r"\b(mobile|phone|telefon|cellphone|telf[12]?)\b|\btel\b|contact\s*(no|num|number)"
)
_DATE_NAME = re.compile(r"\b(date|budat|bldat|gebdt|dob|datum|audat|fkdat|lfdat)\b")
_AMOUNT_NAME = re.compile(
    r"\b(amount|netwr|dmbtr|wrbtr|price|net value|qty|quantity|menge|labst|kwmeng)\b"
)
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[t T].*)?$")
_EU_DATE = re.compile(r"^\d{1,2}[./]\d{1,2}[./]\d{2,4}$")
_INT_RE = re.compile(r"^[+-]?\d+$")
_DEC_RE = re.compile(r"^[+-]?\d+[.,]\d+$")
_PHONE_DIGITS = re.compile(r"\d+")
_BOOL_VALUES = {"x", "true", "false", "yes", "no", "y", "n", "1", "0"}

SYSTEM_PROMPT = (
    "You pick validation rule templates for source-file columns in an SAP "
    "data-migration tool. Each field has a name, sample values, and up to 3 "
    "candidate templates already ranked by embedding similarity. "
    "Return ONLY JSON: {\"picks\": [{\"field_name\": \"...\", "
    "\"template\": \"<template name or null>\"}]}. "
    "Use a template name from the candidates, or null if none fit. "
    "Never invent a template. Never mark a field as a business key. "
    "Include every field you were given, no more, no fewer. "
    "No markdown fences, no extra keys."
)


def suggest_rules(
    fields: list[dict[str, Any]],
    templates: list[dict[str, Any]] | None = None,
    *,
    embed_fn: Callable[[list[str]], np.ndarray] | None = None,
    chat_fn: Callable[..., str] | None = None,
    regex_fn: Callable[[str, str], str] | None = None,
) -> dict[str, Any]:
    """Return {suggestions: [...], warning: str|None}. Does not write validation_fields."""
    catalog = templates if templates is not None else [dict(t) for t in SEED_TEMPLATES]
    catalog = [t for t in catalog if t.get("active", True)]
    embed = embed_fn or embedding_service.embed_texts
    chat = chat_fn or bedrock_llm.chat
    make_regex = regex_fn or regex_generator.generate_regex

    suggestions: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen: set[str] = set()

    for raw in fields:
        name = (raw.get("field_name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        samples = _clean_samples(raw.get("samples") or [])
        exact = _exact_alias_match(name, catalog)
        if exact is not None:
            suggestions.append(_finalize(name, exact, "catalog", make_regex))
            continue
        hit = _heuristic(name, samples)
        if hit is not None:
            suggestions.append(_finalize(name, hit, "heuristic", make_regex))
            continue
        pending.append({"field_name": name, "samples": samples})

    catalog_hits: list[tuple[dict[str, Any], list[tuple[dict[str, Any], float]]]] = []
    ambiguous: list[tuple[dict[str, Any], list[tuple[dict[str, Any], float]]]] = []

    if pending:
        try:
            retrieved = _retrieve(pending, catalog, embed)
        except Exception:
            logger.exception("catalog embedding retrieve failed")
            warnings.append(
                "Could not load catalog embeddings; applied name and sample heuristics only."
            )
            retrieved = []

        for field, cands in retrieved:
            if not cands:
                continue
            top_score = cands[0][1]
            second = cands[1][1] if len(cands) > 1 else 0.0
            confident = top_score >= SIM_CONFIDENT and (top_score - second) >= 0.08
            if confident:
                catalog_hits.append((field, cands))
            elif top_score >= SIM_FLOOR:
                ambiguous.append((field, cands))

        for field, cands in catalog_hits:
            suggestions.append(
                _finalize(field["field_name"], cands[0][0], "catalog", make_regex)
            )

        llm_batch = ambiguous[:MAX_LLM_FIELDS]
        skipped_ambiguous = ambiguous[MAX_LLM_FIELDS:]
        llm_picks: dict[str, str | None] = {}
        if llm_batch:
            try:
                llm_picks = _llm_pick(llm_batch, chat)
            except Exception:
                logger.exception("batched LLM rule pick failed")
                warnings.append(
                    "Could not reach the language model; applied name, sample, "
                    "and catalog matches only."
                )
                llm_picks = {}

        for field, cands in llm_batch:
            name = field["field_name"]
            picked = llm_picks.get(name)
            tmpl = _template_by_name(cands, picked) if picked else None
            if tmpl is None and cands and cands[0][1] >= SIM_FLOOR and name not in llm_picks:
                # invalid/missing LLM output: keep embedding top-1
                tmpl = cands[0][0]
                source = "catalog"
            elif tmpl is None and picked is None:
                continue
            elif tmpl is None:
                continue
            else:
                source = "llm"
            suggestions.append(_finalize(name, tmpl, source, make_regex))

        for field, cands in skipped_ambiguous:
            if cands and cands[0][1] >= SIM_FLOOR:
                suggestions.append(
                    _finalize(field["field_name"], cands[0][0], "catalog", make_regex)
                )

    warning = warnings[0] if warnings else None
    return {"suggestions": suggestions, "warning": warning}


def merge_into_existing(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Replace AI/default rows; never overwrite rule_source=user; never take AI flag_key."""
    by_name = {item["field_name"]: item for item in incoming}
    out: list[dict[str, Any]] = []
    for row in existing:
        name = row.get("field_name")
        if row.get("rule_source") == "user":
            out.append(row)
            continue
        suggestion = by_name.get(name)
        if not suggestion:
            out.append(row)
            continue
        merged = {**row, **suggestion}
        merged["flag_key"] = bool(row.get("flag_key"))
        merged["rule_source"] = "ai"
        out.append(merged)
    return out


def _clean_samples(samples: list[Any]) -> list[str]:
    out: list[str] = []
    for value in samples:
        text = str(value).strip() if value is not None else ""
        if not text:
            continue
        out.append(text[:200])
        if len(out) >= MAX_SAMPLES:
            break
    return out


def _heuristic(name: str, samples: list[str]) -> dict[str, Any] | None:
    norm = _norm_name(name)
    if _EMAIL_NAME.search(norm) or _samples_email(samples):
        return _template_named("email") or _synthetic(flag_email=True)
    if _MOBILE_NAME.search(norm) or _samples_mobile(samples):
        return _template_named("mobile") or _synthetic(flag_mobile=True)
    if _DATE_NAME.search(norm) or _samples_date(samples):
        return _template_named("posting_date") or _synthetic(flag_date=True)
    if _samples_bool(samples):
        return _template_named("boolean_flag") or _synthetic(data_type="boolean")
    # Digit-only samples are not enough: SAP CHAR/NUMC keys (VBELN, KUNNR) look numeric.
    if _AMOUNT_NAME.search(norm):
        numeric = _samples_numeric_kind(samples)
        if numeric == "decimal":
            return _template_named("amount") or _synthetic(data_type="decimal", decimal_length=2)
        if numeric == "int":
            return _synthetic(data_type="int")
    return None


def _exact_alias_match(name: str, catalog: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Match a header to an official SAP field name or alias (CHAR lengths included)."""
    norm = _norm_name(name)
    compact = norm.replace(" ", "")
    if not compact:
        return None
    index: dict[str, dict[str, Any]] = {}
    for tmpl in catalog:
        keys = [_norm_name(str(tmpl.get("name") or ""))]
        for part in str(tmpl.get("aliases") or "").split(","):
            keys.append(_norm_name(part))
        for key in keys:
            if len(key) < 2:
                continue
            if key not in index:
                index[key] = tmpl
            compact_key = key.replace(" ", "")
            if compact_key and compact_key not in index:
                index[compact_key] = tmpl
    return index.get(norm) or index.get(compact)


def _norm_name(name: str) -> str:
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", name or "")
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _samples_email(samples: list[str]) -> bool:
    if len(samples) < 2:
        return False
    hits = sum(1 for s in samples if "@" in s and "." in s.rsplit("@", 1)[-1])
    return hits / len(samples) >= 0.5


def _samples_mobile(samples: list[str]) -> bool:
    if len(samples) < 2:
        return False
    hits = 0
    for s in samples:
        digits = "".join(_PHONE_DIGITS.findall(s))
        if 10 <= len(digits) <= 12:
            hits += 1
    return hits / len(samples) >= 0.6


def _samples_date(samples: list[str]) -> bool:
    if len(samples) < 2:
        return False
    hits = sum(1 for s in samples if _ISO_DATE.match(s) or _EU_DATE.match(s))
    return hits / len(samples) >= 0.5


def _samples_bool(samples: list[str]) -> bool:
    if len(samples) < 3:
        return False
    return all(s.strip().lower() in _BOOL_VALUES for s in samples)


def _samples_numeric_kind(samples: list[str]) -> str | None:
    if len(samples) < 3:
        return None
    cleaned = [s.replace(" ", "").replace("'", "") for s in samples]
    if all(_INT_RE.match(s) for s in cleaned):
        return "int"
    if all(_INT_RE.match(s) or _DEC_RE.match(s) for s in cleaned):
        if any(_DEC_RE.match(s) for s in cleaned):
            return "decimal"
        return "int"
    return None


def _template_named(name: str) -> dict[str, Any] | None:
    for item in SEED_TEMPLATES:
        if item["name"] == name:
            return dict(item)
    return None


def _synthetic(**kwargs: Any) -> dict[str, Any]:
    base = {
        "name": None,
        "aliases": "",
        "flag_email": False,
        "flag_mobile": False,
        "flag_date": False,
        "flag_mandatory": False,
        "flag_null": False,
        "flag_special_chars": False,
        "case_format": None,
        "data_type": "string",
        "max_length": None,
        "decimal_length": None,
        "regex_prompt": None,
    }
    base.update(kwargs)
    return base


def _retrieve(
    fields: list[dict[str, Any]],
    catalog: list[dict[str, Any]],
    embed_fn: Callable[[list[str]], np.ndarray],
) -> list[tuple[dict[str, Any], list[tuple[dict[str, Any], float]]]]:
    if not catalog:
        return []
    field_texts = [
        f"{f['field_name']} {' '.join(f['samples'][:5])}".strip() for f in fields
    ]
    catalog_texts = [embed_text(t) for t in catalog]
    matrix = embed_fn(field_texts + catalog_texts)
    if matrix.size == 0:
        return []
    field_emb = matrix[: len(field_texts)]
    cat_emb = matrix[len(field_texts) :]
    # Rows are already L2-normalized by embed_texts.
    sims = field_emb @ cat_emb.T
    k = min(TOP_K, len(catalog))
    out: list[tuple[dict[str, Any], list[tuple[dict[str, Any], float]]]] = []
    for i, field in enumerate(fields):
        row = sims[i]
        top_idx = np.argsort(-row)[:k]
        cands: list[tuple[dict[str, Any], float]] = []
        for j in top_idx:
            score = float(row[j])
            if score < SIM_FLOOR:
                continue
            cands.append((catalog[int(j)], score))
        out.append((field, cands))
    return out


def _llm_pick(
    batch: list[tuple[dict[str, Any], list[tuple[dict[str, Any], float]]]],
    chat_fn: Callable[..., str],
) -> dict[str, str | None]:
    payload = {
        "fields": [
            {
                "field_name": field["field_name"],
                "samples": [s[:LLM_SAMPLE_CHARS] for s in field["samples"][:8]],
                "candidates": [
                    {
                        "template": tmpl["name"],
                        "aliases": tmpl.get("aliases") or "",
                        "similarity": round(score, 4),
                    }
                    for tmpl, score in cands
                ],
            }
            for field, cands in batch
        ]
    }
    raw = chat_fn(SYSTEM_PROMPT, json.dumps(payload), max_tokens=2000)
    raw = bedrock_llm.strip_markdown_fences(raw)
    data = json.loads(raw)
    picks = data.get("picks") if isinstance(data, dict) else data
    if not isinstance(picks, list):
        raise ValueError("LLM returned no picks array")
    allowed = {field["field_name"] for field, _ in batch}
    out: dict[str, str | None] = {}
    for item in picks:
        if not isinstance(item, dict):
            continue
        name = item.get("field_name")
        if name not in allowed:
            continue
        tmpl = item.get("template")
        out[name] = tmpl if isinstance(tmpl, str) and tmpl.strip() else None
    return out


def _template_by_name(
    cands: list[tuple[dict[str, Any], float]],
    name: str,
) -> dict[str, Any] | None:
    wanted = name.strip().lower()
    for tmpl, _score in cands:
        if (tmpl.get("name") or "").lower() == wanted:
            return tmpl
    return None


def _finalize(
    field_name: str,
    template: dict[str, Any],
    source: str,
    regex_fn: Callable[[str, str], str],
) -> dict[str, Any]:
    flag_email = bool(template.get("flag_email"))
    flag_mobile = bool(template.get("flag_mobile"))
    flag_date = bool(template.get("flag_date"))
    if flag_email:
        flag_mobile = False
        flag_date = False
    elif flag_mobile:
        flag_date = False

    regex = None
    regex_prompt = template.get("regex_prompt") or None
    if regex_prompt:
        try:
            regex = regex_fn(field_name, regex_prompt)
        except Exception:
            logger.info("regex generation failed for field %s; omitting pattern", field_name)
            regex = None

    return {
        "field_name": field_name,
        "flag_key": False,
        "flag_mandatory": bool(template.get("flag_mandatory")),
        "flag_null": bool(template.get("flag_null")),
        "flag_email": flag_email,
        "flag_mobile": flag_mobile,
        "flag_date": flag_date,
        "flag_special_chars": bool(template.get("flag_special_chars")),
        "case_format": template.get("case_format"),
        "data_type": template.get("data_type") or "string",
        "max_length": template.get("max_length"),
        "decimal_length": template.get("decimal_length"),
        "regex": regex,
        "regex_prompt": regex_prompt,
        "rule_source": "ai",
        "suggestion_source": source,
        "template_name": template.get("name"),
    }
