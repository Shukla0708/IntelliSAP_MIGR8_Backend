"""SAP DDIC metadata used as the source of truth for AI rule suggestions.

CHAR / NUMC identifiers stay character fields (with official lengths) even when
sample values look numeric. Templates never set flag_key.
"""
from __future__ import annotations

from typing import Any

# table, field, description, datatype, length, decimals, extra aliases
_SAP_DDIC: list[tuple[str, str, str, str, int | None, int | None, str]] = [
    # Sales document (VBAK / VBAP / VBRK / LIKP)
    ("VBAK", "VBELN", "Sales Document", "CHAR", 10, None, "sales document, sales order, so number, document number, doc number"),
    ("VBAK", "AUART", "Sales Document Type", "CHAR", 4, None, "doc type, document type, order type"),
    ("VBAK", "VKORG", "Sales Organization", "CHAR", 4, None, "sales org, sales organization, sales organisation"),
    ("VBAK", "VTWEG", "Distribution Channel", "CHAR", 2, None, "distr chan, dist channel, distribution channel"),
    ("VBAK", "SPART", "Division", "CHAR", 2, None, "division, division code"),
    ("VBAK", "KUNNR", "Sold-to Party", "CHAR", 10, None, "sold-to, sold to, customer, customer number, customer id"),
    ("VBAK", "AUDAT", "Document Date", "DATS", 8, None, "order date, document date"),
    ("VBAK", "NETWR", "Net Value", "CURR", 15, 2, "amount, net value, net price"),
    ("VBAK", "WAERK", "SD Document Currency", "CUKY", 5, None, "currency, document currency"),
    ("VBAK", "VKBUR", "Sales Office", "CHAR", 4, None, "sales office"),
    ("VBAK", "VKGRP", "Sales Group", "CHAR", 3, None, "sales group"),
    ("VBAP", "POSNR", "Sales Document Item", "NUMC", 6, None, "item, item number, line item"),
    ("VBAP", "MATNR", "Material Number", "CHAR", 40, None, "material, material number, sku"),
    ("VBAP", "KWMENG", "Order Quantity", "QUAN", 15, 3, "qty, quantity, order quantity"),
    ("VBAP", "VRKME", "Sales Unit", "UNIT", 3, None, "sales unit, uom"),
    ("VBAP", "WERKS", "Plant", "CHAR", 4, None, "plant, plant code"),
    ("VBRK", "VBELN", "Billing Document", "CHAR", 10, None, "billing document, invoice number"),
    ("VBRK", "FKART", "Billing Type", "CHAR", 4, None, "billing type"),
    ("VBRK", "FKDAT", "Billing Date", "DATS", 8, None, "billing date, invoice date"),
    ("LIKP", "VBELN", "Delivery", "CHAR", 10, None, "delivery, delivery number"),
    ("LIKP", "LFDAT", "Delivery Date", "DATS", 8, None, "delivery date"),
    # Customer / vendor / material master
    ("KNA1", "KUNNR", "Customer Number", "CHAR", 10, None, "customer, customer number, customer id, sold-to"),
    ("KNA1", "NAME1", "Name 1", "CHAR", 40, None, "name, customer name, name1"),
    ("KNA1", "NAME2", "Name 2", "CHAR", 40, None, "name2"),
    ("KNA1", "ORT01", "City", "CHAR", 40, None, "city, town"),
    ("KNA1", "PSTLZ", "Postal Code", "CHAR", 10, None, "postal, postal code, zip, zipcode, pincode, pin code"),
    ("KNA1", "LAND1", "Country Key", "CHAR", 3, None, "country, country key, country code"),
    ("KNA1", "REGIO", "Region", "CHAR", 3, None, "region, state, province, state code"),
    ("KNA1", "STRAS", "Street", "CHAR", 60, None, "street, address, address line"),
    ("KNA1", "TELF1", "First Telephone Number", "CHAR", 16, None, "phone, telephone, mobile, telf1"),
    ("KNA1", "TELF2", "Second Telephone Number", "CHAR", 16, None, "telf2, cellphone"),
    ("KNA1", "SPRAS", "Language Key", "LANG", 1, None, "language, language key, language code"),
    ("KNA1", "STCEG", "VAT Registration Number", "CHAR", 20, None, "vat, gstin, tax number, vat number"),
    ("KNA1", "LOEVM", "Central Deletion Flag", "CHAR", 1, None, "deletion flag, deletion indicator, loevm"),
    ("ADR6", "SMTP_ADDR", "E-Mail Address", "STRING", 241, None, "email, e-mail, mail, smtpaddr, smtp addr, customer email"),
    ("LFA1", "LIFNR", "Vendor Account Number", "CHAR", 10, None, "vendor, vendor number, vendor id, supplier"),
    ("LFA1", "NAME1", "Name 1", "CHAR", 40, None, "vendor name"),
    ("MARA", "MATNR", "Material Number", "CHAR", 40, None, "material, material number, sku, article"),
    ("MARA", "MTART", "Material Type", "CHAR", 4, None, "material type"),
    ("MARA", "MEINS", "Base Unit of Measure", "UNIT", 3, None, "base uom, unit of measure"),
    ("MARC", "WERKS", "Plant", "CHAR", 4, None, "plant, plant code"),
    # FI
    ("BKPF", "BELNR", "Accounting Document Number", "CHAR", 10, None, "accounting document, fi document, doc number"),
    ("BKPF", "BUKRS", "Company Code", "CHAR", 4, None, "company code, company"),
    ("BKPF", "GJAHR", "Fiscal Year", "NUMC", 4, None, "fiscal year, year"),
    ("BKPF", "BLART", "Document Type", "CHAR", 2, None, "fi doc type, accounting document type"),
    ("BKPF", "BLDAT", "Document Date in Document", "DATS", 8, None, "document date, bldat"),
    ("BKPF", "BUDAT", "Posting Date in the Document", "DATS", 8, None, "posting date, budat"),
    ("BKPF", "WAERS", "Currency Key", "CUKY", 5, None, "currency, currency key, currency code"),
    ("BSEG", "WRBTR", "Amount in Document Currency", "CURR", 13, 2, "amount, wrbtr"),
    ("BSEG", "DMBTR", "Amount in Local Currency", "CURR", 13, 2, "dmbtr, amount in lc"),
    ("BSEG", "HKONT", "General Ledger Account", "CHAR", 10, None, "gl account, account number"),
    ("BSEG", "KOSTL", "Cost Center", "CHAR", 10, None, "cost center"),
    ("BNKA", "BANKN", "Bank Account Number", "CHAR", 18, None, "bank account, bankn"),
    ("BNKA", "BANKL", "Bank Key", "CHAR", 15, None, "bank key, bankl"),
    ("BNKA", "IBAN", "IBAN", "CHAR", 34, None, "iban, iban number"),
]


