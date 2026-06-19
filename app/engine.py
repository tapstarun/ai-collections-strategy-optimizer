"""Orchestration: combine segmentation + strategy into a single Strategy result.

Keeps the API layer thin. Message generation is attached separately (Step 6) so this
stays a pure, deterministic, easily-tested composition of the decision engine.
"""
from __future__ import annotations

from .message_gen import generate_message
from .models import Borrower, Explanation, Strategy
from .segmentation import segment_borrower
from .strategy import (
    best_channel_and_time,
    recommend_action,
    recovery_probability,
)


def build_strategy(borrower: Borrower, with_message: bool = True) -> Strategy:
    """Run the full deterministic pipeline, then attach a safe customer message.

    `with_message=False` skips message generation (faster for the workload queue,
    which only needs the decision, not a drafted message).
    """
    segment, seg_reasons = segment_borrower(borrower)
    action, action_reasons = recommend_action(borrower, segment)
    channel, window, channel_reasons = best_channel_and_time(borrower)
    recovery, recovery_reasons = recovery_probability(borrower, segment)

    reasons = seg_reasons + action_reasons + channel_reasons + recovery_reasons

    message = source = None
    if with_message:
        message, source = generate_message(borrower, segment, action)

    return Strategy(
        borrower_id=borrower.borrower_id,
        segment=segment,
        next_best_action=action,
        best_channel=channel,
        best_time=window,
        recovery_probability=recovery,
        reasons=reasons,
        message_draft=message,
        message_source=source,
    )


def build_explanation(borrower: Borrower) -> Explanation:
    """Answer 'Why is this borrower assigned to X?' using the same rule outputs."""
    segment, seg_reasons = segment_borrower(borrower)
    action, action_reasons = recommend_action(borrower, segment)
    return Explanation(
        borrower_id=borrower.borrower_id,
        segment=segment,
        next_best_action=action,
        reasons=seg_reasons + action_reasons,
    )
