"""Parse fetched SAP table pages into data/sap_ddic_catalog.json."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "sap_ddic_catalog.json"
DUMP_DIRS = [
    Path(r"C:\Users\VE00YM780\.cursor\projects\c-Users-VE00YM780-hackathon\agent-tools"),
    ROOT / "data" / "ddic_raw",
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
    re.MULTILINE,
)
HTML_ROW = re.compile(
    rf'<span class="sap-field-name">([A-Z][/A-Z0-9_]{{1,40}})</span></td>\s*'
    rf"<td>([^<]{{1,200}})</td><td>({_DT})</td><td>(\d+)</td><td>(\d+)</td>",
    re.IGNORECASE,
)
HEADING = re.compile(r"^# (?:SAP Table )?([A-Z][A-Z0-9_]{2,20})\s*$", re.MULTILINE)
TITLE = re.compile(r"^([A-Z][A-Z0-9_]{2,20}) \| ", re.MULTILINE)
FILE_TABLE = re.compile(r"^([A-Z][A-Z0-9_]{2,20})\.(txt|html)$", re.IGNORECASE)


def parse_file(path: Path) -> tuple[str | None, list[dict]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    heading = HEADING.search(text)
    title = TITLE.search(text)
    file_table = FILE_TABLE.match(path.name)
    table = (
        (heading.group(1) if heading else None)
        or (title.group(1) if title else None)
        or (file_table.group(1).upper() if file_table else None)
    )
    if not table:
        return None, []
    rows: list[dict] = []
    seen: set[str] = set()
    for rx in (DP_ROW, HTML_ROW):
        for match in rx.finditer(text):
            field = match.group(1).upper()
            if field in SKIP_FIELDS or field in seen:
                continue
            if "/" in field or field.startswith("DUMMY") or field.startswith("_"):
                continue
            seen.add(field)
            desc = re.sub(r"\s+", " ", match.group(2)).strip()
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
    return table, rows


def main() -> int:
    catalog: list[dict] = []
    tables: set[str] = set()
    for folder in DUMP_DIRS:
        if not folder.is_dir():
            continue
        for path in list(folder.glob("*.txt")) + list(folder.glob("*.html")):
            table, rows = parse_file(path)
            if not rows:
                continue
            tables.add(table or "")
            catalog.extend(rows)
            print(f"  {table}: {len(rows)} from {path.name}")

    # De-dupe identical table+field (same dump fetched twice)
    uniq: dict[tuple[str, str], dict] = {}
    for row in catalog:
        uniq[(row["table"], row["field"])] = row
    fields = list(uniq.values())
    if not fields:
        print("No fields parsed", file=sys.stderr)
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "source": "Public SAP table dictionaries (datapanda.eu / leanx.eu)",
                "tables": sorted(t for t in tables if t),
                "fields": fields,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Wrote {len(fields)} fields across {len(tables)} tables -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
