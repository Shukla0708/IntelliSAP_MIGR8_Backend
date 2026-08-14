"""SAP DDIC metadata used as the source of truth for AI rule suggestions.

Loads public table dictionaries from data/sap_ddic_catalog.json
(datapanda.eu / leanx.eu — not SAP copyrighted ABAP source).

CHAR / NUMC identifiers stay character fields (with official lengths) even when
sample values look numeric. Templates never set flag_key.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any

_CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "sap_ddic_catalog.json"

# English / spreadsheet headers that must exact-match official CHAR lengths.
EXTRA_ALIASES: dict[str, str] = {
    "VBELN": "sales document, sales order, so number, document number, doc number, billing document, invoice number, delivery, delivery number",
    "AUART": "doc type, document type, order type",
    "VKORG": "sales org, sales organization, sales organisation",
    "VTWEG": "distr chan, dist channel, distribution channel",
    "SPART": "division, division code",
    "KUNNR": "sold-to, sold to, customer, customer number, customer id",
    "AUDAT": "order date, document date",
    "NETWR": "amount, net value, net price",
    "WAERK": "currency, document currency",
    "VKBUR": "sales office",
    "VKGRP": "sales group",
    "POSNR": "item, item number, line item",
    "MATNR": "material, material number, sku, article",
    "KWMENG": "qty, quantity, order quantity",
    "VRKME": "sales unit, uom",
    "WERKS": "plant, plant code",
    "FKART": "billing type",
    "FKDAT": "billing date, invoice date",
    "LFDAT": "delivery date",
    "NAME1": "name, customer name, vendor name, name1",
    "NAME2": "name2",
    "ORT01": "city, town",
    "PSTLZ": "postal, postal code, zip, zipcode, pincode, pin code",
    "LAND1": "country, country key, country code",
    "REGIO": "region, state, province, state code",
    "STRAS": "street, address, address line",
    "TELF1": "phone, telephone, mobile, telf1",
    "TELF2": "telf2, cellphone",
    "SPRAS": "language, language key, language code",
    "STCEG": "vat, gstin, tax number, vat number",
    "LOEVM": "deletion flag, deletion indicator, loevm",
    "SMTP_ADDR": "email, e-mail, mail, smtpaddr, smtp addr, customer email",
    "LIFNR": "vendor, vendor number, vendor id, supplier",
    "MTART": "material type",
    "MEINS": "base uom, unit of measure",
    "BELNR": "accounting document, fi document, doc number",
    "BUKRS": "company code, company",
    "GJAHR": "fiscal year, year",
    "BLART": "fi doc type, accounting document type",
    "BLDAT": "document date, bldat",
    "BUDAT": "posting date, budat",
    "WAERS": "currency, currency key, currency code",
    "WRBTR": "amount, wrbtr",
    "DMBTR": "dmbtr, amount in lc",
    "HKONT": "gl account, account number",
    "KOSTL": "cost center",
    "BANKN": "bank account, bankn, bank account number",
    "BANKL": "bank key, bankl",
    "IBAN": "iban, iban number, international bank account",
    "SWIFT": "swift, bic, swift code, bic code",
    "EBELN": "po number, purchase order, purchasing document",
    "EBELP": "po item, purchase order item",
    "MBLNR": "material document, mat doc",
    "LGORT": "storage location, sloc",
    "SAKNR": "gl account, account number, gl account number",
}

# Fields not always present in the scraped tables (e.g. IBAN lives on TIBAN).
EXTRA_FIELDS: list[dict[str, Any]] = [
    {
        "table": "TIBAN",
        "field": "IBAN",
        "description": "IBAN",
        "datatype": "CHAR",
        "length": 34,
        "decimals": 0,
    },
]

_UPPERCASE_FIELDS = {
    "VKORG", "VTWEG", "SPART", "AUART", "BUKRS", "WERKS", "WAERS", "WAERK",
    "SPRAS", "LAND1", "BLART", "FKART", "MTART", "MEINS", "VRKME", "GEWEI",
    "VKBUR", "VKGRP", "IBAN", "LGORT",
}

# Low priority number = included in embedding retrieve (exact-match still uses all).
EMBED_PRIORITY_MAX = 500
CORE_PRIORITY_FIELDS = set(EXTRA_ALIASES)


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, Any]:
    if not _CATALOG_PATH.is_file():
        return {"source": "", "tables": [], "fields": []}
    return json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))


def templates_from_ddic() -> list[dict[str, Any]]:
    catalog = load_catalog()
    rows = list(catalog.get("fields") or [])
    rows.extend(EXTRA_FIELDS)
    collapsed = _collapse_by_field(rows)
    templates: list[dict[str, Any]] = []
    for i, item in enumerate(collapsed):
        field = item["field"]
        priority = 20 if field in CORE_PRIORITY_FIELDS else 1000 + i
        templates.append(
            _ddic_row(
                item["tables"],
                field,
                item["description"],
                item["datatype"],
                item["length"],
                item["decimals"],
                EXTRA_ALIASES.get(field, ""),
                priority=priority,
            )
        )
    return templates


def _collapse_by_field(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        field = str(row.get("field") or "").upper()
        if not field:
            continue
        grouped[field].append(row)

    collapsed: list[dict[str, Any]] = []
    for field, items in grouped.items():
        votes = Counter(
            (
                str(item.get("datatype") or "CHAR").upper(),
                int(item.get("length") or 0),
                int(item.get("decimals") or 0),
            )
            for item in items
        )
        (datatype, length, decimals), _count = votes.most_common(1)[0]
        tables = sorted({str(item.get("table") or "") for item in items if item.get("table")})
        descriptions: list[str] = []
        seen: set[str] = set()
        for item in items:
            desc = re_sub_ws(str(item.get("description") or ""))
            key = desc.lower()
            if desc and key not in seen:
                seen.add(key)
                descriptions.append(desc)
        collapsed.append(
            {
                "field": field,
                "tables": tables,
                "description": "; ".join(descriptions[:4]),
                "datatype": datatype,
                "length": length or None,
                "decimals": decimals,
            }
        )
    collapsed.sort(key=lambda item: item["field"])
    return collapsed


def re_sub_ws(text: str) -> str:
    return " ".join(text.split()).strip()


def _ddic_row(
    tables: list[str],
    field: str,
    description: str,
    datatype: str,
    length: int | None,
    decimals: int | None,
    extra_aliases: str,
    *,
    priority: int,
) -> dict[str, Any]:
    table_aliases = ", ".join(f"{table}.{field}".lower() for table in tables[:12])
    aliases = ", ".join(
        part
        for part in [
            field.lower(),
            field.lower().replace("_", " "),
            table_aliases,
            description.lower(),
            extra_aliases,
        ]
        if part
    )
    mapped = _map_ddic(field, datatype, length, decimals)
    mapped.update(
        {
            "name": field.lower(),
            "aliases": aliases,
            "priority": priority,
            "active": True,
            "flag_mandatory": False,
            "flag_null": False,
            "flag_special_chars": False,
        }
    )
    if field == "IBAN":
        mapped["regex_prompt"] = (
            "IBAN: two letters, then two digits, then 11 to 30 alphanumeric characters"
        )
    return mapped


def _map_ddic(field: str, datatype: str, length: int | None, decimals: int | None) -> dict[str, Any]:
    dt = (datatype or "CHAR").upper()
    flags = {
        "flag_email": field == "SMTP_ADDR",
        "flag_mobile": field in {"TELF1", "TELF2"},
        "flag_date": dt == "DATS",
        "case_format": "uppercase" if field in _UPPERCASE_FIELDS or dt in {"CUKY", "UNIT", "LANG"} else None,
        "data_type": "string",
        "max_length": None,
        "decimal_length": None,
        "regex_prompt": None,
    }
    if dt == "DATS":
        flags["data_type"] = "string"
        return flags
    if dt in {"CURR", "QUAN", "DEC"}:
        flags["data_type"] = "decimal"
        flags["decimal_length"] = decimals if decimals not in (None, 0) else (2 if dt == "CURR" else None)
        return flags
    if dt in {"INT4", "INT2", "INT1"}:
        # Still never emit INT for identifiers; INT* quantities stay decimal.
        flags["data_type"] = "decimal"
        return flags
    if dt == "TIMS":
        flags["data_type"] = "char"
        flags["max_length"] = 6
        return flags
    if dt in {"STRING", "STRG", "LCHR"}:
        flags["data_type"] = "string"
        flags["max_length"] = length
        return flags
    # CHAR, NUMC, CUKY, UNIT, LANG, CLNT — never int (leading zeros matter)
    flags["data_type"] = "char"
    flags["max_length"] = length
    return flags


def char_lengths_for_frontend() -> dict[str, int]:
    """Compact header keys → official CHAR/NUMC length for the UI override."""
    out: dict[str, int] = {}
    for tmpl in templates_from_ddic():
        if tmpl.get("data_type") != "char" or not tmpl.get("max_length"):
            continue
        length = int(tmpl["max_length"])
        keys = [tmpl["name"]]
        for part in str(tmpl.get("aliases") or "").split(","):
            keys.append(part)
        for key in keys:
            compact = "".join(ch for ch in key.lower() if ch.isalnum())
            if 2 <= len(compact) <= 40 and compact not in out:
                out[compact] = length
    return out
