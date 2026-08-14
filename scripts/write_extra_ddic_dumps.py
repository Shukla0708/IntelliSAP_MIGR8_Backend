"""Write extra SAP DDIC rows from already-fetched public table pages.

This avoids a live scrape: the markdown below was retrieved from datapanda.eu
during this session. Re-run scripts/parse_sap_ddic_dumps.py after editing.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "ddic_raw"

# Concatenated datapanda-style field tables (one heading per table).
DUMPS = r"""
# ADR6
| Field | Description | Data type | Length | Decimals |
| Key CLIENT | Client | CLNT | 3 | 0
| Key ADDRNUMBER | Address Number | CHAR | 10 | 0
| Key PERSNUMBER | Person Number | CHAR | 10 | 0
| Key DATE_FROM | Valid-from date | DATS | 8 | 0
| Key CONSNUMBER | Sequence Number | NUMC | 3 | 0
| SMTP_ADDR | E-Mail Address | CHAR | 241 | 0
| SMTP_SRCH | E-Mail Address Search Field | CHAR | 20 | 0
# KNVP
| Field | Description | Data type | Length | Decimals |
| Key KUNNR | Customer Number | CHAR | 10 | 0
| Key VKORG | Sales Organization | CHAR | 4 | 0
| Key VTWEG | Distribution Channel | CHAR | 2 | 0
| Key SPART | Division | CHAR | 2 | 0
| Key PARVW | Partner Function | CHAR | 2 | 0
| Key PARZA | Partner counter | NUMC | 3 | 0
| KUNN2 | Customer number of business partner | CHAR | 10 | 0
| LIFNR | Account Number of Supplier | CHAR | 10 | 0
| PERNR | Personnel Number | NUMC | 8 | 0
| PARNR | Number of Contact Person | NUMC | 10 | 0
| KNREF | Customer description of partner | CHAR | 30 | 0
| DEFPA | Default Partner | CHAR | 1 | 0
| ADRNR | Business Partner Address Number | CHAR | 10 | 0
# MAKT
| Field | Description | Data type | Length | Decimals |
| Key MATNR | Material Number | CHAR | 40 | 0
| Key SPRAS | Language Key | LANG | 1 | 0
| MAKTX | Material Description | CHAR | 40 | 0
| MAKTG | Material Description in Uppercase | CHAR | 40 | 0
# SKA1
| Field | Description | Data type | Length | Decimals |
| Key KTOPL | Chart of Accounts | CHAR | 4 | 0
| Key SAKNR | G/L Account Number | CHAR | 10 | 0
| XBILK | Indicator: Account is a balance sheet account | CHAR | 1 | 0
| SAKAN | G/L Account Number, Significant Length | CHAR | 10 | 0
| BILKT | Group Account Number | CHAR | 10 | 0
| ERDAT | Date on which the Record Was Created | DATS | 8 | 0
| ERNAM | Name of Person who Created the Object | CHAR | 12 | 0
| GVTYP | P and L statement account type | CHAR | 2 | 0
| KTOKS | G/L Account Group | CHAR | 4 | 0
| MUSTR | Number of the Sample Account | CHAR | 10 | 0
| VBUND | Company ID of Trading Partner | CHAR | 6 | 0
| XLOEV | Indicator: Account Marked for Deletion | CHAR | 1 | 0
| XSPEA | Indicator: Account Is Blocked for Creation | CHAR | 1 | 0
| XSPEB | Indicator: Is Account Blocked for Posting | CHAR | 1 | 0
| XSPEP | Indicator: Account Blocked for Planning | CHAR | 1 | 0
| MCOD1 | Search Term for Using Matchcode | CHAR | 25 | 0
| FUNC_AREA | Functional Area | CHAR | 16 | 0
| GLACCOUNT_TYPE | Type of a General Ledger Account | CHAR | 1 | 0
| MAIN_SAKNR | Bank Reconciliation Account | CHAR | 10 | 0
# KNBK
| Field | Description | Data type | Length | Decimals |
| Key KUNNR | Customer Number | CHAR | 10 | 0
| Key BANKS | Country/Region Key of Bank | CHAR | 3 | 0
| Key BANKL | Bank Keys | CHAR | 15 | 0
| Key BANKN | Bank account number | CHAR | 18 | 0
| BKONT | Bank Control Key | CHAR | 2 | 0
| BVTYP | Partner bank type | CHAR | 4 | 0
| XEZER | Indicator: Is there collection authorization | CHAR | 1 | 0
| BKREF | Reference Details for Bank Details | CHAR | 20 | 0
| KOINH | Account Holder Name | CHAR | 60 | 0
| EBPP_ACCNAME | User-Defined Name of Bank Details | CHAR | 40 | 0
| KOVON | Bank Details Valid From | DATS | 8 | 0
| KOBIS | Bank details valid to | DATS | 8 | 0
# MKPF
| Field | Description | Data type | Length | Decimals |
| Key MBLNR | Number of Material Document | CHAR | 10 | 0
| Key MJAHR | Material Document Year | NUMC | 4 | 0
| VGART | Transaction/Event Type | CHAR | 2 | 0
| BLART | Document Type | CHAR | 2 | 0
| BLDAT | Document Date in Document | DATS | 8 | 0
| BUDAT | Posting Date in the Document | DATS | 8 | 0
| CPUDT | Day On Which Accounting Document Was Entered | DATS | 8 | 0
| CPUTM | Time of Entry | TIMS | 6 | 0
| AEDAT | Last Changed On | DATS | 8 | 0
| USNAM | User Name | CHAR | 12 | 0
| XBLNR | Reference Document Number | CHAR | 16 | 0
| BKTXT | Document Header Text | CHAR | 25 | 0
| FRATH | Unplanned delivery costs | CURR | 13 | 2
| FRBNR | Number of Bill of Lading at Time of Goods Receipt | CHAR | 16 | 0
| XABLN | Goods Receipt/Issue Slip Number | CHAR | 10 | 0
| LE_VBELN | Delivery | CHAR | 10 | 0
| KNUMV | Number of the Document Condition | CHAR | 10 | 0
# VBPA
| Field | Description | Data type | Length | Decimals |
| Key VBELN | Sales and Distribution Document Number | CHAR | 10 | 0
| Key POSNR | Item number of the SD document | NUMC | 6 | 0
| Key PARVW | Partner Function | CHAR | 2 | 0
| KUNNR | Customer Number | CHAR | 10 | 0
| LIFNR | Account Number of Supplier | CHAR | 10 | 0
| PERNR | Personnel Number | NUMC | 8 | 0
| PARNR | Number of Contact Person | NUMC | 10 | 0
| ADRNR | Address | CHAR | 10 | 0
| ABLAD | Unloading Point | CHAR | 25 | 0
| LAND1 | Country/Region Key | CHAR | 3 | 0
| STCEG | VAT Registration Number | CHAR | 20 | 0
| KNREF | Customer description of partner | CHAR | 30 | 0
| LZONE | Transportation zone | CHAR | 10 | 0
| ASSIGNED_BP | Business Partner Number | CHAR | 10 | 0
# VBEP
| Field | Description | Data type | Length | Decimals |
| Key VBELN | Sales Document | CHAR | 10 | 0
| Key POSNR | Sales Document Item | NUMC | 6 | 0
| Key ETENR | Schedule Line Number | NUMC | 4 | 0
| ETTYP | Schedule line category | CHAR | 2 | 0
| EDATU | Schedule line date | DATS | 8 | 0
| EZEIT | Arrival time | TIMS | 6 | 0
| WMENG | Order Quantity in Sales Units | QUAN | 13 | 3
| BMENG | Confirmed Quantity | QUAN | 13 | 3
| VRKME | Sales unit | UNIT | 3 | 0
| MEINS | Base Unit of Measure | UNIT | 3 | 0
| BANFN | Purchase Requisition Number | CHAR | 10 | 0
| BSART | Order Type (Purchasing) | CHAR | 4 | 0
| AUFNR | Order Number | CHAR | 12 | 0
| PLNUM | Planned Order | CHAR | 10 | 0
| WADAT | Goods Issue Date | DATS | 8 | 0
| MBDAT | Material Staging/Availability Date | DATS | 8 | 0
| WAERK | SD Document Currency | CUKY | 5 | 0
# MARD
| Field | Description | Data type | Length | Decimals |
| Key MATNR | Material Number | CHAR | 40 | 0
| Key WERKS | Plant | CHAR | 4 | 0
| Key LGORT | Storage location | CHAR | 4 | 0
| LABST | Valuated Unrestricted-Use Stock | QUAN | 13 | 3
| INSME | Stock in Quality Inspection | QUAN | 13 | 3
| SPEME | Blocked Stock | QUAN | 13 | 3
| LGPBE | Storage Bin | CHAR | 10 | 0
| PRCTL | Profit Center | CHAR | 10 | 0
# T001
| Field | Description | Data type | Length | Decimals |
| Key BUKRS | Company Code | CHAR | 4 | 0
| BUTXT | Name of Company Code or Company | CHAR | 25 | 0
| ORT01 | City | CHAR | 25 | 0
| LAND1 | Country/Region Key | CHAR | 3 | 0
| WAERS | Currency Key | CUKY | 5 | 0
| SPRAS | Language Key | LANG | 1 | 0
| KTOPL | Chart of Accounts | CHAR | 4 | 0
| STCEG | VAT Registration Number | CHAR | 20 | 0
| ADRNR | Address | CHAR | 10 | 0
| KKBER | Credit control area | CHAR | 4 | 0
# BNKA
| Field | Description | Data type | Length | Decimals |
| Key BANKS | Country/Region Key of Bank | CHAR | 3 | 0
| Key BANKL | Bank Keys | CHAR | 15 | 0
| BANKA | Name of Financial Institution | CHAR | 60 | 0
| SWIFT | SWIFT/BIC for International Payments | CHAR | 11 | 0
| BNKLZ | Bank Number | CHAR | 15 | 0
| BRNCH | Bank Branch | CHAR | 40 | 0
| STRAS | Street and House Number | CHAR | 35 | 0
| ORT01 | City | CHAR | 35 | 0
# CSKS
| Field | Description | Data type | Length | Decimals |
| Key KOKRS | Controlling Area | CHAR | 4 | 0
| Key KOSTL | Cost Center | CHAR | 10 | 0
| Key DATBI | Valid To Date | DATS | 8 | 0
| DATAB | Valid-From Date | DATS | 8 | 0
| BUKRS | Company Code | CHAR | 4 | 0
| WAERS | Currency Key | CUKY | 5 | 0
| PRCTR | Profit Center | CHAR | 10 | 0
| WERKS | Plant | CHAR | 4 | 0
| NAME1 | Name 1 | CHAR | 35 | 0
| ORT01 | City | CHAR | 35 | 0
| TELF1 | First telephone number | CHAR | 16 | 0
| TELF2 | Second telephone number | CHAR | 16 | 0
# KNB1
| Field | Description | Data type | Length | Decimals |
| Key KUNNR | Customer Number | CHAR | 10 | 0
| Key BUKRS | Company Code | CHAR | 4 | 0
| AKONT | Reconciliation Account in General Ledger | CHAR | 10 | 0
| ZTERM | Terms of payment key | CHAR | 4 | 0
| ZWELS | List of Respected Payment Methods | CHAR | 10 | 0
| SPERR | Posting block for company code | CHAR | 1 | 0
| LOEVM | Deletion Flag for Master Record | CHAR | 1 | 0
| HBKID | Short Key for a House Bank | CHAR | 5 | 0
| INTAD | Internet address of partner company clerk | CHAR | 130 | 0
| TLFNS | Accounting clerk telephone number | CHAR | 30 | 0
# LFB1
| Field | Description | Data type | Length | Decimals |
| Key LIFNR | Account Number of Supplier | CHAR | 10 | 0
| Key BUKRS | Company Code | CHAR | 4 | 0
| AKONT | Reconciliation Account in General Ledger | CHAR | 10 | 0
| ZTERM | Terms of payment key | CHAR | 4 | 0
| ZWELS | List of Respected Payment Methods | CHAR | 10 | 0
| SPERR | Posting block for company code | CHAR | 1 | 0
| LOEVM | Deletion Flag for Master Record | CHAR | 1 | 0
| QSSKZ | Withholding Tax Code | CHAR | 2 | 0
| WRBTR | Amount for Payment Program | CURR | 23 | 2
| WAERS | Currency Key | CUKY | 5 | 0
# KNVV
| Field | Description | Data type | Length | Decimals |
| Key KUNNR | Customer Number | CHAR | 10 | 0
| Key VKORG | Sales Organization | CHAR | 4 | 0
| Key VTWEG | Distribution Channel | CHAR | 2 | 0
| Key SPART | Division | CHAR | 2 | 0
| WAERS | Currency | CUKY | 5 | 0
| VWERK | Delivering Plant | CHAR | 4 | 0
| VKGRP | Sales group | CHAR | 3 | 0
| VKBUR | Sales office | CHAR | 4 | 0
| INCO1 | Incoterms Part 1 | CHAR | 3 | 0
| INCO2 | Incoterms Part 2 | CHAR | 28 | 0
| ZTERM | Terms of payment key | CHAR | 4 | 0
| KDGRP | Customer Group | CHAR | 2 | 0
# ADRC
| Field | Description | Data type | Length | Decimals |
| Key ADDRNUMBER | Address Number | CHAR | 10 | 0
| NAME1 | Name 1 | CHAR | 40 | 0
| NAME2 | Name 2 | CHAR | 40 | 0
| CITY1 | City | CHAR | 40 | 0
| POST_CODE1 | City postal code | CHAR | 10 | 0
| PO_BOX | PO Box | CHAR | 10 | 0
| STREET | Street | CHAR | 60 | 0
| HOUSE_NUM1 | House Number | CHAR | 10 | 0
| COUNTRY | Country/Region Key | CHAR | 3 | 0
| LANGU | Language Key | LANG | 1 | 0
| REGION | Region State Province County | CHAR | 3 | 0
| TEL_NUMBER | First telephone no | CHAR | 30 | 0
| FAX_NUMBER | First Fax No | CHAR | 30 | 0
# T001W
| Field | Description | Data type | Length | Decimals |
| Key WERKS | Plant | CHAR | 4 | 0
| NAME1 | Name | CHAR | 30 | 0
| BWKEY | Valuation area | CHAR | 4 | 0
| KUNNR | Customer Number of Plant | CHAR | 10 | 0
| LIFNR | Supplier Number of Plant | CHAR | 10 | 0
| STRAS | Street and House Number | CHAR | 30 | 0
| PSTLZ | Postal Code | CHAR | 10 | 0
| ORT01 | City | CHAR | 25 | 0
| LAND1 | Country/Region Key | CHAR | 3 | 0
| REGIO | Region | CHAR | 3 | 0
| EKORG | Purchasing organization | CHAR | 4 | 0
| VKORG | Sales Organization for Intercompany Billing | CHAR | 4 | 0
# SKB1
| Field | Description | Data type | Length | Decimals |
| Key BUKRS | Company Code | CHAR | 4 | 0
| Key SAKNR | G/L Account Number | CHAR | 10 | 0
| WAERS | Account Currency | CUKY | 5 | 0
| FSTAG | Field status group | CHAR | 4 | 0
| MITKZ | Account is Reconciliation Account | CHAR | 1 | 0
| XOPVW | Indicator: Open Item Management | CHAR | 1 | 0
| XSPEB | Indicator: Is Account Blocked for Posting | CHAR | 1 | 0
# LFM1
| Field | Description | Data type | Length | Decimals |
| Key LIFNR | Vendor account number | CHAR | 10 | 0
| Key EKORG | Purchasing organization | CHAR | 4 | 0
| WAERS | Purchase order currency | CUKY | 5 | 0
| ZTERM | Terms of payment key | CHAR | 4 | 0
| INCO1 | Incoterms Part 1 | CHAR | 3 | 0
| EKGRP | Purchasing Group | CHAR | 3 | 0
| TELF1 | Supplier Telephone Number | CHAR | 16 | 0
# EKET
| Field | Description | Data type | Length | Decimals |
| Key EBELN | Purchasing Document Number | CHAR | 10 | 0
| Key EBELP | Item Number of Purchasing Document | NUMC | 5 | 0
| Key ETENR | Delivery Schedule Line Counter | NUMC | 4 | 0
| EINDT | Item delivery date | DATS | 8 | 0
| MENGE | Scheduled Quantity | QUAN | 13 | 3
| WEMNG | Quantity of goods received | QUAN | 13 | 3
| BANFN | Purchase Requisition Number | CHAR | 10 | 0
| CHARG | Batch Number | CHAR | 10 | 0
# MARM
| Field | Description | Data type | Length | Decimals |
| Key MATNR | Material Number | CHAR | 40 | 0
| Key MEINH | Alternative Unit of Measure | UNIT | 3 | 0
| EAN11 | International Article Number EAN/UPC | CHAR | 18 | 0
| BRGEW | Gross weight | QUAN | 13 | 3
| GEWEI | Weight Unit | UNIT | 3 | 0
| VOLUM | Volume | QUAN | 13 | 3
# VBKD
| Field | Description | Data type | Length | Decimals |
| Key VBELN | Sales and Distribution Document Number | CHAR | 10 | 0
| Key POSNR | Item number of the SD document | NUMC | 6 | 0
| INCO1 | Incoterms Part 1 | CHAR | 3 | 0
| INCO2 | Incoterms Part 2 | CHAR | 28 | 0
| ZTERM | Terms of payment key | CHAR | 4 | 0
| BSTKD | Customer Reference | CHAR | 35 | 0
| FKDAT | Billing Date | DATS | 8 | 0
| GJAHR | Fiscal Year | NUMC | 4 | 0
| KDGRP | Customer Group | CHAR | 2 | 0
| BZIRK | Sales District | CHAR | 6 | 0
"""


def main() -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    current: str | None = None
    buf: list[str] = []
    written = 0
    for line in DUMPS.splitlines():
        if line.startswith("# "):
            if current and buf:
                (RAW / f"{current}.txt").write_text("\n".join(buf) + "\n", encoding="utf-8")
                written += 1
            current = line[2:].strip()
            buf = [line]
            continue
        if current:
            buf.append(line)
    if current and buf:
        (RAW / f"{current}.txt").write_text("\n".join(buf) + "\n", encoding="utf-8")
        written += 1
    print(f"Wrote {written} dump files under {RAW}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
