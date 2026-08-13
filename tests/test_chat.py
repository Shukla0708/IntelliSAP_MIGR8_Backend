"""Grounded chatbot — prefilter and context pack (mocked Bedrock)."""
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from main import app
from db.database import SessionLocal
from db.models import User, ValidationProject, ValidationRun, ValidationException
from auth import hash_password, create_access_token
from schemas.chat import ChatContextIn
from services import chat_service


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
        full_name="Chat Tester",
        email=f"chat-{suffix}@example.com",
        password_hash=hash_password("test-password-123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(str(user.id))
    yield {"user": user, "headers": {"Authorization": f"Bearer {token}"}}
    db.delete(db.get(User, user.id) or user)
    db.commit()


def test_prefilter_refuses_off_topic():
    assert chat_service._prefilter("what's the weather today?", [])
    assert chat_service._prefilter("write me a poem", [])
    assert chat_service._prefilter("hi", []) is not None


def test_prefilter_allows_domain_questions():
    assert chat_service._prefilter("duplicate key errors in last validation run", []) is None
    assert chat_service._prefilter("why is CUSTOMER_ID failing?", []) is None


def test_context_pack_includes_latest_run(db, auth_user):
    user = auth_user["user"]
    project = ValidationProject(user_id=user.id, name="Chat Project")
    db.add(project)
    db.commit()
    db.refresh(project)
    run = ValidationRun(
        project_id=project.id,
        name="Sales check",
        status="completed",
        total_records=10,
        invalid_rows=2,
        total_errors=3,
        health_score=80,
        errors_by_type=[{"label": "Duplicate", "value": 100}],
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    db.add(ValidationException(
        run_id=run.id,
        row_number=4,
        field_name="CustomerID",
        actual_value="1 | A",
        expected_value="Unique composite",
        error_type="Duplicate composite key value (same as row 2)",
        severity="error",
    ))
    db.commit()

    pack = chat_service.build_context_pack(
        db, user, ChatContextIn(page="dashboard", project_id=str(project.id))
    )
    latest = pack["latestCompletedValidationRun"]
    assert latest["name"] == "Sales check"
    assert latest["exceptionSample"][0]["field"] == "CustomerID"


@patch("services.chat_service.bedrock_llm.chat", return_value="CustomerID is duplicated on row 4.")
def test_chat_endpoint_uses_pack(mock_chat, client, auth_user, db):
    project = ValidationProject(user_id=auth_user["user"].id, name="P")
    db.add(project)
    db.commit()
    res = client.post(
        "/api/chat/",
        headers=auth_user["headers"],
        json={
            "message": "duplicate key errors in last validation run",
            "context": {"page": "dashboard", "project_id": str(project.id)},
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["refused"] is False
    assert "duplicated" in body["reply"]
    mock_chat.assert_called_once()


def test_chat_endpoint_refuses_weather(client, auth_user):
    res = client.post(
        "/api/chat/",
        headers=auth_user["headers"],
        json={"message": "what's the weather in Delhi?"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["refused"] is True
    assert "validation" in body["reply"].lower()
