"""Tests for bonus features: workload queue, execute (mock), audit log + RBAC."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import audit
from app.main import app, limiter

AGENT_A = {"X-Agent-Id": "agent_a", "X-Role": "agent"}
AGENT_B = {"X-Agent-Id": "agent_b", "X-Role": "agent"}
SUPERVISOR = {"X-Agent-Id": "sup_1", "X-Role": "supervisor"}


@pytest.fixture
def client():
    limiter.reset()
    audit.reset()
    return TestClient(app)


def test_queue_sorted_by_priority_desc(client):
    items = client.get("/queue", headers=SUPERVISOR).json()
    scores = [i["priority_score"] for i in items]
    assert scores == sorted(scores, reverse=True)


def test_queue_scoped_to_agent_portfolio(client):
    items = client.get("/queue", headers=AGENT_A).json()
    ids = {i["borrower_id"] for i in items}
    # agent_a owns B001-B005 only.
    assert ids <= {"B001", "B002", "B003", "B004", "B005"}
    assert "B006" not in ids


def test_execute_records_audit(client):
    r = client.post(
        "/borrowers/B001/execute", headers=AGENT_A, json={"action": "SMS reminder"}
    )
    assert r.status_code == 200
    assert r.json()["status"] == "recorded (mock)"

    log = client.get("/audit", headers=SUPERVISOR).json()
    assert len(log) == 1
    assert log[0]["actor_id"] == "agent_a"
    assert log[0]["borrower_id"] == "B001"
    assert log[0]["timestamp"]


def test_agent_cannot_view_audit(client):
    assert client.get("/audit", headers=AGENT_A).status_code == 403


def test_agent_cannot_escalate(client):
    r = client.post(
        "/borrowers/B005/execute", headers=AGENT_A, json={"action": "escalation"}
    )
    assert r.status_code == 403


def test_supervisor_can_escalate(client):
    r = client.post(
        "/borrowers/B005/execute", headers=SUPERVISOR, json={"action": "escalation"}
    )
    assert r.status_code == 200


def test_execute_respects_isolation(client):
    # agent_a cannot execute on agent_b's borrower -> 404 (enumeration-safe).
    r = client.post(
        "/borrowers/B006/execute", headers=AGENT_A, json={"action": "SMS reminder"}
    )
    assert r.status_code == 404


def test_execute_rejects_unknown_action(client):
    r = client.post(
        "/borrowers/B001/execute", headers=AGENT_A, json={"action": "nuke"}
    )
    assert r.status_code == 422  # Pydantic enum validation
