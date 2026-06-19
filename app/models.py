"""Pydantic schemas for borrowers, strategy output, and API payloads.

These models define the data contract for the whole service. Borrower input is
validated strictly so malformed or hostile payloads are rejected at the edge
(see Security notes in the README).
"""
from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# --- Controlled vocabularies -------------------------------------------------

class Channel(str, Enum):
    SMS = "sms"
    EMAIL = "email"
    CALL = "call"


class Segment(str, Enum):
    WILLING_BUT_DELAYED = "Willing but Delayed"
    HABITUAL_LATE_PAYER = "Habitual Late Payer"
    HARDSHIP_CASE = "Hardship Case"
    UNRESPONSIVE = "Unresponsive"
    HIGH_RISK_ESCALATION = "High-Risk Escalation"
    MANUAL_REVIEW = "Manual Review"  # safe fallback for bad/ambiguous data


class NextBestAction(str, Enum):
    SMS_REMINDER = "SMS reminder"
    EMAIL = "email"
    AGENT_CALL = "agent call"
    PAYMENT_PLAN_OFFER = "payment plan offer"
    HARDSHIP_SUPPORT = "hardship support"
    ESCALATION = "escalation"
    MANUAL_REVIEW = "manual review"


# --- Borrower input ----------------------------------------------------------

class ContactAttempt(BaseModel):
    """One historical outreach attempt and whether the borrower responded."""
    model_config = ConfigDict(extra="forbid")

    channel: Channel
    responded: bool
    # Hour of day (0-23) the contact happened; used to learn best contact time.
    hour: int = Field(ge=0, le=23)


class Borrower(BaseModel):
    """Synthetic delinquent-borrower record. `extra="forbid"` blocks injection
    of unexpected fields via the API."""
    model_config = ConfigDict(extra="forbid")

    borrower_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    # Portfolio owner — used for agent-level data isolation (RBAC).
    assigned_agent_id: str = Field(min_length=1, max_length=64)

    days_past_due: int = Field(ge=0, le=3650)
    overdue_amount: float = Field(ge=0)
    preferred_channel: Channel

    # Behavioural history
    prior_late_payments: int = Field(ge=0, le=1000)
    promises_made: int = Field(ge=0, le=1000)
    promises_kept: int = Field(ge=0, le=1000)
    hardship_indicator: bool = False
    contact_history: list[ContactAttempt] = Field(default_factory=list)

    # Optional free-text note — UNTRUSTED. Treated as data, never instructions,
    # and redacted/sanitised before reaching the LLM.
    notes: Optional[str] = Field(default=None, max_length=2000)


# --- Strategy output ---------------------------------------------------------

class Strategy(BaseModel):
    """Full recommendation for a borrower. Everything except `message_draft` is
    produced by the deterministic engine and is fully explainable."""
    borrower_id: str
    segment: Segment
    next_best_action: NextBestAction
    best_channel: Channel
    best_time: str  # human-readable, e.g. "10:00-12:00"
    recovery_probability: int = Field(ge=0, le=100)
    reasons: list[str]  # why this segment/action — drives the /explain endpoint
    message_draft: Optional[str] = None
    message_source: Optional[str] = None  # "llm" | "template" | "template (safety_fallback)"


class Explanation(BaseModel):
    """Standalone answer to 'Why is this borrower assigned to X?'"""
    borrower_id: str
    segment: Segment
    next_best_action: NextBestAction
    reasons: list[str]


class ExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: NextBestAction


class ExecuteResult(BaseModel):
    borrower_id: str
    action: NextBestAction
    status: str  # always "recorded (mock)" — no real send happens
    audit_id: str


class AuditEntry(BaseModel):
    audit_id: str
    timestamp: str
    actor_id: str
    actor_role: str
    borrower_id: str
    event: str  # "recommended" | "executed" | "safety_fallback"
    detail: str


class QueueItem(BaseModel):
    borrower_id: str
    name: str
    segment: Segment
    next_best_action: NextBestAction
    recovery_probability: int
    overdue_amount: float
    priority_score: float