_UPPERCASE_FIELDS = {
    "VKORG", "VTWEG", "SPART", "AUART", "BUKRS", "WERKS", "WAERS", "WAERK",
    "SPRAS", "LAND1", "BLART", "FKART", "MTART", "MEINS", "VRKME", "GEWEI",
    "VKBUR", "VKGRP", "IBAN",
}


def templates_from_ddic() -> list[dict[str, Any]]:
    templates: list[dict[str, Any]] = []
    for i, (table, field, description, datatype, length, decimals, extra) in enumerate(_SAP_DDIC):
        templates.append(_ddic_row(table, field, description, datatype, length, decimals, extra, priority=10 + i))
    return templates


def _ddic_row(
    table: str,
    field: str,
    description: str,
    datatype: str,
    length: int | None,
    decimals: int | None,
    extra_aliases: str,
    *,
    priority: int,
) -> dict[str, Any]:
    aliases = ", ".join(
        part
        for part in [
            field.lower(),
            f"{table}.{field}".lower(),
            description.lower(),
            extra_aliases,
        ]
        if part
    )
    mapped = _map_ddic(field, datatype, length, decimals)
    mapped.update(
        {
            "name": f"{table}_{field}".lower(),
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
        flags["decimal_length"] = decimals if decimals is not None else (2 if dt == "CURR" else None)
        return flags
    if dt in {"INT4", "INT2", "INT1"}:
        flags["data_type"] = "int"
        return flags
    if dt == "TIMS":
        flags["data_type"] = "char"
        flags["max_length"] = 6
        return flags
    # CHAR, NUMC, CUKY, UNIT, LANG, CLNT, STRING — never int (leading zeros matter)
    if dt == "STRING":
        flags["data_type"] = "string"
        flags["max_length"] = length
        return flags
    flags["data_type"] = "char"
    flags["max_length"] = length
    return flags
