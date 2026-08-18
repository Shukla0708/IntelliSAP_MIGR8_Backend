"""Tests for Bedrock-backed LLM services (mocked — no real AWS calls)."""
import json
from unittest.mock import patch

import pytest

from services import bedrock_llm, llm_mapping, regex_generator


def test_strip_markdown_fences():
    assert bedrock_llm.strip_markdown_fences('```json\n{"a": 1}\n```') == '{"a": 1}'


@patch("services.regex_generator.bedrock_llm.chat")
def test_generate_regex_parses_json(mock_chat):
    mock_chat.return_value = '{"regex": "H4.*"}'
    assert regex_generator.generate_regex("FIELD", "starts with H4") == "H4.*"
    mock_chat.assert_called_once()


@patch("services.regex_generator.bedrock_llm.chat")
def test_generate_regex_strips_anchors(mock_chat):
    mock_chat.return_value = '{"regex": "^9[0-9]{9}$"}'
    assert regex_generator.generate_regex("MOBILE", "10 digits starting with 9") == "9[0-9]{9}"


@patch("services.llm_mapping.bedrock_llm.chat")
def test_rank_candidates_reorders(mock_chat):
    candidates = [
        {
            "sap_table": "KNA1",
            "sap_field": "NAME1",
            "target_description": "Name",
            "table_description": "Customer",
            "embedding_score": 0.8,
            "datatype_match_score": 1.0,
        },
        {
            "sap_table": "KNA1",
            "sap_field": "ORT01",
            "target_description": "City",
            "table_description": "Customer",
            "embedding_score": 0.6,
            "datatype_match_score": 0.5,
        },
    ]
    mock_chat.return_value = json.dumps([
        {
            "sap_table": "KNA1",
            "sap_field": "ORT01",
            "confidence_score": 90,
            "reasoning": "City field matches the source address city column.",
        },
        {
            "sap_table": "KNA1",
            "sap_field": "NAME1",
            "confidence_score": 70,
            "reasoning": "Name is related but less specific than city.",
        },
    ])
    ranked = llm_mapping.rank_candidates("CITY", "City name", candidates)
    assert ranked[0]["sap_field"] == "ORT01"
    assert ranked[0]["confidence_score"] == 90.0
    assert ranked[1]["sap_field"] == "NAME1"


@patch("services.llm_mapping.bedrock_llm.chat")
def test_rank_candidates_falls_back_when_llm_empty(mock_chat):
    mock_chat.return_value = '{"results":[]}'
    ranked = llm_mapping.rank_candidates("X", None, [{
        "sap_table": "T",
        "sap_field": "F",
        "embedding_score": 0.5,
    }])
    assert ranked[0]["sap_field"] == "F"
    assert "unavailable" in ranked[0]["reasoning"].lower()
