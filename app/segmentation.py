"""Deterministic borrower segmentation.

This is the explainable core of the system. Each borrower is assigned exactly one
segment by transparent, ordered rules — NO machine learning, NO LLM. Every decision
returns human-readable `reasons`, which power the `/explain` endpoint ("Why is this
borrower assigned to hardship support?").

Rule ordering is intentional and borrower-protective: hardship is checked first so a
struggling customer is never routed to aggressive escalation. The first matching rule
wins.

Thresholds are deliberately simple and centralised here so they are easy to audit and
tune. In production this layer is where a calibrated risk model would slot in, behind
the same `(segment, reasons)` contract.
"""
from __future__ import annotations

from .models import Borrower, Segment

# --- Tunable thresholds (single source of truth, easy to audit) --------------
HIGH_RISK_DPD = 90          # days past due that triggers high-risk escalation
HIGH_BALANCE = 50_000.0     # large outstanding balance
HABITUAL_LATE_COUNT = 3     # prior late payments that mark a habitual pattern
LOW_DPD = 30                # "early stage" delinquency ceiling


def _responded_ever(borrower: Borrower) -> bool:
    """True if the borrower has responded to at least one contact attempt."""
    return any(c.responded for c in borrower.contact_history)


def _has_data(borrower: Borrower) -> bool:
    """Guard against meaningless input (nothing actually overdue)."""
    return borrower.days_past_due > 0 and borrower.overdue_amount > 0


def segment_borrower(borrower: Borrower) -> tuple[Segment, list[str]]:
    """Return (segment, reasons). Reasons are ordered, plain-language, and audit-ready."""
    # Edge case: nothing genuinely overdue -> do not chase, send for manual review.
    if not _has_data(borrower):
        return Segment.MANUAL_REVIEW, [
            "No genuine delinquency detected "
            f"(days_past_due={borrower.days_past_due}, overdue_amount={borrower.overdue_amount:.0f}).",
            "Routed to manual review rather than outreach to avoid contacting a borrower in error.",
        ]

    responded = _responded_ever(borrower)

    # 1) Hardship — highest priority, borrower-protective. Handle gently first.
    if borrower.hardship_indicator:
        return Segment.HARDSHIP_CASE, [
            "Hardship indicator is set for this borrower.",
            "Hardship takes precedence over all other signals to ensure supportive, "
            "non-aggressive treatment.",
        ]

    # 2) High-Risk Escalation — deep delinquency or large balance with no engagement.
    if borrower.days_past_due >= HIGH_RISK_DPD:
        return Segment.HIGH_RISK_ESCALATION, [
            f"Days past due ({borrower.days_past_due}) is at or beyond the high-risk "
            f"threshold ({HIGH_RISK_DPD}).",
            "Late-stage delinquency warrants escalation / specialist handling.",
        ]
    if borrower.overdue_amount >= HIGH_BALANCE and not responded:
        return Segment.HIGH_RISK_ESCALATION, [
            f"Large outstanding balance ({borrower.overdue_amount:.0f}) at or above "
            f"the high-value threshold ({HIGH_BALANCE:.0f}).",
            "No response to any prior contact attempt, increasing recovery risk.",
        ]

    # 3) Unresponsive — has been contacted but never engaged.
    if borrower.contact_history and not responded:
        return Segment.UNRESPONSIVE, [
            f"Contacted {len(borrower.contact_history)} time(s) with no response.",
            "Needs a channel/timing change to re-establish contact.",
        ]

    # 4) Habitual Late Payer — repeated late pattern but does eventually engage/pay.
    if borrower.prior_late_payments >= HABITUAL_LATE_COUNT:
        return Segment.HABITUAL_LATE_PAYER, [
            f"{borrower.prior_late_payments} prior late payments indicate a habitual pattern.",
            "Tends to pay after a reminder; a light-touch nudge is usually sufficient.",
        ]

    # 5) Willing but Delayed — early stage, engaged, generally keeps promises.
    if borrower.days_past_due <= LOW_DPD and responded:
        reasons = [
            f"Early-stage delinquency (days_past_due={borrower.days_past_due} "
            f"<= {LOW_DPD}).",
            "Borrower has responded to contact, signalling willingness to resolve.",
        ]
        if borrower.promises_made and borrower.promises_kept >= borrower.promises_made:
            reasons.append("Has kept prior repayment promises.")
        return Segment.WILLING_BUT_DELAYED, reasons

    # Fallback — signals don't fit a clear bucket -> manual review (never guess).
    return Segment.MANUAL_REVIEW, [
        "Borrower signals do not match a defined segment cleanly.",
        "Routed to manual review for a human decision rather than an automated guess.",
    ]
