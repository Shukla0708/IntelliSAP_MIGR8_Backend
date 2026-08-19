"""Chat copilot intent detection (no Bedrock / DB)."""
from services import chat_actions
from services.semantic_match import is_semantic_match, reclassify_discrepancies


def test_detects_allow_listed_actions():
    assert chat_actions.detect("suggest rules on this draft") == "suggest_rules"
    assert chat_actions.detect("explain MATNR failures") == "explain_failures"
    assert chat_actions.detect("summarize last comparison") == "summarize_comparison"
    assert chat_actions.detect("generate an LSMW load layout") == "generate_load_layout"
    assert chat_actions.detect("find duplicate customers before load") == "find_duplicates"


def test_ignores_plain_questions():
    assert chat_actions.detect("how many invalid rows in the last run?") is None


def test_extracts_field_hint():
    assert chat_actions.extract_field_hint("explain MATNR failures") == "MATNR"


def test_legal_form_is_semantic_match():
    assert is_semantic_match("ACME Inc", "ACME Incorporated")
    assert is_semantic_match("Globex GmbH", "Globex LLC")
    assert is_semantic_match("Intl Widgets", "International Widgets")
    assert not is_semantic_match("ACME Inc", "Globex Inc")
    assert not is_semantic_match("1000", "1001")


def test_reclassify_uses_llm_only_on_text_mismatches(monkeypatch):
    entries = [
        {
            "difference_type": "VALUE_MISMATCH",
            "preload_value": "ACME Inc",
            "postload_value": "ACME Corp",
            "field_name": "NAME1",
        },
        {
            "difference_type": "DROPPED_RECORD",
            "preload_value": "Present",
            "postload_value": "NULL",
            "field_name": "Entire Record",
        },
    ]

    def fake_chat(*_args, **_kwargs):
        return '{"matches":[{"index":0,"match":true}]}'

    monkeypatch.setattr("services.semantic_match.bedrock_llm.chat", fake_chat)
    monkeypatch.setattr(
        "services.semantic_match.bedrock_llm.strip_markdown_fences",
        lambda raw: raw,
    )
    out = reclassify_discrepancies(entries)
    assert out[0]["difference_type"] == "SEMANTIC_MATCH"
    assert out[0]["severity"] == "info"
    assert out[1]["difference_type"] == "DROPPED_RECORD"
