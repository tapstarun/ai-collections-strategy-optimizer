"""Mocked role-based access control and borrower data isolation.

PROTOTYPE NOTE: authentication is simulated via request headers (`X-Agent-Id`,
`X-Role`). This stands in for real identity. The *authorization* logic, however —
role checks and per-agent data isolation — mirrors how a production system would
behave and is enforced on every protected endpoint via FastAPI dependencies
(default-deny).

In production this would be:
  - Identity: OAuth2/OIDC + signed JWT (not trusted headers).
  - Data isolation: row-level security in the database keyed on the agent's portfolio.
  - Sensitive fields: encrypted at rest (KMS), decrypted only for authorized roles.
See README "Security model" for the full mapping.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from fastapi import Depends, Header, HTTPException

from .models import Borrower


class Role(str, Enum):
    AGENT = "agent"
    SUPERVISOR = "supervisor"


@dataclass(frozen=True)
class Principal:
    """The authenticated caller."""
    agent_id: str
    role: Role


def get_principal(
    x_agent_id: str | None = Header(default=None, alias="X-Agent-Id"),
    x_role: str | None = Header(default=None, alias="X-Role"),
) -> Principal:
    """Resolve the caller from headers. Default-deny: missing/invalid -> 401."""
    if not x_agent_id or not x_role:
        raise HTTPException(
            status_code=401,
            detail="Missing credentials (X-Agent-Id and X-Role headers required).",
        )
    try:
        role = Role(x_role.lower())
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid role.")
    return Principal(agent_id=x_agent_id, role=role)


def require_supervisor(principal: Principal = Depends(get_principal)) -> Principal:
    """Guard endpoints restricted to supervisors (audit log, etc.)."""
    if principal.role != Role.SUPERVISOR:
        raise HTTPException(status_code=403, detail="Supervisor role required.")
    return principal


def authorize_borrower_access(principal: Principal, borrower: Borrower) -> None:
    """Enforce data isolation: agents may only access their own portfolio.

    Supervisors may access all borrowers. Raises 403 on violation.
    """
    if principal.role == Role.SUPERVISOR:
        return
    if borrower.assigned_agent_id != principal.agent_id:
        # Generic message — do not leak whether the borrower exists in another portfolio.
        raise HTTPException(status_code=403, detail="Not authorized for this borrower.")


def can_execute_action(principal: Principal, action_value: str) -> bool:
    """Escalation is a supervisor-only action; agents must hand it up."""
    if action_value == "escalation":
        return principal.role == Role.SUPERVISOR
    return True
