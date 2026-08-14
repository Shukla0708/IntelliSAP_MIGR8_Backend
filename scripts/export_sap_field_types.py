"""Write frontend CHAR-length overrides from the DDIC catalog."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.sap_ddic import char_lengths_for_frontend, load_catalog

FRONTEND = ROOT.parent / "IntelliSAP_MIGR8_Frontend" / "lib" / "sap-field-types.ts"


def main() -> int:
    lengths = char_lengths_for_frontend()
    # Keep a short, high-value subset in the UI file so the bundle stays small.
    # Exact SAP names plus the English aliases that previously collapsed to INT.
    keep = {
        "vbeln", "belnr", "kunnr", "lifnr", "matnr", "vkorg", "salesorg",
        "vtweg", "distrchan", "distchannel", "distributionchannel",
        "spart", "division", "divisioncode", "auart", "doctype", "documenttype",
        "bukrs", "companycode", "werks", "plant", "plantcode", "gjahr",
        "posnr", "waers", "waerk", "land1", "spras", "ebeln", "ebelp",
        "mblnr", "lgort", "storagelocation", "saknr", "kostl", "iban",
        "bankn", "smtpaddr",
    }
    compact = {key: value for key, value in lengths.items() if key in keep}
    # Always include official technical names from the keep list when present.
    for key in list(keep):
        if key in lengths:
            compact[key] = lengths[key]

    lines = [
        "/** Official SAP CHAR/NUMC lengths. Digit-looking values are still CHAR, never INT.",
        " *  Generated from backend data/sap_ddic_catalog.json — do not hand-edit lengths.",
        " */",
        "const SAP_CHAR_LENGTHS: Record<string, number> = {",
    ]
    for key in sorted(compact):
        lines.append(f"  {key}: {compact[key]},")
    lines.extend(
        [
            "};",
            "",
            "export function sapFieldKey(name: string): string {",
            "  return name.toLowerCase().replace(/[^a-z0-9]+/g, \"\");",
            "}",
            "",
            "export function sapCharLength(fieldName: string): number | null {",
            "  return SAP_CHAR_LENGTHS[sapFieldKey(fieldName)] ?? null;",
            "}",
            "",
        ]
    )
    FRONTEND.write_text("\n".join(lines), encoding="utf-8")
    catalog = load_catalog()
    print(
        f"Wrote {len(compact)} UI length keys "
        f"(catalog {len(catalog.get('fields') or [])} fields, "
        f"{len(catalog.get('tables') or [])} tables) -> {FRONTEND}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
