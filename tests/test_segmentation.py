"""Tests for the deterministic segmentation engine."""
from __future__ import annotations

from app.models import ContactAttempt, Segment
from app.segmentation import segment_borrower
from tests.conftest import make_borrower


def test_willing_but_delayed():
    b = make_borrower(days_past_due=8, prior_late_payments=1,
                      promises_made=1, promises_kept=1)
    seg, reasons = segment_borrower(b)
    assert seg == Segment.WILLING_BUT_DELAYED
    assert reasons  # always explainable


def test_habitual_late_payer():
    b = make_borrower(days_past_due=20, prior_late_payments=6)
    seg, _ = segment_borrower(b)
    assert seg == Segment.HABITUAL_LATE_PAYER


def test_hardship_case():
    b = make_borrower(hardship_indicator=True)
    seg, _ = segment_borrower(b)
    assert seg == Segment.HARDSHIP_CASE


def test_unresponsive():
    b = make_borrower(
        days_past_due=40,
        contact_history=[
            ContactAttempt(channel="sms", responded=False, hour=9),
            ContactAttempt(channel="call", responded=False, hour=15),
        ],
    )
    seg, _ = segment_borrower(b)
    assert seg == Segment.UNRESPONSIVE


def test_high_risk_escalation_by_dpd():
    b = make_borrower(days_past_due=120)
    seg, _ = segment_borrower(b)
    assert seg == Segment.HIGH_RISK_ESCALATION


def test_high_risk_escalation_by_balance_no_response():
    b = make_borrower(
        days_past_due=40,
        overdue_amount=65000.0,
        contact_history=[ContactAttempt(channel="call", responded=False, hour=10)],
    )
    seg, _ = segment_borrower(b)
    assert seg == Segment.HIGH_RISK_ESCALATION


def test_hardship_wins_tiebreaker_over_high_dpd():
    """Borrower-protective: hardship beats high-risk escalation even at high DPD."""
    b = make_borrower(days_past_due=150, hardship_indicator=True)
    seg, _ = segment_borrower(b)
    assert seg == Segment.HARDSHIP_CASE


def test_zero_overdue_goes_to_manual_review():
    b = make_borrower(days_past_due=0, overdue_amount=0.0)
    seg, reasons = segment_borrower(b)
    assert seg == Segment.MANUAL_REVIEW
    assert any("No genuine delinquency" in r for r in reasons)


def test_ambiguous_goes_to_manual_review():
    """Mid DPD, no contact history, no clear pattern -> manual review, not a guess."""
    b = make_borrower(days_past_due=45, prior_late_payments=1, contact_history=[])
    seg, _ = segment_borrower(b)
    assert seg == Segment.MANUAL_REVIEW


def test_every_segment_always_has_reasons():
    for b in [
        make_borrower(hardship_indicator=True),
        make_borrower(days_past_due=200),
        make_borrower(days_past_due=0, overdue_amount=0),
    ]:
        _, reasons = segment_borrower(b)
        assert len(reasons) >= 1
