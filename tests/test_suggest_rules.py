"""AI-suggested validation rules — heuristics, constraints, merge, API."""
import inspect
import uuid
from unittest.mock import patch

import numpy as np
import pytest
from fastapi.testclient import TestClient

from main import app
from db.database import SessionLocal
from db.models import User
from auth import hash_password, create_access_token
from routers import validation as validation_router
from services import rule_suggester
from services.rule_templates import SEED_TEMPLATES


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def auth_user(db):
    suffix = uuid.uuid4().hex[:12]
    user = User(
        full_name="Suggest Tester",
        email=f"suggest-{suffix}@example.com",
        password_hash=hash_password("test-password-123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(str(user.id))
    yield {"user": user, "headers": {"Authorization": f"Bearer {token}"}}
    db.delete(db.get(User, user.id) or user)
    db.commit()


def _boom(*_args, **_kwargs):
    raise AssertionError("should not be called")


def _zeros(texts):
    return np.zeros((len(texts), 4), dtype=np.float32)


def _template(name: str) -> dict:
    return dict(next(item for item in SEED_TEMPLATES if item["name"] == name))


def test_heuristic_email_does_not_call_bedrock():
    result = rule_suggester.suggest_rules(
        [{"field_name": "Customer Email", "samples": ["a@b.com", "c@d.org"]}],
        SEED_TEMPLATES,
        embed_fn=_boom,
        chat_fn=_boom,
        regex_fn=_boom,
    )
    assert result["warning"] is None
    sug = result["suggestions"][0]
    assert sug["flag_email"] is True
    assert sug["flag_key"] is False
    assert sug["suggestion_source"] in ("heuristic", "catalog")
    assert sug["rule_source"] == "ai"


def test_vbeln_is_char10_not_int():
    result = rule_suggester.suggest_rules(
        [{"field_name": "vbeln", "samples": ["0005000012", "0005000013", "0005000014"]}],
        SEED_TEMPLATES,
        embed_fn=_boom,
        chat_fn=_boom,
        regex_fn=_boom,
    )
    sug = result["suggestions"][0]
    assert sug["data_type"] == "char"
    assert sug["max_length"] == 10
    assert sug["flag_key"] is False
    assert sug["suggestion_source"] == "catalog"


def test_sales_org_and_distr_chan_use_sap_char_lengths():
    result = rule_suggester.suggest_rules(
        [
            {"field_name": "sales org", "samples": ["1000", "2000", "3000"]},
            {"field_name": "distr chan", "samples": ["10", "20", "10"]},
            {"field_name": "division", "samples": ["00", "01", "02"]},
            {"field_name": "doc type", "samples": ["OR", "OR", "OR"]},
        ],
        SEED_TEMPLATES,
        embed_fn=_boom,
        chat_fn=_boom,
        regex_fn=_boom,
    )
    by_name = {row["field_name"]: row for row in result["suggestions"]}
    assert by_name["sales org"]["data_type"] == "char"
    assert by_name["sales org"]["max_length"] == 4
    assert by_name["distr chan"]["max_length"] == 2
    assert by_name["division"]["max_length"] == 2
    assert by_name["doc type"]["max_length"] == 4
    assert all(row["data_type"] != "int" for row in result["suggestions"])


def test_customer_id_does_not_get_flag_key():
    result = rule_suggester.suggest_rules(
        [{"field_name": "CUSTOMER_ID", "samples": ["0000123456"]}],
        SEED_TEMPLATES,
        embed_fn=_boom,
        chat_fn=_boom,
        regex_fn=_boom,
    )
    sug = result["suggestions"][0]
    assert sug["flag_key"] is False
    assert sug["data_type"] == "char"
    assert sug["max_length"] == 10


def test_similarity_below_floor_leaves_defaults():
    def retrieve(fields, catalog, embed_fn):
        return [(fields[0], [])]

    with patch.object(rule_suggester, "_retrieve", side_effect=retrieve):
        result = rule_suggester.suggest_rules(
            [{"field_name": "zzzz_unrelated_foobar", "samples": ["aaa", "bbb"]}],
            SEED_TEMPLATES,
            embed_fn=_zeros,
            chat_fn=_boom,
            regex_fn=_boom,
        )
    assert result["suggestions"] == []


def test_second_click_does_not_clobber_user_flag():
    existing = [
        {
            "field_name": "EMAIL",
            "flag_email": False,
            "flag_key": False,
            "rule_source": "user",
        },
        {
            "field_name": "MOBILE",
            "flag_mobile": False,
            "flag_key": False,
            "rule_source": "ai",
        },
    ]
    incoming = [
        {
            "field_name": "EMAIL",
            "flag_email": True,
            "flag_key": True,
            "rule_source": "ai",
        },
        {
            "field_name": "MOBILE",
            "flag_mobile": True,
            "flag_key": True,
            "rule_source": "ai",
        },
    ]
    merged = rule_suggester.merge_into_existing(existing, incoming)
    by_name = {row["field_name"]: row for row in merged}
    assert by_name["EMAIL"]["flag_email"] is False
    assert by_name["EMAIL"]["rule_source"] == "user"
    assert by_name["MOBILE"]["flag_mobile"] is True
    assert by_name["MOBILE"]["flag_key"] is False
    assert by_name["MOBILE"]["rule_source"] == "ai"


def test_llm_invalid_json_falls_back_to_catalog():
    plant = _template("plant")
    company = _template("company_code")

    def retrieve(fields, catalog, embed_fn):
        return [(fields[0], [(plant, 0.58), (company, 0.55)])]

    with patch.object(rule_suggester, "_retrieve", side_effect=retrieve):
        result = rule_suggester.suggest_rules(
            [{"field_name": "site_location_code", "samples": ["1000"]}],
            [plant, company],
            embed_fn=_zeros,
            chat_fn=lambda *_a, **_k: "this is not json",
            regex_fn=_boom,
        )
    assert result["warning"]
    sug = result["suggestions"][0]
    assert sug["flag_key"] is False
    assert sug["template_name"] == "plant"
    assert sug["suggestion_source"] == "catalog"


def test_regex_omitted_when_generator_fails():
    iban = _template("iban")

    def retrieve(fields, catalog, embed_fn):
        return [(fields[0], [(iban, 0.92)])]

    def bad_regex(_name, _prompt):
        raise ValueError("not a compilable pattern")

    with patch.object(rule_suggester, "_retrieve", side_effect=retrieve):
        result = rule_suggester.suggest_rules(
            [{"field_name": "IBAN", "samples": ["DE89370400440532013000"]}],
            [iban],
            embed_fn=_zeros,
            chat_fn=_boom,
            regex_fn=bad_regex,
        )
    sug = result["suggestions"][0]
    assert sug["regex"] is None
    assert sug["regex_prompt"]


def test_regex_applied_when_generator_succeeds():
    iban = _template("iban")

    def retrieve(fields, catalog, embed_fn):
        return [(fields[0], [(iban, 0.92)])]

    with patch.object(rule_suggester, "_retrieve", side_effect=retrieve):
        result = rule_suggester.suggest_rules(
            [{"field_name": "IBAN", "samples": ["DE89370400440532013000"]}],
            [iban],
            embed_fn=_zeros,
            chat_fn=_boom,
            regex_fn=lambda _n, _p: r"[A-Z]{2}\d{2}[A-Z0-9]+",
        )
    assert result["suggestions"][0]["regex"] == r"[A-Z]{2}\d{2}[A-Z0-9]+"


def test_empty_header_skipped():
    result = rule_suggester.suggest_rules(
        [{"field_name": "  ", "samples": ["x"]}],
        SEED_TEMPLATES,
        embed_fn=_boom,
        chat_fn=_boom,
        regex_fn=_boom,
    )
    assert result["suggestions"] == []


def test_upload_path_does_not_call_suggester():
    source = inspect.getsource(validation_router.upload_source)
    assert "suggest_rules" not in source
    assert "rule_suggester" not in source


def test_suggest_rules_endpoint_returns_suggestions_only(client, auth_user):
    canned = {
        "suggestions": [
            {
                "field_name": "EMAIL",
                "flag_key": False,
                "flag_mandatory": False,
                "flag_null": False,
                "flag_email": True,
                "flag_mobile": False,
                "flag_date": False,
                "flag_special_chars": False,
                "case_format": None,
                "data_type": "string",
                "max_length": None,
                "decimal_length": None,
                "regex": None,
                "regex_prompt": None,
                "rule_source": "ai",
                "suggestion_source": "heuristic",
                "template_name": "email",
            }
        ],
        "warning": None,
    }
    with patch.object(validation_router.rule_suggester, "suggest_rules", return_value=canned):
        res = client.post(
            "/api/runs/suggest-rules",
            json={"fields": [{"field_name": "EMAIL", "samples": ["a@b.com"]}]},
            headers=auth_user["headers"],
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["suggestions"][0]["flag_email"] is True
    assert body["suggestions"][0]["flag_key"] is False
    assert body["warning"] is None


def test_suggest_rules_requires_auth(client):
    res = client.post(
        "/api/runs/suggest-rules",
        json={"fields": [{"field_name": "EMAIL", "samples": []}]},
    )
    assert res.status_code in (401, 403)
