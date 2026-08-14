"""SAP validation-rule catalog.

DDIC fields come from data/sap_ddic_catalog.json (public table dictionaries).
GENERIC_TEMPLATES cover English spreadsheet headers. The DB table is a cache
for ops; suggest-rules uses the in-code list so CHAR lengths cannot go stale.
Templates never set flag_key.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from db.models import ValidationRuleTemplate
from services.sap_ddic import templates_from_ddic


def _row(
    name: str,
    aliases: str,
    *,
    flag_email: bool = False,
    flag_mobile: bool = False,
    flag_date: bool = False,
    flag_mandatory: bool = False,
    flag_null: bool = False,
    flag_special_chars: bool = False,
    case_format: str | None = None,
    data_type: str = "string",
    max_length: int | None = None,
    decimal_length: int | None = None,
    regex_prompt: str | None = None,
    priority: int = 100,
) -> dict[str, Any]:
    return {
        "name": name,
        "aliases": aliases,
        "flag_email": flag_email,
        "flag_mobile": flag_mobile,
        "flag_date": flag_date,
        "flag_mandatory": flag_mandatory,
        "flag_null": flag_null,
        "flag_special_chars": flag_special_chars,
        "case_format": case_format,
        "data_type": data_type,
        "max_length": max_length,
        "decimal_length": decimal_length,
        "regex_prompt": regex_prompt,
        "priority": priority,
        "active": True,
    }


GENERIC_TEMPLATES: list[dict[str, Any]] = [
    _row(
        "email",
        "email, e-mail, e mail, mail, smtp_addr, smtpaddr, smtp addr, customer email",
        flag_email=True,
        priority=10,
    ),
    _row(
        "mobile",
        "mobile, phone, tel, telephone, telf1, telf2, cellphone, contact number, mobile number",
        flag_mobile=True,
        priority=20,
    ),
    _row(
        "posting_date",
        "date, posting date, document date, budat, bldat, gebdt, dob, birth date, datum",
        flag_date=True,
        priority=30,
    ),
    _row(
        "amount",
        "amount, netwr, dmbtr, wrbtr, price, net value, amount in lc, net price",
        data_type="decimal",
        decimal_length=2,
        priority=40,
    ),
    _row(
        "quantity",
        "qty, quantity, menge, labst, stock, stock quantity",
        data_type="decimal",
        priority=50,
    ),
    _row(
        "boolean_flag",
        "active, loevm, xloek, deletion flag, deletion indicator, flag, yes no",
        data_type="boolean",
        priority=60,
    ),
    _row(
        "country",
        "country, land1, landx, country key, country code",
        data_type="char",
        max_length=3,
        case_format="uppercase",
        priority=70,
    ),
    _row(
        "postal_code",
        "postal, pstlz, zip, pincode, zipcode, postal code, zip code, pin code",
        data_type="char",
        max_length=10,
        priority=80,
    ),
    _row(
        "company_code",
        "company code, bukrs, company, companycode",
        data_type="char",
        max_length=4,
        case_format="uppercase",
        priority=90,
    ),
    _row(
        "plant",
        "plant, werks, plant code",
        data_type="char",
        max_length=4,
        case_format="uppercase",
        priority=100,
    ),
    _row(
        "currency",
        "currency, waers, waerk, currency key, currency code",
        data_type="char",
        max_length=5,
        case_format="uppercase",
        priority=110,
    ),
    _row(
        "language",
        "language, spras, language key, language code",
        data_type="char",
        max_length=2,
        case_format="uppercase",
        priority=120,
    ),
    _row(
        "customer_number",
        "customer, kunnr, kunag, sold-to, sold to, customer number, customer id, customer_id",
        data_type="char",
        max_length=10,
        priority=130,
    ),
    _row(
        "vendor_number",
        "vendor, lifnr, vendor number, vendor id, supplier, supplier number",
        data_type="char",
        max_length=10,
        priority=140,
    ),
    _row(
        "material_number",
        "material, matnr, material number, material id, sku, article",
        data_type="char",
        max_length=40,
        priority=150,
    ),
    _row(
        "document_number",
        "doc number, document number, belnr, vbeln, invoice number, accounting document",
        data_type="char",
        max_length=10,
        priority=160,
    ),
    _row(
        "tax_number",
        "gstin, stceg, vat, pan, tax number, vat number, gst number, tax id",
        data_type="char",
        max_length=18,
        priority=170,
    ),
    _row(
        "iban",
        "iban, iban number, international bank account",
        data_type="char",
        max_length=34,
        regex_prompt="IBAN: two letters, then two digits, then 11 to 30 alphanumeric characters",
        case_format="uppercase",
        priority=180,
    ),
    _row(
        "bank_account",
        "bankn, bankl, bank account, bank key, account number, bank account number",
        data_type="char",
        max_length=18,
        priority=190,
    ),
    _row(
        "name1",
        "name, name1, name2, customer name, vendor name, full name, organisation name",
        data_type="string",
        max_length=40,
        priority=200,
    ),
    _row(
        "city",
        "city, ort01, town, city name",
        data_type="string",
        max_length=40,
        priority=210,
    ),
    _row(
        "region",
        "region, regio, state, province, state code",
        data_type="char",
        max_length=3,
        case_format="uppercase",
        priority=220,
    ),
    _row(
        "street",
        "street, stras, address, address line, street address",
        data_type="string",
        max_length=60,
        priority=230,
    ),
    _row(
        "po_box",
        "po box, pfach, post box, pobox, post office box",
        data_type="char",
        max_length=10,
        priority=240,
    ),
    _row(
        "sales_org",
        "sales org, vkorg, sales organization, sales organisation",
        data_type="char",
        max_length=4,
        case_format="uppercase",
        priority=250,
    ),
]


_DDIC_TEMPLATES = templates_from_ddic()
_DDIC_NAMES = {item["name"] for item in _DDIC_TEMPLATES}
# Official SAP CHAR/NUMC lengths win over sample-based guesses (VBELN is CHAR 10, not INT).
SEED_TEMPLATES: list[dict[str, Any]] = _DDIC_TEMPLATES + [
    item for item in GENERIC_TEMPLATES if item["name"] not in _DDIC_NAMES
]


def embed_text(template: dict[str, Any]) -> str:
    return f"{template.get('name') or ''} {template.get('aliases') or ''}".strip()


def load_templates(db: Session | None) -> list[dict[str, Any]]:
    """In-code SAP DDIC + generics are the source of truth.

    The DB table is seeded for inspection; suggest-rules does not depend on it
    being up to date, so CHAR lengths cannot go stale after a code change.
    """
    return [dict(item) for item in SEED_TEMPLATES]


def seed_templates(db: Session) -> int:
    """Upsert SEED_TEMPLATES into validation_rule_templates. Returns row count."""
    existing = {
        row.name: row
        for row in db.query(ValidationRuleTemplate).all()
    }
    for item in SEED_TEMPLATES:
        row = existing.get(item["name"])
        if row is None:
            db.add(ValidationRuleTemplate(**item))
            continue
        for key, value in item.items():
            if key == "name":
                continue
            setattr(row, key, value)
    db.commit()
    return len(SEED_TEMPLATES)


def _model_to_dict(row: ValidationRuleTemplate) -> dict[str, Any]:
    return {
        "name": row.name,
        "aliases": row.aliases or "",
        "flag_email": bool(row.flag_email),
        "flag_mobile": bool(row.flag_mobile),
        "flag_date": bool(row.flag_date),
        "flag_mandatory": bool(row.flag_mandatory),
        "flag_null": bool(row.flag_null),
        "flag_special_chars": bool(row.flag_special_chars),
        "case_format": row.case_format,
        "data_type": row.data_type or "string",
        "max_length": row.max_length,
        "decimal_length": row.decimal_length,
        "regex_prompt": row.regex_prompt,
        "priority": row.priority or 100,
        "active": True,
    }
