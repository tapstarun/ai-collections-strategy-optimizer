"""Role-based access control and borrower data isolation.

TRUST MODEL (read this — it is the key security caveat):
Identity is *simulated* via request headers (`X-Agent-Id`, `X-Role`). These headers are
client-supplied and therefore SPOOFABLE — in this prototype any caller can claim to be a
supervisor. This is an accepted limitation of a mock; it is NOT a secure auth system.

What IS real and production-shaped:
  - The *authorization* logic — role checks, per-agent data isolation, supervisor-only
    endpoints — enforced default-deny via FastAPI dependencies.
  - An optional shared `API_KEY` gate (`X-API-Key`) so the surface isn't trivially open
    when one is configured.

In production, replace the trusted headers with:
  - Identity: OAuth2/OIDC + signed JWT; role claims come from the verified token, not
    headers. The authorization functions below stay essentially unchanged.
  - Data isolation: database row-level security keyed on the agent's portfolio.
  - Sensitive fields: encrypted at rest (KMS), decrypted only for authorized roles.
See README "Security model & threat notes" for the full mapping.
"""
from __future__ import annotations

import hmac
from dataclasses import dataclass
from enum import Enum

from fastapi import Depends, Header, HTTPException

from .config import API_KEY
from .models import Borrower


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    """Coarse gate: if an API_KEY is configured, require a matching X-API-Key header.

    No-op when API_KEY is unset (frictionless local dev). Uses a constant-time compare
    to avoid leaking the key via timing.
    """
    if not API_KEY:
        return
    if not x_api_key or not hmac.compare_digest(x_api_key, API_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


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
    _api_key: None = Depends(require_api_key),
) -> Principal:
    """Resolve the caller from headers. Default-deny: missing/invalid -> 401.

    Depends on `require_api_key`, so the (optional) API-key gate runs before any
    protected handler. `/health` does not depend on this and stays open.
    """
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

    Supervisors may access all borrowers. For agents, a borrower outside their portfolio
    is reported as 404 (not 403) so they cannot distinguish "exists but not yours" from
    "does not exist" — closing an enumeration oracle. The caller raises 404 first only
    when the id is genuinely unknown for everyone.
    """
    if principal.role == Role.SUPERVISOR:
        return
    if borrower.assigned_agent_id != principal.agent_id:
        # Indistinguishable from a true 404 to avoid leaking existence in other portfolios.
        raise HTTPException(status_code=404, detail="Borrower not found")


def can_execute_action(principal: Principal, action_value: str) -> bool:
    """Escalation is a supervisor-only action; agents must hand it up."""
    if action_value == "escalation":
        return principal.role == Role.SUPERVISOR
    return True
