"""FastAPI application for the Collections Strategy Optimizer.

Layers (built incrementally):
  - Deterministic decision engine (segmentation + strategy) — explainable & auditable.
  - RBAC + per-agent data isolation + rate limiting (this step).
  - LLM message generation with safe fallback (Step 6).
  - Audit log + bonus endpoints (Step 7).

Note: this module intentionally does NOT use `from __future__ import annotations`.
FastAPI must resolve route parameter/response types at decoration time, and the
slowapi `@limiter.limit` wrapper hides the signature, so stringized annotations cannot
be resolved for the request-body model. Keeping real annotations here avoids that.
"""
from typing import Annotated

from fastapi import Body, Depends, FastAPI, HTTPException, Request
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from . import audit
from .auth import (
    Principal,
    authorize_borrower_access,
    can_execute_action,
    get_principal,
    require_api_key,
    require_supervisor,
)
from .config import RATE_LIMIT
from .engine import build_explanation, build_strategy
from .models import (
    AuditEntry,
    ExecuteRequest,
    ExecuteResult,
    Explanation,
    QueueItem,
    Strategy,
)
from .segmentation import segment_borrower
from .store import all_borrowers, get_borrower
from .strategy import priority_score, recommend_action, recovery_probability


def _rate_key(request: Request) -> str:
    """Rate-limit on the client IP, which the caller cannot spoof via a header.

    We deliberately do NOT key on `X-Agent-Id`: it is client-supplied, so an attacker
    could rotate it to bypass the limit. IP is the non-spoofable anchor at this layer;
    in production the gateway/WAF would also rate-limit on authenticated identity.
    """
    return get_remote_address(request)


limiter = Limiter(key_func=_rate_key, default_limits=[RATE_LIMIT])

app = FastAPI(
    title="AI-Based Collections Strategy Optimizer",
    description=(
        "Recommends respectful, compliant outreach strategies for delinquent "
        "borrowers. Deterministic rules make every financial decision (explainable "
        "and auditable); an LLM only drafts the customer message."
    ),
    version="0.1.0",
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


def _load_authorized_borrower(borrower_id: str, principal: Principal):
    """Fetch a borrower and enforce data isolation, or raise 404/403."""
    borrower = get_borrower(borrower_id)
    if borrower is None:
        raise HTTPException(status_code=404, detail="Borrower not found")
    authorize_borrower_access(principal, borrower)
    return borrower


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/borrowers/{borrower_id}/strategy", response_model=Strategy, tags=["strategy"])
@limiter.limit(RATE_LIMIT)
def get_strategy(
    request: Request,
    borrower_id: str,
    principal: Principal = Depends(get_principal),
) -> Strategy:
    borrower = _load_authorized_borrower(borrower_id, principal)
    return build_strategy(borrower)


@app.get("/borrowers/{borrower_id}/explain", response_model=Explanation, tags=["strategy"])
@limiter.limit(RATE_LIMIT)
def explain(
    request: Request,
    borrower_id: str,
    principal: Principal = Depends(get_principal),
) -> Explanation:
    """Answer 'Why is this borrower assigned to X?'"""
    borrower = _load_authorized_borrower(borrower_id, principal)
    return build_explanation(borrower)


@app.get("/queue", response_model=list[QueueItem], tags=["workload"])
@limiter.limit(RATE_LIMIT)
def queue(
    request: Request,
    principal: Principal = Depends(get_principal),
) -> list[QueueItem]:
    """Workload prioritisation: borrowers ranked by expected recoverable value.

    Scoped by RBAC — agents see only their own portfolio; supervisors see everyone.
    """
    items: list[QueueItem] = []
    for b in all_borrowers():
        if principal.role.value == "agent" and b.assigned_agent_id != principal.agent_id:
            continue
        segment, _ = segment_borrower(b)
        action, _ = recommend_action(b, segment)
        recovery, _ = recovery_probability(b, segment)
        items.append(
            QueueItem(
                borrower_id=b.borrower_id,
                name=b.name,
                segment=segment,
                next_best_action=action,
                recovery_probability=recovery,
                overdue_amount=b.overdue_amount,
                priority_score=priority_score(recovery, b.overdue_amount),
            )
        )
    items.sort(key=lambda i: i.priority_score, reverse=True)
    return items


@app.post(
    "/borrowers/{borrower_id}/execute", response_model=ExecuteResult, tags=["actions"]
)
@limiter.limit(RATE_LIMIT)
def execute(
    request: Request,
    borrower_id: str,
    body: Annotated[ExecuteRequest, Body()],
    principal: Principal = Depends(get_principal),
) -> ExecuteResult:
    """Record execution of an action. MOCK ONLY — no SMS/email/call is actually sent;
    the action is written to the audit log. Escalation is supervisor-only."""
    borrower = _load_authorized_borrower(borrower_id, principal)
    if not can_execute_action(principal, body.action.value):
        raise HTTPException(
            status_code=403, detail="Escalation requires supervisor role."
        )
    entry = audit.record(
        actor_id=principal.agent_id,
        actor_role=principal.role.value,
        borrower_id=borrower.borrower_id,
        event="executed",
        detail=f"action={body.action.value} (mock — not actually sent)",
    )
    return ExecuteResult(
        borrower_id=borrower.borrower_id,
        action=body.action,
        status="recorded (mock)",
        audit_id=entry.audit_id,
    )


@app.get("/audit", response_model=list[AuditEntry], tags=["actions"])
@limiter.limit(RATE_LIMIT)
def get_audit(
    request: Request,
    principal: Principal = Depends(require_supervisor),
) -> list[AuditEntry]:
    """Audit trail of executed actions. Supervisor-only."""
    return audit.all_entries()
