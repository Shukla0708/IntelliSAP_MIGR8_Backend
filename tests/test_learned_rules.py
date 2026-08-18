from services import learned_rules
from services.rule_suggester import suggest_rules
from services.rule_templates import SEED_TEMPLATES


def test_canonical_key_normalizes_company_code():
    assert learned_rules.canonical_key("Company Code") == "bukrs"
    assert learned_rules.canonical_key("BUKRS") == "bukrs"


def test_learned_rule_used_when_samples_fit():
    learned = {
        "bukrs": {
            "name": "bukrs",
            "aliases": "company code",
            "flag_mandatory": True,
            "flag_null": False,
            "flag_email": False,
            "flag_mobile": False,
            "flag_date": False,
            "flag_special_chars": False,
            "case_format": "uppercase",
            "data_type": "char",
            "max_length": 4,
            "decimal_length": None,
            "regex": "[A-Z0-9]{4}",
            "regex_prompt": None,
            "learned": True,
            "active": True,
        }
    }
    result = suggest_rules(
        [{"field_name": "Company Code", "samples": ["1000", "2000", "3000"]}],
        SEED_TEMPLATES,
        embed_fn=lambda texts: (_ for _ in ()).throw(AssertionError("no embed")),
        chat_fn=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no llm")),
        regex_fn=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no regex")),
        learned=learned,
    )
    sug = result["suggestions"][0]
    assert sug["suggestion_source"] == "learned"
    assert sug["max_length"] == 4
    assert sug["rule_source"] == "learned"
