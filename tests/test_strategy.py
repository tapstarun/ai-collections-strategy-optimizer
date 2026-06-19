"""Tests for the deterministic strategy / next-best-action engine."""
from __future__ import annotations

from app.models import Channel, ContactAttempt, NextBestAction, Segment
from app.strategy import (
    best_channel_and_time,
    priority_score,
    recommend_action,
    recovery_probability,
)
from tests.conftest import make_borrower


def test_action_maps_per_segment():
    cases = {
        Segment.HARDSHIP_CASE: NextBestAction.HARDSHIP_SUPPORT,
        Segment.UNRESPONSIVE: NextBestAction.AGENT_CALL,
        Segment.HIGH_RISK_ESCALATION: NextBestAction.ESCALATION,
        Segment.MANUAL_REVIEW: NextBestAction.MANUAL_REVIEW,
        Segment.HABITUAL_LATE_PAYER: NextBestAction.SMS_REMINDER,
    }
    b = make_borrower()
    for seg, expected in cases.items():
        action, reasons = recommend_action(b, seg)
        assert action == expected
        assert reasons


def test_large_balance_willing_gets_payment_plan():
    b = make_borrower(overdue_amount=20000.0)
    action, _ = recommend_action(b, Segment.WILLING_BUT_DELAYED)
    assert action == NextBestAction.PAYMENT_PLAN_OFFER


def test_small_balance_willing_gets_sms():
    b = make_borrower(overdue_amount=3000.0)
    action, _ = recommend_action(b, Segment.WILLING_BUT_DELAYED)
    assert action == NextBestAction.SMS_REMINDER


def test_best_channel_learned_from_history():
    b = make_borrower(
        preferred_channel="sms",
        contact_history=[
            ContactAttempt(channel="email", responded=True, hour=19),
            ContactAttempt(channel="email", responded=True, hour=21),
            ContactAttempt(channel="call", responded=False, hour=10),
        ],
    )
    channel, window, reasons = best_channel_and_time(b)
    assert channel == Channel.EMAIL  # learned, overrides preference
    assert window == "20:00-22:00"  # avg of 19 & 21 = 20
    assert reasons


def test_best_channel_falls_back_to_preference():
    b = make_borrower(preferred_channel="call", contact_history=[])
    channel, window, _ = best_channel_and_time(b)
    assert channel == Channel.CALL
    assert window == "10:00-12:00"


def test_recovery_probability_bounds_and_explainability():
    b = make_borrower()
    score, reasons = recovery_probability(b, Segment.WILLING_BUT_DELAYED)
    assert 0 <= score <= 100
    assert len(reasons) >= 2  # always explainable


def test_recovery_higher_for_promise_keeper_than_breaker():
    keeper = make_borrower(promises_made=4, promises_kept=4)
    breaker = make_borrower(promises_made=4, promises_kept=0)
    s_keep, _ = recovery_probability(keeper, Segment.WILLING_BUT_DELAYED)
    s_break, _ = recovery_probability(breaker, Segment.WILLING_BUT_DELAYED)
    assert s_keep > s_break


def test_recovery_lower_for_deep_delinquency():
    fresh = make_borrower(days_past_due=10)
    deep = make_borrower(days_past_due=120)
    s_fresh, _ = recovery_probability(fresh, Segment.WILLING_BUT_DELAYED)
    s_deep, _ = recovery_probability(deep, Segment.HIGH_RISK_ESCALATION)
    assert s_fresh > s_deep


def test_priority_score_is_expected_value():
    assert priority_score(50, 10000.0) == 5000.0
    assert priority_score(0, 99999.0) == 0.0
    assert priority_score(100, 2000.0) == 2000.0
