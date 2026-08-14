"""Fetch public SAP DDIC field lists and write data/sap_ddic_catalog.json.

Sources (public table dictionaries, not SAP copyrighted ABAP source):
  - https://datapanda.eu/en/sap/table/{TABLE}
  - https://leanx.eu/en/sap/table/{table}.html  (fallback)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "sap_ddic_catalog.json"
RAW = ROOT / "data" / "ddic_raw"

TABLES = [
    "VBAK", "VBAP", "VBEP", "VBPA", "VBKD", "VBUK", "VBUP",
    "LIKP", "LIPS", "VBRK", "VBRP",
    "KNA1", "KNB1", "KNVV", "KNVP",
    "LFA1", "LFB1", "LFM1",
    "MARA", "MARC", "MARD", "MARM", "MAKT",
    "BKPF", "BSEG",
    "EKKO", "EKPO", "EKET",
    "MKPF", "MSEG",
    "ADRC", "ADR6",
    "SKA1", "SKB1", "CSKS",
    "T001", "T001W",
    "KNBK", "LFBK", "BNKA",
]

SKIP_FIELDS = {"MANDT", "CLIENT"}

DATATYPES = (
    "CHAR", "NUMC", "DATS", "TIMS", "CURR", "QUAN", "CUKY", "UNIT",
    "DEC", "CLNT", "LANG", "INT4", "INT2", "INT1", "FLTP", "RAW",
    "ACCP", "PREC", "LCHR", "SSTR", "STRG", "STRING",
)
_DT = "|".join(DATATYPES)

DP_ROW = re.compile(
    rf"^\| (?:Key )?([A-Z][/A-Z0-9_]{{1,40}}) \| ([^|\n]+?) \| ({_DT}) \| (\d+) \| (\d+)",
    re.MULTILINE | re.IGNORECASE,
)
LX_ROW = re.compile(
    rf"^\| ([A-Z][/A-Z0-9_]{{1,40}}) ([^|\n]+?) \| \S+ \| [^\n|]* \| ({_DT}) \| (\d+) \| (\d+)",
    re.MULTILINE | re.IGNORECASE,
)
HTML_ROW = re.compile(
    rf'<span class="sap-field-name">([A-Z][/A-Z0-9_]{{1,40}})</span></td>\s*'
    rf"<td>([^<]{{1,200}})</td><td>({_DT})</td><td>(\d+)</td><td>(\d+)</td>",
    re.IGNORECASE,
)


def _parse(text: str, table: str) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for rx in (DP_ROW, LX_ROW, HTML_ROW):
        for match in rx.finditer(text):
            field = match.group(1).upper()
            if field in SKIP_FIELDS or field in seen or "/" in field:
                continue
            if field.startswith("DUMMY") or field.startswith("_"):
                continue
            seen.add(field)
            desc = re.sub(r"\s+", " ", match.group(2)).strip(" |")
            rows.append(
                {
                    "table": table,
                    "field": field,
                    "description": desc[:180],
                    "datatype": match.group(3).upper(),
                    "length": int(match.group(4)),
                    "decimals": int(match.group(5)),
                }
            )
    return rows


def fetch_table(client: httpx.Client, table: str) -> list[dict]:
    urls = [
        f"https://datapanda.eu/en/sap/table/{table}",
        f"https://leanx.eu/en/sap/table/{table.lower()}.html",
        f"https://leanx.eu/sap/table/{table.lower()}/",
    ]
    for url in urls:
        try:
            resp = client.get(url, follow_redirects=True)
            if resp.status_code != 200 or len(resp.text) < 500:
                continue
            rows = _parse(resp.text, table)
            if rows:
                RAW.mkdir(parents=True, exist_ok=True)
                (RAW / f"{table}.txt").write_text(resp.text, encoding="utf-8", errors="replace")
                print(f"  {table}: {len(rows)} fields from {url}")
                return rows
        except Exception as exc:
            print(f"  {table}: {url} failed ({exc})")
    print(f"  {table}: no fields parsed")
    return []


def main() -> int:
    catalog: list[dict] = []
    existing_tables: set[str] = set()
    if OUT.is_file():
        prev = json.loads(OUT.read_text(encoding="utf-8"))
        for row in prev.get("fields") or []:
            catalog.append(row)
            existing_tables.add(str(row.get("table") or ""))

    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    with httpx.Client(
        timeout=30.0,
        verify=False,
        headers={"User-Agent": "MIGR8-DDIC-seed/1.0"},
    ) as client:
        for table in TABLES:
            if table in existing_tables:
                print(f"  {table}: keeping {sum(1 for r in catalog if r.get('table') == table)} existing fields")
                continue
            catalog.extend(fetch_table(client, table))

    if not catalog:
        print("No fields fetched", file=sys.stderr)
        return 1

    # De-dupe identical table+field
    uniq: dict[tuple[str, str], dict] = {}
    for row in catalog:
        uniq[(str(row.get("table") or ""), str(row.get("field") or ""))] = row
    fields = list(uniq.values())
    tables = sorted({t for t, _ in uniq if t})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": "Public SAP table dictionaries (datapanda.eu / leanx.eu)",
        "tables": tables,
        "fields": fields,
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {len(fields)} fields across {len(tables)} tables -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
