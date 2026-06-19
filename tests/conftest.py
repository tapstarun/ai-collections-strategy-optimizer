"""Shared test helpers."""
from __future__ import annotations

from app.models import Borrower, ContactAttempt


def make_borrower(**overrides) -> Borrower:
    """Build a valid baseline borrower, overriding only the fields a test cares about."""
    base = dict(
        borrower_id="T001",
        name="Test Borrower",
        assigned_agent_id="agent_a",
        days_past_due=10,
        overdue_amount=5000.0,
        preferred_channel="sms",
        prior_late_payments=0,
        promises_made=0,
        promises_kept=0,
        hardship_indicator=False,
        contact_history=[ContactAttempt(channel="sms", responded=True, hour=10)],
        notes=None,
    )
    base.update(overrides)
    return Borrower.model_validate(base)
