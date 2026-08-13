"""Tests for GET /api/projects/{project_id}/report."""
import uuid

import pytest
from fastapi.testclient import TestClient

from main import app
from db.database import SessionLocal
from db.models import User
from auth import hash_password, create_access_token


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
        full_name="Report Tester",
        email=f"report-{suffix}@example.com",
        password_hash=hash_password("test-password-123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(str(user.id))
    yield {"user": user, "headers": {"Authorization": f"Bearer {token}"}}
    db.delete(db.get(User, user.id) or user)
    db.commit()


def _create_project(client: TestClient, headers: dict, name: str) -> str:
    res = client.post("/api/projects/", json={"name": name}, headers=headers)
    assert res.status_code == 200, res.text
    return res.json()["id"]


def test_project_report_empty(client, auth_user):
    headers = auth_user["headers"]
    project_id = _create_project(client, headers, f"Report-{uuid.uuid4().hex[:8]}")

    res = client.get(f"/api/projects/{project_id}/report", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["project"]["id"] == project_id
    assert body["validation"]["totalRuns"] == 0
    assert body["validation"]["completedRuns"] == 0
    assert body["readiness"]["validation"] == 0.0
    assert body["validation"]["recentRuns"] == []


def test_project_report_not_found_for_other_user(client, auth_user):
    headers = auth_user["headers"]
    project_id = _create_project(client, headers, f"Report-{uuid.uuid4().hex[:8]}")

    suffix = uuid.uuid4().hex[:12]
    other = User(
        full_name="Other User",
        email=f"other-{suffix}@example.com",
        password_hash=hash_password("test-password-123"),
    )
    db = SessionLocal()
    try:
        db.add(other)
        db.commit()
        other_token = create_access_token(str(other.id))
        other_headers = {"Authorization": f"Bearer {other_token}"}

        res = client.get(f"/api/projects/{project_id}/report", headers=other_headers)
        assert res.status_code == 404
    finally:
        db.delete(db.get(User, other.id) or other)
        db.commit()
        db.close()
