"""Load-layout CSV/XML from confirmed mappings (no Bedrock)."""
from services.load_layout import build_layout


FIELDS = [
    {
        "source_field": "Customer Name",
        "target_field": "KNA1.NAME1",
        "is_key": False,
        "description": "Name 1",
        "datatype": "CHAR",
    },
    {
        "source_field": "Customer Number",
        "target_field": "KNA1.KUNNR",
        "is_key": True,
        "description": "Customer Number",
        "datatype": "CHAR",
    },
]


def test_csv_layout_has_key_and_fill_notes():
    body, media, filename = build_layout(
        "Customer Master", FIELDS, fmt="csv", with_llm_notes=False,
    )
    text = body.decode("utf-8-sig")
    assert media.startswith("text/csv")
    assert filename.endswith("_cockpit.csv")
    assert "SAP_TABLE,SAP_FIELD" in text
    assert "KNA1,KUNNR" in text
    assert "IS_KEY" in text
    assert "Y" in text
    assert "Map Customer Name to KNA1.NAME1" in text


def test_xml_layout_is_lsmw_shaped():
    body, media, filename = build_layout(
        "Customer Master", FIELDS, fmt="xml", with_llm_notes=False,
    )
    text = body.decode("utf-8")
    assert media == "application/xml"
    assert filename.endswith("_lsmw.xml")
    assert "<MigrationCockpitLayout" in text
    assert 'sapField="NAME1"' in text
    assert "<FillNote>" in text
    assert 'key="Y"' in text
