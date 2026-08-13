"""Tests for validation run naming (unique per project)."""
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
    """Create a disposable user + Bearer token; clean up after the test."""
    suffix = uuid.uuid4().hex[:12]
    user = User(
        full_name="Run Name Tester",
        email=f"run-name-{suffix}@example.com",
        password_hash=hash_password("test-password-123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(str(user.id))
    yield {"user": user, "headers": {"Authorization": f"Bearer {token}"}}
    # Cascade deletes projects/runs via FK
    db.delete(db.get(User, user.id) or user)
    db.commit()


def _create_project(client: TestClient, headers: dict, name: str) -> str:
    res = client.post("/api/projects/", json={"name": name}, headers=headers)
    assert res.status_code == 200, res.text
    return res.json()["id"]


def test_create_run_with_name(client, auth_user):
    headers = auth_user["headers"]
    project_id = _create_project(client, headers, f"Proj-{uuid.uuid4().hex[:8]}")

    res = client.post(
        f"/api/runs/?project_id={project_id}",
        json={"name": "  Sprint A check  "},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    run_id = res.json()["run_id"]

    listed = client.get(f"/api/projects/{project_id}/runs", headers=headers)
    assert listed.status_code == 200
    runs = listed.json()
    match = next(r for r in runs if r["id"] == run_id)
    assert match["name"] == "Sprint A check"


def test_duplicate_name_same_project_returns_409(client, auth_user):
    headers = auth_user["headers"]
    project_id = _create_project(client, headers, f"Proj-{uuid.uuid4().hex[:8]}")
    body = {"name": "Duplicate Run"}

    first = client.post(f"/api/runs/?project_id={project_id}", json=body, headers=headers)
    assert first.status_code == 200, first.text

    second = client.post(f"/api/runs/?project_id={project_id}", json=body, headers=headers)
    assert second.status_code == 409
    assert second.json()["detail"] == (
        "A validation run with this name already exists in this project"
    )


def test_same_name_different_projects_allowed(client, auth_user):
    headers = auth_user["headers"]
    p1 = _create_project(client, headers, f"Proj-A-{uuid.uuid4().hex[:8]}")
    p2 = _create_project(client, headers, f"Proj-B-{uuid.uuid4().hex[:8]}")
    body = {"name": "Shared Run Name"}

    r1 = client.post(f"/api/runs/?project_id={p1}", json=body, headers=headers)
    r2 = client.post(f"/api/runs/?project_id={p2}", json=body, headers=headers)
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert r1.json()["run_id"] != r2.json()["run_id"]


def test_list_runs_across_projects(client, auth_user):
    headers = auth_user["headers"]
    p1 = _create_project(client, headers, f"Proj-A-{uuid.uuid4().hex[:8]}")
    p2 = _create_project(client, headers, f"Proj-B-{uuid.uuid4().hex[:8]}")

    r1 = client.post(
        f"/api/runs/?project_id={p1}",
        json={"name": "Cross List A"},
        headers=headers,
    )
    r2 = client.post(
        f"/api/runs/?project_id={p2}",
        json={"name": "Cross List B"},
        headers=headers,
    )
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text

    all_runs = client.get("/api/runs/", headers=headers)
    assert all_runs.status_code == 200, all_runs.text
    rows = all_runs.json()
    ids = {row["id"] for row in rows}
    assert r1.json()["run_id"] in ids
    assert r2.json()["run_id"] in ids
    match = next(row for row in rows if row["id"] == r1.json()["run_id"])
    assert match["project_id"] == p1
    assert "project_name" in match

    filtered = client.get(f"/api/runs/?project_id={p1}", headers=headers)
    assert filtered.status_code == 200
    filtered_ids = {row["id"] for row in filtered.json()}
    assert r1.json()["run_id"] in filtered_ids
    assert r2.json()["run_id"] not in filtered_ids


def test_empty_name_returns_422(client, auth_user):
    headers = auth_user["headers"]
    project_id = _create_project(client, headers, f"Proj-{uuid.uuid4().hex[:8]}")

    res = client.post(
        f"/api/runs/?project_id={project_id}",
        json={"name": "   "},
        headers=headers,
    )
    assert res.status_code == 422


def test_get_run_detail(client, auth_user):
    headers = auth_user["headers"]
    project_id = _create_project(client, headers, f"Proj-{uuid.uuid4().hex[:8]}")

    created = client.post(
        f"/api/runs/?project_id={project_id}",
        json={"name": "Detail Run"},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    run_id = created.json()["run_id"]

    detail = client.get(f"/api/runs/{run_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["id"] == run_id
    assert body["name"] == "Detail Run"
    assert body["status"] == "draft"
    assert body["has_source_file"] is False
    assert body["fields"] == []

    rules = client.put(
        f"/api/runs/{run_id}/rules",
        json=[{
            "field_name": "CUSTOMER_ID",
            "flag_key": True,
            "flag_mandatory": True,
        }],
        headers=headers,
    )
    assert rules.status_code == 200, rules.text

    listed = client.get(f"/api/projects/{project_id}/runs", headers=headers)
    match = next(r for r in listed.json() if r["id"] == run_id)
    assert match["status"] == "rules_configured"
