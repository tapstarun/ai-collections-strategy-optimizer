"""API-level tests: auth, RBAC, data isolation, rate limiting, error handling."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app, limiter

AGENT_A = {"X-Agent-Id": "agent_a", "X-Role": "agent"}
AGENT_B = {"X-Agent-Id": "agent_b", "X-Role": "agent"}
SUPERVISOR = {"X-Agent-Id": "sup_1", "X-Role": "supervisor"}


@pytest.fixture
def client():
    # Reset the rate limiter between tests so limits don't bleed across cases.
    limiter.reset()
    return TestClient(app)


def test_health_open(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_missing_credentials_401(client):
    r = client.post("/borrowers/B001/strategy")
    assert r.status_code == 401


def test_agent_can_access_own_borrower(client):
    r = client.post("/borrowers/B001/strategy", headers=AGENT_A)  # B001 -> agent_a
    assert r.status_code == 200
    assert r.json()["segment"]


def test_agent_blocked_from_other_portfolio(client):
    # B006 belongs to agent_b; agent_a must be denied.
    r = client.post("/borrowers/B006/strategy", headers=AGENT_A)
    assert r.status_code == 403


def test_supervisor_sees_all(client):
    r = client.post("/borrowers/B006/strategy", headers=SUPERVISOR)
    assert r.status_code == 200


def test_unknown_borrower_404(client):
    r = client.post("/borrowers/NOPE/strategy", headers=SUPERVISOR)
    assert r.status_code == 404


def test_explain_respects_isolation(client):
    assert client.get("/borrowers/B006/explain", headers=AGENT_A).status_code == 403
    assert client.get("/borrowers/B006/explain", headers=AGENT_B).status_code == 200


def test_rate_limit_returns_429(client):
    limiter.reset()
    # default limit is 30/minute; the 31st request should be rejected.
    last = None
    for _ in range(35):
        last = client.post("/borrowers/B001/strategy", headers=AGENT_A)
    assert last.status_code == 429
